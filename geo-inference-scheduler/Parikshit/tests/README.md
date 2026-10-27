# Parikshit / tests

**Owner:** Parikshit. These are unit and integration tests for every module in Parikshit's folder; the repo rule says every module needs at least one test.

Run from the repository root:

```bash
python3 -m pytest geo-inference-scheduler/Parikshit/tests -q
```

| File | Covers |
|---|---|
| `test_latency_model.py` | the brief's prefill / decode / TTFT / total formulas, and the thermal and warm-up slowdowns |
| `test_calibration.py` | KV bytes per token, the least-squares fits, the scaling between GPUs, capacity, and that `simulator/NUMBERS.md` shows the current calibration |
| `test_telemetry.py` | the JSON Schema; bad records; the Python validator against `jsonschema` on random records; every tick of every scenario; Krupesh's validator |
| `test_workload.py` | reproducible requests, rates, class and region shares, real token pairs, the output-length error, S2's burst keeping every S1 request |
| `test_configs.py` | every config refers to existing data, the 10-node setup extends the 5-node one, bad values and bad scenarios are refused, S3 flips the cheapest region |
| `test_events.py` | each kind of scenario change on its node, its log record, and the change times (t0, the S6 return) |
| `test_node.py` | one node: timing, FIFO queue, KV-cache admission, load slowdown, outage, warm-up, temperature, power, energy and cost |
| `test_cluster.py` | whole runs of the six scenarios: one outcome per request, reproducibility (also across processes), and what each scenario changes |
| `test_router_integration.py` | Krupesh's real router, in-process and over HTTP (identical decisions), Sur's policy, `true_state_violation` |
| `test_scenario_effects.py` | the report's scenario table: its time windows, its shares and each change's description |
| `test_run_scenario.py` | the run command: its summary, the policy's counters, a reward disagreement, the files it writes and its exit codes |
| `test_data_sources.py` | the download and preprocessing code on tiny inputs, the committed files against their manifest, and a byte-for-byte rebuild from the raw downloads (skipped if they are not downloaded) |

Shared helpers are in `helpers.py`:
- `short_scenario`: the shipped scenarios with every time × 0.2;
- `light_workload`: 20 requests/s;
- `PinRouter`: a router that sends everything to one node.
