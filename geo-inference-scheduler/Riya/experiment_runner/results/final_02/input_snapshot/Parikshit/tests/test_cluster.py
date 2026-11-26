"""The whole simulation (simulator/cluster.py) on the six scenarios, shortened 5x and with lighter traffic."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

from helpers import PinRouter, by_node, light_workload, short_scenario
from simulator.cluster import Simulation
from simulator.config import PARIKSHIT_DIR, Scenario
from simulator.data import load_prices
from simulator.routers import LocalRouter

W = light_workload()


def run(name, router, seed=0, **kw):
    sim = Simulation(router, short_scenario(name), seed, workload=W, **kw)
    return sim, sim.run()


def digest(outcomes: dict) -> str:
    return hashlib.sha256(json.dumps(outcomes, sort_keys=True).encode()).hexdigest()


def mean_e2e(outcomes: list[dict]) -> float:
    return sum(o["e2e_ms"] for o in outcomes) / len(outcomes)


def test_every_routed_request_gets_exactly_one_outcome_and_every_tick_is_sent():
    router = LocalRouter()
    sim, s = run("s1_stable", router)
    assert s["requests"] == len(sim.items) == s["routed"] + s["rejected"]
    assert len(router.outcomes) == s["routed"] == s["completed"] + s["failed"]
    assert s["ticks"] == int(sim.scenario.duration_s / sim.cluster.tick_s)
    assert s["end_time_s"] >= sim.scenario.duration_s  # in-flight requests are served to the end
    assert all(o["t_complete"] <= s["end_time_s"] + 1e-9 for o in router.outcomes.values())


def test_runs_are_exactly_reproducible_and_seeds_differ():
    a, b, c = LocalRouter(), LocalRouter(), LocalRouter()
    run("s6_outage_recovery", a, seed=7)
    run("s6_outage_recovery", b, seed=7)
    run("s6_outage_recovery", c, seed=8)
    assert digest(a.outcomes) == digest(b.outcomes) and a.decisions == b.decisions
    assert digest(a.outcomes) != digest(c.outcomes)


def test_results_do_not_depend_on_the_process():
    """Python's hash seed changes per process; nothing in the simulation may depend on it."""
    code = (
        "import sys, json, hashlib; sys.path.insert(0, {p!r}); sys.path.insert(0, {t!r})\n"
        "from helpers import light_workload, short_scenario\n"
        "from simulator.cluster import Simulation\n"
        "from simulator.routers import LocalRouter\n"
        "r = LocalRouter(); Simulation(r, short_scenario('s6_outage_recovery'), 3, workload=light_workload()).run()\n"
        "print(hashlib.sha256(json.dumps(r.outcomes, sort_keys=True).encode()).hexdigest())\n"
    ).format(p=PARIKSHIT_DIR, t=os.path.join(PARIKSHIT_DIR, "tests"))
    hashes = set()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
        hashes.add(
            subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout
        )
    assert len(hashes) == 1


def test_a_router_that_rejects_everything_gets_ticks_but_no_outcomes():
    router = PinRouter(None)
    sim, s = run("s1_stable", router)
    assert s["rejected"] == s["requests"] > 0 and router.outcomes == {} and len(router.ticks) == s["ticks"]


def test_an_unknown_node_from_the_router_is_an_error():
    with pytest.raises(ValueError, match="router answered"):
        run("s1_stable", PinRouter("mars-1"))


def test_s3_switches_every_node_to_the_evening_prices():
    router = PinRouter("us-west-sjc")
    sim, s = run("s3_price_shift", router)
    prices = load_prices()
    t0, hour = sim.scenario.t0_s, sim.scenario.events[0].hour_utc
    for spec in sim.cluster.nodes:
        recs = by_node(sim.telemetry_log, spec.node_id)
        before = {r["energy_price_usd_kwh"] for r in recs if r["t"] < t0}
        after = {r["energy_price_usd_kwh"] for r in recs if r["t"] >= t0}
        assert before == {prices.usd_kwh(spec.price_zone, sim.cluster.price_hour_utc, 0.0)}
        assert after == {prices.usd_kwh(spec.price_zone, hour, 0.0)}
    assert s["events"][0]["usd_kwh"]["us-west-sjc"] > 0.04


def test_s4_the_busy_node_overheats_crosses_85_c_and_slows_down():
    router = PinRouter("us-east-nyc")  # all traffic, so the node is busy
    sim, _ = run("s4_thermal_throttle", router, validate_telemetry=True)
    recs = by_node(sim.telemetry_log, "us-east-nyc")
    t0 = sim.scenario.t0_s
    assert max(r["temperature_c"] for r in recs if r["t"] < t0) < 70
    assert max(r["temperature_c"] for r in recs if r["t"] >= t0) >= 85
    before = [o for o in router.outcomes.values() if o["t_complete"] < t0]
    late = [o for o in router.outcomes.values() if o["t_complete"] > t0 + 10]
    assert mean_e2e(late) > mean_e2e(before)  # same traffic, so the difference is the throttling


def test_s5_adds_80_ms_to_every_region_of_one_node():
    router = PinRouter("us-west-sjc")
    sim, _ = run("s5_network_degradation", router)
    t0 = sim.scenario.t0_s
    for node in sim.cluster.nodes:
        recs = by_node(sim.telemetry_log, node.node_id)
        first, last = recs[0]["rtt_ms"], recs[-1]["rtt_ms"]
        extra = 80.0 if node.node_id == "us-east-nyc" else 0.0
        assert {k: last[k] - first[k] for k in first} == pytest.approx({k: extra for k in first})
        assert all(r["rtt_ms"] == first for r in recs if r["t"] < t0)


def test_s6_down_warming_up_and_failures_are_reported():
    router = PinRouter("us-east-nyc")
    sim, s = run("s6_outage_recovery", router)
    scen = sim.scenario
    down_at, back_at = scen.events[0].at_s, scen.events[1].at_s
    warm_until = back_at + scen.events[1].warmup_s
    for r in by_node(sim.telemetry_log, "us-east-nyc"):
        expected = "up" if r["t"] < down_at or r["t"] >= warm_until else ("down" if r["t"] < back_at else "warming")
        assert r["status"] == expected, r["t"]
    failed = [o for o in router.outcomes.values() if o["failed"]]
    assert failed and all(not o["slo_met"] for o in failed)
    assert s["failed"] == len(failed) and s["failed_at_arrival"] > 0  # this router kept sending to the dead node
    lost_at_t0 = s["events"][0]["failed_requests"]
    assert lost_at_t0 > 0 and sum(o["t_complete"] == pytest.approx(down_at) for o in failed) >= lost_at_t0


def test_the_filtering_router_stops_using_a_down_node_at_the_next_tick():
    router = LocalRouter()
    sim, s = run("s6_outage_recovery", router)
    down_at, back_at = sim.scenario.events[0].at_s, sim.scenario.events[1].at_s
    during = [d for d in router.decisions if down_at <= d["t_arrival"] < back_at]
    assert during and all(d["node_id"] != "us-east-nyc" for d in during)
    assert all(d["filtered_out"].get("us-east-nyc") == "node_down" for d in during)
    assert s["failed_at_arrival"] == 0  # events come before the tick at the same time, so no stale routing here


def test_a_change_comes_before_the_tick_at_the_same_time_even_after_a_change_between_ticks():
    """The return at 11 s must be in the tick at 11 s, although its timer was set after the tick's (at 10.5 s)."""
    scen = Scenario.model_validate(
        {
            "name": "between_ticks",
            "description": "an outage between two ticks, then a return on a tick",
            "duration_s": 20.0,
            "t0_s": 10.5,
            "events": [
                {"kind": "node_down", "at_s": 10.5, "node": "us-east-nyc"},
                {"kind": "node_return", "at_s": 11.0, "node": "us-east-nyc", "warmup_s": 0.5, "warmup_slowdown": 3.0},
            ],
        }
    )
    sim = Simulation(PinRouter("us-west-sjc"), scen, 0, workload=W)
    s = sim.run()
    status = {r["t"]: r["status"] for r in by_node(sim.telemetry_log, "us-east-nyc")}
    assert (status[10.0], status[11.0], status[12.0]) == ("up", "warming", "up")
    applied = [(e["kind"], e["at_s"]) for e in s["events"]]
    assert applied == [("node_down", 10.5), ("node_return", 11.0), ("warm_done", 11.5)]


def test_an_invalid_telemetry_record_stops_the_run():
    sim = Simulation(PinRouter("us-west-sjc"), short_scenario("s1_stable"), 0, workload=W)
    sim.nodes["us-west-lax"].energy_price_usd_kwh = -0.01  # the contract needs prices >= 0
    with pytest.raises(ValueError, match="invalid telemetry from us-west-lax"):
        sim.run()
    unchecked = Simulation(
        PinRouter("us-west-sjc"), short_scenario("s1_stable"), 0, workload=W, validate_telemetry=False
    )
    unchecked.nodes["us-west-lax"].energy_price_usd_kwh = -0.01
    assert unchecked.run()["ticks"] == 120  # without the check the run goes on (only for tests of bad input)


def test_the_true_state_hook_sees_every_routed_request():
    router = PinRouter("us-east-nyc")
    sim, s = run("s6_outage_recovery", router)
    assert len(router.after) == s["routed"]
    assert {status for _, _, status in router.after} == {"up", "down", "warming"}
