"""The calibration of the latency model (simulator/calibration.py) and the numbers it gives."""

import math
import re

import numpy as np
import pytest

from simulator.calibration import (
    calibrate,
    default_constants,
    fit_gpu_time,
    fit_line,
    kv_bytes_per_token,
    report,
    weight_bytes,
)
from simulator.config import PARIKSHIT_DIR, load_calibration, load_workload

CAL = load_calibration()


def test_llama_3_8b_kv_cache_and_weights():
    # 2 (K and V) x 32 layers x 8 KV heads x 128 dims x 2 bytes
    assert kv_bytes_per_token(CAL.model) == 131_072
    assert weight_bytes(CAL.model) == pytest.approx(16.06e9)


def test_fit_line_is_least_squares():
    assert fit_line([(0, 1), (1, 3), (2, 5)]) == pytest.approx((1.0, 2.0))
    a, b = fit_line(CAL.benchmark.ttft_ms)
    x, y = np.array(CAL.benchmark.ttft_ms).T
    assert np.sum(y - (a + b * x)) == pytest.approx(0.0, abs=1e-9)  # residuals of a least-squares line sum to 0


def test_fit_gpu_time_recovers_known_costs():
    p, d = 4e-5, 2e-4
    points = [(i, o, 1 / (p * i + d * o)) for i, o in [(100, 100), (2000, 50), (500, 1500)]]
    assert fit_gpu_time(points) == pytest.approx((p, d))
    with pytest.raises(ValueError):
        fit_gpu_time([(100, 100, 1.0), (100, 1000, 10.0)])  # more output tokens yet faster -> negative cost


def test_constants_follow_the_stated_derivation():
    mean_in, mean_out = 1400.0, 150.0
    k = calibrate(CAL, mean_in, mean_out)
    ref, a100 = CAL.gpus["H100-SXM"], CAL.gpus["A100-80GB-SXM"]
    h, a = k["H100-SXM"], k["A100-80GB-SXM"]
    eff = CAL.serving.decode_bandwidth_efficiency
    assert h.t_tok_ms == pytest.approx(16.06e9 / (3.35e12 * eff) * 1000)
    assert a.t_tok_ms / h.t_tok_ms == pytest.approx(ref.memory_bandwidth_tb_s / a100.memory_bandwidth_tb_s)
    assert a.b_p_ms_per_token / h.b_p_ms_per_token == pytest.approx(ref.bf16_dense_tflops / a100.bf16_dense_tflops)
    assert a.a_p_ms / h.a_p_ms == pytest.approx(ref.memory_bandwidth_tb_s / a100.memory_bandwidth_tb_s)
    assert h.c == a.c == pytest.approx(np.mean(CAL.benchmark.tpot_at_saturation_ms) / h.t_tok_ms - 1)
    for g in (h, a):
        service_full_s = (g.a_p_ms + g.b_p_ms_per_token * mean_in + mean_out * g.t_tok_ms * (1 + g.c)) / 1000
        assert abs(g.capacity - g.max_rps * service_full_s) <= 0.5  # capacity reaches the benchmark throughput
        assert g.kv_tokens == math.floor((80e9 * 0.9 - 16.06e9) / 131_072)
    assert h.max_rps > a.max_rps and h.capacity > a.capacity


def test_a_gpu_too_small_for_one_full_request_is_refused():
    tiny = CAL.model_copy(
        update={"gpus": {**CAL.gpus, "H100-SXM": CAL.gpus["H100-SXM"].model_copy(update={"memory_gb": 18.0})}}
    )
    with pytest.raises(ValueError, match="KV cache"):
        calibrate(tiny, 1400.0, 150.0)


def test_numbers_md_shows_the_current_calibration():
    """simulator/NUMBERS.md quotes the calibration table; it must match what the code computes now."""
    with open(f"{PARIKSHIT_DIR}/simulator/NUMBERS.md", encoding="utf-8") as f:
        text = f.read()
    block = re.search(r"<!-- calibration:start -->\n```text\n(.*?)```\n<!-- calibration:end -->", text, re.S)
    assert block, "NUMBERS.md has no calibration block"
    assert block.group(1).strip() == report(CAL, load_workload()).strip()


def test_default_constants_use_the_shipped_files():
    k = default_constants()
    assert set(k) == set(CAL.gpus)
    assert all(g.capacity >= 1 for g in k.values())
