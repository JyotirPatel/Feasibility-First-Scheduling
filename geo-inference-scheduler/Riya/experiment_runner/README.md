# Riya — simulator evaluation

The current runner uses Parikshit's simulator, Krupesh's router, Jyotir's filter/baselines,
and Sur's registered policies and reward. It supports the existing nested Krupesh upload;
no teammate production files need moving or editing. The previous 140 mock runs remain historical
integration checks and must not be reported as S1–S6 evaluation results.

## Install and run (PowerShell, from geo-inference-scheduler/Riya)

```powershell
python -m pip install -r experiment_runner/requirements.txt
python -m pytest tests -q
python -X utf8 experiment_runner/run_evaluation.py --config experiment_runner/config_final_validation.json --output experiment_runner/results/final_validation --workers 6
```

The final validation config runs round-robin, SW-LinUCB, no filter, no context and the true-state reference on S1, S2 and S6 with seed 0 (15 runs). These are integration
checks; one seed is insufficient for report confidence intervals.

The final config runs the 420 main comparisons, 120 additional no-filter/no-context ablations and 60 true-state reference runs: **600 runs**. Plain LinUCB already supplies the no-forgetting ablation. Historical `config_simulator.json` remains available for the main-only grid.

```powershell
python -X utf8 experiment_runner/run_evaluation.py --config experiment_runner/config_final.json --output experiment_runner/results/final_02 --workers 6
```

Use a new output folder. If interrupted, rerun the exact same command with `--resume`.
The runner rejects resume when code, input data or config hashes changed. After a teammate
changes the filter/router/policy, start a new result bundle. Never combine those versions.
`--limit 1` is available for a single smoke run. Errors return a nonzero exit code.

Five nodes and 80 requests/s are the supplied defaults, recorded explicitly. They are a
reproducible starting configuration, not a claim of team sign-off on cluster size.
The six trace YAMLs determine the 600-second duration and events. Policy configs are
loaded from Sur's files, including per-node W=500 and the current reward normalization;
resolved inputs are saved per run. Do not silently change reward weights or load to get
better results. Ten-node load scaling requires an explicit team choice.

## Metrics conventions

- Goodput uses arrival-time bins throughout, matching Sur's sweep. Successful outcomes
  that drain after 600 seconds count against their original arrival. Counts are divided
  by the fixed 600-second arrival interval, including zero bins.
- Success is the authoritative `slo_met` plus `outcome_status=ok`; the simulator has both
  interactive and batch requests with their own SLOs. These aggregate metrics are mixed
  workload results, not a claim that every request has a 250 ms threshold. The existing
  router contract uses `<=`; any strict `<` change requires team agreement.
- Recovery: 1-second bins, trailing 5-bin mean, G* over [t0+60,t0+120), first 10 consecutive
  seconds at or above 90% G*. Search continues from t0 to the last possible 10-bin hold.
  Deepest dip uses [t0,t0+120). G* is always saved next to the delay. Zero G* is explicitly
  flagged, even though the frozen threshold would report immediate recovery.
- S1's 200-second pseudo-event is a **noise diagnostic**, not adaptation to a real change.
  `stable_noise_floor.csv` counts positive pseudo-delays and reports their range and a
  bootstrap CI on the false-delay fraction. Recompute it; do not hardcode a previous
  sweep's 4/10 observation.
- S6 has separate records at 200 seconds (outage) and 400 seconds (return). Event times
  and affected nodes come from the trace, including the actual warm-up duration.
- `node_traffic_shares.csv` records each affected node's share of all arrivals before the
  event, in the first 120 seconds, and in the G* window. Show these with recovery times:
  a short delay while a node is unused does not demonstrate useful node recovery.
- `true_state_violations` is the count of requests annotated by the simulator's independent
  true-state check. Its rate uses routed requests as denominator. `constraint_violations`
  remains a separate router/filter audit; neither is an assertion of safety certification.
- Energy is kWh, cost is USD including the simulator's GPU attribution. Missing resource
  values on routed requests yield unavailable totals. Rejected requests have zero execution-attributed consumption; raw and accounted coverage are both recorded. TTFT and E2E p95/p99 use successful completed
  outcomes (`ok`), including late outcomes, excluding rejected/failed/unfinished requests.
- The labelled true-state reference refreshes telemetry on every arrival and chooses minimum model TTFT with immediate slot and actual-memory admission. It is a privileged myopic reference, not a proven global upper bound. `finalize_reference.py` checks matching workload fingerprints and integrates positive smoothed-goodput deficits over [t0,t0+120). The reference label and steady level accompany the metric. Never silently substitute a static baseline for an oracle.

## Bundles, CIs and figures

Each run includes persisted decision_log.parquet (CSV is an optional config setting), config.json, resolved_inputs.json,
metrics.json, recovery.json, goodput_curve.csv, events.json, status.json and simulator
stats; bandits also have policy_stats.json. The root includes exact experiment config,
git commit when available and source/input SHA256 hashes. A downloaded ZIP has no Git
metadata, so its commit may be null; hashes still identify its inputs.

`summary.csv`, `recovery_summary.csv`, `node_traffic_shares.csv`, `pairing_checks.csv`,
`recovery_with_node_shares.csv`, `confidence_intervals.csv`, and `stable_noise_floor.csv` are rebuilt from saved bundles:

```powershell
python experiment_runner/summarize_results.py --results experiment_runner/results/final_02
python experiment_runner/analyze_final.py --results experiment_runner/results/final_02
python figures/plot_results.py --results experiment_runner/results/final_02
python experiment_runner/verify_results.py --results experiment_runner/results/final_02 --deep
```

Bootstrap means across seeds (2,000 resamples, fixed bootstrap seed), not across
individual requests. CIs require at least 10 nonmissing seeds. Adaptation-delay CIs are
conditional on recovered seeds; always show the recovery fraction and G*. Do not replace
non-recovery with zero, or publish a CI from one smoke seed. The plots deliberately skip
bar charts lacking 10-seed CIs. All figures read saved bundles only.

## Source capture and caching

Source/input snapshots exclude generated baseline logs, run results, checkpoints and previous snapshots. Compressed Azure traces are included. Workers are independent processes with one BLAS thread; policy-independent workload fingerprints must match. Resume checks every recorded bundle hash and rejects changed code/config/environment inputs. Base Git commit plus exact SHA256 snapshots identify local integration changes that were not yet committed at execution time.

`verify_results.py --deep` checks the entire grid and hashes, then recomputes metrics from raw logs. `analysis/main_run_coverage.json` isolates the main 420; root `run_coverage.json` covers all 600.

## Save and commit

See [FINAL_RUN_COMMANDS.md](FINAL_RUN_COMMANDS.md) for the end-to-end commands and [integration notes](../report/INTEGRATION_NOTES.md) for definitions and module validation. Keep raw logs available alongside the compact code, tables, curves and figures. Avoid staging the virtual environment or several gigabytes of raw results with `git add .`. The delivery's `START_HERE.md` provides explicit staging commands.
