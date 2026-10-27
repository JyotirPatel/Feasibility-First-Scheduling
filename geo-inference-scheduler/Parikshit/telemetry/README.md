# Parikshit / telemetry

**Owner:** Parikshit. **Used by:**
- Krupesh's router, which checks records at its `/telemetry` boundary;
- Jyotir's feasibility filter;
- Sur's context vector.

This is the telemetry contract (Project Brief §10.1, frozen v1): what every node reports once per simulation tick (1 s).

| File | What it is |
|---|---|
| `telemetry_schema_v1.json` | the schema, as JSON Schema (draft 2020-12) |
| `schema.py` | `validate_record(record)`: the same rules in plain Python, plus two that JSON Schema cannot express |

## Fields

| Field | Type | Unit / values | Read by |
|---|---|---|---|
| `schema_version` | string | `"1.x"`; the router rejects other major versions | router |
| `t` | number ≥ 0 | simulation time, s | router (telemetry age) |
| `node_id` | string | e.g. `us-east-nyc` | all |
| `status` | `up` \| `down` \| `warming` | `warming`: back after an outage, serving but slower | filter, context vector |
| `rtt_ms` | {region: number ≥ 0} | ms, round trip from each user region | min-RTT, static-weighted, context vector |
| `queue_len` | integer ≥ 0 | requests waiting for a slot | least-load, power-of-two, context vector |
| `running` | integer, 0 … capacity | requests being served | least-load, context vector |
| `capacity` | integer ≥ 1 | maximum requests served at once | context vector |
| `kv_used_frac` | number 0 … 1 | share of KV-cache memory in use | filter (memory), context vector |
| `models_loaded` | list of distinct strings | e.g. `["llama-3-8b"]` | filter (model) |
| `power_headroom_kw` | number ≥ 0 | kW below the site limit; 0 when down | filter (power) |
| `temperature_c` | number −50 … 150 | GPU temperature, °C | filter, reward (thermal term) |
| `energy_price_usd_kwh` | number ≥ 0 | electricity price now, $/kWh | lowest-energy, static-weighted, reward |
| `gpu_price_usd_hr` | number ≥ 0 | rent of one GPU, $/hour | context vector, cost |
| `kv_capacity_tokens` | integer ≥ 1 or null | *optional v1.0 extension*: KV-cache size in tokens, so the filter can check that a request fits (Krupesh's F2) | filter |

Two more rules are checked by `validate_record` only:
- `running` ≤ `capacity`;
- a `down` node has no running or queued requests and no KV cache in use.

`validate_record` also refuses a boolean where a number is expected, and a float such as `7.0` where an integer is expected, as Krupesh's router does.

**Changing the schema:**
- A 1.x version may add optional fields.
- Renaming or removing a field needs version 2 and a message to the whole group (work distribution §5).

Tests: `tests/test_telemetry.py`. It checks the following:
- the brief's example record is valid;
- `validate_record` agrees with the `jsonschema` package on 4,000 random records;
- every record of every scenario passes both, and also Krupesh's `validate_telemetry`, unchanged through his `NodeState` type.
