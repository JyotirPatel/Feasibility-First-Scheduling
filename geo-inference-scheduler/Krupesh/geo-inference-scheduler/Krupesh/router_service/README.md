# Krupesh / router_service

**Owner:** Krupesh. The routing service.

| File | What |
|---|---|
| `engine.py` | `RoutingEngine`: telemetry view → filter → policy → log → feedback → reward → update. Safety guard + local load accounting |
| `app.py` | FastAPI service: `/route`, `/feedback`, `/health`, `/telemetry`, `/admin/configure`, `/admin/finish` |
| `client.py` | `HttpRouter`: same methods as the engine, over HTTP (lets a simulator drive the real server) |
| `policy_base.py` | `Policy` interface (`choose`, `update`) implemented by Jyotir and Sur |
| `registry.py` | name → policy / filter (`jyotir:<baseline>`, `mock:learning`, `jyotir`, `none`); `EXTRA_POLICIES` for Sur |

Run: `uvicorn router_service.app:app --port 8000` from `Krupesh/`.
