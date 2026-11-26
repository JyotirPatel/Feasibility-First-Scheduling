"""
Stand-in node simulator — owner: Sur (TEMPORARY)

Parikshit owns the real simulator (SimPy, real traces). Until it exists, this
small event-driven simulator lets Sur test the policies and run the window
sweep end to end, the same way the real system will run them:

  request -> Jyotir's real feasibility filter -> policy.choose -> node -> outcome -> policy.update

It follows the brief:
  latency (§5)   TTFT = network + queue wait + prefill;  total = TTFT + decode
                 prefill = a_p + b_p · input_tokens
                 decode  = output_tokens · t_tok · (1 + c · running/capacity)
                           (running includes the request itself, taken when it starts)
  nodes (§5)     queue, running requests, KV cache, power headroom,
                 temperature, prices, status up / down / warming
  formats        telemetry records (§10.1) and decision-log rows (§10.3)
  scenarios (§5) S1–S6, 600 s runs, change at t0 = 200 s

The router sees fresh telemetry at every request. Arrivals are generated up
front from the seed alone, so every policy gets exactly the same requests for
the same (scenario, seed). Every routed request gets exactly one feedback —
including requests lost when a node goes down, which come back as failures.

Safety audit: each decision is checked twice. The chosen node must be in the
filter's allowed list (otherwise SafetyViolation is raised), and its snapshot
is re-checked against the filter's limits (failures are counted, which would
expose a filter that lets a bad node through).

All numbers are in toy_cluster.yaml. Results from this simulator are
preliminary — re-run everything on Parikshit's simulator before reporting.
"""

from __future__ import annotations

import heapq
import itertools
import json
import math
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

_HERE = os.path.dirname(os.path.abspath(__file__))
_SUR_DIR = os.path.dirname(_HERE)
_JYOTIR_DIR = os.path.join(os.path.dirname(_SUR_DIR), "Jyotir")
for _path in (_SUR_DIR, _JYOTIR_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from feasibility_filter.filter import feasibility_filter  # noqa: E402  (Jyotir's real filter)
from feasibility_filter.filter import load_config as load_filter_config  # noqa: E402
from reward import NODE_FIELDS, RewardConfig, as_reward_config, compute_reward  # noqa: E402
from stubs.stub_policy import Outcome  # noqa: E402

DEFAULT_CONFIG_PATH = os.path.join(_HERE, "toy_cluster.yaml")
SCENARIOS = (
    "s1_stable",
    "s2_traffic_burst",
    "s3_price_shift",
    "s4_thermal_throttle",
    "s5_network_degradation",
    "s6_outage_recovery",
)
DECISION_LOG_COLUMNS = (
    "run_id",
    "seed",
    "scenario",
    "policy",
    "request_id",
    "t_arrival",
    "decision",
    "node_id",
    "feasible_nodes",
    "filtered_out",
    "reject_reason",
    "ttft_ms",
    "e2e_ms",
    "slo_met",
    "energy_kwh",
    "cost_usd",
    "reward",
)
NO_FEASIBLE_NODE = "no_feasible_node"  # brief §6.1; spelled as in Krupesh's contract (api_contract/types.py)


class SafetyViolation(RuntimeError):
    """A policy returned a node that the feasibility filter did not allow."""


# ── Config ───────────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TokenDist(_Strict):
    median: float = Field(gt=0)
    sigma: float = Field(ge=0)
    min: int = Field(ge=1)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> TokenDist:
        if self.max < self.min:
            raise ValueError("max must be >= min")
        return self


class ClassSpec(_Strict):
    share: float = Field(gt=0)
    ttft_slo_ms: float = Field(gt=0)


class WorkloadSpec(_Strict):
    base_rate_rps: float = Field(gt=0)
    model: str
    regions: dict[str, float] = Field(min_length=1)
    classes: dict[str, ClassSpec] = Field(min_length=1)
    input_tokens: TokenDist
    output_tokens: TokenDist

    @model_validator(mode="after")
    def _positive_shares(self) -> WorkloadSpec:
        if any(v <= 0 for v in self.regions.values()):
            raise ValueError("region shares must be > 0")
        return self


class ThrottleSpec(_Strict):
    start_c: float
    full_c: float
    max_slowdown: float = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> ThrottleSpec:
        if self.full_c <= self.start_c:
            raise ValueError("full_c must be greater than start_c")
        return self


class NodeSpec(_Strict):
    node_id: str
    models_loaded: list[str]
    capacity: int = Field(gt=0)
    kv_capacity_tokens: int = Field(gt=0)
    rtt_ms: dict[str, float]
    prefill_a_ms: float = Field(ge=0)
    prefill_b_ms_per_token: float = Field(ge=0)
    t_tok_ms: float = Field(gt=0)
    decode_c: float = Field(ge=0)
    power_max_kw: float
    power_idle_kw: float = Field(ge=0)
    power_per_running_kw: float = Field(ge=0)
    ambient_c: float
    heat_per_load_c: float = Field(ge=0)
    thermal_tau_s: float = Field(gt=0)
    energy_price_usd_kwh: float
    gpu_price_usd_hr: float = Field(ge=0)


class BurstSpec(_Strict):
    rate_multiplier: float = Field(gt=0)
    duration_s: float = Field(gt=0)


class PriceShiftSpec(_Strict):
    price_multipliers: dict[str, float] = Field(min_length=1)


class ThermalSpec(_Strict):
    node: str
    ambient_increase_c: float


class NetworkSpec(_Strict):
    node: str
    rtt_increase_ms: float = Field(ge=0)


class OutageSpec(_Strict):
    node: str
    return_s: float
    warmup_s: float = Field(ge=0)
    warmup_slowdown: float = Field(ge=1)


class ScenarioSpecs(_Strict):
    s1_stable: dict[str, Any]
    s2_traffic_burst: BurstSpec
    s3_price_shift: PriceShiftSpec
    s4_thermal_throttle: ThermalSpec
    s5_network_degradation: NetworkSpec
    s6_outage_recovery: OutageSpec


class ClusterConfig(_Strict):
    duration_s: float = Field(gt=0)
    t0_s: float = Field(gt=0)
    workload: WorkloadSpec
    throttle: ThrottleSpec
    nodes: list[NodeSpec] = Field(min_length=1)
    scenarios: ScenarioSpecs

    @model_validator(mode="after")
    def _consistent(self) -> ClusterConfig:
        ids = [n.node_id for n in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("node_id values must be unique")
        if not self.t0_s < self.duration_s:
            raise ValueError("t0_s must be inside the run")
        if self.scenarios.s1_stable:
            raise ValueError("s1_stable takes no settings")
        biggest = self.workload.input_tokens.max + self.workload.output_tokens.max
        for n in self.nodes:
            if n.kv_capacity_tokens < biggest:
                raise ValueError(f"{n.node_id}: kv_capacity_tokens < largest possible request ({biggest})")
            missing = set(self.workload.regions) - set(n.rtt_ms)
            if missing:
                raise ValueError(f"{n.node_id}: no rtt_ms for regions {sorted(missing)}")
        s = self.scenarios
        named = [
            s.s4_thermal_throttle.node,
            s.s5_network_degradation.node,
            s.s6_outage_recovery.node,
            *s.s3_price_shift.price_multipliers,
        ]
        unknown = sorted(set(named) - set(ids))
        if unknown:
            raise ValueError(f"scenarios name unknown nodes {unknown}")
        if not self.t0_s < s.s6_outage_recovery.return_s < self.duration_s:
            raise ValueError("s6 return_s must be between t0_s and duration_s")
        return self


def load_cluster_config(path: str | os.PathLike = DEFAULT_CONFIG_PATH) -> ClusterConfig:
    with open(path) as f:
        return ClusterConfig.model_validate(yaml.safe_load(f))


# ── Workload ─────────────────────────────────────────────────────────────────


def arrival_rate(cfg: ClusterConfig, scenario: str, t: float) -> float:
    rate = cfg.workload.base_rate_rps
    if scenario == "s2_traffic_burst":
        burst = cfg.scenarios.s2_traffic_burst
        if cfg.t0_s <= t < cfg.t0_s + burst.duration_s:
            rate *= burst.rate_multiplier
    return rate


def generate_workload(cfg: ClusterConfig, scenario: str, seed: int) -> list[dict]:
    """All requests of one run, from the seed alone (identical for every policy)."""
    _check_scenario(scenario)
    rng = np.random.default_rng(seed)
    w = cfg.workload
    # Sorted names, so the requests depend only on the config's values, never on the order
    # in which the YAML lists the regions or classes (yaml.safe_dump, for one, re-sorts keys).
    regions = sorted(w.regions)
    region_p = np.array([w.regions[r] for r in regions], dtype=float)
    region_p /= region_p.sum()
    classes = sorted(w.classes)
    class_p = np.array([w.classes[c].share for c in classes], dtype=float)
    class_p /= class_p.sum()
    boundaries = sorted({cfg.t0_s, cfg.t0_s + cfg.scenarios.s2_traffic_burst.duration_s})

    requests, t, i = [], 0.0, 0
    while True:
        # Piecewise-constant rate: if the next arrival would cross a rate change,
        # restart from the change (exact for a Poisson process, which is memoryless).
        t_next = t + rng.exponential(1.0 / arrival_rate(cfg, scenario, t))
        crossing = next((b for b in boundaries if t < b <= t_next), None)
        if crossing is not None:
            t = crossing
            continue
        t = t_next
        if t >= cfg.duration_s:
            return requests
        cls = classes[rng.choice(len(classes), p=class_p)]
        requests.append(
            {
                "request_id": f"r-{i:06d}",
                "t_arrival": t,
                "user_region": regions[rng.choice(len(regions), p=region_p)],
                "model": w.model,
                "input_tokens": _tokens(rng, w.input_tokens),
                "expected_output_tokens": _tokens(rng, w.output_tokens),
                "slo_class": cls,
                "ttft_slo_ms": w.classes[cls].ttft_slo_ms,
            }
        )
        i += 1


def _tokens(rng: np.random.Generator, d: TokenDist) -> int:
    return int(min(max(round(rng.lognormal(math.log(d.median), d.sigma)), d.min), d.max))


def _check_scenario(scenario: str) -> None:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")


# ── Nodes ────────────────────────────────────────────────────────────────────


@dataclass(eq=False)
class _Job:
    request: dict
    node_id: str
    reward_node: dict  # chosen node's numbers at decision time (for the reward)
    feasible: list[str]
    filtered_out: dict
    tokens: int
    t_start: float | None = None
    ttft_ms: float = math.inf
    e2e_ms: float = math.inf
    energy_kwh: float = 0.0
    cost_usd: float = 0.0
    failed: bool = False


class _Node:
    def __init__(self, spec: NodeSpec, throttle: ThrottleSpec):
        self.spec = spec
        self.throttle = throttle
        self.node_id = spec.node_id
        self.status = "up"
        self.rtt_extra_ms = 0.0
        self.energy_price = spec.energy_price_usd_kwh
        self.ambient_c = spec.ambient_c
        self.temp_c = spec.ambient_c
        self._t_temp = 0.0
        # A dict, not a set: it iterates in start order, while a set of objects iterates in
        # memory-address order, which changes between processes and broke reproducibility.
        self.running: dict[_Job, None] = {}
        self.queue: deque[_Job] = deque()
        self.kv_used = 0
        self.warm_start = self.warm_end = None
        self.warm_slowdown = 1.0

    def advance(self, t: float) -> None:
        """Move the temperature toward its target for the time since the last event."""
        dt = t - self._t_temp
        if dt > 0:
            target = self.ambient_c + self.spec.heat_per_load_c * len(self.running) / self.spec.capacity
            self.temp_c = target + (self.temp_c - target) * math.exp(-dt / self.spec.thermal_tau_s)
            self._t_temp = t

    def slowdown(self, t: float) -> float:
        th = self.throttle
        f = 1.0 + (th.max_slowdown - 1.0) * min(max((self.temp_c - th.start_c) / (th.full_c - th.start_c), 0.0), 1.0)
        if self.warm_end is not None and self.warm_start <= t < self.warm_end:
            left = (self.warm_end - t) / (self.warm_end - self.warm_start)
            f *= 1.0 + (self.warm_slowdown - 1.0) * left
        return f

    def rtt(self, region: str) -> float:
        return self.spec.rtt_ms[region] + self.rtt_extra_ms

    def can_start(self, job: _Job) -> bool:
        return (
            self.status != "down"
            and len(self.running) < self.spec.capacity
            and self.kv_used + job.tokens <= self.spec.kv_capacity_tokens
        )

    def telemetry(self, t: float) -> dict:
        """One telemetry record, schema v1 (brief §10.1)."""
        s = self.spec
        return {
            "schema_version": "1.0",
            "t": t,
            "node_id": self.node_id,
            "status": self.status,
            "rtt_ms": {region: ms + self.rtt_extra_ms for region, ms in s.rtt_ms.items()},
            "queue_len": len(self.queue),
            "running": len(self.running),
            "capacity": s.capacity,
            "kv_used_frac": self.kv_used / s.kv_capacity_tokens,
            "models_loaded": list(s.models_loaded),
            "power_headroom_kw": (
                0.0
                if self.status == "down"
                else s.power_max_kw - s.power_idle_kw - s.power_per_running_kw * len(self.running)
            ),
            "temperature_c": self.temp_c,
            "energy_price_usd_kwh": self.energy_price,
            "gpu_price_usd_hr": s.gpu_price_usd_hr,
        }


# ── Simulation ───────────────────────────────────────────────────────────────


@dataclass
class RunResult:
    """One decision-log record per request (brief §10.3), sorted by t_arrival."""

    records: list[tuple]  # values in DECISION_LOG_COLUMNS order (compact; dicts are built on demand)
    stats: dict = field(default_factory=dict)

    @property
    def rows(self) -> list[dict]:
        return [dict(zip(DECISION_LOG_COLUMNS, r, strict=True)) for r in self.records]

    def column(self, name: str) -> list:
        i = DECISION_LOG_COLUMNS.index(name)
        return [r[i] for r in self.records]

    def to_csv(self, path: str | os.PathLike) -> None:
        import csv
        import gzip

        opener = gzip.open if os.fspath(path).endswith(".gz") else open
        with opener(path, "wt", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(DECISION_LOG_COLUMNS)
            writer.writerows(self.records)


def simulate(
    policy: Any,
    scenario: str,
    seed: int,
    *,
    cluster: ClusterConfig | None = None,
    filter_config: dict | None = None,
    reward_config: RewardConfig | dict | None = None,
    policy_name: str | None = None,
    run_id: str | None = None,
    details: bool = True,
) -> RunResult:
    """
    Run one scenario with one policy and return its decision log.
    details=False skips the feasible_nodes / filtered_out columns (faster for big sweeps).
    """
    _check_scenario(scenario)
    cfg = cluster or load_cluster_config()
    fcfg = filter_config or load_filter_config()
    if reward_config is None:
        reward_config = getattr(getattr(policy, "config", None), "reward", None)
    if reward_config is None:  # baselines have no reward config: use the bandit's
        with open(os.path.join(_SUR_DIR, "configs", "policies", "sw_linucb.yaml")) as f:
            reward_config = yaml.safe_load(f)["reward"]
    rcfg = as_reward_config(reward_config)
    name = policy_name or getattr(policy, "name", type(policy).__name__)
    run_id = run_id or f"{name}-{scenario}-{seed}"

    nodes = [_Node(spec, cfg.throttle) for spec in cfg.nodes]
    by_id = {n.node_id: n for n in nodes}
    requests = generate_workload(cfg, scenario, seed)

    events: list = []
    seq = itertools.count()
    records: list[tuple] = []
    stats = {
        "requests": len(requests),
        "routed": 0,
        "rejected": 0,
        "failed": 0,
        "hard_rule_violations": 0,
        "violation_examples": [],
    }

    def push(t, kind, payload=None):
        heapq.heappush(events, (t, next(seq), kind, payload))

    # Scenario events at t0 (S2 is in the workload itself).
    sc = cfg.scenarios
    if scenario == "s3_price_shift":
        push(cfg.t0_s, "prices", sc.s3_price_shift.price_multipliers)
    elif scenario == "s4_thermal_throttle":
        push(cfg.t0_s, "ambient", (sc.s4_thermal_throttle.node, sc.s4_thermal_throttle.ambient_increase_c))
    elif scenario == "s5_network_degradation":
        push(cfg.t0_s, "rtt", (sc.s5_network_degradation.node, sc.s5_network_degradation.rtt_increase_ms))
    elif scenario == "s6_outage_recovery":
        o = sc.s6_outage_recovery
        push(cfg.t0_s, "down", o.node)
        push(o.return_s, "return", o)
        push(o.return_s + o.warmup_s, "warm_done", o.node)

    def log(job: _Job, outcome: dict, reward: float | None) -> None:
        req = job.request
        records.append(
            (
                run_id,
                seed,
                scenario,
                name,
                req["request_id"],
                req["t_arrival"],
                "route",
                job.node_id,
                json.dumps(job.feasible) if details else None,
                json.dumps(job.filtered_out) if details else None,
                None,
                outcome["ttft_ms"],
                outcome["e2e_ms"],
                outcome["slo_met"],
                outcome["energy_kwh"],
                outcome["cost_usd"],
                reward,
            )
        )

    def feedback(job: _Job) -> None:
        outcome = {
            "ttft_ms": job.ttft_ms,
            "e2e_ms": job.e2e_ms,
            "slo_met": (not job.failed) and job.ttft_ms <= job.request["ttft_slo_ms"],
            "energy_kwh": job.energy_kwh,
            "cost_usd": job.cost_usd,
        }
        reward = compute_reward(job.reward_node, outcome, rcfg)
        log(job, outcome, reward)
        policy.update(job.request, job.node_id, Outcome(**outcome, reward=reward))

    def start(node: _Node, job: _Job, t: float) -> None:
        s, req = node.spec, job.request
        f = node.slowdown(t)
        load = (len(node.running) + 1) / s.capacity
        prefill_ms = (s.prefill_a_ms + s.prefill_b_ms_per_token * req["input_tokens"]) * f
        decode_ms = req["expected_output_tokens"] * s.t_tok_ms * (1.0 + s.decode_c * load) * f
        service_s = (prefill_ms + decode_ms) / 1000.0
        job.t_start = t
        job.ttft_ms = node.rtt(req["user_region"]) + (t - req["t_arrival"]) * 1000.0 + prefill_ms
        job.e2e_ms = job.ttft_ms + decode_ms
        job.energy_kwh = s.power_per_running_kw * service_s / 3600.0
        job.cost_usd = job.energy_kwh * node.energy_price + s.gpu_price_usd_hr * service_s / 3600.0 / s.capacity
        node.running[job] = None
        node.kv_used += job.tokens
        push(t + service_s, "finish", (node, job))
        push(req["t_arrival"] + job.e2e_ms / 1000.0, "feedback", job)

    def start_queued(node: _Node, t: float) -> None:
        while node.queue and node.can_start(node.queue[0]):
            start(node, node.queue.popleft(), t)

    def route(req: dict, t: float) -> None:
        for n in nodes:
            n.advance(t)
        snapshots = [n.telemetry(t) for n in nodes]
        allowed, rejected = feasibility_filter(req, snapshots, fcfg)
        filtered_out = {r["node_id"]: r["reason"] for r in rejected}
        feasible = [a["node_id"] for a in allowed]
        if not allowed:
            stats["rejected"] += 1
            records.append(
                (
                    run_id,
                    seed,
                    scenario,
                    name,
                    req["request_id"],
                    req["t_arrival"],
                    "reject",
                    None,
                    json.dumps([]) if details else None,
                    json.dumps(filtered_out) if details else None,
                    NO_FEASIBLE_NODE,
                    None,
                    None,
                    False,
                    0.0,
                    0.0,
                    None,
                )
            )
            return

        chosen = policy.choose(req, allowed)
        if chosen not in feasible:
            raise SafetyViolation(f"{name} chose {chosen!r}, not in the filter's allowed list {feasible}")
        snapshot = allowed[feasible.index(chosen)]
        problems = _hard_rule_problems(req, snapshot, fcfg)
        if problems:
            stats["hard_rule_violations"] += 1
            if len(stats["violation_examples"]) < 5:
                stats["violation_examples"].append({"t": t, "node_id": chosen, "problems": problems})

        stats["routed"] += 1
        job = _Job(
            req,
            chosen,
            {"node_id": chosen, **{k: snapshot[k] for k in NODE_FIELDS}},
            feasible,
            filtered_out,
            req["input_tokens"] + req["expected_output_tokens"],
        )
        node = by_id[chosen]
        if not node.queue and node.can_start(job):
            start(node, job, t)
        else:
            node.queue.append(job)

    arrivals = iter(requests)
    next_req = next(arrivals, None)
    while next_req is not None or events:
        if next_req is not None and (not events or next_req["t_arrival"] < events[0][0]):
            route(next_req, next_req["t_arrival"])
            next_req = next(arrivals, None)
            continue

        t, _, kind, payload = heapq.heappop(events)
        if kind == "finish":
            node, job = payload
            if job.failed:
                continue
            node.advance(t)
            node.running.pop(job, None)
            node.kv_used -= job.tokens
            start_queued(node, t)
        elif kind == "feedback":
            if not payload.failed:
                feedback(payload)
        elif kind == "prices":
            for node_id, factor in payload.items():
                by_id[node_id].energy_price *= factor
        elif kind == "ambient":
            node_id, delta = payload
            by_id[node_id].advance(t)
            by_id[node_id].ambient_c += delta
        elif kind == "rtt":
            node_id, delta = payload
            by_id[node_id].rtt_extra_ms += delta
        elif kind == "down":
            node = by_id[payload]
            node.advance(t)
            lost = list(node.running) + list(node.queue)  # deterministic order: running by start, then queue
            node.status, node.running, node.queue, node.kv_used = "down", {}, deque(), 0
            for job in lost:  # requests on a node that dies come back as failures
                if job.t_start is not None:
                    elapsed = t - job.t_start
                    job.energy_kwh = node.spec.power_per_running_kw * elapsed / 3600.0
                    job.cost_usd = (
                        job.energy_kwh * node.energy_price
                        + node.spec.gpu_price_usd_hr * elapsed / 3600.0 / node.spec.capacity
                    )
                job.failed, job.ttft_ms, job.e2e_ms = True, math.inf, math.inf
                stats["failed"] += 1
                outcome = {
                    "ttft_ms": math.inf,
                    "e2e_ms": math.inf,
                    "slo_met": False,
                    "energy_kwh": job.energy_kwh,
                    "cost_usd": job.cost_usd,
                }
                reward = compute_reward(job.reward_node, outcome, rcfg)
                log(job, outcome, reward)
                policy.update(job.request, job.node_id, Outcome(**outcome, reward=reward))
        elif kind == "return":
            node = by_id[payload.node]
            node.advance(t)
            node.status = "warming"
            node.temp_c = node.ambient_c  # cooled down while off
            node.warm_start, node.warm_end, node.warm_slowdown = t, t + payload.warmup_s, payload.warmup_slowdown
        elif kind == "warm_done":
            by_id[payload].status = "up"

    records.sort(key=lambda r: r[5])  # by t_arrival
    if len(records) != len(requests) or len({r[4] for r in records}) != len(requests):
        # every request is either rejected or gets exactly one feedback
        raise RuntimeError(f"decision log has {len(records)} rows for {len(requests)} requests")
    stats["policy_stats"] = dict(getattr(policy, "stats", {}) or {})
    return RunResult(records, stats)


def _hard_rule_problems(request: dict, node: dict, fcfg: dict) -> list[str]:
    """Independent re-check of the filter's hard rules (brief §6.1) on the chosen node."""
    problems = []
    if node["status"] not in ("up", "warming") or (
        node["status"] == "warming" and not fcfg.get("allow_warming_nodes", True)
    ):
        problems.append(f"status={node['status']}")
    if request["model"] not in node["models_loaded"]:
        problems.append("model_missing")
    if node["kv_used_frac"] >= fcfg["kv_cache_max_frac"]:
        problems.append("memory_full")
    if node["power_headroom_kw"] < fcfg["power_headroom_min_kw"]:
        problems.append("power_limit")
    if node["temperature_c"] >= fcfg["temperature_limit_c"]:
        problems.append("temperature_high")
    return problems


def change_times(cfg: ClusterConfig, scenario: str) -> dict[str, float]:
    """When things change in a scenario: t0 for all; S6 also has the node's return."""
    _check_scenario(scenario)
    times = {"t0": cfg.t0_s}
    if scenario == "s6_outage_recovery":
        times["return"] = cfg.scenarios.s6_outage_recovery.return_s
    return times
