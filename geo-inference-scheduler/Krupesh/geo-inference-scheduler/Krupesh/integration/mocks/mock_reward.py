"""MOCK reward — stands in for Sur's reward function. NOT Sur's implementation.

Implements only the shape in brief §6.3 with placeholder weights, so the router's
feedback path can be tested:
    r = 1.0*[SLO met] - 0.3*min(TTFT/1000 ms, 1) - 0.2*min(energy cost/$0.0001, 1)
        - 0.1*clip((T - 70)/(85 - 70), 0, 1)
TODO(Sur): replace with the real reward (weights from configs, owned by Sur).
Required signature: reward_fn(outcome: Outcome, node_at_dispatch: NodeState) -> float
"""

from __future__ import annotations

import math

from api_contract.types import NodeState, Outcome


def mock_reward(outcome: Outcome, node: NodeState) -> float:
    slo = 1.0 if (outcome.slo_met and not outcome.failed) else 0.0
    if outcome.failed or not math.isfinite(outcome.ttft_ms):
        lat = 1.0
    else:
        lat = min(max(outcome.ttft_ms, 0.0) / 1000.0, 1.0)
    energy = min(outcome.energy_kwh * node.energy_price_usd_kwh / 1e-4, 1.0)
    thermal = min(max((node.temperature_c - 70.0) / 15.0, 0.0), 1.0)
    return slo - 0.3 * lat - 0.2 * energy - 0.1 * thermal
