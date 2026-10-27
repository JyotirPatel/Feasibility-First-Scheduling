# Parikshit / simulator

**Owner:** Parikshit. **Used by:**
- Krupesh's router, which the simulator drives;
- Riya's experiment runner, one run per (scenario, policy, seed);
- Sur's window sweep.

This is a discrete-event simulator (SimPy) of 5 or 10 geo-distributed inference nodes (brief §5).

| File | What it is |
|---|---|
| `config.py` | Pydantic models for every config file; nothing numeric is fixed in the code |
| `data.py` | reads the processed real data in `../data/processed/` |
| `calibration.py` | fits the latency constants per GPU type; `python3 simulator/calibration.py` prints them |
| `latency_model.py` | the brief's formulas: prefill, decode, TTFT, total; thermal and warm-up slowdowns |
| `workload.py` | builds every request of a run from the Azure traces and a seed |
| `node.py` | one node: queue, slots, KV cache, power, temperature, prices, up / down / warming |
| `events.py` | applies the scenario changes of `../event_traces/` |
| `cluster.py` | `Simulation`: the SimPy run that drives a router |
| `routers.py` | `KrupeshRouter` (his engine or his HTTP client), `LocalRouter` (Jyotir's filter + least load), and `true_state_problems` |
| `run_scenario.py` | CLI: one scenario through Krupesh's router, with the decision log and a summary |
| `scenario_effects.py` | CLI: runs all six scenarios and prints what each change measurably did (the report's scenario table) |
| `NUMBERS.md` | how every number is produced: data, spec, fit or assumption |

## How a run works

1. **Before the run.** `workload.generate` builds all requests from the seed, so every policy gets exactly the same requests.
2. **Every tick (1 s).** Every node reports one telemetry record (schema v1), checked against the schema, and the simulator calls `router.ingest_telemetry(records)`.
3. **Every arrival.** The simulator calls `router.route(request)` and gets `(decision, node_id)`.
   - It then calls `router.after_route(request, node_id, true_record)` if the router has it.
   - The request then joins that node's queue.
   - A node starts a queued request when a slot is free and its input + output tokens fit in the KV cache.
4. **Timing.** When a request starts, its times are fixed:
   - TTFT = RTT + queue wait + prefill;
   - total = TTFT + decode;
   - decode is slower when the node is busier, and both phases are slower when the node is hot or warming.
5. **Feedback.** It calls `router.feedback(outcome)` when the last token reaches the user (t_arrival + total). A request lost in an outage is reported at once, with `failed=True`.
6. **Order and the end.** A scenario change at time t (an event, or the end of a warm-up) comes before the tick and any arrival at t, also when changes fall between ticks. Arrivals stop at the end of the run; requests still in flight are served to completion, so every routed request gets exactly one outcome (checked).

```python
from simulator.cluster import Simulation
from simulator.routers import KrupeshRouter, krupesh_engine

engine, reward = krupesh_engine("sur:sw_linucb", seed=0, scenario="s4_thermal_throttle")
summary = Simulation(KrupeshRouter(engine), "s4_thermal_throttle", seed=0).run()
engine.finish()
log = engine.writer.close()  # Krupesh's decision log (brief §10.3)
```

Tests:
- `../tests/test_latency_model.py`, `test_node.py`, `test_workload.py`, `test_cluster.py`, `test_calibration.py`;
- `test_router_integration.py` (with Krupesh's real router).
