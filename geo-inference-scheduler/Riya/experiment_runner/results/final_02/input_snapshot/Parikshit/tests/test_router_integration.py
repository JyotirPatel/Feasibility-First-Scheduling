"""The simulator driving Krupesh's real router (his code, unmodified): in-process and over HTTP (handbook §5.2)."""

import pytest

from helpers import light_workload, short_scenario
from simulator.cluster import Simulation
from simulator.routers import KrupeshRouter, krupesh_engine, true_state_problems, use_krupesh

use_krupesh()
from decision_log.writer import read_log, validate_log  # noqa: E402  (Krupesh's)

W = light_workload()


def run_inprocess(scenario: str, policy: str, seed: int = 0):
    scen = short_scenario(scenario)
    engine, reward = krupesh_engine(policy, seed, scen.name)
    router = KrupeshRouter(engine)
    stats = Simulation(router, scen, seed, workload=W).run()
    engine.finish()
    return stats, engine, router, engine.writer.close(), reward


@pytest.mark.parametrize("scenario", ["s1_stable", "s6_outage_recovery"])
def test_inprocess_run_writes_a_valid_decision_log(scenario):
    stats, engine, router, log, _ = run_inprocess(scenario, "jyotir:least_load")
    assert validate_log(log) == []
    assert len(log) == stats["requests"] and log["request_id"].is_unique
    assert log["constraint_violation"].isna().all()  # the filter was on
    assert engine.counts["feedback"] == stats["routed"] and engine.counts["failed"] == stats["failed"]
    assert (log["outcome_status"] == "failed").sum() == stats["failed"]
    assert set(log["outcome_status"]) <= {"ok", "failed"}  # nothing unfinished: every request got its outcome
    if scenario == "s6_outage_recovery":
        assert stats["failed"] > 0


def test_surs_learning_policy_runs_on_the_simulator():
    stats, engine, _, log, reward = run_inprocess("s1_stable", "sur:sw_linucb")
    assert reward == "sur" and validate_log(log) == []
    policy = engine.policy
    assert policy.stats["updates"] == engine.counts["feedback"] == stats["routed"]
    assert policy.stats["reward_mismatch"] == 0  # the router used Sur's reward, so the two agree


def test_the_router_scores_each_policy_with_its_own_reward_section(monkeypatch):
    krupesh_engine("sur:linucb", 0, "s1_stable")  # puts Sur's folder on the import path
    import router_plugin  # Sur's

    real, seen = router_plugin.make_reward_fn, []
    monkeypatch.setattr(router_plugin, "make_reward_fn", lambda config=None: seen.append(config) or real(config))
    engine, _ = krupesh_engine("sur:linucb", 0, "s1_stable")
    assert seen == [engine.policy.config.reward]  # so the logged reward is the one the policy learns from
    krupesh_engine("jyotir:least_load", 0, "s1_stable")
    assert seen[-1] is None  # a baseline has no reward section: Sur's default


def test_http_mode_makes_the_same_decisions_as_in_process(tmp_path):
    from fastapi.testclient import TestClient
    from router_service.app import create_app
    from router_service.client import HttpRouter

    scen = short_scenario("s1_stable")
    http = HttpRouter(TestClient(create_app()))
    http.configure(policy="jyotir:least_load", seed=0, run_id="http-test", scenario=scen.name)
    Simulation(KrupeshRouter(http), scen, 0, workload=W).run()
    info = http.finish(str(tmp_path / "decision_log.csv"))
    over_http = read_log(info["log_path"])
    assert validate_log(over_http) == []

    _, _, _, in_process, _ = run_inprocess("s1_stable", "jyotir:least_load")
    a = in_process.set_index("request_id")["node_id"]
    b = over_http.set_index("request_id")["node_id"]
    assert a.sort_index().equals(b.sort_index())


def test_true_state_problems_checks_every_hard_rule():
    limits = {"temperature_limit_c": 85.0, "power_headroom_min_kw": 2.0, "kv_cache_max_frac": 0.9}
    good = {
        "status": "up",
        "models_loaded": ["llama-3-8b"],
        "kv_used_frac": 0.5,
        "kv_capacity_tokens": 10_000,
        "power_headroom_kw": 3.0,
        "temperature_c": 70.0,
    }
    req = {"model": "llama-3-8b", "input_tokens": 1000, "expected_output_tokens": 200}
    assert true_state_problems(req, good, limits) == []
    assert true_state_problems(req, {**good, "status": "down"}, limits) == ["node_down"]
    assert true_state_problems({**req, "model": "llama-3-70b"}, good, limits) == ["model_missing"]
    assert true_state_problems(req, {**good, "kv_used_frac": 0.8}, limits) == ["memory_full"]  # 0.8 + 0.12 > 0.9
    assert true_state_problems(req, {**good, "power_headroom_kw": 1.0}, limits) == ["power_limit"]
    assert true_state_problems(req, {**good, "temperature_c": 85.0}, limits) == ["temperature_high"]
    warm_hot = {**good, "status": "warming", "temperature_c": 90.0}
    assert true_state_problems(req, warm_hot, limits) == ["temperature_high"]  # a warming node gets every check (F1)
    assert true_state_problems(req, warm_hot, {**limits, "allow_warming_nodes": False})[0] == "node_warming"


def test_a_true_state_violation_is_written_into_the_decision_log():
    scen = short_scenario("s1_stable")
    engine, _ = krupesh_engine("jyotir:least_load", 0, scen.name)
    router = KrupeshRouter(engine)
    sim = Simulation(router, scen, 0, workload=W)
    req = dict(sim.items[0].request)
    record = sim.nodes["us-east-nyc"].telemetry(0.0)
    router.ingest_telemetry([n.telemetry(0.0) for n in sim.nodes.values()])
    decision, node_id = router.route(req)
    router.after_route(req, node_id, {**record, "status": "down"})
    engine.finish()
    row = engine.writer.close().set_index("request_id").loc[req["request_id"]]
    assert decision == "route" and row["true_state_violation"] == "node_down"
    assert router.true_state_violations["node_down"] == 1
