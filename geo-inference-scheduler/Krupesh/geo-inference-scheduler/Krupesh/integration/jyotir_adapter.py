"""Adapter: Jyotir's ORIGINAL filter and baselines behind Krupesh's interfaces.

Owner: Krupesh. Jyotir's files in geo-inference-scheduler/Jyotir/ are imported
read-only and never modified. The adapter only translates types:

    Request / NodeState (typed)          -> dicts Jyotir's code reads
    (allowed dicts, [{node_id, reason}]) -> FilterResult
    Jyotir baseline.choose(dict, [dict]) -> Policy.choose(Request, [NodeState])

Limits come from Jyotir's own config file Jyotir/feasibility_filter/configs/feasibility.yaml
(read with his load_config), so there is no second copy of his thresholds.

Known behaviour of the original, documented for Jyotir (NOT changed here):
  F1  a node with status "warming" returns before the model/memory/power/temperature
      rules run, so a hot or full warming node is allowed.
  F2  the memory rule ignores the size of the request (only kv_used_frac >= limit).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from api_contract.types import FilterFn, FilterResult, NodeState, Outcome, Request
from router_service.policy_base import Policy

JYOTIR_DIR = Path(__file__).resolve().parents[2] / "Jyotir"


def _load(module: str):
    path = str(JYOTIR_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(module)


def request_to_dict(r: Request) -> dict[str, Any]:
    d = r.to_dict()
    d["slo_ms"] = r.ttft_slo_ms  # Jyotir's stubs say "slo_ms"; the contract says "ttft_slo_ms"
    return d


def make_jyotir_filter(config_path: str | None = None, overrides: dict | None = None) -> FilterFn:
    """Return a FilterFn backed by Jyotir/feasibility_filter/filter.py::feasibility_filter."""
    mod = _load("feasibility_filter.filter")
    cfg = mod.load_config(config_path) if config_path else mod.load_config()
    cfg = {**cfg, **(overrides or {})}

    def jyotir_filter(request: Request, nodes: list[NodeState]) -> FilterResult:
        by_id = {n.node_id: n for n in nodes}
        allowed, rejected = mod.feasibility_filter(
            request_to_dict(request), [n.to_dict() for n in nodes], cfg
        )
        return FilterResult(
            allowed=[by_id[a["node_id"]] for a in allowed],
            rejected={r["node_id"]: r["reason"] for r in rejected},
        )

    jyotir_filter.config = cfg  # type: ignore[attr-defined]
    return jyotir_filter


JYOTIR_BASELINES = {
    "round_robin": "RoundRobin",
    "min_rtt": "MinRTT",
    "least_load": "LeastLoad",
    "lowest_energy": "LowestEnergy",
    "static_weighted": "StaticWeighted",
    "power_of_two": "PowerOfTwo",
}


class JyotirBaseline(Policy):
    """Policy wrapping one of Jyotir's original baseline classes."""

    def __init__(self, seed: int = 0, baseline: str = "static_weighted", **params):
        super().__init__(seed, **params)
        if baseline not in JYOTIR_BASELINES:
            raise KeyError(f"unknown Jyotir baseline {baseline!r}")
        cls = getattr(_load("baselines"), JYOTIR_BASELINES[baseline])
        if baseline == "power_of_two":
            self.impl = cls(seed=seed)
        elif baseline == "static_weighted" and params:
            self.impl = cls(weights=params)
        else:
            self.impl = cls()
        self.name = f"jyotir:{baseline}"

    def choose(self, request: Request, candidates: list[NodeState]) -> str:
        self._require(candidates)
        return self.impl.choose(request_to_dict(request), [n.to_dict() for n in candidates])

    def update(self, request: Request, node_id: str, outcome: Outcome) -> None:
        return None  # Jyotir's baselines do not learn
