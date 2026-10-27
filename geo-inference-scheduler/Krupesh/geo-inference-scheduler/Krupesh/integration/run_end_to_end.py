"""End-to-end integration run — owner: Krupesh.

    mock simulator -> router (Jyotir's original filter -> policy) -> mock node
        -> delayed Outcome -> /feedback -> reward -> policy.update -> decision log

Run from geo-inference-scheduler/Krupesh:
    python -m integration.run_end_to_end                                  # in-process
    python -m integration.run_end_to_end --policy mock:learning --outage
    uvicorn router_service.app:app --port 8000 &                          # real HTTP
    python -m integration.run_end_to_end --mode http --url http://127.0.0.1:8000
    python -m integration.run_end_to_end --policy round_robin --scenario mock_outage --seed 3 \
        --out-dir runs/round_robin/mock_outage/seed_3        # one run -> one folder (for Riya)

The simulator is a MOCK (integration/mocks/mock_simulator.py) until Parikshit's is ready.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pandas as pd

from decision_log.writer import DecisionLogWriter, read_log, validate_log
from integration.mocks.mock_reward import mock_reward
from integration.mocks.mock_simulator import MockCluster
from router_service.client import HttpRouter
from router_service.engine import RoutingEngine, RunMeta
from router_service.registry import build_filter, build_policy


def run(
    policy: str = "jyotir:static_weighted",
    filter_name: str = "jyotir",
    seed: int = 0,
    duration_s: float = 120.0,
    rate_rps: float = 10.0,
    outage: bool = False,
    mode: str = "inprocess",
    url: str | None = None,
    client=None,
    log_path: str | None = None,
) -> pd.DataFrame:
    run_id = f"mock__{policy.replace(':', '-')}__s{seed}{'__outage' if outage else ''}"
    if mode == "http":
        router = HttpRouter(client) if client is not None else HttpRouter.connect(url)
        router.configure(
            policy=policy,
            filter=filter_name,
            seed=seed,
            run_id=run_id,
            scenario="mock_outage" if outage else "mock_stable",
        )
    else:
        router = RoutingEngine(
            policy=build_policy(policy, seed=seed),
            filter_fn=build_filter(filter_name),
            reward_fn=mock_reward,
            meta=RunMeta(run_id, seed, "mock_outage" if outage else "mock_stable", policy),
            writer=DecisionLogWriter(),
            audit_fn=build_filter("jyotir"),
        )
    cluster = MockCluster(
        router,
        seed=seed,
        rate_rps=rate_rps,
        duration_s=duration_s,
        outage=("node-east", duration_s / 3, 2 * duration_s / 3) if outage else None,
    )
    cluster.run()
    if mode == "http":
        path = log_path or str(
            Path(tempfile.mkdtemp(prefix="krupesh_log_")) / "decision_log.parquet"
        )
        info = router.finish(path)
        df = read_log(info["log_path"])
        df["router_wall_ms"] = df["request_id"].map(router.wall_ms)  # client-observed round trip
    else:
        router.finish()
        router.writer.path = Path(log_path) if log_path else None
        df = router.writer.close()
    return df


def summary(df: pd.DataFrame, duration_s: float) -> dict:
    slo = df["slo_met"].fillna(False).astype(bool)
    return {
        "requests": len(df),
        "goodput_rps": round(slo.sum() / duration_s, 3),
        "rejected": int((df.decision == "reject").sum()),
        "failed": int((df.outcome_status == "failed").sum()),
        "unfinished": int((df.outcome_status == "unfinished").sum()),
        "constraint_violations": int(df.constraint_violation.notna().sum()),
        "routed_by_node": df.node_id.value_counts().to_dict(),
        "log_problems": validate_log(df),
    }


MOCK_SCENARIOS = {"mock_stable": False, "mock_outage": True}


def main(argv: list[str] | None = None) -> int:
    """CLI. Exit codes: 0 = ok, 1 = run failed (exception), 2 = log invalid / unsupported scenario.

    With --out-dir DIR the run writes DIR/decision_log.parquet and DIR/run_summary.json
    (status "ok" | "invalid_log" | "failed"); the folder is created if needed.
    """
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--policy", default="jyotir:static_weighted")
    ap.add_argument("--filter", default="jyotir", choices=["jyotir", "none"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--scenario",
        default=None,
        help="mock_stable | mock_outage (S1-S6 need Parikshit's simulator)",
    )
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--rate", type=float, default=10.0)
    ap.add_argument("--outage", action="store_true", help="same as --scenario mock_outage")
    ap.add_argument("--mode", default="inprocess", choices=["inprocess", "http"])
    ap.add_argument("--url")
    ap.add_argument("--log", help="write the decision log here (.parquet or .csv)")
    ap.add_argument(
        "--out-dir", help="write decision_log.parquet + run_summary.json into this folder"
    )
    a = ap.parse_args(argv)

    scenario = a.scenario or ("mock_outage" if a.outage else "mock_stable")
    if scenario not in MOCK_SCENARIOS:
        print(
            f"scenario {scenario!r} is not available yet: S1-S6 require Parikshit's simulator; "
            f"use one of {sorted(MOCK_SCENARIOS)}"
        )
        return 2
    out_dir = Path(a.out_dir) if a.out_dir else None
    log_path = a.log
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = str(out_dir / "decision_log.parquet")
    meta = {
        "policy": a.policy,
        "scenario": scenario,
        "seed": a.seed,
        "filter": a.filter,
        "duration_s": a.duration,
        "rate_rps": a.rate,
        "mode": a.mode,
        "simulator": "mock",
    }

    try:
        df = run(
            a.policy,
            a.filter,
            a.seed,
            a.duration,
            a.rate,
            MOCK_SCENARIOS[scenario],
            a.mode,
            a.url,
            log_path=log_path,
        )
    except Exception as e:  # report and signal failure, never a silent half-run
        if out_dir is not None:
            (out_dir / "run_summary.json").write_text(
                json.dumps(
                    {**meta, "status": "failed", "error": f"{type(e).__name__}: {e}"}, indent=2
                )
            )
        print(f"run failed: {type(e).__name__}: {e}")
        return 1

    s = summary(df, a.duration)
    status = "ok" if not s["log_problems"] else "invalid_log"
    if out_dir is not None:
        (out_dir / "run_summary.json").write_text(
            json.dumps(
                {**meta, "status": status, **s, "decision_log": "decision_log.parquet"},
                indent=2,
                default=str,
            )
        )
    print(json.dumps({**s, "status": status}, indent=2, default=str))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
