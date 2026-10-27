"""MOCK node simulator — stands in for Parikshit's SimPy simulator. NOT Parikshit's code.

Deliberately small (a heap of timed events, no SimPy) so it is obviously a test double.
What it does — just enough to exercise every router path:
  * N nodes with a capacity (concurrent slots), a FIFO queue, KV usage, RTT per region,
    a fixed temperature / power headroom / prices (one node can be configured too hot);
  * service time = prefill (a + b*input) + decode (out * t_tok * (1 + 0.5*load));
    TTFT = RTT + queue wait + prefill (brief §5 formula shape, made-up constants);
  * telemetry records (schema v1) every `tick_s` of simulated time;
  * optional outage: node goes down at t_down (in-flight + queued requests FAIL) and
    returns at t_up with status "warming" for `warmup_s`.

TODO(Parikshit): replace with the real simulator. The router needs exactly two calls from
it: router.ingest_telemetry(list[NodeState]) every tick, and router.feedback(Outcome)
when each request finishes (or POST /telemetry and POST /feedback over HTTP).
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import deque
from dataclasses import dataclass, field

from api_contract.types import NodeState, Outcome, Request


@dataclass
class MockNodeSpec:
    node_id: str
    capacity: int
    rtt_ms: dict[str, float]
    models: list[str] = field(default_factory=lambda: ["llama-3-8b"])
    prefill_a_ms: float = 20.0
    prefill_b_ms: float = 0.05
    tok_ms: float = 15.0
    kv_capacity_tokens: int = 60000
    temperature_c: float = 60.0
    power_headroom_kw: float = 5.0
    energy_price: float = 0.10
    gpu_price: float = 2.0


DEFAULT_NODES = [
    MockNodeSpec("node-east", 24, {"nyc": 8, "lon": 75, "sin": 220}, energy_price=0.11),
    MockNodeSpec("node-west", 24, {"nyc": 70, "lon": 140, "sin": 160}, energy_price=0.08),
    MockNodeSpec("node-eu", 16, {"nyc": 75, "lon": 12, "sin": 170}, energy_price=0.18),
    MockNodeSpec("node-asia", 12, {"nyc": 230, "lon": 165, "sin": 5}, energy_price=0.14),
    MockNodeSpec("node-hot", 16, {"nyc": 30, "lon": 100, "sin": 190}, temperature_c=91.0),
]


class _Node:
    def __init__(self, spec: MockNodeSpec):
        self.s = spec
        self.status = "up"
        self.queue: deque = deque()
        self.running: dict[str, tuple] = {}
        self.kv = 0
        self.t_warm_end = 0.0


class MockCluster:
    def __init__(
        self,
        router,
        nodes=None,
        seed=0,
        rate_rps=10.0,
        duration_s=120.0,
        tick_s=1.0,
        outage: tuple[str, float, float] | None = None,
        warmup_s: float = 20.0,
    ):
        self.router = router
        self.nodes = {s.node_id: _Node(s) for s in (nodes or DEFAULT_NODES)}
        self.rng = random.Random(seed)
        self.rate, self.duration, self.tick = rate_rps, duration_s, tick_s
        self.outage, self.warmup_s = outage, warmup_s
        self.now = 0.0
        self._ev: list = []
        self._seq = itertools.count()
        self.items: dict[str, tuple[Request, int]] = {}
        self.decisions: list = []

    # ── event plumbing ────────────────────────────────────────────────────────
    def _at(self, t: float, kind: str, payload=None) -> None:
        heapq.heappush(self._ev, (t, next(self._seq), kind, payload))

    def snapshot(self) -> list[NodeState]:
        out = []
        for n in self.nodes.values():
            s = n.s
            out.append(
                NodeState(
                    node_id=s.node_id,
                    status=n.status,
                    rtt_ms=dict(s.rtt_ms),
                    queue_len=len(n.queue),
                    running=len(n.running),
                    capacity=s.capacity,
                    kv_used_frac=n.kv / s.kv_capacity_tokens,
                    models_loaded=list(s.models),
                    power_headroom_kw=0.0 if n.status == "down" else s.power_headroom_kw,
                    temperature_c=s.temperature_c,
                    energy_price_usd_kwh=s.energy_price,
                    gpu_price_usd_hr=s.gpu_price,
                    t=self.now,
                    kv_capacity_tokens=s.kv_capacity_tokens,
                )
            )
        return out

    # ── node behaviour ────────────────────────────────────────────────────────
    def _submit(self, node_id: str, req: Request, out_tokens: int) -> None:
        n = self.nodes[node_id]
        if n.status == "down":
            self._finish_failed(req, enqueue_t=self.now, rtt=n.s.rtt_ms.get(req.user_region, 100))
            return
        n.queue.append((req, out_tokens, self.now))
        self._try_start(n)

    def _try_start(self, n: _Node) -> None:
        while n.queue and len(n.running) < n.s.capacity and n.status != "down":
            req, out_tokens, t_enq = n.queue[0]
            need = req.input_tokens + out_tokens
            if n.kv + need > n.s.kv_capacity_tokens:
                break
            n.queue.popleft()
            load = len(n.running) / n.s.capacity
            slow = 2.0 if (n.status == "warming" and self.now < n.t_warm_end) else 1.0
            prefill = (n.s.prefill_a_ms + n.s.prefill_b_ms * req.input_tokens) * slow
            decode = out_tokens * n.s.tok_ms * (1 + 0.5 * load) * slow
            rtt = n.s.rtt_ms.get(req.user_region, 100.0)
            ttft = rtt + (self.now - t_enq) * 1000 + prefill
            n.running[req.request_id] = (req, need, ttft, decode)
            n.kv += need
            self._at(self.now + (prefill + decode) / 1000, "done", (n.s.node_id, req.request_id))

    def _done(self, node_id: str, rid: str) -> None:
        n = self.nodes[node_id]
        if rid not in n.running:
            return  # killed by an outage
        req, need, ttft, decode_ms = n.running.pop(rid)
        n.kv -= need
        energy = 0.2 * decode_ms / 3.6e6  # 0.2 kW per slot during decode (made up)
        self.router.feedback(
            Outcome(
                rid,
                ttft,
                ttft + decode_ms,
                ttft <= req.ttft_slo_ms,
                energy,
                energy * n.s.energy_price,
                t_complete=self.now,
            )
        )
        self._try_start(n)

    def _finish_failed(self, req: Request, enqueue_t: float, rtt: float) -> None:
        ms = (self.now - enqueue_t) * 1000 + rtt
        self.router.feedback(
            Outcome(req.request_id, ms, ms, False, 0.0, 0.0, failed=True, t_complete=self.now)
        )

    def _go_down(self, node_id: str) -> None:
        n = self.nodes[node_id]
        n.status = "down"
        for req, *_ in list(n.running.values()):
            self._finish_failed(req, self.now, n.s.rtt_ms.get(req.user_region, 100))
        for req, _, t_enq in list(n.queue):
            self._finish_failed(req, t_enq, n.s.rtt_ms.get(req.user_region, 100))
        n.running.clear()
        n.queue.clear()
        n.kv = 0

    # ── run ───────────────────────────────────────────────────────────────────
    def run(self) -> None:
        t, i = 0.0, 0
        regions = ["nyc", "lon", "sin"]
        while True:
            t += self.rng.expovariate(self.rate)
            if t >= self.duration:
                break
            req = Request(
                f"m-{i:06d}",
                t,
                self.rng.choice(regions),
                "llama-3-8b",
                self.rng.randint(100, 2000),
                self.rng.randint(20, 400),
                "interactive",
                250.0,
            )
            self._at(
                t,
                "arrive",
                (req, max(1, int(req.expected_output_tokens * self.rng.uniform(0.7, 1.3)))),
            )
            i += 1
        k = 0.0
        while k <= self.duration:
            self._at(k, "tick")
            k += self.tick
        if self.outage:
            nid, t_down, t_up = self.outage
            self._at(t_down, "down", nid)
            self._at(t_up, "up", nid)
        while self._ev:
            self.now, _, kind, p = heapq.heappop(self._ev)
            if kind == "tick":
                for n in self.nodes.values():
                    if n.status == "warming" and self.now >= n.t_warm_end:
                        n.status = "up"
                self.router.ingest_telemetry(self.snapshot())
            elif kind == "arrive":
                req, out_tokens = p
                d = self.router.route(req)
                self.decisions.append(d)
                if d.decision == "route":
                    self._submit(d.node_id, req, out_tokens)
            elif kind == "done":
                self._done(*p)
            elif kind == "down":
                self._go_down(p)
            elif kind == "up":
                self.nodes[p].status = "warming"
                self.nodes[p].t_warm_end = self.now + self.warmup_s
