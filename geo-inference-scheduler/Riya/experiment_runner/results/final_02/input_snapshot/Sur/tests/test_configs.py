"""The policy config files: valid, and the ablations differ only where they should."""

import pytest

from linucb import LinUCBConfig
from reward import slo_term_dominates
from sliding_window_linucb import SWLinUCBConfig
from sur_factories import load_yaml

SHARED = ("alpha", "lambda", "seed", "max_pending", "features", "reward")


@pytest.mark.parametrize(
    "name,model",
    [
        ("linucb.yaml", LinUCBConfig),
        ("sw_linucb.yaml", SWLinUCBConfig),
        ("sw_linucb_no_context.yaml", SWLinUCBConfig),
    ],
)
def test_every_policy_config_is_valid(name, model):
    model.model_validate(load_yaml(name))


def test_no_forgetting_ablation_differs_only_in_the_window():
    plain, windowed = load_yaml("linucb.yaml"), load_yaml("sw_linucb.yaml")
    for key in SHARED:
        assert plain[key] == windowed[key], f"linucb.yaml and sw_linucb.yaml differ in '{key}'"
    assert set(windowed) - set(plain) == {"window"}
    assert (plain["policy"], windowed["policy"]) == ("linucb", "sw_linucb")


def test_no_context_ablation_differs_only_in_use_context():
    full, no_context = load_yaml("sw_linucb.yaml"), load_yaml("sw_linucb_no_context.yaml")
    assert full["features"]["use_context"] is True
    assert no_context["features"]["use_context"] is False
    no_context["features"]["use_context"] = True
    assert no_context == full


def test_default_reward_lets_the_slo_term_dominate():
    for name in ("linucb.yaml", "sw_linucb.yaml", "sw_linucb_no_context.yaml"):
        assert slo_term_dominates(load_yaml(name)["reward"])


def test_lambda_is_one_as_in_the_brief():
    assert load_yaml("sw_linucb.yaml")["lambda"] == 1.0
