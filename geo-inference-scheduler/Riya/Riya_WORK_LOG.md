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

## 4. Current Simulator Evaluation


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

A fresh full simulator grid, confidence intervals and report figures must be generated from
these bundles before final comparative claims. Lost goodput requires a matched oracle.
Recovery delays must be shown with G*, recovery fractions, stable noise and node traffic
shares. Team decisions about final cluster size and reward settings remain explicit inputs.

## 5. Earlier Commits

- `a8106d4`: Initial metrics and synthetic verification example
- `a578495`: Dry-run planner for 420 experiment combinations
