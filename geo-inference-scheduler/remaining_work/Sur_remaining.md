# Remaining Work — Sur
**AMS 560 · Group 20 · Fall 2026**
**Professor's remark:** *"Prioritize resolving integration issues and completing end-to-end comparisons."*

*Updated by Sur on 2026-11-26, after Riya's final evaluation.*

---

## Status Summary
All of Sur's items are done.
- Riya's final evaluation (`Riya/experiment_runner/results/final_02`) ran Sur's code unchanged, with the shipped defaults: a per-node window with W=500, α=1 and weights 1.0/0.2/0.1/0.1.
- Its numbers for these policies match the window sweep.

---

## 1. Completed

| Deliverable | Notes |
|---|---|
| Plain LinUCB (`linucb/linucb.py`) | Runs via `sur:linucb` in Krupesh's registry |
| Sliding-window LinUCB (`sliding_window_linucb/sw_linucb.py`) | Per-node and global window modes; shipped default W=500, α=1 |
| Context vector builder (`context_vector/features.py`) | 14 scaled features; handles both `ttft_slo_ms` and `slo_ms` naming |
| Reward function (`reward/reward.py`) | YAML-configurable weights; SLO/latency/energy/thermal terms |
| Router plug-in (`router_plugin/plugin.py`) | `register()` adds `sur:linucb`, `sur:sw_linucb`, `sur:sw_linucb_no_context`, `linucb`, `sliding_window_linucb` to Krupesh's registry |
| Window sweep (1,350 runs) | W ∈ {200,500,1000,2000,5000,10000,20000}, per-node and global, all 6 scenarios, 10 seeds |
| Sweep results and tables | `window_sweep/RESULTS.md` with Tables A–G; `results/summary.csv` and figures |
| All tests | Test suite passes; `test_figures_and_tables.py` verifies RESULTS.md matches bundle |
| Method section of report | `report/method_section.md`; Riya condensed it into §2 of the final report |
| Notes on the final evaluation | `report/final_evaluation_notes.md` (numbers from `window_sweep/final_eval_check.py`). They explain why the "no context" ablation wins S4–S6 and why the S6 outage recovery looks slower, with suggested sentences for the final report. |
| Patch for Krupesh's router | `router_plugin/krupesh_sur_policies.patch` resolves the `TODO(Sur)` notes in his code. It registers Sur's policies in `registry.py` and uses Sur's reward for them in `app.py` and `run_end_to_end.py`, as his handbook §5.3 asks. On a copy of his folder, his acceptance test (`python -m integration.run_end_to_end --policy sur:sw_linucb`) passes with it and fails without it, and his suite is unchanged. It is his decision to apply it. |

---

## 2. Reward weights for S3 — decided: keep them

The final evaluation ran with the current weights: SLO 1.0, latency 0.2, energy 0.1, thermal 0.1, and `energy_cost_max_usd` $0.00001. Its saved copies of all three policy files show these values.
- **S3 against S1.** S3 gives exactly S1's SLO-met count in every seed, for both learned policies.
- **Why.** After the price shift, a San Jose request loses about 0.02 of reward, against about 1.0 for meeting the SLO (`window_sweep/final_eval_check.py`, part 6).
- **Future work.** The final report lists a reward-weight study as future work. Changing the weights now would mean re-running the 240 final runs that learn from this reward: both learned policies and the no-context and no-filter ablations.
- **For anyone who revisits this:**
  - The lever is the energy weight. Raising `energy_cost_max_usd` makes the energy signal weaker, not stronger.
  - Below an energy weight of 0.7, meeting the SLO always beats missing it (1.0 > 0.2 + energy + 0.1). From 0.7 up, the weights no longer guarantee that.

---

## 3. Re-check after Jyotir's fix — done, on every run

The window sweep ran before Jyotir's `kv_cache_max_frac` fix (5e3b1a6), and Riya's final evaluation ran after it.
- For both learned policies, all 60 runs (6 scenarios × 10 seeds) have exactly the same request and SLO-met counts in the two (`final_eval_check.py`, part 0).
- A test re-checks this.
- The spot check the team suggested (S2 and S4 with one seed) was also re-run on the current code with `window_sweep/run_sweep.py`: seed 0, the default policy and plain LinUCB. All 4 runs match the sweep in every field except wall-clock run time.
- No full re-run was needed.

---

## 4. Figures — confirmed

All 10 figures in `window_sweep/results/figures/` are byte-identical to the ones `python3 window_sweep/make_figures.py` regenerates from `results/` (Parikshit's simulator). None matches the `results_standin/` version (checked 2026-11-26 with matplotlib 3.10.8). The figures are:
- `goodput_<scenario>.png` × 6
- `window_adaptation.png`
- `window_steady_level.png`
- `window_goodput.png`
- `alpha_check.png`

They are for the method section only; the evaluation figures are Riya's.
