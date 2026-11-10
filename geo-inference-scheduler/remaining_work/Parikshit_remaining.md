# Remaining Work — Parikshit
**AMS 560 · Group 20 · Fall 2026**
**Professor's remark:** *"Prioritize resolving integration issues and completing end-to-end comparisons."*

---

## Status Summary
Simulator, telemetry schema, all 6 scenario traces, 122 tests, and `KrupeshRouter` integration bridge are complete. One crash-on-edge-case bug needs fixing before the final 420-run grid. One optional calibration discussion flagged by Sur.

---

## 1. Completed

| Deliverable | Notes |
|---|---|
| SimPy discrete-event simulator | 5 GPU nodes (2 H100, 3 A100); queue, KV cache, power, temperature, RTT modelled |
| Latency model | Calibrated to published H100/A100 benchmarks; `NUMBERS.md` documents every constant |
| Data loaders | Azure LLM traces, NYISO/CAISO electricity prices, inter-city ping data |
| 6 event traces (S1–S6) | `event_traces/s1_stable.yaml` through `s6_outage_recovery.yaml`; all used in Sur's sweep |
| Telemetry schema v1 | `telemetry_schema_v1.json`; `kv_capacity_tokens` field present and used by Jyotir's filter |
| `KrupeshRouter` bridge | `simulator/routers.py`; wraps Krupesh's engine and writes `true_state_violation` per request |
| `LocalRouter` | Jyotir's filter + least-load for standalone tests |
| `true_state_problems()` | Checks the chosen node's true state at decision time against Jyotir's hard rules |
| 122 tests | All pass |
| Simulator section of report | Drafted in `report/simulator_section.md` |
| 10-node config | `configs/nodes_10.yaml` available as an alternative to the 5-node default |

---

## 2. Bug to Fix (crash on edge case)

### `node.py` raises `ValueError` instead of calling `on_outcome` on KV overflow
**File:** `simulator/node.py`, line 178–179
```python
if job.kv_tokens > self.kv_capacity:
    raise ValueError(f"{job.request['request_id']} needs more KV cache than {self.node_id} has")
```
If a request somehow passes the filter but arrives with more tokens than the node's total KV capacity (possible if telemetry was stale when the filter ran), the simulator **crashes the entire run** with an uncaught `ValueError` instead of recording a graceful failure. All results for that run are lost.

**Fix:** Call the failure callback instead:
```python
if job.kv_tokens > self.kv_capacity:
    self.on_outcome(self._failure(job, self.env.now))
    return
```
This matches how the `go_down()` path already handles abrupt failures.

**Priority: High** — this would crash Riya's 420-run grid if any run hits the edge case.

---

## 3. Optional / Team Decisions

### S2 burst intensity (Sur RESULTS.md finding 5)
Sur's sweep notes that at 80 req/s, the 3× burst (240 req/s) stays below the cluster's maximum throughput. An even spread of requests absorbs the burst, so learned and simple policies do not separate much during the burst itself — only over the full run.

**Option:** Raise the base rate to, say, 120 req/s so that the 3× burst (360 req/s) cannot be absorbed by an even spread. This would better stress-test the adaptive policy's advantage. This is a **team decision** before the final run; changing it means Sur's sweep is no longer a direct comparison (sweep used 80 req/s).

### Telemetry tick interval
Sur's sweep found ~3,200 true-state violations per S2 run with the per-node W=500 policy, all caused by requests reaching nodes that crossed the power limit in the last 1 second. Reducing the tick from 1 s to 0.5 s is straightforward in the simulator config and would halve this number. Coordinate with Krupesh (see Krupesh's remaining work, Bug B).

---

## 4. After Bug Fix: What Parikshit's Output Feeds

Once `node.py` is fixed:
- Riya's `run_evaluation.py` can run the full grid without risk of a mid-run crash.
- Sur can optionally re-run the window sweep against the patched simulator to confirm numbers are stable.
- The `true_state_violation` column in the decision log remains Parikshit's independent safety audit.
