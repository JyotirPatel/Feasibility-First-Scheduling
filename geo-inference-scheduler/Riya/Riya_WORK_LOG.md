# Riya — Work Log

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Fall 2026 · Group 20
**Role:** Experiments, Metrics, Analysis, and Report

## 1. Initial Metrics Implementation (historical)

Implemented `metrics/calculate_metrics.py` to read request logs
and run metadata, validate inputs, and calculate:

- Total, completed, unfinished, and rejected request counts
- SLO-successful request count
- SLO goodput
- Rejection rate
- p95 and p99 end-to-end latency
- Total request-attributed cost and energy
- Cost and energy per SLO-successful request

The current implementation uses the supplied `slo_met` field.
The initial version preceded the router-schema integration described below.

### Files

- `metrics/calculate_metrics.py`
- `metrics/sample_requests.csv`
- `metrics/sample_metadata.json`
- `metrics/sample_metrics.json`

### Verification

Verified calculations using a synthetic example containing
10 requests over 10 seconds:

| Metric | Verified value |
|---|---:|
| Completed requests | 8 |
| Rejected requests | 2 |
| SLO successes | 6 |
| Goodput | 0.6 requests/second |
| Rejection rate | 20% |
| p95 latency | Approximately 365 ms |
| p99 latency | 393 ms |
| Cost per SLO success | $0.02 |
| Energy per SLO success | 20 J |

These values verify the metric calculations.
They do not represent actual scheduling-policy performance.

## 2. Dry-Run Experiment Planner (historical)

Implemented configuration-driven planning for:

- 7 scheduling policies
- 6 scenarios
- 10 random seeds
- 420 planned experiment combinations

The planner validates configuration entries, assigns unique
run identifiers, and saves a configuration snapshot, experiment
plan, and Git commit metadata.

This version only prepares experiments. It does not execute
the simulator or generate performance results.

### Files

- `experiment_runner/config.json`
- `experiment_runner/run_experiments.py`
- `experiment_runner/plans/midterm_v1/config_snapshot.json`
- `experiment_runner/plans/midterm_v1/experiment_plan.csv`
- `experiment_runner/plans/midterm_v1/plan_metadata.json`

The simulator runner below uses the registered policy names and trace names.

## 3. Historical Mock Integration Checks

The earlier router integration executed 7 policies × 2 mock scenarios × 10 seeds
(140 successful runs). These checked wiring and metric output; they are not the full
S1–S6 evaluation. Their logs remain in `experiment_runner/results/evaluation_01/`.
Do not use their goodput, energy or cost estimates as the new simulator results.

## 4. Earlier Simulator Integration


- Switched the evaluation runner from the mock cluster to the replayable S1–S6 simulator.
- Added a 420-run main configuration (7 policies, 6 scenarios, 10 paired seeds), with five
  nodes and 80 requests/s explicitly recorded as the current starting defaults.
- Uses current teammate policy/reward configurations; saves resolved inputs and source hashes.
- Implemented frozen adaptation time, G*, deepest dip, and both S6 anchors (200 and 400 s).
- Standardized curves and recovery calculations on arrival-time goodput, matching the sweep.
- Added stable pseudo-event noise diagnostics, affected-node traffic shares and independent
  simulator true-state violation counts alongside the router audit.
- Added bootstrap intervals across seeds, workload-pairing checks and bundle-only figures.
- Preserved sample fixtures and historical mock runs as verification material.

This stage established the simulator integration. The frozen final evaluation below
supersedes its result bundle for final comparative claims.

## 5. Earlier Commits

- `a8106d4`: Initial metrics and synthetic verification example
- `a578495`: Dry-run planner for 420 experiment combinations

## 6. Final Integration, Evaluation and Report

Completed a new frozen 600-run evaluation after auditing the old source hashes and
finding four content changes. The main comparison contains 420 runs; no-filter and
no-context ablations add 120, and a clearly labelled myopic true-state reference adds 60.
Plain LinUCB is the no-forgetting ablation. Every run passed execution/log validation.

The runner now supports explicit filter variants, parallel independent processes,
Parquet logs, checked resume, and source capture that excludes generated baseline logs.
All policies use matching seeded workloads. Metrics account for rejected requests'
zero execution-attributed resources without hiding missing routed outcomes.

Full verification replayed all raw-log metrics and all recovery records, checked hashes,
validated matching workloads and confirmed the complete grid. The final analysis adds
paired bootstrap effects, recovery counts, stable noise, both S6 anchors, node traffic
shares and independent true-state safety annotations. Module test counts and limitations
are recorded in `report/INTEGRATION_NOTES.md`.

All figures were regenerated from the frozen bundle. The final PDF and editable report
are in `report/Group20_Final_Report.*`; `report/FINAL_RESULTS.md` summarizes completion.
Raw logs are preserved separately from the compact code/tables/figures for transfer.
Old synthetic fixtures, mock results and earlier simulator runs remain historical material.
