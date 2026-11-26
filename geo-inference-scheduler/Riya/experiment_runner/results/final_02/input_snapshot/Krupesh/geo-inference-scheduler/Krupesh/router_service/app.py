"""FastAPI router service — owner: Krupesh.

Contract endpoints (brief §10.2):  POST /route · POST /feedback · GET /health
Extensions (backward compatible):  POST /telemetry · POST /admin/configure · POST /admin/finish

Run (from geo-inference-scheduler/Krupesh):
    uvicorn router_service.app:app --port 8000

Default engine: Jyotir's original filter + Jyotir's static-weighted baseline, MOCK reward.
Environment overrides: KRUPESH_POLICY, KRUPESH_FILTER, KRUPESH_SEED, KRUPESH_LOG_PATH.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from api_contract.schemas import (
    ConfigureRequest,
    FeedbackRequest,
    FeedbackResponse,
    RouteRequest,
    RouteResponse,
    TelemetryBatch,
    validate_telemetry,
)
from api_contract.types import NodeState, Outcome, Request
from decision_log.writer import DecisionLogWriter
from integration.mocks.mock_reward import mock_reward
from router_service.engine import RoutingEngine, RunMeta, UnknownRequest
from router_service.registry import build_filter, build_policy


def make_engine(cfg: ConfigureRequest) -> RoutingEngine:
    policy = build_policy(cfg.policy, seed=cfg.seed)
    return RoutingEngine(
        policy=policy,
        filter_fn=build_filter(cfg.filter),
        reward_fn=mock_reward,  # TODO(Sur): replace with Sur's reward function
        meta=RunMeta(cfg.run_id, cfg.seed, cfg.scenario, cfg.policy),
        writer=DecisionLogWriter(cfg.log_path),
        local_load_accounting=cfg.local_load_accounting,
        audit_fn=build_filter("jyotir"),
    )


def default_config() -> ConfigureRequest:
    return ConfigureRequest(
        policy=os.environ.get("KRUPESH_POLICY", "jyotir:static_weighted"),
        filter=os.environ.get("KRUPESH_FILTER", "jyotir"),
        seed=int(os.environ.get("KRUPESH_SEED", "0")),
        log_path=os.environ.get("KRUPESH_LOG_PATH"),
    )


def create_app(engine: RoutingEngine | None = None) -> FastAPI:
    app = FastAPI(title="Group 20 router (Krupesh)", version="1.0")
    state: dict[str, RoutingEngine | None] = {"engine": engine}

    def eng() -> RoutingEngine:
        if state["engine"] is None:
            state["engine"] = make_engine(default_config())
        return state["engine"]

    @app.post("/route", response_model=RouteResponse)
    def route(req: RouteRequest) -> RouteResponse:
        try:
            d = eng().route(Request(**req.model_dump()))
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return RouteResponse(**d.to_dict())

    @app.post("/feedback", response_model=FeedbackResponse)
    def feedback(fb: FeedbackRequest) -> FeedbackResponse:
        try:
            r = eng().feedback(Outcome(**fb.model_dump()))
        except UnknownRequest as e:
            raise HTTPException(404, f"unknown or already-finished request {fb.request_id}") from e
        return FeedbackResponse(request_id=fb.request_id, accepted=True, reward=r)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return eng().health()

    @app.post("/telemetry")
    def telemetry(batch: TelemetryBatch) -> dict[str, Any]:
        problems = {
            str(r.get("node_id", "?")): e for r in batch.records if (e := validate_telemetry(r))
        }
        if problems:
            raise HTTPException(422, {"invalid_records": problems})
        eng().ingest_telemetry([NodeState.from_dict(r) for r in batch.records])
        return {"accepted": len(batch.records)}

    @app.post("/admin/configure")
    def configure(cfg: ConfigureRequest) -> dict[str, Any]:
        try:
            state["engine"] = make_engine(cfg)
        except (KeyError, ValueError, TypeError) as e:
            raise HTTPException(400, str(e)) from e
        return state["engine"].health()

    @app.post("/admin/finish")
    def finish(body: dict[str, Any] | None = None) -> dict[str, Any]:
        e = eng()
        unfinished = e.finish()
        if body and body.get("log_path"):
            e.writer.path = Path(body["log_path"])
        df = e.writer.close()
        return {
            "rows": len(df),
            "unfinished": unfinished,
            "log_path": str(e.writer.path) if e.writer.path else None,
        }

    return app


app = create_app()
