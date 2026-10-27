# Sur / context_vector

**Owner:** Sur. **Used by:** the LinUCB policies (`linucb/`, `sliding_window_linucb/`).

`features.py` turns one (request, candidate node) pair into the numbers LinUCB scores. The policy builds one vector per candidate.

| # | Feature | From | Scaling (to 0..1) |
|---|---|---|---|
| 1 | `bias` | always 1.0 | — |
| 2 | `input_tokens` | request | min-max with configured range, clipped |
| 3 | `expected_output_tokens` | request | min-max, clipped |
| 4–5 | `slo_class=interactive`, `slo_class=batch` | request `slo_class` | 0/1 flag per configured class |
| 6 | `ttft_slo_ms` | request `ttft_slo_ms` (or `slo_ms`) | min-max, clipped |
| 7 | `rtt_ms` | node `rtt_ms[request.user_region]` | min-max, clipped |
| 8 | `queue_len` | node | min-max, clipped |
| 9 | `running_frac` | node `running / capacity` | clipped |
| 10 | `kv_used_frac` | node | clipped |
| 11 | `energy_price_usd_kwh` | node | min-max, clipped |
| 12 | `gpu_price_usd_hr` | node | min-max, clipped |
| 13 | `temperature_c` | node | min-max, clipped |
| 14 | `warming` | node `status == "warming"` or the filter's `_warming` tag | 0/1 |

These are the brief's §6.2 features: request size, class, SLO, node delay, queue, running requests, memory, prices, temperature and the warming flag. `bias` is the usual intercept, so each node's model can learn its own base level. The ranges and class list are in `configs/policies/*.yaml`; none are in the code.

**"No context" ablation:** with `features.use_context: false` the vector is just `[1.0]`, which makes the policy a plain non-contextual bandit (`configs/policies/sw_linucb_no_context.yaml`).

**Robustness:**
- A missing field raises `KeyError` naming the field, and a NaN, infinite or negative count raises `ValueError`. A renamed telemetry field therefore fails on the first request instead of silently feeding the policy wrong numbers.
- If the user's region is unknown, the RTT falls back to the node's average, the same rule Jyotir's MinRTT baseline uses. A node with no RTT data gets the worst value.
- Requests and nodes may be dicts (as today) or objects (if Krupesh's `NodeState` becomes a dataclass).

```python
from context_vector import ContextBuilder

builder = ContextBuilder(config["features"])  # once
x = builder.build(request, node)  # numpy array, len(builder.names)
```

Tests: `tests/test_features.py`.
