# Remaining Work — Jyotir
**AMS 560 · Group 20 · Fall 2026**
**Professor's remark:** *"Prioritize resolving integration issues and completing end-to-end comparisons."*

---

## Status Summary
All individual code deliverables are complete. One integration-blocking bug was fixed on 2026-11-10. One deliverable remains blocked on the team pipeline.

---

## 1. Completed (all locked in)

| Deliverable | Notes |
|---|---|
| Feasibility filter (`filter.py`, `feasibility.yaml`) | 5 rules, YAML thresholds, warming-node tag |
| 6 baseline policies | Round-Robin, Min RTT, Least Load, Lowest Energy, Static Weighted, Power-of-Two |
| Stub objects (`fake_node.py`, `stub_policy.py`) | One-line swap to real interfaces |
| Edge-case test suite | **28 tests**, 28 pass (28th test added 2026-11-10 for regression below) |
| Report section | MD + PDF in `report_section/`; covers filter rules, all baselines, S1–S6 tables |

---

## 2. Bug Fixed (2026-11-10)

**`kv_cache_max_frac` not enforced in token-exact memory path** *(flagged by Sur in RESULTS.md item 4)*

The token-exact check in `filter.py` compared against 100% of KV capacity instead of the configured `kv_cache_max_frac` threshold (0.90 by default). A node at 85% fill with capacity 1000 tokens should reject any request that pushes usage past 900 tokens — but the old code accepted it up to 1000 tokens.

- **File:** `feasibility_filter/filter.py`, Rule 3 (Memory)
- **Fix:** `kv_used_tokens + tokens_needed > kv_capacity * kv_limit` (was `> kv_capacity`)
- **New test:** `TestTokenAwareMemoryCheck::test_token_check_respects_kv_cache_max_frac`
- **Impact:** Sur's sweep used the pre-fix filter. After this fix, Sur may want to re-run on the 3 scenarios most affected (S2, S4) to confirm numbers are stable. Sur's RESULTS.md notes the winning node rarely approaches the 90–100% zone, so numbers are expected to be unchanged.

---

## 3. Remaining Open Item

### Baseline decision logs on all 6 scenarios
Running all 6 baselines through Parikshit's simulator to produce the Parquet/CSV decision logs that Riya's analysis needs.

**What is needed before this can be done:**
1. Riya's `config_validation.json` pipeline runs clean (1 policy × 3 scenarios × 1 seed — a quick smoke test). Once that passes, the router path through `jyotir_adapter.py` is confirmed.
2. Riya runs `config_simulator.json` (which includes all 6 `jyotir:*` baselines by name).

**What Jyotir needs to do:**  Nothing additional — the baselines are already registered as `jyotir:round_robin` etc. in Krupesh's registry and will be included in Riya's full grid automatically.

**Estimated time once pipeline is green:** 0 hours of coding; logs produced as a side effect of Riya's experiment run.

---

## 4. Items to Coordinate with Teammates

| Item | Owner | Priority |
|---|---|---|
| Stale F1/F2 bug comments in `Krupesh/geo-inference-scheduler/Krupesh/integration/jyotir_adapter.py` lines 13–16 say bugs still exist — both are fixed | **Krupesh** | Medium — grader reads the adapter |
| `JYOTIR_DIR` default path in same file resolves to wrong folder when router runs standalone | **Krupesh** | High — router fails without Riya's override |
| Sur may want to re-run sweep after kv_cache_max_frac fix | **Sur** | Low — expected to be numerically stable |
| Reward weights (energy scale) team decision before final runs | **Team** | High — affects S3 results |
