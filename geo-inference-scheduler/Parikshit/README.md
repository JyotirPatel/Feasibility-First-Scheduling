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

---

## Implementation (what is in this folder now)

Every task above is implemented and tested. Each folder has its own README with details.

| Task | Where | Status |
|---|---|---|
| 1. Node simulator (SimPy, 5 or 10 nodes) | `simulator/` | done: the brief's latency model, queue, KV-cache admission, power, temperature, prices, up / down / warming |
| Latency constants "fitted per node type" | `simulator/calibration.py`, `configs/calibration.yaml` | done: fitted to a published H100 benchmark and scaled by NVIDIA's specs (H100, A100) |
| 2. Real data sources | `data_sources/`, `data/processed/` | done: Azure LLM traces, NYISO and CAISO day-ahead prices, WonderProxy pings; download + preprocess scripts; processed files in git, byte-for-byte reproducible |
| 3. Six change-event traces | `event_traces/s1_stable.yaml` … `s6_outage_recovery.yaml` | done: 600 s runs, t0 = 200 s; one seed fixes every request |
| 4. Telemetry schema v1 | `telemetry/telemetry_schema_v1.json`, `telemetry/schema.py` | done: JSON Schema plus a Python validator; every tick of every scenario is tested against both and against Krupesh's router |
| Note on how each number is produced | `simulator/NUMBERS.md` | done |
| Running with Krupesh's router | `simulator/run_scenario.py` | done: in-process and over HTTP; his `validate_log()` accepts the decision logs |
| Report section draft | `report/simulator_section.md` | draft for Riya to merge |
| Tests | `tests/` | 122 tests (`python3 -m pytest geo-inference-scheduler/Parikshit/tests -q`); ruff lint + format clean |

Install: `python3 -m pip install -r geo-inference-scheduler/Parikshit/requirements.txt` (Python 3.11+). For the router runs, also install `geo-inference-scheduler/Krupesh/.../requirements.txt`.

### Run one scenario

From the `Parikshit/` folder:

```bash
python3 simulator/run_scenario.py --scenario s6_outage_recovery --policy jyotir:least_load --seed 0
python3 simulator/run_scenario.py --scenario s2_traffic_burst --policy sur:sw_linucb --seed 3 --out-dir runs/x
python3 simulator/calibration.py              # the fitted latency constants
python3 data_sources/download_data.py         # fetch the raw public data (not in git)
python3 data_sources/preprocess_traces.py     # rebuild data/processed/ from it
```

A 600-s run of the 5-node setup (about 48,000 requests) takes about 7–15 s.

### For each teammate

- **Krupesh (router).**
  - The simulator drives your engine exactly like your `MockCluster`: `ingest_telemetry` every 1-s tick, `route` per arrival and `feedback` per finished or failed request (`failed=True`).
  - It does this in-process and through your `HttpRouter`, which makes identical decisions (`tests/test_router_integration.py`).
  - It fills the `true_state_violation` column through `engine.annotate`.
  - Telemetry includes the optional `kv_capacity_tokens`, which your F2 fix needs.
  - Your upload currently sits in `Krupesh/geo-inference-scheduler/Krupesh/`; the simulator finds it there or in `Krupesh/`.
- **Jyotir (filter).**
  - Every record has the schema's 14 fields and passes your filter.
  - `true_state_violation` shows where the router's 1-s-old view and the truth disagree. It is an independent check of your filter.
  - It still applies the 90 % memory limit (`kv_cache_max_frac`) when a node reports `kv_capacity_tokens`; since your commit 59b63af your filter compares the request against 100 % of the memory in that case.
- **Sur (policies).**
  - `sur:linucb` and `sur:sw_linucb` run on the simulator through Sur's router plug-in, with Sur's reward.
  - The window sweep can now be re-run here instead of on Sur's stand-in.
- **Riya (experiments).**
  - One command per (scenario, policy, seed). `--out-dir` writes `decision_log.(parquet|csv)` and `run_summary.json`, with exit codes 0 / 1 / 2 like Krupesh's runner.
  - The same seed gives the same requests for every policy, and S1–S6 share their base requests, so comparisons are paired.
  - In `experiment_runner/run_evaluation.py`, the mock cluster can be replaced by this simulator, with your engine unchanged:
    - with `Parikshit/` on `sys.path`, `Simulation(KrupeshRouter(engine), "s4_thermal_throttle", seed).run()` replaces `MockCluster(engine, ...).run()`;
    - `simulator.events.change_times(load_scenario(name))` gives the change times for your `events.json` (t0, plus the return in S6).
  - As in your runner, the router's reward is built from the policy's own reward section. `run_summary.json` includes the policy's counters, and a reward disagreement makes the run invalid (exit code 2).

### Things found while building this (to discuss with the team)

1. **The bandit has something real to learn here.** An A100 needs about 424 ms to start the mean request (1,437 input tokens), so it misses the 250 ms interactive SLO for long prompts, while an H100 needs about 143 ms (`simulator/NUMBERS.md`). The request-length × node-type interaction is exactly what a contextual policy is for.
2. **The router's telemetry is up to 1 s old, and that matters.** During S2's burst, requests reach nodes whose *true* power headroom had already fallen below Jyotir's 2 kW limit after the last tick, and in S4 nodes that had already crossed 85 °C. The `true_state_violation` column counts these. Counting the router's own in-flight placements (Krupesh's local load accounting) does not cover power or temperature.
3. **Assumptions to confirm** with one real vLLM run (brief §5, optional): the decode bandwidth share (0.7), GPU temperature and power behaviour, and the warm-up after a restart. They are listed in `simulator/NUMBERS.md` §9.
4. **Prices are wholesale.** California's midday day-ahead prices are negative, so they are floored at 0. A site's real tariff adds delivery charges, which would shrink the S3 price gap; a fixed adder could be added if the team wants retail-like levels.
5. **S2's burst does not raise TTFT under an even spread.** At 80 requests/s the 3× burst (≈ 240/s) stays below the 5-node maximum of ≈ 278/s.
   - In the brief's model, prefill has no load term, so TTFT rises only when a node runs out of slots or KV cache.
   - With least-load, the share of requests meeting their SLO stays at ~73 % during the burst. Slot use rises from 12 % to 67 %, and A100 nodes hit the power limit.
   - The burst does hurt policies that concentrate traffic on few nodes.
   - If the team wants S2 to stress TTFT for every policy, two options:
     - raise `rate_rps` to ~100, so the burst (≈ 300/s) exceeds the maximum and queues build and then drain;
     - or add a load term to prefill (a change to the brief's model).
   - `python3 simulator/scenario_effects.py` shows the effect of each scenario.
