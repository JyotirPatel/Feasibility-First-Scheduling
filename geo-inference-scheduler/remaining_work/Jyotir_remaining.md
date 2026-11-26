# Remaining Work — Jyotir
**AMS 560 · Group 20 · Fall 2026**
**Professor's remark:** *"Prioritize resolving integration issues and completing end-to-end comparisons."*

---

## Status Summary
All deliverables are complete and pushed. No open items remain on Jyotir's side.

---

## 1. Completed (all locked in)

| Deliverable | Notes |
|---|---|
| Feasibility filter (`filter.py`, `feasibility.yaml`) | 5 rules, YAML thresholds, warming-node tag |
| 6 baseline policies | Round-Robin, Min RTT, Least Load, Lowest Energy, Static Weighted, Power-of-Two |
| Stub objects (`fake_node.py`, `stub_policy.py`) | One-line swap to real interfaces |
| Edge-case test suite | 28 tests, all pass (28th added 2026-11-10 for kv_cache_max_frac regression) |
| Report section | MD + PDF in `report_section/`; covers filter rules, all baselines, S1–S6 tables |
| **Baseline decision logs** | 360 runs (6 policies × 6 scenarios × 10 seeds); committed 2026-11-12 to `Jyotir/baseline_logs/` |

---

## 2. Bugs Fixed

### `kv_cache_max_frac` not enforced in token-exact memory path *(fixed 2026-11-10)*
*(flagged by Sur in RESULTS.md item 4)*

The token-exact check in `filter.py` compared against 100% of KV capacity instead of the configured `kv_cache_max_frac` threshold (0.90 by default). Fixed by adding `kv_limit = config.get("kv_cache_max_frac", 0.90)` and comparing against `kv_capacity * kv_limit`.

- **File:** `feasibility_filter/filter.py`, Rule 3 (Memory)
- **Fix:** `kv_used_tokens + tokens_needed > kv_capacity * kv_limit` (was `> kv_capacity`)
- **New test:** `TestTokenAwareMemoryCheck::test_token_check_respects_kv_cache_max_frac`

---

## 3. Baseline Decision Logs — Results

Committed to `Jyotir/baseline_logs/` on 2026-11-12. Summary:

| Policy | Avg goodput (req/s) |
|---|---|
| jyotir:lowest_energy | 64.08 |
| jyotir:least_load | 61.60 |
| jyotir:power_of_two | 61.43 |
| jyotir:static_weighted | 61.03 |
| jyotir:round_robin | 58.10 |
| jyotir:min_rtt | 55.83 |

All 360 runs returned `status: ok`. `run_coverage.json` shows `"complete": true`.

---

## 4. Open Items for Teammates

| Item | Owner | Priority |
|---|---|---|
| Reward weights (energy scale for S3) team decision | **Team / Sur** | High — must be decided before Riya's 420-run grid |
| Optional spot-check re-run on S2/S4 after kv_cache_max_frac fix | **Sur** | Low — expected numerically stable |
