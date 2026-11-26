# Notes on the final evaluation: two results about the learning policy

*Sur, 2026-11-26. The numbers come from Riya's frozen final bundle (`Riya/experiment_runner/results/final_02`) and from re-running ten of its runs through the same pipeline. Each re-run reproduces her goodput curve exactly. `python3 window_sweep/final_eval_check.py` prints every number below in about 2 minutes; `--no-reruns` prints only the parts that read saved results (0–3).*

Riya's final report raises two questions about the learning policy:

1. **Why does the "no context" ablation beat the full SW-LinUCB in S4, S5 and S6?** Keeping context costs −1.17 [−1.64, −0.75] req/s in S6, and the intervals also favour no context in S4 and S5.
2. **Why does SW-LinUCB recover more slowly than plain LinUCB after the S6 outage?** It takes 18.3 s, against 9.9 s.

## Short answers

- **No context wins S4–S6 because of how the full policy divides work between sites, not because context is useless.**
  - In S4 and S5 the whole gap comes from 3 of 10 seeds. In those seeds the full policy had sent almost all interactive requests to New York before the change. San Jose's model had therefore seen only a few very long interactive prompts, which miss the deadline at any site.
  - When New York slowed down, that model predicted that interactive requests would fail at San Jose (estimate −0.03; they actually earn 0.78–0.79 there). So the policy kept 92 % of them on New York.
  - The no-context policy keeps one average per site. When New York's average drops, it moves almost everything to San Jose, which can carry the whole load at 80 req/s.
- **The same all-or-nothing behaviour sinks the no-context policy in S2.** One site cannot carry three times the load, and context is worth +36 req/s there.
- **The slower S6 recovery is mostly a measuring effect.**
  - SW-LinUCB settles at a higher level after the outage (G\* 70.45 against 68.18 req/s), so its own 90 % bar is higher.
  - Against one shared bar the two times are 10.9 s and 9.9 s.

## 1. The no-context advantage comes from three seeds

Full minus no-context goodput, from 220 s to the end of the run (req/s):

| Seeds | S4 thermal | S5 network | S6 outage |
|---|---|---|---|
| 3, 8, 9 | −3.7 to −4.1 | −7.7 to −8.0 | −1.6 to −3.3 |
| the other seven | −0.2 to +0.1 | 0.0 to +0.3 | −0.3 to −1.7 |

Seeds 3, 8 and 9 are the seeds where the full policy had put most traffic on New York before any change: 71–73 % of requests, against 26–27 % in the other seven. Every S4–S6 change hits New York.

## 2. Why the full policy keeps interactive requests on New York (S5)

Each site has its own model, and that model learns only from the requests sent to its site. Before the change, the full policy splits the two H100 sites by request type. Which site gets the interactive requests depends on the seed.

| S5, full policy | Seeds 3, 8, 9 | Seed 0 (a typical seed) |
|---|---|---|
| Interactive requests sent to New York, before → after the change | 92–96 % → 92 % | 2 % → 2 % |
| San Jose's window when the change hits: share that is interactive | 3–5 % | 93 % |
| Median input of those interactive requests (a typical one: 1,020 tokens) | 4,088–4,752 tokens | 1,029 tokens |
| Predicted reward of an interactive request after the change: New York / San Jose | 0.60 / −0.03 | −0.06 / 0.79 |
| What interactive requests actually earn at San Jose (no-context runs) | 0.78–0.79 | 0.78 |
| West-coast users sent to New York after the change; their SLO rate there | 60–61 %; 0.51–0.52 | 25 %; 0.97 |
| SLO rate after the change: full / no context | 0.81 / 0.90–0.91 | 0.91 / 0.90 |

- **A wrong belief.** In seeds 3, 8 and 9, San Jose's model has seen only the rare extra-long interactive prompts, which miss the 250 ms deadline anywhere. It therefore predicts that every interactive request does badly at San Jose.
- **Exploration does not correct it.** San Jose's exploration bonus (0.17) is far smaller than the gap between the two predictions (0.60 against −0.03). So the policy never tries an ordinary interactive request at San Jose, and never finds out that the belief is wrong.
- **Forgetting does not correct it either.** The sliding window drops old outcomes, but it cannot collect the ones that were never observed. San Jose's window keeps refilling with the same kind of long prompts.
- **In the other seeds** San Jose already serves the interactive requests, so its estimate is accurate (0.79 against 0.78) and the change to New York barely matters.

## 3. The S6 outage

During the outage (seed 0, 220–400 s):

| Policy | San Jose: share / SLO rate | Los Angeles (A100): share / SLO rate | SLO rate, all sites |
|---|---|---|---|
| Full | 83 % / 0.89 | 17 % / 0.76 | 0.86 |
| No context | 100 % / 0.90 | – | 0.90 |

- **The full policy picks Los Angeles because its models predict those requests do better there** (0.66 against 0.46 for San Jose).
  - It is not because San Jose was busier: San Jose's load was lower when the policy chose Los Angeles (0.58 of capacity) than when it chose San Jose (0.65).
  - The cause is the same as in S5: each site's model knows only the requests that were sent to it.
- **After New York returns, the no-context policy never goes back to it.** New York gets 0 % of its traffic in all ten seeds, against 31 % on average for the full policy.
  - With one average per site, New York's score stays below San Jose's. Since nothing is sent there, nothing can raise it.
  - At 80 req/s San Jose carries the load, so this costs no goodput here. With less spare capacity it would.

## 4. The S6 recovery time

Adaptation time after the outage, as the mean of ten seeds. The frozen definition is 10 s at or above the bar.

| Bar | SW-LinUCB | Plain LinUCB |
|---|---|---|
| Each policy's own: 0.9 × its G\* | 18.3 s | 9.9 s |
| Shared: 0.9 × the lower G\* of the two | 10.9 s | 9.9 s |

- SW-LinUCB settles at a higher level after the outage (G\* 70.45 against 68.18 req/s), so its own bar is higher and takes longer to clear.
- Seeds 1, 2 and 6 account for most of the difference. With their own bars SW-LinUCB takes 36, 24 and 21 s; at the shared bar it takes 0, 4 and 11 s, the same as plain LinUCB.
- Seed 9 is a real delay: 22 s against 3 s at either bar.

## 5. What this means for the method

- **Context is what lets the policy handle load.** Without it, the S2 burst costs 36 req/s.
- **The price of per-site models is that each learns only from what its site is sent.** A policy that specialises sites by request type can hold a wrong belief about a site for the type it never sends there, and a sliding window does not correct it.
- **The scenarios expose this.** Every S4–S6 change hits New York, and at 80 req/s one H100 site can carry the whole load, so moving everything at once is the right answer.
- **Possible fixes, not tested here:**
  - share what is learned between sites (one model with site features);
  - force a little exploration per request type;
  - raise α, a blunt option: in the window sweep, α = 2 abandoned the returned S6 node in 3 of 10 seeds.

## Suggested text for the final report

For the Discussion, after "Context does not improve every condition":

> In S4 and S5 the advantage of the constant-context variant comes from three of the ten seeds. In those seeds the full policy had routed almost all interactive requests to New York before the change, so San Jose's model had seen only a few very long interactive prompts and predicted that interactive requests would fail there; when New York degraded, the policy kept them on New York. A sliding window cannot correct such a belief, because it forgets old outcomes but does not collect missing ones.

For section 4, after the recovery table:

> SW-LinUCB's longer S6 outage time largely reflects its higher steady level (G\* 70.45 against 68.18 requests/s). Against a common threshold of 0.9 times the lower G\*, the two policies take 10.9 s and 9.9 s.
