# Sur / reward

**Owner:** Sur. **Used by:**
- the LinUCB policies, which learn from it;
- the router (Krupesh), which can fill the decision log's `reward` column with it;
- Riya, who reads that column.

`reward.py` computes the reward of brief §6.3:

```
r = w1·[SLO met] − w2·latency − w3·energy cost − w4·thermal stress
```

| Term | Definition | Scaled to 0..1 by |
|---|---|---|
| `[SLO met]` | `outcome.slo_met` (1 or 0) | — |
| latency | the outcome's `ttft_ms` (or `e2e_ms`, set by `latency_metric`) | `/ latency_max_ms`, clipped |
| energy cost | `energy_kwh × node electricity price` at decision time (`energy_cost_source: energy_usd`), or the outcome's total `cost_usd` (`cost_usd`) | `/ energy_cost_max_usd`, clipped |
| thermal stress | the node's temperature at decision time | linear from `thermal_safe_c` (0) to `thermal_limit_c` (1) |

Defaults (in `configs/policies/*.yaml`): weights 1.0 / 0.2 / 0.1 / 0.1, so **the SLO term dominates**: meeting the SLO always beats missing it. That gives r ∈ [−0.4, 1.0]. `thermal_limit_c` equals Jyotir's filter limit (85 °C), and a test keeps them equal.

**Failures:**
- A missing value (`None`), NaN or infinity, such as a request lost in an outage, gets the worst value for its term, so a failure never scores better than a slow success.
- A negative time or energy is a data error and raises `ValueError`.
- A missing `slo_met` raises `KeyError`.

```python
from reward import compute_reward, reward_terms

r = compute_reward(node_snapshot_at_decision, outcome, config["reward"])
```

`node` must be the snapshot the policy saw when it chose. The policy keeps that snapshot itself, so a router calling `compute_reward` should pass the same candidate dict it gave to `choose()`.

Tests: `tests/test_reward.py`.
