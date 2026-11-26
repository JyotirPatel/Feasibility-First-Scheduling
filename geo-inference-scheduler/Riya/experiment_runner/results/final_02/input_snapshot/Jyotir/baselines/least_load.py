"""
Baseline 3: Least Load — owner: Jyotir

Always picks the feasible node with the fewest waiting + running
requests (i.e. the shortest total queue).

Why it exists: a node with a shorter queue starts processing sooner,
so queue wait time (part of TTFT) is lower. This is classic load
balancing — spread work evenly to avoid bottlenecks.

Weakness: ignores network delay, energy cost, and temperature.
Two nodes with equal queue length but very different RTTs are
treated identically. In a traffic burst (S2) that fills every
queue simultaneously, this degrades to arbitrary selection.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stubs.stub_policy import Policy, Outcome


class LeastLoad(Policy):

    def choose(self, request: dict, candidates: list[dict]) -> str:
        if not candidates:
            raise ValueError("No feasible candidates — router should have rejected this request.")

        def total_load(node: dict) -> int:
            return node.get("queue_len", 0) + node.get("running", 0)

        return min(candidates, key=total_load)["node_id"]

    def update(self, request: dict, node_id: str, outcome: Outcome) -> None:
        pass
