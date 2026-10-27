"""Routing engine: filter-first, safety guard, delayed feedback, local accounting."""

import pytest

from api_contract.types import FilterResult, Outcome
from decision_log.writer import validate_log
from integration.mocks.mock_reward import mock_reward
from kr_helpers import node, request
from router_service.engine import RoutingEngine, UnknownRequest
from router_service.policy_base import Policy
from router_service.registry import build_filter, build_policy


def engine(policy="jyotir:min_rtt", flt="jyotir", **kw):
    return RoutingEngine(build_policy(policy), build_filter(flt), mock_reward, **kw)


def test_reject_when_no_feasible_node():
    e = engine()
    e.ingest_telemetry([node("a", status="down"), node("b", temperature_c=99)])
    d = e.route(request())
    assert d.decision == "reject" and d.reject_reason == "no_feasible_node"
    assert d.filtered_out == {"a": "node_down", "b": "temperature_high"}
    assert e.writer.to_frame().loc[0, "outcome_status"] == "rejected"


def test_no_telemetry_means_reject_not_guess():
    assert engine().route(request()).decision == "reject"


def test_route_then_delayed_feedback_writes_one_valid_row():
    e = engine()
    e.ingest_telemetry([node("near", rtt_ms={"nyc": 5}), node("far", rtt_ms={"nyc": 90})])
    d = e.route(request("r1"))
    assert d.node_id == "near" and d.feasible_nodes == ["near", "far"]
    assert e.writer.rows == []  # nothing logged until the outcome arrives
    r = e.feedback(Outcome("r1", 120, 900, True, 2e-4, 5e-5, t_complete=3.0))
    df = e.writer.to_frame()
    assert len(df) == 1 and df.loc[0, "reward"] == pytest.approx(r) and validate_log(df) == []
    with pytest.raises(UnknownRequest):
        e.feedback(Outcome("r1", 1, 1, True, 0, 0))


def test_duplicate_in_flight_request_rejected():
    e = engine()
    e.ingest_telemetry([node("a")])
    e.route(request("x"))
    with pytest.raises(ValueError):
        e.route(request("x"))


class Rogue(Policy):
    def choose(self, request, candidates):
        return "hot"


def test_policy_cannot_bypass_filter():
    e = RoutingEngine(Rogue(), build_filter("jyotir"), mock_reward)
    e.ingest_telemetry([node("ok"), node("hot", temperature_c=95)])
    with pytest.raises(RuntimeError):
        e.route(request())


def test_no_filter_ablation_logs_violation():
    e = RoutingEngine(
        build_policy("jyotir:lowest_energy"),
        build_filter("none"),
        mock_reward,
        audit_fn=build_filter("jyotir"),
    )
    e.ingest_telemetry([node("ok"), node("hot", temperature_c=95, energy_price_usd_kwh=0.01)])
    e.route(request("v"))
    e.finish()
    row = e.writer.to_frame().iloc[0]
    assert row.node_id == "hot" and row.constraint_violation == "temperature_high"


def test_local_load_accounting_spreads_traffic_between_reports():
    e = engine("jyotir:least_load")
    e.ingest_telemetry([node("a", running=0, t=0.0), node("b", running=1, t=0.0)])
    picks = [e.route(request(f"r{i}", t_arrival=0.5)).node_id for i in range(4)]
    assert picks == ["a", "a", "b", "a"]
    e.ingest_telemetry([node("a", t=1.0), node("b", t=1.0)])
    assert all(len(v) == 0 for v in e._local.values())


def test_custom_filter_plugs_in():
    def only_b(req, nodes):
        return FilterResult(
            [n for n in nodes if n.node_id == "b"],
            {n.node_id: "custom" for n in nodes if n.node_id != "b"},
        )

    e = RoutingEngine(build_policy("jyotir:round_robin"), only_b, mock_reward)
    e.ingest_telemetry([node("a"), node("b")])
    assert e.route(request()).node_id == "b"


def test_learning_policy_receives_reward_through_engine():
    e = engine("mock:learning")
    e.ingest_telemetry([node("a"), node("b")])
    e.route(request("q"))
    e.feedback(Outcome("q", 50, 500, True, 0, 0))
    assert sum(e.policy.n.values()) == 1


def test_finish_marks_unfinished():
    e = engine()
    e.ingest_telemetry([node("a")])
    e.route(request("u"))
    assert e.finish() == 1 and e.writer.to_frame().loc[0, "outcome_status"] == "unfinished"


def test_riya_plain_policy_names_map_to_jyotir_baselines():
    for name in ("round_robin", "min_rtt", "least_load", "lowest_energy", "static_weighted"):
        assert build_policy(name).name == f"jyotir:{name}"
    for name in ("linucb", "sliding_window_linucb"):
        with pytest.raises(KeyError, match="Sur"):
            build_policy(name)
