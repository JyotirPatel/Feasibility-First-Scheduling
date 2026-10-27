# Window-size sweep on the stand-in: results (superseded)

**Owner:** Sur. **Superseded by `RESULTS.md`**, the same sweep on Parikshit's simulator through Krupesh's router. Kept for the record.

> **Stand-in results.** These runs used Sur's temporary stand-in simulator (`../standins/`) and the earlier reward scale (energy cost $0.0002). The bundle they describe is in `results_standin/`; where this text says `results/`, read `results_standin/`. Re-running with `python3 window_sweep/run_sweep.py --simulator standin` now gives slightly different numbers, because the reward scale has changed.

## What was run

- **Runs:** 1,350, on 16 processes.
  - `results/manifest.json` records 14,372 s of wall time because the run was paused partway through. The previous full sweep, run without a pause, took 1,323 s (about 22 min).
  - Provenance is also in `results/manifest.json`: git commit `1f2f514` with Sur's uncommitted work on top, plus SHA-256 hashes of every config file.
  - The runs are reproducible. Re-running them gives identical numbers: four complete jobs re-run with the sweep's code, and 80 S6 runs (eight policies × 10 seeds) re-run by `diagnostics.py`, all match `runs.csv`. `tests/test_toy_cluster.py` checks that results depend neither on the process they run in nor on the order of keys in `toy_cluster.yaml`.
- **Scenarios and seeds:** six scenarios (S1–S6, 600 s each, change at t0 = 200 s) × 10 seeds. Every policy got the same requests for a given seed.
- **Policies:**
  - Sliding-window LinUCB with W ∈ {200, 500, 1000, 2000, 5000} (the brief's sweep) plus 10000 and 20000, each as a **per-node** and a **global** window.
  - Plain LinUCB, the "no forgetting" reference.
  - An α check: α ∈ {0.1, 0.5, 1, 2} on S1, S2 and S6, per-node window, W = 1000.
  - Jyotir's six baselines, as a sanity reference only. The main comparison is Riya's.
- **Load.**
  - 240 requests/s arrive, all from US users (New York 50 %, Chicago 30 %, San Francisco 20 %). In S1 with plain LinUCB (seeds 0–2), 37.5–38.7 % of all request slots are in use on average, and 43.2–43.8 % at the 95th percentile.
  - Traffic is uneven: each of the three US nodes gets 23–37 %, eu-west-1 3–12 % and ap-south-1 under 1 % (`python3 window_sweep/diagnostics.py --policy plain --load --seeds 3`).
  - So a per-node window of W outcomes covers about W ÷ 75 seconds of a US node's history (W = 1000 ≈ 13 s, W = 5000 ≈ 67 s), and much more for the far nodes. A global window covers about W ÷ 240 seconds (W = 1000 ≈ 4 s, W = 5000 ≈ 21 s, W = 20000 ≈ 83 s).
- **Metrics.** These follow the frozen definitions in work distribution §6:
  - goodput in 1-s bins smoothed over 5 s;
  - G\*, the mean goodput from t0 + 60 s to t0 + 120 s;
  - adaptation time, the first moment G ≥ 0.9·G\* holds for 10 s;
  - deepest dip, the lowest goodput from t0 to t0 + 120 s, so a higher number is a milder dip.

  S6 is also measured from the node's return at 400 s. For S6 the bundle also records the returned node's share of requests before the outage and after its warm-up, and the length of the "rush" (seconds after its return in which it got ≥ 50 % of requests).
- **Numbers.** Every number in the tables is **mean [95 % bootstrap CI]** over the 10 seeds. All tables are generated from `results/summary.csv` by `make_tables.py`, and `tests/test_figures_and_tables.py` fails if any table here differs from the bundle. Per-seed numbers in the text come from `results/runs.csv` or from `diagnostics.py`.

## Findings

1. **Forgetting costs goodput while nothing changes (Table A).** In S1, plain LinUCB meets the SLO for 98.6 % [98.5, 98.7] of requests.
   - Per-node windows reach 93.4 % [93.1, 93.6] at W = 200, 94.6 % [94.2, 95.0] at W = 1000, 97.6 % [97.4, 97.8] at W = 5000 and 98.5 % [98.4, 98.5] at W = 20000.
   - The cost is largest at mid-sized windows (per-node W = 500: 92.7 % [92.5, 93.0]; global W = 1000: 90.7 % [90.4, 91.0]) and shrinks steadily as W grows beyond them.
   - Likely reason: a window keeps fewer outcomes, so the exploration bonus stays larger and the policy keeps re-trying nodes it is unsure about. This is clearest for a global window, which can forget a rarely used node completely. Global W = 1000 sends 8–9 % of S1 requests to ap-south-1, which is 170–200 ms from every user, against under 1 % for plain LinUCB (`diagnostics.py --load`, seeds 0–2).

2. **No window setting beat plain LinUCB on mean goodput in any scenario (Table E).** In each of the six scenarios, plain LinUCB's mean goodput is at least that of every sliding-window setting, including the α-check runs. The closest, per-node W = 20000, has CIs that overlap plain LinUCB's everywhere.
   - A likely reason, which is a hypothesis consistent with the data: every change in these six scenarios is visible in the context features (queue, delay, price, temperature, warming flag). A contextual model that has learned how those features relate to reward therefore reacts at once, without needing to forget.
   - A controlled test supports this. In `tests/test_sw_linucb.py`, two nodes look identical in the context, and their success rates swap at round T, so the change is invisible.
     - There, windows of 100 outcomes switch to the new best node within 6–66 rounds.
     - Plain LinUCB needs 134–214 rounds when the change comes at T = 1500, and 487–1,763 rounds at T = 6000 (seeds 0–2), because its longer history anchors it.

3. **One result favours a window on adaptation time: the S2 burst (Table C).**
   - Per-node W = 5000 adapts in 4.6 s [1.3, 8.1], plain LinUCB in 12.1 s [8.5, 15.5]. Seed by seed, W = 5000 was faster in 8 of 10, slower in 1 and tied in 1. Global W = 200 shows the same pattern: 3.1 s [1.0, 6.2], faster in 8 seeds, slower in 1, tied in 1.
   - What the number measures here. For these three policies, the per-seed S2 adaptation time is either 1–2 s or 8–22 s.
     - When the burst starts, goodput first overshoots (to 500–530 req/s in seed 0), then falls back as queues build, then settles near G\*.
     - If goodput stays above 0.9·G\* through that fall, the metric reports 1–2 s. If it dips below, the metric reports when goodput recovered.
     - Goodput stayed above in 7 of 10 seeds for per-node W = 5000, 8 for global W = 200, 1 for plain LinUCB, and 10 for every baseline.
   - The same policy is not better on the other S2 measures. Per-node W = 5000 against plain LinUCB:
     - burst level G\*: 393.0 [387.7, 397.4] against 397.0 [394.8, 399.1];
     - lowest goodput: 282.5 [250.7, 312.9] against 312.7 [299.7, 324.6];
     - mean goodput: 266.4 [265.3, 267.4] against 268.2 [267.3, 269.1].
   - Its neighbours, W = 2000 (8.9 s) and W = 10000 (8.6 s), are not significantly faster than plain LinUCB.
   - Nowhere else is a window faster.
     - In S3–S5, plain LinUCB scores 0 s in every seed. The windows score 0–8.6 s there, but they score similar times in S1, where nothing changes (0–6.5 s), so those numbers mostly reflect how noisy their goodput is.
     - In S6, every CI at t0 overlaps plain LinUCB's. After the node's return, the shortest times come from abandoning it (finding 4).
   - S2 compares 17 window settings with plain LinUCB, so one or two results like this can appear by chance. Treat it as a lead to check on the real simulator, not yet as evidence for the brief's "Faster" criterion.

4. **After the S6 node returns, small per-node windows often abandon it (Table B1).** The node counts as abandoned when it gets under 1 % of requests after its warm-up.
   - **How often.**
     - Per-node windows abandoned it in 7 of 10 seeds at W = 200, 3 at W = 500, 4 at W = 1000, 3 at W = 2000 and 1 at W = 5000.
     - W ≥ 10000, plain LinUCB and every global window never did.
     - Before the outage these windows gave the node 31–34 % of requests. Plain LinUCB gives it 43.5 % after its return.
     - A smaller α abandons it more often. At W = 1000 it happened in 7 of 10 seeds with α = 0.1, in 5 with α = 0.5, and in 4 with both α = 1 and α = 2.
   - **Cause**, checked with a counterfactual (`python3 window_sweep/diagnostics.py --policy per_node:1000 --counterfactual`):
     - The requests lost when the node went down are the newest outcomes in its window. In every seed the last of them is among the newest 5 of the window's 1,000 outcomes. There are 192–323 of them per seed, except 5 in seed 8.
     - They make the model's estimate for the returning node erratic: −1.026 to +2.546 across seeds. The same window without them gives +0.633 to +0.925, and the best other node scored about 0.9–1.1.
     - A negative estimate means the node is never tried again, and a per-node window only changes when its node is chosen. The node was abandoned in exactly the seeds where its estimate at the return was negative:
       - at W = 1000, seeds 0, 2, 4 and 5 (−1.026 to −0.169);
       - at W = 200, all seven abandoned seeds; this window held 164–200 lost outcomes out of 200.
     - At W = 2000 the two seeds with a negative estimate were abandoned too. So was seed 0, by another route: the node was tried while still warming up (a 6-s rush, as in finding 5), its slow warm-up results entered the window as well, and it was dropped after that.
   - **What this does to the metrics.** A short adaptation time after the return often means the node was dropped while the other nodes absorbed its load.
     - At W = 1000 it was 0 s in all four abandoned seeds: a mean of 3.0 s [0.0, 6.5], against 7.7 s [4.7, 10.4] for plain LinUCB.
     - Dropping the node costs little here only because the cluster has spare capacity (about 38 % of slots in use).
     - **It is not evidence that forgetting helps.**

5. **Plain LinUCB and the global windows rush onto the returned node (Tables B1, B2).** The rush is how long the returned node got ≥ 50 % of all requests.
   - **How long.** Global windows rushed for 5–7 s in 69 of their 70 S6 runs, and for 1 s in the other. Plain LinUCB rushed for 6–7 s in 7 of 10 seeds and for 2 s in the other 3: 5.2 s [3.8, 6.4].
   - **The rush is what makes the dip deep.**
     - In all 103 S6 runs of a learning policy with a rush of 5 s or more, goodput fell to 77 req/s or less.
     - In 73 of the 77 runs with a rush of 2 s or less, goodput stayed at 93 req/s or more.
     - During a long rush, the node's queue reached 737–1,143 requests. That range covers plain LinUCB, global W = 1000 and 20000 and per-node W = 1000 over seeds 0–9 (`python3 window_sweep/diagnostics.py`).
     - The 50 % threshold misses some heavy use: per-node W = 10000 never crossed it in seeds 4 and 6, yet still fell to 14–19 req/s.
     - Hence the dips in Tables B1 and B2. The global windows' lowest goodput after the return is 22.9–31.9 req/s on average. Plain LinUCB's is 77.7 [31.4, 137.8], and its wide CI is its mix of 2-s and 6–7-s rushes.
   - **Causes**, from the per-second trace (`python3 window_sweep/diagnostics.py --policy plain --trace 0`; `--seeds 0 --trace 3` for seed 3):
     - The warming flag is a value the model never saw for that node, which gives the node a large exploration bonus. In seed 0 it is 1.0 for plain LinUCB and 2.0 for a global window that has forgotten the node. So at first every request goes to the node.
     - Whether the rush lasts 2 s or 6–7 s is a race between the node's first results and its queue.
       - **Seed 3 (2-s rush):** 5 results came back in the first second, and the bonus fell to 0.76 (at 401 s) and then 0.32 (at 402 s). The node's share fell to 0.67 and then to 0, and its queue never held more than 5 requests.
       - **Seed 0 (7-s rush):** only 3 results came back in the first second, and the bonus fell only to 0.91. Every request still went to the node, and its queue started to grow (10 requests at 401 s, 184 at 402 s).
     - In seed 0, each new request then had a context (warming, with a long queue) unlike those whose results had come back. So its bonus stayed between 0.91 and 1.06 until 405 s, although the bonus for the first context had already fallen to 0.11.
     - The rush ended at 406–407 s, only when results for requests that had waited in the queue came back and pulled the node's estimate down (0.68 at 405 s, −0.30 at 407 s). By then about 1,050–1,100 requests were waiting.
     - **Jyotir's filter bug (below) is what lets the queue grow that far:** the warming node stays allowed after its KV cache is ≥ 90 % full.
       - The what-if `python3 window_sweep/diagnostics.py --fixed-filter` fixes the bug in memory; `filter.py` is unchanged. The node is then filtered out once its memory fills.
       - In that what-if, no learning policy tested rushes for more than 2 s. Plain LinUCB's lowest goodput after the return is 200–219 req/s (mean 211.4) instead of 0–219 (mean 77.7). See "For the team", item 1.

6. **Only a global window rediscovers a node it had abandoned (controlled test).** In the two-node test in `tests/test_sw_linucb.py` (seeds 0–2), a node that is useless early and then becomes the best got 99.0–99.3 % of requests in the final 300 rounds under a global window. It got none under a per-node window or plain LinUCB.

7. **Exploration check: no α is best on every measure (Table D).**
   - α = 0.1 and α = 0.5 give more goodput than α = 1 when nothing changes. In S1 they give 230.2 [229.2, 231.2] and 229.2 [228.5, 229.9] req/s, against 227.1 [226.2, 228.1] at α = 1 and 228.2 [226.9, 229.5] at α = 2.
   - **After the S2 burst,** α = 1 has the shortest mean adaptation time: 10.4 s [5.8, 14.6], against 21.9 s [10.5, 34.2] for α = 0.1.
   - **After the S6 outage,** α = 0.5 has the shortest: 4.2 s [2.1, 6.6], against 5.6 s [3.2, 8.2] for α = 1.
   - All the adaptation-time CIs overlap.
   - A smaller α abandons the returned S6 node more often (finding 4).
   - α = 1 stays the default; α = 0.5 is worth re-checking on the real simulator.

8. **The best simple baselines match or beat plain LinUCB here (Tables E, F).**
   - **Static-weighted.** Its CIs overlap plain LinUCB's in S1–S5, and it is ahead in S6: 235.0 [234.7, 235.3] against 233.3 [232.6, 234.1].
     - Most of that S6 gap is the filter bug. In the what-if with the bug fixed, plain LinUCB gets 234.6 and static-weighted 235.1 req/s (means over seeds 0–9).
   - **Min-RTT.** It is ahead of plain LinUCB in S1–S3 (S1: 237.7 [237.4, 238.0] against 236.7 [236.3, 237.0]), level in S4–S5, and behind in S6 (224.1 [223.8, 224.4]).
     - Its S6 deficit is the filter bug: with the bug fixed, min-RTT gets 235.2.
   - **Cost** (Table F, S3 price shift): static-weighted needs 55.5 µ$ [55.4, 55.6] per SLO-met request, plain LinUCB 57.0 [56.6, 57.5].
   - So the brief's "Better" criterion (higher SLO goodput or lower cost than the strongest baseline) is **not** met on this stand-in. The brief accepts a clean negative result.
   - Static baselines show about 1 s "adaptation" in S2 because they don't learn: they apply a fixed rule to fresh telemetry.

### Table A — S1 stable: the cost of forgetting

| W | per-node: mean goodput (req/s) | per-node: SLO met | global: mean goodput (req/s) | global: SLO met |
|---|---|---|---|---|
| 200 | 224.0 [223.2, 224.7] | 93.4 % [93.1, 93.6] | 225.0 [224.6, 225.5] | 93.8 % [93.7, 93.9] |
| 500 | 222.5 [221.9, 223.1] | 92.7 % [92.5, 93.0] | 221.1 [220.0, 222.1] | 92.1 % [91.7, 92.6] |
| 1000 | 227.1 [226.2, 228.1] | 94.6 % [94.2, 95.0] | 217.6 [216.8, 218.3] | 90.7 % [90.4, 91.0] |
| 2000 | 230.7 [230.1, 231.5] | 96.2 % [95.9, 96.4] | 219.7 [219.0, 220.4] | 91.6 % [91.3, 91.8] |
| 5000 | 234.2 [233.8, 234.5] | 97.6 % [97.4, 97.8] | 225.5 [224.9, 226.1] | 94.0 % [93.7, 94.3] |
| 10000 *(extra)* | 235.6 [235.1, 236.0] | 98.2 % [98.0, 98.4] | 229.3 [228.4, 230.4] | 95.6 % [95.2, 96.0] |
| 20000 *(extra)* | 236.3 [235.9, 236.7] | 98.5 % [98.4, 98.5] | 232.9 [232.3, 233.5] | 97.1 % [96.9, 97.3] |
| plain LinUCB | 236.7 [236.3, 237.0] | 98.6 % [98.5, 98.7] | — | — |

### Table B1 — S6 after the node returns (from 400 s), per-node windows

| W | adaptation (s) | recovered | G* (req/s) | deepest dip (req/s) | rush (s) | returned node's traffic share after warm-up | seeds where it was abandoned |
|---|---|---|---|---|---|---|---|
| 200 | 10.7 [4.1, 18.9] | 10/10 | 225.0 [222.6, 227.2] | 161.9 [149.6, 174.4] | 0.1 [0.0, 0.3] | 9 % [3, 19] | 7/10 |
| 500 | 7.4 [3.1, 11.4] | 10/10 | 223.0 [220.3, 225.8] | 117.9 [86.6, 143.0] | 1.6 [0.2, 3.3] | 24 % [13, 33] | 3/10 |
| 1000 | 3.0 [0.0, 6.5] | 10/10 | 227.5 [225.6, 229.3] | 136.9 [101.3, 165.5] | 1.7 [0.4, 3.2] | 17 % [7, 26] | 4/10 |
| 2000 | 6.0 [2.9, 9.4] | 10/10 | 232.2 [230.1, 234.5] | 152.9 [113.7, 182.4] | 1.8 [0.8, 3.2] | 20 % [10, 30] | 3/10 |
| 5000 | 8.3 [5.6, 10.9] | 10/10 | 235.6 [234.4, 236.7] | 98.6 [49.1, 151.5] | 4.3 [2.7, 5.8] | 33 % [25, 37] | 1/10 |
| 10000 *(extra)* | 11.1 [8.5, 13.6] | 10/10 | 234.9 [233.0, 237.0] | 60.0 [21.3, 110.4] | 3.8 [2.0, 5.6] | 39 % [38, 40] | 0/10 |
| 20000 *(extra)* | 11.1 [7.1, 14.5] | 10/10 | 236.3 [234.5, 238.1] | 76.4 [26.0, 130.1] | 5.1 [3.7, 6.3] | 44 % [41, 46] | 0/10 |
| plain LinUCB | 7.7 [4.7, 10.4] | 10/10 | 236.8 [235.5, 238.1] | 77.7 [31.4, 137.8] | 5.2 [3.8, 6.4] | 44 % [41, 46] | 0/10 |

### Table B2 — S6 after the node returns (from 400 s), global windows

| W | adaptation (s) | recovered | G* (req/s) | deepest dip (req/s) | rush (s) | returned node's traffic share after warm-up | seeds where it was abandoned |
|---|---|---|---|---|---|---|---|
| 200 | 11.5 [10.4, 12.8] | 10/10 | 224.4 [222.5, 226.1] | 31.9 [23.5, 40.9] | 5.4 [4.2, 6.2] | 24 % [24, 24] | 0/10 |
| 500 | 13.2 [10.9, 15.5] | 10/10 | 219.2 [216.2, 221.9] | 30.0 [22.2, 39.0] | 6.1 [5.8, 6.4] | 26 % [25, 26] | 0/10 |
| 1000 | 12.3 [9.8, 16.2] | 10/10 | 217.7 [214.4, 220.8] | 29.7 [21.7, 37.8] | 6.3 [5.9, 6.7] | 26 % [25, 27] | 0/10 |
| 2000 | 15.6 [12.0, 19.2] | 10/10 | 222.2 [218.4, 225.8] | 31.5 [24.0, 39.5] | 6.2 [5.8, 6.6] | 28 % [27, 28] | 0/10 |
| 5000 | 15.4 [11.2, 20.8] | 10/10 | 221.9 [219.6, 224.4] | 24.9 [18.7, 31.5] | 6.6 [6.3, 6.9] | 31 % [30, 32] | 0/10 |
| 10000 *(extra)* | 10.9 [9.9, 12.0] | 10/10 | 230.5 [226.9, 233.6] | 28.0 [19.8, 38.1] | 6.3 [5.9, 6.7] | 34 % [33, 35] | 0/10 |
| 20000 *(extra)* | 11.0 [10.2, 12.2] | 10/10 | 231.7 [228.5, 234.8] | 22.9 [19.0, 27.0] | 6.6 [6.3, 6.9] | 37 % [37, 38] | 0/10 |
| plain LinUCB | 7.7 [4.7, 10.4] | 10/10 | 236.8 [235.5, 238.1] | 77.7 [31.4, 137.8] | 5.2 [3.8, 6.4] | 44 % [41, 46] | 0/10 |

### Table C — S2 traffic burst (3× arrivals for 120 s)

| policy | mean goodput (req/s) | adaptation (s) | recovered | G* during the burst (req/s) | deepest dip (req/s) |
|---|---|---|---|---|---|
| plain LinUCB | 268.2 [267.3, 269.1] | 12.1 [8.5, 15.5] | 10/10 | 397.0 [394.8, 399.1] | 312.7 [299.7, 324.6] |
| per-node W = 1000 | 258.5 [256.5, 260.3] | 10.4 [5.8, 14.6] | 10/10 | 385.4 [378.0, 392.0] | 268.8 [244.1, 293.6] |
| per-node W = 2000 | 263.1 [261.7, 264.5] | 8.9 [4.5, 13.6] | 10/10 | 389.1 [383.3, 394.2] | 292.5 [272.4, 312.2] |
| per-node W = 5000 | 266.4 [265.3, 267.4] | 4.6 [1.3, 8.1] | 10/10 | 393.0 [387.7, 397.4] | 282.5 [250.7, 312.9] |
| global W = 200 | 260.2 [259.3, 260.9] | 3.1 [1.0, 6.2] | 10/10 | 397.0 [395.5, 398.4] | 307.6 [284.3, 324.3] |
| global W = 20000 *(extra)* | 264.9 [264.3, 265.6] | 12.1 [9.1, 14.6] | 10/10 | 396.6 [395.2, 397.9] | 286.2 [258.0, 309.8] |
| static-weighted | 269.3 [268.7, 269.8] | 1.0 [1.0, 1.0] | 10/10 | 394.8 [393.7, 395.9] | 332.8 [328.5, 337.2] |
| min-RTT | 270.3 [269.9, 270.7] | 1.0 [1.0, 1.0] | 10/10 | 396.6 [394.9, 398.1] | 330.6 [326.7, 335.0] |

### Table D — exploration check (per-node window, W = 1000)

| α | S1 mean goodput (req/s) | S2 adaptation (s) | S2 G* (req/s) | S6 adaptation at t0 (s) | S6 G* (req/s) |
|---|---|---|---|---|---|
| 0.1 | 230.2 [229.2, 231.2] | 21.9 [10.5, 34.2] | 380.0 [367.0, 390.6] | 6.1 [3.5, 8.7] | 232.5 [231.3, 233.7] |
| 0.5 | 229.2 [228.5, 229.9] | 12.6 [2.6, 25.4] | 387.9 [386.0, 389.6] | 4.2 [2.1, 6.6] | 228.6 [226.4, 230.7] |
| 1 (default) | 227.1 [226.2, 228.1] | 10.4 [5.8, 14.6] | 385.4 [378.0, 392.0] | 5.6 [3.2, 8.2] | 227.7 [226.6, 228.6] |
| 2 | 228.2 [226.9, 229.5] | 15.2 [12.3, 18.4] | 391.8 [388.4, 395.2] | 7.9 [2.8, 13.6] | 225.0 [223.1, 226.9] |

### Table E — mean goodput (req/s) in every scenario

| policy | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---|---|---|---|---|---|
| plain LinUCB | 236.7 [236.3, 237.0] | 268.2 [267.3, 269.1] | 236.4 [236.1, 236.8] | 235.5 [235.2, 235.8] | 234.9 [234.5, 235.4] | 233.3 [232.6, 234.1] |
| per-node W = 2000 | 230.7 [230.1, 231.5] | 263.1 [261.7, 264.5] | 231.1 [230.4, 231.8] | 230.9 [230.1, 231.6] | 230.7 [230.2, 231.3] | 230.5 [229.8, 231.2] |
| per-node W = 5000 | 234.2 [233.8, 234.5] | 266.4 [265.3, 267.4] | 234.6 [234.1, 235.1] | 233.9 [233.4, 234.4] | 233.3 [232.8, 233.8] | 232.0 [231.1, 233.0] |
| per-node W = 20000 *(extra)* | 236.3 [235.9, 236.7] | 267.9 [267.1, 268.7] | 236.3 [236.1, 236.6] | 235.4 [235.0, 235.7] | 234.7 [234.3, 235.2] | 233.1 [232.4, 233.8] |
| static-weighted | 236.5 [236.2, 236.8] | 269.3 [268.7, 269.8] | 237.0 [236.6, 237.3] | 235.4 [235.1, 235.8] | 235.3 [234.9, 235.6] | 235.0 [234.7, 235.3] |
| min-RTT | 237.7 [237.4, 238.0] | 270.3 [269.9, 270.7] | 237.7 [237.4, 238.0] | 235.6 [235.2, 235.9] | 234.9 [234.5, 235.2] | 224.1 [223.8, 224.4] |
| least-load | 218.1 [217.8, 218.4] | 254.4 [253.9, 254.9] | 218.1 [217.8, 218.4] | 216.1 [215.9, 216.4] | 216.7 [216.4, 217.0] | 215.5 [215.2, 215.8] |
| power-of-two | 218.0 [217.6, 218.3] | 254.7 [254.2, 255.1] | 218.0 [217.6, 218.3] | 216.1 [215.8, 216.5] | 216.6 [216.2, 216.9] | 215.6 [215.2, 215.9] |
| round-robin | 215.8 [215.4, 216.1] | 252.8 [252.5, 253.1] | 215.8 [215.5, 216.1] | 214.1 [213.8, 214.4] | 214.5 [214.2, 214.8] | 210.9 [210.5, 211.4] |
| lowest-energy | 203.4 [203.0, 203.8] | 242.4 [241.9, 242.8] | 210.3 [210.0, 210.7] | 203.4 [203.0, 203.8] | 203.4 [203.0, 203.7] | 203.4 [203.0, 203.7] |

### Table F — S3 price shift: cost per SLO-met request (µ$)

| policy | cost (µ$) |
|---|---|
| static-weighted | 55.5 [55.4, 55.6] |
| lowest-energy | 56.0 [55.8, 56.3] |
| plain LinUCB | 57.0 [56.6, 57.5] |
| per-node W = 20000 *(extra)* | 57.6 [57.3, 57.8] |
| per-node W = 5000 | 59.9 [59.6, 60.1] |
| per-node W = 2000 | 61.8 [61.5, 62.1] |
| min-RTT | 66.1 [65.9, 66.2] |
| least-load | 72.0 [71.9, 72.1] |
| power-of-two | 72.1 [72.0, 72.2] |
| round-robin | 75.5 [75.4, 75.6] |

### Table G — S6: hard-rule violations by nodes the filter allowed

| policy | total over all seeds | per run |
|---|---|---|
| min-RTT | 68,788 | 6,879 |
| round-robin | 19,558 | 1,956 |
| global W=200 | 14,430 | 1,443 |
| global W=500 | 12,661 | 1,266 |
| global W=20000 | 12,210 | 1,221 |
| global W=1000 | 12,192 | 1,219 |
| global W=5000 | 11,817 | 1,182 |
| global W=2000 | 11,732 | 1,173 |
| static-weighted | 11,596 | 1,160 |
| global W=10000 | 11,495 | 1,150 |
| per_node W=10000 | 10,830 | 1,083 |
| plain LinUCB | 8,556 | 856 |
| per_node W=20000 | 8,292 | 829 |
| per_node W=5000 | 6,768 | 677 |
| per_node W=500 | 3,178 | 318 |
| per_node W=1000 | 2,199 | 220 |
| per_node W=2000 | 2,183 | 218 |
| per_node W=200 | 0 | 0 |
| power-of-two | 0 | 0 |
| lowest-energy | 0 | 0 |
| least-load | 0 | 0 |

## Recommendation (provisional, to confirm on the real simulator)

- **Against the brief's success criteria, on this stand-in:**
  - *Safe:* Sur's policies only ever chose nodes the filter allowed, which is checked on every decision. The system as a whole is not safe until the filter bug is fixed (Table G).
  - *Faster than plain LinUCB:* there is one positive result, in S2 (finding 3), and none in any other scenario. That is not enough to claim it yet.
  - *Better than the strongest baseline:* not met (finding 8).
- **If a window is used, per-node W = 5000 is the best choice within the brief's sweep.**
  - Its mean goodput is within 1.1 % of plain LinUCB's in every scenario (Table E); the largest gap is 2.5 req/s, in S1.
  - It abandoned the returned node in 1 of 10 seeds (Table B1).
  - It has the faster S2 adaptation (finding 3).
- **Avoid small per-node windows (W ≤ 2000).** They abandoned the returned node in 3–7 of 10 seeds.
- **Avoid global windows until the rush is fixed.** They rushed onto the returning node in 69 of 70 runs, and goodput then fell to 23–32 req/s on average. Even with the filter fixed, their lowest goodput after the return stays well below plain LinUCB's: 148 req/s for W = 1000 and 99 for W = 20000, against 211.
- **The shipped default is still per-node W = 1000, α = 1.** Changing it, for example to W = 5000, is a decision for Sur and the team, best made on the real simulator.
- **To give forgetting a fair test,** see the team list below: fix the filter, then add a change the telemetry cannot see.

## For the team

1. **Bug in Jyotir's feasibility filter (Table G).** A node with status `warming` skips the model, memory, power and temperature checks, because rule 1 in `filter.py` returns early.
   - **How often.** While the S6 node warmed up, the filter kept allowing it after its KV cache was ≥ 90 % full: 234,039 times over the sweep, all in S6. Table G lists them by policy; the α-check runs add the remaining 5,554.
   - **Who was affected.** It hit every policy that put many requests on the warming node: plain LinUCB (856 per run), static-weighted (1,160), round-robin (1,956), min-RTT (6,879), and every sliding-window setting in Table G except per-node W = 200.
     - Least-load and power-of-two also use the node (22 % of requests after its warm-up), but they never sent it a request while its memory was ≥ 90 % full.
     - Lowest-energy hardly uses it.
   - **Why it matters.** It breaks the brief's "Safe" criterion for every affected policy, not just Sur's. It is also the main cause of the S6 damage (finding 5).
   - **What fixing it would change.** The what-if `diagnostics.py --fixed-filter` (seeds 0–9; `filter.py` unchanged) gives the numbers below, from the sweep as run → with the bug fixed. Violations are totals over the 10 seeds; the other columns are means.

     | policy | S6 violations | rush (s) | lowest goodput after the return (req/s) | mean goodput (req/s) |
     |---|---|---|---|---|
     | plain LinUCB | 8,556 → 0 | 5.2 → 1.6 | 77.7 → 211.4 | 233.3 → 234.6 |
     | per-node W = 5000 | 6,768 → 0 | 4.3 → 1.5 | 98.6 → 197.0 | 232.0 → 233.0 |
     | per-node W = 20000 *(extra)* | 8,292 → 0 | 5.1 → 1.6 | 76.4 → 198.0 | 233.1 → 234.3 |
     | global W = 1000 | 12,192 → 0 | 6.3 → 1.6 | 29.7 → 148.0 | 215.4 → 216.7 |
     | static-weighted | 11,596 → 0 | 1.0 → 1.0 | 213.0 → 214.0 | 235.0 → 235.1 |
     | min-RTT | 68,788 → 0 | 2.2 → 1.8 | 109.0 → 214.5 | 224.1 → 235.2 |

   - **Suggested fix (Jyotir's call).** Check rules 2–5 for a warming node as well, then allow it with its `_warming` tag as now. `tests/test_toy_cluster.py::test_s6_warming_node_respects_hard_rules` records the bug and will flag when it is fixed. After the fix, re-run the sweep.
2. **Adaptation-time metric (Riya).** Eight things to know:
   - **Agree on when a request counts.** This stand-in metric puts a request in the 1-s bin of its arrival, the moment of its routing decision. `Riya/metrics/calculate_metrics.py` counts SLO successes by completion time. Either is defensible, but the team's metric should fix one.
   - **It needs enough traffic.** At 25 requests/s, random variation alone gave S1 (where nothing changes) a non-zero "adaptation time" in 2 of 5 seeds for plain LinUCB (6–7 s) and in 3 of 5 for static-weighted (1–7 s). At 240 requests/s every seed gave 0 s (`diagnostics.py --metric-noise`).
   - **A noisy policy gets noise times too.** Even at 240 requests/s, every global window and every per-node window with W ≤ 5000 scores a non-zero time in S1 in 1–5 of 10 seeds (means up to 6.5 s). Read a policy's S1 time as its noise floor before comparing its adaptation times elsewhere.
   - **It can be all-or-nothing.** In S2, for plain LinUCB and the two fastest windows, it is 1–2 s or 8–22 s per seed, depending on whether goodput briefly falls below 0.9·G\* just after the burst (finding 3). Report the per-seed spread, not only the mean.
   - **A late dip does not count.** The rule stops at the first 10 s above 0.9·G\*, so if goodput holds that long and only then dips, it reports 0 s.
     - Plain LinUCB scores 0 s in every S4 and S5 seed, yet its goodput then falls to 150–223 req/s in S4 and 133–221 req/s in S5.
     - For comparison, in S1, where nothing changes, it stays at 213–226 req/s. Static-weighted and min-RTT show no such dip in S4 or S5 (210–223 req/s).
     - In S4 the node heats up with a 30-s time constant, which is why the dip comes late.
     - The deepest dip catches it.
   - **S6 needs a second anchor** at the node's return (400 s), as done here.
   - **It can reward abandonment.** A short adaptation time can mean the policy stopped using the recovered node (finding 4). The two shortest times after the S6 return both come from policies that do not use the node:
     - lowest-energy, 0 s in every seed, which hardly sends that node any requests;
     - per-node W = 1000 with α = 0.1, 0.2 s [0.0, 0.6], which abandoned the node in 7 of 10 seeds.

     Show the node's traffic share next to it.
   - **Static baselines always look fast,** so show G\* and the dip next to it, as the definition already says.
3. **Scenario design.** If the benchmark should show when forgetting helps, consider adding one change the telemetry does *not* show, for example a node that silently gets slower per token. All six current changes are visible in the context features (finding 2).
4. **Warming nodes (Jyotir, Krupesh).** The rush (finding 5) happens even though the stand-in gives the router fresh queue lengths at every request, so stale telemetry is not the cause. The filter fix (item 1) limits it to at most 2 s for every learning policy tested (min-RTT: 3 s). If that is still too much, the router or the filter could cap the share of requests a warming node gets. That is a design decision and is not implemented.
5. **Policy option to discuss (Sur).** A per-node window keeps the requests lost in an outage as its newest evidence (finding 4). Dropping those outcomes, or clearing the node's window when it comes back from `down`, would let it be re-evaluated.
   - The filter fix does not help here: in the what-if, per-node W = 1000 still abandoned the node in 5 of 10 seeds.
   - This changes the method, so it is a team decision and is not implemented.

## Figures (`results/figures/`)

| File | Shows |
|---|---|
| `goodput_<scenario>.png` | goodput over time for W = 200 / 1000 / 5000 and plain LinUCB; per-node and global windows side by side; dots at the mean adaptation time |
| `window_adaptation.png` | adaptation time vs W, every scenario, plus S6 after the node returns |
| `window_steady_level.png` | steady-state goodput G\* vs W |
| `window_goodput.png` | mean goodput over the whole run vs W (S1 shows the cost of forgetting) |
| `alpha_check.png` | goodput and adaptation time vs α |

Colours: per-node = blue, global = orange, plain LinUCB = grey; W runs from light (small) to dark (large). The palette was checked with the dataviz validator. The numbers behind every figure are in `results/summary.csv`.

## Reproduce

```bash
cd geo-inference-scheduler/Sur
python3 window_sweep/run_sweep.py               # ~22 min on 16 processes; writes results/
python3 window_sweep/make_figures.py            # figures from results/ only
python3 window_sweep/make_tables.py --update    # tables from results/summary.csv, into this file
python3 window_sweep/diagnostics.py --help      # the per-seed checks quoted above, and the --fixed-filter what-if
```
