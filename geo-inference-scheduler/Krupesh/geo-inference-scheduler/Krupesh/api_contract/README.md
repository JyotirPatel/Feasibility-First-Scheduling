# Krupesh / api_contract

**Owner:** Krupesh. The shared interfaces every module codes against.

| File | What |
|---|---|
| `api_contract.md` | Routing API contract v1 (POST /route, /feedback, GET /health + extensions) and the Python plug-in interfaces |
| `types.py` | `Request`, `NodeState` (telemetry v1), `Decision`, `Outcome`, `FilterResult`, `FilterFn`, `RewardFn` |
| `schemas.py` | HTTP wire models (Pydantic) and `validate_telemetry` (telemetry schema v1 check at the router boundary) |

Telemetry schema v1 itself is owned by Parikshit; the router consumes and validates it.
