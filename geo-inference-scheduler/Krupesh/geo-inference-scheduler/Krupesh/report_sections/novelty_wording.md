# Novelty wording — owner: Krupesh (Work Distribution task 6)

Professor Liu's comment: *"Frame the novelty around the full scheduling system and recovery
evaluation, not around sliding-window LinUCB itself."*

## Slide 4 — replacement text

**Title:** What is new in this project

- **An integrated scheduling loop for multi-site LLM inference:** hard feasibility rules first,
  then a context-aware choice, then learning from delayed outcomes — inside one real HTTP router.
- **A recovery benchmark:** six controlled change events (stable, traffic burst, price shift,
  thermal throttle, network degradation, outage + recovery) with a precise adaptation-time metric.
- **What we reuse:** LinUCB (Li et al., 2010) and sliding-window LinUCB (Cheung, Simchi-Levi & Zhu,
  2019) are existing methods. We use them inside the loop; we do not claim them.

## Report — contribution list (replace the old list)

> We contribute an integrated, feasibility-first, change-aware scheduling loop for multi-site LLM
> inference and a recovery benchmark with six controlled change events. Sliding-window LinUCB is an
> existing method that we use inside this loop.

1. **Feasibility-first loop.** Every request passes hard rules (model loaded, KV memory, power
   headroom, temperature, node status) before any policy chooses; all policies — baselines and
   learning — see the same filtered set, and no policy can override the filter to save cost.
2. **Change-aware choice.** The policy uses request and node context and forgets stale history, so it
   can follow changes in load, price, temperature, network delay and node health.
3. **Recovery benchmark and metric.** Six controlled change events at t0 = 200 s, and an exact
   adaptation-time definition (return to ≥ 90 % of the new steady goodput G\* for 10 s), always reported
   with G\*, the deepest dip and the goodput lost compared with a reference.

## Phrases to avoid

- "We propose a new bandit algorithm" / "our sliding-window LinUCB" → say "the existing
  sliding-window LinUCB (Cheung et al., 2019)".
- "Optimal" / "guaranteed to recover" — not claimed.
