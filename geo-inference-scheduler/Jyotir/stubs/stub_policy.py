# Stub for Krupesh's Policy base class and shared data types.
# Replace this import with Krupesh's real module once it is ready:
#   from src.geosched.policies.base import Policy, Outcome
# Everything else in your baseline files stays the same.

from dataclasses import dataclass
from typing import Optional


@dataclass
class Outcome:
    """What the simulator reports back after a request finishes."""
    ttft_ms: float          # time to first token (ms)
    e2e_ms: float           # end-to-end total time (ms)
    slo_met: bool           # did TTFT beat the SLO deadline?
    energy_kwh: float       # energy consumed by this request
    cost_usd: float         # total cost (energy + GPU rent)
    reward: float           # computed reward signal (Sur fills this in)


class Policy:
    """
    Base class every policy (baseline or LinUCB) must implement.
    Krupesh owns the real version of this — this stub keeps the same
    method signatures so your baselines work now and merge cleanly later.
    """

    def choose(self, request: dict, candidates: list[dict]) -> str:
        """
        Pick one node from the list of feasible candidates.

        Args:
            request   : the incoming request dict (from fake_node.FAKE_REQUEST)
            candidates: list of node dicts that passed the feasibility filter

        Returns:
            node_id (str) of the chosen node
        """
        raise NotImplementedError("Each policy must implement choose()")

    def update(self, request: dict, node_id: str, outcome: Outcome) -> None:
        """
        Learn from what happened after a request was served.
        Baselines ignore this (they do not learn). LinUCB uses it.

        Args:
            request : the original request dict
            node_id : the node that was chosen
            outcome : what the simulator reported back
        """
        pass  # baselines do not learn — default is a no-op
