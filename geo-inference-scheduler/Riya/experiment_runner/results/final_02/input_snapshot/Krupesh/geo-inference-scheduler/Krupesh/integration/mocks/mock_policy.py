"""MOCK learning policy — stands in for Sur's LinUCB / SW-LinUCB. NOT Sur's algorithm.

It exists only to prove that the router's delayed-feedback path works for a policy that
learns: it caches the choice per request_id in choose(), receives the reward in update()
seconds later, and keeps a running mean reward per (node, user_region). It picks the best
mean, trying every (node, region) pair once first. No contexts, no confidence bounds.

TODO(Sur): replace with LinUCB and sliding-window LinUCB implementing router_service.policy_base.Policy,
then register them in router_service/registry.py (EXTRA_POLICIES["sur:sw_linucb"] = ...).
"""

from __future__ import annotations

from collections import defaultdict

from api_contract.types import NodeState, Outcome, Request
from router_service.policy_base import Policy


class MockLearningPolicy(Policy):
    name = "mock:learning"

    def __init__(self, seed: int = 0, **params):
        super().__init__(seed, **params)
        self.sum: dict[tuple[str, str], float] = defaultdict(float)
        self.n: dict[tuple[str, str], int] = defaultdict(int)
        self.pending: dict[str, tuple[str, str]] = {}

    def choose(self, request: Request, candidates: list[NodeState]) -> str:
        self._require(candidates)

        def score(node: NodeState) -> float:
            k = (node.node_id, request.user_region)
            return float("inf") if self.n[k] == 0 else self.sum[k] / self.n[k]

        best = max(candidates, key=score)  # ties -> first candidate (deterministic)
        self.pending[request.request_id] = (best.node_id, request.user_region)
        return best.node_id

    def update(self, request: Request, node_id: str, outcome: Outcome) -> None:
        key = self.pending.pop(request.request_id, None)
        if key is None or outcome.reward is None:
            return
        self.sum[key] += outcome.reward
        self.n[key] += 1
