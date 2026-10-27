"""One node (simulator/node.py): queueing, KV-cache admission, timing, outage, warm-up, heat and power."""

import math

import pytest
import simpy

from simulator.calibration import GpuConstants
from simulator.config import GpuSpec, load_cluster
from simulator.node import Job, Node

CLUSTER = load_cluster(5)
SPEC = CLUSTER.nodes[0]  # us-east-nyc
GPU = GpuSpec(
    memory_gb=80,
    memory_bandwidth_tb_s=3.35,
    bf16_dense_tflops=989.5,
    server_gpus=1,
    server_max_power_kw=10.0,
    rent_usd_per_gpu_hr=4.0,
)  # one GPU per server, so capacity and KV size are exactly the constants below


def make_node(env, outcomes, capacity=2, kv_tokens=100_000, a_p=10.0, b_p=0.1, t_tok=10.0, c=2.0, cluster=CLUSTER):
    consts = GpuConstants("test", a_p, b_p, t_tok, c, capacity, kv_tokens, max_rps=1.0)
    rtt = {"nyc": 20.0, "lax": 60.0}
    return Node(env, SPEC, GPU, consts, cluster, rtt, 0.05, lambda o: outcomes.append((env.now, o)))


def request(rid, t, inp=100, out=10, slo=250.0, region="nyc"):
    return {
        "request_id": rid,
        "t_arrival": t,
        "user_region": region,
        "model": "llama-3-8b",
        "input_tokens": inp,
        "expected_output_tokens": out,
        "slo_class": "interactive",
        "ttft_slo_ms": slo,
    }


def submit_at(env, node, t, job):
    def go():
        yield env.timeout(t - env.now)
        node.submit(job)

    env.process(go())


def test_one_request_timing_matches_the_latency_model():
    env, out = simpy.Environment(), []
    node = make_node(env, out)
    node.submit(Job(request("r1", 0.0, inp=100, out=10), 10, rtt_ms=20.0))
    env.run()
    t, o = out[0]
    prefill = 10.0 + 0.1 * 100  # a_p + b_p * input
    decode = 10 * 10.0 * (1 + 2.0 * 1 / 2)  # out * t_tok * (1 + c * load), load = 1 running / capacity 2
    assert o["ttft_ms"] == pytest.approx(20.0 + prefill)  # network + no queue + prefill
    assert o["e2e_ms"] == pytest.approx(20.0 + prefill + decode)
    assert t == pytest.approx(o["e2e_ms"] / 1000)  # the outcome arrives when the last token reaches the user
    assert o["t_complete"] == pytest.approx(t) and o["slo_met"] is True and o["failed"] is False


def test_requests_queue_first_come_first_served_when_slots_are_full():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=2)
    jobs = [Job(request(f"r{i}", 0.0, out=100), 100, 20.0) for i in range(3)]
    for j in jobs:
        node.submit(j)
    assert len(node.running) == 2 and [j.request["request_id"] for j in node.queue] == ["r2"]
    env.run()
    ids = [o["request_id"] for _, o in out]
    assert sorted(ids) == ["r0", "r1", "r2"]
    first_done = min(t for t, o in out if o["request_id"] in ("r0", "r1"))
    r2 = next(o for _, o in out if o["request_id"] == "r2")
    assert r2["ttft_ms"] > 20.0 + 20.0  # it waited in the queue, which counts in its TTFT
    assert jobs[2].t_start == pytest.approx(first_done - 0.020)  # it started when a slot freed (before the RTT)


def test_waiting_requests_start_in_arrival_order():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=1)
    jobs = [Job(request(f"r{i}", 0.0), 10, 20.0) for i in range(4)]
    for j in jobs:
        node.submit(j)
    env.run()
    starts = [j.t_start for j in jobs]
    assert starts == sorted(starts) and len(set(starts)) == len(jobs)  # one slot: each starts after the one before


def test_a_request_only_starts_if_its_kv_cache_fits():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=10, kv_tokens=1_000)
    node.submit(Job(request("big", 0.0, inp=700, out=100), 100, 20.0))  # 800 tokens
    node.submit(Job(request("next", 0.0, inp=150, out=100), 100, 20.0))  # 250 more would overflow
    assert len(node.running) == 1 and node.kv_used == 800 and len(node.queue) == 1
    rec = node.telemetry(0.0)
    assert rec["kv_used_frac"] == pytest.approx(0.8) and rec["kv_capacity_tokens"] == 1_000
    env.run()
    assert len(out) == 2 and node.kv_used == 0
    with pytest.raises(ValueError, match="KV cache"):
        node.submit(Job(request("huge", env.now, inp=2_000, out=10), 10, 20.0))


def test_decode_is_slower_when_the_node_is_busier():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=4)
    first, second = Job(request("a", 0.0), 10, 20.0), Job(request("b", 0.0), 10, 20.0)
    node.submit(first)
    node.submit(second)
    assert second.decode_ms / first.decode_ms == pytest.approx((1 + 2.0 * 2 / 4) / (1 + 2.0 * 1 / 4))


def test_an_outage_fails_running_and_queued_requests_once():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=1)
    for i in range(3):
        node.submit(Job(request(f"r{i}", 0.0, out=200), 200, 20.0))

    def outage():
        yield env.timeout(1.0)
        assert node.go_down() == 3

    env.process(outage())
    env.run()
    assert len(out) == 3 and all(o["failed"] and not o["slo_met"] for _, o in out)
    assert all(t == pytest.approx(1.0) for t, _ in out)  # reported at the moment of the failure
    running = next(o for _, o in out if o["request_id"] == "r0")
    assert running["ttft_ms"] == pytest.approx(1000.0 + 20.0) and running["energy_kwh"] > 0  # it used 1 s of GPU
    queued = next(o for _, o in out if o["request_id"] == "r2")
    assert queued["energy_kwh"] == 0.0 and queued["cost_usd"] == 0.0
    rec = node.telemetry(env.now)
    assert (rec["status"], rec["running"], rec["queue_len"], rec["kv_used_frac"], rec["power_headroom_kw"]) == (
        "down",
        0,
        0,
        0.0,
        0.0,
    )


def test_a_request_sent_to_a_down_node_fails_at_once():
    env, out = simpy.Environment(), []
    node = make_node(env, out)
    node.go_down()
    node.submit(Job(request("late", 0.0), 10, 35.0))
    assert out[0][1]["failed"] and out[0][1]["ttft_ms"] == pytest.approx(35.0)


def test_warm_up_is_slower_then_back_to_normal():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=100)
    node.go_down()
    node.come_back(warmup_s=60.0, warmup_slowdown=3.0)
    assert node.status == "warming" and node.slowdown(0.0) == pytest.approx(3.0)
    slow = Job(request("w", 0.0), 10, 20.0)
    node.submit(slow)
    submit_at(env, node, 30.0, mid := Job(request("m", 30.0), 10, 20.0))
    submit_at(env, node, 70.0, fast := Job(request("f", 70.0), 10, 20.0))

    def done():
        yield env.timeout(60.0)
        node.warm_done()

    env.process(done())
    env.run()
    assert node.status == "up"
    assert slow.prefill_ms / fast.prefill_ms == pytest.approx(3.0)
    assert mid.prefill_ms / fast.prefill_ms == pytest.approx(2.0)


def test_temperature_follows_the_first_order_model_and_throttles():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=1)
    th, power = CLUSTER.thermal, CLUSTER.power
    idle_temp = th.inlet_c + th.rise_at_full_power_c * power.idle_fraction
    assert node.temp_c == pytest.approx(idle_temp)
    node.change_inlet(40.0)
    node.submit(Job(request("hot", 0.0, out=1000), 1000, 20.0))  # full load: utilization 1
    target = th.inlet_c + 40.0 + th.rise_at_full_power_c
    node.advance(30.0)
    assert node.temp_c == pytest.approx(target + (idle_temp - target) * math.exp(-30.0 / th.tau_s))
    assert node.temp_c > th.throttle_start_c and node.slowdown(30.0) > 1.0


def test_power_follows_utilization_and_headroom_is_what_is_left():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=4, c=2.0)
    for i in range(2):
        node.submit(Job(request(f"r{i}", 0.0), 10, 20.0))
    u = 0.5 * 3.0 / (1 + 2.0 * 0.5)  # L(1 + c)/(1 + cL) at L = 0.5
    assert node.utilization == pytest.approx(u)
    draw = 10.0 * (CLUSTER.power.idle_fraction + (1 - CLUSTER.power.idle_fraction) * u)
    assert node.power_headroom_kw() == pytest.approx(10.0 * (1 + CLUSTER.power.provisioning_margin) - draw)


def test_energy_and_cost_are_each_requests_share_of_draw_and_rent():
    env, out = simpy.Environment(), []
    node = make_node(env, out, capacity=4)
    job = Job(request("solo", 0.0), 10, 20.0)
    node.submit(job)
    env.run()
    o = out[0][1]
    draw_kw = 10.0 * node.power.idle_fraction + 10.0 * (1 - node.power.idle_fraction) * (0.25 * 3 / 1.5)
    assert o["energy_kwh"] == pytest.approx(draw_kw * job.service_s / 3600)  # alone: the whole draw
    assert o["cost_usd"] == pytest.approx(o["energy_kwh"] * 0.05 + 4.0 * job.service_s / 3600)
