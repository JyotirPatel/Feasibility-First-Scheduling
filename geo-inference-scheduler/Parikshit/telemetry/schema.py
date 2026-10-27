"""
Telemetry schema v1 — owner: Parikshit

The contract for what every node reports once per simulation tick (Project Brief §10.1).
The schema itself is telemetry_schema_v1.json (JSON Schema, draft 2020-12). This module
loads it and checks records in plain Python, so the simulator needs no extra package:

    validate_record(record) -> list of problems, empty if the record is valid

validate_record enforces everything in the JSON file, plus rules a JSON Schema cannot
express: running <= capacity, and a down node holds no requests and no KV cache.
tests/test_telemetry.py checks that it agrees with the `jsonschema` package on thousands
of random records.
"""

from __future__ import annotations

import json
import math
import numbers
import os
from typing import Any

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telemetry_schema_v1.json")
STATUSES = ("up", "down", "warming")
TEMPERATURE_RANGE_C = (-50.0, 150.0)
REQUIRED_FIELDS = (
    "schema_version",
    "t",
    "node_id",
    "status",
    "rtt_ms",
    "queue_len",
    "running",
    "capacity",
    "kv_used_frac",
    "models_loaded",
    "power_headroom_kw",
    "temperature_c",
    "energy_price_usd_kwh",
    "gpu_price_usd_hr",
)
OPTIONAL_FIELDS = ("kv_capacity_tokens",)


def load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def _number(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool) and math.isfinite(value)


def _integer(value: Any) -> bool:
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def validate_record(rec: Any) -> list[str]:
    """Problems with one telemetry record (empty list = valid)."""
    if not isinstance(rec, dict):
        return ["a telemetry record must be a JSON object"]
    problems = [f"missing field {k}" for k in REQUIRED_FIELDS if k not in rec]
    problems += [f"unknown field {k}" for k in rec if k not in REQUIRED_FIELDS + OPTIONAL_FIELDS]
    if problems:
        return problems

    version = rec["schema_version"]
    if not isinstance(version, str) or version.split(".")[0] != "1" or not version.partition(".")[2].isdigit():
        problems.append(f"schema_version must be 1.x, got {version!r}")
    if not _number(rec["t"]) or rec["t"] < 0:
        problems.append("t must be a number >= 0")
    if not isinstance(rec["node_id"], str) or not rec["node_id"]:
        problems.append("node_id must be a non-empty string")
    if rec["status"] not in STATUSES:
        problems.append(f"status must be one of {STATUSES}, got {rec['status']!r}")
    rtt = rec["rtt_ms"]
    if not isinstance(rtt, dict) or not rtt or any(not _number(v) or v < 0 for v in rtt.values()):
        problems.append("rtt_ms must map each user region to a number of ms >= 0")
    for key in ("queue_len", "running"):
        if not _integer(rec[key]) or rec[key] < 0:
            problems.append(f"{key} must be an integer >= 0")
    if not _integer(rec["capacity"]) or rec["capacity"] < 1:
        problems.append("capacity must be an integer >= 1")
    elif _integer(rec["running"]) and rec["running"] > rec["capacity"]:
        problems.append("running must not exceed capacity")
    if not _number(rec["kv_used_frac"]) or not 0 <= rec["kv_used_frac"] <= 1:
        problems.append("kv_used_frac must be a number from 0 to 1")
    models = rec["models_loaded"]
    if (
        not isinstance(models, list)
        or any(not isinstance(m, str) or not m for m in models)
        or len(set(models)) != len(models)
    ):
        problems.append("models_loaded must be a list of distinct model names")
    for key in ("power_headroom_kw", "energy_price_usd_kwh", "gpu_price_usd_hr"):
        if not _number(rec[key]) or rec[key] < 0:
            problems.append(f"{key} must be a number >= 0")
    lo, hi = TEMPERATURE_RANGE_C
    if not _number(rec["temperature_c"]) or not lo <= rec["temperature_c"] <= hi:
        problems.append(f"temperature_c must be a number from {lo} to {hi}")
    cap = rec.get("kv_capacity_tokens")
    if cap is not None and (not _integer(cap) or cap < 1):
        problems.append("kv_capacity_tokens must be an integer >= 1 or null")
    if rec["status"] == "down" and not problems and (rec["running"] or rec["queue_len"] or rec["kv_used_frac"]):
        problems.append("a down node holds no running or queued requests and no KV cache")
    return problems
