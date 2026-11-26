# Final evaluation results

The frozen `experiment_runner/results/final_02` bundle completed **600/600 runs**:
420 main policy comparisons, 120 additional no-filter/no-context ablations, and
60 privileged myopic true-state reference runs. Plain LinUCB supplies no forgetting.
All 60 scenario/seed groups have identical workload fingerprints across ten policies.

- All per-run hashes and 152 source/input snapshots passed validation.
- Metrics were independently replayed from all 600 raw Parquet logs.
- Recovery replay passed for 700 event records: curves, smoothing, G*, adaptation, dips,
  reference-relative deficits and affected-node traffic shares.
- Module suites passed separately: Riya 26, Jyotir 28, Krupesh 34 (one skip),
  Parikshit 121 (one skip), Sur 228. Two stale regression assertions were corrected.

## Selected results

Goodput is requests/s; brackets are 95% seed-bootstrap intervals.

| SW-LinUCB scenario | Goodput |
| --- | --- |
| Stable | 72.26 [71.96, 72.59] |
| Traffic burst | 91.85 [91.43, 92.23] |
| Outage and recovery | 70.80 [70.27, 71.29] |

The paired S2 goodput difference from plain LinUCB is 1.23
[0.65, 1.94] requests/s. Main and ablation results, tail latency,
resource accounting, recovery and safety are reported together in the final report.
Execution success is distinct from physical safety; independent true-state violations
remain important because telemetry can be stale. The reference is not a proven global optimum.

## Submission files

- `report/Group20_Final_Report.pdf` and editable Markdown.
- Root bundle tables, confidence intervals, analysis and regenerated figures.
- Ten separate policy raw-log archives, each restoring its logs into `final_02`.
- `verification.json`, `recovery_verification.json`, `source_comparison.json` and
  the exact code/config/data snapshot for reproducibility.

Old mock outputs, the earlier 420-run bundle and historical tuning results remain
separate. Final parameters were held at five nodes, base 80 requests/s, alpha=1,
per-node W=500 and reward weights 1.0/0.2/0.1/0.1. The source commit is the base
repository commit; captured source hashes additionally identify the local integration changes.
