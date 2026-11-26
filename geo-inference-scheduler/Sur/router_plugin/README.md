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

- Use `reward_fn` for Sur's policies wherever `mock_reward` is used today: `router_service/app.py::make_engine` and `integration/run_end_to_end.py`.
- The router fills `outcome.reward` with it before `update()`. The policies recompute the same number themselves and count any difference in `stats["reward_mismatch"]`, so a router still wired to `mock_reward` shows up there.
- His `Outcome.failed=True` (a node died holding the request) gets no SLO credit and the worst latency term.

## Wiring into his router: a ready patch

His handbook (§5.3) asks for two steps:
- register Sur's policies in `router_service/registry.py`;
- pass Sur's `reward_fn` where `mock_reward` is used (`app.py` make_engine and `integration/run_end_to_end.py`).

His acceptance test is `python -m integration.run_end_to_end --policy sur:sw_linucb`, which must give `log_problems: []` and `constraint_violations: 0`. His code still has the `TODO(Sur)` notes, so that command fails today with `KeyError: unknown policy 'sur:sw_linucb'`, and his HTTP service answers 400 "unknown policy". The final evaluation registers the policies itself, so no result depends on this. It matters for his acceptance test and for a live demo.

`krupesh_sur_policies.patch` does both steps. Apply it from the repo root with `git apply geo-inference-scheduler/Sur/router_plugin/krupesh_sur_policies.patch`. It changes 5 of his files:
- **`router_service/registry.py`.**
  - It registers Sur's policies under their `sur:` names only. His tests expect `linucb` and `sliding_window_linucb` to stay unregistered.
  - It finds Sur's folder by searching upward, so it works at either depth of his folder.
  - Its `reward_for(policy, default)` gives Sur's reward to Sur's policies and `default` to everything else.
- **`router_service/app.py` and `integration/run_end_to_end.py`.** These use `reward_for(...)` where they used `mock_reward`. His baselines keep the mock, so his in-process and HTTP runs stay identical.
- **`integration/mocks/mock_reward.py` and `mock_policy.py`.** Their `TODO(Sur)` notes now say what replaced them. The mocks stay for plumbing tests.

It was checked on a copy of his folder (2026-11-26):
- **His acceptance test:** passes with the patch for `sur:sw_linucb`, `sur:linucb --outage --seed 3` and `sur:sw_linucb_no_context`: exit 0, `log_problems: []`, `constraint_violations: 0`. Without the patch it fails, as described above.
- **His suite:** 32 passed with the patch, exactly as without it. The same 3 tests fail either way:
  - his two outdated tests about Jyotir's folder;
  - the live-server test, which also fails without the patch on this machine.
- **Over HTTP:** each of Sur's three policies routed all 1,173 requests of his mock cluster with 0 reward mismatches. `jyotir:static_weighted` still uses the mock reward.
- **On a real `uvicorn` server:** `/admin/configure` with `sur:sw_linucb` answers `"status": "ok"`.
- **Lint:** ruff check and format pass with his settings.

One thing in his folder that the patch does not touch: `integration/weekly_integration_check.py` looks for teammates' modules one level above his folder. In the nested upload that is `Krupesh/geo-inference-scheduler/`, so it reports Sur's modules as missing.

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
- His adapter's path to Jyotir's folder was later fixed (`parents[4]`), so it works in the nested place.

Tests: `tests/test_router_plugin.py`.
