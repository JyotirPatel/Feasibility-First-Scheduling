# Final integration and evaluation notes

Baseline repository: `d997af8dc5004e0a3d89f5d4734ec31008a184ff`.
The old 420-run bundle records commit `b6d9bb6b09b3cfc19b1f05dea21fcbfbae91bf40`.

After normalizing Windows path separators and testing both LF and CRLF encodings,
145 recorded inputs comprise 5 exact matches, 136 newline-only differences and four
content differences: Jyotir's filter and filter tests, Krupesh's adapter, and
Parikshit's node simulator. The filter now enforces the configured 90% KV threshold;
the simulator reports oversized requests as failures instead of crashing. These are
behavioral changes, so the old result bundle is retained as historical evidence and
the final grid is generated anew.

## Evaluation implementation

- Explicit policy variants identify the no-filter and no-context ablations. No forgetting
  reuses plain LinUCB from the main grid. The registered no-filter name is `none`.
- Generated `baseline_logs`, results, stand-in results, runs, checkpoints and input
  snapshots are excluded from source capture. All actual code/config/data inputs,
  including compressed Azure traces, are copied into the bundle.
- Parquet preserves the authoritative raw decision logs while reducing storage.
- Run tasks execute in independent worker processes; every policy receives the same
  seeded requests. Each worker uses one BLAS thread.
- Completed bundle hashes are checked before reuse. The final verifier also replays
  metrics from saved raw logs and verifies workload pairing and complete seed grids.
- Rejected requests have zero simulator-attributed GPU/energy consumption because they
  never execute; control-plane costs are outside the model. Missing values on routed
  outcomes still make resource totals unavailable. Raw and accounted coverage are both
  recorded.
- Two stale module regression tests were updated to verify the corrected warming-node
  filter and graceful simulator rejection, without changing those production modules.

## Privileged reference and recovery deficit

The reference is labelled `reference:true_state`. It refreshes true node states on every
arrival, applies the configured hard filter, checks actual token admission and an immediate
slot, and greedily selects minimum model TTFT. It has no future-event lookahead or global
allocation optimization. It is a myopic true-state reference, not a proven upper bound.

For each matched scenario/seed, the positive area between this reference's smoothed
arrival-goodput curve and a policy's curve is summed over [t0,t0+120). This is reported as
reference-relative lost goodput with its reference label, not as globally optimal regret.
The same reference steady level accompanies each recovery record. S1 pseudo-events and
S6 outage/return anchors remain distinct. This operational reference is documented because
the original brief did not supply an implemented oracle. Static round-robin is never
silently substituted for it.

## Scope

The final config retains five sites, 80 base requests/s, the six 600-second traces,
per-node W=500, alpha=1, and reward weights 1.0/0.2/0.1/0.1. The main comparison contains
420 runs. Two extra ablations add 120; the privileged reference adds 60, for 600 total.
Sur's historical window sweep is supporting method-selection evidence and is not pooled
with this final result bundle. HTTP service deployment is outside this in-process
experiment driver; router HTTP contract tests are checked independently.

## Module validation

| Module | Passed | Skipped |
| --- | ---: | ---: |
| Riya metrics and final integration | 26 | 0 |
| Jyotir filter and baselines | 28 | 0 |
| Krupesh router | 34 | 1 |
| Parikshit simulator | 121 | 1 |
| Sur policy, features and reward | 228 | 0 |

These are separately invoked suites, not one aggregated suite. Optional skips are
preserved. The router suite uses its nested package root and excludes proxy routing
for local HTTP tests. The final smoke grid completed 15 runs: round-robin,
SW-LinUCB, no filter, no context and true-state reference, each on S1/S2/S6 with seed 0.
No learning parameters or simulator production files were changed for this evaluation.
