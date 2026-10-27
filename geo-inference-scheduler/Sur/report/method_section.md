# Method: choosing a node with a learning policy

*Draft by Sur for the report. Riya merges it into the full report. Citation keys refer to `../citations/references.bib`. Numbers marked "stand-in" come from the window sweep on the stand-in simulator and must be refreshed after the re-run on the project simulator.*

## Where the policy sits in the loop

For every request, the router runs four steps: filter, choose, send, learn. The learning policy handles steps 2 and 4.

The feasibility filter runs first. It removes every node that cannot or must not serve the request: the model is not loaded, the KV cache is full, there is no power headroom, the node is too hot, or it is down. The policy only ever sees the remaining *candidates* and returns one of them. It therefore cannot trade a hard rule for a better score, and every comparison between policies differs only in the choosing step. In our experiments the simulation checks this on every decision: a policy that returned any other node would stop the run.

After the request finishes, the simulator reports its outcome (TTFT, end-to-end time, whether the SLO was met, energy, cost). The policy turns that outcome into a reward and updates its model.

## Context vector

For a request *q* and a candidate node *a*, the policy builds a vector **x** ∈ [0, 1]^14. Each raw number is min-max scaled with a fixed range from the configuration file and then clipped to [0, 1]. Values that are already fractions are only clipped.

| Group | Features |
|---|---|
| Constant | bias = 1 (lets each node's model learn its own base level) |
| Request | input length; expected output length; SLO class (one 0/1 flag per class); TTFT deadline |
| Node telemetry | network delay from the user's region to the node; queue length; running requests ÷ capacity; KV-cache use; electricity price; GPU price; temperature; warming-up flag |

The engine signals — queue length, running requests and KV-cache use — are expected to matter most. Fixed (not data-dependent) scaling keeps the meaning of every feature identical across runs, so learned weights can be compared and checkpoints reused.

For the **"no context" ablation**, **x** = [1]. Each node then has a single average reward and uncertainty bonus, which makes the policy a plain, non-contextual bandit.

## Reward

After each request the policy receives

> r = w₁·[SLO met] − w₂·latency − w₃·energy cost − w₄·thermal stress

The terms are defined as follows:
- **[SLO met]** is 1 if the request met its TTFT SLO and 0 otherwise.
- **Latency** is the TTFT divided by a fixed maximum (1000 ms), clipped to [0, 1].
- **Energy cost** is the request's energy times the node's electricity price, divided by a fixed maximum and clipped.
- **Thermal stress** rises linearly from 0 at 60 °C to 1 at the filter's 85 °C limit.

The weights (1.0, 0.2, 0.1, 0.1) make the SLO term dominate: because w₁ > w₂ + w₃ + w₄, meeting the SLO always scores higher than missing it, whatever the other terms are. The reward therefore lies in [−0.4, 1].

A request lost to a failure, such as a node going down mid-request, gets the worst value for every term it cannot measure. Electricity price and temperature are taken from the node's telemetry *at decision time*, which the policy keeps until the outcome arrives.

## LinUCB

We use LinUCB [li2010contextual] with one linear model per node, the "disjoint" variant. Node *a* keeps a matrix **A**ₐ and a vector **b**ₐ, initialised to **A**ₐ = λ**I** (λ = 1) and **b**ₐ = **0**. For a request, every candidate is scored:

> θₐ = **A**ₐ⁻¹ **b**ₐ,    scoreₐ = θₐᵀ**x**ₐ + α·√(**x**ₐᵀ **A**ₐ⁻¹ **x**ₐ)

The first term is the predicted reward. The second is an exploration bonus that is large for nodes the policy is unsure about and shrinks as the node is observed; α sets how much to explore. The policy picks the candidate with the highest score, breaking exact ties uniformly at random with a seeded generator, so every run is reproducible. When the outcome of the chosen node arrives, only that node's model is updated:

> **A**ₐ ← **A**ₐ + **x x**ᵀ,    **b**ₐ ← **b**ₐ + r·**x**

**Delayed feedback.** An outcome arrives seconds after its decision, by which time the node's telemetry has changed and other decisions have been made. The policy therefore stores, per request id, the exact **x** it scored and the node values the reward needs, and learns from those, not from newer telemetry. Outcomes may arrive in any order. Feedback for an unknown or already-used request id is ignored and counted, so no outcome is learned twice.

## Sliding-window LinUCB

Plain LinUCB never forgets: an outcome from long ago weighs as much as one from a second ago. After a change — a traffic burst, a price shift, a node that overheats or returns from an outage — old outcomes describe a node that no longer exists. Following [cheung2019learning], sliding-window LinUCB keeps only the most recent W outcomes. Cheung et al. analyse a single parameter vector shared by all actions; we apply their window to each node's own model. When an outcome leaves the window, its contribution is subtracted:

> **A**ₐ ← **A**ₐ − **x x**ᵀ,    **b**ₐ ← **b**ₐ − r·**x**

A small W reacts quickly but estimates from few outcomes, so it is noisy and explores more. A large W is stable but slow to notice a change. Plain LinUCB is the limit W → ∞ and serves as the "no forgetting" ablation.

The brief leaves open whether "the last W" is counted per node or over all decisions, so we implemented both:

- **Per-node window:** each node keeps its own last W outcomes.
- **Global window:** the last W outcomes over all nodes, as in [cheung2019learning].

The two differ in an important way. In LinUCB the matrix **A**ₐ, which sets a node's exploration bonus, only changes when that node's own outcomes arrive. Under a per-node window, a node the policy has stopped choosing keeps its last W outcomes indefinitely, so its estimate never refreshes and it may never be tried again, even after it recovers. Under a global window those outcomes age out as other nodes are used; the node's bonus grows back to its prior value and it is re-explored. In the controlled two-node test in `tests/test_sw_linucb.py` (seeds 0–2), a global window gave 99.0–99.3 % of requests to a node that improved after being abandoned; a per-node window and plain LinUCB gave it none.

The window counts outcomes, not seconds. At a request rate ρ, a global window spans about W/ρ seconds of history, and a per-node window spans W/ρₐ seconds for a node receiving ρₐ requests per second.

Repeated subtraction accumulates rounding error, so after every 1000 removals (a configuration setting) a node's **A**ₐ and **b**ₐ are rebuilt exactly from the outcomes still in its window. A node whose window empties returns exactly to its prior.

## Parameters

λ = 1, as specified in the brief. Window size, window mode and α are chosen with the window sweep (window_sweep/RESULTS.md):
- W ∈ {200, 500, 1000, 2000, 5000}, plus 10000 and 20000;
- both window modes;
- α ∈ {0.1, 0.5, 1, 2};
- six scenarios × 10 seeds, with 95 % bootstrap confidence intervals.

On the stand-in simulator (*preliminary*), the sweep showed:

- **Forgetting costs goodput while nothing changes.** In the stable scenario, a per-node window of W = 1000 met the SLO for 94.6 % of requests, against 98.6 % for plain LinUCB. The gap closed as W grew: 97.6 % at W = 5000 and 98.5 % at W = 20000.
- **No sliding-window setting beat plain LinUCB on mean goodput, in any of the six scenarios.** A likely reason is that every change in these scenarios is visible in the context features, so a contextual model reacts without needing to forget.
- **One adaptation-time result favoured a window.** After the traffic burst, a per-node window of W = 5000 regained 90 % of the new steady goodput in 4.6 s [1.3, 8.1], against 12.1 s [8.5, 15.5] for plain LinUCB, though with slightly lower goodput during the burst. No other scenario showed a window adapting faster.
- **A per-node window can abandon a node that recovers.** When the S6 node came back, the outcomes of the requests lost in its outage were the newest evidence in its window, and they made its estimate erratic. Windows of W ≤ 2000 then gave it under 1 % of requests in 3–7 of 10 seeds (W = 5000: 1 of 10). A short adaptation time measured after its return can therefore reflect this abandonment rather than faster recovery.
- **Global windows were worse than per-node windows at every W ≥ 1000, in every scenario.** They also collapsed when the S6 node returned: goodput fell to 23–32 requests/s on average, against 78 for plain LinUCB. The forgotten node looked new to the policy, so its exploration bonus was large, and it attracted a burst of requests while still warming up. A bug in the feasibility filter, which let the warming node accept requests after its memory was full, made that burst much worse; it must be fixed before the final runs.
- **No α was best on every measure.** α = 0.1 and 0.5 gave 0.9–1.4 % more goodput while stable. After the burst α = 1 adapted fastest, and after the outage α = 0.5 did, but all these confidence intervals overlap. Smaller α abandoned the returned S6 node more often.

We therefore use a per-node window and α = 1. W stays at 1000 until the sweep is repeated on the project simulator. On the stand-in, the best window within the brief's range was W = 5000: its goodput was within 1.1 % of plain LinUCB's in every scenario, and it adapted faster than plain LinUCB after the burst. Because no window beat plain LinUCB overall, the report should not claim that forgetting helps unless the re-run shows it.

All parameters are stored in configuration files; none are fixed in code. The three policy files (sliding window, plain, no context) differ only in the ablated component, which a test enforces.

## Related work: bandits for changing environments

A contextual bandit picks one option per round using side information and observes the reward of that option only. LinUCB [li2010contextual] models each option's expected reward as linear in a context vector and adds an upper-confidence bonus. It was introduced for news recommendation and is a standard choice when decisions must be made online with partial feedback, as in request routing.

Classical bandit algorithms assume the rewards do not change. For abruptly changing rewards, [garivier2011switching] showed that forgetting old observations helps, through a discount factor (discounted UCB) or a sliding window (sliding-window UCB), and proved regret bounds that match a lower bound up to a logarithmic factor. [cheung2019learning] (journal version [cheung2022hedging]) extended the sliding-window idea to linear bandits whose parameter drifts. [russac2019weighted] proposed exponential discounting instead of a window (D-LinUCB), which needs no storage of past actions. Later work reported mistakes in existing regret analyses of forgetting-based methods for drifting (generalized) linear bandits [faury2021technical], so we treat sliding-window LinUCB as a practical method and evaluate it empirically instead of relying on its theoretical guarantee.

These methods are not our contribution. We use LinUCB and its sliding-window variant inside a larger system. Our contribution is the integrated, feasibility-first, change-aware scheduling loop for multi-site LLM inference — hard-rule filter, contextual choice and forgetting — and a recovery benchmark with six controlled change events and a precise adaptation-time metric.
