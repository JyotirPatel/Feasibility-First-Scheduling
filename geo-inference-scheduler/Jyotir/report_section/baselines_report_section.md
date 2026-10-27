# Section: Feasibility Filter and Baseline Scheduling Policies

**Author:** Jyotir  
**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes  
**Course:** AMS 560 · Big Data Systems, Algorithms and Networks · Fall 2026 · Group 20

---

## 3. Feasibility Filter and Baseline Scheduling Policies

### 3.1 Overview

Our scheduler operates in two stages: a **feasibility filter** that removes nodes that physically cannot serve a request, followed by a **selection policy** that picks the best node from those that remain. This section describes both components.

The separation between filtering and selection is intentional. Hard physical constraints — node reachability, model availability, GPU memory, thermal limits, and power limits — are not preferences to be traded off; they are binary. A node whose KV cache is full will drop the request. A node above 85 °C is throttling. Routing to such a node wastes the request and degrades the SLO. By handling these constraints in a single, dedicated filter, every policy downstream is guaranteed to work only with nodes that can actually serve the request.

This design also enables controlled experimental comparison: every baseline policy and the learned policy (sliding-window LinUCB) receive exactly the same candidate set from the same filter. Any difference in measured goodput or adaptation time is therefore attributable to the selection logic, not to differences in which nodes each policy sees.

---

### 3.2 Feasibility Filter

#### 3.2.1 Design

The filter takes a request and the current telemetry snapshot of all nodes and returns two lists: `allowed` (nodes that pass every rule) and `rejected` (nodes removed, each with a reason string). If `allowed` is empty, the router rejects the request entirely with reason `no_feasible_node`.

All thresholds are read from `feasibility_filter/configs/feasibility.yaml` at startup. No threshold is hardcoded in Python. This allows the system operator to tune limits without touching the implementation.

```yaml
# feasibility_filter/configs/feasibility.yaml
temperature_limit_c:    85.0
power_headroom_min_kw:  2.0
kv_cache_max_frac:      0.90
allow_warming_nodes:    true
```

#### 3.2.2 The Five Rules

The filter evaluates each node against five rules in order. Evaluation stops at the first failure (fail-fast), and the reason string for that rule is recorded.

**Rule 1 — Node Status.**  
The node's `status` field must be `"up"` or `"warming"`. The filter normalises the value to lowercase before checking, so `"DOWN"`, `"Offline"`, and `"draining"` are all treated as `"node_down"`. A missing `status` field is also treated as `"node_down"`. Nodes with status `"warming"` pass this rule and continue through all remaining rules; they are not fast-pathed through.

**Rule 2 — Model Available.**  
The model requested by the client (e.g., `"llama-3-8b"`) must appear in the node's `models_loaded` list. A node that does not carry the required model returns reason `"model_missing"`. This matters in a geo-distributed cluster where different nodes may be configured to serve different model variants.

**Rule 3 — KV Cache Memory.**  
The filter checks whether the incoming request's tokens will fit in the node's remaining KV cache capacity. When the node's telemetry includes the `kv_capacity_tokens` field (the total token budget for that node's GPU memory), the check is token-exact:

```
kv_used_tokens = kv_used_frac × kv_capacity_tokens
tokens_needed  = input_tokens + expected_output_tokens

reject if: kv_used_tokens + tokens_needed > kv_capacity_tokens
```

When `kv_capacity_tokens` is not yet available (e.g., during integration testing), the filter falls back to a fraction threshold: reject if `kv_used_frac ≥ kv_cache_max_frac` (default 0.90). In either case, rejection reason is `"memory_full"`.

The token-exact check is strictly tighter than the fraction fallback. A node at 50 % fill with a total capacity of 1 000 tokens will correctly reject a 1 050-token request, whereas the fraction fallback alone would pass it.

**Rule 4 — Power Headroom.**  
The node must have at least `power_headroom_min_kw` (default 2.0 kW) of available power capacity above its current draw. A node below this threshold is at risk of hitting its power cap during the request, which causes thermal throttling and sudden latency spikes. Rejection reason: `"power_limit"`.

**Rule 5 — Temperature.**  
The node's GPU temperature must be strictly below `temperature_limit_c` (default 85 °C). A node at or above this threshold is throttling. Any further requests will see degraded throughput until the node cools down. Rejection reason: `"temperature_high"`.

#### 3.2.3 Warming Node Handling

A node in `"warming"` status is one that has recently restarted or returned from an outage (Scenario S6). The node is functionally available but may be slower than steady state while its caches and JIT compilation warm up.

If the configuration flag `allow_warming_nodes` is `true` (the default), a node that passes all five rules and has status `"warming"` is admitted to the allowed list with the extra flag `_warming=True`. Downstream policies use this flag to apply a soft preference penalty — they still consider the node, but prefer a fully warm node when one is available.

If `allow_warming_nodes` is `false`, warming nodes are rejected with reason `"node_warming"` even if they pass all five rules.

A key design point: warming nodes are **not** exempted from rules 2–5. A warming node that is also out of memory, over temperature, or missing the required model is rejected just as any other node would be. The `_warming` tag is a scheduling hint, not a safety override.

#### 3.2.4 Rule Table

| Rule | Field checked | Threshold (default) | Rejection reason |
|------|--------------|---------------------|-----------------|
| 1 Status | `status` | must be `"up"` or `"warming"` | `node_down` |
| 2 Model | `models_loaded` | requested model present | `model_missing` |
| 3 Memory | `kv_used_frac`, `kv_capacity_tokens` | token fit or frac < 0.90 | `memory_full` |
| 4 Power | `power_headroom_kw` | ≥ 2.0 kW | `power_limit` |
| 5 Temperature | `temperature_c` | < 85 °C | `temperature_high` |

---

### 3.3 Baseline Scheduling Policies

Baseline policies are simple, stateless (or nearly stateless) scheduling rules. Their purpose in this work is threefold:

1. **Lower bound on performance.** A learned policy that does not beat the best baseline does not justify its added complexity.
2. **Ablation anchors.** Each baseline isolates one signal (latency, load, energy cost) so we can understand which signals matter most in which scenarios.
3. **Stress-testing.** Some baselines will perform well in specific scenarios by construction, setting a ceiling for how much improvement is possible in that scenario.

All five (and the optional sixth) baseline policies accept the `allowed` list from the feasibility filter and return a single `node_id`. They are implemented as subclasses of the common `Policy` interface (`stubs/stub_policy.py`) so they are interchangeable with the learned policy in the router.

#### 3.3.1 Round-Robin (RR)

**Mechanism.** Maintains a per-instance counter. On each call, increments the counter and selects `candidates[counter % len(candidates)]`. The counter is local to the instance, so a fresh instance starts at index 0.

**Why it exists.** Round-robin is the canonical load-distribution baseline. It makes no assumptions about node state and distributes requests evenly across whatever candidates the filter passes. It is both simple and well-understood, which makes it a reliable lower bound.

**Expected behavior per scenario.**

| Scenario | Expected behavior |
|----------|------------------|
| S1 Stable | Spreads load evenly. Goodput near the cluster mean. |
| S2 Traffic burst | As feasible nodes fill up and are filtered out, round-robin shrinks its candidate set and continues to distribute. May incur load imbalance if one region fills faster. |
| S3 Price shift | Indifferent to price. Energy cost rises needlessly when cheap nodes are available. |
| S4 Thermal throttle | When the hot node is removed by the filter, round-robin adapts automatically — but only once the node crosses the temperature threshold. |
| S5 Network degradation | Ignores RTT. Will continue to route to the high-latency node, increasing TTFT for requests sent there. |
| S6 Outage + recovery | When the node goes down, the filter removes it; round-robin continues over the remainder. On recovery, the filter re-admits it (with `_warming=True`) and round-robin includes it again. |

**Weakness.** Makes no use of any signal. Identical nodes do not exist in a geo-distributed cluster, so an even distribution is not an optimal distribution. A fast H100 and a slow A100 should not receive equal traffic.

#### 3.3.2 Minimum RTT (MinRTT)

**Mechanism.** For each candidate, looks up the network round-trip time (RTT) to the requesting user's region from the node's `rtt_ms` map. Selects the candidate with the lowest RTT. If the user's region is not found in a node's RTT map, the policy falls back to the average RTT across all regions for that node.

**Why it exists.** Network delay is the dominant component of TTFT for short requests routed across regions. A policy that minimises RTT provides the best case for SLO compliance when compute is not the bottleneck.

**Expected behavior per scenario.**

| Scenario | Expected behavior |
|----------|------------------|
| S1 Stable | Routes requests to the geographically nearest node. Low TTFT, good SLO compliance. |
| S2 Traffic burst | Concentrates traffic on the lowest-RTT node. That node may fill up and be filtered out, at which point MinRTT routes to the next closest. |
| S3 Price shift | Indifferent to price. Will route to cheap nodes only by coincidence. |
| S4 Thermal throttle | RTT is unaffected by thermal state. Will continue routing to the overloaded node until the filter removes it at 85 °C. |
| S5 Network degradation | Reacts immediately. Once the degraded node's RTT rises, MinRTT shifts traffic away from it automatically. This is the scenario MinRTT was designed for. |
| S6 Outage + recovery | Same as round-robin during outage. On recovery, immediately routes to the returned node if it is geographically closest. |

**Weakness.** Ignores queue depth and running requests. Concentrates requests on the nearest node even when it is saturated.

#### 3.3.3 Least Load (LL)

**Mechanism.** For each candidate, computes `queue_len + running` as a proxy for current load. Selects the candidate with the lowest value. Tie-breaking is by order in the candidate list (stable, deterministic).

**Why it exists.** Queue length and running request count are the most direct indicator of whether a node will process the next request quickly. Under steady-state traffic, least-load approximates optimal load balancing without any knowledge of node speed.

**Expected behavior per scenario.**

| Scenario | Expected behavior |
|----------|------------------|
| S1 Stable | Keeps all nodes near equal utilisation. Good general-purpose performance. |
| S2 Traffic burst | Spreads the burst across all nodes. More resilient than MinRTT because it avoids concentrating traffic. Best-performing simple baseline in this scenario. |
| S3 Price shift | Indifferent to price. |
| S4 Thermal throttle | The overheated node is likely the busiest one; least-load may have already been deprioritising it before the filter removes it. |
| S5 Network degradation | Ignores RTT. May route to a high-latency node if it is less loaded. |
| S6 Outage + recovery | Clean removal on outage. On recovery, the returning node has zero load and will receive a burst of traffic until the system rebalances. |

**Weakness.** `queue_len + running` is a count of requests, not a weighted measure of their cost. A mix of short and long requests on one node may look lighter than it is.

#### 3.3.4 Lowest Energy Cost (LE)

**Mechanism.** Selects the candidate with the lowest `energy_price_usd_kwh`. Before sorting by price, the policy excludes any candidate where `queue_len + running ≥ capacity` (node is full). If all candidates are full, the price sort is applied to the full candidate list rather than returning an error.

**Why it exists.** Electricity price varies by region and time of day. NYISO and CAISO publish real-time marginal prices that can change by an order of magnitude across hours. Routing to the cheapest available region reduces operating cost directly. This is the natural baseline for Scenario S3 (price/renewable shift).

**Expected behavior per scenario.**

| Scenario | Expected behavior |
|----------|------------------|
| S1 Stable | Routes to the cheapest region. Operating cost is minimised but latency and load are ignored, leading to concentration on one region. |
| S2 Traffic burst | May flood the cheapest node. The capacity pre-filter prevents routing to a fully saturated node, but does not limit the queue buildup before saturation. |
| S3 Price shift | Immediately shifts routing when the cheapest region changes. This is the scenario LE was designed for. Expected to outperform all other baselines here. |
| S4 Thermal throttle | Indifferent to thermal state until the filter removes the node at 85 °C. |
| S5 Network degradation | Indifferent to RTT. |
| S6 Outage + recovery | On recovery, routes to the returned node if it is cheapest. |

**Weakness.** Ignores all signals except price. Floods the cheapest node regardless of queue depth (until saturation). A cheap node may be cheap because it is a remote region with high RTT.

#### 3.3.5 Static Weighted (SW)

**Mechanism.** Computes a composite score for each candidate by normalising three signals across the current candidate set and combining them with fixed weights:

```
score = w_rtt × norm_rtt + w_load × norm_load + w_price × norm_price
```

where `norm_x` is min-max normalised over the candidates (value 0 = best, 1 = worst). Default weights: `w_rtt = 0.5`, `w_load = 0.3`, `w_price = 0.2`. The candidate with the **lowest** score wins.

All three signals are combined in one pass. If all candidates have the same value for a signal (e.g., all have the same price), normalisation returns 0 for all, and that signal has no effect.

**Why it exists.** The three key optimisation criteria in this work are latency (RTT), throughput (load), and operating cost (price). Static Weighted is the best single-policy heuristic that considers all three simultaneously. It is the natural upper bound for non-adaptive baselines.

**Expected behavior per scenario.**

| Scenario | Expected behavior |
|----------|------------------|
| S1 Stable | Generally strong: routes to nodes that are nearby, lightly loaded, and affordable. Expected to be the best-performing baseline in steady state. |
| S2 Traffic burst | The load signal reacts to the burst; static weights adjust routing toward less-loaded nodes. Performance depends on whether 0.3 weight on load is sufficient. |
| S3 Price shift | Price signal is present at weight 0.2. Will shift some traffic to the newly cheap region but RTT weight means it cannot concentrate traffic as aggressively as LowestEnergy. |
| S4 Thermal throttle | The filter handles removal at 85 °C. Within the filter's window, load signal partially compensates (hot node is usually busy). |
| S5 Network degradation | RTT signal reacts immediately to the degraded node. SW will naturally deprioritise it as its normalised RTT rises. |
| S6 Outage + recovery | Clean removal on outage. On recovery, the returning node has zero load and low normalised scores in a lightly loaded cluster, so it may receive a disproportionate burst. |

**Weakness.** Weights are static. The same `w_rtt = 0.5` applies whether the cluster is latency-bound (S5) or price-sensitive (S3). The optimal weight vector changes with the operating scenario. The sliding-window LinUCB policy learns to adapt these implicit weights from observed rewards.

#### 3.3.6 Power-of-Two Choices (Po2) — Optional Baseline

**Mechanism.** Samples two candidates uniformly at random (without replacement). Selects the one with lower `queue_len + running`. If only one candidate is available, returns it directly.

**Why it exists.** Power-of-Two is a well-known trick from load balancing literature (Mitzenmacher, 2001): sampling just two options and taking the better one achieves 99% of the load balance of optimal random assignment, with no central state. It tests whether the benefit of full load information over a random sample is significant in this cluster.

**Expected behavior.** Similar to Least Load on average, but with higher variance. Because the sample is random, a high-load node may be selected if neither of the two sampled candidates is the least-loaded one. In a small cluster (5–10 nodes), Po2 will sometimes choose the second-best node where LL would always find the best. The gap between LL and Po2 measures the value of observing full cluster state.

---

### 3.4 What Baselines Do Not Do

Each baseline has a structural blindspot that the learned policy is designed to address:

| Baseline | Blindspot |
|----------|-----------|
| Round-Robin | All signals |
| Min RTT | Load, price, thermal state |
| Least Load | RTT, price, request heterogeneity |
| Lowest Energy | RTT, load (until saturation) |
| Static Weighted | Fixed weights cannot adapt to scenario changes |
| Power-of-Two | Stochastic: misses the best node proportional to cluster size |

None of the baselines update their behaviour based on observed outcomes. They do not track TTFT, do not penalise nodes that produced SLO misses, and do not shift weights in response to a change event. This is the gap that the sliding-window LinUCB policy fills.

---

### 3.5 Integration with the Filter

All baseline policies receive the output of the feasibility filter, not the raw node list. They never need to check status, model availability, memory, power, or temperature — those checks are already done. If the filter returns an empty allowed list, the request is rejected before any policy is called.

The only filter-aware behaviour in the policies is the `_warming=True` tag. The Static Weighted policy and LinUCB both check this flag and can apply a load penalty to warming nodes. Round-Robin, MinRTT, LeastLoad, and LowestEnergy treat warming nodes identically to fully up nodes.

---

### 3.6 Test Coverage

The edge-case test suite (`edge_case_tests/test_filter_edge_cases.py`) covers six categories with 27 tests:

| Test class | Tests | What is verified |
|-----------|-------|-----------------|
| `TestAllNodesTooHot` | 4 | All 4 nodes rejected; empty allowed list does not crash; reasons are `temperature_high` |
| `TestOnlyOneNodeFeasible` | 5 | Correct node returned; 3 rejected with correct reasons; all 6 baselines handle single-candidate input without error |
| `TestWarmingNode` | 5 | Warming node admitted with `_warming=True`; healthy node not tagged; warming rejected when flag is off |
| `TestWarmingNodeFailsSafetyRules` | 5 | Warming nodes with wrong model, full memory, low power, or high temperature are still rejected |
| `TestLooseStatusValues` | 5 | `"DOWN"`, `"offline"`, `"draining"`, missing status all rejected; `"up"` passes |
| `TestTokenAwareMemoryCheck` | 3 | Token-exact check rejects oversized request; fits if capacity allows; fallback fraction check works when field is absent |

All 27 tests pass under `pytest`.

---

### 3.7 Summary

The feasibility filter and five baseline policies form Jyotir's contribution to the evaluation framework. The filter enforces hard physical constraints before any policy sees the candidate list, ensuring fair and safe comparison. The baselines span the space of simple one-signal and multi-signal heuristics, from fully stateless (Round-Robin) to partially adaptive (Static Weighted). Their performance across scenarios S1–S6 provides the lower bound against which the adaptive sliding-window LinUCB policy is evaluated.
