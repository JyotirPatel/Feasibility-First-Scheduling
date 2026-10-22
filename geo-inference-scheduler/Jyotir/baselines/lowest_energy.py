"""
Baseline 4: Lowest Energy Cost — owner: Jyotir

Always picks the feasible node with the cheapest electricity price
(energy_price_usd_kwh) at this moment.

Why it exists: electricity cost varies by region and time of day
(NYISO/CAISO publish hourly prices). Routing to the cheapest region
saves real money at scale. Directly relevant to Scenario S3
(price / renewable shift).

Weakness: ignores latency, load, and temperature. Routing everything
to the cheapest node overloads it, causing queue buildup and SLO
misses. A cheap node might be cheap because it is far away.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stubs.stub_policy import Policy, Outcome


class LowestEnergy(Policy):

    def choose(self, request: dict, candidates: list[dict]) -> str:
        if not candidates:
            raise ValueError("No feasible candidates — router should have rejected this request.")

        return min(candidates, key=lambda n: n.get("energy_price_usd_kwh", float("inf")))["node_id"]

    def update(self, request: dict, node_id: str, outcome: Outcome) -> None:
        pass
