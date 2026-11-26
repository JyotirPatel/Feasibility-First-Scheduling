"""
Baseline 1: Round-Robin — owner: Jyotir

Serves feasible nodes in order: node 0, node 1, node 2, back to 0.
Uses no information about the nodes at all.

Why it exists: the simplest possible policy. A control that any real
system could deploy in minutes. LinUCB must beat this after every
change event or something is wrong with the learning algorithm.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stubs.stub_policy import Policy, Outcome


class RoundRobin(Policy):

    def __init__(self):
        self._index = 0

    def choose(self, request: dict, candidates: list[dict]) -> str:
        """
        Pick the next node in order. Wraps around when the end is reached.
        candidates is already filtered by the feasibility filter.
        """
        if not candidates:
            raise ValueError("No feasible candidates — router should have rejected this request.")

        node = candidates[self._index % len(candidates)]
        self._index += 1
        return node["node_id"]

    def update(self, request: dict, node_id: str, outcome: Outcome) -> None:
        pass  # round-robin does not learn
