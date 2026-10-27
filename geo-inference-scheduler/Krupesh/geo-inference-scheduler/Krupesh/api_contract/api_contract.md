# Routing API contract v1 — owner: Krupesh

Implements Project Brief §10.2. Code: `router_service/app.py` (HTTP), `router_service/engine.py`
(decision loop), `api_contract/types.py` (Python types), `api_contract/schemas.py` (wire models).
Fields marked *extension* are optional and backward compatible.

## Start

```bash
cd geo-inference-scheduler/Krupesh
pip install -r requirements.txt
uvicorn router_service.app:app --port 8000          # docs at http://127.0.0.1:8000/docs
# env: KRUPESH_POLICY=jyotir:static_weighted  KRUPESH_FILTER=jyotir  KRUPESH_SEED=0  KRUPESH_LOG_PATH=...
```

## POST /route

```json
{"request_id": "r-000123", "t_arrival": 312.4, "user_region": "nyc", "model": "llama-3-8b",
 "input_tokens": 850, "expected_output_tokens": 200, "slo_class": "interactive", "ttft_slo_ms": 250}
```
→
```json
{"request_id": "r-000123", "decision": "route", "node_id": "us-east-1", "policy": "jyotir:static_weighted",
 "feasible_nodes": ["us-east-1"], "filtered_out": {"us-west-2": "temperature_high"}, "reject_reason": null}
```

- Reject: `decision="reject"`, `node_id=null`, `feasible_nodes=[]`, `reject_reason="no_feasible_node"`.
- `filtered_out` reasons are Jyotir's: `node_down`, `node_warming`, `model_missing`, `memory_full`,
  `power_limit`, `temperature_high` (the brief's example said `temperature`; we keep Jyotir's names).
- `t_arrival` is **simulation time** (s); the router never uses the wall clock for decisions.
- Errors: `422` invalid body, `409` duplicate in-flight `request_id`.

## POST /feedback  (simulator → router, when the request finishes)

```json
{"request_id": "r-000123", "ttft_ms": 184, "e2e_ms": 2210, "slo_met": true,
 "energy_kwh": 0.0004, "cost_usd": 0.00013}
```
*Extensions:* `failed` (bool), `t_complete` (sim s). Response
`{"request_id", "accepted": true, "reward": <float>}`; `404` if unknown or already answered.

## GET /health

`{"status":"ok","policy":...,"run_id":...,"telemetry_nodes":5,"telemetry_t":311.0,"pending":42,
"routed":..,"rejected":..,"feedback":..,"failed":..}`

## Extensions

| Endpoint | Body | Purpose |
|---|---|---|
| `POST /telemetry` | `{"records": [<telemetry v1>, ...]}` | nodes push state (validated; `422` if invalid) |
| `POST /admin/configure` | `{"policy","seed","run_id","scenario","filter","local_load_accounting","log_path"}` | new engine for one run |
| `POST /admin/finish` | `{"log_path": "..."}` | mark in-flight requests `unfinished`, write the decision log |

## Python plug-in interfaces

```python
# router_service/policy_base.py            (Jyotir: baselines, Sur: LinUCB / SW-LinUCB)
class Policy:
    def choose(self, request: Request, candidates: list[NodeState]) -> str: ...
    def update(self, request: Request, node_id: str, outcome: Outcome) -> None: ...


# api_contract/types.py
FilterFn = Callable[[Request, list[NodeState]], FilterResult]  # Jyotir
RewardFn = Callable[[Outcome, NodeState], float]  # Sur
```

Guarantees: policies only see filtered candidates; a choice outside them raises; feedback is
delayed (cache your context by `request.request_id` in `choose`, use it in `update`).
