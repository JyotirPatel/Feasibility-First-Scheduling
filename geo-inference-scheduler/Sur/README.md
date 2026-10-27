# Sur — LinUCB + Sliding-Window Policy + Reward

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Big Data Systems, Algorithms and Networks · Fall 2026 · Group 20

---

## Role

Sur owns the learning policy and the reward signal it learns from. The policy is the part that actually improves over time — it watches outcomes and shifts traffic toward better nodes as conditions change.

---

## Assigned Work

### 1. Plain LinUCB (`linucb/`)
Implement LinUCB (Li et al., 2010) — a contextual bandit that keeps one linear model per node:

- For each node `a`, maintain matrix `A_a` and vector `b_a`. Start with `A_a = λI` and `b_a = 0`.
- **Estimate:** `θ_a = A_a⁻¹ b_a`
- **Score:** `score_a = θ_a^T x + α · √(x^T A_a⁻¹ x)` (predicted reward + uncertainty bonus)
- **Choose:** pick the feasible node with the highest score.
- **Update:** `A_a ← A_a + x x^T`, `b_a ← b_a + r · x`

Plain LinUCB also serves as an ablation baseline (never forgets).

### 2. Sliding-Window LinUCB (`sliding_window_linucb/`)
Same algorithm, but `A_a` and `b_a` are built only from the last **W** decisions per node (Cheung, Simchi-Levi, Zhu, 2019). When a result leaves the window, subtract it back out:
- `A_a ← A_a − x x^T`, `b_a ← b_a − r · x`

Small W reacts faster to changes but is noisier. Large W is stable but slow to adapt. W is swept in experiments.

### 3. Context Vector (`context_vector/`)
For each candidate node, build a feature vector of scaled numbers so all features are comparable in range:
- Request: input token length, expected output length, SLO class, SLO deadline
- Node: network delay to user region, queue length, running requests, KV cache used, electricity price, GPU price, temperature, warming-up flag

### 4. Reward Function (`reward/`)
After each request outcome, compute:

```
r = w₁ · [SLO met] − w₂ · latency − w₃ · energy cost − w₄ · thermal stress
```

- `[SLO met]` is 1 if TTFT was within the SLO, 0 otherwise.
- All other terms scaled to 0–1 range before weighting.
- Weights `w₁`–`w₄` live in `configs/policies/sw_linucb.yaml` — not in code.

### 5. Window-Size Sweep (`window_sweep/`)
Run experiments with W ∈ {200, 500, 1000, 2000, 5000} to find the best trade-off between reaction speed and stability. Also run an exploration-parameter sweep over `α`.

### 6. Citations
Provide correct academic citations for:
- Li et al., 2010 — original LinUCB
- Cheung, Simchi-Levi, Zhu, 2019 — sliding-window idea
These must appear in the report's Related Work section (not framed as our novelty).

---

## Deliverables

| Deliverable | Where it lives |
|---|---|
| Plain LinUCB implementation | `linucb/` |
| Sliding-window LinUCB implementation | `sliding_window_linucb/` |
| Context vector builder | `context_vector/` |
| Reward function | `reward/` |
| Parameter config file + model checkpoints | root of `Sur/` |
| Window-size sweep results | `window_sweep/` |

---

## What You Need From Others Before You Can Build

### From Parikshit — Telemetry Schema v1
**Specific deliverable:** `telemetry/telemetry_schema_v1.json` — the full list of fields each node reports and their units (rtt_ms per region, queue_len, running, kv_used_frac, power_headroom_kw, temperature_c, energy_price_usd_kwh, gpu_price_usd_hr, status).
**Why you need it first:** The context vector is built from node telemetry fields. You need to know which fields exist, their names, and their value ranges before you can scale them to comparable ranges and write `features.py`. If the schema changes after you hardcode field names, every feature-building function breaks.
**Due:** End of Week 1.

### From Jyotir — Feasibility Filter Module (callable interface)
**Specific deliverable:** The `filter.py` function/class that takes a request and a list of nodes and returns only the feasible nodes with reasons.
**Why you need it first:** LinUCB must only score and choose among nodes that the filter has approved. Without the filter being callable, you have no clean way to get the candidate list — you would either call non-existent code or have to mock the filter in a way that does not match the real behavior. At minimum you need the interface stub so your `choose()` method can call it correctly.
**Due:** End of Week 1 (interface stub), End of Week 2 (full implementation).

### From Krupesh — Policy Interface (`Policy` base class)
**Specific deliverable:** The `Policy` base class with `choose(request, candidates) → node_id` and `update(request, node_id, outcome) → None`, plus the `Outcome` data type definition (ttft_ms, e2e_ms, slo_met, energy_kwh, cost_usd).
**Why you need it first:** Both LinUCB variants must subclass this base class so the router can swap policies with one config line. Without knowing what `request`, `candidates`, and `outcome` look like as typed objects, you cannot write the `choose` and `update` methods — you would be working against a moving interface.
**Due:** End of Week 1.

---

## What You Provide to Others

| Deliverable you hand over | Who receives it | When |
|---|---|---|
| Plain LinUCB + sliding-window LinUCB policy modules | Krupesh (plugs into router for adaptive runs) | End of Week 3 (sliding window), End of Week 2 (plain LinUCB) |
| Window-size sweep results (W ∈ {200, 500, 1000, 2000, 5000}) | Riya — included in the ablations and method section figures | End of Week 3 |
| Citations for LinUCB and sliding-window LinUCB | Riya — inserted into the Related Work section of the report | End of Week 3 |

---

## Report / Presentation Section

Method section — policy description, context vector, reward function, and a related-work paragraph on contextual bandits and sliding-window forgetting.

---

## Implementation (what is in this folder now)

Every task above is implemented and tested. Each folder has its own README with details.

| Task | Where | Status |
|---|---|---|
| 1. Plain LinUCB | `linucb/linucb.py` | done: brief §6.4 math, per-node models, seeded tie-breaking, checkpoints |
| 2. Sliding-window LinUCB | `sliding_window_linucb/sw_linucb.py` | done, with **both** window readings (`per_node` and `global`; open question, brief §15) |
| 3. Context vector | `context_vector/features.py` | done: the brief §6.2 features (13 numbers, because the SLO class is one 0/1 flag per class) plus a bias term, scaled to 0..1, and a "no context" switch for the ablation |
| 4. Reward | `reward/reward.py` | done: `w1·[SLO met] − w2·latency − w3·energy cost − w4·thermal stress`, terms scaled to 0..1, weights in config |
| 5. Window-size sweep + α check | `window_sweep/` | done on the stand-in simulator; results in `window_sweep/RESULTS.md` (preliminary until Parikshit's simulator exists) |
| 6. Citations | `citations/` | done: BibTeX and plain text, checked against Crossref (the publishers' records) or the official proceedings pages |
| Parameter files | `configs/policies/` | `linucb.yaml`, `sw_linucb.yaml`, `sw_linucb_no_context.yaml`; no numbers in the Python code |
| Checkpoints | `checkpoints/` | save/load in both policies (`.npz`, no pickle); stand-in checkpoints from the sweep |
| Method section draft | `report/method_section.md` | draft for Riya to merge into the report |
| Tests | `tests/` | every module tested (`python3 -m pytest geo-inference-scheduler/Sur/tests -q`) |

Install: `python3 -m pip install -r geo-inference-scheduler/Sur/requirements.txt` (Python 3.11+).

### For Krupesh (router)

```python
from sliding_window_linucb import SlidingWindowLinUCB  # or: from linucb import LinUCB

policy = SlidingWindowLinUCB(seed=run_seed)  # reads configs/policies/sw_linucb.yaml

allowed, rejected = feasibility_filter(request, telemetry)  # Jyotir's filter first
node_id = policy.choose(request, allowed)  # always one of `allowed`
...  # POST /feedback arrives later
policy.update(request, node_id, outcome)  # Outcome(ttft_ms, e2e_ms, slo_met, energy_kwh, cost_usd, reward)
decision_log_row["reward"] = policy.last_reward
```

- Both policies subclass the shared `Policy` stub in `Jyotir/stubs/stub_policy.py`, like Jyotir's baselines. When your real base class exists, change the one `from stubs.stub_policy import ...` line in `linucb/linucb.py`.
- `update()` doesn't receive the features, so the policy stores them itself at `choose()` time, keyed by `request_id`. Please keep `request_id` unique per request and send exactly one feedback for every routed request, **including failures** (for example, a node dying mid-request).
- The policy computes the reward itself and ignores `outcome.reward`. `reward.compute_reward(node_snapshot, outcome, cfg)` gives the same number for baseline runs.
- The SLO field is read from `ttft_slo_ms` (brief) or `slo_ms` (Jyotir's stub), because the drafts disagree.
- `choose()` and `update()` are thread-safe.

### For Riya (experiments)

- **"No forgetting" ablation:** `configs/policies/linucb.yaml`.
- **"No context" ablation:** `configs/policies/sw_linucb_no_context.yaml`.
- Both differ from `sw_linucb.yaml` only in the ablated part; `tests/test_configs.py` checks this.
- **Policy identifiers** (each class's `name`, also written to checkpoints):
  - `linucb` is `LinUCB` with `linucb.yaml`.
  - `sw_linucb` is `SlidingWindowLinUCB` with `sw_linucb.yaml`. The "no context" ablation is the same class with `sw_linucb_no_context.yaml`.
  - Your planner (`Riya/experiment_runner/config.json`) currently calls the second one `sliding_window_linucb`, and it does not list the "no context" ablation yet.
- **Goodput binning:** the stand-in metric (`standins/adaptation.py`) counts a request in the second it arrived. `Riya/metrics/calculate_metrics.py` counts SLO successes by completion time. Agree on one before the adaptation-time metric is written.
- **Window sweep:** `window_sweep/results/summary.csv`, with means and 95% bootstrap CIs over 10 seeds; the tables in `window_sweep/RESULTS.md` (generated from it by `window_sweep/make_tables.py`); and figures in `window_sweep/results/figures/`.

### Things found while building this (to discuss with the team)

1. **Bug in Jyotir's filter.** A `warming` node skips the model, memory, power and temperature checks (`filter.py`, rule 1 returns early).
   - In the S6 sweep this let most policies route requests to a warming node whose KV cache was ≥ 90% full: 234,039 times in total.
   - That includes plain LinUCB, min-RTT, round-robin, static-weighted and every sliding-window setting except per-node W = 200. Least-load, power-of-two and lowest-energy never did.
   - It is also the main cause of the S6 slowdowns. With the bug fixed in memory (the what-if `window_sweep/diagnostics.py --fixed-filter`), plain LinUCB's lowest goodput after the node's return rises from 77.7 to 211.4 req/s on average.
   - `tests/test_toy_cluster.py::test_s6_warming_node_respects_hard_rules` records it as an expected failure.
2. **Per-node vs global window.** With a per-node window, a node the policy stopped picking may never be tried again. In S6 this really happened.
   - Per-node windows of W ≤ 2000 sent the recovered node under 1% of requests after its warm-up in 3–7 of 10 seeds (W = 5000: 1 of 10).
   - The requests lost in its outage were the newest outcomes in its window, and they made the model's estimate for it erratic. At W = 200 and W = 1000 the node was dropped in exactly the seeds where that estimate was negative.
   - A global window always used it again, but rushed most traffic onto it for 5–7 s (in 69 of 70 runs) while it was still warming up.
   - See `window_sweep/RESULTS.md`, findings 4 and 5.
3. **The adaptation-time metric.**
   - At low request rates, normal random variation alone can break the "≥ 90% of G* for 10 s" rule. At 25 requests/s, S1 (where nothing changes) showed a non-zero time in 2 of 5 seeds for plain LinUCB and in 3 of 5 for static-weighted.
   - A noisy policy gets noise times too. Even at 240 requests/s, the windows with W ≤ 5000 and every global window score up to 6.5 s on average in S1.
   - The rule stops at the first 10 s above 0.9·G\*, so a later dip does not count. Plain LinUCB scores 0 s in every S4 and S5 seed although its goodput dips afterwards.
   - In S2 it is all-or-nothing: 1–2 s or 8–22 s per seed for plain LinUCB and the two fastest windows.
   - For S6, measuring only from t0 = 200 s misses the node's return at 400 s.
   - A short adaptation time can also mean the policy simply stopped using the recovered node, so show its traffic share next to the time.
4. **Rush onto a fresh node.** When a node comes back warming, the model has never seen it in that state, so its exploration bonus is large. Any policy that still uses it can then send it most requests for several seconds, until results for the queued requests come back.
   - Plain LinUCB did this for 6–7 s in 7 of 10 seeds, and global windows in 69 of their 70 S6 runs.
   - The stand-in's router already sees fresh queue lengths, so stale telemetry is not the cause.
   - Fixing the filter bug (item 1) cuts the rush to at most 2 s.
5. **One faster-adaptation result.** In the S2 traffic burst, per-node W = 5000 adapted faster than plain LinUCB (4.6 s [1.3, 8.1] against 12.1 s [8.5, 15.5]), but with lower goodput during the burst. In no other scenario was a window faster (RESULTS.md, finding 3).
