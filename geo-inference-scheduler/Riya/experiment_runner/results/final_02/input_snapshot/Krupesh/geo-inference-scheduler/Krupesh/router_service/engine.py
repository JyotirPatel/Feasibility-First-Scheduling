"""Routing engine — owner: Krupesh. The one implementation of the decision loop:

    telemetry view -> feasibility filter -> policy.choose -> (later) feedback
    -> reward -> policy.update -> decision-log row

Used directly (in-process, fast) and by the FastAPI service (router_service/app.py).

Plug-in points (no teammate code is imported here):
    filter_fn  (request, nodes) -> FilterResult        Jyotir   (integration/jyotir_adapter.py)
    policy     Policy subclass                          Jyotir / Sur
    reward_fn  (outcome, node_at_dispatch) -> float     Sur      (mock in integration/mocks)
    audit_fn   same as filter_fn; re-checks the chosen node independently (safety audit)

Safety guarantees enforced HERE, whatever the policy does:
  * the policy only sees nodes that passed the filter;
  * a choice outside that list raises (the engine never routes to an unchecked node);
  * no feasible node -> deliberate reject with reason "no_feasible_node".

Local load accounting: telemetry arrives every ~1 s. Between reports the engine adds its
own not-yet-reported placements to queue_len / kv_used_frac, so load-reading policies do
not send a whole second of traffic to the same node (herd effect).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any

from api_contract.types import (
    NO_FEASIBLE_NODE,
    Decision,
    FilterFn,
    NodeState,
    Outcome,
    Request,
    RewardFn,
)
from decision_log.writer import DecisionLogWriter
from router_service.policy_base import Policy


@dataclass
class RunMeta:
    run_id: str = "adhoc"
    seed: int = 0
    scenario: str = "none"
    policy: str = "unknown"


@dataclass
class _Pending:
    request: Request
    node_id: str
    node_view: NodeState
    row: dict[str, Any] = field(default_factory=dict)


class UnknownRequest(KeyError):
    pass


class RoutingEngine:
    def __init__(
        self,
        policy: Policy,
        filter_fn: FilterFn,
        reward_fn: RewardFn,
        meta: RunMeta | None = None,
        writer: DecisionLogWriter | None = None,
        local_load_accounting: bool = True,
        audit_fn: FilterFn | None = None,
    ):
        self.policy = policy
        self.filter_fn = filter_fn
        self.reward_fn = reward_fn
        self.audit_fn = audit_fn or filter_fn
        self.meta = meta or RunMeta(policy=getattr(policy, "name", "unknown"))
        self.writer = writer or DecisionLogWriter()
        self.local_load_accounting = local_load_accounting
        self._telemetry: dict[str, NodeState] = {}
        self._telemetry_t: float | None = None
        self._local: dict[str, list[tuple[float, int]]] = {}
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.RLock()
        self.counts = {"routed": 0, "rejected": 0, "feedback": 0, "failed": 0}

    # ── telemetry ─────────────────────────────────────────────────────────────
    def ingest_telemetry(self, records: list[NodeState]) -> None:
        with self._lock:
            for r in records:
                self._telemetry[r.node_id] = r
            if records:
                t_snap = max(r.t for r in records)
                self._telemetry_t = t_snap
                for nid in list(self._local):
                    self._local[nid] = [e for e in self._local[nid] if e[0] >= t_snap]

    def telemetry_view(self) -> list[NodeState]:
        view = []
        for nid, s in self._telemetry.items():
            extra = self._local.get(nid) if self.local_load_accounting else None
            if extra:
                kv = s.kv_used_frac
                if s.kv_capacity_tokens:
                    kv = min(1.0, kv + sum(k for _, k in extra) / s.kv_capacity_tokens)
                s = replace(s, queue_len=s.queue_len + len(extra), kv_used_frac=kv)
            view.append(s)
        return view

    # ── /route ────────────────────────────────────────────────────────────────
    def route(self, request: Request) -> Decision:
        wall0 = time.perf_counter()
        with self._lock:
            if request.request_id in self._pending:
                raise ValueError(f"duplicate request_id {request.request_id}")
            view = self.telemetry_view()
            res = self.filter_fn(request, view)
            age = None if self._telemetry_t is None else request.t_arrival - self._telemetry_t
            row: dict[str, Any] = {
                "run_id": self.meta.run_id,
                "seed": self.meta.seed,
                "scenario": self.meta.scenario,
                "policy": self.meta.policy,
                "request_id": request.request_id,
                "t_arrival": request.t_arrival,
                "feasible_nodes": res.allowed_ids,
                "filtered_out": res.rejected,
                "user_region": request.user_region,
                "model": request.model,
                "slo_class": request.slo_class,
                "ttft_slo_ms": request.ttft_slo_ms,
                "input_tokens": request.input_tokens,
                "expected_output_tokens": request.expected_output_tokens,
                "telemetry_age_s": age,
            }
            if not res.allowed:
                row.update(
                    decision="reject",
                    node_id=None,
                    reject_reason=NO_FEASIBLE_NODE,
                    slo_met=False,
                    outcome_status="rejected",
                    router_wall_ms=(time.perf_counter() - wall0) * 1000.0,
                )
                self.writer.write(row)
                self.counts["rejected"] += 1
                return Decision(
                    request.request_id,
                    "reject",
                    None,
                    self.meta.policy,
                    [],
                    res.rejected,
                    NO_FEASIBLE_NODE,
                )

            node_id = self.policy.choose(request, res.allowed)
            chosen = next((n for n in res.allowed if n.node_id == node_id), None)
            if chosen is None:
                raise RuntimeError(
                    f"policy {self.meta.policy} returned {node_id!r}, not a feasible candidate"
                )
            audit = self.audit_fn(request, [chosen])
            violation = audit.rejected.get(node_id)

            if self.local_load_accounting:
                self._local.setdefault(node_id, []).append((request.t_arrival, request.kv_tokens))
            row.update(
                decision="route",
                node_id=node_id,
                reject_reason=None,
                chosen_node_status=chosen.status,
                constraint_violation=violation,
                router_wall_ms=(time.perf_counter() - wall0) * 1000.0,
            )
            self._pending[request.request_id] = _Pending(request, node_id, chosen, row)
            self.counts["routed"] += 1
            return Decision(
                request.request_id,
                "route",
                node_id,
                self.meta.policy,
                res.allowed_ids,
                res.rejected,
                None,
            )

    def annotate(self, request_id: str, **fields: Any) -> None:
        with self._lock:
            if request_id in self._pending:
                self._pending[request_id].row.update(fields)

    # ── /feedback ─────────────────────────────────────────────────────────────
    def feedback(self, outcome: Outcome) -> float:
        with self._lock:
            p = self._pending.pop(outcome.request_id, None)
            if p is None:
                raise UnknownRequest(outcome.request_id)
            r = float(self.reward_fn(outcome, p.node_view))
            outcome.reward = r
            self.policy.update(p.request, p.node_id, outcome)
            p.row.update(
                ttft_ms=outcome.ttft_ms,
                e2e_ms=outcome.e2e_ms,
                slo_met=bool(outcome.slo_met and not outcome.failed),
                energy_kwh=outcome.energy_kwh,
                cost_usd=outcome.cost_usd,
                reward=r,
                t_complete=outcome.t_complete,
                outcome_status="failed" if outcome.failed else "ok",
            )
            self.writer.write(p.row)
            self.counts["feedback"] += 1
            self.counts["failed"] += int(outcome.failed)
            return r

    def finish(self) -> int:
        """Log requests still in flight as 'unfinished'."""
        with self._lock:
            for p in self._pending.values():
                p.row.update(slo_met=False, outcome_status="unfinished")
                self.writer.write(p.row)
            n = len(self._pending)
            self._pending.clear()
            return n

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ok",
                "policy": self.meta.policy,
                "run_id": self.meta.run_id,
                "telemetry_nodes": len(self._telemetry),
                "telemetry_t": self._telemetry_t,
                "pending": len(self._pending),
                **self.counts,
            }
