# Jyotir / stubs

This folder holds **temporary placeholder files** that let you build and test the filter and baselines independently, without waiting for Parikshit and Krupesh to finish their parts.

---

## Files

### `fake_node.py` — stands in for Parikshit's telemetry schema
Parikshit will eventually provide real node snapshots from the simulator. Until then, this file gives you:
- `FAKE_NODE_SINGLE` — one node to test a single filter rule
- `FAKE_CLUSTER` — five nodes that cover all interesting cases (normal, warming, overheated, wrong model, down)
- `FAKE_REQUEST` — a fake incoming request to pass alongside the node list

**How to use it in your filter tests:**
```python
from stubs.fake_node import FAKE_CLUSTER, FAKE_REQUEST
allowed, reasons = feasibility_filter(FAKE_REQUEST, FAKE_CLUSTER)
```

**When to replace it:**
Once Parikshit shares `telemetry_schema_v1.json`, check if any field names differ from the ones here (e.g. `temperature_c`, `kv_used_frac`, `power_headroom_kw`). Fix those names in your filter — the stub file itself can then be deleted.

---

### `stub_policy.py` — stands in for Krupesh's Policy base class
Krupesh will provide the real `Policy` base class and `Outcome` dataclass as part of the router service. Until then, this file defines the same interface so your baselines can inherit from it now.

**How to use it in your baseline files:**
```python
from stubs.stub_policy import Policy, Outcome

class RoundRobin(Policy):
    def choose(self, request, candidates):
        ...
```

**When to replace it:**
Once Krupesh publishes the real base class, change the import in each baseline file from:
```python
from stubs.stub_policy import Policy, Outcome
```
to:
```python
from src.geosched.policies.base import Policy, Outcome
```
Nothing else in your baseline code needs to change.

---

## What to tell your teammates

**Tell Parikshit:** "I'm assuming these field names in the node snapshot — `node_id`, `status`, `models_loaded`, `kv_used_frac`, `power_headroom_kw`, `temperature_c`, `queue_len`, `running`, `capacity`, `rtt_ms`, `energy_price_usd_kwh`, `gpu_price_usd_hr`. Let me know if any name is different."

**Tell Krupesh:** "I'm assuming `choose(request, candidates) → str` and `update(request, node_id, outcome) → None` as the Policy interface, and `Outcome` has fields `ttft_ms`, `e2e_ms`, `slo_met`, `energy_kwh`, `cost_usd`, `reward`. Confirm or correct."

Once both confirm, you are safe to build everything in `feasibility_filter/` and `baselines/` independently.
