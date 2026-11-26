"""
Baseline 5: Static Weighted — owner: Jyotir

Scores each feasible node with a fixed formula that mixes three
factors: network RTT, queue load, and energy price. Always picks
the lowest-scoring node (lower = better on all three factors).

Score formula:
  score = w_rtt   * norm(rtt_ms)
        + w_load  * norm(queue_len + running)
        + w_price * norm(energy_price_usd_kwh)

norm() = min-max normalisation across the current candidate set,
so the weights are directly comparable regardless of units.
If all candidates have the same value for a factor (range = 0),
that factor contributes 0 to the score (no information to use).

Weights live in the config dict — never hardcoded here.
Default weights: rtt=0.5, load=0.3, price=0.2
(network delay dominates because TTFT is the primary SLO metric).

Why it exists: the strongest baseline. It tries to balance multiple
factors simultaneously — like LinUCB — but with human-chosen fixed
weights rather than learned ones. Beating this consistently is the
most important result in the experiment.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stubs.stub_policy import Policy, Outcome

DEFAULT_WEIGHTS = {
    "w_rtt":   0.5,
    "w_load":  0.3,
    "w_price": 0.2,
}


def _normalise(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


class StaticWeighted(Policy):

    def __init__(self, weights: dict | None = None):
        self._w = {**DEFAULT_WEIGHTS, **(weights or {})}

    def choose(self, request: dict, candidates: list[dict]) -> str:
        if not candidates:
            raise ValueError("No feasible candidates — router should have rejected this request.")

        user_region = request.get("user_region", "")

        def rtt(node):
            rtt_map = node.get("rtt_ms", {})
            if user_region in rtt_map:
                return rtt_map[user_region]
            return sum(rtt_map.values()) / len(rtt_map) if rtt_map else 0.0

        rtts   = [rtt(n)                                          for n in candidates]
        loads  = [n.get("queue_len", 0) + n.get("running", 0)    for n in candidates]
        prices = [n.get("energy_price_usd_kwh", 0.0)             for n in candidates]

        norm_rtts   = _normalise(rtts)
        norm_loads  = _normalise(loads)
        norm_prices = _normalise(prices)

        w = self._w
        scores = [
            w["w_rtt"]   * norm_rtts[i]   +
            w["w_load"]  * norm_loads[i]  +
            w["w_price"] * norm_prices[i]
            for i in range(len(candidates))
        ]

        best_idx = scores.index(min(scores))
        return candidates[best_idx]["node_id"]

    def update(self, request: dict, node_id: str, outcome: Outcome) -> None:
        pass  # weights are static — this baseline never learns
