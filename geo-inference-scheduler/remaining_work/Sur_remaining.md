# Remaining Work — Sur
**AMS 560 · Group 20 · Fall 2026**
**Professor's remark:** *"Prioritize resolving integration issues and completing end-to-end comparisons."*

---

## Status Summary
LinUCB, sliding-window LinUCB, context vector, reward function, router plug-in, and the full window sweep (1,350 runs on the real pipeline) are complete. One key team decision blocks finalising the S3 results. One optional re-run after Jyotir's fix.

---

## 1. Completed

| Deliverable | Notes |
|---|---|
| Plain LinUCB (`linucb/linucb.py`) | Runs via `sur:linucb` in Krupesh's registry |
| Sliding-window LinUCB (`sliding_window_linucb/sw_linucb.py`) | Per-node and global window modes; shipped default W=500, α=1 |
| Context vector builder (`context_vector/features.py`) | 14 scaled features; handles both `ttft_slo_ms` and `slo_ms` naming |
| Reward function (`reward/reward.py`) | YAML-configurable weights; SLO/latency/energy/thermal terms |
| Router plug-in (`router_plugin/plugin.py`) | `register()` adds `sur:linucb`, `sur:sw_linucb`, `linucb`, `sliding_window_linucb` to Krupesh's registry |
| Window sweep (1,350 runs) | W ∈ {200,500,1000,2000,5000,10000,20000}, per-node and global, all 6 scenarios, 10 seeds |
| Sweep results and tables | `window_sweep/RESULTS.md` with Tables A–G; `results/summary.csv` and figures |
| All tests | Test suite passes; `test_figures_and_tables.py` verifies RESULTS.md matches bundle |
| Method section of report | Drafted in `report/method_section.md` |

---

## 2. Team Decision Required Before Final Runs

### Reward weights — energy scale for price-aware routing (S3)
*(RESULTS.md finding 5)*

**Current weights:** SLO = 1.0, latency = 0.2, energy = 0.1, thermal = 0.1
**Current `energy_cost_max_usd`:** $0.00001 (99th percentile of a request's energy cost)

With these weights, the learned policies give **exactly the same results in S3 (price shift) as in S1 (stable)** — routing does not change despite California prices jumping from ~$0 to $0.046–0.050/kWh. The energy term moves the reward by only ~0.01 per request, so it is dominated by the SLO term.

**What is needed:** A team decision on whether the final paper should show price-aware routing in S3. Options:

| Option | Change | Trade-off |
|---|---|---|
| Keep current weights | No change | S3 looks identical to S1; lowest-energy is the only policy that reacts |
| Raise energy weight | Increase `energy` weight or raise `energy_cost_max_usd` | Policy shifts traffic in S3; SLO term no longer wins every trade-off; may lose ~1–2 req/s goodput in S1 |

**Who decides:** Whole team; **must be decided before Riya runs the final grid.** Changing weights after the run means re-running.

The reward config is `Sur/configs/policies/sw_linucb.yaml`. Krupesh's handbook §7, item 4 tracks this decision.

---

## 3. Optional Re-Run After Jyotir's Fix

Jyotir fixed the `kv_cache_max_frac` regression on 2026-11-10 (token-exact memory path now enforces the 90% threshold instead of 100%). Sur's sweep ran with the pre-fix filter.

**Expected impact:** Minor. Sur's RESULTS.md notes that no S6 true-state violations involved the warming node, and the fix only tightens the memory check by 10% of capacity. Nodes between 90–100% KV fill that were previously accepted will now be rejected.

**Recommendation:** Re-run a quick spot check on S2 and S4 (the scenarios with the most true-state violations) with 1 seed to confirm numbers are stable before Riya's full grid. If numbers match, no full re-run is needed.

---

## 4. Figures Still Needed for the Report

The window sweep produced its own figures (goodput-over-time, window vs. adaptation time, α check). These are for the **method section only**. The figures Riya will generate from the full grid (goodput bar charts with 95% bootstrap CIs per policy × scenario) are separate and cover the **evaluation/results sections**. Sur does not need to produce these.

**Sur's one outstanding figure item:** confirm that `window_sweep/results/figures/` contains all 5 figures listed in RESULTS.md (`goodput_<scenario>.png` × 6, `window_adaptation.png`, `window_steady_level.png`, `window_goodput.png`, `alpha_check.png`) and that they were generated from `results/` (not `results_standin/`).
