# Messages to the Team — Parikshit
**AMS 560 · Group 20 · Fall 2026**
**Date:** 2026-11-12 · **Branch:** `parikshit`

---

## Summary
My required item from `remaining_work/` (the `node.py` KV-overflow crash) is done: Jyotir fixed it in `9617653`, and I updated my test to match on the `parikshit` branch. The rest of my list is team decisions. While running my tests on Windows I found an encoding bug in Sur's folder that crashes every router run on Windows.

Each section below is a ready-to-send message.

---

## 1. Group message

> Hi all, Parikshit here. Status from my side:
>
> - The `node.py` crash fix is in `main` (thanks Jyotir). I've updated my test to match and fixed some Windows encoding issues in my folder. It's all on the `parikshit` branch, waiting for Jyotir to merge.
> - Nothing else on my list is blocked by me. What's left is team decisions, and they need to happen **before Riya runs the final 420-run grid**:
>   1. **Reward weights for S3** (Sur's item): with the current weights, the learned policy ignores the price shift. This one blocks the grid.
>   2. **S2 base rate 80 → ~120 req/s**, so the 3× burst actually stresses the cluster. Changing it means Sur's sweep is no longer directly comparable.
>   3. **Telemetry tick 1 s → 0.5 s.** This should roughly halve the true-state power violations caused by stale telemetry.
>   4. **Krupesh's Option A** (router counts recent placements against power and temperature). If we pick it, I'll provide the per-request power delta.
> - **Windows heads-up:** Sur's reward config fails to load on Windows (details sent to Sur). Until it's fixed, set `PYTHONUTF8=1` before any run.
> - **Small one:** on Windows, git changes the line endings of my two data CSVs, so one of my tests fails locally (the committed files are fine). A `.gitattributes` with `* -text` in `Parikshit/data/processed/` fixes it. OK if I add it?
>
> Can we settle items 1–4 this week? Full details are in `Parikshit/TEAM_MESSAGES.md` on the `parikshit` branch.

---

## 2. To Jyotir

> Hi Jyotir, can you merge the `parikshit` branch into `main`? It only touches `geo-inference-scheduler/Parikshit/`:
> - `tests/test_node.py`: the KV-overflow test still expected the old `ValueError`. After your `node.py` fix it now checks that the request is recorded as a failure and the node stays empty.
> - Added `encoding="utf-8"` to the YAML/JSON file reads, so the configs load on Windows.
> - `run_scenario.py`: the `configs_sha256` keys in `run_summary.json` now use forward slashes on every OS.
> - This file, `TEAM_MESSAGES.md`.
>
> PR link: https://github.com/JyotirPatel/Feasibility-First-Scheduling/pull/new/parikshit
>
> Two small things about the remaining-work docs:
> - §2 of `Parikshit_remaining.md` can be marked done.
> - The Quick Status table in `Group20_Remaining_Work.pdf` has shifted columns: my row says "Run 420-grid; write Eval / Results / Discussion", which is Riya's item. The critical-path table at the end has it right.

---

## 3. To Sur

> Hi Sur, I found a bug that crashes runs on Windows. In `Sur/router_plugin/plugin.py` line 88:
> ```python
> with open(config) as f:
> ```
> Windows Python reads files as cp1252 by default. `configs/policies/linucb.yaml` and `sw_linucb.yaml` contain non-ASCII characters it can't decode, so loading the reward config raises `UnicodeDecodeError`. Any run with your policy or reward then crashes on Windows. 15 of my integration tests fail for this reason alone.
>
> The fix is one line:
> ```python
> with open(config, encoding="utf-8") as f:
> ```
> The same pattern (`open(...)` without `encoding=`) is also in `linucb/linucb.py:106`, `standins/toy_cluster.py` and `window_sweep/*.py`. Those only matter if someone runs them on Windows.
>
> Also, the reward-weights decision for S3 is the one blocking Riya's final grid. It would help if you proposed the new energy weight.

---

## 4. To Riya

> Hi Riya, a few notes before the final grid:
> - If you run it on **Windows**, set `PYTHONUTF8=1` until Sur's encoding fix is merged. Without it the router crashes on its first run.
> - The `node.py` crash and the `JYOTIR_DIR` bug are both fixed in `main`, so nothing on my side blocks the validation run anymore.
> - If the team raises the S2 rate, change `rate_rps` in your `config_simulator.json`. It overrides the 80 in my `configs/workload.yaml`.
> - `run_summary.json` → `configs_sha256` keys now always use forward slashes. Nothing in `Riya/` reads them, so you don't need to change anything.
> - My report section (`Parikshit/report/simulator_section.md`) is drafted. I'll update it if the tick or rate changes.

---

## 5. To Krupesh

> Hi Krupesh, two of the open decisions are between the two of us:
> - **Telemetry tick 1 s → 0.5 s:** on my side it's one value (`tick_s` in `configs/nodes_5.yaml`). Does the router need any change for a 0.5 s tick?
> - **Your Option A** (count recent placements against power and temperature): if we go with it, I'll work out each node's per-request power delta from my power model (`power:` in `configs/nodes_5.yaml` plus the server power in `configs/calibration.yaml`).
>
> Which one do you prefer? Either way, it needs to be settled before Riya's final grid.

---

## Reference: open team decisions

| Decision | Who | Change on my side |
|---|---|---|
| Reward weights / energy scale for S3 | Team | None |
| S2 base rate 80 → ~120 req/s | Team + Krupesh | `rate_rps` in `configs/workload.yaml` and Riya's `config_simulator.json` |
| Telemetry tick 1 s → 0.5 s | Team + Krupesh | `tick_s` in `configs/nodes_5.yaml` |
| Router counts placements against power/temperature (Option A) | Team + Krupesh | Provide per-request power delta |
| `.gitattributes` for `data/processed/` | Team | Add `* -text` |
