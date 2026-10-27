"""
Scenario events — owner: Parikshit

Applies the changes of an event trace (event_traces/s*.yaml) to the nodes at their times:

  arrival_rate       S2: more requests for a while. Already built into the workload by
                     simulator/workload.py, so nothing changes on the nodes.
  energy_prices      S3: every node switches to its zone's real price at another hour.
  inlet_temperature  S4: a node's cooling air gets hotter, so it heats up, throttles and can
                     cross the filter's temperature limit.
  rtt                S5: the delay from every user region to a node rises.
  node_down          S6: a node fails; its running and queued requests fail.
  node_return        S6: the node comes back "warming" and slower; "up" after its warm-up.

change_times() gives the moments the metrics measure recovery from: t0 for every scenario,
plus the node's return in S6.
"""

from __future__ import annotations

from simulator.config import (
    ArrivalRate,
    ClusterConfig,
    EnergyPrices,
    InletTemperature,
    NodeDown,
    NodeReturn,
    RttIncrease,
    Scenario,
    load_scenario,
    scenario_names,
)
from simulator.data import Prices
from simulator.node import Node

__all__ = ["apply_event", "change_times", "load_scenario", "scenario_names"]


def apply_event(event, nodes: dict[str, Node], cluster: ClusterConfig, prices: Prices) -> dict:
    """Apply one event now; returns a short record of what happened (kept in the run's event log)."""
    record = {"kind": event.kind, "at_s": event.at_s}
    if isinstance(event, ArrivalRate):
        record["note"] = f"arrival rate × {event.factor} for {event.duration_s} s (built into the workload)"
    elif isinstance(event, EnergyPrices):
        new = {
            nid: prices.usd_kwh(cluster.node(nid).price_zone, event.hour_utc, cluster.energy_price_floor_usd_kwh)
            for nid in nodes
        }
        for nid, price in new.items():
            nodes[nid].set_energy_price(price)
        record["usd_kwh"] = new
    elif isinstance(event, InletTemperature):
        nodes[event.node].change_inlet(event.delta_c)
        record.update(node=event.node, inlet_c=nodes[event.node].inlet_c)
    elif isinstance(event, RttIncrease):
        nodes[event.node].rtt_extra_ms += event.delta_ms
        record.update(node=event.node, rtt_extra_ms=nodes[event.node].rtt_extra_ms)
    elif isinstance(event, NodeDown):
        record.update(node=event.node, failed_requests=nodes[event.node].go_down())
    elif isinstance(event, NodeReturn):
        nodes[event.node].come_back(event.warmup_s, event.warmup_slowdown)
        record.update(node=event.node, warm_until_s=event.at_s + event.warmup_s)
    else:  # pragma: no cover - the config models allow only the kinds above
        raise TypeError(f"unknown event {event!r}")
    return record


def change_times(scenario: Scenario) -> dict[str, float]:
    """When things change: t0 always; for S6 also the node's return."""
    times = {"t0": scenario.t0_s}
    for e in scenario.events:
        if isinstance(e, NodeReturn):
            times["return"] = e.at_s
    return times
