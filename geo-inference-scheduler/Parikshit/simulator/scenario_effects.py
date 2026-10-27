"""
What each scenario does to the cluster — owner: Parikshit

Runs the six event traces with one policy and seed through Krupesh's router and prints one
row per scenario:
- the share of requests that met their TTFT SLO before the change (0-200 s), in the 200 s
  after it and in the rest of the run (by arrival time; rejected and failed requests count
  as missed);
- what each change measurably did, from the run's telemetry and outcomes;
- the hard rules broken by the chosen node's true state at decision time (simulator/routers.py).

report/simulator_section.md quotes this table for Jyotir's least-load baseline, seed 0.

Usage (from the Parikshit/ folder):
    python3 simulator/scenario_effects.py                       # about 1 min
    python3 simulator/scenario_effects.py --policy sur:sw_linucb --seed 3
"""

from __future__ import annotations

import argparse
import math
import os
import sys

if __package__ in (None, ""):  # run as a script
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.cluster import Simulation
from simulator.config import (
    ArrivalRate,
    ClusterConfig,
    EnergyPrices,
    InletTemperature,
    NodeDown,
    NodeReturn,
    RttIncrease,
    Scenario,
    WorkloadConfig,
    load_cluster,
    load_scenario,
    load_workload,
    scenario_names,
)
from simulator.routers import KrupeshRouter, jyotir_filter, krupesh_engine


class RecordingRouter(KrupeshRouter):
    """Krupesh's router that also keeps each request's arrival time, node and outcome."""

    def __init__(self, engine):
        super().__init__(engine)
        self.routes: dict[str, tuple[float, str | None]] = {}
        self.outcomes: dict[str, dict] = {}

    def route(self, request: dict) -> tuple[str, str | None]:
        decision, node_id = super().route(request)
        self.routes[request["request_id"]] = (request["t_arrival"], node_id)
        return decision, node_id

    def feedback(self, outcome: dict) -> None:
        self.outcomes[outcome["request_id"]] = outcome
        super().feedback(outcome)


def windows(scen: Scenario) -> list[tuple[float, float]]:
    """Before t0, then the rest of the run in two halves: 0-200, 200-400 and 400-600 s for the shipped traces."""
    mid = scen.t0_s + (scen.duration_s - scen.t0_s) / 2
    return [(0.0, scen.t0_s), (scen.t0_s, mid), (mid, scen.duration_s)]


def slo_share(router: RecordingRouter, lo: float, hi: float) -> float:
    ids = [rid for rid, (t, _) in router.routes.items() if lo <= t < hi]
    met = sum(1 for rid in ids if rid in router.outcomes and router.outcomes[rid]["slo_met"])
    return met / len(ids) if ids else math.nan


def node_share(router: RecordingRouter, node: str, lo: float, hi: float) -> float:
    chosen = [n for t, n in router.routes.values() if lo <= t < hi]
    return sum(n == node for n in chosen) / len(chosen) if chosen else math.nan


def _records(sim: Simulation, node: str, lo: float = 0.0, hi: float = math.inf) -> list[dict]:
    return [r for r in sim.telemetry_log if r["node_id"] == node and lo <= r["t"] < hi]


def slot_use(sim: Simulation, lo: float, hi: float) -> float:
    """Running requests ÷ capacity over the nodes that are not down, in the ticks of [lo, hi)."""
    ticks = [r for r in sim.telemetry_log if lo <= r["t"] < hi and r["status"] != "down"]
    return sum(r["running"] for r in ticks) / sum(r["capacity"] for r in ticks)


def describe(event, sim: Simulation, router: RecordingRouter, limits: dict) -> str:
    """One sentence on what this event measurably did in the run."""
    end = sim.scenario.duration_s
    if isinstance(event, ArrivalRate):
        lo, hi = event.at_s, event.at_s + event.duration_s
        before = sum(t < lo for t, _ in router.routes.values()) / lo if lo else math.nan
        during = sum(lo <= t < hi for t, _ in router.routes.values()) / event.duration_s
        return (
            f"arrivals {before:.0f} → {during:.0f} req/s for {event.duration_s:.0f} s; "
            f"cluster slot use {slot_use(sim, 0, lo):.0%} → {slot_use(sim, lo, hi):.0%}"
        )
    if isinstance(event, EnergyPrices):
        t_before = max(r["t"] for r in sim.telemetry_log if r["t"] < event.at_s)
        t_after = min(r["t"] for r in sim.telemetry_log if r["t"] >= event.at_s)
        before = {r["node_id"]: r["energy_price_usd_kwh"] for r in sim.telemetry_log if r["t"] == t_before}
        after = {r["node_id"]: r["energy_price_usd_kwh"] for r in sim.telemetry_log if r["t"] == t_after}
        a, b = (min(sorted(p), key=p.get) for p in (before, after))
        return f"cheapest node {a} → {b}; {a} ${before[a]:.3f} → ${after[a]:.3f}/kWh, {b} ${after[b]:.3f}/kWh"
    if isinstance(event, InletTemperature):
        before, after = _records(sim, event.node, 0, event.at_s), _records(sim, event.node, event.at_s)
        limit = limits["temperature_limit_c"]
        hot = sum(r["temperature_c"] >= limit for r in after)
        return (
            f"{event.node}: peak {max(r['temperature_c'] for r in before):.0f} → "
            f"{max(r['temperature_c'] for r in after):.0f} °C, at or above {limit:g} °C in {hot} of {len(after)} "
            f"ticks; gets {node_share(router, event.node, 0, event.at_s):.0%} → "
            f"{node_share(router, event.node, event.at_s, end):.0%} of requests"
        )
    if isinstance(event, RttIncrease):
        regions = sim.workload.regions
        region = max(regions, key=lambda k: regions[k].population)
        before, after = _records(sim, event.node, 0, event.at_s)[-1], _records(sim, event.node, event.at_s)[0]
        return (
            f"{event.node}: RTT from {region} {before['rtt_ms'][region]:.0f} → {after['rtt_ms'][region]:.0f} ms; "
            f"gets {node_share(router, event.node, 0, event.at_s):.0%} → "
            f"{node_share(router, event.node, event.at_s, end):.0%} of requests"
        )
    if isinstance(event, NodeDown):
        lost = next(e["failed_requests"] for e in sim.event_log if e["kind"] == "node_down" and e["node"] == event.node)
        late = sim.stats["failed_at_arrival"]
        return f"{event.node} down: {lost} running or queued requests lost, {late} sent to it while down"
    if isinstance(event, NodeReturn):
        lo, hi = event.at_s, event.at_s + event.warmup_s
        return (
            f"{event.node} back at {lo:.0f} s, warming until {hi:.0f} s; gets "
            f"{node_share(router, event.node, lo, hi):.0%} of requests while warming, "
            f"{node_share(router, event.node, hi, end):.0%} after "
            f"({node_share(router, event.node, 0, sim.scenario.t0_s):.0%} before the outage)"
        )
    raise TypeError(f"unknown event {event!r}")  # pragma: no cover - the config models allow only the kinds above


def effects(
    scenario: Scenario | str,
    policy: str = "jyotir:least_load",
    seed: int = 0,
    *,
    workload: WorkloadConfig | None = None,
    cluster: ClusterConfig | None = None,
) -> dict:
    """Run one scenario and return its row of the table."""
    scen = load_scenario(scenario) if isinstance(scenario, str) else scenario
    engine, _ = krupesh_engine(policy, seed, scen.name)
    router = RecordingRouter(engine)
    sim = Simulation(router, scen, seed, workload=workload, cluster=cluster)
    stats = sim.run()
    engine.finish()
    engine.writer.close()
    limits = jyotir_filter()[1]
    w = windows(scen)
    return {
        "scenario": scen.name,
        "requests": stats["requests"],
        "windows": w,
        "slo_met": [slo_share(router, lo, hi) for lo, hi in w],
        "changes": [describe(e, sim, router, limits) for e in sorted(scen.events, key=lambda e: e.at_s)],
        "true_state_violations": dict(sorted(router.true_state_violations.items())),
    }


def table(rows: list[dict]) -> str:
    """The rows as a Markdown table."""
    w = rows[0]["windows"]
    if any(r["windows"] != w for r in rows):
        raise ValueError("the scenarios have different windows; print them in separate tables")
    head = [
        "Scenario",
        "Requests",
        *(f"SLO met {lo:g}–{hi:g} s" for lo, hi in w),
        "What the change did",
        "True-state violations",
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        violations = ", ".join(f"{k} {v:,}" for k, v in r["true_state_violations"].items()) or "none"
        cells = [
            r["scenario"],
            f"{r['requests']:,}",
            *(f"{s:.1%}" for s in r["slo_met"]),
            "; ".join(r["changes"]) or "nothing",
            violations,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", default="jyotir:least_load", help="a policy name of Krupesh's registry")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--nodes", default="5", help="5, 10 or a path to a nodes YAML file")
    ap.add_argument("--scenarios", nargs="+", default=None, help="default: all six")
    args = ap.parse_args(argv)
    cluster = load_cluster(args.nodes)
    rows = [effects(s, args.policy, args.seed, cluster=cluster) for s in (args.scenarios or scenario_names())]
    print(f"policy {args.policy}, seed {args.seed}, {len(cluster.nodes)} nodes, {load_workload().rate_rps:g} req/s\n")
    print(table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
