"""
Context vector — owner: Sur

Builds the numbers ("context vector" x) that LinUCB sees for one
(request, candidate node) pair. The policy builds one vector per candidate.

Features, in this fixed order (brief §6.2, Sur/README.md §3):

  bias                    always 1.0 — lets each node's model learn its own base level
  input_tokens            request input length
  expected_output_tokens  request expected output length
  slo_class=<name>        one 0/1 flag per SLO class listed in the config
  ttft_slo_ms             the request's TTFT deadline (its SLO)
  rtt_ms                  network delay from the user's region to this node
  queue_len               requests waiting at the node
  running_frac            running requests / node capacity
  kv_used_frac            share of the KV cache in use
  energy_price_usd_kwh    electricity price at the node
  gpu_price_usd_hr        GPU rent price at the node
  temperature_c           GPU temperature
  warming                 1.0 if the node is warming up after an outage, else 0.0

Scaling: each raw number that has a range in the config is min-max scaled
with that range and clipped to 0..1. running_frac and kv_used_frac are
already fractions and are only clipped. So every feature lies in 0..1 and
the features are comparable.

"No context" ablation (brief §7 b): with use_context: false the vector is
just [1.0]. LinUCB then becomes a plain bandit — one average reward plus one
uncertainty bonus per node, ignoring the request and the telemetry.

Field names follow the telemetry v1 draft (brief §10.1) and the routing API
draft (§10.2). The SLO deadline is read from "ttft_slo_ms" (brief) or, if that
is absent, "slo_ms" (Jyotir's stub and Parikshit's README), because the two
drafts disagree. Requests and nodes may be dicts or objects with attributes.

A missing field raises KeyError, and a NaN / infinite / negative count raises
ValueError, so a renamed or broken telemetry field fails loudly instead of
silently feeding the policy wrong numbers.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Raw numbers that are min-max scaled with a [min, max] range from the config.
RANGED_FEATURES = (
    "input_tokens",
    "expected_output_tokens",
    "ttft_slo_ms",
    "rtt_ms",
    "queue_len",
    "energy_price_usd_kwh",
    "gpu_price_usd_hr",
    "temperature_c",
)

_MISSING = object()


# ── Config (the `features:` section of configs/policies/*.yaml) ──────────────


class Range(BaseModel):
    """Min-max scaling range for one feature."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    min: float
    max: float

    @model_validator(mode="after")
    def _max_above_min(self) -> Range:
        if self.max <= self.min:
            raise ValueError(f"max ({self.max}) must be greater than min ({self.min})")
        return self


class FeatureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_context: bool
    slo_classes: list[str] = Field(min_length=1)
    ranges: dict[str, Range]

    @field_validator("slo_classes")
    @classmethod
    def _classes_valid(cls, v: list[str]) -> list[str]:
        if any(not c for c in v):
            raise ValueError("SLO class names must be non-empty")
        if len(set(v)) != len(v):
            raise ValueError(f"duplicate SLO class in {v}")
        return v

    @field_validator("ranges")
    @classmethod
    def _ranges_complete(cls, v: dict[str, Range]) -> dict[str, Range]:
        missing = sorted(set(RANGED_FEATURES) - set(v))
        unknown = sorted(set(v) - set(RANGED_FEATURES))
        if missing:
            raise ValueError(f"missing ranges for {missing}")
        if unknown:
            raise ValueError(f"unknown range names {unknown}")
        return v


def as_feature_config(config: FeatureConfig | Mapping[str, Any]) -> FeatureConfig:
    if isinstance(config, FeatureConfig):
        return config
    if isinstance(config, Mapping):
        return FeatureConfig.model_validate(dict(config))
    raise TypeError(f"expected FeatureConfig or mapping, got {type(config).__name__}")


def feature_names(config: FeatureConfig | Mapping[str, Any]) -> list[str]:
    """Names of the context-vector entries, in order."""
    cfg = as_feature_config(config)
    if not cfg.use_context:
        return ["bias"]
    return (
        ["bias", "input_tokens", "expected_output_tokens"]
        + [f"slo_class={c}" for c in cfg.slo_classes]
        + [
            "ttft_slo_ms",
            "rtt_ms",
            "queue_len",
            "running_frac",
            "kv_used_frac",
            "energy_price_usd_kwh",
            "gpu_price_usd_hr",
            "temperature_c",
            "warming",
        ]
    )


# ── Builder ──────────────────────────────────────────────────────────────────


class ContextBuilder:
    """Builds context vectors for one validated feature config."""

    def __init__(self, config: FeatureConfig | Mapping[str, Any]):
        self.config = as_feature_config(config)
        self.names = feature_names(self.config)
        self.dim = len(self.names)
        # (min, max - min) per ranged feature, computed once.
        self._scale = {k: (r.min, r.max - r.min) for k, r in self.config.ranges.items()}

    def build(self, request: Any, node: Any) -> np.ndarray:
        """Return the context vector x for one (request, node) pair."""
        if not self.config.use_context:
            return np.ones(1)

        capacity = _count(node, "capacity", "node")
        if capacity <= 0:
            raise ValueError(f"node {_label(node)}: capacity must be > 0, got {capacity}")
        slo_class = _get(request, "slo_class", None)

        x = [
            1.0,
            self._ranged("input_tokens", _count(request, "input_tokens", "request")),
            self._ranged("expected_output_tokens", _count(request, "expected_output_tokens", "request")),
            *(1.0 if slo_class == c else 0.0 for c in self.config.slo_classes),
            self._ranged("ttft_slo_ms", slo_deadline_ms(request)),
            self._ranged("rtt_ms", rtt_to_user_ms(request, node)),
            self._ranged("queue_len", _count(node, "queue_len", "node")),
            _clip01(_count(node, "running", "node") / capacity),
            _clip01(_finite(node, "kv_used_frac", "node")),
            self._ranged("energy_price_usd_kwh", _finite(node, "energy_price_usd_kwh", "node")),
            self._ranged("gpu_price_usd_hr", _finite(node, "gpu_price_usd_hr", "node")),
            self._ranged("temperature_c", _finite(node, "temperature_c", "node")),
            1.0 if is_warming(node) else 0.0,
        ]
        return np.array(x, dtype=float)

    def _ranged(self, name: str, value: float) -> float:
        lo, span = self._scale[name]
        return _clip01((value - lo) / span)


def build_features(request: Any, node: Any, config: FeatureConfig | Mapping[str, Any]) -> np.ndarray:
    """One-off convenience wrapper. Policies keep a ContextBuilder instead."""
    return ContextBuilder(config).build(request, node)


# ── Field readers ────────────────────────────────────────────────────────────


def slo_deadline_ms(request: Any) -> float:
    """The request's TTFT deadline, from "ttft_slo_ms" or (fallback) "slo_ms"."""
    for key in ("ttft_slo_ms", "slo_ms"):
        value = _get(request, key, _MISSING)
        if value is not _MISSING:
            ms = _as_number(value, key, "request")
            if not math.isfinite(ms) or ms <= 0:
                raise ValueError(f"request {_label(request)}: {key} must be a positive finite number, got {value!r}")
            return ms
    raise KeyError(f"request {_label(request)} has neither 'ttft_slo_ms' nor 'slo_ms'")


def rtt_to_user_ms(request: Any, node: Any) -> float:
    """
    Network delay from the request's user region to this node.
    Same fallbacks as Jyotir's MinRTT baseline, so every policy treats a
    missing region the same way: unknown region -> average over the node's
    regions; node with no RTT data -> infinity (scaled to the worst value, 1.0).
    """
    rtt_map = _require(node, "rtt_ms", "node")
    if not isinstance(rtt_map, Mapping):
        raise TypeError(f"node {_label(node)}: rtt_ms must be a mapping region -> ms")
    values = {region: _as_number(ms, f"rtt_ms[{region}]", "node") for region, ms in rtt_map.items()}
    for region, ms in values.items():
        if not math.isfinite(ms) or ms < 0:
            raise ValueError(f"node {_label(node)}: rtt_ms[{region}] must be finite and >= 0, got {ms!r}")
    region = _get(request, "user_region", None)
    if region in values:
        return values[region]
    if values:
        return sum(values.values()) / len(values)
    return math.inf


def is_warming(node: Any) -> bool:
    """True if the node reports status "warming" or the filter tagged it _warming."""
    return _get(node, "status", None) == "warming" or bool(_get(node, "_warming", False))


def _get(obj: Any, key: str, default: Any = _MISSING) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _require(obj: Any, key: str, kind: str) -> Any:
    value = _get(obj, key)
    if value is _MISSING:
        raise KeyError(f"context vector: {kind} {_label(obj)} has no field '{key}'")
    return value


def _as_number(value: Any, key: str, kind: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"context vector: {kind} field '{key}' must be a number, got {value!r}")
    return float(value)


def _finite(obj: Any, key: str, kind: str) -> float:
    value = _as_number(_require(obj, key, kind), key, kind)
    if not math.isfinite(value):
        raise ValueError(f"context vector: {kind} {_label(obj)} field '{key}' is not finite: {value!r}")
    return value


def _count(obj: Any, key: str, kind: str) -> float:
    value = _finite(obj, key, kind)
    if value < 0:
        raise ValueError(f"context vector: {kind} {_label(obj)} field '{key}' is negative: {value!r}")
    return value


def _label(obj: Any) -> str:
    for key in ("node_id", "request_id"):
        value = _get(obj, key, None)
        if value is not None:
            return repr(value)
    return "<unnamed>"


def _clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)
