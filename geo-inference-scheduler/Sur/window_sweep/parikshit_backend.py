"""
The window sweep on Parikshit's simulator — owner: Sur

With --simulator parikshit (the default) every run of run_sweep.py goes through the project's
real pipeline, the one Riya's experiment runner uses:

    Parikshit's simulator (Parikshit/simulator/) -> Krupesh's router: Jyotir's filter -> the policy
        -> delayed outcome -> Sur's reward (the policy's own reward section) -> update -> decision log

simulate() returns the run in the same shape as the stand-in's result (standins/toy_cluster.py):
.column(name) per request in arrival order, .stats and .to_csv(path), so run_sweep.py computes the
same metrics on both. scenario_clock() gives the times compute_metrics needs (duration, t0, the S6
return). Nothing in Parikshit's, Krupesh's or Jyotir's folders is changed.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import numpy as np

_SUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARIKSHIT_DIR = os.path.join(os.path.dirname(_SUR_DIR), "Parikshit")

# Jyotir's baseline classes (sweep.yaml) -> their names in Krupesh's policy registry
BASELINE_NAMES = {
    "RoundRobin": "jyotir:round_robin",
    "MinRTT": "jyotir:min_rtt",
    "LeastLoad": "jyotir:least_load",
    "LowestEnergy": "jyotir:lowest_energy",
    "StaticWeighted": "jyotir:static_weighted",
    "PowerOfTwo": "jyotir:power_of_two",
}


def use_parikshit() -> None:
    """Make Parikshit's simulator importable, and through it Krupesh's and Jyotir's packages."""
    if PARIKSHIT_DIR not in sys.path:
        sys.path.append(PARIKSHIT_DIR)
    from simulator.routers import use_krupesh

    use_krupesh()


def config_paths() -> list[str]:
    """The simulator's config files and event traces, for the bundle's manifest."""
    configs = os.path.join(PARIKSHIT_DIR, "configs")
    traces = os.path.join(PARIKSHIT_DIR, "event_traces")
    return [
        *(os.path.join(configs, f) for f in ("nodes_5.yaml", "workload.yaml", "calibration.yaml")),
        *(os.path.join(traces, f) for f in sorted(os.listdir(traces)) if f.endswith(".yaml")),
    ]


@dataclass(frozen=True)
class ScenarioClock:
    """What run_sweep.compute_metrics reads from the stand-in's ClusterConfig, for one of Parikshit's scenarios."""

    duration_s: float
    t0_s: float
    change_times: dict[str, float]
    scenarios: Any = field(default=None)  # .s6_outage_recovery.{node, return_s, warmup_s}


def scenario_clock(scenario: str) -> ScenarioClock:
    use_parikshit()
    from simulator.config import NodeDown, NodeReturn, load_scenario
    from simulator.events import change_times

    scen = load_scenario(scenario)
    s6 = load_scenario("s6_outage_recovery")
    down = next(e for e in s6.events if isinstance(e, NodeDown))
    back = next(e for e in s6.events if isinstance(e, NodeReturn))
    outage = SimpleNamespace(node=down.node, return_s=back.at_s, warmup_s=back.warmup_s)
    return ScenarioClock(scen.duration_s, scen.t0_s, change_times(scen), SimpleNamespace(s6_outage_recovery=outage))


def make_router_policy(family: str, *, seed: int, config: dict | None = None, baseline: str | None = None):
    """The router-side policy object: Sur's bandits as Krupesh Policy subclasses, or Jyotir's baseline."""
    use_parikshit()
    if family in ("sw_linucb", "linucb"):
        if _SUR_DIR not in sys.path:
            sys.path.append(_SUR_DIR)
        from router_plugin import RouterLinUCB, RouterSlidingWindowLinUCB

        cls = RouterSlidingWindowLinUCB if family == "sw_linucb" else RouterLinUCB
        return cls(config, seed=seed)
    from router_service.registry import build_policy

    return build_policy(BASELINE_NAMES[baseline], seed=seed)


class RunResult:
    """One run's decision log, read like the stand-in's result."""

    _ZERO_IF_MISSING = ("cost_usd", "energy_kwh")  # a rejected request costs nothing

    def __init__(self, log, stats: dict):
        self.log = log
        self.stats = stats

    def column(self, name: str) -> list:
        col = self.log[name]
        if name == "slo_met":  # rejected requests have no outcome: they did not meet the SLO
            return [v is True or (isinstance(v, (bool, np.bool_)) and bool(v)) for v in col]
        if name in self._ZERO_IF_MISSING:
            return [0.0 if v is None or v != v else float(v) for v in col]
        return [None if v is None or (isinstance(v, float) and v != v) else v for v in col]

    def to_csv(self, path: str) -> None:
        self.log.to_csv(path, index=False)


def simulate(policy, scenario: str, seed: int, *, policy_name: str, run_id: str) -> RunResult:
    """One run of `policy` on Parikshit's `scenario` with `seed`, through Krupesh's router."""
    use_parikshit()
    from decision_log.writer import DecisionLogWriter
    from router_service.engine import RoutingEngine, RunMeta
    from router_service.registry import build_filter
    from simulator.cluster import Simulation
    from simulator.routers import KrupeshRouter

    if _SUR_DIR not in sys.path:
        sys.path.append(_SUR_DIR)
    from router_plugin import make_reward_fn

    reward_section = getattr(getattr(policy, "config", None), "reward", None)
    engine = RoutingEngine(
        policy=policy,
        filter_fn=build_filter("jyotir"),
        reward_fn=make_reward_fn(reward_section),  # the policy's own reward, so router and policy agree
        meta=RunMeta(run_id, seed, scenario, policy_name),
        writer=DecisionLogWriter(None),
        audit_fn=build_filter("jyotir"),
    )
    router = KrupeshRouter(engine)
    sim_stats = Simulation(router, scenario, seed).run()
    engine.finish()
    log = engine.writer.close()
    if len(log) != sim_stats["requests"]:
        raise RuntimeError(f"{run_id}: {len(log)} log rows for {sim_stats['requests']} requests")
    stats = {
        "failed": int((log["outcome_status"] == "failed").sum()),
        "hard_rule_violations": int(log["constraint_violation"].notna().sum()),  # must stay 0: the filter is on
        "true_state_violations": int(sum(router.true_state_violations.values())),
        "policy_stats": dict(getattr(policy, "stats", {}) or {}),
    }
    return RunResult(log, stats)
