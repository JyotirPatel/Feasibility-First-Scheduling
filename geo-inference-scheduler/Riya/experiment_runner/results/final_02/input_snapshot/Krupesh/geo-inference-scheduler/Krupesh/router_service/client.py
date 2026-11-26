"""HTTP client with the same methods as RoutingEngine — owner: Krupesh.

Lets a simulator (Parikshit's, or the mock) drive the real HTTP service exactly like it
would drive the in-process engine. Real wall-clock round-trip time per /route is stored
in `wall_ms`; it never advances simulated time.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from api_contract.types import Decision, NodeState, Outcome, Request


class HttpRouter:
    def __init__(self, client: Any):
        self.client = client  # httpx.Client or fastapi.testclient.TestClient
        self.wall_ms: dict[str, float] = {}

    @classmethod
    def connect(cls, base_url: str, timeout: float = 10.0) -> HttpRouter:
        return cls(httpx.Client(base_url=base_url, timeout=timeout))

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = self.client.post(path, json=payload)
        r.raise_for_status()
        return r.json()

    def configure(self, **cfg: Any) -> dict[str, Any]:
        return self._post("/admin/configure", cfg)

    def ingest_telemetry(self, records: list[NodeState]) -> None:
        self._post("/telemetry", {"records": [r.to_dict() for r in records]})

    def route(self, request: Request) -> Decision:
        t0 = time.perf_counter()
        d = self._post("/route", request.to_dict())
        self.wall_ms[request.request_id] = (time.perf_counter() - t0) * 1000.0
        return Decision(**d)

    def feedback(self, outcome: Outcome) -> float:
        payload = outcome.to_dict()
        payload.pop("reward", None)
        return float(self._post("/feedback", payload)["reward"])

    def finish(self, log_path: str | None = None) -> dict[str, Any]:
        return self._post("/admin/finish", {"log_path": log_path})

    def health(self) -> dict[str, Any]:
        r = self.client.get("/health")
        r.raise_for_status()
        return r.json()
