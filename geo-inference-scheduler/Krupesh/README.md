# Krupesh — Architecture + Integration

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Big Data Systems, Algorithms and Networks · Fall 2026 · Group 20

---

## Role

Krupesh owns the overall system design, the HTTP router service, the interfaces that connect every module together, and the weekly integrated build.

---

## Assigned Work

### 1. Routing API Contract (`api_contract/`)
Define the full input/output contract for the router:
- **Request fields:** model name, input token length, expected output length, SLO class, SLO deadline (ms)
- **Response fields:** chosen node ID (or rejection) + rejection reason
- This contract is the shared interface everyone else codes against — freeze it by end of Week 1.

### 2. Router Service (`router_service/`)
Build the HTTP service (FastAPI) that handles every incoming request:
- Receive the request
- Read latest telemetry from the node simulator
- Call the feasibility filter (Jyotir's module)
- Call the chosen policy (Jyotir's baselines or Sur's LinUCB)
- Log the decision
- Return the response

The router must also handle a `/feedback` endpoint so the simulator can report the outcome (latency, SLO met, energy used) back to the policy.

### 3. Decision Log Format (`decision_log/`)
Define one CSV/Parquet row per request containing:
`run_id, seed, scenario, policy, request_id, t_arrival, decision, node_id, feasible_nodes, filtered_out, reject_reason, ttft_ms, e2e_ms, slo_met, energy_kwh, cost_usd, reward`

This is the only source of truth for Riya's experiments and figures.

### 4. Pluggable Policy Interface (`integration/`)
Define a shared `Policy` base class so any policy (baseline or LinUCB) plugs in with the same two methods:
- `choose(request, candidates) → node_id`
- `update(request, node_id, outcome) → None`

Experiments switch policies with one config line — no code changes.

### 5. Weekly Integration Check (`integration/`)
Every week: pull all modules, run one end-to-end smoke scenario, report what breaks to the group.

### 6. Novelty Wording (report contribution)
Per the professor's first comment: rewrite slide 4 and the report's contribution list to frame the novelty around the full scheduling loop (filter + context + forgetting + recovery benchmark), not around sliding-window LinUCB itself.

---

## Deliverables

| Deliverable | Where it lives |
|---|---|
| API contract document | `api_contract/` |
| Router service code | `router_service/` |
| Decision log format spec | `decision_log/` |
| Policy interface definition | `integration/` |
| Weekly integration build report | `integration/` |

---

## What You Need From Others Before You Can Build

### From Parikshit — Telemetry Schema v1
**Specific deliverable:** `telemetry/telemetry_schema_v1.json` (or equivalent versioned schema file)
**Why you need it first:** The router reads live telemetry from the node simulator on every request. Without knowing the exact field names, types, and ranges (queue_len, kv_used_frac, temperature_c, etc.), you cannot write the router code that passes the right data to the filter and the policy. The schema must be frozen before you wire up the router's internal pipeline.
**Due:** End of Week 1.

### From Jyotir — Feasibility Filter Module
**Specific deliverable:** The `filter.py` module (or its interface stub) that accepts a request + list of NodeState objects and returns a filtered list of allowed nodes with reasons.
**Why you need it first:** The router calls the filter as Step 1 of every request. Without the filter's callable interface being defined, you cannot finish the router's request-handling logic. At minimum you need the function signature and what it returns so the router can call it — even if the rules inside are not complete yet.
**Due:** End of Week 2 (stub by end of Week 1 so integration can proceed).

### From Sur — Policy Module Interface
**Specific deliverable:** The `Policy` base class with `choose(request, candidates) → node_id` and `update(request, node_id, outcome) → None` defined.
**Why you need it first:** The router calls the policy as Step 2 of every request. You are defining the interface yourself (it is your deliverable), but Sur must agree to it and implement against it. Agree on the exact method signatures together by end of Week 1 so Sur can build LinUCB without needing to refactor later.
**Due:** End of Week 1 (joint agreement).

---

## What You Provide to Others

| Deliverable you hand over | Who receives it | When |
|---|---|---|
| Routing API contract (request + response format) | Everyone — this is the shared interface | End of Week 1 |
| Decision log format (CSV/Parquet column list) | Riya — all figures come from this log | End of Week 1 |
| Policy interface (`Policy` base class) | Sur and Jyotir — both implement it | End of Week 1 |
| Running end-to-end system + decision logs | Riya — for all experiment runs | Week 2 onward |

---

## Report / Presentation Section

Introduction, Problem Statement, System Design section, and the architecture design slide.
