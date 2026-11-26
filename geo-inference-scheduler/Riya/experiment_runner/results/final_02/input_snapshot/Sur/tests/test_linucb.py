"""Tests for plain LinUCB (linucb/linucb.py)."""

import threading

import numpy as np
import pytest
from pydantic import ValidationError

from linucb import LinUCB, load_config
from reward import compute_reward
from sur_factories import load_yaml, make_node, make_outcome, make_request

LAM = 1.0


def fresh(**overrides):
    cfg = load_yaml("linucb.yaml")
    cfg.update(overrides)
    return LinUCB(cfg)


def outcome_for(rng, p_met):
    met = bool(rng.random() < p_met)
    return make_outcome(slo_met=met, ttft_ms=150.0 if met else 400.0)


# ── the math matches brief §6.4 ──────────────────────────────────────────────


def test_initial_state_is_the_prior():
    policy = fresh()
    policy.choose(make_request(), [make_node("a")])
    model = policy._models["a"]
    np.testing.assert_array_equal(model.A, LAM * np.eye(policy.dim))
    np.testing.assert_array_equal(model.b, np.zeros(policy.dim))
    np.testing.assert_array_equal(policy.theta("a"), np.zeros(policy.dim))


def test_update_matches_the_formula_and_touches_only_the_chosen_node():
    policy = fresh()
    rng = np.random.default_rng(0)
    xs, rs = [], []
    node_a, node_b = make_node("a"), make_node("b", queue_len=0)
    for i in range(30):
        request = make_request(f"r-{i}", input_tokens=int(rng.integers(10, 4000)))
        outcome = outcome_for(rng, 0.7)
        policy.choose(request, [node_a])  # single candidate -> must pick "a"
        xs.append(policy.features.build(request, node_a))
        rs.append(compute_reward(node_a, outcome, policy.config.reward))
        policy.update(request, "a", outcome)
    policy.choose(make_request("r-b"), [node_b])  # "b" seen but never updated

    X, R = np.array(xs), np.array(rs)
    model = policy._models["a"]
    np.testing.assert_allclose(model.A, LAM * np.eye(policy.dim) + X.T @ X, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(model.b, X.T @ R, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(policy.theta("a"), np.linalg.solve(model.A, model.b), rtol=1e-9, atol=1e-12)
    np.testing.assert_array_equal(policy._models["b"].A, LAM * np.eye(policy.dim))


def test_score_is_estimate_plus_alpha_times_bonus():
    policy = fresh(alpha=0.7)
    rng = np.random.default_rng(1)
    node = make_node("a")
    for i in range(20):
        request = make_request(f"r-{i}", input_tokens=int(rng.integers(10, 4000)))
        policy.choose(request, [node])
        policy.update(request, "a", outcome_for(rng, 0.6))
    request = make_request("probe", input_tokens=1234)
    x = policy.features.build(request, node)
    A = policy._models["a"].A
    theta = np.linalg.solve(A, policy._models["a"].b)
    expected = theta @ x + 0.7 * np.sqrt(x @ np.linalg.solve(A, x))
    assert policy.explain(request, [node])[0]["score"] == pytest.approx(expected, rel=1e-9)


# ── safety: only ever picks a candidate the filter allowed ───────────────────


def test_returns_one_of_the_candidates():
    policy = fresh()
    rng = np.random.default_rng(2)
    for i in range(300):
        candidates = [
            make_node(f"n{j}", queue_len=int(rng.integers(0, 30)), temperature_c=float(rng.uniform(40, 84)))
            for j in rng.choice(8, size=int(rng.integers(1, 6)), replace=False)
        ]
        request = make_request(f"r-{i}")
        chosen = policy.choose(request, candidates)
        assert chosen in {c["node_id"] for c in candidates}
        policy.update(request, chosen, outcome_for(rng, 0.5))


def test_never_picks_a_node_the_real_filter_removed():
    from feasibility_filter.filter import feasibility_filter
    from stubs.fake_node import FAKE_CLUSTER, FAKE_REQUEST

    policy = fresh()
    rng = np.random.default_rng(3)
    for i in range(300):
        request = {**FAKE_REQUEST, "request_id": f"r-{i}"}
        allowed, rejected = feasibility_filter(request, FAKE_CLUSTER)
        chosen = policy.choose(request, allowed)
        assert chosen in {n["node_id"] for n in allowed}
        assert chosen not in {r["node_id"] for r in rejected}
        policy.update(request, chosen, outcome_for(rng, 0.8))


def test_empty_candidates_raise_like_the_baselines():
    with pytest.raises(ValueError, match="No feasible candidates"):
        fresh().choose(make_request(), [])


def test_request_id_is_required():
    request = make_request()
    del request["request_id"]
    with pytest.raises(ValueError, match="request_id"):
        fresh().choose(request, [make_node()])


# ── delayed feedback ─────────────────────────────────────────────────────────


def test_learns_from_decision_time_state_not_later_telemetry():
    policy = fresh()
    node = make_node("a", temperature_c=71.0, queue_len=7)
    request = make_request()
    x_at_decision = policy.features.build(request, node)
    policy.choose(request, [node])

    node["temperature_c"] = 99.0  # telemetry changes before the feedback arrives
    node["queue_len"] = 60
    outcome = make_outcome()
    policy.update(request, "a", outcome)

    expected_A = LAM * np.eye(policy.dim) + np.outer(x_at_decision, x_at_decision)
    np.testing.assert_allclose(policy._models["a"].A, expected_A)
    at_decision = make_node("a", temperature_c=71.0)
    assert policy.last_reward == pytest.approx(compute_reward(at_decision, outcome, policy.config.reward))


def test_reward_is_computed_by_the_policy_not_taken_from_the_outcome():
    policy = fresh()
    request = make_request()
    policy.choose(request, [make_node("a")])
    policy.update(request, "a", make_outcome(reward=999.0))
    assert policy.last_reward == pytest.approx(compute_reward(make_node("a"), make_outcome(), policy.config.reward))
    assert policy.stats["reward_mismatch"] == 1


def test_a_router_reward_that_differs_is_counted_and_warned_about_once(caplog):
    policy = fresh()
    own = compute_reward(make_node("a"), make_outcome(), policy.config.reward)
    for i, reported in enumerate([own, None, 999.0, float("nan"), "bad", own + 1e-15]):
        policy.choose(make_request(f"r-{i}"), [make_node("a")])
        with caplog.at_level("WARNING", logger="linucb.linucb"):
            policy.update(make_request(f"r-{i}"), "a", make_outcome(reward=reported))
    # equal, missing and equal-within-rounding are fine; 999, NaN and a non-number are mismatches
    assert policy.stats["reward_mismatch"] == 3 and policy.stats["updates"] == 6
    assert sum("differs from this policy's reward" in r.getMessage() for r in caplog.records) == 1


def test_out_of_order_feedback_is_matched_by_request_id():
    policy = fresh()
    a, b = make_node("a", queue_len=0), make_node("b", queue_len=50)
    policy.choose(make_request("r-1"), [a])
    policy.choose(make_request("r-2"), [b])
    policy.update(make_request("r-2"), "b", make_outcome(slo_met=False))
    policy.update(make_request("r-1"), "a", make_outcome(slo_met=True))
    assert policy.model_counts() == {"a": 1, "b": 1}
    estimate = {n["node_id"]: policy.theta(n["node_id"]) @ policy.features.build(make_request(), n) for n in (a, b)}
    assert estimate["a"] > estimate["b"]


def test_duplicate_unknown_and_mismatched_feedback_is_ignored():
    policy = fresh()
    policy.choose(make_request("r-1"), [make_node("a")])
    policy.update(make_request("r-1"), "a", make_outcome())
    policy.update(make_request("r-1"), "a", make_outcome())  # duplicate
    policy.update(make_request("never-routed"), "a", make_outcome())  # unknown
    policy.choose(make_request("r-2"), [make_node("a")])
    policy.update(make_request("r-2"), "b", make_outcome())  # wrong node
    assert policy.model_counts() == {"a": 1}
    assert policy.stats == {
        "decisions": 2,
        "updates": 1,
        "ignored_feedback": 3,
        "dropped_pending": 0,
        "reward_mismatch": 0,
    }
    assert policy.pending_count == 0
    assert policy.last_reward is None


def test_malformed_outcome_keeps_the_decision_for_a_retry():
    policy = fresh()
    policy.choose(make_request("r-1"), [make_node("a")])
    bad = make_outcome()
    del bad["slo_met"]
    with pytest.raises(KeyError):
        policy.update(make_request("r-1"), "a", bad)
    assert policy.pending_count == 1
    policy.update(make_request("r-1"), "a", make_outcome())
    assert policy.model_counts() == {"a": 1}


def test_pending_decisions_are_capped():
    policy = fresh(max_pending=3)
    for i in range(5):
        policy.choose(make_request(f"r-{i}"), [make_node("a")])
    assert policy.pending_count == 3
    assert policy.stats["dropped_pending"] == 2
    policy.update(make_request("r-0"), "a", make_outcome())  # dropped -> ignored
    policy.update(make_request("r-4"), "a", make_outcome())  # kept -> learned
    assert policy.stats["updates"] == 1 and policy.stats["ignored_feedback"] == 1


def test_accepts_jyotirs_outcome_dataclass():
    from stubs.stub_policy import Outcome, Policy

    policy = fresh()
    assert isinstance(policy, Policy)
    policy.choose(make_request(), [make_node("a")])
    policy.update(make_request(), "a", Outcome(**make_outcome()))
    assert policy.stats["updates"] == 1


def test_accepts_the_exact_feedback_payload_from_the_brief():
    """POST /feedback in brief §10.2 has no reward field; the policy computes it."""
    policy = fresh()
    request = {
        "request_id": "r-000123",
        "t_arrival": 312.4,
        "user_region": "nyc",
        "model": "llama-3-8b",
        "input_tokens": 850,
        "expected_output_tokens": 200,
        "slo_class": "interactive",
        "ttft_slo_ms": 250,
    }
    node = policy.choose(request, [make_node("us-east-1")])
    feedback = {
        "request_id": "r-000123",
        "ttft_ms": 184,
        "e2e_ms": 2210,
        "slo_met": True,
        "energy_kwh": 0.0004,
        "cost_usd": 0.00013,
    }
    policy.update(request, node, feedback)
    assert policy.stats["updates"] == 1
    # the brief's example energy (0.0004 kWh at $0.11 = $0.000044) is above the $0.00001 scale: that term is 1
    assert policy.last_reward == pytest.approx(1.0 - 0.2 * 0.184 - 0.1 * 1.0 - 0.1 * 0.44)


# ── learning and reproducibility ─────────────────────────────────────────────


def test_learns_to_prefer_the_better_node():
    policy = fresh()
    rng = np.random.default_rng(4)
    nodes = [make_node("good"), make_node("ok"), make_node("bad")]
    p_met = {"good": 0.9, "ok": 0.5, "bad": 0.2}
    picks = []
    for i in range(800):
        request = make_request(f"r-{i}")
        chosen = policy.choose(request, nodes)
        policy.update(request, chosen, outcome_for(rng, p_met[chosen]))
        picks.append(chosen)
    assert picks[-300:].count("good") / 300 > 0.9


def test_same_seed_same_choices_and_ties_are_broken_at_random():
    def run(seed):
        policy = fresh(seed=seed)
        nodes = [make_node(f"n{j}") for j in range(4)]  # identical nodes -> every score ties
        return [policy.choose(make_request(f"r-{i}"), nodes) for i in range(40)]

    assert run(7) == run(7)
    assert len(set(run(7))) > 1  # not always the first candidate


def test_constructor_seed_overrides_the_config_seed():
    assert fresh(seed=0).seed == 0
    assert LinUCB(load_yaml("linucb.yaml"), seed=123).seed == 123


def test_thread_safe_under_concurrent_calls():
    policy = fresh()
    nodes = [make_node(f"n{j}", queue_len=j) for j in range(5)]
    errors = []

    def worker(k):
        rng = np.random.default_rng(k)
        try:
            for i in range(150):
                request = make_request(f"t{k}-r{i}")
                chosen = policy.choose(request, nodes)
                policy.update(request, chosen, outcome_for(rng, 0.6))
        except Exception as e:  # pragma: no cover - only on failure
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert policy.stats["decisions"] == policy.stats["updates"] == 8 * 150
    assert sum(policy.model_counts().values()) == 8 * 150


# ── config and checkpoints ───────────────────────────────────────────────────


def test_default_config_file_loads():
    cfg = load_config()
    assert cfg.policy == "linucb" and cfg.lambda_ == 1.0
    assert LinUCB().dim == 14


@pytest.mark.parametrize(
    "override",
    [
        {"alpha": -1},
        {"lambda": 0},
        {"policy": "sw_linucb"},
        {"max_pending": 0},
        {"unknown": 1},
        {"alpha": float("nan")},
    ],
)
def test_bad_config_is_rejected(override):
    cfg = load_yaml("linucb.yaml")
    cfg.update(override)
    with pytest.raises(ValidationError):
        LinUCB(cfg)


def _train(policy, rounds=200, seed=5):
    rng = np.random.default_rng(seed)
    nodes = [make_node("a"), make_node("b", queue_len=40), make_node("c", status="warming")]
    for i in range(rounds):
        request = make_request(f"r-{seed}-{i}", input_tokens=int(rng.integers(10, 4000)))
        chosen = policy.choose(request, nodes)
        policy.update(request, chosen, outcome_for(rng, 0.7 if chosen == "a" else 0.4))
    return nodes


def test_checkpoint_round_trip_restores_the_exact_state(tmp_path):
    policy = fresh()
    nodes = _train(policy)
    path = tmp_path / "linucb.npz"
    policy.save_checkpoint(path)

    restored = fresh()
    restored.load_checkpoint(path)
    for node_id in ("a", "b", "c"):
        np.testing.assert_array_equal(restored._models[node_id].A, policy._models[node_id].A)
        np.testing.assert_array_equal(restored._models[node_id].b, policy._models[node_id].b)
    assert restored.stats == policy.stats
    probe = make_request("probe")
    assert restored.explain(probe, nodes) == policy.explain(probe, nodes)
    assert [restored.choose(make_request(f"next-{i}"), nodes) for i in range(20)] == [
        policy.choose(make_request(f"next-{i}"), nodes) for i in range(20)
    ]


def test_checkpoint_refuses_a_different_config_or_policy(tmp_path):
    from sliding_window_linucb import SlidingWindowLinUCB

    policy = fresh()
    _train(policy, rounds=20)
    path = tmp_path / "linucb.npz"
    policy.save_checkpoint(path)

    other_reward = load_yaml("linucb.yaml")
    other_reward["reward"]["weights"]["latency"] = 0.5
    with pytest.raises(ValueError, match="reward"):
        LinUCB(other_reward).load_checkpoint(path)

    no_context = load_yaml("linucb.yaml")
    no_context["features"]["use_context"] = False
    with pytest.raises(ValueError, match="features"):
        LinUCB(no_context).load_checkpoint(path)

    with pytest.raises(ValueError, match="policy"):
        SlidingWindowLinUCB().load_checkpoint(path)

    # a different alpha is fine: alpha only changes scoring, not the learned state
    fresh(alpha=0.3).load_checkpoint(path)


def test_checkpoint_rejects_tampered_numbers(tmp_path):
    policy = fresh()
    _train(policy, rounds=20)
    path = tmp_path / "linucb.npz"
    policy.save_checkpoint(path)
    with np.load(path, allow_pickle=False) as data:
        arrays = {k: data[k] for k in data.files}
    arrays["A"][0] = -np.eye(policy.dim)  # not positive definite
    bad = tmp_path / "bad.npz"
    np.savez(bad, **arrays)
    with pytest.raises(ValueError, match="positive definite"):
        fresh().load_checkpoint(bad)
