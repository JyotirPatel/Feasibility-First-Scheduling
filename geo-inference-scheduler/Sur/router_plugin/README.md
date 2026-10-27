# Sur / router_plugin

**Owner:** Sur. **Used by:** Krupesh's router (`geo-inference-scheduler/Krupesh/`), and Riya's experiment runner through it.

This folder plugs Sur's policies and reward into Krupesh's router, as his Interface & Dependency Handbook (§5.3) asks. Nothing in his folder is edited.

| What | Where | For the router |
|---|---|---|
| `RouterLinUCB`, `RouterSlidingWindowLinUCB` | `plugin.py` | Sur's LinUCB and sliding-window LinUCB as subclasses of his `router_service.policy_base.Policy`. They are the same classes as `linucb/` and `sliding_window_linucb/`: same names, configs and checkpoints. |
| `reward_fn(outcome, node_at_dispatch)` | `plugin.py` | Sur's reward (`reward/`) in his `RewardFn` shape, with the weights in `configs/policies/sw_linucb.yaml`. `make_reward_fn(config)` builds one for another reward section. |
| `register(extra_policies=None)` | `plugin.py` | Adds the names below to his registry (`router_service.registry.EXTRA_POLICIES`, or the dict you pass). |
| `check_router.py` | | Runs a policy through his router end to end and checks the result (see below). |

Registered names. A `config=` parameter picks another policy YAML file.

| Name | Policy | Config |
|---|---|---|
| `sur:linucb`, `linucb` | plain LinUCB, the "no forgetting" ablation | `configs/policies/linucb.yaml` |
| `sur:sw_linucb`, `sliding_window_linucb` | sliding-window LinUCB (per-node window, W = 1000) | `configs/policies/sw_linucb.yaml` |
| `sur:sw_linucb_no_context` | the "no context" ablation | `configs/policies/sw_linucb_no_context.yaml` |

`linucb` and `sliding_window_linucb` are the names in `Riya/experiment_runner/config.json`.

## How to use it in the router (Krupesh)

```python
import sys
sys.path.insert(0, "<repo>/geo-inference-scheduler/Sur")
from router_plugin import register, reward_fn

register()  # or register(EXTRA_POLICIES) inside router_service/registry.py
engine = RoutingEngine(policy=build_policy("sur:sw_linucb", seed=seed),
                       filter_fn=build_filter("jyotir"), reward_fn=reward_fn, ...)
```

- Use `reward_fn` wherever `mock_reward` is used today: `router_service/app.py::make_engine` and `integration/run_end_to_end.py`.
- The router fills `outcome.reward` with it before `update()`. The policies recompute the same number themselves and count any difference in `stats["reward_mismatch"]`, so a router still wired to `mock_reward` shows up there.
- His `Outcome.failed=True` (a node died holding the request) gets no SLO credit and the worst latency term.

## The acceptance check

```bash
cd geo-inference-scheduler/Sur
python3 router_plugin/check_router.py                         # sur:sw_linucb, his mock cluster, 120 s
python3 router_plugin/check_router.py --policy sur:linucb --outage --seed 3
```

This builds the same in-process run as his `integration/run_end_to_end.py`: his `RoutingEngine`, Jyotir's filter, his `MockCluster` and his run summary. The only difference is that it uses Sur's reward instead of his mock. It prints his summary plus the policy's counters, and exits 0 only if all of these hold:
- the decision log is valid (`log_problems: []`);
- no hard rule was broken (`constraint_violations: 0`);
- every finished request was learned from, with none ignored;
- the router's reward equals the policy's.

On his mock (seed 0, 120 s) `sur:linucb` and `sur:sw_linucb` make identical decisions. No node collects 1,000 outcomes in that time, so the window never drops one. His mock uses made-up constants, so its goodput numbers are not results.

## Where his code is found

Krupesh's upload of 2026-10-27 landed one level too deep: `Krupesh/geo-inference-scheduler/Krupesh/`. `plugin.py` looks there and in `Krupesh/`, so it keeps working after he moves it up.
- His folder is appended to `sys.path`, so Sur's and Jyotir's modules win any name clash.
- In the nested place, his own adapter cannot find Jyotir's folder: it looks for `parents[2]/Jyotir`. As uploaded, 29 of his 35 tests fail with `No module named 'baselines'` or `'feasibility_filter'`.
- Moved up one level (checked on a scratch copy), 30 pass and 1 is skipped. The remaining 4 need `pyarrow` to write Parquet, which is in his `requirements.txt`.

Tests: `tests/test_router_plugin.py`.
