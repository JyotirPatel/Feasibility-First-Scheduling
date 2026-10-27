"""simulator/scenario_effects.py: the scenario table of the report, on the shortened scenarios."""

import math
import re
from types import SimpleNamespace

import pytest

from helpers import light_workload, short_scenario
from simulator.scenario_effects import effects, node_share, slo_share, table

W = light_workload()


@pytest.fixture(scope="module")
def rows():
    found = {name: effects(short_scenario(name), workload=W) for name in ("s1_stable", "s2_traffic_burst")}
    # S4 at the shipped rate: with the light test traffic the node never reaches the filter's 85 °C limit
    found["s4_thermal_throttle"] = effects(short_scenario("s4_thermal_throttle"))
    found["s6_outage_recovery"] = effects(short_scenario("s6_outage_recovery"), workload=W)
    return found


def test_windows_split_the_run_at_t0_and_halfway_after_it(rows):
    assert rows["s1_stable"]["windows"] == [(0.0, 40.0), (40.0, 80.0), (80.0, 120.0)]


def test_shares_are_fractions_and_a_stable_run_changes_nothing(rows):
    s1 = rows["s1_stable"]
    assert s1["changes"] == [] and s1["true_state_violations"] == {}
    for row in rows.values():
        assert all(0.0 <= s <= 1.0 and not math.isnan(s) for s in row["slo_met"])


def test_each_change_is_described_with_what_it_did(rows):
    (burst,) = rows["s2_traffic_burst"]["changes"]
    found = re.fullmatch(r"arrivals (\d+) → (\d+) req/s for 24 s; cluster slot use (\d+)% → (\d+)%", burst)
    before, during, use_before, use_during = map(int, found.groups())
    assert 2.5 < during / before < 3.5 and use_during > use_before
    (heat,) = rows["s4_thermal_throttle"]["changes"]
    hot = int(re.search(r"at or above 85 °C in (\d+) of \d+ ticks", heat).group(1))
    share_before, share_after = map(int, re.search(r"gets (\d+)% → (\d+)% of requests", heat).groups())
    assert heat.startswith("us-east-nyc: peak") and hot > 0 and share_after < share_before  # filtered out when hot
    down, back = rows["s6_outage_recovery"]["changes"]
    assert down.startswith("us-east-nyc down:") and "0 sent to it while down" in down
    assert back.startswith("us-east-nyc back at 80 s, warming until 92 s")


def test_the_table_has_one_line_per_scenario_and_labels_the_windows(rows):
    text = table(list(rows.values())).splitlines()
    assert len(text) == 2 + len(rows)
    assert "SLO met 0–40 s" in text[0] and "SLO met 80–120 s" in text[0]
    assert text[2].startswith("| s1_stable | ") and "| nothing | none |" in text[2]


def test_shares_count_every_arrival_in_the_window_including_rejected_ones():
    recorded = SimpleNamespace(
        routes={"r1": (1.0, "a"), "r2": (2.0, "a"), "r3": (3.0, "a"), "r4": (4.0, None), "r5": (9.0, "b")},
        outcomes={"r1": {"slo_met": True}, "r2": {"slo_met": False}, "r3": {"slo_met": True}, "r5": {"slo_met": True}},
    )  # r4 was rejected, so it has no outcome
    assert slo_share(recorded, 0.0, 5.0) == pytest.approx(2 / 4)
    assert node_share(recorded, "a", 0.0, 5.0) == pytest.approx(3 / 4)
    assert node_share(recorded, "a", 5.0, 10.0) == 0.0 and node_share(recorded, "b", 5.0, 10.0) == 1.0
    assert math.isnan(slo_share(recorded, 20.0, 30.0)) and math.isnan(node_share(recorded, "a", 20.0, 30.0))


def test_scenarios_with_different_windows_cannot_share_a_table(rows):
    other = {**rows["s1_stable"], "windows": [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]}
    with pytest.raises(ValueError, match="different windows"):
        table([rows["s1_stable"], other])
