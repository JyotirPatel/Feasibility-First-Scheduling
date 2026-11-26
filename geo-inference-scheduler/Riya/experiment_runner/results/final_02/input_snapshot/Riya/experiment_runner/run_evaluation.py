"""Reproducible simulator evaluation, parallel runs and explicit ablations."""

import argparse
import os

# Prevent a small matrix operation from spawning a BLAS pool in every worker.
for _key in ["OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"]:
    os.environ[_key] = "1"
from concurrent.futures import ProcessPoolExecutor, as_completed
import platform
import time
import hashlib
import json
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
import numpy as np
import pandas as pd

RIYA = Path(__file__).resolve().parents[1]
ROOT = RIYA.parent
# Explicit paths handle the uploaded nested tree without modifying teammates.
for folder in [ROOT / "Sur", ROOT / "Jyotir", ROOT / "Parikshit", RIYA / "metrics"]:
    sys.path.insert(0, str(folder))
candidates = [ROOT / "Krupesh", ROOT / "Krupesh/geo-inference-scheduler/Krupesh"]
KR = next((p for p in candidates if (p / "router_service/engine.py").exists()), None)
if KR is None:
    raise RuntimeError("Cannot locate Krupesh router")
sys.path.append(str(KR))
from integration import jyotir_adapter

jyotir_adapter.JYOTIR_DIR = ROOT / "Jyotir"
from router_plugin import register, make_reward_fn
from router_service.registry import build_policy, build_filter
from router_service.engine import RoutingEngine, RunMeta
from simulator.cluster import Simulation
from simulator.config import load_cluster, load_scenario, load_workload
from simulator.events import change_times
from simulator.routers import KrupeshRouter
from recovery import recovery_metrics, goodput_curve
from summarize_results import summarize
from decision_log.writer import DecisionLogWriter, validate_log
from evaluate_log import evaluate


def dump(path, obj):
    path.write_text(
        json.dumps(obj, indent=2, allow_nan=False, default=str), encoding="utf-8"
    )


GENERATED_DIRS = {
    "results",
    "plans",
    "baseline_logs",
    "input_snapshot",
    "runs",
    "checkpoints",
    "__pycache__",
    ".git",
    ".venv",
}


def source_files(root=ROOT):
    return sorted(
        p
        for owner in ["Riya", "Krupesh", "Jyotir", "Sur", "Parikshit"]
        for p in (root / owner).rglob("*")
        if p.is_file()
        and (
            p.suffix in {".py", ".yaml", ".yml", ".json", ".csv"}
            or p.name.endswith(".csv.gz")
        )
        and not any(
            x in GENERATED_DIRS or x.startswith("results_")
            for x in p.relative_to(root).parts
        )
    )


def source_info():
    files = source_files()
    manifest = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    }
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        "git_commit": commit,
        "source_sha256": manifest,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }


def resolve_policy(label, cfg):
    spec = cfg.get("policy_overrides", {}).get(label, {})
    return spec.get("implementation", label), spec.get(
        "filter", cfg.get("filter_name", "jyotir")
    )


def read_decision_log(folder):
    parquet = folder / "decision_log.parquet"
    return (
        pd.read_parquet(parquet)
        if parquet.exists()
        else pd.read_csv(folder / "decision_log.csv", low_memory=False)
    )


def run_one(policy, scenario, seed, cfg, folder):
    started = time.perf_counter()
    register()
    implementation, filter_name = resolve_policy(policy, cfg)
    if implementation == "reference:true_state":
        from true_state_reference import TrueStatePolicy

        model = TrueStatePolicy(seed=seed)
    else:
        model = build_policy(implementation, seed=seed)
    reward_cfg = model.config.reward if hasattr(model, "config") else None
    engine = RoutingEngine(
        policy=model,
        filter_fn=build_filter(filter_name),
        reward_fn=make_reward_fn(reward_cfg),
        meta=RunMeta(f"{scenario}__{policy}__s{seed}", seed, scenario, policy),
        writer=DecisionLogWriter(
            folder / ("decision_log." + cfg.get("log_format", "parquet"))
        ),
        audit_fn=build_filter("jyotir"),
    )
    trace = load_scenario(scenario)
    duration = trace.duration_s
    workload = load_workload()
    if cfg.get("rate_rps") is not None:
        workload = workload.model_copy(update={"rate_rps": cfg["rate_rps"]})
    cluster_config = load_cluster(cfg["nodes"])
    dump(
        folder / "resolved_inputs.json",
        {
            "scenario": trace.model_dump(),
            "cluster": cluster_config.model_dump(),
            "workload": workload.model_dump(),
            "policy_config": model.config.model_dump()
            if hasattr(getattr(model, "config", None), "model_dump")
            else None,
        },
    )
    adapter = KrupeshRouter(engine)
    cluster = Simulation(
        adapter, trace, seed, cluster=cluster_config, workload=workload
    )
    if implementation == "reference:true_state":
        from true_state_reference import attach_reference

        attach_reference(adapter, cluster, model)
    simulation_stats = cluster.run()
    dump(folder / "simulation_stats.json", simulation_stats)
    engine.finish()
    df = engine.writer.close()
    # Metrics always read the persisted authoritative log.
    df = read_decision_log(folder)
    problems = validate_log(df)
    if problems:
        raise ValueError(str(problems))
    if "true_state_violation" not in df:
        raise ValueError("Simulator independent safety annotations are missing")
    result = evaluate(df, duration)
    result.update(
        policy=policy,
        scenario=scenario,
        seed=seed,
        implementation=implementation,
        filter_name=filter_name,
    )
    if hasattr(model, "stats"):
        dump(folder / "policy_stats.json", dict(model.stats))
        if model.stats.get("reward_mismatch", 0):
            raise ValueError("Router and policy rewards disagree")
    result.update(
        simulator="Parikshit/simulator (SimPy)",
        nodes=cfg["nodes"],
        goodput_convention="arrival-time bins; drained outcomes attributed to arrival",
    )
    # Workload fingerprint must match across policies for the same trace and seed.
    workload_cols = [
        "request_id",
        "t_arrival",
        "user_region",
        "model",
        "slo_class",
        "ttft_slo_ms",
        "input_tokens",
        "expected_output_tokens",
    ]
    fingerprint = (
        df[workload_cols].sort_values("request_id").to_csv(index=False).encode("utf-8")
    )
    result["workload_sha256"] = hashlib.sha256(fingerprint).hexdigest()
    curve = goodput_curve(df, duration)
    curve.to_csv(folder / "goodput_curve.csv", index=False)
    anchors = change_times(trace)
    event_rows = []
    affected_nodes = sorted(
        {e.node for e in trace.events if getattr(e, "node", None) is not None}
    )
    for anchor, t0 in anchors.items():
        event_rows.append(
            recovery_metrics(
                df, curve, t0, anchor, affected_nodes, control=scenario == "s1_stable"
            )
        )
    dump(
        folder / "events.json",
        {
            "anchors": anchors,
            "events": [e.model_dump() for e in trace.events],
            "actual_events": cluster.event_log,
        },
    )
    dump(folder / "recovery.json", event_rows)
    result["recovery_status"] = "see recovery.json (S1 is a control diagnostic)"
    result["wall_s"] = round(time.perf_counter() - started, 3)
    dump(folder / "metrics.json", result)
    return result


def bundle_hashes(folder):
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.iterdir())
        if p.is_file() and p.name not in {"status.json", "error.txt"}
    }


def verify_cached(folder):
    saved = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    expected = saved.get("bundle_sha256", {})
    if not expected or any(
        not (folder / n).is_file()
        or hashlib.sha256((folder / n).read_bytes()).hexdigest() != h
        for n, h in expected.items()
    ):
        raise ValueError(f"Cached bundle incomplete or modified: {folder}")
    return json.loads((folder / "metrics.json").read_text(encoding="utf-8"))


def execute_task(task):
    policy, scenario, seed, cfg, folder_string = task
    folder = Path(folder_string)
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "policy": policy,
        "scenario": scenario,
        "seed": seed,
        "simulator": "parikshit",
        "nodes": cfg["nodes"],
        "duration_s": load_scenario(scenario).duration_s,
        "rate_rps": cfg.get("rate_rps"),
    }
    dump(folder / "config.json", {**cfg, **meta})
    dump(folder / "status.json", {**meta, "status": "running"})
    try:
        result = run_one(policy, scenario, seed, cfg, folder)
        dump(
            folder / "status.json",
            {**meta, "status": "ok", "bundle_sha256": bundle_hashes(folder)},
        )
        return {**result, "status": "ok"}
    except Exception as exc:
        dump(folder / "status.json", {**meta, "status": "failed", "error": str(exc)})
        (folder / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return {**meta, "status": "failed", "error": str(exc)}


def validate_config(cfg):
    if (
        cfg.get("simulator") != "parikshit"
        or cfg.get("goodput_time_basis") != "arrival"
    ):
        raise ValueError("Use the Parikshit simulator with arrival-time goodput")
    if cfg.get("nodes") not in [5, 10]:
        raise ValueError("nodes must be 5 or 10")
    rate = cfg.get("rate_rps")
    if rate is not None and (not np.isfinite(rate) or rate <= 0):
        raise ValueError("Invalid rate_rps")
    if cfg.get("log_format", "parquet") not in ["parquet", "csv"]:
        raise ValueError("Unsupported log format")
    for name in ["policies", "scenarios", "seeds"]:
        if not cfg[name] or len(cfg[name]) != len(set(cfg[name])):
            raise ValueError(f"Empty/duplicate {name}")
    for seed in cfg["seeds"]:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("Seeds must be nonnegative integers")
    for label in cfg["policies"]:
        _, f = resolve_policy(label, cfg)
        if f not in ["jyotir", "none"]:
            raise ValueError(f"Unsupported filter: {f}")
    for scenario in cfg["scenarios"]:
        load_scenario(scenario)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--config", default=str(Path(__file__).with_name("config_final.json"))
    )
    ap.add_argument("--output", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    if a.workers < 1 or (a.limit is not None and a.limit < 1):
        raise ValueError("workers/limit must be positive")
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    validate_config(cfg)
    out = Path(a.output).resolve()
    if out.exists() and not a.resume:
        raise FileExistsError("Use a new output directory or --resume")
    out.mkdir(parents=True, exist_ok=True)
    provenance = source_info()
    if (out / "config.json").exists():
        if (
            json.loads((out / "config.json").read_text(encoding="utf-8")) != cfg
            or json.loads((out / "source.json").read_text(encoding="utf-8"))
            != provenance
        ):
            raise ValueError("Config/source/environment changed; choose a new bundle")
    dump(out / "config.json", cfg)
    dump(out / "source.json", provenance)
    # Copy only reproducibility inputs; never include generated baseline logs.
    for relative in provenance["source_sha256"]:
        original = ROOT / relative
        target = out / "input_snapshot" / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
    tasks = []
    rows = []
    for policy in cfg["policies"]:
        for scenario in cfg["scenarios"]:
            for seed in cfg["seeds"]:
                if a.limit is not None and len(tasks) + len(rows) >= a.limit:
                    continue
                folder = out / policy.replace(":", "-") / scenario / f"seed_{seed}"
                if (
                    a.resume
                    and (folder / "status.json").exists()
                    and json.loads(
                        (folder / "status.json").read_text(encoding="utf-8")
                    ).get("status")
                    == "ok"
                ):
                    rows.append({**verify_cached(folder), "status": "ok"})
                else:
                    tasks.append((policy, scenario, seed, cfg, str(folder)))
    total = len(tasks) + len(rows)
    done = len(rows)
    print(f"{total} selected runs, {done} cached, {a.workers} workers", flush=True)
    if a.workers == 1:
        iterator = map(execute_task, tasks)
        for row in iterator:
            rows.append(row)
            done += 1
            pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)
            print(
                f"{done}/{total}: {row['policy']} {row['scenario']} seed={row['seed']}: {row['status']}",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            futures = [pool.submit(execute_task, t) for t in tasks]
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                done += 1
                pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)
                print(
                    f"{done}/{total}: {row['policy']} {row['scenario']} seed={row['seed']}: {row['status']}",
                    flush=True,
                )
    # Reference loss is computed post hoc only after all paired reference curves exist.
    if "reference:true_state" in cfg["policies"]:
        from finalize_reference import finalize_reference

        finalize_reference(out)
    summarize(out)
    if any(r["status"] != "ok" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
