"""Tests for the reward function (reward/reward.py)."""

import os
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from reward import RewardConfig, compute_reward, reward_bounds, reward_terms, slo_term_dominates
from sur_factories import SUR_DIR, load_yaml, make_node, make_outcome

CONFIG = load_yaml("sw_linucb.yaml")["reward"]


def test_hand_computed_reward():
    # latency 184/1000 = 0.184; energy 0.00004 kWh × $0.11 / $0.00001 = 0.44;
    # thermal (71 − 60) / (85 − 60) = 0.44
    r = compute_reward(make_node(), make_outcome(energy_kwh=0.00004), CONFIG)
    assert r == pytest.approx(1.0 - 0.2 * 0.184 - 0.1 * 0.44 - 0.1 * 0.44, abs=1e-12)


def test_missed_slo_scores_zero_for_that_term():
    t = reward_terms(make_node(), make_outcome(slo_met=False, ttft_ms=400.0), CONFIG)
    assert t["slo_met"] == 0.0
    assert t["latency"] == pytest.approx(0.4)


def test_terms_and_reward_stay_in_bounds():
    rng = np.random.default_rng(1)
    lo, hi = reward_bounds(CONFIG)
    assert (lo, hi) == (pytest.approx(-0.4), 1.0)
    for _ in range(500):
        node = make_node(temperature_c=float(rng.uniform(-20, 140)), energy_price_usd_kwh=float(rng.uniform(-0.3, 2.0)))
        outcome = make_outcome(
            slo_met=bool(rng.random() < 0.5),
            ttft_ms=float(rng.uniform(0, 5000)),
            e2e_ms=float(rng.uniform(0, 60_000)),
            energy_kwh=float(rng.uniform(0, 0.01)),
        )
        t = reward_terms(node, outcome, CONFIG)
        assert t["slo_met"] in (0.0, 1.0)
        assert all(0.0 <= t[k] <= 1.0 for k in ("latency", "energy_cost", "thermal_stress"))
        assert lo - 1e-12 <= compute_reward(node, outcome, CONFIG) <= hi + 1e-12


def test_default_weights_let_the_slo_term_dominate():
    assert slo_term_dominates(CONFIG)
    worst_met = compute_reward(
        make_node(temperature_c=200.0), make_outcome(slo_met=True, ttft_ms=1e9, energy_kwh=1.0), CONFIG
    )
    best_missed = compute_reward(
        make_node(temperature_c=0.0), make_outcome(slo_met=False, ttft_ms=0.0, energy_kwh=0.0), CONFIG
    )
    assert worst_met > best_missed


@pytest.mark.parametrize("missing", [None, float("nan"), float("inf")])
def test_unknown_outcome_values_get_the_worst_term(missing):
    t = reward_terms(make_node(), make_outcome(slo_met=None, ttft_ms=missing, energy_kwh=missing), CONFIG)
    assert t == {"slo_met": 0.0, "latency": 1.0, "energy_cost": 1.0, "thermal_stress": pytest.approx(0.44)}


@pytest.mark.parametrize("field", ["ttft_ms", "energy_kwh"])
def test_negative_time_or_energy_is_a_data_error(field):
    with pytest.raises(ValueError):
        compute_reward(make_node(), make_outcome(**{field: -1.0}), CONFIG)


def test_slo_met_must_be_present_and_boolean():
    outcome = make_outcome()
    del outcome["slo_met"]
    with pytest.raises(KeyError):
        compute_reward(make_node(), outcome, CONFIG)
    with pytest.raises(TypeError):
        compute_reward(make_node(), make_outcome(slo_met="yes"), CONFIG)
    assert reward_terms(make_node(), make_outcome(slo_met=np.bool_(True)), CONFIG)["slo_met"] == 1.0


def test_latency_metric_switch():
    cfg = {**CONFIG, "latency_metric": "e2e_ms", "latency_max_ms": 10_000}
    assert reward_terms(make_node(), make_outcome(), cfg)["latency"] == pytest.approx(2210 / 10_000)


def test_energy_cost_source_switch():
    cfg = {**CONFIG, "energy_cost_source": "cost_usd", "energy_cost_max_usd": 0.001}  # rent included: a larger scale
    assert reward_terms(make_node(), make_outcome(), cfg)["energy_cost"] == pytest.approx(0.00013 / 0.001)


def test_negative_electricity_price_is_no_penalty():
    t = reward_terms(make_node(energy_price_usd_kwh=-0.05), make_outcome(), CONFIG)
    assert t["energy_cost"] == 0.0


@pytest.mark.parametrize("temperature,expected", [(40.0, 0.0), (60.0, 0.0), (72.5, 0.5), (85.0, 1.0), (99.0, 1.0)])
def test_thermal_stress_shape(temperature, expected):
    terms = reward_terms(make_node(temperature_c=temperature), make_outcome(), CONFIG)
    assert terms["thermal_stress"] == pytest.approx(expected)


def test_failed_outcome_gets_no_slo_credit_and_the_worst_latency():
    """Krupesh's simulator reports a request lost on a dead node as failed=True with a finite ttft_ms
    (how long it waited before it was lost). That time is not a latency, so it must score as a failure."""
    lost = make_outcome(failed=True, slo_met=True, ttft_ms=40.0, e2e_ms=40.0, energy_kwh=0.0)
    terms = reward_terms(make_node(), lost, CONFIG)
    assert terms["slo_met"] == 0.0 and terms["latency"] == 1.0
    unknown_ttft = make_outcome(slo_met=False, ttft_ms=float("inf"), e2e_ms=float("inf"), energy_kwh=0.0)
    assert compute_reward(make_node(), lost, CONFIG) == compute_reward(make_node(), unknown_ttft, CONFIG)
    slow_success = make_outcome(slo_met=False, ttft_ms=900.0, energy_kwh=0.0)
    assert compute_reward(make_node(), lost, CONFIG) < compute_reward(make_node(), slow_success, CONFIG)
    assert compute_reward(make_node(), make_outcome(failed=False), CONFIG) == compute_reward(
        make_node(), make_outcome(), CONFIG
    )
    with pytest.raises(TypeError):
        compute_reward(make_node(), make_outcome(failed="yes"), CONFIG)


def test_dataclass_outcome_and_object_node_work():
    from stubs.stub_policy import Outcome

    outcome = Outcome(**make_outcome())
    as_dicts = compute_reward(make_node(), make_outcome(), CONFIG)
    assert compute_reward(SimpleNamespace(**make_node()), outcome, CONFIG) == as_dicts


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["weights"].update({"latency": -0.1}),
        lambda c: c["weights"].update({"slo_met": float("nan")}),
        lambda c: c.update({"thermal_limit_c": 50.0}),
        lambda c: c.update({"latency_metric": "p99_ms"}),
        lambda c: c.update({"latency_max_ms": 0}),
        lambda c: c.update({"surprise": 1}),
    ],
)
def test_bad_reward_config_is_rejected(mutate):
    cfg = {**CONFIG, "weights": dict(CONFIG["weights"])}
    mutate(cfg)
    with pytest.raises(ValidationError):
        RewardConfig.model_validate(cfg)


def test_thermal_limit_matches_jyotirs_filter_limit():
    """Thermal stress reaches 1 exactly where the filter starts rejecting the node."""
    path = os.path.join(os.path.dirname(SUR_DIR), "Jyotir", "feasibility_filter", "configs", "feasibility.yaml")
    with open(path) as f:
        filter_limit = yaml.safe_load(f)["temperature_limit_c"]
    for name in ("linucb.yaml", "sw_linucb.yaml", "sw_linucb_no_context.yaml"):
        assert load_yaml(name)["reward"]["thermal_limit_c"] == filter_limit
