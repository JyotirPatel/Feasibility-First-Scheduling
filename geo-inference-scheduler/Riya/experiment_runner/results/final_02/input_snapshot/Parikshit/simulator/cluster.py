"""
The simulated cluster — owner: Parikshit

Runs one scenario with SimPy. The simulator drives a router through three calls, in
simulated time only (handbook §5.2):

    router.ingest_telemetry(records)     every tick: one telemetry record per node (schema v1)
    router.route(request) -> (decision, node_id)     every arrival
    router.feedback(outcome)             when a request finishes, or fails (failed=True)

An optional fourth call, router.after_route(request, node_id, true_record), receives the
chosen node's true state at the moment of the decision. The router decides on telemetry
that can be up to one tick old, so the two can differ (simulator/routers.py records it).

A scenario change at time t (an event of the trace, or the end of a node's warm-up) always
comes before the telemetry tick and any arrival at t: both apply every change that is due
before they do anything else, whatever order SimPy wakes the processes in. Arrivals stop
at the end of the run; requests still in flight are then served to completion, so every
routed request gets exactly one outcome.
"""

from __future__ import annotations

import bisect
import itertools
from collections import Counter

import simpy

from simulator.calibration import GpuConstants, default_constants
from simulator.config import (
    ClusterConfig,
    NodeReturn,
    Scenario,
    WorkloadConfig,
    load_calibration,
    load_cluster,
    load_scenario,
    load_workload,
)
from simulator.data import Prices, RttTable, Trace, load_prices, load_rtt, load_trace
from simulator.events import apply_event
from simulator.node import Job, Node
from simulator.workload import WorkItem, generate
from telemetry.schema import validate_record


class Simulation:
    def __init__(
        self,
        router,
        scenario: Scenario | str,
        seed: int,
        *,
        cluster: ClusterConfig | None = None,
        workload: WorkloadConfig | None = None,
        constants: dict[str, GpuConstants] | None = None,
        prices: Prices | None = None,
        rtt: RttTable | None = None,
        traces: dict[str, Trace] | None = None,
        validate_telemetry: bool = True,
    ):
        self.router = router
        self.scenario = load_scenario(scenario) if isinstance(scenario, str) else scenario
        self.seed = seed
        self.cluster = cluster or load_cluster()
        self.workload = workload or load_workload()
        calibration = load_calibration()
        self.constants = constants or default_constants(calibration, self.workload)
        self.prices = prices or load_prices()
        rtt = rtt or load_rtt()
        traces = traces or {c.trace: load_trace(c.trace) for c in self.workload.classes.values()}
        self.validate_telemetry = validate_telemetry

        for spec in self.cluster.nodes:
            if spec.gpu not in calibration.gpus:
                raise KeyError(f"{spec.node_id}: unknown GPU type {spec.gpu!r}")
        for e in self.scenario.events:
            if getattr(e, "node", None) is not None:
                self.cluster.node(e.node)  # raises for a node the setup does not have

        self.env = simpy.Environment()
        self.nodes: dict[str, Node] = {}
        for spec in self.cluster.nodes:
            node_rtt = {
                region: rtt.ms(r.city, spec.city, self.cluster.min_rtt_ms)
                for region, r in self.workload.regions.items()
            }
            price = self.prices.usd_kwh(
                spec.price_zone, self.cluster.price_hour_utc, self.cluster.energy_price_floor_usd_kwh
            )
            self.nodes[spec.node_id] = Node(
                self.env,
                spec,
                calibration.gpus[spec.gpu],
                self.constants[spec.gpu],
                self.cluster,
                node_rtt,
                price,
                self._deliver,
            )
        self.items: list[WorkItem] = generate(self.workload, self.scenario, seed, traces)
        self.event_log: list[dict] = []
        self.telemetry_log: list[dict] = []
        self.stats = Counter()
        self.routed_by_node = Counter()
        self._order = itertools.count()  # keeps changes at the same time in trace order
        self._due: list[tuple[float, int, object]] = []  # (time, order, change), sorted
        for event in sorted(self.scenario.events, key=lambda e: e.at_s):
            self._schedule(event.at_s, event)

    # ── scenario changes ─────────────────────────────────────────────────────

    def _schedule(self, at_s: float, change) -> None:
        """change: a scenario event, or the id of a node whose warm-up ends at at_s."""
        bisect.insort(self._due, (at_s, next(self._order), change))

    def _apply_due_changes(self) -> None:
        """Apply, in time order, every change due by now that has not been applied yet."""
        while self._due and self._due[0][0] <= self.env.now:
            _, _, change = self._due.pop(0)
            if isinstance(change, str):
                self.nodes[change].warm_done()
                self.event_log.append({"kind": "warm_done", "at_s": self.env.now, "node": change})
                continue
            self.event_log.append(apply_event(change, self.nodes, self.cluster, self.prices))
            if isinstance(change, NodeReturn):
                self._schedule(change.at_s + change.warmup_s, change.node)

    # ── processes ────────────────────────────────────────────────────────────

    def _changes(self):
        while self._due:
            yield self.env.timeout(self._due[0][0] - self.env.now)
            self._apply_due_changes()

    def _ticks(self):
        tick = self.cluster.tick_s
        k = 0
        while k * tick < self.scenario.duration_s:
            yield self.env.timeout(k * tick - self.env.now)
            self._apply_due_changes()
            records = [n.telemetry(self.env.now) for n in self.nodes.values()]
            if self.validate_telemetry:
                for r in records:
                    problems = validate_record(r)
                    if problems:
                        raise ValueError(f"invalid telemetry from {r.get('node_id')}: {problems}")
            self.telemetry_log.extend(records)
            self.router.ingest_telemetry(records)
            self.stats["ticks"] += 1
            k += 1

    def _arrivals(self):
        for item in self.items:
            yield self.env.timeout(item.request["t_arrival"] - self.env.now)
            self._apply_due_changes()
            self.stats["requests"] += 1
            decision, node_id = self.router.route(dict(item.request))
            if decision == "reject":
                self.stats["rejected"] += 1
                continue
            if decision != "route" or node_id not in self.nodes:
                raise ValueError(f"router answered {decision!r} / {node_id!r} for {item.request['request_id']}")
            node = self.nodes[node_id]
            if hasattr(self.router, "after_route"):
                self.router.after_route(item.request, node_id, node.telemetry(self.env.now))
            self.stats["routed"] += 1
            self.routed_by_node[node_id] += 1
            if node.status == "down":
                self.stats["failed_at_arrival"] += 1
            node.submit(Job(item.request, item.output_tokens, node.rtt_to(item.request["user_region"])))

    def _deliver(self, outcome: dict) -> None:
        self.stats["failed" if outcome["failed"] else "completed"] += 1
        self.router.feedback(outcome)

    # ── run ──────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """Run the scenario to the end and until every routed request has its outcome."""
        self.env.process(self._changes())
        self.env.process(self._ticks())
        self.env.process(self._arrivals())
        self.env.run()
        if self.stats["completed"] + self.stats["failed"] != self.stats["routed"]:
            raise RuntimeError(
                f"{self.stats['routed']} routed requests but {self.stats['completed']} completed and "
                f"{self.stats['failed']} failed"
            )
        return self.summary()

    def summary(self) -> dict:
        ticks = [r for r in self.telemetry_log if r["status"] != "down"]
        used = sum(r["running"] for r in ticks)
        slots = sum(r["capacity"] for r in ticks)
        return {
            "scenario": self.scenario.name,
            "seed": self.seed,
            "requests": self.stats["requests"],
            "routed": self.stats["routed"],
            "rejected": self.stats["rejected"],
            "completed": self.stats["completed"],
            "failed": self.stats["failed"],
            "failed_at_arrival": self.stats["failed_at_arrival"],
            "ticks": self.stats["ticks"],
            "mean_slot_use": used / slots if slots else 0.0,
            "routed_by_node": dict(sorted(self.routed_by_node.items())),
            "end_time_s": self.env.now,
            "events": self.event_log,
        }
