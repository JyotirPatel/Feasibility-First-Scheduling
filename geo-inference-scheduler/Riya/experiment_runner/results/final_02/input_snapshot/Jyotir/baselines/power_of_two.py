"""
Baseline 6 (optional): Power of Two Choices — owner: Jyotir

Pick 2 random feasible nodes. Send to the one with less total load.

Why it exists: Mitzenmacher (2001) proved that picking the better
of 2 random choices reduces maximum queue length from O(log n) to
O(log log n) — a large improvement from almost no extra work.
It outperforms round-robin significantly while using zero information
about RTT, cost, or temperature.

This is optional — the five main baselines are enough for the
comparison. Add it if time allows; it makes for a good discussion
point in the report.
"""

import random
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stubs.stub_policy import Policy, Outcome


class PowerOfTwo(Policy):

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def choose(self, request: dict, candidates: list[dict]) -> str:
        if not candidates:
            raise ValueError("No feasible candidates — router should have rejected this request.")

        if len(candidates) == 1:
            return candidates[0]["node_id"]

        a, b = self._rng.sample(candidates, 2)

        load_a = a.get("queue_len", 0) + a.get("running", 0)
        load_b = b.get("queue_len", 0) + b.get("running", 0)

        return (a if load_a <= load_b else b)["node_id"]

    def update(self, request: dict, node_id: str, outcome: Outcome) -> None:
        pass
