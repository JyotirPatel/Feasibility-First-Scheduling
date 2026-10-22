# Riya — Experiments + Metrics + Analysis + Report

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Big Data Systems, Algorithms and Networks · Fall 2026 · Group 20

---

## Role

Riya owns running all experiments, computing all metrics, producing every figure, and assembling the final report. All numbers in the paper come from Riya's result bundle — nowhere else.

---

## Assigned Work

### 1. Metrics (`metrics/`)
Implement each metric from the decision log:

| Metric | Definition |
|---|---|
| SLO goodput | Requests per second that finish within their SLO (TTFT < 250 ms). Late requests do not count. |
| p95 / p99 latency | 95th / 99th percentile of TTFT and end-to-end time |
| Rejection rate | Share of requests rejected because no node was feasible |
| Cost per successful request | Total energy cost + GPU cost divided by requests that met SLO |
| Adaptation time | See exact definition below |
| Deepest dip | Lowest goodput value during the recovery window |
| Lost goodput | Area between oracle goodput and actual goodput during recovery |

**Adaptation time (frozen definition — do not change after sign-off):**
1. A change starts at time t₀.
2. Measure goodput G(t) in 1-second bins, smoothed with a 5-second moving average.
3. New steady level G* = average of G(t) from t₀+60 s to t₀+120 s.
4. Adaptation time = (first time t after t₀ where G(t) ≥ 0.9 × G* and stays ≥ 0.9 × G* for 10 s in a row) − t₀.
5. If that never happens, report "did not recover" — not a number.
6. Always show G* next to adaptation time (a weak policy can settle at a low G* and look fast).

### 2. Experiment Runner (`experiment_runner/`)
Build a runner that executes: every policy × every scenario × at least 10 random seeds, all from one config file. Same seeds and traces for every policy so comparisons are fair.

Experiment bundle per run must include: exact config used, seed, git commit hash, decision log, summary metrics table. Figures are regenerated from bundles only — never from memory.

### 3. Ablations (`ablations/`)
Run the three ablations to show what each component contributes:
- No feasibility filter (remove Jyotir's filter)
- No context (plain bandit with no features)
- No forgetting (plain LinUCB — never forgets)

### 4. Confidence Intervals (`metrics/`)
Compute 95% bootstrap confidence intervals on every reported number. No number goes into the report without a CI.

### 5. Figures (`figures/`)
Produce:
- Goodput over time around each change event (one line per policy), with the adaptation-time marker drawn on the graph
- Bar charts with confidence intervals for all policies × all scenarios

### 6. Report (`report/`)
Assemble the final report from all members' sections. Write the Evaluation, Results, and Discussion sections personally, including cases where the method does not help. Produce the results slides for the Zoom recording.

---

## Deliverables

| Deliverable | Where it lives |
|---|---|
| Metrics code (including adaptation time) | `metrics/` |
| Experiment runner + config files | `experiment_runner/` |
| Ablation run configs and results | `ablations/` |
| Result bundle (raw logs + summary tables) | `experiment_runner/` |
| Figures (goodput curves + bar charts) | `figures/` |
| Final report draft | `report/` |

---

## What You Need From Others Before You Can Build

### From Krupesh — Decision Log Format + Running System
**Specific deliverable 1:** `decision_log/decision_log_format.md` — the exact column list and types for the CSV/Parquet log (`run_id, seed, scenario, policy, request_id, t_arrival, decision, node_id, feasible_nodes, filtered_out, reject_reason, ttft_ms, e2e_ms, slo_met, energy_khw, cost_usd, reward`).
**Why you need it first:** Every metric (goodput, latency, cost, adaptation time) is computed by reading specific columns from this log. If the column names or types change after you write `metrics.py`, all your parsing code breaks. Freeze the format in Week 1 before writing a single line of metrics code.

**Specific deliverable 2:** A running end-to-end system that produces actual decision logs when given a scenario trace and a policy config.
**Why you need it first:** You cannot run any real experiment without the system producing logs. You can write and test the metrics code against a small synthetic log, but the real experiment runner cannot fire until Krupesh's router is wired to Jyotir's filter and Sur's policy.
**Due:** Log format — End of Week 1. Running system — End of Week 2.

### From Parikshit — Six Event Trace Files (S1–S6)
**Specific deliverable:** The 6 replayable scenario trace files in `event_traces/` (s1_stable, s2_traffic_burst, s3_price_shift, s4_thermal_throttle, s5_network_degradation, s6_outage_recovery), each with a fixed random seed so results are reproducible.
**Why you need it first:** The experiment runner replays these traces for every policy × seed combination. Without them, you have no controlled scenarios to test recovery on — you cannot generate the goodput-over-time curves or measure adaptation time. All six scenarios must exist before the full experiment grid can run.
**Due:** End of Week 3 (all 6 traces complete), End of Week 2 (at least S1 and S2 for first baseline numbers).

### From Jyotir — Baseline Decision Logs on All 6 Traces
**Specific deliverable:** One decision log file per baseline policy (round-robin, min RTT, least load, lowest energy, static weighted) × all 6 scenarios, produced by running those baselines through the full system with the same seeds.
**Why you need it first:** Every comparison figure shows the adaptive policy against baselines. Without baseline logs, you can only plot LinUCB's curve in isolation — there is nothing to compare against, so no figure is meaningful. You need these logs before you can make any bar chart or goodput curve.
**Due:** End of Week 3.

### From Sur — Window-Size Sweep Results
**Specific deliverable:** Raw decision logs or summary tables from running W ∈ {200, 500, 1000, 2000, 5000} on at least S2 (traffic burst) and S6 (outage + recovery), showing how adaptation time and steady-state goodput change with W.
**Why you need it first:** The window-size ablation figure and the method section's claim about the chosen W both depend on these results. You need them before you can write the "we chose W=X because…" justification in the report and produce the sweep figure.
**Due:** End of Week 3.

---

## What You Provide to Others

| Deliverable you hand over | Who receives it | When |
|---|---|---|
| Adaptation time definition (code + frozen spec) | All members — must sign off before any run is finalized | End of Week 1 (spec), End of Week 2 (code) |
| Experiment bundle format (configs, seeds, logs, tables) | All members — final numbers for the report come only from here | End of Week 3 |
| Final report (assembled from all sections) | All members for review, then submission | Week 4 |
| Figures (goodput curves + bar charts with CIs) | All members for the presentation slides | Week 4 |

---

## Report / Presentation Section

Evaluation, Results, and Discussion sections of the report. All results slides for the final Zoom recording and submission.
