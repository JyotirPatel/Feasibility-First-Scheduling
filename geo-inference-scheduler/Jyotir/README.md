# Jyotir — Feasibility Filter + Static Baselines

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Big Data Systems, Algorithms and Networks · Fall 2026 · Group 20

---

## Role

Jyotir owns the hard safety rules that remove unsafe nodes before any choice is made, and all simple baseline policies that the adaptive policy is compared against.

---

## Assigned Work

### 1. Feasibility Filter (`feasibility_filter/`)
A node is allowed for a request **only if all of the following are true:**

| Rule | Check |
|---|---|
| Model available | The requested model is loaded on the node |
| Memory | KV cache has room for this request (input + expected output tokens) |
| Power | Power headroom is above the configured safety limit |
| Temperature | Temperature is below the configured safety limit |
| Status | Node is up (a warming node may be allowed with a penalty; default: allowed) |

**Key design rules:**
- All limits live in `configs/feasibility.yaml` — never hard-coded in Python.
- Every removed node gets a reason string in the response.
- If no node passes, the request is **rejected on purpose** with reason `"no feasible node"`. The policy never overrides the filter to save cost.

### 2. Static Baseline Policies (`baselines/`)
Five (or six) simple policies that all pass through the same feasibility filter (so comparisons are fair — only the choosing step differs):

| Policy | Rule |
|---|---|
| Round-robin | Take feasible nodes in turn |
| Min RTT | Closest node (lowest network delay) |
| Least load | Fewest waiting + running requests |
| Lowest energy | Cheapest node for energy cost |
| Static weighted | Fixed hand-set formula mixing delay, load, and price |
| Power of two (optional) | Pick 2 random feasible nodes; send to the less busy one |

### 3. Baseline Runs (`baselines/`)
Run all baselines on all six change-event traces (S1–S6) and save the decision logs. These are the comparison numbers Riya uses for every figure.

### 4. Edge Case Tests (`edge_case_tests/`)
Test the filter under corner cases:
- All nodes are too hot → expect full rejection
- Only one node is feasible → expect that node to be chosen every time
- Node is in the warming-up state after an outage → confirm the warming penalty logic

---

## Deliverables

| Deliverable | Where it lives |
|---|---|
| Feasibility filter module + unit tests | `feasibility_filter/` |
| 5 (or 6) baseline policy implementations | `baselines/` |
| Baseline decision log on all 6 event traces | `baselines/` |
| Rule / threshold table (for the report) | `feasibility_filter/` |
| Edge case test suite | `edge_case_tests/` |

---

## What You Need From Others Before You Can Build

### From Parikshit — Telemetry Schema v1
**Specific deliverable:** `telemetry/telemetry_schema_v1.json` — the versioned list of fields each node reports (kv_used_frac, models_loaded, power_headroom_kw, temperature_c, status, etc.).
**Why you need it first:** Every feasibility rule reads a specific field from the node's telemetry snapshot. Without knowing the exact field names and their units (e.g., is temperature in Celsius or Kelvin? is power headroom in kW or a fraction?), you cannot write a correct filter — you would be guessing field names that may change. Freeze the schema, then write the rules against it.
**Due:** End of Week 1.

### From Krupesh — Policy Interface (`Policy` base class)
**Specific deliverable:** The `Policy` base class definition with `choose(request, candidates) → node_id` and `update(request, node_id, outcome) → None`.
**Why you need it first:** Each of your five baseline policies must implement this interface so they are interchangeable with Sur's LinUCB in experiments. Without seeing the exact method signatures — especially what `candidates` contains (a list of NodeState? a list of node IDs?) and what `outcome` looks like — you cannot write the baseline classes in a compatible way.
**Due:** End of Week 1.

---

## What You Provide to Others

| Deliverable you hand over | Who receives it | When |
|---|---|---|
| Feasibility filter module (`filter.py` + interface stub) | Krupesh (router calls it on every request), Sur (policy only sees nodes that passed the filter) | End of Week 1 (stub), End of Week 2 (full rules) |
| 5 (or 6) baseline policy implementations | Krupesh (plugs into router for baseline runs) | End of Week 2 |
| Baseline decision log on all 6 event traces | Riya — every figure compares adaptive policy against these baseline numbers | End of Week 3 |
| Rule / threshold table | Riya — included verbatim in the Feasibility section of the report | End of Week 3 |

---

## Report / Presentation Section

Feasibility and Baselines section — describes each rule, the threshold table, and the rejection path. Includes a slide on the filter and the rejection flow.
