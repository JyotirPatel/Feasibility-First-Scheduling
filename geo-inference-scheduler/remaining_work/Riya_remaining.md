# Remaining Work — Riya
**AMS 560 · Group 20 · Fall 2026**
**Professor's remark:** *"Prioritize resolving integration issues and completing end-to-end comparisons."*

---

## Status Summary
Experiment runner, metrics module, recovery metrics, summarizer, figure generator, and the full pipeline integration are complete. The full 420-run grid has not yet been executed. Report sections for Evaluation, Results, and Discussion are not yet written. These are the main remaining items.

---

## 1. Completed

| Deliverable | Notes |
|---|---|
| Metrics module (`evaluate_log.py`) | Goodput, rejection rate, p95/p99 latency, cost, energy, `true_state_violation_rate` |
| Recovery metrics (`metrics/recovery.py`) | Adaptation time, G\*, deepest dip, stable noise floor, node traffic shares; binned by arrival time |
| Experiment runner (`run_evaluation.py`) | Full pipeline: simulator → router → filter → policy → decision log → metrics → recovery |
| Summarizer (`summarize_results.py`) | Bootstrap CIs across seeds, pairing checks (workload SHA), stable noise floor table |
| Figure generator (`figures/plot_results.py`) | Goodput-over-time curves + CI bar charts; reads from persisted bundles only |
| Main config (`config_simulator.json`) | 7 policies × 6 scenarios × 10 seeds = 420 runs; 80 req/s, 5 nodes, arrival-time binning |
| Validation config (`config_validation.json`) | 1 policy × 3 scenarios × 1 seed — smoke test before full grid |
| Mock evaluation results (historical) | 7 policies × 2 mock scenarios × 10 seeds = 140 runs; in `results/evaluation_01/`; not to be used for comparisons |
| Sample fixtures | `metrics/sample_metrics.json`, `sample_metadata.json` for unit verification |

---

## 2. Pipeline Validation (do first)

Before running the full 420-run grid, run the validation config to confirm the end-to-end pipeline is wired correctly:

```bash
python run_evaluation.py \
  --config config_validation.json \
  --output ../results/validation_01
```

This runs 1 policy × 3 scenarios × 1 seed (3 runs total, ~5–10 min). Check that:
- `status.json` shows `"status": "ok"` for all 3 folders
- `decision_log.csv` exists and passes `validate_log()`
- `metrics.json` shows non-zero `goodput_rps`
- `recovery.json` has the correct anchors for each scenario
- `true_state_violation` column is present (requires Parikshit's `KrupeshRouter.after_route`)

**Block:** Parikshit's `node.py` crash bug (see Parikshit's remaining work) must be fixed first to avoid a mid-run crash. Krupesh's `JYOTIR_DIR` bug must also be fixed so the adapter resolves without Riya's override (or confirm the override is in place for the production run).

---

## 3. Full 420-Run Grid

After validation passes:

```bash
python run_evaluation.py \
  --config config_simulator.json \
  --output ../results/final_01
```

Expected duration: ~21 min on 16 processes (matches Sur's sweep; uses the same pipeline).

Use `--resume` if the run is interrupted. Each completed seed bundle is SHA-256 verified before being skipped on resume.

**After the run completes:**
- Check `run_coverage.json`: `"complete": true`, 420 ok bundles.
- Check `pairing_checks.csv`: all `workloads_match = true` (all policies saw the same arrivals per seed).
- Check `stable_noise_floor.csv`: S1 pseudo-event delays give a noise floor to compare against S2–S6 adaptation times.

**Team decision needed first:** Reward weights (Sur's item — energy scale for S3). Once decided, update `Sur/configs/policies/sw_linucb.yaml` and re-run. If unchanged from the sweep, S3 results will show no price-aware routing.

---

## 4. Figure Generation

After `final_01` is complete:

```bash
python figures/plot_results.py --results ../results/final_01
```

Produces in `final_01/figures/`:
- `<scenario>_goodput.png` — goodput-over-time per policy with recovery dots
- `<scenario>_<metric>.png` — CI bar charts for 9 key metrics per scenario

These are the **primary paper figures**. Plots will not be generated until the full grid is complete (they require `confidence_intervals.csv`, which needs ≥10 seeds).

---

## 5. Report Sections to Write

| Section | Status | Inputs needed |
|---|---|---|
| Evaluation setup | Not started | Final cluster size, rate_rps, seed count — already in `config_simulator.json` |
| Results — goodput | Not started | `final_01/figures/` and `confidence_intervals.csv` |
| Results — adaptation time | Not started | `final_01/recovery_summary.csv`; note S1 noise floor when reporting |
| Results — cost and energy | Not started | `confidence_intervals.csv` (cost_usd_per_slo_success, energy_kwh columns) |
| Ablation runs (3) | Not started | Need separate runs: (a) no filter, (b) no context features, (c) no forgetting |
| Discussion | Not started | Written after results are in |

**Ablation configs** — create three variants of `config_simulator.json`:
- `config_ablation_no_filter.json`: change `filter_name` from `"jyotir"` to `"passthrough"` (or disable filter in engine)
- `config_ablation_no_context.json`: use `sur:sw_linucb` with `sw_linucb_no_context.yaml`
- `config_ablation_no_forgetting.json`: use `sur:linucb` (plain LinUCB; no window)

---

## 6. Final Report Assembly

Each member has pushed their section:
- **Krupesh:** Introduction, System Design, Novelty (`report_sections/`)
- **Parikshit:** Simulator section (`report/simulator_section.md`)
- **Sur:** Method section (`report/method_section.md`)
- **Jyotir:** Filter and baselines section (`report_section/baselines_report_section.md`)

**Riya assembles:** Evaluation + Results + Discussion + Conclusion → merge into final PDF. Coordinate section order and consistent notation (e.g. G\* symbol, adaptation time definition, goodput binning note).

---

## 7. Known Metric Limitations to Document

- **Lost goodput**: `recovery.json` sets `lost_goodput_requests: null` for all runs because a matched oracle (round-robin baseline curve at same seed) is not yet provided. When `final_01` is complete, pass the round-robin curve as the oracle in a post-processing step.
- **S1 noise floor**: In stable operation, Sur's sweep found non-zero pseudo-adaptation delays in 4 of 10 seeds (4–12 s). Report every scenario's adaptation time against this floor.
- **S6 two-anchor reporting**: Report S6 adaptation time from both t0=200 s (outage) and t0=400 s (node return). Include returned node's traffic share alongside the time number.
