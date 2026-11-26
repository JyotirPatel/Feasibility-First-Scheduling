"""Shared contract types — owner: Krupesh. Frozen v1 fields from the Project Brief §10.

Every teammate's module talks to the router ONLY through these types:

    Request      what POST /route receives                      (brief §10.2)
    Decision     what POST /route returns                       (brief §10.2)
    NodeState    one telemetry record per node per tick          (brief §10.1, owner Parikshit)
    Outcome      what POST /feedback receives                    (brief §10.2)
    FilterResult what a feasibility filter returns               (Jyotir's filter, via adapter)
    FilterFn     (request, nodes) -> FilterResult                (filter plug-in point)
    RewardFn     (outcome, node_at_dispatch) -> float            (Sur's reward plug-in point)

Fields marked "extension" are optional and backward compatible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"
NODE_STATUSES = ("up", "down", "warming")
NO_FEASIBLE_NODE = "no_feasible_node"


@dataclass(frozen=True)
class Request:
    request_id: str
    t_arrival: float  # simulation time, seconds
    user_region: str
    model: str
    input_tokens: int
    expected_output_tokens: int
    slo_class: str = "interactive"
    ttft_slo_ms: float = 250.0

    @property
    def kv_tokens(self) -> int:
        return int(self.input_tokens) + int(self.expected_output_tokens)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Request:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class NodeState:
    node_id: str
    status: str
    rtt_ms: dict[str, float]
    queue_len: int
    running: int
    capacity: int
    kv_used_frac: float
    models_loaded: list[str]
    power_headroom_kw: float
    temperature_c: float
    energy_price_usd_kwh: float
    gpu_price_usd_hr: float
    t: float = 0.0
    schema_version: str = SCHEMA_VERSION
    kv_capacity_tokens: int | None = None  # extension (optional)

    @property
    def is_warming(self) -> bool:
        return self.status == "warming"

    @property
    def load(self) -> int:
        return int(self.queue_len) + int(self.running)

    def rtt_for(self, region: str) -> float:
        if region in self.rtt_ms:
            return float(self.rtt_ms[region])
        if self.rtt_ms:
            return float(sum(self.rtt_ms.values()) / len(self.rtt_ms))
        return float("inf")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rtt_ms"] = dict(self.rtt_ms)
        d["models_loaded"] = list(self.models_loaded)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeState:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Decision:
    request_id: str
    decision: str  # "route" | "reject"
    node_id: str | None
    policy: str
    feasible_nodes: list[str] = field(default_factory=list)
    filtered_out: dict[str, str] = field(default_factory=dict)
    reject_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Outcome:
    request_id: str
    ttft_ms: float
    e2e_ms: float
    slo_met: bool
    energy_kwh: float
    cost_usd: float
    failed: bool = False  # extension: node died while holding the request
    t_complete: float | None = None  # extension: simulation time of completion
    reward: float | None = None  # filled by the router before policy.update()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Outcome:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class FilterResult:
    allowed: list[NodeState] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)  # node_id -> reason

    @property
    def allowed_ids(self) -> list[str]:
        return [n.node_id for n in self.allowed]


FilterFn = Callable[[Request, list[NodeState]], FilterResult]
RewardFn = Callable[[Outcome, NodeState], float]
