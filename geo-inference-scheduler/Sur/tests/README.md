# Sur / tests

**Owner:** Sur. These are unit and integration tests for every module in Sur's folder; the repo rule says every module needs at least one test.

Run from the repository root:

```bash
python3 -m pytest geo-inference-scheduler/Sur/tests -q
```

| File | Covers |
|---|---|
| `test_features.py` | context vector: exact values, scaling, field fallbacks, error handling, no-context mode, real filter output |
| `test_reward.py` | reward formula, bounds, SLO dominance, failures (including Krupesh's `failed=True`), config validation, thermal limit = filter limit |
| `test_linucb.py` | LinUCB math (§6.4), only-candidates safety with the real filter, delayed and out-of-order feedback, bad feedback, a router reward that differs, learning, seeds, threads, checkpoints |
| `test_sw_linucb.py` | window contents in both modes, exact rebuilds, numeric drift, forgetting vs plain LinUCB after a change, rediscovering an abandoned node, checkpoints |
| `test_configs.py` | the three policy configs are valid and differ only where an ablation should |
| `test_adaptation.py` | goodput and the frozen adaptation-time definition on hand-made curves |
| `test_toy_cluster.py` | stand-in simulator: workload, scenarios, one feedback per decision, safety audit, determinism |
| `test_sweep.py` | sweep jobs, per-run metrics (including the S6 returned-node metrics), bootstrap CIs and their stability |
| `test_shipped_checkpoints.py` | every file in `checkpoints/standin/` loads into its policy and scores |
| `test_reference_checks.py` | independent re-implementations compared with the production code on thousands of random inputs (context vector, reward, sliding window after every outcome, goodput, adaptation time) |
| `test_diagnostics.py` | the diagnostics script (S6 rush, queue, share, counterfactual; S1 load and metric noise), that watching a run does not change it, that Jyotir's baselines work in every check, and the `--fixed-filter` what-if |
| `test_figures_and_tables.py` | the figure and table scripts, and that every table in `window_sweep/RESULTS.md` equals what `summary.csv` gives |
| `test_router_plugin.py` | Sur's policies and reward inside Krupesh's router (his code, unmodified): `Policy` subclasses, registry names, his typed `Request` / `NodeState` / `Outcome`, failed requests, the end-to-end acceptance check, and catching a router still on his mock reward |

One test is marked **expected to fail** (`xfail`): `test_s6_warming_node_respects_hard_rules`. It records a known bug in Jyotir's filter, where a warming node skips the other hard rules. Once that bug is fixed, the test will pass, and `strict=True` makes the suite report that so the marker can be removed.
