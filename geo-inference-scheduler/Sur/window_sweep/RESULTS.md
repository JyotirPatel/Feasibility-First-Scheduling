# Window-size sweep: results

**Owner:** Sur. **For:** Riya (window-size ablation and method section) and the whole team.

This sweep ran on the project's real pipeline:
- Parikshit's simulator;
- Krupesh's router, with Jyotir's filter;
- Sur's reward (`parikshit_backend.py`).

It supersedes the earlier sweep on the stand-in simulator (`RESULTS_standin.md`), whose main conclusions it reverses: here, forgetting helps after the traffic burst and costs nothing elsewhere.

## What was run

- **Runs:** 1,350 on 16 processes, in 1,258 s (about 21 min).
  - Provenance is in `results/manifest.json`: git commit `6f9100c` with this update on top, and SHA-256 hashes of every config file. The hashed files are the sweep, policy and filter configs, and Parikshit's nodes, workload, calibration and six event traces.
  - The runs are deterministic. The sweep ran twice, before and after the default window changed, and every run present in both gave identical numbers.
- **Pipeline:** the same one Riya's experiment runner uses.
  - **Parikshit's simulator:**
    - 5 sites (2 H100, 3 A100), with real Azure request traces at 80 requests/s and real prices and pings;
    - S1–S6, 600 s each, change at t0 = 200 s;
    - 10 seeds, with the same requests for every policy.
  - **Krupesh's router:**
    - Jyotir's filter on every decision;
    - his load accounting between the 1-s telemetry ticks;
    - the decision log.
  - **Sur's reward:** built from each policy's own reward section, with the energy scale set to $0.00001 (see "Reward scale" below). The router's and the policy's rewards agree in every run (`reward_mismatch` = 0).
- **Policies:**
  - Sliding-window LinUCB with W ∈ {200, 500, 1000, 2000, 5000} (the brief's sweep), plus 10000 and 20000. Each size runs as a **per-node** and as a **global** window, with α = 1.
  - Plain LinUCB, the "no forgetting" reference.
  - An α check: α ∈ {0.1, 0.5, 1, 2} on S1, S2 and S6, with a per-node window of W = 500.
  - Jyotir's six baselines, as a reference only. The main comparison is Riya's.
- **Where the traffic goes.** The learned policies send almost everything to the two H100 sites. With a per-node window of W = 500 in S1 (seed 0):

  | Site | Share of requests | Rate | Traffic |
  |---|---|---|---|
  | San Jose (H100) | 72 % | 57.6 req/s | almost all interactive requests |
  | New York (H100) | 26 % | 21.1 req/s | mostly batch |
  | the three A100 sites | 1.5 % together | — | — |

  - So a per-node window of W = 500 covers about 9 s of San Jose's history and 24 s of New York's.
  - A global window covers about W ÷ 80 s of all traffic, so W = 500 ≈ 6 s.
- **Metrics:** the frozen definitions of work distribution §6.
  - **Goodput:** 1-s bins by arrival time, smoothed over 5 s.
  - **G\*:** the mean goodput from t0 + 60 s to t0 + 120 s.
  - **Adaptation time:** the first moment G ≥ 0.9·G\* holds for 10 s.
  - **Deepest dip:** the lowest goodput in [t0, t0 + 120 s).
  - **S6** is also measured from the node's return at 400 s, together with the returned node's traffic share and the "rush" (seconds after its return in which it got ≥ 50 % of requests).
- **Numbers:**
  - Every table entry is **mean [95 % bootstrap CI]** over the 10 seeds.
  - `make_tables.py` generates every table from `results/summary.csv`, and `tests/test_figures_and_tables.py` fails if a table here differs from the bundle.
  - Per-seed numbers in the text come from `results/runs.csv`.

## Findings

1. **The learned policies beat every baseline in every scenario (Table E).**
   - **S1 goodput.** Plain LinUCB and every per-node window reach 72.2 req/s and meet the SLO for 90.7 % of requests. The best baseline, lowest-energy, reaches 61.0 req/s and the others 54.5–59.0 req/s; the baselines meet the SLO for 68–77 % of requests.
   - **Why.** The policies learned the interaction the simulator was calibrated to have: an A100 cannot start 59.5 % of interactive requests within 250 ms even when idle, while an H100 misses only 10.2 % (Parikshit's `report/simulator_section.md`).
   - **Cost.** They are also about 2–2.5 times cheaper per SLO-met request: 259–312 µ$ in S3, against 522–677 µ$ for min-RTT, static-weighted, least-load, power-of-two and round-robin (Table F). They keep the busy sites busy, and a lightly used site costs more per request.

2. **Per-node windows cost nothing while nothing changes; global windows do (Table A).**
   - **Per-node.** In S1, every per-node window from W = 200 to 20000 gives plain LinUCB's goodput (72.2 req/s; 90.6–90.7 % of SLOs met).
   - **Global.** Global windows lose goodput at every W ≤ 2000: 61.6 req/s at W = 200, 67.6 at W = 1000 and 70.6 at W = 2000. Only from W = 5000 up are they within plain LinUCB's interval.
   - **Why.** The policy hardly uses the A100 sites.
     - A per-node window keeps their few old outcomes, so their estimates stay low and they are left alone.
     - A global window drops those outcomes within seconds. Their exploration bonus then grows back, and the policy keeps re-trying sites that miss the SLO.
   - **Compared with the stand-in.** This reverses the stand-in result, where every window cost goodput in S1.

3. **Forgetting helps after the traffic burst (Table C).** In S2, plain LinUCB adapts in 33.6 s [24.9, 41.8] and averages 90.6 req/s [89.8, 91.3].
   - **W = 500.** A per-node window of W = 500 adapts in 20.4 s [17.8, 22.2] and averages 91.8 req/s [91.4, 92.2]. Both intervals are clear of plain LinUCB's. Per seed, W = 500 took 11–24 s and plain LinUCB 9–54 s.
   - **Other sizes.**
     - W = 1000 and 2000 also give more goodput than plain LinUCB (91.9 and 92.5 req/s, intervals clear of it), but their adaptation-time intervals overlap plain LinUCB's. W = 5000 (91.7 req/s) is within plain LinUCB's interval on both.
     - W = 200 is too short: 90.1 req/s and the lowest burst level of the per-node windows (G\* 165.5).
   - **Why.** During the burst the two H100 sites fill up and their outcomes get worse. With a window, the outcomes from before the burst age out, so the policy sees sooner that its favourite sites are slower now and spreads the load.
   - **Load-balancing baselines adapt faster still.** Least-load adapts in 4.4 s [4.0, 5.2] and reaches a higher burst level (G\* 178.2 against 174.1 for W = 500); round-robin reaches 186.6. A policy that concentrates traffic has to re-learn when that traffic triples.
   - **Over the whole run,** the learned policies still deliver more goodput (91.8 against 82.7 req/s for least-load), because before and after the burst they are far better.

4. **After the S6 outage, short windows recover fastest, but W = 200 abandons the node (Table B1).**
   - **Plain LinUCB** recovers in 14.7 s [7.5, 22.6] from the node's return at 400 s.
   - **Per-node W = 200** recovers in 3.2 s [1.5, 4.9] and has the highest S6 goodput of the α = 1 policies (71.7 against 70.1 req/s). But it stops using the returned node in 6 of 10 seeds, so its quick "recovery" partly means it no longer waits for the node.
   - **Per-node W = 500** never abandons the node (0 of 10 seeds).
     - Its recovery time, 10.7 s [3.5, 18.8], overlaps plain LinUCB's.
     - It rushes onto the returning node for 0.9 s [0.7, 1.0], against 2.5 s [1.0, 4.3] for plain LinUCB.
     - It keeps its goodput: 70.8 req/s [70.2, 71.3], against 70.1 [69.9, 70.3].
   - **Global windows** recover more slowly (16.7–19.9 s for W ≤ 5000) and settle lower after the return (G\* 62.0–71.9 req/s; Table B2).
   - **A warning about short times.** Lowest-energy "recovers" in 3.0 s because it never sends that node anything (abandoned in 10 of 10 seeds), so a short time needs the traffic share next to it.

5. **The price shift does not change the learned routing (S3, Table E).** S3 gives the learned policies exactly the S1 numbers.
   - **Routing.** With a per-node window of W = 500 (seed 0), 72.0 % of requests go to the California sites before the shift and 73.0 % after (S1: 72.0 % and 73.2 %), although California's prices jump from about $0 to $0.046–0.050/kWh.
   - **Why.** With the reward weights 1.0 / 0.2 / 0.1 / 0.1, meeting the SLO dominates, and after the shift the energy term moves the reward by only about 0.01.
   - **Only lowest-energy reacts:** 61.0 → 53.8 req/s.
   - **What it would take.** A price-aware policy needs a larger energy weight; that is the team's reward-weights decision (Krupesh's handbook §7, #4).

6. **S4 and S5: windows neither help nor hurt (Table E).** All per-node windows are within each other's intervals and plain LinUCB's: 71.3–71.9 req/s in S4 and 70.5–71.0 in S5. Both changes hit the New York site, which serves mostly batch requests, whose 1,000-ms SLO absorbs the throttling and the +80 ms.

7. **Exploration: α = 1 is the robust choice (Table D).**
   - **S1:** α = 0.1 and 0.5 give 0.2 req/s more (72.5 against 72.2), within the intervals.
   - **S2:** α = 1 and 2 adapt in 20–21 s. α = 0.5 needs 37.5 s, and α = 0.1 needs 52.3 s with a much lower burst level (G\* 162.2). Too little exploration keeps the policy on its saturated favourites.
   - **S6:** smaller α adapts faster at t0 (6.8–7.5 s against 18.3 s), but abandons the returned node in 1–2 of 10 seeds (α = 2: 3 of 10). α = 1 never does.

8. **Safety, and the router's 1-s-old view.**
   - **The filter held.** No request went to a node the router's filter had excluded: the router's audit found 0 hard-rule violations in all 1,350 runs (Table G).
   - **True-state check.** Parikshit's simulator also checks the chosen node's *true* state at decision time, which can be up to 1 s newer than the router's view.
     - A per-node window of W = 500 reaches a node that has just passed a limit about 3,200 times per S2 run (past the power limit during the burst), 142 times per S4 run (past 85 °C) and 82 times per S6 run.
     - The S6 cases are all power-limit hits on A100 sites that take over New York's traffic during the outage, at nodes that were up. In seed 3, the seed with the most, all 461 are of this kind; none involve the warming node.
     - The baselines reach such nodes more often: about 8,000 times per S2 run for least-load, and 13,300–19,700 per run in every scenario for lowest-energy, which sends everything to the cheapest site.
   - **Cause.** These come from the telemetry's age, not from the policies (team item 3).

**Reward scale.** This sweep uses `energy_cost_max_usd` = $0.00001, about the 99th percentile of a request's energy cost on Parikshit's simulator in S1–S3 ($8.1e-6); 0.4 % of requests hit the cap. With the earlier $0.0002, the energy term was about 0.002 for a typical request, so energy did not count at all.

## Tables

### Table A — S1 stable: the cost of forgetting

| W | per-node: mean goodput (req/s) | per-node: SLO met | global: mean goodput (req/s) | global: SLO met |
|---|---|---|---|---|
| 200 | 72.2 [71.9, 72.5] | 90.6 % [90.3, 90.9] | 61.6 [61.4, 61.8] | 77.3 % [77.2, 77.4] |
| 500 | 72.2 [71.9, 72.6] | 90.7 % [90.4, 91.0] | 64.0 [63.7, 64.2] | 80.3 % [80.1, 80.5] |
| 1000 | 72.2 [71.9, 72.6] | 90.7 % [90.4, 91.0] | 67.6 [67.4, 67.9] | 84.9 % [84.7, 85.0] |
| 2000 | 72.2 [71.9, 72.6] | 90.7 % [90.4, 91.0] | 70.6 [70.4, 70.8] | 88.6 % [88.4, 88.7] |
| 5000 | 72.2 [71.9, 72.6] | 90.7 % [90.4, 91.0] | 71.8 [71.5, 72.1] | 90.1 % [89.9, 90.4] |
| 10000 *(extra)* | 72.2 [71.9, 72.6] | 90.7 % [90.4, 91.0] | 72.0 [71.7, 72.4] | 90.4 % [90.1, 90.7] |
| 20000 *(extra)* | 72.2 [71.9, 72.6] | 90.7 % [90.4, 91.0] | 72.1 [71.8, 72.5] | 90.5 % [90.3, 90.8] |
| plain LinUCB | 72.2 [71.9, 72.6] | 90.7 % [90.4, 91.0] | — | — |

### Table B1 — S6 after the node returns (from 400 s), per-node windows

| W | adaptation (s) | recovered | G* (req/s) | deepest dip (req/s) | rush (s) | returned node's traffic share after warm-up | seeds where it was abandoned |
|---|---|---|---|---|---|---|---|
| 200 | 3.2 [1.5, 4.9] | 10/10 | 72.6 [71.7, 73.4] | 61.5 [60.1, 62.8] | 0.9 [0.5, 1.3] | 27 % [7, 50] | 6/10 |
| 500 | 10.7 [3.5, 18.8] | 10/10 | 72.1 [70.8, 73.2] | 60.6 [58.8, 62.1] | 0.9 [0.7, 1.0] | 35 % [27, 47] | 0/10 |
| 1000 | 12.8 [4.8, 21.6] | 10/10 | 72.5 [71.7, 73.3] | 60.9 [60.0, 61.8] | 1.5 [0.8, 2.4] | 39 % [29, 51] | 0/10 |
| 2000 | 13.5 [5.9, 21.4] | 10/10 | 72.5 [71.7, 73.3] | 59.3 [56.3, 61.7] | 1.9 [0.8, 3.4] | 38 % [30, 47] | 0/10 |
| 5000 | 12.9 [6.3, 20.1] | 10/10 | 72.6 [71.7, 73.4] | 57.1 [51.2, 61.8] | 2.8 [1.0, 5.1] | 39 % [33, 46] | 0/10 |
| 10000 *(extra)* | 14.4 [7.3, 22.1] | 10/10 | 72.6 [71.8, 73.3] | 56.2 [49.2, 61.4] | 3.5 [1.0, 6.6] | 41 % [34, 49] | 0/10 |
| 20000 *(extra)* | 14.7 [7.5, 22.5] | 10/10 | 72.5 [71.7, 73.3] | 58.3 [54.7, 61.2] | 2.5 [1.0, 4.2] | 42 % [34, 50] | 0/10 |
| plain LinUCB | 14.7 [7.5, 22.6] | 10/10 | 72.5 [71.7, 73.3] | 58.3 [54.5, 61.3] | 2.5 [1.0, 4.3] | 42 % [36, 50] | 0/10 |

### Table B2 — S6 after the node returns (from 400 s), global windows

| W | adaptation (s) | recovered | G* (req/s) | deepest dip (req/s) | rush (s) | returned node's traffic share after warm-up | seeds where it was abandoned |
|---|---|---|---|---|---|---|---|
| 200 | 17.9 [11.9, 25.5] | 10/10 | 62.0 [61.2, 62.7] | 44.5 [43.4, 45.7] | 2.2 [2.0, 2.5] | 30 % [29, 32] | 0/10 |
| 500 | 19.9 [10.8, 31.0] | 10/10 | 64.3 [63.4, 65.3] | 44.2 [42.8, 45.7] | 3.0 [2.6, 3.4] | 28 % [23, 34] | 0/10 |
| 1000 | 18.6 [13.5, 24.7] | 10/10 | 67.1 [66.1, 68.2] | 44.9 [43.5, 46.1] | 3.0 [2.4, 3.6] | 16 % [16, 17] | 0/10 |
| 2000 | 19.1 [10.8, 29.1] | 10/10 | 70.5 [69.9, 71.2] | 48.7 [47.4, 50.0] | 3.6 [3.0, 4.2] | 25 % [20, 34] | 0/10 |
| 5000 | 16.7 [10.2, 23.5] | 10/10 | 71.9 [71.1, 72.6] | 49.5 [47.2, 51.8] | 4.6 [3.7, 5.5] | 37 % [26, 48] | 0/10 |
| 10000 *(extra)* | 12.9 [8.7, 18.0] | 10/10 | 72.2 [71.4, 73.0] | 49.1 [46.9, 51.2] | 4.7 [3.8, 5.6] | 35 % [31, 39] | 0/10 |
| 20000 *(extra)* | 14.4 [7.4, 22.0] | 10/10 | 72.3 [71.6, 73.0] | 59.2 [55.9, 61.8] | 2.1 [0.8, 3.8] | 39 % [36, 44] | 0/10 |
| plain LinUCB | 14.7 [7.5, 22.6] | 10/10 | 72.5 [71.7, 73.3] | 58.3 [54.5, 61.3] | 2.5 [1.0, 4.3] | 42 % [36, 50] | 0/10 |

### Table C — S2 traffic burst (3× arrivals for 120 s)

| policy | mean goodput (req/s) | adaptation (s) | recovered | G* during the burst (req/s) | deepest dip (req/s) |
|---|---|---|---|---|---|
| plain LinUCB | 90.6 [89.8, 91.3] | 33.6 [24.9, 41.8] | 10/10 | 175.4 [170.9, 179.4] | 78.4 [74.7, 82.5] |
| per-node W = 200 | 90.1 [89.5, 90.6] | 28.2 [19.5, 39.0] | 10/10 | 165.5 [161.9, 168.9] | 97.1 [94.4, 99.7] |
| per-node W = 500 | 91.8 [91.4, 92.2] | 20.4 [17.8, 22.2] | 10/10 | 174.1 [170.9, 177.6] | 93.7 [89.5, 98.0] |
| per-node W = 1000 | 91.9 [91.6, 92.2] | 25.3 [21.1, 30.7] | 10/10 | 174.1 [170.3, 177.9] | 92.6 [88.5, 96.7] |
| per-node W = 2000 | 92.5 [92.1, 92.9] | 23.6 [19.8, 27.9] | 10/10 | 176.1 [173.3, 178.6] | 92.7 [88.9, 96.5] |
| per-node W = 5000 | 91.7 [91.1, 92.4] | 23.9 [18.3, 29.3] | 10/10 | 174.1 [171.0, 177.5] | 90.2 [85.7, 95.0] |
| global W = 1000 | 86.0 [85.4, 86.6] | 28.9 [18.0, 41.4] | 10/10 | 161.9 [157.2, 166.6] | 88.8 [83.8, 93.1] |
| global W = 5000 | 92.0 [91.6, 92.4] | 28.4 [23.6, 33.8] | 10/10 | 178.5 [174.9, 182.1] | 90.3 [86.8, 93.8] |
| least-load | 82.7 [82.4, 83.0] | 4.4 [4.0, 5.2] | 10/10 | 178.2 [176.5, 179.8] | 79.9 [77.3, 82.5] |
| round-robin | 80.6 [80.4, 80.7] | 8.3 [6.6, 10.5] | 10/10 | 186.6 [185.4, 187.5] | 76.5 [73.8, 78.8] |
| static-weighted | 80.6 [79.8, 81.3] | 3.2 [2.8, 3.6] | 10/10 | 156.7 [149.6, 162.9] | 81.1 [78.5, 83.9] |

### Table D — exploration check (per-node window, W = 500)

| α | S1 mean goodput (req/s) | S2 adaptation (s) | S2 G* (req/s) | S6 adaptation at t0 (s) | S6 G* (req/s) |
|---|---|---|---|---|---|
| 0.1 | 72.5 [72.1, 72.8] | 52.3 [39.5, 67.0] | 162.2 [156.5, 167.4] | 6.8 [2.8, 11.5] | 72.4 [71.8, 73.0] |
| 0.5 | 72.4 [72.1, 72.8] | 37.5 [27.6, 48.2] | 170.4 [165.6, 175.3] | 7.5 [3.1, 12.9] | 71.8 [70.8, 72.7] |
| 1 (default) | 72.2 [71.9, 72.6] | 20.4 [17.8, 22.2] | 174.1 [170.9, 177.6] | 18.3 [9.3, 27.1] | 70.5 [69.2, 71.7] |
| 2 | 72.3 [72.0, 72.6] | 21.2 [16.8, 26.0] | 176.1 [172.7, 179.7] | 18.0 [12.2, 23.7] | 70.6 [69.4, 71.7] |

### Table E — mean goodput (req/s) in every scenario

| policy | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---|---|---|---|---|---|
| plain LinUCB | 72.2 [71.9, 72.6] | 90.6 [89.8, 91.3] | 72.2 [71.9, 72.6] | 71.4 [70.7, 71.9] | 70.5 [68.9, 71.8] | 70.1 [69.9, 70.3] |
| per-node W = 200 | 72.2 [71.9, 72.5] | 90.1 [89.5, 90.6] | 72.2 [71.9, 72.5] | 71.9 [71.8, 72.1] | 71.0 [69.6, 72.0] | 71.7 [71.4, 72.0] |
| per-node W = 500 | 72.2 [71.9, 72.6] | 91.8 [91.4, 92.2] | 72.2 [71.9, 72.6] | 71.3 [70.6, 71.9] | 70.5 [69.0, 71.8] | 70.8 [70.2, 71.3] |
| per-node W = 1000 | 72.2 [71.9, 72.6] | 91.9 [91.6, 92.2] | 72.2 [71.9, 72.6] | 71.4 [70.8, 71.9] | 70.6 [69.2, 71.9] | 70.1 [70.0, 70.3] |
| per-node W = 2000 | 72.2 [71.9, 72.6] | 92.5 [92.1, 92.9] | 72.2 [71.9, 72.6] | 71.4 [70.8, 71.9] | 70.6 [69.3, 71.9] | 70.2 [70.0, 70.3] |
| per-node W = 5000 | 72.2 [71.9, 72.6] | 91.7 [91.1, 92.4] | 72.2 [71.9, 72.6] | 71.5 [71.0, 71.9] | 70.6 [69.2, 71.8] | 70.2 [70.0, 70.4] |
| global W = 5000 | 71.8 [71.5, 72.1] | 92.0 [91.6, 92.4] | 71.8 [71.5, 72.1] | 70.8 [70.0, 71.5] | 70.2 [68.8, 71.3] | 69.6 [69.3, 69.9] |
| static-weighted | 59.0 [58.8, 59.1] | 80.6 [79.8, 81.3] | 59.0 [58.8, 59.1] | 56.7 [56.5, 56.8] | 54.6 [54.5, 54.7] | 56.4 [56.2, 56.6] |
| min-RTT | 58.6 [58.4, 58.7] | 62.7 [62.5, 63.0] | 58.6 [58.4, 58.7] | 52.3 [52.2, 52.5] | 49.7 [49.5, 49.8] | 53.3 [53.2, 53.5] |
| least-load | 58.5 [58.4, 58.7] | 82.7 [82.4, 83.0] | 58.5 [58.4, 58.7] | 56.5 [56.4, 56.6] | 57.0 [56.9, 57.1] | 56.4 [56.2, 56.5] |
| power-of-two | 58.4 [58.2, 58.5] | 82.5 [82.3, 82.7] | 58.4 [58.2, 58.5] | 56.3 [56.2, 56.5] | 56.9 [56.7, 57.0] | 56.2 [56.0, 56.3] |
| round-robin | 54.5 [54.3, 54.7] | 80.6 [80.4, 80.7] | 54.5 [54.3, 54.7] | 53.0 [52.9, 53.2] | 53.4 [53.2, 53.5] | 52.6 [52.5, 52.8] |
| lowest-energy | 61.0 [60.8, 61.2] | 29.7 [29.5, 29.8] | 53.8 [53.7, 54.0] | 61.0 [60.8, 61.2] | 61.0 [60.8, 61.2] | 61.0 [60.8, 61.2] |

### Table F — S3 price shift: cost per SLO-met request (µ$)

| policy | cost (µ$) |
|---|---|
| per-node W = 200 | 258.8 [256.9, 260.5] |
| per-node W = 500 | 267.8 [266.3, 269.8] |
| per-node W = 1000 | 278.7 [276.9, 280.8] |
| per-node W = 2000 | 291.1 [288.7, 293.7] |
| per-node W = 5000 | 309.0 [304.9, 312.9] |
| plain LinUCB | 311.5 [304.6, 317.5] |
| lowest-energy | 354.0 [352.4, 355.7] |
| global W = 5000 | 370.5 [366.9, 373.7] |
| min-RTT | 522.4 [520.6, 524.4] |
| static-weighted | 625.3 [623.8, 626.9] |
| least-load | 630.2 [628.6, 632.0] |
| power-of-two | 631.8 [630.0, 633.6] |
| round-robin | 676.8 [674.8, 678.8] |

### Table G — S6: hard-rule violations by nodes the filter allowed

| policy | total over all seeds | per run |
|---|---|---|
| per_node W=5000 | 0 | 0 |
| per_node W=500 | 0 | 0 |
| per_node W=20000 | 0 | 0 |
| per_node W=2000 | 0 | 0 |
| per_node W=200 | 0 | 0 |
| per_node W=10000 | 0 | 0 |
| per_node W=1000 | 0 | 0 |
| global W=5000 | 0 | 0 |
| global W=500 | 0 | 0 |
| global W=20000 | 0 | 0 |
| global W=2000 | 0 | 0 |
| global W=200 | 0 | 0 |
| global W=10000 | 0 | 0 |
| global W=1000 | 0 | 0 |
| plain LinUCB | 0 | 0 |
| static-weighted | 0 | 0 |
| round-robin | 0 | 0 |
| power-of-two | 0 | 0 |
| min-RTT | 0 | 0 |
| lowest-energy | 0 | 0 |
| least-load | 0 | 0 |

## Recommendation

- **Use a per-node window with W = 500 and α = 1.** This is now the shipped default (`configs/policies/sw_linucb.yaml`; the no-context ablation follows it).
  - It is the only window that beats plain LinUCB on both S2 measures, with intervals that do not overlap (finding 3).
  - It costs nothing in S1, S3, S4 and S5 (findings 2 and 6).
  - It never abandons the returned S6 node (finding 4).
- **Count the window per node.** Global windows lose goodput at every W ≤ 2000 in S1 (finding 2) and recover more slowly after the S6 return (finding 4).
- **Against the brief's success criteria, on Parikshit's simulator:**
  - *Safe:* yes. There are 0 hard-rule violations by filter-allowed nodes in every run. The true-state violations come from the telemetry's age, not from the policy (finding 8).
  - *Faster than plain LinUCB:* yes in S2 (20.4 s against 33.6 s); no significant difference in the other scenarios.
  - *Better than the strongest baseline:*
    - yes, on mean goodput in all six scenarios (Table E);
    - about 2–2.5 times cheaper per SLO-met request (Table F);
    - but not faster than least-load in S2 (finding 3).

## For the team

1. **Reward weights (Sur and the team; handbook §7, #4).** With 1.0 / 0.2 / 0.1 / 0.1 the policy ignores prices (finding 5). If the report should show price-aware routing, the energy weight must grow, and the SLO term then no longer wins every trade-off. Decide this before the final runs.
2. **Adaptation-time metric (Riya).**
   - **Binning.** This sweep bins by arrival time (the moment of the decision), while Riya's runner bins by completion time. The team should fix one.
   - **Noise floor.** In S1, where nothing changes, plain LinUCB and per-node W = 500 show a non-zero time in 4 of 10 seeds (4–12 s; mean 3.8 s), because the interactive arrivals are bursty. Read every scenario's time against this floor.
   - **Abandonment.** A short time can mean the policy stopped using the node (finding 4), so show the traffic share next to it.
   - **S6 needs a second anchor** at the node's return (400 s), as done here.
3. **Telemetry age (Krupesh and Parikshit).** The router's view is up to 1 s old, so in S2 and S4 requests reach nodes that have just crossed a limit (finding 8). Either of these would reduce it:
   - counting the router's own recent placements against power and temperature, as it already does for load;
   - a shorter telemetry tick.
4. **Jyotir's warming-node bug is still in the filter, but it does not affect these runs.** The bug lets a warming node skip the memory, power and temperature checks. On Parikshit's simulator the warming node never comes near those limits: none of the S6 true-state violations involve it (finding 8).
5. **The S2 burst is mild (Parikshit's README, item 5).** At 80 requests/s the 3× burst stays below the cluster's maximum throughput, so an even spread absorbs it. A harder S2 (a higher base rate) would separate the policies more.

## Figures (`results/figures/`)

| File | Shows |
|---|---|
| `goodput_<scenario>.png` | goodput over time for W = 200 / 500 (the default) / 5000 and plain LinUCB; per-node and global windows side by side; dots at the mean adaptation time |
| `window_adaptation.png` | adaptation time vs W, every scenario, plus S6 after the node returns |
| `window_steady_level.png` | steady-state goodput G\* vs W |
| `window_goodput.png` | mean goodput over the whole run vs W (S1 shows the cost of forgetting) |
| `alpha_check.png` | goodput and adaptation time vs α |

**Colours:**
- per-node windows are blue, global windows orange and plain LinUCB grey;
- W runs from light (small) to dark (large).

The numbers behind every figure are in `results/summary.csv`.

## Reproduce

```bash
cd geo-inference-scheduler/Sur
python3 window_sweep/run_sweep.py               # ~21 min on 16 processes; writes results/ and checkpoints/simulator/
python3 window_sweep/make_figures.py            # figures from results/ only
python3 window_sweep/make_tables.py --update    # tables from results/summary.csv, into this file
```
