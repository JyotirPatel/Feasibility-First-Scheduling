# Sur / configs / policies

**Owner:** Sur. This folder holds the YAML parameter files for the bandit policies, matching the brief's planned `configs/policies/`:

- `sw_linucb.yaml`: sliding-window LinUCB, the main policy.
- `linucb.yaml`: plain LinUCB, the "no forgetting" ablation.
- `sw_linucb_no_context.yaml`: the "no context" ablation.

Each file holds α, λ, the seed, the pending-decision cap, the feature ranges and the reward weights; the sliding-window files also hold the window. See `../README.md` for what each setting means.
