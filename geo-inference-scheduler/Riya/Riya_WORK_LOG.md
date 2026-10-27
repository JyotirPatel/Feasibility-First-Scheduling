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



Integrated Evaluation Update - October 27, 2026
Implementation is now stored on main; any earlier reference to the deleted riya/evaluation branch is historical.
Completed
- Added metrics/evaluate_log.py for router logs, with TTFT/e2e p95/p99, SLO goodput, outcome counts, rejection/failure rates, logged constraint violations, and raw cost/energy per SLO success.
- Added experiment_runner/run_evaluation.py and config_mock.json, connecting Krupesh's router, Jyotir's filter/baselines and Sur's real learning policies/reward.
- Executed 7 policies x 2 mock scenarios x 10 seeds = 140 unique runs, all status ok. Each uses 300 seconds of arrivals at 10 requests/second.
- Generated per-run logs, metrics, status, goodput curves, configuration and source metadata.
- Generated 95% bootstrap confidence intervals across seed runs (2,000 resamples).
Preliminary results
- Plain/sliding-window LinUCB stable mean goodput: 9.211/9.211 requests/second.
- Plain/sliding-window LinUCB outage mean goodput: 8.212/8.211 requests/second.
- Strongest baseline by mean goodput, static weighted: 8.953 stable and 7.181 outage.
- No demonstrated advantage from forgetting in these runs. Zero rejections and zero logged constraint violations were observed.
- Evidence: experiment_runner/results/evaluation_01/summary.csv, confidence_intervals.csv, config.json, source.json, and individual raw run folders.
Limitations and pending work
- These are mock-simulator integration results, not the full S1-S6 research evaluation.
- Adaptation time, deepest dip, lost goodput and ablations remain pending.
- Upstream energy conversion, GPU-cost omission and timing conventions need correction/review. Cost/energy claims remain provisional.
- Integrate Parikshit's simulator, finalize metric conventions, produce figures with CIs, and complete report analysis.
