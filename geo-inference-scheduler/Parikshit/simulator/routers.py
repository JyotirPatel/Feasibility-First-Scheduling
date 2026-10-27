"""
Router connections — owner: Parikshit

The simulator drives a router through ingest_telemetry / route / feedback, plus an optional
after_route (simulator/cluster.py). This module provides two routers:

  KrupeshRouter  Krupesh's router: his RoutingEngine in-process, or his HTTP service through
                 his HttpRouter client. Telemetry, requests and outcomes become his NodeState,
                 Request and Outcome types, as in his mock simulator. In-process it also fills
                 the decision log's true_state_violation column.
  LocalRouter    a small router for tests and quick runs: Jyotir's real filter and a
                 least-loaded choice, with its own decision rows.

krupesh_engine() builds his RoutingEngine for one run with Jyotir's filter and, when Sur's
router plug-in is present, Sur's policies and reward (Sur/router_plugin/).

true_state_problems() checks the chosen node's true state at the moment of the decision
against the brief's hard rules (§6.1), with Jyotir's limits from his feasibility.yaml. The
router decides on telemetry up to one tick old, so the node may, for example, have gone
down or filled up since its last report. Unlike Jyotir's filter today it also checks a
warming node, and it checks that the request fits in the KV cache (Krupesh's F1 and F2).
"""

from __future__ import annotations

import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
PARIKSHIT_DIR = os.path.dirname(_HERE)
GEO_DIR = os.path.dirname(PARIKSHIT_DIR)
JYOTIR_DIR = os.path.join(GEO_DIR, "Jyotir")
SUR_DIR = os.path.join(GEO_DIR, "Sur")
# Krupesh's upload of 2026-10-27 landed one level deeper than his folder; accept both places.
KRUPESH_CANDIDATES = (
    os.path.join(GEO_DIR, "Krupesh"),
    os.path.join(GEO_DIR, "Krupesh", "geo-inference-scheduler", "Krupesh"),
)


def _append_path(path: str) -> None:
    if path not in sys.path:
        sys.path.append(path)  # appended, so the simulator's own modules win any name clash


def krupesh_dir() -> str:
    for path in KRUPESH_CANDIDATES:
        if os.path.isfile(os.path.join(path, "router_service", "engine.py")):
            return path
    raise ImportError(f"Krupesh's router (router_service/engine.py) is not in any of {KRUPESH_CANDIDATES}")


def use_krupesh() -> str:
    """Make Krupesh's packages importable, and Jyotir's, which his adapter imports. Returns his folder."""
    _append_path(JYOTIR_DIR)
    path = krupesh_dir()
    _append_path(path)
    return path


def jyotir_filter():
    """(feasibility_filter, limits) from Jyotir's code and his feasibility.yaml."""
    _append_path(JYOTIR_DIR)
    from feasibility_filter.filter import feasibility_filter, load_config

    return feasibility_filter, load_config()


def true_state_problems(request: dict, record: dict, limits: dict) -> list[str]:
    """Hard rules the node breaks in its true state, in Jyotir's reason names (empty = none)."""
    problems = []
    if record["status"] == "down":
        problems.append("node_down")
    elif record["status"] == "warming" and not limits.get("allow_warming_nodes", True):
        problems.append("node_warming")
    if request["model"] not in record["models_loaded"]:
        problems.append("model_missing")
    kv_limit = limits["kv_cache_max_frac"]
    cap = record.get("kv_capacity_tokens")
    if cap:
        need = (request["input_tokens"] + request["expected_output_tokens"]) / cap
        if record["kv_used_frac"] + need > kv_limit:
            problems.append("memory_full")
    elif record["kv_used_frac"] >= kv_limit:
        problems.append("memory_full")
    if record["power_headroom_kw"] < limits["power_headroom_min_kw"]:
        problems.append("power_limit")
    if record["temperature_c"] >= limits["temperature_limit_c"]:
        problems.append("temperature_high")
    return problems


def least_load(request: dict, candidates: list[dict]) -> str:
    return min(candidates, key=lambda c: ((c["queue_len"] + c["running"]) / c["capacity"], c["node_id"]))["node_id"]


class LocalRouter:
    """Jyotir's filter + least-loaded choice. Keeps one row per decision and the outcomes."""

    def __init__(self, choose=least_load):
        self._filter, self.limits = jyotir_filter()
        self.choose = choose
        self.view: dict[str, dict] = {}
        self.decisions: list[dict] = []
        self.outcomes: dict[str, dict] = {}

    def ingest_telemetry(self, records: list[dict]) -> None:
        self.view = {r["node_id"]: r for r in records}

    def route(self, request: dict) -> tuple[str, str | None]:
        allowed, rejected = self._filter(request, list(self.view.values()), self.limits)
        node_id = self.choose(request, allowed) if allowed else None
        self.decisions.append(
            {
                "request_id": request["request_id"],
                "t_arrival": request["t_arrival"],
                "node_id": node_id,
                "feasible_nodes": [a["node_id"] for a in allowed],
                "filtered_out": {r["node_id"]: r["reason"] for r in rejected},
            }
        )
        return ("route", node_id) if allowed else ("reject", None)

    def feedback(self, outcome: dict) -> None:
        if outcome["request_id"] in self.outcomes:
            raise ValueError(f"second outcome for {outcome['request_id']}")
        self.outcomes[outcome["request_id"]] = outcome


class KrupeshRouter:
    """Krupesh's RoutingEngine (in-process) or his HttpRouter client behind the simulator's calls."""

    def __init__(self, router, check_true_state: bool = True):
        use_krupesh()
        from api_contract.types import NodeState, Outcome, Request

        self.router = router
        self._types = NodeState, Outcome, Request
        self._limits = jyotir_filter()[1] if check_true_state else None
        self.true_state_violations: Counter = Counter()

    def ingest_telemetry(self, records: list[dict]) -> None:
        node_state = self._types[0]
        self.router.ingest_telemetry([node_state.from_dict(r) for r in records])

    def route(self, request: dict) -> tuple[str, str | None]:
        d = self.router.route(self._types[2].from_dict(request))
        return d.decision, d.node_id

    def feedback(self, outcome: dict) -> None:
        self.router.feedback(self._types[1](**outcome))

    def after_route(self, request: dict, node_id: str, true_record: dict) -> None:
        if self._limits is None:
            return
        problems = true_state_problems(request, true_record, self._limits)
        if problems:
            self.true_state_violations.update(problems)
            if hasattr(self.router, "annotate"):  # the in-process engine; the HTTP API has no annotate call
                self.router.annotate(request["request_id"], true_state_violation=",".join(problems))


def krupesh_engine(policy: str, seed: int, scenario: str, log_path: str | None = None, filter_name: str = "jyotir"):
    """(Krupesh's RoutingEngine for one run, "sur" or "mock").

    With Sur/router_plugin/ present, Sur's policies and reward are used. The router's reward is built from the
    policy's own reward section (Sur's default for policies without one), so the reward in the decision log is
    the one the policy learns from, as in Riya's runner. Without the plug-in, the router's mock reward is used.
    """
    use_krupesh()
    from decision_log.writer import DecisionLogWriter
    from router_service.engine import RoutingEngine, RunMeta
    from router_service.registry import build_filter, build_policy

    if os.path.isdir(os.path.join(SUR_DIR, "router_plugin")):
        _append_path(SUR_DIR)
        from router_plugin import make_reward_fn, register

        register()
        model = build_policy(policy, seed=seed)
        reward_fn = make_reward_fn(getattr(getattr(model, "config", None), "reward", None))
        reward_name = "sur"
    else:  # without Sur's plug-in the router can only use its mock reward
        from integration.mocks.mock_reward import mock_reward as reward_fn

        model = build_policy(policy, seed=seed)
        reward_name = "mock"
    engine = RoutingEngine(
        policy=model,
        filter_fn=build_filter(filter_name),
        reward_fn=reward_fn,
        meta=RunMeta(f"{scenario}__{policy}__s{seed}", seed, scenario, policy),
        writer=DecisionLogWriter(log_path),
        audit_fn=build_filter("jyotir"),
    )
    return engine, reward_name
