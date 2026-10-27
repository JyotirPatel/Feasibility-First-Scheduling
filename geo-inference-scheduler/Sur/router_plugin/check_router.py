"""
Router check — owner: Sur

Runs one of Sur's policies through Krupesh's router end to end, which is the
acceptance check in his handbook (§5.3: `run_end_to_end --policy sur:sw_linucb`
gives log_problems: [] and constraint_violations: 0). It is done from Sur's side,
with Sur's reward, so Krupesh's folder is not edited:

    Krupesh's mock simulator -> router (Jyotir's filter -> Sur's policy) -> mock node
        -> delayed Outcome -> feedback -> Sur's reward_fn -> policy.update -> decision log

It builds the same in-process run as Krupesh's integration/run_end_to_end.py (his
RoutingEngine, MockCluster and run summary), except that the reward is Sur's
instead of his mock_reward.

Usage (from the Sur/ folder):
    python3 router_plugin/check_router.py                          # sur:sw_linucb, no outage
    python3 router_plugin/check_router.py --policy sur:linucb --outage --seed 3

It prints Krupesh's run summary and the policy's counters. The exit code is 0 only if
the decision log is valid, no hard rule was broken, every finished request was learned
from, and the router's reward equals the policy's.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_SUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SUR_DIR not in sys.path:
    sys.path.insert(0, _SUR_DIR)

from router_plugin import make_reward_fn, register  # noqa: E402  (also makes Krupesh's packages importable)


def run(
    policy: str = "sur:sw_linucb",
    seed: int = 0,
    duration_s: float = 120.0,
    rate_rps: float = 10.0,
    outage: bool = False,
):
    """One mock run through Krupesh's router; returns (the policy, his RoutingEngine, the decision log)."""
    from integration.mocks.mock_simulator import MockCluster
    from router_service.engine import RoutingEngine, RunMeta
    from router_service.registry import build_filter, build_policy

    register()
    bandit = build_policy(policy, seed=seed)
    scenario = "mock_outage" if outage else "mock_stable"
    engine = RoutingEngine(
        policy=bandit,
        filter_fn=build_filter("jyotir"),
        reward_fn=make_reward_fn(bandit.config.reward),
        meta=RunMeta(f"sur-check__{policy.replace(':', '-')}__s{seed}", seed, scenario, policy),
        audit_fn=build_filter("jyotir"),
    )
    # The same outage as Krupesh's run_end_to_end.run(): node-east down for the middle third.
    down = ("node-east", duration_s / 3, 2 * duration_s / 3) if outage else None
    MockCluster(engine, seed=seed, rate_rps=rate_rps, duration_s=duration_s, outage=down).run()
    engine.finish()
    return bandit, engine, engine.writer.close()


def check(
    policy: str = "sur:sw_linucb",
    seed: int = 0,
    duration_s: float = 120.0,
    rate_rps: float = 10.0,
    outage: bool = False,
) -> dict:
    """One mock run through Krupesh's router; returns his summary plus the policy's counters and `ok`."""
    from integration.run_end_to_end import summary

    bandit, engine, log = run(policy, seed, duration_s, rate_rps, outage)
    result = summary(log, duration_s)
    result["engine_counts"] = dict(engine.counts)
    result["policy_stats"] = dict(bandit.stats)
    result["policy_pending"] = bandit.pending_count
    result["ok"] = (
        result["log_problems"] == []
        and result["constraint_violations"] == 0
        and bandit.stats["updates"] == engine.counts["feedback"]
        and bandit.stats["ignored_feedback"] == 0
        and bandit.stats["reward_mismatch"] == 0
        and bandit.pending_count == result["unfinished"]
    )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", default="sur:sw_linucb", help="a name registered by router_plugin.register()")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--duration", type=float, default=120.0, help="simulated seconds")
    ap.add_argument("--rate", type=float, default=10.0, help="requests per second")
    ap.add_argument("--outage", action="store_true", help="node-east goes down for the middle third of the run")
    args = ap.parse_args(argv)
    result = check(args.policy, args.seed, args.duration, args.rate, args.outage)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
