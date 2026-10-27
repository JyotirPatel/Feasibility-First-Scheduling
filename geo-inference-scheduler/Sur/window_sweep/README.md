# Sur / window_sweep

**Owner:** Sur. **Hands to:** Riya, for the window-size ablation figure and the "we chose W = … because …" sentence in the method section.

This folder holds the window-size sweep and the exploration-parameter (α) check required in Sur/README.md §5 and brief §6.5 / §7.

| File | What it is |
|---|---|
| `sweep.yaml` | every setting: seeds, scenarios, window sizes and modes, α values, baselines, metric definition |
| `run_sweep.py` | runs every (policy setting × scenario × seed) in parallel and writes the result bundle |
| `parikshit_backend.py` | one run on the project's real pipeline: Parikshit's simulator, Krupesh's router, Jyotir's filter, Sur's reward |
| `make_figures.py` | makes every figure from the bundle only |
| `make_tables.py` | makes every table of `RESULTS.md` from `results/summary.csv` (`--update` rewrites them in place) |
| `diagnostics.py` | per-seed checks behind `RESULTS_standin.md`, on the stand-in: S6 rush, peak queue, traffic share, lowest goodput, violations, per-second trace, counterfactual; S1 load; metric noise; and the `--fixed-filter` what-if (Jyotir's warming-node bug fixed in memory only) |
| `RESULTS.md` | what the sweep found on Parikshit's simulator, with the numbers, and the caveats |
| `results/` | its bundle: `runs.csv`, `summary.csv`, `curves.csv.gz`, `manifest.json`, `tables.md`, `figures/` |
| `RESULTS_standin.md`, `results_standin/` | the earlier sweep on the stand-in simulator, with the old reward scale; superseded |

What one sweep runs:
- every scenario S1–S6 × 10 seeds, with the same seeds and requests for every policy;
- sliding-window LinUCB with W ∈ {200, 500, 1000, 2000, 5000}, plus two extra sizes (10000, 20000), in **both** window modes;
- plain LinUCB as the "no forgetting" reference;
- α ∈ {0.1, 0.5, 1, 2} on S1, S2 and S6;
- Jyotir's six baselines, as a sanity reference only (Riya owns the main comparison).

Run it from the `Sur/` folder:

```bash
python3 window_sweep/run_sweep.py            # full sweep (1,350 runs; ~21 min on 16 processes)
python3 window_sweep/run_sweep.py --quick    # smoke run (the `quick:` subset in sweep.yaml) into results_quick/
python3 window_sweep/make_figures.py         # figures into results/figures/
python3 window_sweep/make_tables.py --update # tables into results/tables.md and RESULTS.md
python3 window_sweep/diagnostics.py          # per-seed checks behind RESULTS.md (see its --help)
```

`--save-logs` also writes every full decision log, in the brief §10.3 columns, to `results/raw/`; that folder is not in git.

**Metrics.** These follow the frozen definitions in work distribution §6:
- **Goodput:** 1-s bins smoothed over 5 s.
- **G\*:** the mean goodput over t0 + 60 s to t0 + 120 s.
- **Adaptation time:** the first moment G ≥ 0.9·G\* for 10 s in a row. A run that never gets there is counted under "recovered runs" instead of being given a number.
- **Deepest dip.**

For S6 the same metrics are also computed from the node's return at 400 s (`return_*` columns), because the frozen anchor at t0 = 200 s only sees the outage. Three more S6 columns describe how the policy treats the returned node:
- `return_node_share_before`: its share of requests before the outage.
- `return_node_share_after`: its share after its warm-up.
- `return_rush_s`: the seconds after its return in which it got ≥ 50% of requests.

`summary.csv` also counts the seeds in which the node was abandoned (< 1% of requests after its warm-up). Every number comes with a 95% bootstrap CI over seeds. Each metric has its own fixed random stream, so one metric's CI never changes because another metric was added.

**Which simulator.** Every run goes through the project's real pipeline (`parikshit_backend.py`):
- Parikshit's simulator, with its real data and the six event traces;
- Krupesh's router, with its decision log, its load accounting between telemetry ticks and Jyotir's filter;
- Sur's reward, built from the policy's own reward section, so router and policy agree (`reward_mismatch` is 0 in every run).

This is the same pipeline Riya's experiment runner uses, so the window chosen here is the one the final runs use. `--simulator standin` runs the earlier stand-in in `../standins/` instead, writing to `results_standin/`; the policies, metrics, CIs and figures are the same code either way.
