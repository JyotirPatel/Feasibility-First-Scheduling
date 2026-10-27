# Krupesh — Architecture + Integration (router service)

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Fall 2026 · Group 20 · **Status:** midterm deliverable (Krupesh's part only)

## Midterm deliverable — what this folder is

A working, tested FastAPI **router service** with the shared contracts that every teammate's module
plugs into. Everything here runs from this folder. Teammates' modules are NOT modified; where a
teammate's module does not exist yet, a clearly labelled **test double** in `integration/mocks/` is
used instead (see "What is real and what is mocked").

### Install (Python ≥ 3.11)

```bash
cd geo-inference-scheduler/Krupesh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`Jyotir/` must sit next to this folder (as in the team repository): the adapter loads Jyotir's
original filter and baselines from `../Jyotir`.

### Run

```bash
pytest -o addopts= tests                                    # all tests (35)
uvicorn router_service.app:app --port 8000                  # API; interactive docs at http://127.0.0.1:8000/docs
python -m integration.run_end_to_end                        # closed loop, in-process (mock simulator)
python -m integration.run_end_to_end --policy mock:learning --outage
python -m integration.run_end_to_end --mode http --url http://127.0.0.1:8000   # same loop over real HTTP
python -m integration.weekly_integration_check              # writes integration/weekly_integration_report.md
```

Quick manual check against a running server:

```bash
curl -s localhost:8000/health
curl -s -X POST localhost:8000/telemetry -H 'content-type: application/json' -d '{"records":[{"schema_version":"1.0","t":312,"node_id":"us-east-1","status":"up","rtt_ms":{"nyc":12},"queue_len":7,"running":22,"capacity":32,"kv_used_frac":0.68,"models_loaded":["llama-3-8b"],"power_headroom_kw":4.5,"temperature_c":71,"energy_price_usd_kwh":0.11,"gpu_price_usd_hr":2.4}]}'
curl -s -X POST localhost:8000/route -H 'content-type: application/json' -d '{"request_id":"r-000123","t_arrival":312.4,"user_region":"nyc","model":"llama-3-8b","input_tokens":850,"expected_output_tokens":200,"slo_class":"interactive","ttft_slo_ms":250}'
curl -s -X POST localhost:8000/feedback -H 'content-type: application/json' -d '{"request_id":"r-000123","ttft_ms":184,"e2e_ms":2210,"slo_met":true,"energy_kwh":0.0004,"cost_usd":0.00013}'
```

### Architecture

```
 simulator (Parikshit)            ROUTER (this folder)                        evaluation (Riya)
 ───────────────────   POST /telemetry   ┌───────────────────────────────┐
 node telemetry v1  ───────────────────► │ router_service/engine.py      │
 request arrivals   ── POST /route ────► │ 1 telemetry view (+ own        │
                                         │   recent placements)           │
                                         │ 2 FilterFn  (Jyotir)           │
                                         │ 3 Policy.choose  (Jyotir/Sur)  │
                                         │ 4 guard: choice must be        │
                                         │   in the feasible set          │
 node runs request ◄── decision ──────── │ 5 pending row                  │
 outcome            ── POST /feedback ─► │ 6 reward_fn (Sur) → update()   │ ──► decision_log/*.parquet
                                         └───────────────────────────────┘     (17 columns, §10.3)
```

| Folder | Responsibility (Work Distribution) |
|---|---|
| `api_contract/` | Routing API contract v1; shared types `Request`, `NodeState`, `Decision`, `Outcome`, `FilterResult`, `FilterFn`, `RewardFn`; HTTP schemas; telemetry validation |
| `router_service/` | FastAPI app (`/route`, `/feedback`, `/health`, plus `/telemetry`, `/admin/*`), decision engine, HTTP client, `Policy` interface, registry |
| `decision_log/` | Decision-log format (brief §10.3) + writer/reader/validator |
| `integration/` | Adapter to Jyotir's original code, end-to-end driver, weekly integration check, `policy_interface.py`, test doubles in `mocks/` |
| `report_sections/` | Novelty wording, research gap (midterm), Introduction/Problem/System design, design slide |
| `tests/` | 35 tests (unit, HTTP, real uvicorn server, end-to-end) |

### Dependencies on teammates

| Teammate | What the router needs | Status |
|---|---|---|
| Jyotir | feasibility filter + baselines | **exists**; used unchanged via `integration/jyotir_adapter.py` |
| Parikshit | telemetry v1 each tick + an outcome per finished request | **missing** → `integration/mocks/mock_simulator.py` |
| Sur | LinUCB / SW-LinUCB as `Policy`, reward function | **missing** → `mocks/mock_policy.py`, `mocks/mock_reward.py` |
| Riya | reads decision logs (nothing needed by the router) | **missing** (not blocking the router) |

### What is real and what is mocked

- **Real:** the router, API, contracts, decision log, and **Jyotir's original filter and baselines**
  (tests call his unmodified code; his own 14 tests are re-run and pass).
- **Mocked:** the simulator, the learning policy and the reward. Tests that use them prove the
  router's plumbing (routing, rejection, delayed feedback, logging, HTTP), **not** integration with
  Parikshit's or Sur's real code, and their numbers are not research results.

Details: `INTEGRATION.md` (teammate interfaces, one-run command for Riya, control-plane walkthrough), `WORK_LOG.md`, `api_contract/api_contract.md`, `integration/integration_guide.md`,
`Group20_Interface_and_Dependency_Handbook.pdf`.

---

# Original role description (team skeleton, unchanged below)


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
