# Sur / linucb

**Owner:** Sur. **Used by:** the router (Krupesh) as a pluggable policy, and Riya as the "no forgetting" ablation.

`linucb.py` implements plain LinUCB (Li et al., 2010; brief §6.4) with one model per node:

- start: `A_a = λI`, `b_a = 0` (λ = 1)
- estimate: `θ_a = A_a⁻¹ b_a`
- score: `θ_aᵀx + α·√(xᵀA_a⁻¹x)`; choose the highest-scoring **candidate** (candidates are the filter's allowed nodes)
- update the chosen node only: `A_a ← A_a + xxᵀ`, `b_a ← b_a + r·x`

```python
from linucb import LinUCB

policy = LinUCB()  # reads configs/policies/linucb.yaml
node_id = policy.choose(request, allowed_nodes)  # allowed_nodes = the filter's output
...
policy.update(request, node_id, outcome)  # after POST /feedback
log_row["reward"] = policy.last_reward
```

## Details that matter for integration

- **It subclasses the shared `Policy` stub**, `Jyotir/stubs/stub_policy.py`, exactly like Jyotir's baselines. For Krupesh's router, `router_plugin.RouterLinUCB` is this same class with his `router_service.policy_base.Policy` added as a base (see `../router_plugin/`). When the team merges into one layout, the stub import here can become his base class directly.
- **It accepts dicts or objects.** Requests, nodes and outcomes are read by field name, so Jyotir's filter output (dicts) and Krupesh's `Request` / `NodeState` / `Outcome` dataclasses give the same context vector and the same choice.
- **Delayed feedback is handled inside.** `choose()` stores the exact `x` it used and the node's temperature and price, keyed by `request_id`. `update()` learns from those, never from newer telemetry. Feedback can arrive in any order.
- **The reward is computed by the policy** (`reward/`), so a placeholder from the router cannot corrupt learning. The value used is in `last_reward`.
  - Krupesh's router fills `outcome.reward` before `update()`. With Sur's `router_plugin.reward_fn` that is the same number.
  - If a filled-in value differs, the router is probably using another reward function (such as his `mock_reward`). The policy then learns from its own value, counts the difference in `stats["reward_mismatch"]`, and logs one warning.
- **Safe with bad feedback.** Feedback that is unknown, duplicated, or names a node other than the one chosen is ignored and counted in `stats`. A malformed outcome raises an error and leaves the decision pending for a retry.
- **Pending decisions are capped** by `max_pending` (100,000), so feedback that never arrives cannot grow memory without bound.
- **Reproducible.** Exact score ties are broken by a seeded random generator; `LinUCB(seed=...)` overrides the config seed per run.
- **Thread-safe.** `choose`, `update`, `save_checkpoint` and `load_checkpoint` take a lock.
- **Checkpoints:**
  - `save_checkpoint(path)` writes A, b, counts, the config and the random-generator state to a `.npz` file, without pickle, through an atomic temp file and rename.
  - `load_checkpoint(path)` restores the model, the stats, the random-generator state and the run's seed. It refuses a file from another policy type, or one whose λ, features or reward differ.
  - It also refuses broken numbers, such as an A that isn't positive definite.
- **Inspection:** `explain(request, candidates)` gives each candidate's estimate, bonus and score without recording a decision. `theta(node_id)` returns the learned weights, aligned with `policy.features.names`.

Tests: `tests/test_linucb.py`.
