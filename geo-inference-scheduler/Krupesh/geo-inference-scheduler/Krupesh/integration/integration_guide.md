# Integration guide — owner: Krupesh

How every teammate's module connects to the router. The full version with copy-paste agent
briefs is `Krupesh/Group20_Interface_and_Dependency_Handbook.pdf`.

## Status today

| Teammate | Module | Status | How it is connected now |
|---|---|---|---|
| Jyotir | feasibility filter + 6 baselines | **exists** | original code, unmodified, via `integration/jyotir_adapter.py` |
| Parikshit | simulator + telemetry + 6 event traces | missing | `integration/mocks/mock_simulator.py` (MOCK) |
| Sur | LinUCB, SW-LinUCB, context vector, reward | missing | `integration/mocks/mock_policy.py`, `mock_reward.py` (MOCKS) |
| Riya | metrics, adaptation time, runner, figures | missing | not needed by the router; she reads `decision_log` files |

## What each teammate must hand to the router

**Jyotir** — already compatible. Requested changes (his decision):
1. F1 (safety): in `Jyotir/feasibility_filter/filter.py::_check_node`, a `warming` node returns before
   the model/memory/power/temperature rules; a 99 °C warming node is allowed
   (`tests/test_jyotir_adapter.py::test_known_issue_F1_warming_bypass_is_documented_not_fixed`).
2. F2: memory rule should include this request's tokens:
   `kv_used_frac + (input_tokens + expected_output_tokens) / kv_capacity_tokens > kv_cache_max_frac`.
3. Use `from router_service.policy_base import Policy` and `from api_contract.types import Outcome`
   instead of `stubs.stub_policy` (his stub README already plans this).
4. Request field is `ttft_slo_ms` (his tests use `slo_ms`; the adapter maps it for now).

**Parikshit** — a simulator that calls, in simulated time:
- `router.ingest_telemetry(list[NodeState])` once per tick (or `POST /telemetry`), records per
  `api_contract/types.py::NodeState` (brief §10.1 field names and units);
- `decision = router.route(Request)` per arrival (or `POST /route`);
- `router.feedback(Outcome)` when the request finishes or fails (or `POST /feedback`);
  `failed=True` if the node died while holding it; `t_complete` = sim time.
Reference call order: `integration/mocks/mock_simulator.py::MockCluster.run`.
Optional extension field `kv_capacity_tokens` (needed for F2).

**Sur** — `Policy` subclasses (LinUCB, SW-LinUCB) and a reward function:
- `choose(request, candidates) -> node_id` — candidates are already filtered; cache the context
  vector by `request.request_id`;
- `update(request, node_id, outcome)` — called later; `outcome.reward` is already set;
- `reward_fn(outcome, node_at_dispatch) -> float` (brief §6.3);
- register: `router_service/registry.py: EXTRA_POLICIES["sur:sw_linucb"] = ...`, and pass the reward
  function as `reward_fn` in `router_service/app.py::make_engine` / `integration/run_end_to_end.py`.
Reference: `integration/mocks/mock_policy.py` shows the delayed-feedback pattern.

**Riya** — nothing to hand to the router. She consumes `decision_log/decision_log_format.md`
files (one per run). The router guarantees column order, unique ids, outcomes on completed rows.

## Checklist to connect a real module

1. Implement against `api_contract/types.py` and `router_service/policy_base.py` only.
2. Register it (`registry.py`) or pass it (`filter_fn` / `reward_fn`).
3. Run `pytest -o addopts= tests` in `Krupesh/` — must stay green.
4. Run `python -m integration.run_end_to_end --policy <your policy>` — `log_problems: []`,
   `constraint_violations: 0`.
5. Delete the matching mock in `integration/mocks/`.
