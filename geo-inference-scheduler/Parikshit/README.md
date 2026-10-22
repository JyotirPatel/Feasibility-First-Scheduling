# Parikshit — Node Simulator + Telemetry

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Big Data Systems, Algorithms and Networks · Fall 2026 · Group 20

---

## Role

Parikshit owns everything about simulated nodes: how they behave, what numbers they report, and how change events unfold over time.

---

## Assigned Work

### 1. Node Simulator (`simulator/`)
Build a discrete-event simulator (SimPy) of 5 to 10 nodes. Each node tracks:
- Network delay to user regions (city-to-city ping data)
- Queue of waiting requests
- Number of running requests
- GPU memory (KV cache) used
- Models currently loaded
- Power headroom (kW)
- Electricity price (USD/kWh) and GPU rent price (USD/hr)
- Temperature (°C)
- Status: up / down / warming

**Latency model per node:**
```
T_total  = T_network + T_queue + T_prefill + T_decode
TTFT     = T_network + T_queue + T_prefill

T_prefill = a_p + b_p × (input tokens)
T_decode  = output_tokens × t_tok × (1 + c × load)
```
Constants fitted per node type. Reference: Inference Engineering book, sections 2.2, 2.4, 7.2.1.

### 2. Real Data Sources (`data_sources/`)
Use real public data where it exists:
- **Request arrivals and token lengths:** Azure LLM Inference traces
- **Electricity prices:** NYISO / CAISO hourly public data
- **Network delay:** inter-city ping data (e.g. WonderNetwork)
- **Prefill / decode speed:** published GPU benchmarks

### 3. Six Change-Event Traces (`event_traces/`)
Script each scenario as a replayable trace file. Each run is 600 s simulated time; the change starts at t₀ = 200 s.

| # | Scenario | What changes at t₀ |
|---|---|---|
| S1 | Stable | Nothing — checks normal behavior |
| S2 | Traffic burst | Arrival rate jumps 3× for 120 s |
| S3 | Price / renewable shift | Cheapest node's price jumps; another region becomes cheap |
| S4 | Thermal throttle | One busy node overheats and crosses the temperature limit |
| S5 | Network degradation | Delay to one popular node rises sharply (+80 ms) |
| S6 | Outage + recovery | Node goes down at t₀; returns at 400 s with a warm-up period before it is fully fast |

Fix a random seed per run so every result is exactly reproducible.

### 4. Telemetry Schema (`telemetry/`)
Write a versioned JSON schema (v1) for what each node reports once per simulation tick. Fields include: `schema_version`, `t`, `node_id`, `status`, `rtt_ms` (per user region), `queue_len`, `running`, `capacity`, `kv_used_frac`, `models_loaded`, `power_headroom_kw`, `temperature_c`, `energy_price_usd_kwh`, `gpu_price_usd_hr`.

Also write unit tests confirming the simulator produces valid telemetry at each tick.

---

## Deliverables

| Deliverable | Where it lives |
|---|---|
| Simulator code + unit tests | `simulator/` |
| Telemetry schema v1 | `telemetry/` |
| 6 event trace files (S1–S6) | `event_traces/` |
| Note explaining how each number is produced | `simulator/` |
| Real-data loaders (download + preprocess scripts) | `data_sources/` |

---

## What You Need From Others Before You Can Build

### From Krupesh — Routing API Contract
**Specific deliverable:** `api_contract/api_contract.md` — the document that defines what a request looks like (model, input_tokens, expected_output_tokens, slo_class, slo_ms) and what the router response looks like (node_id, feasible_nodes, filtered_out, reject_reason).
**Why you need it first:** The telemetry schema must be designed so each node reports exactly the fields the router will consume. If Krupesh later adds or renames a field on the request side, it may change what the node needs to track (e.g., which model is requested affects which `models_loaded` check matters). Freeze the API contract first so you do not have to redesign the telemetry schema mid-build.
**Due:** End of Week 1.

---

## What You Provide to Others

| Deliverable you hand over | Who receives it | When |
|---|---|---|
| Telemetry schema v1 (field names, types, ranges) | Krupesh (router), Jyotir (filter), Sur (context vector) — all three read node state | End of Week 1 |
| Running simulator producing valid telemetry | Krupesh (router integration), Jyotir (filter testing), Sur (policy testing) | End of Week 1 (5 nodes) |
| 6 event trace files (S1–S6) | Riya — experiment runner replays these traces for every policy × seed run | End of Week 3 |
| Real-data loaders (Azure traces, NYISO prices) | Riya — needed for realistic workload in experiments | End of Week 2 |

---

## Report / Presentation Section

Simulator and Workload section — explains why the simulated numbers are realistic and how traces were generated.
