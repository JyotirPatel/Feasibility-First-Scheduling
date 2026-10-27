"""
Reward — owner: Sur

After each request finishes, the policy learns from one number (brief §6.3):

    r = w1·[SLO met] − w2·latency − w3·energy cost − w4·thermal stress

  [SLO met]       1 if the outcome says the request met its SLO, else 0.
  latency         the outcome's TTFT (latency_metric: ttft_ms) or end-to-end
                  time (latency_metric: e2e_ms), divided by latency_max_ms.
  energy cost     energy_kwh × the node's electricity price when it was chosen
                  (energy_cost_source: energy_usd), or the outcome's total
                  cost_usd, which includes GPU rent (energy_cost_source: cost_usd);
                  divided by energy_cost_max_usd.
  thermal stress  the node's temperature when it was chosen, mapped linearly
                  from thermal_safe_c (0) up to thermal_limit_c (1).

Every term except [SLO met] is clipped to 0..1, so r always lies in
[−(w2 + w3 + w4), w1]. Weights and scales live in configs/policies/*.yaml,
never in this file. With the default weights the SLO term dominates: meeting
the SLO always scores higher than missing it.

A missing value (None), NaN or infinity in the outcome — for example a request
lost when its node went down — gets the worst value for its term, so a failure
can never score better than a slow success. A negative time or energy is a
data error and raises ValueError.

`node` is the chosen node's snapshot at decision time (the policy keeps it
from choose() until the feedback arrives). The router can call
compute_reward() with the same inputs to fill the decision log's reward
column (brief §10.3).
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

_MISSING = object()

# Node numbers (from the decision-time snapshot) that the reward reads.
NODE_FIELDS = ("temperature_c", "energy_price_usd_kwh")


# ── Config (the `reward:` section of configs/policies/*.yaml) ────────────────


class RewardWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    slo_met: float = Field(ge=0)
    latency: float = Field(ge=0)
    energy_cost: float = Field(ge=0)
    thermal_stress: float = Field(ge=0)


class RewardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    weights: RewardWeights
    latency_metric: Literal["ttft_ms", "e2e_ms"]
    latency_max_ms: float = Field(gt=0)
    energy_cost_source: Literal["energy_usd", "cost_usd"]
    energy_cost_max_usd: float = Field(gt=0)
    thermal_safe_c: float
    thermal_limit_c: float

    @model_validator(mode="after")
    def _limit_above_safe(self) -> RewardConfig:
        if self.thermal_limit_c <= self.thermal_safe_c:
            raise ValueError(
                f"thermal_limit_c ({self.thermal_limit_c}) must be greater than thermal_safe_c ({self.thermal_safe_c})"
            )
        return self


def as_reward_config(config: RewardConfig | Mapping[str, Any]) -> RewardConfig:
    if isinstance(config, RewardConfig):
        return config
    if isinstance(config, Mapping):
        return RewardConfig.model_validate(dict(config))
    raise TypeError(f"expected RewardConfig or mapping, got {type(config).__name__}")


# ── Reward ───────────────────────────────────────────────────────────────────


def reward_terms(node: Any, outcome: Any, config: RewardConfig | Mapping[str, Any]) -> dict[str, float]:
    """The four reward terms before weighting: slo_met is 0/1, the rest 0..1."""
    cfg = as_reward_config(config)

    latency_ms = _optional_nonneg(outcome, cfg.latency_metric, "outcome")

    if cfg.energy_cost_source == "energy_usd":
        energy_kwh = _optional_nonneg(outcome, "energy_kwh", "outcome")
        price = _required_finite(node, "energy_price_usd_kwh", "node")
        energy_usd = None if energy_kwh is None or not math.isfinite(energy_kwh) else energy_kwh * price
    else:
        energy_usd = _optional_number(outcome, "cost_usd", "outcome")

    temperature = _optional_number(node, "temperature_c", "node", required=True)

    return {
        "slo_met": _slo_met(outcome),
        "latency": _scaled_or_worst(latency_ms, 0.0, cfg.latency_max_ms),
        "energy_cost": _scaled_or_worst(energy_usd, 0.0, cfg.energy_cost_max_usd),
        "thermal_stress": _scaled_or_worst(temperature, cfg.thermal_safe_c, cfg.thermal_limit_c),
    }


def compute_reward(node: Any, outcome: Any, config: RewardConfig | Mapping[str, Any]) -> float:
    """r = w1·[SLO met] − w2·latency − w3·energy cost − w4·thermal stress."""
    cfg = as_reward_config(config)
    t = reward_terms(node, outcome, cfg)
    w = cfg.weights
    return (
        w.slo_met * t["slo_met"]
        - w.latency * t["latency"]
        - w.energy_cost * t["energy_cost"]
        - w.thermal_stress * t["thermal_stress"]
    )


def reward_bounds(config: RewardConfig | Mapping[str, Any]) -> tuple[float, float]:
    """(lowest, highest) reward the config can produce."""
    w = as_reward_config(config).weights
    return -(w.latency + w.energy_cost + w.thermal_stress), w.slo_met


def slo_term_dominates(config: RewardConfig | Mapping[str, Any]) -> bool:
    """True if meeting the SLO always beats missing it, whatever the other terms are."""
    w = as_reward_config(config).weights
    return w.slo_met > w.latency + w.energy_cost + w.thermal_stress


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get(obj: Any, key: str, default: Any = _MISSING) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _slo_met(outcome: Any) -> float:
    value = _get(outcome, "slo_met")
    if value is _MISSING:
        raise KeyError("reward: outcome has no field 'slo_met'")
    if value is None:
        return 0.0  # unknown -> treated as missed
    if isinstance(value, (bool, np.bool_)):
        return 1.0 if value else 0.0
    raise TypeError(f"reward: slo_met must be true/false, got {value!r}")


def _optional_number(obj: Any, key: str, kind: str, required: bool = True) -> float | None:
    """The field as float; None stays None. NaN/inf pass through (scaled to worst later)."""
    value = _get(obj, key)
    if value is _MISSING:
        if required:
            raise KeyError(f"reward: {kind} has no field '{key}'")
        return None
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"reward: {kind} field '{key}' must be a number, got {value!r}")
    return float(value)


def _optional_nonneg(obj: Any, key: str, kind: str) -> float | None:
    value = _optional_number(obj, key, kind)
    if value is not None and value < 0:  # NaN compares False, -inf is caught here
        raise ValueError(f"reward: {kind} field '{key}' is negative: {value!r}")
    return value


def _required_finite(obj: Any, key: str, kind: str) -> float:
    value = _optional_number(obj, key, kind)
    if value is None or not math.isfinite(value):
        raise ValueError(f"reward: {kind} field '{key}' must be a finite number, got {value!r}")
    return value


def _scaled_or_worst(value: float | None, lo: float, hi: float) -> float:
    """Map lo..hi to 0..1 and clip; unknown (None / NaN / ±inf) -> 1.0, the worst."""
    if value is None or not math.isfinite(value):
        return 1.0
    return min(max((value - lo) / (hi - lo), 0.0), 1.0)
