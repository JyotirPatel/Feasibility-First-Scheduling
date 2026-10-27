"""Tests for router_plugin/: Sur's policies and reward inside Krupesh's router, using his code unmodified."""

import math

import numpy as np
import pytest

from linucb import LinUCB
from reward import compute_reward
from router_plugin import POLICIES, RouterLinUCB, RouterSlidingWindowLinUCB, krupesh_dir, make_reward_fn, register
from router_plugin import reward_fn as sur_reward_fn
from router_plugin.check_router import check, run
from sliding_window_linucb import SlidingWindowLinUCB
from sur_factories import POLICY_CONFIG_DIR, load_yaml, make_node, make_request

KRUPESH_DIR = krupesh_dir()  # importing router_plugin put this folder on sys.path

from api_contract.types import NodeState, Outcome, Request  # noqa: E402  (Krupesh's contract types)
from router_service import registry  # noqa: E402
from router_service.policy_base import Policy  # noqa: E402

REWARD = load_yaml("sw_linucb.yaml")["reward"]


def as_krupesh(request: dict, node: dict) -> tuple[Request, NodeState]:
    return Request.from_dict(request), NodeState.from_dict(node)


def test_router_policies_are_sur_policies_and_krupesh_policies():
    plain, windowed = RouterLinUCB(seed=2), RouterSlidingWindowLinUCB(seed=3)
    assert isinstance(plain, Policy) and isinstance(plain, LinUCB) and (plain.name, plain.seed) == ("linucb", 2)
    assert isinstance(windowed, Policy) and isinstance(windowed, SlidingWindowLinUCB)
    assert (windowed.name, windowed.seed) == ("sw_linucb", 3)
    assert (windowed.window_mode, windowed.window_size) == ("per_node", 500)


def test_register_resolves_every_name_through_krupeshs_registry(monkeypatch):
    monkeypatch.setattr(registry, "EXTRA_POLICIES", {})
    assert register() == sorted(POLICIES)
    assert type(registry.build_policy("sur:linucb", seed=1)) is RouterLinUCB
    assert type(registry.build_policy("linucb", seed=1)) is RouterLinUCB  # Riya's experiment name
    windowed = registry.build_policy("sliding_window_linucb", seed=5)
    assert type(windowed) is RouterSlidingWindowLinUCB and windowed.seed == 5
    assert registry.build_policy("sur:sw_linucb_no_context").dim == 1
    cfg = load_yaml("sw_linucb.yaml")
    cfg["window"]["size"] = 50
    assert registry.build_policy("sur:sw_linucb", seed=0, config=cfg).window_size == 50
    target: dict = {}
    register(target)
    assert sorted(target) == sorted(POLICIES)


def test_sur_policy_reads_krupeshs_typed_request_and_node_like_the_dicts():
    nodes = [make_node("a", queue_len=3), make_node("b", queue_len=40, status="warming")]
    request = make_request()
    typed = [as_krupesh(request, n) for n in nodes]
    by_dict, by_type = RouterSlidingWindowLinUCB(seed=0), RouterSlidingWindowLinUCB(seed=0)
    for node, (_, typed_node) in zip(nodes, typed, strict=True):
        np.testing.assert_array_equal(
            by_dict.features.build(request, node), by_type.features.build(typed[0][0], typed_node)
        )
    assert by_dict.choose(request, nodes) == by_type.choose(typed[0][0], [n for _, n in typed])


def test_reward_fn_is_surs_reward_in_krupeshs_shape():
    node = NodeState.from_dict(make_node(temperature_c=78.0))
    outcome = Outcome("r-000001", 184.0, 2210.0, True, 0.0004, 0.00013, t_complete=3.0)
    expected = compute_reward(node, outcome, REWARD)
    assert sur_reward_fn(outcome, node) == expected
    assert make_reward_fn(f"{POLICY_CONFIG_DIR}/linucb.yaml")(outcome, node) == expected  # same reward section
    assert make_reward_fn(RouterLinUCB().config.reward)(outcome, node) == expected
    other = {**REWARD, "weights": {**REWARD["weights"], "latency": 0.5}}
    assert make_reward_fn(other)(outcome, node) < expected


def test_failed_request_from_krupeshs_simulator_scores_as_a_failure():
    """His MockCluster reports a lost request as failed=True, slo_met=False and a finite ttft_ms."""
    node = NodeState.from_dict(make_node())
    lost = Outcome("r-1", 35.0, 35.0, False, 0.0, 0.0, failed=True, t_complete=10.0)
    late = Outcome("r-2", 900.0, 4000.0, False, 0.0, 0.0, t_complete=10.0)
    assert sur_reward_fn(lost, node) < sur_reward_fn(late, node)
    assert sur_reward_fn(lost, node) == pytest.approx(
        -REWARD["weights"]["latency"] - REWARD["weights"]["thermal_stress"] * (71.0 - 60.0) / (85.0 - 60.0)
    )


@pytest.mark.parametrize("policy", ["sur:sw_linucb", "sur:linucb", "sur:sw_linucb_no_context"])
@pytest.mark.parametrize("outage", [False, True])
def test_end_to_end_through_krupeshs_router(policy, outage):
    """The handbook's acceptance check (§5.3), run from Sur's side with Sur's reward."""
    result = check(policy, seed=1, duration_s=60.0, rate_rps=8.0, outage=outage)
    assert result["log_problems"] == [] and result["constraint_violations"] == 0
    assert result["policy_stats"]["updates"] == result["engine_counts"]["feedback"] > 0
    assert result["policy_stats"]["reward_mismatch"] == 0 and result["policy_stats"]["ignored_feedback"] == 0
    assert "node-hot" not in result["routed_by_node"]  # 91 °C: Jyotir's filter keeps it out
    assert result["failed"] == result["engine_counts"]["failed"] and (outage or result["failed"] == 0)
    assert result["ok"]


def test_requests_lost_in_an_outage_are_learned_as_failures():
    """Seed 0: node-east holds requests when it goes down. Each lost one must reach the policy with
    Sur's failure reward: no SLO credit, the worst latency (his mock reports no energy for it and the
    node runs at 60 °C, so there is no energy or thermal term)."""
    policy, engine, log = run("sur:sw_linucb", seed=0, duration_s=120.0, outage=True)
    lost = log[log["outcome_status"] == "failed"]
    assert len(lost) == engine.counts["failed"] > 0
    assert set(lost["node_id"]) == {"node-east"}
    np.testing.assert_allclose(lost["reward"].astype(float), -REWARD["weights"]["latency"])
    assert policy.stats["updates"] == engine.counts["feedback"]


def test_a_router_still_using_krupeshs_mock_reward_is_caught():
    from integration.mocks.mock_reward import mock_reward
    from integration.mocks.mock_simulator import MockCluster
    from router_service.engine import RoutingEngine

    policy = RouterSlidingWindowLinUCB(seed=0)
    engine = RoutingEngine(policy=policy, filter_fn=registry.build_filter("jyotir"), reward_fn=mock_reward)
    MockCluster(engine, seed=0, rate_rps=8.0, duration_s=30.0).run()
    assert policy.stats["updates"] > 0
    assert policy.stats["reward_mismatch"] == policy.stats["updates"]  # its weights differ from Sur's config
    assert math.isfinite(policy.last_reward)
