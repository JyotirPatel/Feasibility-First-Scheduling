"""Tests for the context vector (context_vector/features.py)."""

from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from context_vector import ContextBuilder, FeatureConfig, build_features, feature_names
from sur_factories import load_yaml, make_node, make_request

CONFIG = load_yaml("sw_linucb.yaml")["features"]

EXPECTED_NAMES = [
    "bias",
    "input_tokens",
    "expected_output_tokens",
    "slo_class=interactive",
    "slo_class=batch",
    "ttft_slo_ms",
    "rtt_ms",
    "queue_len",
    "running_frac",
    "kv_used_frac",
    "energy_price_usd_kwh",
    "gpu_price_usd_hr",
    "temperature_c",
    "warming",
]


def idx(name):
    return EXPECTED_NAMES.index(name)


# ── shape and exact values ──────────────────────────────────────────────────


def test_names_and_dimension():
    builder = ContextBuilder(CONFIG)
    assert builder.names == EXPECTED_NAMES == feature_names(CONFIG)
    assert builder.dim == 14
    assert builder.build(make_request(), make_node()).shape == (14,)


def test_vector_matches_hand_computed_values():
    x = build_features(make_request(), make_node(), CONFIG)
    expected = [
        1.0,
        850 / 8192,
        200 / 2048,
        1.0,
        0.0,  # interactive, not batch
        250 / 1000,
        12 / 300,  # nyc -> us-east-1
        7 / 64,
        22 / 32,  # running / capacity
        0.68,
        0.11 / 0.50,
        2.40 / 5.00,
        (71.0 - 20) / (100 - 20),
        0.0,  # not warming
    ]
    np.testing.assert_allclose(x, expected, rtol=0, atol=1e-12)


def test_every_feature_is_in_0_1_even_for_extreme_inputs():
    rng = np.random.default_rng(0)
    builder = ContextBuilder(CONFIG)
    for _ in range(500):
        request = make_request(
            input_tokens=int(rng.integers(0, 100_000)),
            expected_output_tokens=int(rng.integers(0, 50_000)),
            ttft_slo_ms=float(rng.uniform(1, 10_000)),
            slo_class=str(rng.choice(["interactive", "batch", "other"])),
        )
        node = make_node(
            rtt_ms={"nyc": float(rng.uniform(0, 2000))},
            queue_len=int(rng.integers(0, 1000)),
            running=int(rng.integers(0, 100)),
            capacity=int(rng.integers(1, 64)),
            kv_used_frac=float(rng.uniform(-0.5, 1.5)),
            energy_price_usd_kwh=float(rng.uniform(-0.2, 3.0)),  # real markets can go negative
            gpu_price_usd_hr=float(rng.uniform(0, 20)),
            temperature_c=float(rng.uniform(-10, 150)),
            status=str(rng.choice(["up", "warming"])),
        )
        x = builder.build(request, node)
        assert np.all(np.isfinite(x))
        assert np.all((x >= 0.0) & (x <= 1.0))


def test_values_outside_range_are_clipped():
    x = build_features(make_request(input_tokens=1_000_000), make_node(temperature_c=-40.0), CONFIG)
    assert x[idx("input_tokens")] == 1.0
    assert x[idx("temperature_c")] == 0.0


# ── field handling ───────────────────────────────────────────────────────────


def test_slo_deadline_prefers_ttft_slo_ms_then_slo_ms():
    both = make_request(ttft_slo_ms=250, slo_ms=900)
    only_slo_ms = make_request(slo_ms=500)
    del only_slo_ms["ttft_slo_ms"]
    assert build_features(both, make_node(), CONFIG)[idx("ttft_slo_ms")] == pytest.approx(0.25)
    assert build_features(only_slo_ms, make_node(), CONFIG)[idx("ttft_slo_ms")] == pytest.approx(0.5)

    neither = make_request()
    del neither["ttft_slo_ms"]
    with pytest.raises(KeyError, match="ttft_slo_ms"):
        build_features(neither, make_node(), CONFIG)


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf")])
def test_invalid_slo_deadline_raises(bad):
    with pytest.raises(ValueError):
        build_features(make_request(ttft_slo_ms=bad), make_node(), CONFIG)


def test_rtt_uses_the_users_region():
    x_chi = build_features(make_request(user_region="chi"), make_node(), CONFIG)
    assert x_chi[idx("rtt_ms")] == pytest.approx(25 / 300)


def test_rtt_falls_back_like_jyotirs_min_rtt():
    node = make_node(rtt_ms={"nyc": 12, "chi": 25, "sfo": 70})
    unknown_region = build_features(make_request(user_region="tokyo"), node, CONFIG)
    assert unknown_region[idx("rtt_ms")] == pytest.approx(((12 + 25 + 70) / 3) / 300)

    no_region = make_request()
    del no_region["user_region"]
    assert build_features(no_region, node, CONFIG)[idx("rtt_ms")] == pytest.approx(((12 + 25 + 70) / 3) / 300)

    no_data = build_features(make_request(), make_node(rtt_ms={}), CONFIG)
    assert no_data[idx("rtt_ms")] == 1.0  # unknown delay counts as the worst


def test_warming_flag_from_status_or_filter_tag():
    assert build_features(make_request(), make_node(status="warming"), CONFIG)[idx("warming")] == 1.0
    assert build_features(make_request(), {**make_node(), "_warming": True}, CONFIG)[idx("warming")] == 1.0
    assert build_features(make_request(), make_node(status="up"), CONFIG)[idx("warming")] == 0.0


def test_slo_class_flags():
    batch = build_features(make_request(slo_class="batch"), make_node(), CONFIG)
    assert (batch[idx("slo_class=interactive")], batch[idx("slo_class=batch")]) == (0.0, 1.0)
    unknown = build_features(make_request(slo_class="premium"), make_node(), CONFIG)
    assert (unknown[idx("slo_class=interactive")], unknown[idx("slo_class=batch")]) == (0.0, 0.0)


@pytest.mark.parametrize(
    "field",
    [
        "queue_len",
        "running",
        "capacity",
        "kv_used_frac",
        "rtt_ms",
        "energy_price_usd_kwh",
        "gpu_price_usd_hr",
        "temperature_c",
    ],
)
def test_missing_node_field_raises_keyerror_naming_it(field):
    node = make_node()
    del node[field]
    with pytest.raises(KeyError, match=field):
        build_features(make_request(), node, CONFIG)


@pytest.mark.parametrize("field", ["input_tokens", "expected_output_tokens"])
def test_missing_request_field_raises_keyerror_naming_it(field):
    request = make_request()
    del request[field]
    with pytest.raises(KeyError, match=field):
        build_features(request, make_node(), CONFIG)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("queue_len", -1, ValueError),
        ("running", float("nan"), ValueError),
        ("temperature_c", float("inf"), ValueError),
        ("capacity", 0, ValueError),
        ("kv_used_frac", True, TypeError),  # a bool is not a number here
        ("energy_price_usd_kwh", "0.11", TypeError),
    ],
)
def test_bad_node_values_raise(field, value, error):
    with pytest.raises(error):
        build_features(make_request(), make_node(**{field: value}), CONFIG)


def test_negative_rtt_raises():
    with pytest.raises(ValueError):
        build_features(make_request(), make_node(rtt_ms={"nyc": -3}), CONFIG)


def test_object_nodes_and_requests_work_like_dicts():
    as_dicts = build_features(make_request(), make_node(), CONFIG)
    as_objects = build_features(SimpleNamespace(**make_request()), SimpleNamespace(**make_node()), CONFIG)
    np.testing.assert_array_equal(as_dicts, as_objects)


# ── ablation and config checks ───────────────────────────────────────────────


def test_no_context_mode_is_bias_only():
    cfg = {**CONFIG, "use_context": False}
    builder = ContextBuilder(cfg)
    assert builder.names == ["bias"]
    np.testing.assert_array_equal(builder.build(make_request(), make_node()), [1.0])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["ranges"].pop("rtt_ms"),
        lambda c: c["ranges"].update({"made_up": {"min": 0, "max": 1}}),
        lambda c: c["ranges"].update({"rtt_ms": {"min": 5, "max": 5}}),
        lambda c: c["ranges"].update({"rtt_ms": {"min": 0, "max": float("inf")}}),
        lambda c: c.update({"slo_classes": ["interactive", "interactive"]}),
        lambda c: c.update({"slo_classes": []}),
        lambda c: c.update({"typo_key": 1}),
    ],
)
def test_bad_feature_config_is_rejected(mutate):
    cfg = {**CONFIG, "ranges": {k: dict(v) for k, v in CONFIG["ranges"].items()}}
    mutate(cfg)
    with pytest.raises(ValidationError):
        FeatureConfig.model_validate(cfg)


def test_works_on_the_real_filter_output():
    from feasibility_filter.filter import feasibility_filter
    from stubs.fake_node import FAKE_CLUSTER, FAKE_REQUEST

    allowed, _ = feasibility_filter(FAKE_REQUEST, FAKE_CLUSTER)
    builder = ContextBuilder(CONFIG)
    xs = {n["node_id"]: builder.build(FAKE_REQUEST, n) for n in allowed}  # FAKE_REQUEST uses "slo_ms"
    assert set(xs) == {"us-east-1", "us-central-1", "us-west-1"}
    assert xs["us-west-1"][idx("warming")] == 1.0
    assert xs["us-east-1"][idx("warming")] == 0.0
