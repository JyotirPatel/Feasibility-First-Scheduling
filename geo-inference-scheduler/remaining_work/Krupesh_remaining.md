# Remaining Work — Krupesh
**AMS 560 · Group 20 · Fall 2026**
**Professor's remark:** *"Prioritize resolving integration issues and completing end-to-end comparisons."*

---

## Status Summary
Router service, decision log format, policy interface, integration adapter, and all integration bugs are complete. One optional telemetry-age improvement remains as a team decision.

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
| **Bug A — stale F1/F2 comments** | Fixed 2026-11-12: removed outdated comments describing pre-fix behaviour; replaced with accurate description |
| **Bug B — wrong `JYOTIR_DIR` path** | Fixed 2026-11-12: changed `parents[2]` → `parents[4]`; path now resolves correctly to repo root's `Jyotir/` |

---

## 2. Optional Improvement (team decision)

### Telemetry-age: count recent placements against power and temperature
*(Sur RESULTS.md finding 8, item 3)*

The router already counts its own in-flight placements against **load** between telemetry ticks. Sur's sweep found that in S2 (3× burst) the learned policy reaches ~3,200 nodes per run that have just crossed the power limit — caused entirely by the 1-second-old telemetry view. The baselines reach ~8,000–19,800 such nodes per run.

**Option A (team decision):** Count router placements against power draw and temperature, the same way it currently counts against queue depth. Requires knowing each node's per-request power delta (Parikshit can provide from calibration).

**Option B (team decision):** Reduce the telemetry tick interval from 1 s to 0.5 s.

Both are team decisions before the final run. Neither blocks current results.

---

## 3. Verification Step

Before Riya's final 420-run grid:

1. Run `run_end_to_end.py` standalone (without Riya's path override) to confirm `JYOTIR_DIR` now resolves correctly with `parents[4]`.
2. Confirm `weekly_integration_check.py` passes on the latest code from all members.

No further router-side code changes are expected.
