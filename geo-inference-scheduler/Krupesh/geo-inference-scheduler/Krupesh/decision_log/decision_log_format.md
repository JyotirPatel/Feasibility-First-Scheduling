# Decision log format v1 — owner: Krupesh, consumer: Riya

One row per request; Parquet (or CSV if the path ends in `.csv`). Writer/validator:
`decision_log/writer.py` (`DecisionLogWriter`, `read_log`, `validate_log`).

## Frozen v1 columns (brief §10.3, in this order)

| # | Column | Type | Meaning |
|---|---|---|---|
| 1 | run_id | str | `<scenario>__<policy>__s<seed>` |
| 2 | seed | int | random seed of the run |
| 3 | scenario | str | e.g. `S6_outage_recovery` |
| 4 | policy | str | policy name/label |
| 5 | request_id | str | unique in a run |
| 6 | t_arrival | float | simulation time (s) |
| 7 | decision | str | `route` or `reject` |
| 8 | node_id | str/null | chosen node, null on reject |
| 9 | feasible_nodes | JSON str | node ids that passed the filter |
| 10 | filtered_out | JSON str | `{node_id: reason}` |
| 11 | reject_reason | str/null | `no_feasible_node` on reject |
| 12 | ttft_ms | float/null | time to first token |
| 13 | e2e_ms | float/null | end-to-end time |
| 14 | slo_met | bool | TTFT ≤ SLO and not failed; False if rejected/unfinished |
| 15 | energy_kwh | float/null | energy attributed to the request |
| 16 | cost_usd | float/null | energy cost + GPU rent share |
| 17 | reward | float/null | reward given to the policy |

## Extension columns

`outcome_status` (ok / failed / rejected / unfinished), `t_complete`, `user_region`, `model`,
`slo_class`, `ttft_slo_ms`, `input_tokens`, `expected_output_tokens`, `chosen_node_status`,
`telemetry_age_s`, `constraint_violation` (must be null while the filter is on),
`true_state_violation` (filled by a simulator that knows the true state), `router_wall_ms` (real
wall-clock time, never simulated time).

## When rows are written

- Rejected request → immediately at `/route`.
- Routed request → when its `/feedback` arrives (delayed), with outcome and reward.
- Still in flight at the end → `outcome_status = unfinished`, `slo_met = False` (`/admin/finish`).

`validate_log(df)` checks column order, unique ids, route/reject consistency, completed rows have
outcomes, `e2e_ms ≥ ttft_ms`, chosen node ∈ feasible set.
