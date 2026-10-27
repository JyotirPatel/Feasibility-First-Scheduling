"""API contract types, telemetry validation, decision log."""

import pytest

from api_contract.schemas import validate_telemetry
from api_contract.types import NodeState, Request
from decision_log.writer import COLUMNS, V1_COLUMNS, DecisionLogWriter
from kr_helpers import node, request

BRIEF_TELEMETRY = {
    "schema_version": "1.0",
    "t": 312.0,
    "node_id": "us-east-1",
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


def test_brief_telemetry_example_is_valid_and_roundtrips():
    assert validate_telemetry(BRIEF_TELEMETRY) == []
    n = NodeState.from_dict(BRIEF_TELEMETRY)
    assert n.to_dict()["rtt_ms"] == BRIEF_TELEMETRY["rtt_ms"] and n.load == 29


def test_bad_telemetry_rejected():
    bad = {**BRIEF_TELEMETRY, "status": "melting", "kv_used_frac": 1.5, "queue_len": -1}
    assert len(validate_telemetry(bad)) == 3
    assert validate_telemetry({"node_id": "x"})


def test_request_roundtrip_and_kv_tokens():
    r = request()
    assert Request.from_dict(r.to_dict()) == r and r.kv_tokens == 1050


def test_rtt_fallback_to_mean_for_unknown_region():
    assert node(rtt_ms={"a": 10, "b": 30}).rtt_for("zzz") == 20


def test_decision_log_v1_columns_frozen():
    assert len(V1_COLUMNS) == 17 and COLUMNS[:17] == V1_COLUMNS
    assert V1_COLUMNS[:5] == ["run_id", "seed", "scenario", "policy", "request_id"]
    with pytest.raises(ValueError):
        DecisionLogWriter().write({"bogus": 1})


def test_log_written_to_parquet_and_csv(tmp_path):
    for name in ("log.parquet", "log.csv"):
        w = DecisionLogWriter(tmp_path / name)
        w.write(
            {
                "request_id": "a",
                "t_arrival": 1.0,
                "decision": "reject",
                "outcome_status": "rejected",
            }
        )
        df = w.close()
        assert (tmp_path / name).exists() and len(df) == 1
