# Sur / checkpoints

**Owner:** Sur. This folder holds saved learned state of the LinUCB policies, which is the "checkpoints" deliverable.

## `simulator/`: current checkpoints

`window_sweep/run_sweep.py` writes `simulator/` for the runs listed under `checkpoints:` in `window_sweep/sweep.yaml`. Those runs are the shipped default policies at the end of S1 and S6, seed 0, on **Parikshit's simulator through Krupesh's router**:
- plain LinUCB;
- sliding-window LinUCB with a per-node window of W = 500 and α = 1.

They were saved with the current configs, so they load into a default policy.

| File | Policy | Scenario |
|---|---|---|
| `simulator/linucb_alpha=1__s1_stable_seed0.npz` | plain LinUCB | S1 stable |
| `simulator/linucb_alpha=1__s6_outage_recovery_seed0.npz` | plain LinUCB | S6 outage + recovery |
| `simulator/sw_linucb_per_node_W=500_alpha=1__s1_stable_seed0.npz` | sliding window, per-node, W = 500 | S1 stable |
| `simulator/sw_linucb_per_node_W=500_alpha=1__s6_outage_recovery_seed0.npz` | sliding window, per-node, W = 500 | S6 outage + recovery |

**What the S1 sliding-window checkpoint learned:**
- On the three A100 sites, the largest weight is a strongly negative one on `input_tokens` (−1.3 to −1.8): a long prompt misses the 250 ms SLO there.
- New York's H100 learned to prefer batch requests (+0.43 on the batch flag), which is where the policy sends them.
- The two H100 windows are full (500 outcomes each). The rarely used A100 sites still hold only their older outcomes (113–315), as a per-node window does.

## `standin/`: earlier checkpoints

`standin/` holds the earlier checkpoints from the sweep on the stand-in simulator. They were saved with the earlier configs: per-node W = 1000 and the energy scale $0.0002. Load them with the config stored in each file, as `tests/test_shipped_checkpoints.py` does; a default policy refuses them.

`tests/test_shipped_checkpoints.py` checks that every file in both folders loads and scores.

## Loading one

Load a checkpoint into a policy with the same config:

```python
from sliding_window_linucb import SlidingWindowLinUCB

policy = SlidingWindowLinUCB()
policy.load_checkpoint("checkpoints/simulator/sw_linucb_per_node_W=500_alpha=1__s1_stable_seed0.npz")
print(dict(zip(policy.features.names, policy.theta("us-east-buf"))))
```

**File format.** Each checkpoint is a NumPy `.npz` file, readable without pickle. It holds:
- `A`, `b` and the outcome count for every node;
- for the sliding window, the outcomes still in the window and their order;
- a `meta` JSON with the format version, policy name, feature names, full config, random-generator state, stats and save time.

**What loading refuses:**
- a file from another policy type;
- a file with a different λ, features, reward or window;
- a file with corrupted numbers.
