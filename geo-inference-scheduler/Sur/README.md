# Sur — LinUCB + Sliding-Window Policy + Reward

**Owner:** Sur. This folder holds the learning policy (plain and sliding-window LinUCB), its context vector and reward, the window sweep, and the method section of the report.

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
| 5. Window-size sweep + α check | `window_sweep/` | done on Parikshit's simulator through Krupesh's router (1,350 runs); results in `window_sweep/RESULTS.md`; it chose the default, a per-node window with W = 500 and α = 1 |
| 6. Citations | `citations/` | done: BibTeX and plain text, checked against Crossref (the publishers' records) or the official proceedings pages |
| Parameter files | `configs/policies/` | `linucb.yaml`, `sw_linucb.yaml`, `sw_linucb_no_context.yaml`; no numbers in the Python code |
| Checkpoints | `checkpoints/` | save/load in both policies (`.npz`, no pickle); checkpoints of the default policies from the sweep on Parikshit's simulator (`checkpoints/simulator/`) |
| Method section | `report/method_section.md` | Riya condensed it into §2 of the final report (`Riya/report/Group20_Final_Report.md`) |
| Notes on the final evaluation | `report/final_evaluation_notes.md`, `window_sweep/final_eval_check.py` | why the "no context" ablation wins S4–S6, and why the S6 outage recovery looks slower; every number regenerated from Riya's bundle |
| Router plug-in | `router_plugin/` | done: the policies as subclasses of Krupesh's `Policy`, `reward_fn` in his `RewardFn` shape, registry names, and his handbook's end-to-end acceptance check (`router_plugin/check_router.py`) |
| Tests | `tests/` | every module tested (`python3 -m pytest geo-inference-scheduler/Sur/tests -q`) |

Install: `python3 -m pip install -r geo-inference-scheduler/Sur/requirements.txt` (Python 3.11+).

### For Krupesh (router)

Your router plugs in through `router_plugin/`. Details are in `router_plugin/README.md`.

**Your code still has the `TODO(Sur)` notes.** Nothing registers Sur's policies in your `registry.py`, and `app.py` and `run_end_to_end.py` use `mock_reward`. So your handbook's acceptance test (`python -m integration.run_end_to_end --policy sur:sw_linucb`) fails with "unknown policy", and so does the HTTP service.
- `router_plugin/krupesh_sur_policies.patch` makes the changes your handbook §5.3 asks for. Apply it from the repo root with `git apply`.
- It was tested on a copy of your folder: the acceptance test passes, and your suite gives the same results with it as without it.
- Details are in `router_plugin/README.md`.

```python
from router_plugin import register, reward_fn  # with geo-inference-scheduler/Sur on sys.path

register()  # adds sur:linucb, sur:sw_linucb, sur:sw_linucb_no_context, linucb, sliding_window_linucb
engine = RoutingEngine(policy=build_policy("sur:sw_linucb", seed=seed), filter_fn=build_filter("jyotir"),
                       reward_fn=reward_fn, ...)  # reward_fn replaces mock_reward
```

- **Acceptance check.** `python3 router_plugin/check_router.py` runs your handbook's acceptance check from Sur's side, with your mock cluster, Jyotir's filter and Sur's policy and reward. It gives `log_problems: []` and `constraint_violations: 0`; `tests/test_router_plugin.py` runs it too.
- **Policy classes.** The registered policies are `RouterLinUCB` and `RouterSlidingWindowLinUCB`: the same classes as `linucb/` and `sliding_window_linucb/`, with your `Policy` added as a base. They read your typed `Request` and `NodeState` and Jyotir's dicts alike.
- **Feedback.** `update()` doesn't receive the features, so the policy stores them at `choose()` time, keyed by `request_id`. Please keep `request_id` unique per request and send exactly one feedback for every routed request, **including failures** (`failed=True`). Your engine and mock already do this.
- **Reward.** The policy recomputes the reward itself; with `reward_fn` it equals your `outcome.reward`. A difference is counted in `stats["reward_mismatch"]`, for example if `mock_reward` is still wired in. A `failed=True` outcome gets no SLO credit and the worst latency.
- **Fields.** The SLO deadline is read from `ttft_slo_ms` (your contract) or `slo_ms` (Jyotir's stub).
- **Threads.** `choose()` and `update()` are thread-safe.
- **Your upload's location.** Your upload sits at `Krupesh/geo-inference-scheduler/Krupesh/`. Your adapter's path to Jyotir's folder has since been fixed (`parents[4]`), and the plug-in finds your code in either place.
- **Your handbook's open decisions owned by Sur (§7).**
  - **#3, window counted globally or per node:** Sur's default is **per node**, with W = 500 (`window_sweep/RESULTS.md`, on Parikshit's simulator through your router).
    - In S1, global windows lose goodput at every W ≤ 2000 (61.6 req/s at W = 200, against 72.2 for every per-node window).
    - Global windows also recover more slowly after the S6 node returns.
  - **#4, reward weights:** Sur's are 1.0 / 0.2 / 0.1 / 0.1 (`configs/policies/sw_linucb.yaml`), so the SLO term dominates.
    - Scales: latency 1,000 ms; energy cost $0.00001, about the 99th percentile of a request's energy cost on Parikshit's simulator (the earlier $0.0002 left the energy term near 0 there); thermal 60 → 85 °C.
    - With these weights the policy ignores prices: S3 does not change its routing (`window_sweep/RESULTS.md`, finding 5).
    - **Decided:** the final evaluation kept these weights. Price-aware routing is listed in the final report as future work.
    - The 1.0 / 0.3 / 0.2 / 0.1 in the handbook are your mock reward's placeholders.

### For Riya (experiments)

- **"No forgetting" ablation:** `configs/policies/linucb.yaml`.
- **"No context" ablation:** `configs/policies/sw_linucb_no_context.yaml`.
- Both differ from `sw_linucb.yaml` only in the ablated part; `tests/test_configs.py` checks this.
- **Policy identifiers** (each class's `name`, also written to checkpoints):
  - `linucb` is `LinUCB` with `linucb.yaml`.
  - `sw_linucb` is `SlidingWindowLinUCB` with `sw_linucb.yaml`. The "no context" ablation is the same class with `sw_linucb_no_context.yaml`.
  - Your final configuration (`Riya/experiment_runner/config_final.json`) uses the registry names `sur:sw_linucb`, `sur:linucb` and `sur:sw_linucb_no_context`.
- **Goodput binning:** the sweep and your final evaluation both count a request in the second it arrived.
- **Window sweep:** run on Parikshit's simulator through Krupesh's router, the same pipeline as your runner.
  - `window_sweep/results/summary.csv` has the means and 95% bootstrap CIs over 10 seeds.
  - The tables in `window_sweep/RESULTS.md` are generated from it by `window_sweep/make_tables.py`.
  - The figures are in `window_sweep/results/figures/`.

### Things found while building this (to discuss with the team)

These come from the window sweep on Parikshit's simulator through Krupesh's router (`window_sweep/RESULTS.md`). The earlier stand-in findings are in `window_sweep/RESULTS_standin.md`.

1. **Forgetting helps after the burst, and costs nothing elsewhere.** This reverses the stand-in result.
   - **S2.** A per-node window of W = 500 adapts in 20.4 s [17.8, 22.2], against 33.6 s [24.9, 41.8] for plain LinUCB, with higher mean goodput (91.8 against 90.6 req/s).
   - **Elsewhere.** In S1, S3, S4 and S5 every per-node window matches plain LinUCB.
   - **Default.** This is why the shipped default is now a per-node window with W = 500 (it was 1000).
2. **Very short per-node windows abandon a node that comes back.**
   - With W = 200, the S6 node got under 1% of requests after its warm-up in 6 of 10 seeds. Its short recovery time (3.2 s) partly reflects that.
   - W ≥ 500 never abandoned it.
   - When reporting a recovery time, show the node's traffic share next to it.
3. **The policy ignores prices with the current weights (1.0 / 0.2 / 0.1 / 0.1).**
   - In S3, the share of traffic to California stays at 72–73 % after California becomes the expensive region.
   - Price-aware routing would need a larger energy weight. The team kept these weights for the final evaluation, so S3 routes as S1 does; the final report lists a reward-weight study as future work.
4. **The router's view is up to 1 s old.** In S2 and S4 the policy (and every baseline) reaches nodes that have just crossed the power or temperature limit, as Parikshit's true-state check shows.
   - Per-node W = 500: about 3,200 such requests per S2 run and 142 per S4 run.
   - Counting the router's own placements against power and temperature, as it does for load, would cut this.
5. **Jyotir's warming-node bug is fixed (his commit 59b63af).**
   - The bug: a `warming` node skipped the memory, power and temperature checks (`filter.py`, rule 1 returned early).
   - It never affected the runs on Parikshit's simulator: the warming node never nears those limits there, and re-running sweep jobs with the fixed filter gives identical numbers.
   - `tests/test_toy_cluster.py::test_s6_warming_node_respects_hard_rules`, an expected failure until then, now guards the fix.
   - **One regression came with the fix, and it is fixed too.** When a node reported `kv_capacity_tokens`, the memory rule ignored the configured 90 % limit (`kv_cache_max_frac`). Jyotir fixed it in 5e3b1a6. The sweep ran before his fix and Riya's final evaluation after it. For both W = 500 and plain LinUCB, all 60 runs (6 scenarios × 10 seeds) have exactly the same request and SLO-met counts in both (`window_sweep/final_eval_check.py`, part 0).
6. **The adaptation-time metric.**
   - **Noise floor.** In S1, where nothing changes, plain LinUCB and W = 500 show a non-zero time in 4 of 10 seeds (4–12 s), because the interactive arrivals are bursty. Read every scenario's time against that floor.
   - **S6** needs the second anchor at the node's return (400 s), as the sweep does.
   - **Binning.** The sweep and Riya's final evaluation both bin requests by arrival time.

### The final evaluation (Riya, 2026-11-26)

- **It ran this folder's code unchanged.** Every code, config and test file it saved from `Sur/` is identical to the one here. It used the shipped defaults: a per-node window with W = 500, α = 1, weights 1.0 / 0.2 / 0.1 / 0.1 and an energy scale of $0.00001.
- **Its numbers for these policies match the sweep.** In S2, W = 500 adapts in 20.4 s against 33.6 s for plain LinUCB, with 91.85 against 90.62 req/s.
- **Two of its results needed an explanation:** the "no context" ablation beating the full policy in S4–S6, and the slower recovery after the S6 outage. Both are explained in `report/final_evaluation_notes.md`, which also has suggested sentences for the final report.
