# Messages to the Team — Parikshit
**AMS 560 · Group 20 · Fall 2026**
**Date:** 2026-11-12 · **Branch:** `parikshit` (commit `3216633`)

---

## Summary
My remaining-work item (the `node.py` KV-overflow crash) is done; Jyotir fixed it in `9617653`, and I updated my test to match. While running my 122 tests on Windows I found encoding problems: mine are fixed on the `parikshit` branch, and one in Sur's folder still breaks any router run on Windows.

---

## 1. For Jyotir

| Item | Details |
|---|---|
| Please merge `parikshit` into `main` | 6 files, all inside `Parikshit/`; no other folder is touched |
| Thanks for the `node.py` fix | `tests/test_node.py` still expected the old `ValueError`; it now checks that the oversized request is recorded as a failed outcome and the node stays empty |
| `remaining_work/Parikshit_remaining.md` §2 can be marked done | The crash fix is in `main`; the matching test fix is on `parikshit` |
| The Quick Status table in `Group20_Remaining_Work.pdf` has shifted columns | My row reads "Run 420-grid; write Eval / Results / Discussion", which is Riya's item (the critical-path table has it right) |

---

## 2. For Sur — Windows encoding bug (High)

**File:** `Sur/router_plugin/plugin.py`, line 88
```python
with open(config) as f:
```
On Windows, Python reads files as cp1252 by default. `Sur/configs/policies/linucb.yaml` and `sw_linucb.yaml` contain non-ASCII characters that cp1252 cannot decode, so loading the reward config raises `UnicodeDecodeError`. Every run that uses Sur's policy or reward crashes on Windows: 15 of my integration tests fail for this reason alone.

**Fix:**
```python
with open(config, encoding="utf-8") as f:
```
The same pattern (`open(...)` without `encoding=`) appears in `linucb/linucb.py:106`, `standins/toy_cluster.py`, and `window_sweep/*.py`. They only matter if those files are run on Windows.

**Workaround until fixed:** set `PYTHONUTF8=1` before running.

---

## 3. For Riya — before the final grid

- If the 420-run grid runs on **Windows**, set `PYTHONUTF8=1` until Sur's fix is merged, or the router crashes on its first run.
- `run_summary.json` → `configs_sha256` keys now always use forward slashes (`configs/nodes_5.yaml`), so they are the same on Windows and Linux. Nothing in `Riya/` reads these keys, so no change is needed on your side.
- My test suite on the merged branch: 120 passed, 1 skipped with `PYTHONUTF8=1`. The one other failure is a local checkout issue, described below.

---

## 4. For Everyone

### Git line endings on Windows (Low)
With `core.autocrlf=true` (the Windows default), git converts `Parikshit/data/processed/*.csv` to CRLF on checkout. The simulator reads them correctly, but their SHA-256 no longer matches `manifest.json`, so `test_committed_processed_files_match_their_manifest` fails locally. The committed files are correct. A `.gitattributes` in `data/processed/` with `* -text` would fix this for everyone; I'll add it if the team agrees.

### Team decisions still open (from `remaining_work/`)

| Decision | Who | My side |
|---|---|---|
| Reward weights / energy scale for S3 | Team | Blocks the final grid; no simulator change needed |
| S2 base rate 80 → ~120 req/s | Team + Krupesh | `rate_rps` in `configs/workload.yaml` and in Riya's `config_simulator.json` (which overrides it); Sur's sweep would no longer be directly comparable |
| Telemetry tick 1 s → 0.5 s | Team + Krupesh | One value (`tick_s`) in `configs/nodes_5.yaml` |
| Router counts placements against power/temperature (Krupesh Option A) | Team + Krupesh | I can work out the per-request power delta from the power model (`power:` in `configs/nodes_5.yaml` + server power in `configs/calibration.yaml`) |
