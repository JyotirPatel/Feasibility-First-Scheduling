"""HTTP service (TestClient + a real uvicorn server) and the full closed loop."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
from fastapi.testclient import TestClient

from decision_log.writer import validate_log
from integration.run_end_to_end import run, summary
from router_service.app import create_app

KRUPESH = Path(__file__).resolve().parents[1]
REC = {
    "schema_version": "1.0",
    "t": 312.0,
    "node_id": "us-east-1",
    "status": "up",
    "rtt_ms": {"nyc": 12},
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
BODY = {
    "request_id": "r-000123",
    "t_arrival": 312.4,
    "user_region": "nyc",
    "model": "llama-3-8b",
    "input_tokens": 850,
    "expected_output_tokens": 200,
    "slo_class": "interactive",
    "ttft_slo_ms": 250,
}


def test_brief_contract_example_over_http():
    with TestClient(create_app()) as c:
        assert c.get("/health").json()["telemetry_nodes"] == 0
        hot = {**REC, "node_id": "us-west-2", "temperature_c": 90.0}
        assert c.post("/telemetry", json={"records": [REC, hot]}).json() == {"accepted": 2}
        assert c.post("/telemetry", json={"records": [{**REC, "status": "?"}]}).status_code == 422
        r = c.post("/route", json=BODY).json()
        assert r == {
            "request_id": "r-000123",
            "decision": "route",
            "node_id": "us-east-1",
            "policy": "jyotir:static_weighted",
            "feasible_nodes": ["us-east-1"],
            "filtered_out": {"us-west-2": "temperature_high"},
            "reject_reason": None,
        }
        assert c.post("/route", json=BODY).status_code == 409
        fb = {
            "request_id": "r-000123",
            "ttft_ms": 184,
            "e2e_ms": 2210,
            "slo_met": True,
            "energy_kwh": 0.0004,
            "cost_usd": 0.00013,
        }
        assert c.post("/feedback", json=fb).json()["accepted"] is True
        assert c.post("/feedback", json=fb).status_code == 404
        assert c.post("/route", json={**BODY, "input_tokens": 0}).status_code == 422
        assert c.post("/admin/configure", json={"policy": "nope"}).status_code == 400
        assert c.post("/admin/finish", json={}).json()["rows"] == 1


def test_closed_loop_inprocess_valid_and_safe():
    df = run(duration_s=60, seed=3)
    s = summary(df, 60)
    assert s["log_problems"] == [] and s["constraint_violations"] == 0 and s["requests"] > 400
    assert "node-hot" not in set(df.node_id.dropna())  # 91 C node always filtered


def test_closed_loop_with_outage_and_recovery():
    df = run(policy="mock:learning", duration_s=90, seed=1, outage=True)
    assert validate_log(df) == []
    failed = df[df.outcome_status == "failed"]
    assert len(failed) > 0 and (failed.node_id == "node-east").all()
    routed = df[df.decision == "route"]
    assert (routed[(routed.t_arrival > 31) & (routed.t_arrival < 60)].node_id != "node-east").all()
    assert (routed[routed.t_arrival > 61].chosen_node_status == "warming").any()


def test_inprocess_and_http_make_identical_decisions():
    a = run(duration_s=40, seed=7)
    with TestClient(create_app()) as c:
        b = run(duration_s=40, seed=7, mode="http", client=c, log_path=None)
    cols = ["request_id", "decision", "node_id", "slo_met", "reward"]
    pd.testing.assert_frame_equal(a[cols].reset_index(drop=True), b[cols].reset_index(drop=True))


def test_real_uvicorn_server(tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "router_service.app:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=KRUPESH,
        env={**os.environ, "PYTHONPATH": str(KRUPESH)},
    )
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(url + "/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        df = run(
            duration_s=40, seed=2, mode="http", url=url, log_path=str(tmp_path / "log.parquet")
        )
        assert validate_log(df) == [] and len(df) > 300
        assert df.router_wall_ms.median() < 50
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ── runner interface for Riya's experiment runner ─────────────────────────────


def test_out_dir_run_writes_log_and_summary(tmp_path):
    import json

    from integration.run_end_to_end import main

    out = tmp_path / "round_robin" / "mock_outage" / "seed_3"
    rc = main(
        [
            "--policy",
            "round_robin",
            "--scenario",
            "mock_outage",
            "--seed",
            "3",
            "--duration",
            "40",
            "--out-dir",
            str(out),
        ]
    )
    assert rc == 0
    s = json.loads((out / "run_summary.json").read_text())
    assert s["status"] == "ok" and s["policy"] == "round_robin" and s["seed"] == 3
    assert validate_log(pd.read_parquet(out / "decision_log.parquet")) == []


def test_out_dir_failure_and_unsupported_scenario_signal(tmp_path):
    import json

    from integration.run_end_to_end import main

    assert main(["--policy", "linucb", "--duration", "10", "--out-dir", str(tmp_path / "a")]) == 1
    s = json.loads((tmp_path / "a" / "run_summary.json").read_text())
    assert s["status"] == "failed" and "Sur" in s["error"]
    assert main(["--scenario", "s1_stable", "--out-dir", str(tmp_path / "b")]) == 2
