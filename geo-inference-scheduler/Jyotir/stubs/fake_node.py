# Stub for Parikshit's telemetry schema (v1).
# Replace this with real telemetry snapshots once Parikshit finalises the schema.
# Field names here are our best guess — confirm with Parikshit and update if any name changes.

# One fake node snapshot — mirrors what the real simulator will report each tick.
FAKE_NODE_SINGLE = {
    "schema_version": "1.0",
    "node_id": "us-east-1",
    "status": "up",                        # "up" | "down" | "warming"
    "models_loaded": ["llama-3-8b"],
    "kv_used_frac": 0.68,                  # 0.0 = empty, 1.0 = full
    "power_headroom_kw": 4.5,
    "temperature_c": 71.0,
    "queue_len": 7,
    "running": 22,
    "capacity": 32,                        # max concurrent requests
    "rtt_ms": {"nyc": 12, "chi": 25, "sfo": 70},
    "energy_price_usd_kwh": 0.11,
    "gpu_price_usd_hr": 2.40,
}

# A cluster of fake nodes — used to test the filter across multiple candidates.
FAKE_CLUSTER = [
    {
        "schema_version": "1.0",
        "node_id": "us-east-1",
        "status": "up",
        "models_loaded": ["llama-3-8b"],
        "kv_used_frac": 0.68,
        "power_headroom_kw": 4.5,
        "temperature_c": 71.0,
        "queue_len": 7,
        "running": 22,
        "capacity": 32,
        "rtt_ms": {"nyc": 12, "chi": 25, "sfo": 70},
        "energy_price_usd_kwh": 0.11,
        "gpu_price_usd_hr": 2.40,
    },
    {
        "schema_version": "1.0",
        "node_id": "us-central-1",
        "status": "up",
        "models_loaded": ["llama-3-8b", "llama-3-70b"],
        "kv_used_frac": 0.30,
        "power_headroom_kw": 8.0,
        "temperature_c": 60.0,
        "queue_len": 2,
        "running": 10,
        "capacity": 32,
        "rtt_ms": {"nyc": 25, "chi": 10, "sfo": 45},
        "energy_price_usd_kwh": 0.09,
        "gpu_price_usd_hr": 2.10,
    },
    {
        "schema_version": "1.0",
        "node_id": "us-west-1",
        "status": "warming",               # recovering from outage — filter may penalise this
        "models_loaded": ["llama-3-8b"],
        "kv_used_frac": 0.10,
        "power_headroom_kw": 10.0,
        "temperature_c": 55.0,
        "queue_len": 0,
        "running": 2,
        "capacity": 32,
        "rtt_ms": {"nyc": 70, "chi": 50, "sfo": 8},
        "energy_price_usd_kwh": 0.14,
        "gpu_price_usd_hr": 2.60,
    },
    {
        "schema_version": "1.0",
        "node_id": "eu-west-1",
        "status": "up",
        "models_loaded": ["llama-3-70b"],  # does NOT have llama-3-8b → fails model check
        "kv_used_frac": 0.50,
        "power_headroom_kw": 3.0,
        "temperature_c": 88.0,             # over temperature limit → fails thermal check
        "queue_len": 15,
        "running": 30,
        "capacity": 32,
        "rtt_ms": {"nyc": 90, "chi": 95, "sfo": 120},
        "energy_price_usd_kwh": 0.20,
        "gpu_price_usd_hr": 3.00,
    },
    {
        "schema_version": "1.0",
        "node_id": "ap-south-1",
        "status": "down",                  # node is down → fails status check
        "models_loaded": ["llama-3-8b"],
        "kv_used_frac": 0.00,
        "power_headroom_kw": 0.0,
        "temperature_c": 40.0,
        "queue_len": 0,
        "running": 0,
        "capacity": 32,
        "rtt_ms": {"nyc": 200, "chi": 210, "sfo": 180},
        "energy_price_usd_kwh": 0.08,
        "gpu_price_usd_hr": 1.80,
    },
]

# A fake incoming request — mirrors what the router will pass to the filter.
FAKE_REQUEST = {
    "request_id": "r-000001",
    "model": "llama-3-8b",
    "input_tokens": 850,
    "expected_output_tokens": 200,
    "slo_class": "interactive",
    "slo_ms": 250,
    "user_region": "nyc",
}
