# Sur / checkpoints

**Owner:** Sur. This folder holds saved learned state of the LinUCB policies, which is the "checkpoints" deliverable.

`standin/` is written by `window_sweep/run_sweep.py` for the runs listed under `checkpoints:` in `window_sweep/sweep.yaml`. Those are the default plain and sliding-window policies at the end of S1 and S6, seed 0, on the **stand-in simulator**. They show what the policies learned there, for example which features each node's θ weights. They are not final; regenerate them on Parikshit's simulator.

| File | Policy | Scenario |
|---|---|---|
| `standin/linucb_alpha=1__s1_stable_seed0.npz` | plain LinUCB | S1 stable |
| `standin/linucb_alpha=1__s6_outage_recovery_seed0.npz` | plain LinUCB | S6 outage + recovery |
| `standin/sw_linucb_per_node_W=1000_alpha=1__s1_stable_seed0.npz` | sliding window, per-node, W = 1000 | S1 stable |
| `standin/sw_linucb_per_node_W=1000_alpha=1__s6_outage_recovery_seed0.npz` | sliding window, per-node, W = 1000 | S6 outage + recovery |

Example of what they contain: in the S1 sliding-window checkpoint, us-east-1's largest learned weight is a negative one on `input_tokens`. Long prompts mean longer prefill and a later first token, which is the physics the stand-in simulates. `tests/test_shipped_checkpoints.py` checks that every file here loads and scores.

Load one into a policy with the same config:

```python
from sliding_window_linucb import SlidingWindowLinUCB

policy = SlidingWindowLinUCB()
policy.load_checkpoint("checkpoints/standin/<file>.npz")
print(dict(zip(policy.features.names, policy.theta("us-east-1"))))
```

The format is a NumPy `.npz` file, readable without pickle. It holds:
- `A`, `b` and the outcome count for every node;
- for the sliding window, the outcomes still in the window and their order;
- a `meta` JSON with the format version, policy name, feature names, full config, random-generator state, stats and save time.

Loading refuses a file from another policy type or with a different λ, features, reward or window. It also refuses files with corrupted numbers.
