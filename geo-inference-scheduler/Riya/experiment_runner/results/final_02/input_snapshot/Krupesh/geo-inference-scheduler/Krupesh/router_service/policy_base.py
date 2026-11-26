"""Policy interface (brief §10.2) — owner: Krupesh. Jyotir and Sur implement this.

    choose(request, candidates: list[NodeState]) -> node_id
    update(request, node_id, outcome: Outcome) -> None

`candidates` are ONLY the nodes that passed the feasibility filter. Feedback is delayed:
`update` is called seconds (sim time) after `choose`, when the request finishes, and
`outcome.reward` has already been filled in by the router.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from api_contract.types import NodeState, Outcome, Request


class Policy(ABC):
    name: str = "base"

    def __init__(self, seed: int = 0, **params):
        self.seed = seed
        self.params = params

    @abstractmethod
    def choose(self, request: Request, candidates: list[NodeState]) -> str:
        """Return the node_id of one element of `candidates` (never empty)."""

    def update(self, request: Request, node_id: str, outcome: Outcome) -> None:  # noqa: B027
        """Learn from a finished request. Default: no-op (static baselines)."""

    @staticmethod
    def _require(candidates: list[NodeState]) -> None:
        if not candidates:
            raise ValueError("No feasible candidates - the router should have rejected this.")
