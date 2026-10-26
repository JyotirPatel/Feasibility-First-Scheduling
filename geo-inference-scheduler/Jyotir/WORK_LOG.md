# Jyotir — Work Log

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Big Data Systems, Algorithms and Networks · Fall 2026 · Group 20
**Role:** Feasibility Filter + Static Baselines

---

## What This Folder Contains

```
Jyotir/
├── WORK_LOG.md                          ← this file
├── README.md                            ← role overview and dependencies
│
├── stubs/                               ← temporary placeholders (delete after merge)
│   ├── fake_node.py                     ← fake node snapshots (stand-in for Parikshit's simulator)
│   ├── stub_policy.py                   ← placeholder Policy base class (stand-in for Krupesh's interface)
│   └── README.md                        ← explains what each stub replaces and how to swap it out
│
├── feasibility_filter/
│   ├── __init__.py                      ← exports feasibility_filter and load_config
│   ├── filter.py                        ← the main filter (5 rules, returns allowed + rejected)
│   └── configs/
│       └── feasibility.yaml             ← all thresholds live here, never in code
│
├── baselines/
│   ├── __init__.py                      ← exports all 6 baseline classes
│   ├── round_robin.py                   ← Baseline 1: rotate through nodes in order
│   ├── min_rtt.py                       ← Baseline 2: pick closest node (lowest RTT)
│   ├── least_load.py                    ← Baseline 3: pick node with shortest queue
│   ├── lowest_energy.py                 ← Baseline 4: pick cheapest electricity node
│   ├── static_weighted.py               ← Baseline 5: fixed formula (RTT + load + price)
│   └── power_of_two.py                  ← Baseline 6 (optional): pick better of 2 random nodes
│
└── edge_case_tests/
    ├── __init__.py
    └── test_filter_edge_cases.py        ← 14 tests across 3 edge cases (all pass)
```

---

## What Was Built and Why — Start to End

### Step 1 — Stubs (independent development setup)
**Files:** `stubs/fake_node.py`, `stubs/stub_policy.py`, `stubs/README.md`

Before writing any real code, two stub files were created so the filter and baselines could be built and tested without waiting for teammates.

- `fake_node.py` gives a fake cluster of 5 nodes covering every interesting case: a normal node, a warming node (recovering from outage), an overheated node, a node with the wrong model loaded, and a node that is down. The filter is tested against these until Parikshit's real simulator is ready.
- `stub_policy.py` defines the `Policy` base class and `Outcome` datatype with the same method signatures Krupesh will use. All baselines inherit from this. When Krupesh publishes the real base class, each baseline file changes one import line and nothing else.

**How to swap stubs out when real code arrives:**
- Replace `from stubs.fake_node import ...` with real telemetry from Parikshit's simulator.
- Replace `from stubs.stub_policy import Policy, Outcome` with `from src.geosched.policies.base import Policy, Outcome`.

---

### Step 2 — Feasibility Filter
**Files:** `feasibility_filter/filter.py`, `feasibility_filter/configs/feasibility.yaml`, `feasibility_filter/__init__.py`

The filter is the first thing the router calls on every request. It checks each node against 5 rules in order and removes any node that fails. Only safe, capable nodes reach the learning algorithm.

**The 5 rules (in order, fail-fast):**

| # | Rule | Field checked | Fails when |
|---|---|---|---|
| 1 | Status | `status` | node is `"down"` or `"warming"` |
| 2 | Model available | `models_loaded` | requested model not in list |
| 3 | KV cache (memory) | `kv_used_frac` | usage >= `kv_cache_max_frac` in config |
| 4 | Power headroom | `power_headroom_kw` | headroom < `power_headroom_min_kw` in config |
| 5 | Temperature | `temperature_c` | temp >= `temperature_limit_c` in config |

**Warming nodes are a special case:**
- If `allow_warming_nodes: true` in the config → node is allowed but tagged with `_warming=True` so the policy can apply a penalty.
- If `allow_warming_nodes: false` → node is rejected with reason `"node_warming"`.

**What the filter returns:**
```python
allowed, rejected = feasibility_filter(request, nodes, config)
# allowed  → list of node dicts that passed (warming nodes carry _warming=True)
# rejected → list of {"node_id": str, "reason": str} for every removed node
```

**If allowed is empty** → the router rejects the request entirely with reason `"no_feasible_node"`. The filter returns an empty list; it never makes the rejection call itself.

**Config file (`feasibility.yaml`):**
```yaml
temperature_limit_c: 85.0
power_headroom_min_kw: 2.0
kv_cache_max_frac: 0.90
allow_warming_nodes: true
```
All threshold values live here. Changing a threshold is a one-line YAML edit — no Python changes, no redeployment.

---

### Step 3 — Baseline Policies
**Files:** `baselines/round_robin.py`, `baselines/min_rtt.py`, `baselines/least_load.py`, `baselines/lowest_energy.py`, `baselines/static_weighted.py`, `baselines/power_of_two.py`

Five (plus one optional) simple policies that the learning algorithm (LinUCB) must outperform. All inherit from `stub_policy.Policy` and implement the same two methods:
- `choose(request, candidates) → node_id`
- `update(request, node_id, outcome) → None` (baselines ignore this — they do not learn)

All baselines receive an **already-filtered** candidate list from the router. The router calls the feasibility filter first, then passes the result to the policy. This means the only difference between a baseline and LinUCB is the choosing step — the comparison is fair.

| File | Strategy | Weakness |
|---|---|---|
| `round_robin.py` | Rotate through nodes in order | Ignores everything — load, latency, cost |
| `min_rtt.py` | Pick node with lowest RTT to user's region | Ignores load and cost; keeps sending to a degrading node |
| `least_load.py` | Pick node with fewest queue + running requests | Ignores RTT and cost |
| `lowest_energy.py` | Pick node with cheapest electricity price | Ignores latency; overloads the cheap node |
| `static_weighted.py` | Score = w_rtt×RTT + w_load×load + w_price×price (min-max normalised) | Weights are fixed — cannot adapt when conditions change |
| `power_of_two.py` | Pick 2 random nodes, send to less busy one (optional) | Ignores RTT and cost; random sampling |

**Static weighted formula:**
All three factors are min-max normalised across the current candidate set before weighting, so the weights (default: RTT=0.5, load=0.3, price=0.2) are directly comparable regardless of units. If all candidates have the same value for a factor, that factor contributes 0 — the policy adapts naturally to a homogeneous cluster.

---

### Step 4 — Edge Case Tests
**File:** `edge_case_tests/test_filter_edge_cases.py`

14 tests across 3 edge cases. All pass.

**Edge Case 1 — All nodes are too hot (4 tests)**
- Confirms `allowed` list is empty
- Confirms every node appears in `rejected`
- Confirms reason is `"temperature_high"` for each
- Confirms filter does not crash or raise on empty result

**Edge Case 2 — Only one node passes (5 tests)**
- Confirms exactly one node in `allowed` and it is the correct one
- Confirms 3 nodes in `rejected` with correct reasons: `"node_down"`, `"temperature_high"`, `"memory_full"`
- Confirms all 6 baseline classes handle a single-candidate list without crashing

**Edge Case 3 — Node is warming up after outage (5 tests)**
- Confirms warming node is in `allowed` when `allow_warming_nodes=True`
- Confirms warming node carries `_warming=True` tag
- Confirms healthy node does not carry `_warming` tag
- Confirms warming node is rejected when `allow_warming_nodes=False`
- Confirms rejection reason is `"node_warming"`

**Run the tests:**
```bash
cd geo-inference-scheduler/Jyotir
pytest edge_case_tests/test_filter_edge_cases.py -v
```

---

## How to Use the Filter and Baselines Together

```python
from feasibility_filter import feasibility_filter, load_config
from baselines import RoundRobin, MinRTT, LeastLoad, LowestEnergy, StaticWeighted

config = load_config()

# Step 1 — filter
allowed, rejected = feasibility_filter(request, all_nodes, config)

if not allowed:
    return {"decision": "reject", "reason": "no_feasible_node"}

# Step 2 — choose (swap the policy class to run a different baseline)
policy = StaticWeighted()
chosen_node_id = policy.choose(request, allowed)
```

---

## What Still Needs to Happen (Next Steps)

| Task | Depends on | Target |
|---|---|---|
| Replace `fake_node.py` with real telemetry snapshots | Parikshit finalising telemetry schema v1 | Week 2 |
| Replace `stub_policy.py` with Krupesh's real Policy class | Krupesh publishing the interface | Week 2 |
| Run all baselines on all 6 event traces and save decision logs | Parikshit finishing all 6 trace files | Week 3 |
| Hand baseline logs to Riya for experiment figures | All 6 traces done | Week 3 |
