# Krupesh — Work Log

**Project:** Change-Aware, Feasibility-First Scheduling for AI Inference across Geo-Distributed Nodes
**Course:** AMS 560 · Fall 2026 · Group 20 · **Role:** Architecture, router service, contracts,
decision log, integration (Group20_Work_Distribution.pdf §4). AI-assisted; see "Disclosure" below.

## Folder contents (everything is runnable from this folder)

```
Krupesh/
├── README.md                     role description (from the team skeleton, unchanged)
├── WORK_LOG.md                   this file
├── INTEGRATION.md                teammate interfaces, run-one-experiment command, control-plane walkthrough
├── Group20_Interface_and_Dependency_Handbook.pdf   ← give to teammates / their AI agents
├── requirements.txt  ruff.toml
├── tools/make_handbook.py        rebuilds the handbook PDF
├── api_contract/                 Routing API contract v1 + shared types + telemetry validation
│   ├── api_contract.md  types.py  schemas.py  README.md
├── router_service/               FastAPI service + decision engine + Policy interface + registry
│   ├── app.py  engine.py  client.py  policy_base.py  registry.py  README.md
├── decision_log/                 decision log format + writer + validator
│   ├── decision_log_format.md  writer.py  README.md
├── integration/                  adapters, end-to-end driver, labelled mocks
│   ├── jyotir_adapter.py         Jyotir's ORIGINAL filter + baselines (unmodified) behind my interfaces
│   ├── run_end_to_end.py         closed loop, in-process or over HTTP
│   ├── integration_guide.md      what each teammate must provide
│   ├── policy_interface.py       pluggable Policy interface (task 4)
│   ├── weekly_integration_check.py + weekly_integration_report.md   (task 5)
│   └── mocks/                    TEMPORARY: mock_simulator (Parikshit), mock_policy + mock_reward (Sur)
├── report_sections/              novelty wording (task 6), midterm research gap, Introduction/Problem/System design, design slide
└── tests/                        35 tests: contract, log, engine, Jyotir adapter, HTTP, real uvicorn, end-to-end
```

## Run it

```bash
cd geo-inference-scheduler/Krupesh
pip install -r requirements.txt
pytest -o addopts= tests                                   # 35 tests
python -m integration.run_end_to_end                       # closed loop with Jyotir's original code
python -m integration.run_end_to_end --policy mock:learning --outage
uvicorn router_service.app:app --port 8000                 # real service; /docs for the API
python -m integration.run_end_to_end --mode http --url http://127.0.0.1:8000
```

## What was built and why

1. **Contract first** (`api_contract/`): `Request`, `NodeState`, `Decision`, `Outcome` exactly as
   brief §10; `FilterFn` and `RewardFn` as the plug-in points for Jyotir and Sur.
2. **One decision loop, two transports** (`router_service/engine.py` + `app.py`): the same engine
   runs in-process and behind FastAPI; a test proves identical decisions both ways.
3. **Safety in the engine, not trusted to policies**: policies only see filtered nodes; any other
   answer raises; empty set → deliberate `no_feasible_node` reject; an independent audit logs
   `constraint_violation` (only non-null in the no-filter ablation).
4. **Local load accounting**: telemetry is ≤1 s old; the router counts its own recent placements so
   load-based policies do not herd.
5. **Decision log** (`decision_log/`): 17 frozen columns + extensions; rows written at reject time or
   when the delayed feedback arrives; unfinished requests marked at the end.
6. **Integration without touching teammates' code**: Jyotir's original module runs through
   `integration/jyotir_adapter.py` (his 14 tests still pass; his folder is byte-identical to his last
   commit). Missing modules are replaced by clearly labelled mocks.

7. **Experiment-runner interface** (for Riya): plain policy names (`round_robin`, …) map to
   Jyotir's baselines; `linucb` / `sliding_window_linucb` fail loudly until Sur registers them;
   `--out-dir` writes `decision_log.parquet` + `run_summary.json` with exit codes 0/1/2. See
   `INTEGRATION.md` §5.

## Findings to share with the team

- Jyotir's filter lets a `warming` node skip every other rule (F1) — documented by a test, not changed.
- Memory rule ignores the request size (F2).
- Field-name mismatch `slo_ms` vs contract `ttft_slo_ms` (handled in the adapter).

## Tests (midterm verification, 2026-10-27)

Command (from `Krupesh/`): `pytest -o addopts= -v tests` → **35 passed, 0 failed, 0 skipped**.
Lint: `ruff check .` and `ruff format --check .` → clean.

| File | Tests | What it shows | Real or mock |
|---|---|---|---|
| `test_contract_and_log.py` | 6 | brief §10.1 telemetry example validates; bad records rejected; request round-trip; decision log has the 17 §10.3 columns in order; Parquet + CSV writing | real (Krupesh) |
| `test_engine.py` | 11 | **controlled rejection** (`no_feasible_node` with reasons); no telemetry ⇒ reject; **route → delayed feedback → one valid log row**; duplicate id refused; **policy cannot bypass the filter**; no-filter ablation logs the violation; local load accounting; custom filter plug-in; **learning policy receives reward via update()**; unfinished rows | filter/baselines = Jyotir's real code; learning policy + reward = mocks |
| `test_http_and_end_to_end.py` | 7 | brief §10.2 contract example over HTTP (`/route`, `/feedback`, `/health`, 404/409/422); closed loop in-process; outage + recovery; in-process and HTTP make **identical decisions**; **real uvicorn server** | simulator = mock |
| `test_jyotir_adapter.py` | 11 | Jyotir's own 14 tests still pass; `Jyotir/` unchanged since his commit `6c699f7`; his reasons/config; all 6 of his baselines through the `Policy` interface; known issue F1 recorded | **real teammate code** |

What the tests do **not** prove: integration with Parikshit's simulator or Sur's policies (they do not
exist yet). The closed-loop tests use test doubles and only verify the router's plumbing.

## Assumptions

- Contracts follow Project Brief §10 exactly; optional extensions (`failed`, `t_complete`,
  `kv_capacity_tokens`, `/telemetry`, `/admin/*`) are backward compatible.
- Filter reason strings are Jyotir's existing ones (`temperature_high`, …), not the brief's example
  (`temperature`).
- Feedback is delayed; policies cache context by `request_id` (shown in `mocks/mock_policy.py`).
- Experiments use simulated time only; `router_wall_ms` records real time and never advances the
  simulation.
- Feasibility limits are read from Jyotir's own `feasibility.yaml` (85 °C, 2 kW, KV 0.90).

## Limitations (midterm)

- Simulator, learning policies and reward are **test doubles**; no research results are claimed.
- Single-process router with in-memory state (no replication / persistence across restarts).
- Feedback that never arrives is only handled at the end of a run (`unfinished`), not by timeouts.
- Jyotir's filter issues F1/F2 are reported, not fixed (his module, his decision).

## Next steps

| Task | Depends on | When |
|---|---|---|
| Swap `mock_simulator` for Parikshit's simulator | Parikshit's telemetry + feedback calls | Week 2 |
| Register Sur's LinUCB / SW-LinUCB + reward | Sur's `Policy` classes | Week 2–3 |
| Jyotir decides on F1/F2 and the stub import | Jyotir | Week 2 |
| Hand decision logs to Riya for every run | all of the above | Week 3 |

## Disclosure

Code and documents in this folder were produced with an AI coding assistant (Claude Code) under
Krupesh's direction on 2026-10-26/27, and verified by running the tests listed above. The team
should review it before submission, following the course's AI-use policy.
