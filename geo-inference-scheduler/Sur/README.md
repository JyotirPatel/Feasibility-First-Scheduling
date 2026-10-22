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
