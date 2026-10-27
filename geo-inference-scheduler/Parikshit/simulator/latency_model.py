"""
Latency model — owner: Parikshit

The brief's model of the time one request takes on a node (§5):

    T_total = T_network + T_queue + T_prefill + T_decode
    TTFT    = T_network + T_queue + T_prefill

    T_prefill = a_p + b_p · input_tokens                       fixed start cost + cost per prompt token
    T_decode  = output_tokens · t_tok · (1 + c · load)        slower when the node is busier

load is running requests / capacity, counting the request itself, taken when it starts.
T_network is the round-trip time between the user's region and the node. a_p, b_p, t_tok
and c are fitted per GPU type by simulator/calibration.py.

Two slowdowns multiply both GPU phases, both taken when the request starts:
  thermal  above throttle_start_c the GPU lowers its clocks; the slowdown grows linearly to
           max_slowdown at throttle_full_c (S4)
  warm-up  a node back from an outage starts warmup_slowdown times slower, falling linearly
           to normal speed over its warm-up (S6)
"""

from __future__ import annotations


def prefill_ms(a_p_ms: float, b_p_ms_per_token: float, input_tokens: int, slowdown: float = 1.0) -> float:
    return (a_p_ms + b_p_ms_per_token * input_tokens) * slowdown


def decode_ms(t_tok_ms: float, c: float, output_tokens: int, load: float, slowdown: float = 1.0) -> float:
    if not 0.0 <= load <= 1.0:
        raise ValueError(f"load must be running / capacity in [0, 1], got {load}")
    return output_tokens * t_tok_ms * (1.0 + c * load) * slowdown


def ttft_ms(network_ms: float, queue_ms: float, prefill: float) -> float:
    return network_ms + queue_ms + prefill


def e2e_ms(ttft: float, decode: float) -> float:
    return ttft + decode


def thermal_slowdown(temperature_c: float, start_c: float, full_c: float, max_slowdown: float) -> float:
    share = min(max((temperature_c - start_c) / (full_c - start_c), 0.0), 1.0)
    return 1.0 + (max_slowdown - 1.0) * share


def warmup_slowdown(t: float, warm_start: float | None, warm_end: float | None, max_slowdown: float) -> float:
    if warm_start is None or warm_end is None or not warm_start <= t < warm_end:
        return 1.0
    left = (warm_end - t) / (warm_end - warm_start)
    return 1.0 + (max_slowdown - 1.0) * left
