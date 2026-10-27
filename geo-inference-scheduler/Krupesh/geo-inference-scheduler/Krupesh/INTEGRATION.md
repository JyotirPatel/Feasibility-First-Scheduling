# INTEGRATION — how teammates plug into Krupesh's router

Owner: Krupesh (architecture, router, contracts, decision log, integration).
Status date: 2026-10-27 (midterm). Everything below is implemented in this folder and covered by
`tests/`. Nothing outside `Krupesh/` was edited.

## 1. Real vs mock today

| Piece | Owner | Status in this folder | Where |
|---|---|---|---|
| Feasibility filter | Jyotir | **REAL**: his original code, loaded read-only, limits from his `feasibility.yaml` | `integration/jyotir_adapter.py` |
| Baselines (round_robin, min_rtt, least_load, lowest_energy, static_weighted, power_of_two) | Jyotir | **REAL** (his code behind the `Policy` interface) | `integration/jyotir_adapter.py` |
| Simulator and telemetry | Parikshit | **MOCK** (`MockCluster`, test double) | `integration/mocks/mock_simulator.py` |
| LinUCB / SW-LinUCB | Sur | **MISSING**: `linucb` and `sliding_window_linucb` raise a clear "needs Sur's implementation" error. `mock:learning` exists only to test the plumbing | `integration/mocks/mock_policy.py` |
| Reward function | Sur | **MOCK** (placeholder weights shaped like brief §6.3) | `integration/mocks/mock_reward.py` |
| Experiments and metrics | Riya | **Interface ready** (`--out-dir`, see §5). Runs on the mock simulator only | `integration/run_end_to_end.py` |

Tests that use mocks only prove the router's plumbing. They do not prove integration with code that
does not exist yet.

## 2. Exact interfaces (from `api_contract/types.py`)

```python
Request(request_id, t_arrival, user_region, model, input_tokens, expected_output_tokens,
        slo_class="interactive", ttft_slo_ms=250.0)
NodeState(node_id, status, rtt_ms: dict[region, ms], queue_len, running, capacity, kv_used_frac,
          models_loaded, power_headroom_kw, temperature_c, energy_price_usd_kwh, gpu_price_usd_hr,
          t=0.0, schema_version=SCHEMA_VERSION, kv_capacity_tokens=None)
Decision(request_id, decision: "route"|"reject", node_id, policy, feasible_nodes, filtered_out,
         reject_reason)
Outcome(request_id, ttft_ms, e2e_ms, slo_met, energy_kwh, cost_usd,
        failed=False, t_complete=None, reward=None)       # reward is filled in by the router

FilterFn = Callable[[Request, list[NodeState]], FilterResult]   # FilterResult(allowed, rejected{id: reason})
RewardFn = Callable[[Outcome, NodeState], float]                 # NodeState = node as seen at dispatch

class Policy:                                                    # router_service/policy_base.py
    def choose(self, request, candidates: list[NodeState]) -> str: ...   # node_id of a candidate
    def update(self, request, node_id, outcome: Outcome) -> None: ...    # delayed feedback
```

### Jyotir (filter and baselines): already connected
- The adapter turns `Request` into his dict (it adds `slo_ms = ttft_slo_ms`) and calls his filter. It
  maps his reasons (`node_down`, `temperature_high`, `memory_full`, `power_limit`, `model_missing`)
  straight into `filtered_out`.
- Open items for Jyotir to decide (reported, not changed): **F1**, a `warming` node skips every
  other rule; **F2**, the memory rule ignores the request size.

### Sur (learning policies and reward): to register
1. Subclass `Policy`. Cache the context in `choose` keyed by `request.request_id`, because
   `update` arrives later, when the request finishes.
2. Register the classes in `router_service/registry.py`:
   ```python
   EXTRA_POLICIES["linucb"] = lambda seed, **p: LinUCB(seed=seed, **p)
   EXTRA_POLICIES["sliding_window_linucb"] = lambda seed, **p: SlidingWindowLinUCB(seed=seed, **p)
   ```
   `EXTRA_POLICIES` is checked first, so Riya's plain names then resolve to Sur's code.
3. Replace `mock_reward` with the real `reward_fn(outcome, node_at_dispatch) -> float`, both in
   `router_service/app.py::make_engine` and in `integration/run_end_to_end.py`.

### Parikshit (simulator and telemetry): to connect
The simulator drives the router with these calls. The in-process engine and the HTTP client
(`router_service/client.py::HttpRouter`) have the same methods:
```python
router.ingest_telemetry(list_of_NodeState)    # or POST /telemetry   {"records":[...]}, every tick (<= 1 s)
decision = router.route(request)              # or POST /route       -> RouteResponse
...simulated execution on decision.node_id...
router.feedback(outcome)                      # or POST /feedback    when the request finishes
router.finish()                               # or POST /admin/finish {"log_path": ...}
```
Telemetry records must contain the brief §10.1 fields. `api_contract/schemas.py::validate_telemetry`
lists any that are missing. `integration/mocks/mock_simulator.py` is the reference driver: copy its
call order.

## 3. How the router calls the filter and the policy (one `/route`)

1. Validate the request (Pydantic). A bad body returns 422; a duplicate `request_id` returns 409.
2. Take the latest telemetry snapshot. With no telemetry, reject with `no_feasible_node`.
3. Optionally add the router's own recent placements (local load accounting between ticks).
4. `filter_fn(request, nodes)` returns the allowed nodes plus a reason for every rejected node.
5. If nothing is allowed, return `decision="reject"`, `reject_reason="no_feasible_node"` and the
   reasons. This is a controlled rejection, not an error.
6. `policy.choose(request, allowed)`. If the answer is not in `allowed`, the router raises: a policy
   cannot bypass the filter.
7. An independent audit (Jyotir's filter) records `constraint_violation`, which is only ever
   non-null in the `--filter none` ablation.
8. Store the pending context (request, node snapshot, time) and return the `Decision`.

On `/feedback`, the router computes `outcome.reward = reward_fn(outcome, node_at_dispatch)`, calls
`policy.update(...)`, and writes one decision-log row. An unknown id returns 404.

## 4. Decision log (what Riya reads)

There are 17 frozen v1 columns (brief §10.3), in this order: `run_id, seed, scenario, policy,
request_id, t_arrival, decision, node_id, feasible_nodes, filtered_out, reject_reason, ttft_ms,
e2e_ms, slo_met, energy_kwh, cost_usd, reward`. After them come extension columns: `outcome_status`
(`ok|failed|rejected|unfinished`), `t_complete`, request fields, `telemetry_age_s`,
`constraint_violation`, `router_wall_ms`. Run `decision_log.writer.validate_log(df)` to check a log;
it returns `[]` when the log is valid. Full spec: `decision_log/decision_log_format.md`.

Column mapping for `Riya/metrics/calculate_metrics.py` (her sample CSV uses different names):

| Riya sample column | Decision-log equivalent |
|---|---|
| `request_id` | `request_id` |
| `completion_time_s` | `t_complete` |
| `rejected` | `decision == "reject"` |
| `latency_ms` | `ttft_ms` (or `e2e_ms` for end-to-end) |
| `slo_met` | `slo_met` |
| `cost_usd` | `cost_usd` |
| `energy_j` | `energy_kwh * 3.6e6` |

## 5. Running one experiment run (for Riya's runner)

From `geo-inference-scheduler/Krupesh`:
```bash
python -m integration.run_end_to_end --policy round_robin --scenario mock_outage --seed 3 \
    --duration 120 --out-dir runs/round_robin/mock_outage/seed_3
```
- `--policy` accepts Riya's plain names (`round_robin`, `min_rtt`, `least_load`, `lowest_energy`,
  `static_weighted`, `power_of_two`) as well as `jyotir:*` and `mock:learning`.
- The run writes `decision_log.parquet` and `run_summary.json` (with `status` set to `ok`,
  `invalid_log` or `failed`).
- Exit codes: **0** means ok; **1** means the run failed (for example, Sur's policy is not registered
  yet); **2** means the log is invalid or the scenario is not supported.
- Today the scenarios are `mock_stable` and `mock_outage`. `s1_stable` … `s6_outage_recovery`
  return exit code 2 with "requires Parikshit's simulator" until his simulator is connected.
- HTTP mode does the same through the real service: start
  `uvicorn router_service.app:app --port 8000`, then add `--mode http --url http://127.0.0.1:8000`.

## 6. Full flow once every module exists

1. Parikshit: put the simulator's driver in place of `MockCluster` (same calls as §2) and map the
   S1–S6 names in `run_end_to_end.py::MOCK_SCENARIOS` (renamed to a scenario table).
2. Sur: register the policies and the reward (§2).
3. Riya: loop over policy × scenario × seed, calling the command in §5; read each
   `decision_log.parquet`; and compute the metrics using the mapping in §4.
4. Re-run `pytest -o addopts= tests` and `python -m integration.weekly_integration_check`.

## 7. Walkthrough: how this resembles a real GPU data-center control plane

A real inference platform separates a **control plane** (the part that decides where work goes) from
the **data plane** (the GPUs that run the work). This router is a small version of the control
plane:

| This project | Production analogue |
|---|---|
| `POST /telemetry` every ≤ 1 s | node agents or exporters pushing GPU, thermal, power and queue metrics to a scheduler |
| feasibility filter (model loaded, KV memory, power, temperature, status) | the "filter / predicate" stage of a cluster scheduler (Kubernetes-style), plus power and thermal capping in the data center |
| policy `choose()` over the feasible set only | the "score / rank" stage, or a load balancer's routing algorithm |
| `no_feasible_node` reject | admission control / load shedding instead of overloading a hot or full GPU |
| local load accounting between ticks | schedulers counting their own in-flight assignments, because metrics are always a little stale |
| delayed `/feedback` → reward → `update()` | closed-loop control: completion latency and SLO results flow back to tune routing |
| decision log | the audit and observability trail used for incident reviews and offline evaluation |
| `/health`, `/admin/configure` | readiness probes and runtime configuration of a service |

What this midterm version simplifies: there is one router process with in-memory state (production
control planes are replicated and keep durable state), telemetry is simulated, feedback that never
arrives is handled only at the end of a run (no timeouts), and there is no authentication on the
admin endpoints.
