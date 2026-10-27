"""
One simulated node — owner: Parikshit

A node is a site with one or more 8-GPU servers serving one model (brief §5). It keeps:

  queue          requests waiting for a slot, first come first served
  running        requests being served; at most `capacity`
  KV cache       a request holds input + output tokens of KV cache while it runs; a request
                 only starts if it fits (brief: "a node cannot accept a request if its KV
                 cache memory would overflow")
  utilization    the share of its maximum token throughput the node is producing. With the decode
                 model, load L = running / capacity gives L·(1 + c) / (1 + c·L): batching makes a
                 node at 10 % of its slots already produce ~29 % of its maximum tokens per second
  power          draw = max power × (idle share + (1 - idle share) × utilization); headroom = the
                 site's provisioned power (max × (1 + margin)) minus the draw; 0 when down
  temperature    moves toward inlet + rise_at_full_power × (draw / max power), time constant tau
  prices         electricity price of the site's zone; GPU rent per GPU-hour
  status         up | down | warming

A request's times are fixed when it starts (simulator/latency_model.py). When it finishes,
its slot and KV cache are freed at once; its outcome reaches the router one network delay
later, when the last token reaches the user, i.e. at t_arrival + e2e.

Energy and cost: when a request starts it takes an equal share of the node's power draw and
GPU rent with the requests running then (draw / running, rent / running), and pays that share
for its service time; energy is charged at the site's electricity price. A lightly used node
therefore costs more per request, as a real idle server does.

Outage: every running and queued request fails at once and is reported with failed=True and
slo_met=False; its ttft_ms and e2e_ms are the time until the failure plus the network delay,
and it is charged for the GPU time it used. A request routed to a down node (the router's
telemetry can be up to one tick old) fails the same way.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import simpy

from simulator import latency_model as lm
from simulator.calibration import GpuConstants
from simulator.config import ClusterConfig, GpuSpec, NodeSpec
from telemetry.schema import SCHEMA_VERSION


@dataclass(eq=False)
class Job:
    request: dict
    output_tokens: int  # true number of tokens the request generates
    rtt_ms: float  # network delay between the user's region and the node when the request was sent
    t_start: float | None = None
    prefill_ms: float = 0.0
    decode_ms: float = 0.0
    price_usd_kwh: float = 0.0
    power_kw: float = 0.0  # its share of the node's power draw while it runs
    rent_usd_hr: float = 0.0  # its share of the node's GPU rent while it runs
    cancelled: bool = False  # set when the node went down while the request was running

    @property
    def kv_tokens(self) -> int:
        return int(self.request["input_tokens"]) + self.output_tokens

    @property
    def service_s(self) -> float:
        return (self.prefill_ms + self.decode_ms) / 1000.0


class Node:
    def __init__(
        self,
        env: simpy.Environment,
        spec: NodeSpec,
        gpu: GpuSpec,
        consts: GpuConstants,
        cluster: ClusterConfig,
        rtt_ms: dict[str, float],
        energy_price_usd_kwh: float,
        on_outcome: Callable[[dict], None],
    ):
        self.env, self.spec, self.consts, self.on_outcome = env, spec, consts, on_outcome
        self.node_id = spec.node_id
        self.thermal, self.power = cluster.thermal, cluster.power
        self.n_gpus = spec.servers * gpu.server_gpus
        self.capacity = self.n_gpus * consts.capacity
        self.kv_capacity = self.n_gpus * consts.kv_tokens
        self.power_max_kw = spec.servers * gpu.server_max_power_kw
        self.power_cap_kw = self.power_max_kw * (1.0 + cluster.power.provisioning_margin)
        self.gpu_price_usd_hr = gpu.rent_usd_per_gpu_hr
        self.base_rtt_ms = dict(rtt_ms)
        self.rtt_extra_ms = 0.0
        self.energy_price_usd_kwh = energy_price_usd_kwh

        self.status = "up"
        self.queue: deque[Job] = deque()
        self.running: dict[Job, None] = {}  # in start order
        self.kv_used = 0
        self.inlet_c = cluster.thermal.inlet_c
        self.temp_c = self._target_temp()  # starts at its idle steady state
        self._t_temp = env.now
        self.warm_start: float | None = None
        self.warm_end: float | None = None
        self.warm_slowdown = 1.0

    # ── state ────────────────────────────────────────────────────────────────

    @property
    def load(self) -> float:
        return len(self.running) / self.capacity

    @property
    def utilization(self) -> float:
        """Share of the node's maximum token throughput: L·(1 + c) / (1 + c·L)."""
        c, load = self.consts.c, self.load
        return load * (1.0 + c) / (1.0 + c * load)

    def power_share(self) -> float:
        if self.status == "down":
            return 0.0
        idle = self.power.idle_fraction
        return idle + (1.0 - idle) * self.utilization

    def power_headroom_kw(self) -> float:
        if self.status == "down":
            return 0.0
        return self.power_cap_kw - self.power_max_kw * self.power_share()

    def rtt_to(self, region: str) -> float:
        return self.base_rtt_ms[region] + self.rtt_extra_ms

    def _target_temp(self) -> float:
        return self.inlet_c + self.thermal.rise_at_full_power_c * self.power_share()

    def advance(self, now: float) -> None:
        """Move the temperature toward its target for the time since the last change (exact for a constant load)."""
        dt = now - self._t_temp
        if dt > 0:
            target = self._target_temp()
            self.temp_c = target + (self.temp_c - target) * math.exp(-dt / self.thermal.tau_s)
            self._t_temp = now

    def slowdown(self, now: float) -> float:
        th = self.thermal
        thermal = lm.thermal_slowdown(self.temp_c, th.throttle_start_c, th.throttle_full_c, th.max_slowdown)
        return thermal * lm.warmup_slowdown(now, self.warm_start, self.warm_end, self.warm_slowdown)

    def telemetry(self, now: float) -> dict:
        """One telemetry record, schema v1 (telemetry/telemetry_schema_v1.json)."""
        self.advance(now)
        return {
            "schema_version": SCHEMA_VERSION,
            "t": now,
            "node_id": self.node_id,
            "status": self.status,
            "rtt_ms": {region: ms + self.rtt_extra_ms for region, ms in self.base_rtt_ms.items()},
            "queue_len": len(self.queue),
            "running": len(self.running),
            "capacity": self.capacity,
            "kv_used_frac": self.kv_used / self.kv_capacity,
            "models_loaded": list(self.spec.models_loaded),
            "power_headroom_kw": self.power_headroom_kw(),
            "temperature_c": self.temp_c,
            "energy_price_usd_kwh": self.energy_price_usd_kwh,
            "gpu_price_usd_hr": self.gpu_price_usd_hr,
            "kv_capacity_tokens": self.kv_capacity,
        }

    # ── requests ─────────────────────────────────────────────────────────────

    def submit(self, job: Job) -> None:
        """The router sent this request here."""
        if self.status == "down":
            self.on_outcome(self._failure(job, self.env.now))
            return
        if job.kv_tokens > self.kv_capacity:
            raise ValueError(f"{job.request['request_id']} needs more KV cache than {self.node_id} has")
        self.queue.append(job)
        self._try_start()

    def _try_start(self) -> None:
        while self.queue and self.status != "down":
            job = self.queue[0]
            if len(self.running) >= self.capacity or self.kv_used + job.kv_tokens > self.kv_capacity:
                return
            self.queue.popleft()
            self._start(job)

    def _start(self, job: Job) -> None:
        now = self.env.now
        self.advance(now)
        k, slow = self.consts, self.slowdown(now)
        load = (len(self.running) + 1) / self.capacity
        job.t_start = now
        job.prefill_ms = lm.prefill_ms(k.a_p_ms, k.b_p_ms_per_token, job.request["input_tokens"], slow)
        job.decode_ms = lm.decode_ms(k.t_tok_ms, k.c, job.output_tokens, load, slow)
        job.price_usd_kwh = self.energy_price_usd_kwh
        self.running[job] = None
        self.kv_used += job.kv_tokens
        job.power_kw = self.power_max_kw * self.power_share() / len(self.running)
        job.rent_usd_hr = self.n_gpus * self.gpu_price_usd_hr / len(self.running)
        self.env.process(self._serve(job))

    def _serve(self, job: Job):
        yield self.env.timeout(job.service_s)
        if job.cancelled:
            return  # the node went down meanwhile; go_down() has reported the failure
        self.advance(self.env.now)
        del self.running[job]
        self.kv_used -= job.kv_tokens
        self._try_start()
        yield self.env.timeout(job.rtt_ms / 1000.0)  # the last token travels back to the user
        self.on_outcome(self._success(job))

    @staticmethod
    def _charges(job: Job, busy_s: float) -> tuple[float, float]:
        energy_kwh = job.power_kw * busy_s / 3600.0
        return energy_kwh, energy_kwh * job.price_usd_kwh + job.rent_usd_hr * busy_s / 3600.0

    def _success(self, job: Job) -> dict:
        r = job.request
        queue_ms = (job.t_start - r["t_arrival"]) * 1000.0
        ttft = lm.ttft_ms(job.rtt_ms, queue_ms, job.prefill_ms)
        e2e = lm.e2e_ms(ttft, job.decode_ms)
        energy, cost = self._charges(job, job.service_s)
        return {
            "request_id": r["request_id"],
            "ttft_ms": ttft,
            "e2e_ms": e2e,
            "slo_met": ttft <= r["ttft_slo_ms"],
            "energy_kwh": energy,
            "cost_usd": cost,
            "failed": False,
            "t_complete": r["t_arrival"] + e2e / 1000.0,
        }

    def _failure(self, job: Job, now: float) -> dict:
        r = job.request
        waited_ms = (now - r["t_arrival"]) * 1000.0 + job.rtt_ms
        energy, cost = self._charges(job, now - job.t_start) if job.t_start is not None else (0.0, 0.0)
        return {
            "request_id": r["request_id"],
            "ttft_ms": waited_ms,
            "e2e_ms": waited_ms,
            "slo_met": False,
            "energy_kwh": energy,
            "cost_usd": cost,
            "failed": True,
            "t_complete": now,
        }

    # ── scenario events ──────────────────────────────────────────────────────

    def go_down(self) -> int:
        """S6: the node fails. Every running and queued request fails now. Returns how many."""
        now = self.env.now
        self.advance(now)
        lost = list(self.running) + list(self.queue)
        for job in self.running:
            job.cancelled = True
        self.status, self.running, self.queue, self.kv_used = "down", {}, deque(), 0
        self.warm_start = self.warm_end = None
        for job in lost:
            self.on_outcome(self._failure(job, now))
        return len(lost)

    def come_back(self, warmup_s: float, warmup_slowdown: float) -> None:
        """S6: the node returns, warming (and slower) for warmup_s."""
        now = self.env.now
        self.advance(now)
        self.status = "warming"
        self.warm_start, self.warm_end, self.warm_slowdown = now, now + warmup_s, warmup_slowdown

    def warm_done(self) -> None:
        if self.status == "warming":
            self.advance(self.env.now)
            self.status = "up"

    def change_inlet(self, delta_c: float) -> None:
        """S4: the cooling gets worse (or better) by delta_c."""
        self.advance(self.env.now)
        self.inlet_c += delta_c

    def set_energy_price(self, usd_kwh: float) -> None:
        self.energy_price_usd_kwh = usd_kwh
