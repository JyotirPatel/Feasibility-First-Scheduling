# Research gap and proposed contribution — midterm note

Owner of the wording: Krupesh (Work Distribution: novelty wording). Draft for team review.
Sources: Group 20 Final Proposal (§2, §4, §6, references [1]–[5]) and Project Brief §3, §14.
**No experimental results are claimed here** — full evaluation belongs to the final stage.

## Proposed contribution (one sentence)

An **integrated feasibility-first, change-aware routing system for geographically distributed AI
inference, evaluated for recovery after abrupt infrastructure changes.** Sliding-window LinUCB is an
existing method that we use inside this system.

## What already exists (and what we do not claim)

| Prior work | What it does | What it leaves open for us |
|---|---|---|
| Energy-geography framework — Luo & Yang, arXiv:2604.27855, 2026 [1] | geo-distributed placement with latency, electricity, carbon and feasibility constraints | planned optimisation in a stylised simulation; no online learning and no measurement of recovery after sudden changes |
| TAPAS — Stojkovic et al., ASPLOS 2025 [2] | thermal- and power-aware LLM placement and request routing inside cloud clusters | not geo-distributed node selection under changing network and regional energy conditions; no bandit adaptation |
| WISERouter — Li, Gao, Lakshmanan, arXiv:2607.23765, 2026 [3] | contextual-bandit routing among different LLM *models* under a workload budget | selects models for quality/cost, not infrastructure nodes with GPU, network, power and thermal constraints |
| MAB for edge computing — Ghoorchian & Maghsudi, IEEE TCCN 2020 [4] | bandits for energy-efficient, delay-sensitive edge computing under uncertainty | not LLM inference with SLO context and hard feasibility rules |
| LinUCB — Li et al., WWW 2010; SW-LinUCB — Cheung, Simchi-Levi & Zhu, AISTATS 2019 | contextual bandit; sliding-window forgetting for non-stationary rewards | **existing algorithms — we use them, we do not claim them** |
| DistServe — Zhong et al., OSDI 2024 [5] | goodput as the serving metric | serving-engine layer, not geo routing (we adopt its goodput metric) |

**Gap (proposal §2):** to the best of our literature review, no single evaluated system combines
(1) geo-distributed GPU-node selection, (2) hard feasibility filtering, (3) inference-specific SLO
context, and (4) fast online adaptation to abrupt changes.

## What is distinctive in our system

1. **Feasibility first.** Model, memory/capacity, power and temperature rules are enforced *before*
   any learning or cost trade-off. Every policy — baselines and learning — receives the same filtered
   set, and the router refuses any choice outside it (implemented and tested in Krupesh's router:
   `tests/test_engine.py::test_policy_cannot_bypass_filter`).
2. **Change aware.** The learning policy (Sur) uses request + node context and a sliding observation
   window so stale outcomes are forgotten after a change.
3. **Recovery as a first-class result.** Six controlled change events and a precise adaptation-time
   metric, reported with the new steady level G*, the deepest dip and lost goodput — answering
   Professor Liu's request to define adaptation time precisely.

## Planned evaluation (later stage — not done for the midterm)

| Dimension | Plan (proposal §6, brief §8) |
|---|---|
| Scenarios | stable; traffic burst; price/renewable shift; thermal throttling; network degradation; outage + recovery (600 s, change at t0 = 200 s) |
| Baselines | round-robin, min RTT, least load, lowest energy cost, static weighted, (power of two), plain LinUCB |
| Metrics | SLO goodput, p95/p99 latency, rejection rate, cost and energy per successful request, adaptation time with G* |
| Analysis | ≥ 10 seeds per scenario, 95 % bootstrap CIs, window-size sensitivity, ablations (no filter, no context, no forgetting) |
| Success criteria | better goodput or cost than the strongest baseline without unsafe placements; faster recovery than plain LinUCB; negative results reported |

## Midterm status of this contribution

- **Done (Krupesh):** the router that enforces feasibility-first routing, the shared contracts, the
  decision log that the whole evaluation will be computed from, and tests of these guarantees.
- **Pending (teammates):** simulator and change events (Parikshit), LinUCB/SW-LinUCB and reward (Sur),
  metrics and experiments (Riya). Jyotir's filter and baselines already run through the router.
