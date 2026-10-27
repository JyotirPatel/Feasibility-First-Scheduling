"""
Window-size sweep and exploration check — owner: Sur

Runs sliding-window LinUCB for every window size W and window mode, plain
LinUCB, an alpha check, and (as a sanity reference) Jyotir's baselines, on
every scenario × seed in sweep.yaml, and writes a result bundle:

  results/runs.csv         one row per run: its settings and metrics
  results/summary.csv      per policy setting × scenario: mean and 95% bootstrap CI over seeds
  results/curves.csv.gz    mean smoothed goodput G(t) per policy setting × scenario (for the figures)
  results/manifest.json    git commit, config hashes, versions, command — to reproduce the bundle
  results/raw/             full decision logs, only with --save-logs (kept out of git)
  ../checkpoints/standin/  learned state of the default bandits (the `checkpoints:` runs)

Figures are made from this bundle only, by make_figures.py.

Usage, from the Sur/ folder:
  python3 window_sweep/run_sweep.py            # the full sweep in sweep.yaml
  python3 window_sweep/run_sweep.py --quick    # a fast smoke run, written to results_quick/

Until Parikshit's simulator exists this runs on the stand-in in standins/, so
its numbers are preliminary.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import subprocess
import sys
import time
import zlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

_HERE = os.path.dirname(os.path.abspath(__file__))
_SUR_DIR = os.path.dirname(_HERE)
_JYOTIR_DIR = os.path.join(os.path.dirname(_SUR_DIR), "Jyotir")
for _path in (_SUR_DIR, _JYOTIR_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import baselines as jyotir_baselines  # noqa: E402
from linucb import LinUCB  # noqa: E402
from sliding_window_linucb import SlidingWindowLinUCB  # noqa: E402
from standins.adaptation import adaptation_time, deepest_dip, goodput_series, smooth, steady_level  # noqa: E402
from standins.toy_cluster import SCENARIOS, ClusterConfig, change_times, load_cluster_config, simulate  # noqa: E402

POLICY_DIR = os.path.join(_SUR_DIR, "configs", "policies")
DEFAULT_SWEEP = os.path.join(_HERE, "sweep.yaml")
CHECKPOINT_DIR = os.path.join(_SUR_DIR, "checkpoints", "standin")


# ── Sweep config ─────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WindowSweepSpec(_Strict):
    sizes: list[int] = Field(min_length=1)
    extended_sizes: list[int]
    modes: list[str] = Field(min_length=1)
    include_plain_linucb: bool


class AlphaWindow(_Strict):
    size: int = Field(gt=0)
    mode: str


class AlphaSpec(_Strict):
    alphas: list[float] = Field(min_length=1)
    window: AlphaWindow
    scenarios: list[str]


class CheckpointSpec(_Strict):
    scenarios: list[str]
    seed: int


class BootstrapSpec(_Strict):
    resamples: int = Field(gt=0)
    confidence: float = Field(gt=0, lt=1)
    seed: int


class MetricsSpec(_Strict):
    bin_s: float = Field(gt=0)
    smooth_s: float = Field(gt=0)
    steady_from_s: float = Field(ge=0)
    steady_to_s: float = Field(gt=0)
    fraction: float = Field(gt=0, le=1)
    hold_s: float = Field(gt=0)
    dip_until_s: float = Field(gt=0)
    before_s: float = Field(gt=0)
    rush_share: float = Field(gt=0, le=1)
    abandoned_below_share: float = Field(gt=0, lt=1)
    bootstrap: BootstrapSpec


class QuickSpec(_Strict):
    seeds: int = Field(gt=0)
    scenarios: list[str] = Field(min_length=1)
    sizes: list[int] = Field(min_length=1)
    alphas: list[float] = Field(min_length=1)
    baselines: list[str]


class SweepConfig(_Strict):
    seeds: list[int] = Field(min_length=1)
    scenarios: list[str] = Field(min_length=1)
    window_sweep: WindowSweepSpec
    alpha_check: AlphaSpec
    baselines: list[str]
    checkpoints: CheckpointSpec
    metrics: MetricsSpec
    quick: QuickSpec
    workers: int = Field(ge=0)


def load_sweep_config(path: str = DEFAULT_SWEEP) -> SweepConfig:
    with open(path) as f:
        cfg = SweepConfig.model_validate(yaml.safe_load(f))
    named = (
        set(cfg.scenarios) | set(cfg.alpha_check.scenarios) | set(cfg.checkpoints.scenarios) | set(cfg.quick.scenarios)
    )
    unknown = sorted(named - set(SCENARIOS))
    if unknown:
        raise ValueError(f"unknown scenarios {unknown}")
    for mode in [*cfg.window_sweep.modes, cfg.alpha_check.window.mode]:
        if mode not in ("per_node", "global"):
            raise ValueError(f"unknown window mode {mode!r}")
    missing = [b for b in cfg.baselines + cfg.quick.baselines if not hasattr(jyotir_baselines, b)]
    if missing:
        raise ValueError(f"unknown baselines {missing}")
    return cfg


# ── Jobs ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Job:
    family: str  # "sw_linucb" | "linucb" | "baseline"
    scenario: str
    seed: int
    mode: str | None = None
    window: int | None = None
    alpha: float | None = None
    baseline: str | None = None
    checkpoint: bool = False

    @property
    def label(self) -> str:
        if self.family == "sw_linucb":
            return f"sw_linucb[{self.mode},W={self.window},alpha={self.alpha:g}]"
        if self.family == "linucb":
            return f"linucb[alpha={self.alpha:g}]"
        return f"baseline:{self.baseline}"

    @property
    def key(self) -> tuple:
        return (self.family, self.mode, self.window, self.alpha, self.baseline, self.scenario, self.seed)


def build_jobs(cfg: SweepConfig, quick: bool = False) -> list[Job]:
    """Every run in the sweep, each exactly once (the alpha check reuses window-sweep runs)."""
    seeds, scenarios = cfg.seeds, cfg.scenarios
    sizes = cfg.window_sweep.sizes + cfg.window_sweep.extended_sizes
    alphas, baseline_names = cfg.alpha_check.alphas, cfg.baselines
    alpha_scenarios = cfg.alpha_check.scenarios
    if quick:  # the smoke-run subset, from the `quick:` section of sweep.yaml
        q = cfg.quick
        seeds, scenarios, sizes, alphas, baseline_names = seeds[: q.seeds], q.scenarios, q.sizes, q.alphas, q.baselines
        alpha_scenarios = [s for s in alpha_scenarios if s in scenarios]

    default_alpha = _policy_yaml("sw_linucb.yaml")["alpha"]
    jobs: dict[tuple, Job] = {}

    def add(job: Job) -> None:
        old = jobs.get(job.key)
        jobs[job.key] = job if old is None else Job(**{**asdict(old), "checkpoint": old.checkpoint or job.checkpoint})

    ck = cfg.checkpoints
    for scenario in scenarios:
        for seed in seeds:
            for mode in cfg.window_sweep.modes:
                for size in sizes:
                    add(Job("sw_linucb", scenario, seed, mode=mode, window=size, alpha=default_alpha))
            if cfg.window_sweep.include_plain_linucb:
                add(
                    Job(
                        "linucb",
                        scenario,
                        seed,
                        alpha=default_alpha,
                        checkpoint=scenario in ck.scenarios and seed == ck.seed,
                    )
                )
            for name in baseline_names:
                add(Job("baseline", scenario, seed, baseline=name))
            # the default sliding-window policy also gets a checkpoint
            default = _policy_yaml("sw_linucb.yaml")["window"]
            add(
                Job(
                    "sw_linucb",
                    scenario,
                    seed,
                    mode=default["mode"],
                    window=default["size"],
                    alpha=default_alpha,
                    checkpoint=scenario in ck.scenarios and seed == ck.seed,
                )
            )
    for scenario in alpha_scenarios:
        for seed in seeds:
            for alpha in alphas:
                add(
                    Job(
                        "sw_linucb",
                        scenario,
                        seed,
                        mode=cfg.alpha_check.window.mode,
                        window=cfg.alpha_check.window.size,
                        alpha=float(alpha),
                    )
                )
    return list(jobs.values())


def _policy_yaml(name: str) -> dict:
    with open(os.path.join(POLICY_DIR, name)) as f:
        return yaml.safe_load(f)


def make_policy(job: Job):
    if job.family == "sw_linucb":
        cfg = _policy_yaml("sw_linucb.yaml")
        cfg["window"]["size"], cfg["window"]["mode"], cfg["alpha"] = job.window, job.mode, job.alpha
        return SlidingWindowLinUCB(cfg, seed=job.seed)
    if job.family == "linucb":
        cfg = _policy_yaml("linucb.yaml")
        cfg["alpha"] = job.alpha
        return LinUCB(cfg, seed=job.seed)
    cls = getattr(jyotir_baselines, job.baseline)
    return cls(seed=job.seed) if job.baseline == "PowerOfTwo" else cls()


# ── One run ──────────────────────────────────────────────────────────────────


def run_job(args: tuple) -> tuple[dict, np.ndarray]:
    job, cluster_dict, metrics_dict, raw_dir, checkpoint_dir = args
    cluster = ClusterConfig.model_validate(cluster_dict)
    metrics = MetricsSpec.model_validate(metrics_dict)
    policy = make_policy(job)
    run_id = f"{job.label}|{job.scenario}|seed={job.seed}"

    started = time.perf_counter()
    result = simulate(
        policy,
        job.scenario,
        job.seed,
        cluster=cluster,
        policy_name=job.label,
        run_id=run_id,
        details=raw_dir is not None,
    )
    runtime = time.perf_counter() - started

    row, curve = compute_metrics(result, cluster, job.scenario, metrics)
    row = {**asdict(job), "label": job.label, **row, "runtime_s": runtime}
    stats = result.stats.get("policy_stats", {})
    row["ignored_feedback"] = stats.get("ignored_feedback", 0)
    row["dropped_pending"] = stats.get("dropped_pending", 0)

    if raw_dir is not None:
        os.makedirs(raw_dir, exist_ok=True)
        result.to_csv(os.path.join(raw_dir, _safe_name(run_id) + ".csv.gz"))
    if job.checkpoint and checkpoint_dir is not None and hasattr(policy, "save_checkpoint"):
        name = _safe_name(f"{job.label}_{job.scenario}_seed{job.seed}") + ".npz"
        policy.save_checkpoint(os.path.join(checkpoint_dir, name))
    return row, curve


def compute_metrics(result, cluster: ClusterConfig, scenario: str, m: MetricsSpec) -> tuple[dict, np.ndarray]:
    t_arrival = np.asarray(result.column("t_arrival"), dtype=float)
    met = np.asarray(result.column("slo_met"), dtype=bool)
    routed = np.asarray([d == "route" for d in result.column("decision")])
    ttft = np.asarray([np.nan if v is None else v for v in result.column("ttft_ms")], dtype=float)
    cost = np.asarray(result.column("cost_usd"), dtype=float)
    energy = np.asarray(result.column("energy_kwh"), dtype=float)

    G = smooth(goodput_series(t_arrival, met, cluster.duration_s, m.bin_s), max(int(round(m.smooth_s / m.bin_s)), 1))
    n_good = max(int(met.sum()), 1)
    served = ttft[routed & np.isfinite(ttft)]
    t0_bin = int(round(cluster.t0_s / m.bin_s))
    before = max(t0_bin - int(round(m.before_s / m.bin_s)), 0)

    row = {
        "requests": int(len(met)),
        "slo_rate": float(met.mean()),
        "rejection_rate": float(1.0 - routed.mean()),
        "failed": int(result.stats["failed"]),
        "hard_rule_violations": int(result.stats["hard_rule_violations"]),
        "goodput_mean": float(G.mean()),
        "goodput_before": float(G[before:t0_bin].mean()),
        "cost_per_good_usd": float(cost.sum() / n_good),
        "energy_per_good_kwh": float(energy.sum() / n_good),
        "ttft_p95_ms": float(np.percentile(served, 95)) if served.size else float("nan"),
        "ttft_p99_ms": float(np.percentile(served, 99)) if served.size else float("nan"),
    }
    for anchor, t_anchor in change_times(cluster, scenario).items():
        prefix = "" if anchor == "t0" else f"{anchor}_"
        try:
            steady_level(G, t_anchor, m.bin_s, m.steady_from_s, m.steady_to_s)
        except ValueError:  # the steady window does not fit in this (shortened) run
            continue
        adapt, g_star = adaptation_time(
            G,
            t_anchor,
            bin_s=m.bin_s,
            steady_from_s=m.steady_from_s,
            steady_to_s=m.steady_to_s,
            fraction=m.fraction,
            hold_s=m.hold_s,
        )
        a, b = int(round(t_anchor / m.bin_s)), int(round((t_anchor + m.steady_to_s) / m.bin_s))
        row[prefix + "adaptation_s"] = float("nan") if adapt is None else float(adapt)
        row[prefix + "recovered"] = adapt is not None
        row[prefix + "g_star"] = g_star
        row[prefix + "deepest_dip"] = deepest_dip(G, t_anchor, bin_s=m.bin_s, until_s=m.dip_until_s)
        # supplementary: seconds spent below fraction·G* in [t_anchor, t_anchor + steady_to_s)
        row[prefix + "degraded_s"] = float(np.sum(G[a:b] < m.fraction * g_star) * m.bin_s)
    if scenario == "s6_outage_recovery":
        row.update(_returning_node_metrics(result, cluster, m, t_arrival, routed))
    return row, G.astype(np.float32)


def _returning_node_metrics(result, cluster: ClusterConfig, m: MetricsSpec, t_arrival, routed) -> dict:
    """
    S6 only — how the policy treats the node that went down and came back:
      return_node_share_before  its share of routed requests in the before_s seconds before t0
      return_node_share_after   its share after it has finished warming up, to the end of the run
      return_rush_s             seconds from its return in which it got >= rush_share of all requests
    """
    o = cluster.scenarios.s6_outage_recovery
    to_node = routed & (np.asarray(result.column("node_id"), dtype=object) == o.node)

    def share(a: float, b: float) -> float:
        span = routed & (t_arrival >= a) & (t_arrival < b)
        return float(to_node[span].sum() / span.sum()) if span.any() else float("nan")

    rush = 0.0
    t = o.return_s
    while t < cluster.duration_s and share(t, t + m.bin_s) >= m.rush_share:
        rush += m.bin_s
        t += m.bin_s
    return {
        "return_node_share_before": share(cluster.t0_s - m.before_s, cluster.t0_s),
        "return_node_share_after": share(o.return_s + o.warmup_s, cluster.duration_s),
        "return_rush_s": rush,
    }


def _safe_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_.=" else "_" for c in text)


# ── Aggregation ──────────────────────────────────────────────────────────────

SUMMARY_METRICS = (
    "slo_rate",
    "goodput_mean",
    "goodput_before",
    "rejection_rate",
    "cost_per_good_usd",
    "energy_per_good_kwh",
    "ttft_p95_ms",
    "ttft_p99_ms",
    "g_star",
    "deepest_dip",
    "degraded_s",
    "return_g_star",
    "return_deepest_dip",
    "return_degraded_s",
    "return_node_share_before",
    "return_node_share_after",
    "return_rush_s",
)
GROUP_KEYS = ("label", "family", "mode", "window", "alpha", "baseline", "scenario")


def bootstrap_ci(values, resamples: int, confidence: float, rng: np.random.Generator) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean."""
    v = np.asarray([x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x))], dtype=float)
    if v.size == 0:
        return float("nan"), float("nan")
    if v.size == 1:
        return float(v[0]), float(v[0])
    means = rng.choice(v, size=(resamples, v.size), replace=True).mean(axis=1)
    tail = (1 - confidence) / 2
    return float(np.quantile(means, tail)), float(np.quantile(means, 1 - tail))


def _ci_rng(seed: int, group: tuple, metric: str) -> np.random.Generator:
    """
    One fixed random stream per (policy setting, scenario, metric), so a metric's
    CI never changes because another metric was added or removed. crc32 (not
    Python's hash) because it is the same in every process.
    """
    key = zlib.crc32("|".join(map(str, (*group, metric))).encode())
    return np.random.default_rng([seed, key])


def aggregate(rows: list[dict], m: MetricsSpec) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(tuple(r[k] for k in GROUP_KEYS), []).append(r)
    summary = []
    for key in sorted(groups, key=lambda k: tuple("" if x is None else str(x) for x in k)):
        runs = sorted(groups[key], key=lambda r: r["seed"])
        out = dict(zip(GROUP_KEYS, key, strict=True))
        out["seeds"] = len(runs)
        out["hard_rule_violations"] = int(sum(r["hard_rule_violations"] for r in runs))
        for name in SUMMARY_METRICS:
            values = [r[name] for r in runs if name in r]
            if not values:
                continue
            arr = np.asarray(values, dtype=float)
            out[name] = float(np.nanmean(arr)) if np.isfinite(arr).any() else float("nan")
            out[name + "_lo"], out[name + "_hi"] = bootstrap_ci(
                values, m.bootstrap.resamples, m.bootstrap.confidence, _ci_rng(m.bootstrap.seed, key, name)
            )
        for prefix in ("", "return_"):
            if prefix + "recovered" not in runs[0]:
                continue
            recovered = [r for r in runs if r[prefix + "recovered"]]
            out[prefix + "recovered_runs"] = len(recovered)
            times = [r[prefix + "adaptation_s"] for r in recovered]
            out[prefix + "adaptation_s"] = float(np.mean(times)) if times else float("nan")
            out[prefix + "adaptation_s_lo"], out[prefix + "adaptation_s_hi"] = bootstrap_ci(
                times,
                m.bootstrap.resamples,
                m.bootstrap.confidence,
                _ci_rng(m.bootstrap.seed, key, prefix + "adaptation_s"),
            )
        if "return_node_share_after" in runs[0]:
            # runs in which the returned node got (almost) nothing after it came back
            out["return_node_abandoned_runs"] = sum(
                r["return_node_share_after"] < m.abandoned_below_share for r in runs
            )
        summary.append(out)
    return summary


# ── Output ───────────────────────────────────────────────────────────────────


def write_csv(path: str, rows: list[dict]) -> None:
    columns: list[str] = []
    for r in rows:
        columns += [k for k in r if k not in columns]
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "wt", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def mean_curves(rows: list[dict], curves: list[np.ndarray], bin_s: float) -> list[dict]:
    groups: dict[tuple, list[np.ndarray]] = {}
    for r, c in zip(rows, curves, strict=True):
        groups.setdefault(tuple(r[k] for k in GROUP_KEYS), []).append(c)
    out = []
    for key, cs in groups.items():
        mean = np.mean(np.stack(cs), axis=0)
        base = dict(zip(GROUP_KEYS, key, strict=True))
        out += [{**base, "t_s": round(i * bin_s, 6), "goodput": round(float(g), 4)} for i, g in enumerate(mean)]
    return out


def manifest(args: argparse.Namespace, n_jobs: int, runtime: float, cluster_path: str) -> dict:
    def sha(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def git(*cmd):
        try:
            done = subprocess.run(["git", *cmd], cwd=_SUR_DIR, capture_output=True, text=True, timeout=20)
            return done.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    configs = [
        args.config,
        cluster_path,
        os.path.join(_JYOTIR_DIR, "feasibility_filter", "configs", "feasibility.yaml"),
        *(os.path.join(POLICY_DIR, f) for f in sorted(os.listdir(POLICY_DIR)) if f.endswith(".yaml")),
    ]
    repo_root = os.path.dirname(os.path.dirname(_SUR_DIR))
    status = git("status", "--porcelain")
    return {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": " ".join(["python3", os.path.relpath(__file__, _SUR_DIR), *sys.argv[1:]]),
        "git_commit": git("rev-parse", "HEAD"),
        "git_uncommitted_changes": bool(status) if status is not None else None,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "config_sha256": {os.path.relpath(p, repo_root): sha(p) for p in configs},
        "runs": n_jobs,
        "runtime_s": round(runtime, 1),
        "simulator": "Sur/standins/toy_cluster.py (stand-in; results are preliminary)",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_SWEEP, help="sweep settings (default: window_sweep/sweep.yaml)")
    ap.add_argument("--cluster", default=None, help="stand-in cluster config (default: standins/toy_cluster.yaml)")
    ap.add_argument("--out", default=None, help="output folder (default: window_sweep/results or results_quick)")
    ap.add_argument("--quick", action="store_true", help="fast smoke run: 2 seeds, 3 scenarios, 2 windows")
    ap.add_argument("--save-logs", action="store_true", help="also write every decision log to <out>/raw/")
    ap.add_argument("--workers", type=int, default=None, help="parallel processes (default: from sweep.yaml)")
    args = ap.parse_args(argv)

    cfg = load_sweep_config(args.config)
    cluster_path = args.cluster or os.path.join(_SUR_DIR, "standins", "toy_cluster.yaml")
    cluster = load_cluster_config(cluster_path)
    out = args.out or os.path.join(_HERE, "results_quick" if args.quick else "results")
    os.makedirs(out, exist_ok=True)
    raw_dir = os.path.join(out, "raw") if args.save_logs else None
    checkpoint_dir = None if args.quick else CHECKPOINT_DIR

    jobs = build_jobs(cfg, quick=args.quick)
    workers = args.workers if args.workers is not None else cfg.workers
    workers = workers or max((os.cpu_count() or 2) - 2, 1)
    payload = [(job, cluster.model_dump(), cfg.metrics.model_dump(), raw_dir, checkpoint_dir) for job in jobs]
    # Longest runs first (the S2 burst has the most requests) so the pool finishes evenly.
    payload.sort(key=lambda p: (p[0].scenario != "s2_traffic_burst", p[0].family == "baseline"))

    print(f"{len(jobs)} runs on {workers} processes -> {out}", flush=True)
    started = time.perf_counter()
    rows, curves = [], []
    with mp.get_context("spawn").Pool(workers) as pool:
        for i, (row, curve) in enumerate(pool.imap_unordered(run_job, payload), 1):
            rows.append(row)
            curves.append(curve)
            if i % 25 == 0 or i == len(payload):
                print(f"  {i}/{len(payload)} runs done ({time.perf_counter() - started:.0f} s)", flush=True)
    runtime = time.perf_counter() - started

    order = sorted(range(len(rows)), key=lambda i: (rows[i]["scenario"], rows[i]["label"], rows[i]["seed"]))
    rows, curves = [rows[i] for i in order], [curves[i] for i in order]
    write_csv(os.path.join(out, "runs.csv"), rows)
    write_csv(os.path.join(out, "summary.csv"), aggregate(rows, cfg.metrics))
    write_csv(os.path.join(out, "curves.csv.gz"), mean_curves(rows, curves, cfg.metrics.bin_s))
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest(args, len(jobs), runtime, cluster_path), f, indent=2)
    violations = sum(r["hard_rule_violations"] for r in rows)
    print(f"done in {runtime:.0f} s; hard-rule violations by filter-allowed nodes: {violations}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
