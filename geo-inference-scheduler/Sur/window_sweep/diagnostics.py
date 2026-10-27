"""
Sweep diagnostics — owner: Sur

Per-seed checks behind the statements in RESULTS.md. By default it shows how a
policy treats the node that went down and came back in S6:

  rush (s)        seconds from its return in which it got >= half of all requests
  peak queue      the largest queue the router saw at that node during [return, return + 30 s)
  share after     its share of requests after its warm-up ended
  lowest goodput  the deepest dip: the lowest goodput in the 120 s after its return
  mean goodput    over the whole run
  violations      hard-rule violations by nodes the filter allowed (Table G)

The rush, share and goodput numbers are computed by the sweep's own code with
the settings in sweep.yaml, so they equal the matching columns of runs.csv.

With --trace SEED it also prints, second by second after the return, the node's
share of requests, its queue, and the policy's estimate and bonus for it
against the best other node's score. A baseline has no estimate or bonus, so
those columns show nan.

With --counterfactual (per-node windows only) it checks why a per-node window
may stop using the node: when the node returns, it compares the policy's
estimate for it with what the same window would give without the outcomes of
requests lost in the outage. This reads the policy's internal window, so it is
a diagnostic, not part of the policy's interface.

With --load it instead reports how busy the stand-in cluster is in S1 (no
change): the mean and 95th-percentile share of all request slots in use, as
seen at each decision, and each node's share of the traffic.

With --metric-noise RATE it runs S1 (where nothing changes, so the right answer
is 0 s) with the arrival rate set to RATE requests/s and node capacities scaled
to match, and prints the adaptation time the frozen metric reports. A non-zero
value is random noise: use it to check the metric at the real simulator's rate.

With --fixed-filter every check runs on a what-if version of Jyotir's filter:
the bug that lets a warming node skip the model, memory, power and temperature
rules is fixed in memory, so a warming node must pass them like any other node.
filter.py is not changed. Use it to see how much of the S6 damage that bug causes.

Policies: plain | per_node:W | global:W | baseline:<name of one of Jyotir's baselines>

Usage (from the Sur/ folder):
  python3 window_sweep/diagnostics.py                                    # default policies, seeds 0-9
  python3 window_sweep/diagnostics.py --policy per_node:1000 --trace 0
  python3 window_sweep/diagnostics.py --policy per_node:1000 --counterfactual
  python3 window_sweep/diagnostics.py --policy plain --load --seeds 3
  python3 window_sweep/diagnostics.py --policy plain --policy baseline:StaticWeighted --metric-noise 25 --seeds 5
  python3 window_sweep/diagnostics.py --policy plain --policy global:1000 --fixed-filter
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SUR_DIR = os.path.dirname(_HERE)
_JYOTIR_DIR = os.path.join(os.path.dirname(_SUR_DIR), "Jyotir")
for _path in (_SUR_DIR, _JYOTIR_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import yaml  # noqa: E402

from linucb import LinUCB  # noqa: E402
from sliding_window_linucb import SlidingWindowLinUCB  # noqa: E402
from standins.adaptation import adaptation_time, goodput_series, smooth  # noqa: E402
from standins.toy_cluster import DEFAULT_CONFIG_PATH, ClusterConfig, load_cluster_config, simulate  # noqa: E402
from window_sweep.run_sweep import compute_metrics, load_sweep_config  # noqa: E402

DEFAULT_POLICIES = ("plain", "per_node:1000", "per_node:5000", "global:1000")
TRACE_SECONDS = 12
QUEUE_WINDOW_S = 30


def make(spec: str, seed: int):
    """'plain', '<per_node|global>:<W>' or 'baseline:<Name>'."""
    if spec == "plain":
        return LinUCB(seed=seed)
    if spec.startswith("baseline:"):
        import baselines

        cls = getattr(baselines, spec.split(":", 1)[1])
        return cls(seed=seed) if cls.__name__ == "PowerOfTwo" else cls()
    mode, size = spec.split(":")
    with open(os.path.join(_SUR_DIR, "configs", "policies", "sw_linucb.yaml")) as f:
        cfg = yaml.safe_load(f)
    cfg["window"]["mode"], cfg["window"]["size"] = mode, int(size)
    return SlidingWindowLinUCB(cfg, seed=seed)


@contextlib.contextmanager
def fixed_warming_rule():
    """
    What-if: Jyotir's filter with its warming-node bug fixed, in memory only.

    The real filter returns as soon as it sees status "warming" (rule 1 in
    filter.py), so a warming node skips the model, memory, power and temperature
    rules. Inside this block a warming node must pass them too, and is then
    allowed with its warming tag as before. filter.py is not changed, and the
    original rule is back when the block ends.
    """
    import feasibility_filter.filter as ff

    original = ff._check_node

    def check(request, node, config):
        if node.get("status") != "warming":
            return original(request, node, config)
        reason = original(request, {**node, "status": "up"}, config)
        return "node_warming" if reason is None else reason

    ff._check_node = check
    try:
        yield
    finally:
        ff._check_node = original


class _PassThrough:
    """Passes decisions and feedback on to a policy: one of Sur's bandits or one of Jyotir's baselines."""

    def __init__(self, inner):
        self.inner = inner
        # simulate() reads these; Jyotir's baselines have none of them, and simulate() has defaults for that
        self.name = getattr(inner, "name", type(inner).__name__)
        self.config = getattr(inner, "config", None)
        self.stats = getattr(inner, "stats", {})

    def choose(self, request, candidates):
        return self.inner.choose(request, candidates)

    def update(self, request, node_id, outcome):
        self.inner.update(request, node_id, outcome)


class _Watch(_PassThrough):
    """Records the returning node's queue, and the policy's estimate and bonus for it, at each decision."""

    def __init__(self, inner, node: str, start: float, stop: float):
        super().__init__(inner)
        self.node, self.start, self.stop = node, start, stop
        self.samples: list[tuple[float, int, float, float, float]] = []

    def choose(self, request, candidates):
        if self.start <= request["t_arrival"] < self.stop:
            mine = next((c for c in candidates if c["node_id"] == self.node), None)
            if mine is not None:
                estimate = bonus = best_other = float("nan")
                if hasattr(self.inner, "explain"):  # Sur's bandits; the baselines have no estimate or bonus
                    rows = {r["node_id"]: r for r in self.inner.explain(request, candidates)}
                    best_other = max((r["score"] for n, r in rows.items() if n != self.node), default=float("nan"))
                    estimate, bonus = rows[self.node]["estimate"], rows[self.node]["bonus"]
                self.samples.append((request["t_arrival"], mine["queue_len"], estimate, bonus, best_other))
        return self.inner.choose(request, candidates)


def _mean(samples: list[tuple], i: int) -> float:
    return sum(x[i] for x in samples) / len(samples) if samples else float("nan")


def diagnose(spec: str, seed: int, cluster: ClusterConfig) -> dict:
    o = cluster.scenarios.s6_outage_recovery
    watch = _Watch(make(spec, seed), o.node, o.return_s, o.return_s + QUEUE_WINDOW_S)
    result = simulate(watch, "s6_outage_recovery", seed, cluster=cluster, details=False)
    metrics, _ = compute_metrics(result, cluster, "s6_outage_recovery", load_sweep_config().metrics)
    routed = [r for r in result.rows if r["decision"] == "route"]

    def share(a, b):
        span = [r for r in routed if a <= r["t_arrival"] < b]
        return sum(r["node_id"] == o.node for r in span) / len(span) if span else float("nan")

    seconds = []
    for s in range(int(o.return_s), int(o.return_s) + TRACE_SECONDS):
        samples = [x for x in watch.samples if s <= x[0] < s + 1]
        met = sum(bool(r["slo_met"]) for r in routed if s <= r["t_arrival"] < s + 1)
        seconds.append((s, share(s, s + 1), *(_mean(samples, i) for i in (1, 2, 3, 4)), met))
    return {
        "rush_s": metrics["return_rush_s"],
        "peak_queue": max((x[1] for x in watch.samples), default=0),
        "share_after": metrics["return_node_share_after"],
        "lowest_goodput": metrics["return_deepest_dip"],
        "goodput_mean": metrics["goodput_mean"],
        "violations": result.stats["hard_rule_violations"],
        "trace": seconds,
    }


def counterfactual(spec: str, seed: int, cluster: ClusterConfig) -> dict:
    """Per-node window at the node's return: estimate with vs without the outcomes lost in the outage."""
    import math

    from linucb.linucb import _NodeModel

    o = cluster.scenarios.s6_outage_recovery
    inner = make(spec, seed)
    if getattr(inner, "window_mode", None) != "per_node":
        raise ValueError("--counterfactual needs a per-node window policy (per_node:W)")
    lost_x: set[int] = set()
    snap: dict = {}

    class Probe(_PassThrough):
        def choose(self, request, candidates):
            if not snap and request["t_arrival"] >= o.return_s:
                mine = next((c for c in candidates if c["node_id"] == o.node), None)
                if mine is not None:
                    snap["samples"] = list(inner._samples.get(o.node, []))
                    snap["x"] = inner.features.build(request, mine)
                    scores = {r["node_id"]: r["score"] for r in inner.explain(request, candidates)}
                    snap["best_other"] = max(v for k, v in scores.items() if k != o.node)
            return inner.choose(request, candidates)

        def update(self, request, node_id, outcome):
            if node_id == o.node and math.isinf(outcome.ttft_ms):  # lost when the node went down
                lost_x.add(id(inner._pending[str(request["request_id"])].x))
            inner.update(request, node_id, outcome)

    simulate(Probe(inner), "s6_outage_recovery", seed, cluster=cluster, details=False)
    samples = snap["samples"]
    lost = [id(x) in lost_x for x, _ in samples]
    with_lost, without = _NodeModel(inner.dim, inner.lam), _NodeModel(inner.dim, inner.lam)
    with_lost.rebuild(samples)
    without.rebuild([s for s, is_lost in zip(samples, lost, strict=True) if not is_lost])
    return {
        "window": len(samples),
        "lost_in_window": sum(lost),
        "last_lost_position": max((i + 1 for i, is_lost in enumerate(lost) if is_lost), default=0),
        "estimate_with": with_lost.estimate_and_bonus(snap["x"])[0],
        "estimate_without": without.estimate_and_bonus(snap["x"])[0],
        "best_other_score": snap["best_other"],
    }


def cluster_load(spec: str, seed: int, cluster: ClusterConfig) -> dict:
    """S1: share of all request slots in use at each decision, and each node's share of the traffic."""
    used: list[float] = []

    class Probe(_PassThrough):
        def choose(self, request, candidates):
            used.append(sum(c["running"] for c in candidates) / sum(c["capacity"] for c in candidates))
            return self.inner.choose(request, candidates)

    rows = simulate(Probe(make(spec, seed)), "s1_stable", seed, cluster=cluster, details=False).rows
    routed = [r["node_id"] for r in rows if r["decision"] == "route"]
    used.sort()
    return {
        "mean_slot_use": sum(used) / len(used),
        "p95_slot_use": used[int(0.95 * (len(used) - 1))],
        "traffic_share": {n: routed.count(n) / len(routed) for n in sorted(set(routed))},
    }


def metric_noise(spec: str, seed: int, rate: float) -> float | None:
    """Adaptation time the frozen metric reports in S1 at `rate` requests/s (the true answer is 0 s)."""
    with open(DEFAULT_CONFIG_PATH) as f:
        raw = yaml.safe_load(f)
    scale = rate / raw["workload"]["base_rate_rps"]
    biggest = raw["workload"]["input_tokens"]["max"] + raw["workload"]["output_tokens"]["max"]
    raw["workload"]["base_rate_rps"] = rate
    for node in raw["nodes"]:  # keep the cluster equally busy at the new rate
        node["capacity"] = max(int(node["capacity"] * scale), 1)
        node["kv_capacity_tokens"] = max(int(node["kv_capacity_tokens"] * scale), biggest)
    cluster = ClusterConfig.model_validate(raw)
    m = load_sweep_config().metrics
    rows = simulate(make(spec, seed), "s1_stable", seed, cluster=cluster, details=False).rows
    G = smooth(
        goodput_series([r["t_arrival"] for r in rows], [bool(r["slo_met"]) for r in rows], cluster.duration_s, m.bin_s),
        max(int(round(m.smooth_s / m.bin_s)), 1),
    )
    adapt, _ = adaptation_time(
        G,
        cluster.t0_s,
        bin_s=m.bin_s,
        steady_from_s=m.steady_from_s,
        steady_to_s=m.steady_to_s,
        fraction=m.fraction,
        hold_s=m.hold_s,
    )
    return adapt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", action="append", help="plain | per_node:W | global:W | baseline:Name (repeatable)")
    ap.add_argument("--seeds", type=int, default=10, help="seeds 0..N-1 (default 10)")
    ap.add_argument("--trace", type=int, default=None, help="also print the per-second trace for this seed")
    ap.add_argument(
        "--counterfactual", action="store_true", help="per-node windows: estimate with/without lost outcomes"
    )
    ap.add_argument("--load", action="store_true", help="S1 cluster load and per-node traffic shares")
    ap.add_argument(
        "--metric-noise",
        type=float,
        default=None,
        metavar="RATE",
        help="S1 adaptation time at RATE requests/s (should be 0 s)",
    )
    ap.add_argument(
        "--fixed-filter",
        action="store_true",
        help="what-if: run with the warming-node bug in Jyotir's filter fixed in memory (filter.py is not changed)",
    )
    args = ap.parse_args(argv)
    with fixed_warming_rule() if args.fixed_filter else contextlib.nullcontext():
        if args.fixed_filter:
            print("what-if: Jyotir's filter with the warming-node bug fixed in memory")
        return _run(args)


def _run(args: argparse.Namespace) -> int:
    if args.metric_noise is not None:
        for spec in args.policy or ["plain"]:
            times = [metric_noise(spec, seed, args.metric_noise) for seed in range(args.seeds)]
            print(f"S1 at {args.metric_noise:g} requests/s, {spec}: adaptation time (s) per seed {times}")
        return 0
    cluster = load_cluster_config()
    if args.load:
        for spec in args.policy or ["plain"]:
            for seed in range(args.seeds):
                c = cluster_load(spec, seed, cluster)
                shares = ", ".join(f"{n} {s:.3f}" for n, s in c["traffic_share"].items())
                print(
                    f"{spec} seed {seed}: slots in use mean {c['mean_slot_use']:.3f}, "
                    f"p95 {c['p95_slot_use']:.3f}; traffic share: {shares}"
                )
        return 0
    if args.counterfactual:
        for spec in args.policy or ["per_node:1000"]:
            for seed in range(args.seeds):
                c = counterfactual(spec, seed, cluster)
                print(
                    f"{spec} seed {seed}: {c['lost_in_window']} of {c['window']} outcomes in the node's window "
                    f"were lost in the outage (last at position {c['last_lost_position']}); estimate at return "
                    f"{c['estimate_with']:+.3f} with them, {c['estimate_without']:+.3f} without; "
                    f"best other node's score {c['best_other_score']:.3f}"
                )
        return 0
    for spec in args.policy or DEFAULT_POLICIES:
        results = [diagnose(spec, seed, cluster) for seed in range(args.seeds)]
        print(f"{spec:14s} rush (s): {[r['rush_s'] for r in results]}")
        print(f"{'':14s} peak queue: {[r['peak_queue'] for r in results]}")
        print(f"{'':14s} share after warm-up: {[round(r['share_after'], 3) for r in results]}")
        print(f"{'':14s} lowest goodput after the return (req/s): {[round(r['lowest_goodput'], 1) for r in results]}")
        print(f"{'':14s} mean goodput (req/s): {[round(r['goodput_mean'], 1) for r in results]}")
        print(f"{'':14s} hard-rule violations: {[r['violations'] for r in results]}")
        if args.trace is not None:
            traced = results[args.trace] if args.trace < len(results) else diagnose(spec, args.trace, cluster)
            print("    second | share | queue | estimate | bonus | best other score | SLO-met requests")
            for s, sh, q, est, bon, oth, met in traced["trace"]:
                print(f"    {s} | {sh:5.2f} | {q:5.0f} | {est:6.3f} | {bon:6.3f} | {oth:6.3f} | {met}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
