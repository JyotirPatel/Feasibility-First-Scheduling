"""Request generation (simulator/workload.py): reproducible, real token mixes, the right rates, S2 bursts."""

import numpy as np
import pytest

from helpers import light_workload, short_scenario
from simulator.config import load_scenario, load_workload
from simulator.data import load_trace
from simulator.workload import _rng, generate

W = load_workload()
TRACES = {c.trace: load_trace(c.trace) for c in W.classes.values()}
S1, S2 = load_scenario("s1_stable"), load_scenario("s2_traffic_burst")
CONTRACT_FIELDS = {
    "request_id",
    "t_arrival",
    "user_region",
    "model",
    "input_tokens",
    "expected_output_tokens",
    "slo_class",
    "ttft_slo_ms",
}


def _key(item):
    r = item.request
    return (r["t_arrival"], r["slo_class"], r["user_region"], r["input_tokens"], item.output_tokens)


def test_same_seed_same_requests_and_other_seeds_differ():
    a, b = generate(W, S1, 3, TRACES), generate(W, S1, 3, TRACES)
    assert [x.request for x in a] == [x.request for x in b]
    assert [x.output_tokens for x in a] == [x.output_tokens for x in b]
    c = generate(W, S1, 4, TRACES)
    assert [_key(x) for x in a] != [_key(x) for x in c]


def test_requests_follow_the_contract_and_time_order():
    items = generate(light_workload(), short_scenario("s1_stable"), 0, TRACES)
    times = [x.request["t_arrival"] for x in items]
    assert times == sorted(times) and times[0] > 0 and times[-1] < 120
    assert [x.request["request_id"] for x in items] == [f"r-{i:06d}" for i in range(len(items))]
    for x in items:
        assert set(x.request) == CONTRACT_FIELDS
        assert x.request["model"] == "llama-3-8b"
        assert x.request["ttft_slo_ms"] == W.classes[x.request["slo_class"]].ttft_slo_ms


def test_rate_class_shares_and_regions():
    items = generate(W, S1, 0, TRACES)
    assert len(items) / S1.duration_s == pytest.approx(W.rate_rps, rel=0.03)
    classes = [x.request["slo_class"] for x in items]
    for cls, spec in W.classes.items():
        assert classes.count(cls) / len(items) == pytest.approx(spec.share, abs=0.01)
    pop = {r: spec.population for r, spec in W.regions.items()}
    regions = [x.request["user_region"] for x in items]
    for r, p in pop.items():
        assert regions.count(r) / len(items) == pytest.approx(p / sum(pop.values()), abs=0.01)


def test_token_pairs_come_from_the_class_traces():
    items = generate(W, S1, 1, TRACES)
    for cls, spec in W.classes.items():
        t = TRACES[spec.trace]
        real = set(zip(t.input_tokens.tolist(), t.output_tokens.tolist(), strict=True))
        drawn = [(x.request["input_tokens"], x.output_tokens) for x in items if x.request["slo_class"] == cls]
        assert drawn and all(pair in real for pair in drawn)
        assert np.mean([i for i, _ in drawn]) == pytest.approx(t.mean_input, rel=0.05)


def test_output_estimate_error_is_bounded_and_spread_as_configured():
    e = W.expected_output_error
    items = generate(W, S1, 2, TRACES)
    for x in items:
        est, true = x.request["expected_output_tokens"], x.output_tokens
        assert est >= 1 and abs(est - true) <= e * true + 0.5
    ratios = np.array([x.request["expected_output_tokens"] / x.output_tokens for x in items if x.output_tokens >= 50])
    assert ratios.mean() == pytest.approx(1.0, abs=0.01)
    assert ratios.std() == pytest.approx(2 * e / np.sqrt(12), rel=0.1)  # the spread of U(1 - e, 1 + e)


def test_every_class_and_stream_has_its_own_random_numbers():
    """S2's burst streams must not replay the base stream's draws (or another class's)."""
    draws = {(cls, s): tuple(_rng(7, cls, s).random(4)) for cls in W.classes for s in range(3)}
    assert len(set(draws.values())) == len(draws)
    assert tuple(_rng(7, "batch", 1).random(4)) == draws[("batch", 1)]  # and each is reproducible


def test_trace_gaps_keep_the_traces_burstiness():
    items = [x for x in generate(W, S1, 0, TRACES) if x.request["slo_class"] == "interactive"]
    gaps = np.diff([x.request["t_arrival"] for x in items])
    real = TRACES["azure_conv"].gaps_s
    assert gaps.std() / gaps.mean() == pytest.approx(real.std() / real.mean(), rel=0.1)


def test_s2_adds_a_burst_and_keeps_every_s1_request():
    s1, s2 = generate(W, S1, 5, TRACES), generate(W, S2, 5, TRACES)
    k1, k2 = {_key(x) for x in s1}, {_key(x) for x in s2}
    assert k1 <= k2  # the base streams are the same in both scenarios
    burst = S2.events[0]
    extra = [k for k in k2 - k1]
    assert all(burst.at_s <= k[0] < burst.at_s + burst.duration_s for k in extra)
    in_window = [x for x in s2 if burst.at_s <= x.request["t_arrival"] < burst.at_s + burst.duration_s]
    rate = len(in_window) / burst.duration_s
    assert rate == pytest.approx(burst.factor * W.rate_rps, rel=0.05)
