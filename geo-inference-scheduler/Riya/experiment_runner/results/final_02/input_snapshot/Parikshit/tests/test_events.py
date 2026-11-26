"""simulator/events.py: what each kind of scenario change does to the nodes, its log record, and the change times."""

from helpers import PinRouter, light_workload
from simulator.cluster import Simulation
from simulator.config import load_scenario
from simulator.events import apply_event, change_times


def test_change_times_are_t0_and_the_s6_return():
    assert change_times(load_scenario("s1_stable")) == {"t0": 200.0}
    assert change_times(load_scenario("s6_outage_recovery")) == {"t0": 200.0, "return": 400.0}


def test_each_kind_of_change_acts_on_the_right_node_and_is_logged():
    sim = Simulation(PinRouter(None), "s1_stable", 0, workload=light_workload())  # builds the five nodes
    nyc = sim.nodes["us-east-nyc"]

    def apply(scenario: str, i: int = 0) -> dict:
        return apply_event(load_scenario(scenario).events[i], sim.nodes, sim.cluster, sim.prices)

    assert "built into the workload" in apply("s2_traffic_burst")["note"]
    prices = apply("s3_price_shift")["usd_kwh"]
    assert set(prices) == set(sim.nodes) and all(sim.nodes[n].energy_price_usd_kwh == p for n, p in prices.items())
    heat = apply("s4_thermal_throttle")
    assert heat == {"kind": "inlet_temperature", "at_s": 200.0, "node": "us-east-nyc", "inlet_c": 65.0}
    before = nyc.rtt_to("nyc")
    assert apply("s5_network_degradation")["rtt_extra_ms"] == 80.0 and nyc.rtt_to("nyc") == before + 80.0
    down = apply("s6_outage_recovery", 0)
    assert down == {"kind": "node_down", "at_s": 200.0, "node": "us-east-nyc", "failed_requests": 0}
    assert nyc.status == "down"
    assert apply("s6_outage_recovery", 1)["warm_until_s"] == 460.0 and nyc.status == "warming"
    assert all(n.status == "up" and n.rtt_extra_ms == 0 for n in sim.nodes.values() if n is not nyc)
