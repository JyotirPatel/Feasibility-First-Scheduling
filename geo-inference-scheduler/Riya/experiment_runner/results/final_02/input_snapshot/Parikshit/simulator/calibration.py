"""
Latency-model calibration — owner: Parikshit

Fits the brief's latency model (§5) for every GPU type in configs/calibration.yaml:

    T_prefill = a_p + b_p · input_tokens
    T_decode  = output_tokens · t_tok · (1 + c · load),   load = running / capacity

The steps (simulator/NUMBERS.md explains each one and its sources):

  1. a_p, b_p   least-squares line through the benchmark's TTFT points (TTFT vs input tokens),
                measured on the benchmark GPU; other GPUs scale b_p by compute (dense BF16
                TFLOPS) and a_p by memory bandwidth.
  2. t_tok      decode is memory-bound: every output token reads all weights once, so
                t_tok = weight bytes / (memory bandwidth × decode_bandwidth_efficiency).
  3. c          the benchmark's mean time per output token at saturation = t_tok · (1 + c).
  4. capacity   the benchmark's saturated runs give the GPU time per input and per output
                token (least squares of 1 / throughput); for the workload's mean request this
                is the GPU's maximum throughput. capacity is the number of running requests
                at which the model reaches that throughput: max_rps × service time at load 1.
  5. KV tokens  (memory × gpu_memory_utilization − weights) / KV bytes per token.

Usage (from the Parikshit/ folder):
    python3 simulator/calibration.py      # prints the constants and the fit residuals
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass

import numpy as np

if __package__ in (None, ""):  # run as a script
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.config import CalibrationConfig, ModelSpec, WorkloadConfig, load_calibration, load_workload
from simulator.data import Trace, load_trace


@dataclass(frozen=True)
class GpuConstants:
    """Fitted latency-model constants for one GPU (per GPU; a node multiplies capacity and KV by its GPUs)."""

    gpu: str
    a_p_ms: float  # fixed prefill cost
    b_p_ms_per_token: float  # prefill cost per input token
    t_tok_ms: float  # decode time per output token when the GPU is nearly idle
    c: float  # decode slowdown at full load
    capacity: int  # running requests per GPU
    kv_tokens: int  # KV-cache tokens per GPU
    max_rps: float  # benchmark-implied maximum throughput for the workload's mean request


def kv_bytes_per_token(m: ModelSpec) -> float:
    """Keys and values of every layer and KV head: 2 × layers × kv_heads × head_dim × bytes."""
    return 2 * m.layers * m.kv_heads * m.head_dim * m.kv_bytes_per_value


def weight_bytes(m: ModelSpec) -> float:
    return m.params * m.bytes_per_param


def fit_line(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares (intercept, slope) of y = intercept + slope · x."""
    x, y = np.array(points, dtype=float).T
    slope, intercept = np.polyfit(x, y, 1)
    return float(intercept), float(slope)


def fit_gpu_time(points: list[tuple[float, float, float]]) -> tuple[float, float]:
    """Least-squares (s per input token, s per output token) of 1 / throughput = p · input + d · output."""
    a = np.array([[i, o] for i, o, _ in points], dtype=float)
    y = np.array([1.0 / x for _, _, x in points], dtype=float)
    (p, d), *_ = np.linalg.lstsq(a, y, rcond=None)
    if p <= 0 or d <= 0:
        raise ValueError(f"the saturated benchmark points give a non-positive GPU time per token: {p}, {d}")
    return float(p), float(d)


def t_tok_ms(m: ModelSpec, memory_bandwidth_tb_s: float, efficiency: float) -> float:
    return weight_bytes(m) / (memory_bandwidth_tb_s * 1e12 * efficiency) * 1000.0


def calibrate(cal: CalibrationConfig, mean_input: float, mean_output: float) -> dict[str, GpuConstants]:
    """Constants for every GPU type, for a workload whose mean request has these token counts."""
    ref = cal.gpus[cal.benchmark.gpu]
    a_ref, b_ref = fit_line(cal.benchmark.ttft_ms)
    p_ref, d_ref = fit_gpu_time(cal.benchmark.saturated)
    eff = cal.serving.decode_bandwidth_efficiency
    c = float(np.mean(cal.benchmark.tpot_at_saturation_ms)) / t_tok_ms(cal.model, ref.memory_bandwidth_tb_s, eff) - 1
    if c < 0:
        raise ValueError("the benchmark's time per token at saturation is below the low-load estimate")
    kv_per_token = kv_bytes_per_token(cal.model)

    out = {}
    for name, g in cal.gpus.items():
        compute_ratio = ref.bf16_dense_tflops / g.bf16_dense_tflops
        bandwidth_ratio = ref.memory_bandwidth_tb_s / g.memory_bandwidth_tb_s
        a_p, b_p = a_ref * bandwidth_ratio, b_ref * compute_ratio
        t_tok = t_tok_ms(cal.model, g.memory_bandwidth_tb_s, eff)
        max_rps = 1.0 / (mean_input * p_ref * compute_ratio + mean_output * d_ref * bandwidth_ratio)
        service_full_s = (a_p + b_p * mean_input + mean_output * t_tok * (1 + c)) / 1000.0
        kv_tokens = math.floor(
            (g.memory_gb * 1e9 * cal.serving.gpu_memory_utilization - weight_bytes(cal.model)) / kv_per_token
        )
        if kv_tokens < cal.model.max_context_tokens:
            raise ValueError(f"{name}: the KV cache cannot hold even one full-length request")
        out[name] = GpuConstants(
            gpu=name,
            a_p_ms=a_p,
            b_p_ms_per_token=b_p,
            t_tok_ms=t_tok,
            c=c,
            capacity=max(1, round(max_rps * service_full_s)),
            kv_tokens=kv_tokens,
            max_rps=max_rps,
        )
    return out


def workload_mean_tokens(workload: WorkloadConfig, traces: dict[str, Trace]) -> tuple[float, float]:
    """Mean input and output tokens of a request, weighting each class's trace by its share."""
    mean_in = sum(c.share * traces[c.trace].mean_input for c in workload.classes.values())
    mean_out = sum(c.share * traces[c.trace].mean_output for c in workload.classes.values())
    return mean_in, mean_out


def default_constants(
    cal: CalibrationConfig | None = None, workload: WorkloadConfig | None = None
) -> dict[str, GpuConstants]:
    """Constants for the shipped calibration and workload files."""
    cal = cal or load_calibration()
    workload = workload or load_workload()
    traces = {c.trace: load_trace(c.trace) for c in workload.classes.values()}
    return calibrate(cal, *workload_mean_tokens(workload, traces))


def report(cal: CalibrationConfig, workload: WorkloadConfig) -> str:
    traces = {c.trace: load_trace(c.trace) for c in workload.classes.values()}
    mean_in, mean_out = workload_mean_tokens(workload, traces)
    consts = calibrate(cal, mean_in, mean_out)
    a, b = fit_line(cal.benchmark.ttft_ms)
    p, d = fit_gpu_time(cal.benchmark.saturated)
    lines = [
        f"workload mean request: {mean_in:.0f} input tokens, {mean_out:.0f} output tokens",
        f"KV cache: {kv_bytes_per_token(cal.model):,.0f} bytes per token; "
        f"weights {weight_bytes(cal.model) / 1e9:.2f} GB",
        f"TTFT fit on {cal.benchmark.gpu}: a_p = {a:.2f} ms, b_p = {b:.5f} ms/token",
    ]
    lines += [f"   {i:5.0f} tokens: measured {y:7.2f} ms, fitted {a + b * i:7.2f} ms" for i, y in cal.benchmark.ttft_ms]
    lines.append(
        f"GPU time fit on {cal.benchmark.gpu}: {p * 1e3:.4f} ms per input token, {d * 1e3:.4f} ms per output token"
    )
    lines += [
        f"   {i:5.0f} in / {o:5.0f} out: measured {x:6.2f} req/s, fitted {1 / (p * i + d * o):6.2f} req/s"
        for i, o, x in cal.benchmark.saturated
    ]
    lines.append("")
    lines.append(
        f"{'GPU':16s} {'a_p ms':>7s} {'b_p ms/tok':>10s} {'t_tok ms':>8s} {'c':>5s} {'cap/GPU':>7s} "
        f"{'KV tok/GPU':>10s} {'max req/s/GPU':>13s}"
    )
    for k in consts.values():
        lines.append(
            f"{k.gpu:16s} {k.a_p_ms:7.2f} {k.b_p_ms_per_token:10.5f} {k.t_tok_ms:8.2f} {k.c:5.2f} {k.capacity:7d} "
            f"{k.kv_tokens:10,d} {k.max_rps:13.2f}"
        )
    return "\n".join(lines)


def main() -> int:
    print(report(load_calibration(), load_workload()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
