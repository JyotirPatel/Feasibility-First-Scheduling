# Riya — Work Log

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Fall 2026 · Group 20
**Role:** Experiments, Metrics, Analysis, and Report

## 1. Initial Metrics Implementation

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
TTFT metrics and the final simulator log schema remain pending.

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

## 2. Dry-Run Experiment Planner

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

Policy and scenario identifiers are provisional until confirmed
during team integration.

## 3. Integration Requirements

- Krupesh: final decision-log schema and simulator entry point
- Parikshit: scenario traces, run duration, and event timestamps
- Jyotir: baseline policy identifiers and configurations
- Sur: learning-policy identifiers and parameter configurations

## 4. Pending Work

- Connect the runner to the integrated simulator
- Adapt metrics to the final decision-log schema
- Add TTFT percentile metrics
- Implement adaptation time, deepest dip, and lost goodput
- Add execution failure tracking and resume support
- Run actual experiments using matching workloads across policies
- Compute bootstrap confidence intervals
- Run ablations and produce figures
- Write results and discussion and assemble the report

## 5. Commits

- `a8106d4`: Initial metrics and synthetic verification example
- `a578495`: Dry-run planner for 420 experiment combinations