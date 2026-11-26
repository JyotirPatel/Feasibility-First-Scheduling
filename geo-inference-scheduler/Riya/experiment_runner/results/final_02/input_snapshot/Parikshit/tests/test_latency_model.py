"""The brief's latency model (§5) and the two slowdowns, on hand-computed numbers."""

import pytest

from simulator import latency_model as lm


def test_prefill_is_fixed_cost_plus_cost_per_input_token():
    assert lm.prefill_ms(20.0, 0.1, 1000) == pytest.approx(120.0)
    assert lm.prefill_ms(20.0, 0.1, 1000, slowdown=2.0) == pytest.approx(240.0)
    assert lm.prefill_ms(20.0, 0.1, 0) == pytest.approx(20.0)


def test_decode_grows_with_output_tokens_and_load():
    assert lm.decode_ms(10.0, 2.0, 100, load=0.0) == pytest.approx(1000.0)
    assert lm.decode_ms(10.0, 2.0, 100, load=0.5) == pytest.approx(2000.0)
    assert lm.decode_ms(10.0, 2.0, 100, load=1.0) == pytest.approx(3000.0)
    assert lm.decode_ms(10.0, 2.0, 100, load=1.0, slowdown=1.5) == pytest.approx(4500.0)
    for bad in (-0.1, 1.01):
        with pytest.raises(ValueError):
            lm.decode_ms(10.0, 2.0, 100, load=bad)


def test_ttft_and_total_compose_like_the_brief():
    ttft = lm.ttft_ms(network_ms=30.0, queue_ms=5.0, prefill=100.0)
    assert ttft == pytest.approx(135.0)  # TTFT = network + queue + prefill
    assert lm.e2e_ms(ttft, 900.0) == pytest.approx(1035.0)  # total = TTFT + decode


@pytest.mark.parametrize("temp,expected", [(60.0, 1.0), (80.0, 1.0), (85.0, 1.5), (90.0, 2.0), (99.0, 2.0)])
def test_thermal_slowdown_is_linear_between_start_and_full(temp, expected):
    assert lm.thermal_slowdown(temp, 80.0, 90.0, 2.0) == pytest.approx(expected)


def test_warmup_slowdown_falls_linearly_to_one():
    assert lm.warmup_slowdown(400.0, 400.0, 460.0, 3.0) == pytest.approx(3.0)
    assert lm.warmup_slowdown(430.0, 400.0, 460.0, 3.0) == pytest.approx(2.0)
    assert lm.warmup_slowdown(460.0, 400.0, 460.0, 3.0) == 1.0
    assert lm.warmup_slowdown(399.0, 400.0, 460.0, 3.0) == 1.0
    assert lm.warmup_slowdown(430.0, None, None, 3.0) == 1.0
