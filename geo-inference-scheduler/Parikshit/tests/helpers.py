"""Shared test helpers: the real scenarios and workload, made shorter and lighter so tests run fast."""

from simulator.config import Scenario, load_scenario, load_workload

SHORT = 0.2  # every time in a scenario is multiplied by this: 600 s -> 120 s, t0 200 s -> 40 s
TEST_RATE_RPS = 20.0


def short_scenario(name: str, factor: float = SHORT) -> Scenario:
    """The shipped event trace with every time (and duration) scaled by `factor`; the changes themselves are kept."""
    s = load_scenario(name)
    events = []
    for e in s.events:
        update = {"at_s": e.at_s * factor}
        for key in ("duration_s", "warmup_s"):
            if hasattr(e, key):
                update[key] = getattr(e, key) * factor
        events.append(e.model_copy(update=update))
    return s.model_copy(update={"duration_s": s.duration_s * factor, "t0_s": s.t0_s * factor, "events": events})


def light_workload(rate: float = TEST_RATE_RPS):
    return load_workload().model_copy(update={"rate_rps": rate})


def by_node(records: list[dict], node_id: str) -> list[dict]:
    return [r for r in records if r["node_id"] == node_id]


class PinRouter:
    """Sends every request to one node (or rejects all when node_id is None); records what it was told."""

    def __init__(self, node_id: str | None):
        self.node_id = node_id
        self.ticks: list[list[dict]] = []
        self.requests: list[dict] = []
        self.outcomes: dict[str, dict] = {}
        self.after: list[tuple] = []

    def ingest_telemetry(self, records):
        self.ticks.append(records)

    def route(self, request):
        self.requests.append(request)
        return ("route", self.node_id) if self.node_id else ("reject", None)

    def feedback(self, outcome):
        assert outcome["request_id"] not in self.outcomes, "two outcomes for one request"
        self.outcomes[outcome["request_id"]] = outcome

    def after_route(self, request, node_id, true_record):
        self.after.append((request["request_id"], node_id, true_record["status"]))
