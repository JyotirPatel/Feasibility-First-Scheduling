"""
Config files and their checks — owner: Parikshit

Every number the simulator uses comes from one of these YAML files; nothing is fixed in
the Python code (brief §13). Each file is checked by a Pydantic model: unknown keys,
missing keys, wrong types and impossible values are rejected when the file is loaded.

  configs/calibration.yaml     model, GPU specs and the benchmark the latency model is fitted to
  configs/nodes_5.yaml         5-node setup (sites, GPUs, power, temperature, telemetry tick)
  configs/nodes_10.yaml        10-node setup
  configs/workload.yaml        request classes, arrival rate, user regions
  event_traces/s*.yaml         the six change scenarios (S1-S6)
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PARIKSHIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PARIKSHIT_DIR, "configs")
EVENT_TRACE_DIR = os.path.join(PARIKSHIT_DIR, "event_traces")
PROCESSED_DIR = os.path.join(PARIKSHIT_DIR, "data", "processed")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


# ── configs/calibration.yaml ─────────────────────────────────────────────────


class ModelSpec(_Strict):
    name: str
    params: float = Field(gt=0)
    bytes_per_param: float = Field(gt=0)
    layers: int = Field(gt=0)
    kv_heads: int = Field(gt=0)
    head_dim: int = Field(gt=0)
    kv_bytes_per_value: float = Field(gt=0)
    max_context_tokens: int = Field(gt=0)


class GpuSpec(_Strict):
    memory_gb: float = Field(gt=0)
    memory_bandwidth_tb_s: float = Field(gt=0)
    bf16_dense_tflops: float = Field(gt=0)
    server_gpus: int = Field(gt=0)
    server_max_power_kw: float = Field(gt=0)
    rent_usd_per_gpu_hr: float = Field(ge=0)


class BenchmarkSpec(_Strict):
    gpu: str
    ttft_ms: list[tuple[float, float]] = Field(min_length=2)
    saturated: list[tuple[float, float, float]] = Field(min_length=2)
    tpot_at_saturation_ms: list[float] = Field(min_length=1)


class ServingSpec(_Strict):
    gpu_memory_utilization: float = Field(gt=0, le=1)
    decode_bandwidth_efficiency: float = Field(gt=0, le=1)


class CalibrationConfig(_Strict):
    model: ModelSpec
    gpus: dict[str, GpuSpec] = Field(min_length=1)
    benchmark: BenchmarkSpec
    serving: ServingSpec

    @model_validator(mode="after")
    def _benchmark_gpu_is_listed(self) -> CalibrationConfig:
        if self.benchmark.gpu not in self.gpus:
            raise ValueError(f"benchmark.gpu {self.benchmark.gpu!r} is not one of the gpus {sorted(self.gpus)}")
        return self


# ── configs/nodes_*.yaml ─────────────────────────────────────────────────────


class PowerSpec(_Strict):
    idle_fraction: float = Field(ge=0, lt=1)  # share of the server's max power drawn when idle
    provisioning_margin: float = Field(ge=0)  # site power available above the server's max, as a share of it


class ThermalSpec(_Strict):
    inlet_c: float  # cooling-air temperature at the server inlet
    rise_at_full_power_c: float = Field(gt=0)  # GPU temperature above the inlet at full power
    tau_s: float = Field(gt=0)  # time constant of the first-order temperature response
    throttle_start_c: float  # the GPU starts slowing down here ...
    throttle_full_c: float  # ... and runs max_slowdown times slower from here on
    max_slowdown: float = Field(ge=1)

    @model_validator(mode="after")
    def _throttle_range(self) -> ThermalSpec:
        if self.throttle_full_c <= self.throttle_start_c:
            raise ValueError("throttle_full_c must be above throttle_start_c")
        return self


class NodeSpec(_Strict):
    node_id: str = Field(min_length=1)
    city: str  # a city of data/processed/rtt_ms.csv
    price_zone: str  # a zone of data/processed/prices_hourly.csv
    gpu: str  # a GPU type of configs/calibration.yaml
    servers: int = Field(ge=1)
    models_loaded: list[str] = Field(min_length=1)


class ClusterConfig(_Strict):
    tick_s: float = Field(gt=0)  # telemetry period
    price_hour_utc: datetime  # the hour of real prices used before any S3 change
    min_rtt_ms: float = Field(ge=0)  # RTT for a user in the node's own metro area
    energy_price_floor_usd_kwh: float = Field(ge=0)
    power: PowerSpec
    thermal: ThermalSpec
    nodes: list[NodeSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_and_aware(self) -> ClusterConfig:
        ids = [n.node_id for n in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError(f"node ids must be unique, got {ids}")
        if self.price_hour_utc.tzinfo is None:
            raise ValueError("price_hour_utc needs a time zone (write it with a trailing Z)")
        return self

    def node(self, node_id: str) -> NodeSpec:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        raise KeyError(f"no node {node_id!r} in this setup")


# ── configs/workload.yaml ────────────────────────────────────────────────────


class ClassSpec(_Strict):
    trace: str  # a trace of data/processed/ (azure_conv, azure_code)
    share: float = Field(gt=0, le=1)  # share of all arrivals
    arrivals: Literal["trace_gaps", "poisson"]
    ttft_slo_ms: float = Field(gt=0)


class RegionSpec(_Strict):
    city: str  # a city of data/processed/rtt_ms.csv
    population: float = Field(gt=0)  # requests come from each region in proportion to this


class WorkloadConfig(_Strict):
    model: str
    rate_rps: float = Field(gt=0)  # mean arrivals per second over the whole cluster
    expected_output_error: float = Field(ge=0, lt=1)
    classes: dict[str, ClassSpec] = Field(min_length=1)
    regions: dict[str, RegionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _shares_add_up(self) -> WorkloadConfig:
        total = sum(c.share for c in self.classes.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"class shares must add up to 1, got {total}")
        return self


# ── event_traces/*.yaml ──────────────────────────────────────────────────────


class _Event(_Strict):
    at_s: float = Field(ge=0)


class ArrivalRate(_Event):
    kind: Literal["arrival_rate"]
    factor: float = Field(ge=1)  # the rate is multiplied by this ...
    duration_s: float = Field(gt=0)  # ... for this long


class EnergyPrices(_Event):
    kind: Literal["energy_prices"]
    hour_utc: datetime  # every node switches to its zone's real price at this hour


class InletTemperature(_Event):
    kind: Literal["inlet_temperature"]
    node: str
    delta_c: float  # the node's cooling-air temperature changes by this much


class RttIncrease(_Event):
    kind: Literal["rtt"]
    node: str
    delta_ms: float = Field(ge=0)  # added to the node's delay to every user region


class NodeDown(_Event):
    kind: Literal["node_down"]
    node: str


class NodeReturn(_Event):
    kind: Literal["node_return"]
    node: str
    warmup_s: float = Field(gt=0)  # status "warming" and slower for this long, then "up"
    warmup_slowdown: float = Field(ge=1)  # slowdown at the return, falling linearly to 1


Event = Annotated[
    ArrivalRate | EnergyPrices | InletTemperature | RttIncrease | NodeDown | NodeReturn,
    Field(discriminator="kind"),
]


class Scenario(_Strict):
    name: str
    description: str
    duration_s: float = Field(gt=0)
    t0_s: float = Field(ge=0)
    events: list[Event]

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        if self.t0_s >= self.duration_s:
            raise ValueError("t0_s must be inside the run")
        down: dict[str, float] = {}
        for e in sorted(self.events, key=lambda e: e.at_s):
            if e.at_s >= self.duration_s:
                raise ValueError(f"event {e.kind} at {e.at_s} s is after the end of the run")
            if isinstance(e, ArrivalRate) and e.at_s + e.duration_s > self.duration_s:
                raise ValueError("an arrival_rate change must end inside the run")
            if isinstance(e, NodeDown):
                down[e.node] = e.at_s
            if isinstance(e, NodeReturn) and e.node not in down:
                raise ValueError(f"node_return for {e.node!r} without an earlier node_down")
            if isinstance(e, EnergyPrices) and e.hour_utc.tzinfo is None:
                raise ValueError("hour_utc needs a time zone (write it with a trailing Z)")
        return self


# ── Loading ──────────────────────────────────────────────────────────────────


def _load(path: str, model: type[BaseModel]):
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return model.model_validate(data)


def load_calibration(path: str | None = None) -> CalibrationConfig:
    return _load(path or os.path.join(CONFIG_DIR, "calibration.yaml"), CalibrationConfig)


def load_cluster(path_or_size: str | int | None = None) -> ClusterConfig:
    """configs/nodes_5.yaml by default; 5 or 10 picks configs/nodes_<n>.yaml; anything else is a path."""
    if path_or_size is None or isinstance(path_or_size, int) or str(path_or_size).isdigit():
        path_or_size = os.path.join(CONFIG_DIR, f"nodes_{path_or_size or 5}.yaml")
    return _load(str(path_or_size), ClusterConfig)


def load_workload(path: str | None = None) -> WorkloadConfig:
    return _load(path or os.path.join(CONFIG_DIR, "workload.yaml"), WorkloadConfig)


def scenario_names() -> list[str]:
    return sorted(f[:-5] for f in os.listdir(EVENT_TRACE_DIR) if f.startswith("s") and f.endswith(".yaml"))


def load_scenario(name_or_path: str) -> Scenario:
    """An event trace by name (s1_stable, ...) or by path."""
    path = name_or_path if name_or_path.endswith(".yaml") else os.path.join(EVENT_TRACE_DIR, name_or_path + ".yaml")
    return _load(path, Scenario)
