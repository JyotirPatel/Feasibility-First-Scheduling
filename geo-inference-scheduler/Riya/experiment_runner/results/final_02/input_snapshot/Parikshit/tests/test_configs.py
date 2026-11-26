"""Every config file loads, refers only to data that exists, and rejects bad values."""

from datetime import UTC, datetime

import pydantic
import pytest
import yaml

from simulator.config import (
    CONFIG_DIR,
    WorkloadConfig,
    load_calibration,
    load_cluster,
    load_scenario,
    load_workload,
    scenario_names,
)
from simulator.data import load_prices, load_rtt, load_trace

PRICES, RTT = load_prices(), load_rtt()


@pytest.mark.parametrize("size", [5, 10])
def test_node_setups_refer_to_existing_data(size):
    cluster, cal = load_cluster(size), load_calibration()
    assert len(cluster.nodes) == size
    for n in cluster.nodes:
        assert n.gpu in cal.gpus
        assert n.city in RTT.cities
        assert PRICES.usd_mwh(n.price_zone, cluster.price_hour_utc) is not None
        assert "llama-3-8b" in n.models_loaded


def test_the_10_node_setup_extends_the_5_node_setup():
    five, ten = load_cluster(5), load_cluster(10)
    assert five.model_dump(exclude={"nodes"}) == ten.model_dump(exclude={"nodes"})
    assert ten.nodes[: len(five.nodes)] == five.nodes


def test_workload_refers_to_existing_data_and_its_shares_are_the_traces_rates():
    w = load_workload()
    rates = {c.trace: load_trace(c.trace).rate_rps for c in w.classes.values()}
    total = sum(rates.values())
    for c in w.classes.values():
        assert c.share == pytest.approx(rates[c.trace] / total, abs=0.001)
    for r in w.regions.values():
        assert r.city in RTT.cities


def test_every_scenario_names_its_file_and_uses_known_nodes_and_hours():
    cluster = load_cluster(10)
    names = scenario_names()
    assert names == [
        "s1_stable",
        "s2_traffic_burst",
        "s3_price_shift",
        "s4_thermal_throttle",
        "s5_network_degradation",
        "s6_outage_recovery",
    ]
    for name in names:
        s = load_scenario(name)
        assert s.name == name and s.duration_s == 600 and s.t0_s == 200  # brief §5
        for e in s.events:
            if hasattr(e, "node"):
                cluster.node(e.node)
            if hasattr(e, "hour_utc"):
                for n in cluster.nodes:
                    PRICES.usd_mwh(n.price_zone, e.hour_utc)


def test_s3_flips_the_cheapest_region_in_real_data():
    cluster, s3 = load_cluster(5), load_scenario("s3_price_shift")
    before = {n.node_id: PRICES.usd_mwh(n.price_zone, cluster.price_hour_utc) for n in cluster.nodes}
    after = {n.node_id: PRICES.usd_mwh(n.price_zone, s3.events[0].hour_utc) for n in cluster.nodes}
    assert min(before, key=before.get).startswith("us-west")  # California is cheapest at midday ...
    assert min(after, key=after.get).startswith("us-east")  # ... and New York in the evening
    assert all(after[n] > before[n] + 30 for n in before if n.startswith("us-west"))


@pytest.mark.parametrize(
    "path,bad",
    [
        ("workload.yaml", {"surprise": 1}),
        ("workload.yaml", {"rate_rps": -1}),
        ("workload.yaml", {"expected_output_error": 1.0}),
        ("nodes_5.yaml", {"tick_s": 0}),
        ("nodes_5.yaml", {"price_hour_utc": "2024-04-17T19:00:00"}),  # no time zone
        ("calibration.yaml", {"serving": {"gpu_memory_utilization": 1.5, "decode_bandwidth_efficiency": 0.7}}),
    ],
)
def test_bad_values_are_rejected(path, bad, tmp_path):
    with open(f"{CONFIG_DIR}/{path}") as f:
        data = yaml.safe_load(f)
    data.update(bad)
    out = tmp_path / path
    out.write_text(yaml.safe_dump(data))
    loader = {"workload.yaml": load_workload, "nodes_5.yaml": load_cluster, "calibration.yaml": load_calibration}[path]
    with pytest.raises((pydantic.ValidationError, ValueError)):
        loader(str(out))


def test_class_shares_must_add_up_and_duplicate_nodes_are_refused():
    data = load_workload().model_dump()
    data["classes"]["batch"]["share"] = 0.5
    with pytest.raises(pydantic.ValidationError, match="add up to 1"):
        WorkloadConfig.model_validate(data)
    c = load_cluster(5).model_dump()
    c["nodes"].append(c["nodes"][0])
    with pytest.raises(pydantic.ValidationError, match="unique"):
        type(load_cluster(5)).model_validate(c)


@pytest.mark.parametrize(
    "events,needle",
    [
        (
            [{"kind": "node_return", "at_s": 400, "node": "us-east-nyc", "warmup_s": 60, "warmup_slowdown": 3}],
            "without",
        ),
        ([{"kind": "rtt", "at_s": 700, "node": "us-east-nyc", "delta_ms": 80}], "after the end"),
        ([{"kind": "arrival_rate", "at_s": 550, "factor": 3, "duration_s": 120}], "end inside"),
        ([{"kind": "arrival_rate", "at_s": 200, "factor": 0.5, "duration_s": 60}], "greater than or equal"),
        ([{"kind": "teleport", "at_s": 200}], "kind"),
    ],
)
def test_bad_scenarios_are_rejected(events, needle):
    base = load_scenario("s1_stable").model_dump()
    with pytest.raises(pydantic.ValidationError, match=needle):
        type(load_scenario("s1_stable")).model_validate({**base, "events": events})


def test_price_hours_are_whole_utc_hours():
    hour = datetime(2024, 4, 17, 19, tzinfo=UTC)
    assert PRICES.usd_kwh("CAISO:SP15", hour, 0.0) == 0.0  # negative at midday, floored
    assert PRICES.usd_kwh("NYISO:N.Y.C.", hour, 0.0) == pytest.approx(PRICES.usd_mwh("NYISO:N.Y.C.", hour) / 1000)
    with pytest.raises(ValueError):
        PRICES.usd_mwh("NYISO:N.Y.C.", datetime(2024, 4, 17, 19, 30, tzinfo=UTC))
    with pytest.raises(KeyError):
        PRICES.usd_mwh("NYISO:N.Y.C.", datetime(2023, 1, 1, tzinfo=UTC))
