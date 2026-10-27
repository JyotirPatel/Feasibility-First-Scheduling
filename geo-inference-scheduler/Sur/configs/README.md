# Sur / configs

**Owner:** Sur. **Used by:** everything in Sur's folder, plus the router and experiment runner when they load Sur's policies.

These are the parameter files. All of Sur's numbers live here and none are in Python, which is the repo rule in brief §13. These paths match the brief's planned `configs/policies/`.

| File | Policy | Notes |
|---|---|---|
| `policies/sw_linucb.yaml` | sliding-window LinUCB (main policy) | α, λ, seed, window (W, mode, rebuild), features, reward |
| `policies/linucb.yaml` | plain LinUCB ("no forgetting" ablation) | identical to `sw_linucb.yaml` except it has no window |
| `policies/sw_linucb_no_context.yaml` | "no context" ablation | identical to `sw_linucb.yaml` except `features.use_context: false` |

`tests/test_configs.py` checks that the ablation files differ from the main one only where they should, so a comparison never mixes up two changes. Each file is validated on load and rejects:
- unknown keys, which catches typos;
- negative weights;
- an empty or zero-width range;
- NaN or infinity.

Values marked *(default)* in the comments are starting choices. Feature ranges and the `batch` SLO class are placeholders until Parikshit's telemetry ranges and Krupesh's class list are frozen.
