# Remaining Work — Krupesh
**AMS 560 · Group 20 · Fall 2026**
**Professor's remark:** *"Prioritize resolving integration issues and completing end-to-end comparisons."*

---

## Status Summary
Router service, decision log format, policy interface, and integration adapter are complete. Two integration bugs exist in `jyotir_adapter.py` that must be fixed before standalone deployment works. One optional telemetry-age improvement flagged by Sur.

---

## 1. Completed

| Deliverable | Notes |
|---|---|
| FastAPI router service (`/route`, `/feedback` endpoints) | Complete with thread-safe `RLock` engine |
| Decision log format | 18-column Parquet/CSV schema; `validate_log()` enforced by Riya's runner |
| Policy base class (`policy_base.py`) | Jyotir's baselines and Sur's LinUCB both inherit from it |
| Integration adapter (`jyotir_adapter.py`) | Wraps Jyotir's filter and all 6 baselines behind Krupesh's types |
| Registry with `build_policy` / `build_filter` | `jyotir:*` names work; Sur's `register()` adds `sur:*` names |
| Mock objects | `mock_policy.py`, `mock_reward.py`, `mock_simulator.py` for smoke tests |
| Integration test scripts | `weekly_integration_check.py`, `run_end_to_end.py` |
| Report sections | Introduction, System Design, Novelty sections drafted |

---

## 2. Bugs to Fix (integration-blocking)

### Bug A — Stale F1/F2 comments in `jyotir_adapter.py`
**File:** `integration/jyotir_adapter.py`, lines 13–16
```
# F1  a node with status "warming" returns before the model/memory/power/temperature
#     rules run, so a hot or full warming node is allowed.
# F2  the memory rule ignores the size of the request (only kv_used_frac >= limit).
```
Both bugs were fixed by Jyotir (his commit 59b63af). These comments now falsely tell the grader that known bugs still exist. **Remove or rewrite them** to document the current correct behaviour.

**Fix:** Delete lines 13–16 and replace with:
```
# Jyotir's filter as of commit 59b63af+: warming nodes go through all 5 rules;
# the memory rule uses token-exact check with kv_cache_max_frac enforced.
```

### Bug B — Default `JYOTIR_DIR` resolves to wrong path
**File:** `integration/jyotir_adapter.py`, line 29
```python
JYOTIR_DIR = Path(__file__).resolve().parents[2] / "Jyotir"
```
Because Krupesh's folder was uploaded one level deeper than the repo root, `parents[2]` resolves to `Krupesh/geo-inference-scheduler/` → `JYOTIR_DIR` becomes `Krupesh/geo-inference-scheduler/Jyotir/` which does not exist. The router works only because Riya's runner overrides this with `jyotir_adapter.JYOTIR_DIR = ROOT / "Jyotir"`. Running `uvicorn router_service.app:app` directly would fail at import time.

**Fix:** `Parikshit/simulator/routers.py` already solves this for the simulator path; use the same pattern:
```python
JYOTIR_DIR = Path(__file__).resolve().parents[4] / "Jyotir"  # or use GEO_DIR detection
```
Or make `JYOTIR_DIR` resolve relative to the repo root by walking up until a known sentinel file is found.

---

## 3. Optional Improvement

### Telemetry-age: count recent placements against power and temperature
*(Sur RESULTS.md finding 8, item 3)*

The router already counts its own in-flight placements against **load** between telemetry ticks. Sur's sweep found that in S2 (3× burst) the learned policy reaches ~3,200 nodes per run that have just crossed the power limit — caused entirely by the 1-second-old telemetry view. The baselines reach ~8,000–19,800 such nodes per run.

**Option A (team decision):** Count router placements against power draw and temperature, the same way it currently counts against queue depth. Requires knowing each node's per-request power delta (Parikshit can provide from calibration).

**Option B (team decision):** Reduce the telemetry tick interval from 1 s to 0.5 s.

Both are team decisions before the final run. Neither blocks current results.

---

## 4. Final Integration Steps (after Bug A and B are fixed)

1. Run `run_end_to_end.py` standalone (without Riya's path override) to confirm `JYOTIR_DIR` resolves correctly.
2. Confirm `weekly_integration_check.py` passes on the latest code from all members.
3. No further router-side changes are expected before Riya's final 420-run grid.
