"""Policy and filter registry — owner: Krupesh. Experiments switch policy with one string.

Policy names:
    "jyotir:<baseline>"   Jyotir's ORIGINAL baseline via the adapter, e.g. "jyotir:static_weighted"
                          (<baseline> in round_robin, min_rtt, least_load, lowest_energy,
                          static_weighted, power_of_two)
    "mock:learning"       MOCK learning policy standing in for Sur's LinUCB (integration only)
    "sur:<name>"          reserved for Sur's real policies once they exist (register below)

Filter names:
    "jyotir"              Jyotir's ORIGINAL feasibility filter via the adapter
    "none"                allow every known node (ONLY for the "no filter" ablation)
"""

from __future__ import annotations

from collections.abc import Callable

from api_contract.types import FilterFn, FilterResult, NodeState, Request
from router_service.policy_base import Policy

# Teammates register real implementations here when they are ready, e.g.
#   EXTRA_POLICIES["sur:sw_linucb"] = lambda seed, **p: SlidingWindowLinUCB(seed=seed, **p)
EXTRA_POLICIES: dict[str, Callable[..., Policy]] = {}

# Plain names used in Riya's experiment config (Riya/experiment_runner/config.json).
SHARED_NAMES = {
    "round_robin": "jyotir:round_robin",
    "min_rtt": "jyotir:min_rtt",
    "least_load": "jyotir:least_load",
    "lowest_energy": "jyotir:lowest_energy",
    "static_weighted": "jyotir:static_weighted",
    "power_of_two": "jyotir:power_of_two",
}
NEEDS_SUR = {"linucb", "sliding_window_linucb"}


def build_policy(name: str, seed: int = 0, **params) -> Policy:
    if name in EXTRA_POLICIES:
        return EXTRA_POLICIES[name](seed=seed, **params)
    if name in NEEDS_SUR:
        raise KeyError(
            f"policy {name!r} needs Sur's implementation: register it in "
            "router_service/registry.py EXTRA_POLICIES (use 'mock:learning' only for plumbing tests)"
        )
    name = SHARED_NAMES.get(name, name)
    kind, _, arg = name.partition(":")
    if kind == "jyotir":
        from integration.jyotir_adapter import JyotirBaseline

        return JyotirBaseline(seed=seed, baseline=arg, **params)
    if name == "mock:learning":
        from integration.mocks.mock_policy import MockLearningPolicy

        return MockLearningPolicy(seed=seed, **params)
    raise KeyError(f"unknown policy {name!r}")


def allow_all(request: Request, nodes: list[NodeState]) -> FilterResult:
    """No-filter ablation ONLY: every known node is a candidate."""
    return FilterResult(allowed=list(nodes), rejected={})


def build_filter(name: str = "jyotir", config_path: str | None = None) -> FilterFn:
    if name == "jyotir":
        from integration.jyotir_adapter import make_jyotir_filter

        return make_jyotir_filter(config_path)
    if name == "none":
        return allow_all
    raise KeyError(f"unknown filter {name!r}")
