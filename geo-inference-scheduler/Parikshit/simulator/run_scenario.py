"""
Run one scenario through Krupesh's router — owner: Parikshit

    Parikshit's simulator -> Krupesh's router (Jyotir's filter -> a policy) -> simulated node
        -> delayed outcome -> feedback -> reward -> policy.update -> decision log

This is the acceptance check of Krupesh's handbook for the simulator (§5.2): his mock cluster
replaced by this simulator, in-process or over HTTP, with a decision log that his
validate_log() accepts. Policies are those of his registry: Jyotir's baselines
("jyotir:least_load", "round_robin", ...) and, when Sur's router plug-in is present, Sur's
("sur:sw_linucb", "linucb", ...). The reward is Sur's when available, else his mock.

Usage (from the Parikshit/ folder):
    python3 simulator/run_scenario.py --scenario s6_outage_recovery --policy jyotir:least_load --seed 0
    python3 simulator/run_scenario.py --scenario s2_traffic_burst --policy sur:sw_linucb --nodes 10 \\
        --out-dir runs/sur-sw_linucb/s2_traffic_burst/seed_0
    uvicorn router_service.app:app --port 8000 &          # from Krupesh's folder, for HTTP mode
    python3 simulator/run_scenario.py --mode http --url http://127.0.0.1:8000 --policy jyotir:least_load

With --out-dir DIR it writes DIR/decision_log.(parquet|csv) and DIR/run_summary.json. Exit
codes, as Krupesh's runner: 0 = ok, 1 = the run failed, 2 = the decision log is invalid.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # run as a script
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.cluster import Simulation
from simulator.config import CONFIG_DIR, EVENT_TRACE_DIR, load_cluster, load_scenario, load_workload
from simulator.routers import KrupeshRouter, krupesh_engine, use_krupesh


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _log_name() -> str:
    """Parquet needs pyarrow (in Krupesh's requirements); without it the log is written as CSV."""
    return "decision_log.parquet" if importlib.util.find_spec("pyarrow") else "decision_log.csv"


def run(
    scenario: str,
    policy: str,
    seed: int,
    nodes: str | int | None = None,
    mode: str = "inprocess",
    url: str | None = None,
    client=None,
    log_path: str | None = None,
    rate_rps: float | None = None,
) -> tuple[dict, object]:
    """One run. Returns (summary, decision log DataFrame). rate_rps overrides configs/workload.yaml."""
    use_krupesh()
    cluster = load_cluster(nodes)
    scen = load_scenario(scenario)
    workload = load_workload()
    if rate_rps is not None:
        workload = workload.model_copy(update={"rate_rps": rate_rps})
    if mode == "http":
        from router_service.client import HttpRouter

        http = HttpRouter(client) if client is not None else HttpRouter.connect(url)
        http.configure(policy=policy, seed=seed, run_id=f"{scen.name}__{policy}__s{seed}", scenario=scen.name)
        router, reward = KrupeshRouter(http), "router's (set by the HTTP service)"
    else:
        engine, reward = krupesh_engine(policy, seed, scen.name, log_path)
        router = KrupeshRouter(engine)

    started = time.perf_counter()
    sim = Simulation(router, scen, seed, cluster=cluster, workload=workload)
    stats = sim.run()
    if mode == "http":
        info = router.router.finish(log_path)
        from decision_log.writer import read_log

        log = read_log(info["log_path"]) if info.get("log_path") else None
    else:
        engine.finish()
        log = engine.writer.close()

    from decision_log.writer import validate_log
    from integration.run_end_to_end import summary as krupesh_summary

    summary = {
        "scenario": scen.name,
        "policy": policy,
        "seed": seed,
        "nodes": [n.node_id for n in cluster.nodes],
        "rate_rps": workload.rate_rps,
        "mode": mode,
        "reward": reward,
        "simulator": "Parikshit/simulator (SimPy)",
        "wall_s": round(time.perf_counter() - started, 2),
        "simulation": stats,
        "true_state_violations": dict(router.true_state_violations),
    }
    if log is not None:
        summary["router"] = krupesh_summary(log, scen.duration_s)
        summary["log_problems"] = validate_log(log)
    stats = getattr(getattr(router.router, "policy", None), "stats", None)  # in-process only
    if stats is not None:
        summary["policy_stats"] = dict(stats)
        if stats.get("reward_mismatch"):
            summary.setdefault("log_problems", []).append(
                f"the router's and the policy's rewards disagree on {stats['reward_mismatch']} outcomes"
            )
    return summary, log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="s1_stable", help="an event trace in event_traces/ (s1_stable ... s6_...)")
    ap.add_argument("--policy", default="jyotir:least_load", help="a policy name of Krupesh's registry")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--nodes", default="5", help="5, 10 or a path to a nodes YAML file")
    ap.add_argument("--rate", type=float, default=None, help="arrivals per second (default: configs/workload.yaml)")
    ap.add_argument("--mode", default="inprocess", choices=["inprocess", "http"])
    ap.add_argument("--url", help="the router service for --mode http")
    ap.add_argument("--out-dir", help="write the decision log and run_summary.json here")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir) if args.out_dir else None
    log_path = str(out_dir / _log_name()) if out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    nodes_path = os.path.join(CONFIG_DIR, f"nodes_{args.nodes}.yaml") if str(args.nodes).isdigit() else args.nodes
    meta = {
        "configs_sha256": {
            os.path.relpath(p, os.path.dirname(CONFIG_DIR)): _sha256(p)
            for p in (
                nodes_path,
                os.path.join(CONFIG_DIR, "workload.yaml"),
                os.path.join(CONFIG_DIR, "calibration.yaml"),
                os.path.join(EVENT_TRACE_DIR, f"{args.scenario}.yaml"),
            )
        },
        "krupesh_dir": use_krupesh(),
    }
    try:
        summary, _ = run(
            args.scenario,
            args.policy,
            args.seed,
            args.nodes,
            args.mode,
            args.url,
            log_path=log_path,
            rate_rps=args.rate,
        )
    except Exception as e:  # report and signal failure, never a silent half-run
        if out_dir:
            (out_dir / "run_summary.json").write_text(
                json.dumps({**meta, "status": "failed", "error": f"{type(e).__name__}: {e}"}, indent=2)
            )
        print(f"run failed: {type(e).__name__}: {e}")
        return 1
    status = "ok" if not summary.get("log_problems") else "invalid_log"
    summary = {**summary, **meta, "status": status, "decision_log": os.path.basename(log_path) if log_path else None}
    if out_dir:
        (out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("configs_sha256",)}, indent=2, default=str))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
