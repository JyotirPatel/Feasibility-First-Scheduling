"""
Baseline 2: Min RTT (Closest Node) — owner: Jyotir

Always picks the feasible node with the lowest network round-trip
time to the user's region.

Why it exists: network delay is a large part of TTFT. Getting the
request to a nearby node fast is a sensible real-world heuristic
used by CDNs and geo-routers.

Weakness: ignores load, cost, and temperature. If the closest node
overheats (S4) or its network degrades (S5), this baseline keeps
sending requests there until it fully fails.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stubs.stub_policy import Policy, Outcome


class MinRTT(Policy):

    def choose(self, request: dict, candidates: list[dict]) -> str:
        """
        Pick the node with the lowest RTT to the user's region.
        Falls back to the first candidate if the region is not found.
        """
        if not candidates:
            raise ValueError("No feasible candidates — router should have rejected this request.")

        user_region = request.get("user_region", "")

        def rtt_for(node: dict) -> float:
            rtt_map = node.get("rtt_ms", {})
            # use the user's region RTT; fall back to average if region unknown
            if user_region in rtt_map:
                return rtt_map[user_region]
            if rtt_map:
                return sum(rtt_map.values()) / len(rtt_map)
            return float("inf")

        return min(candidates, key=rtt_for)["node_id"]

    def update(self, request: dict, node_id: str, outcome: Outcome) -> None:
        pass  # min-RTT does not learn
