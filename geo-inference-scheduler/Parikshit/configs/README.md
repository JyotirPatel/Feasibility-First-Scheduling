# Parikshit / configs

**Owner:** Parikshit. Every number the simulator uses is in these files (brief §13: none in the Python code). `simulator/config.py` checks each file when it is loaded: unknown keys, missing keys and impossible values are refused.

| File | What it sets |
|---|---|
| `calibration.yaml` | the model (Llama-3-8B), the GPU specs (H100, A100), the published benchmark the latency model is fitted to, and the serving assumptions |
| `nodes_5.yaml` | the 5-node setup: sites, GPU type, telemetry tick, price hour, power and thermal behaviour |
| `nodes_10.yaml` | the 10-node setup: the 5 nodes plus 5 more, otherwise identical (a test checks this) |
| `workload.yaml` | arrival rate, request classes and their SLOs, the router's output-length error, user regions |

The six scenarios are in `../event_traces/`. Every value and its source: `../simulator/NUMBERS.md`.
