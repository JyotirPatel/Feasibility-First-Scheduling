"""Small builders for requests, nodes and outcomes used across Sur's tests."""

import os

import yaml

SUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_CONFIG_DIR = os.path.join(SUR_DIR, "configs", "policies")


def load_yaml(name: str) -> dict:
    with open(os.path.join(POLICY_CONFIG_DIR, name)) as f:
        return yaml.safe_load(f)


def make_request(request_id: str = "r-000001", **overrides) -> dict:
    request = {
        "request_id": request_id,
        "t_arrival": 0.0,
        "user_region": "nyc",
        "model": "llama-3-8b",
        "input_tokens": 850,
        "expected_output_tokens": 200,
        "slo_class": "interactive",
        "ttft_slo_ms": 250,
    }
    request.update(overrides)
    return request


def make_node(node_id: str = "us-east-1", **overrides) -> dict:
    node = {
        "schema_version": "1.0",
        "t": 0.0,
        "node_id": node_id,
        "status": "up",
        "rtt_ms": {"nyc": 12, "chi": 25, "sfo": 70},
        "queue_len": 7,
        "running": 22,
        "capacity": 32,
        "kv_used_frac": 0.68,
        "models_loaded": ["llama-3-8b"],
        "power_headroom_kw": 4.5,
        "temperature_c": 71.0,
        "energy_price_usd_kwh": 0.11,
        "gpu_price_usd_hr": 2.40,
    }
    node.update(overrides)
    return node


def make_outcome(**overrides) -> dict:
    outcome = {
        "ttft_ms": 184.0,
        "e2e_ms": 2210.0,
        "slo_met": True,
        "energy_kwh": 0.0004,
        "cost_usd": 0.00013,
        "reward": 0.0,
    }
    outcome.update(overrides)
    return outcome
