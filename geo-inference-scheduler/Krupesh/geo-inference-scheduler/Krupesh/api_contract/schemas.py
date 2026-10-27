"""HTTP request/response models (Pydantic) + telemetry validator — owner: Krupesh.

These are the wire formats of POST /route, POST /feedback, POST /telemetry.
`validate_telemetry` checks a record against telemetry schema v1 (brief §10.1); the
schema itself is owned by Parikshit, the router only enforces it at its boundary.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from api_contract.types import NODE_STATUSES, SCHEMA_VERSION


class RouteRequest(BaseModel):
    request_id: str
    t_arrival: float = Field(ge=0)
    user_region: str
    model: str
    input_tokens: int = Field(ge=1)
    expected_output_tokens: int = Field(ge=1)
    slo_class: str = "interactive"
    ttft_slo_ms: float = Field(250.0, gt=0)


class RouteResponse(BaseModel):
    request_id: str
    decision: str
    node_id: str | None
    policy: str
    feasible_nodes: list[str]
    filtered_out: dict[str, str]
    reject_reason: str | None


class FeedbackRequest(BaseModel):
    request_id: str
    ttft_ms: float
    e2e_ms: float
    slo_met: bool
    energy_kwh: float = Field(ge=0)
    cost_usd: float = Field(ge=0)
    failed: bool = False
    t_complete: float | None = None


class FeedbackResponse(BaseModel):
    request_id: str
    accepted: bool
    reward: float


class TelemetryBatch(BaseModel):
    records: list[dict[str, Any]]


class ConfigureRequest(BaseModel):
    """POST /admin/configure: build a fresh engine for one run."""

    policy: str = "jyotir:static_weighted"
    seed: int = 0
    run_id: str = "adhoc"
    scenario: str = "none"
    filter: str = "jyotir"  # "jyotir" (Jyotir's original) | "none" (ablation only)
    local_load_accounting: bool = True
    log_path: str | None = None


REQUIRED_TELEMETRY = (
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


def validate_telemetry(rec: dict[str, Any]) -> list[str]:
    """Problems with one telemetry record (empty list = valid)."""
    errs = [f"missing field {k}" for k in REQUIRED_TELEMETRY if k not in rec]
    if errs:
        return errs
    if str(rec["schema_version"]).split(".")[0] != SCHEMA_VERSION.split(".")[0]:
        errs.append(f"unsupported schema_version {rec['schema_version']}")
    if rec["status"] not in NODE_STATUSES:
        errs.append(f"bad status {rec['status']}")
    for k in ("queue_len", "running"):
        if not isinstance(rec[k], int) or rec[k] < 0:
            errs.append(f"{k} must be an integer >= 0")
    if not isinstance(rec["capacity"], int) or rec["capacity"] < 1:
        errs.append("capacity must be an integer >= 1")
    if not 0.0 <= float(rec["kv_used_frac"]) <= 1.0:
        errs.append("kv_used_frac must be in [0, 1]")
    if not isinstance(rec["rtt_ms"], dict) or any(float(v) < 0 for v in rec["rtt_ms"].values()):
        errs.append("rtt_ms must map region -> non-negative ms")
    if not isinstance(rec["models_loaded"], list):
        errs.append("models_loaded must be a list")
    for k in ("energy_price_usd_kwh", "gpu_price_usd_hr", "t"):
        if float(rec[k]) < 0:
            errs.append(f"{k} must be >= 0")
    return errs
