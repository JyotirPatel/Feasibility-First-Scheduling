# How every number in the simulator is produced

**Owner:** Parikshit. This is the "short note: how each number is produced" of the work distribution. Every number comes from one of three places:
- **data**: a public dataset, processed by `data_sources/`;
- **spec**: a published specification or price list;
- **fit**: fitted to a published benchmark by `simulator/calibration.py`.

The rest are marked **assumption**. They are plausible values the team can change in the YAML files, and they are the first things to check against a real vLLM run (brief §5 calls that optional). All sources were read on 2026-10-27.

## 1. Requests (`configs/workload.yaml`, `simulator/workload.py`)

| Number | Value | Where it comes from |
|---|---|---|
| Prompt and answer lengths | the Azure traces' own (input, output) pairs | **data**: Azure LLM inference traces 2023 (Patel et al., Splitwise, ISCA 2024; CC-BY) |
| Interactive class | the conversation trace: 19,365 requests in 58 min, median 1,020 input and 129 output tokens | **data** |
| Batch class | the code trace: 8,819 requests, median 1,469 input and 13 output tokens | **data** |
| Class shares | 68.3 % interactive, 31.7 % batch | **data**: the two traces' rates, 5.530 and 2.566 requests/s |
| Interactive arrivals | gaps resampled from the conversation trace (coefficient of variation 1.09), rescaled to the class rate | **data** |
| Batch arrivals | Poisson at the class rate | **assumption**: the code trace comes in on/off bursts (72 % of its hour is in gaps > 5 s), which would make S1 unstable |
| Requests dropped | 1 conversation request (input + output > 8,192 tokens) | **spec**: Llama-3-8B's context window (`max_position_embeddings`) |
| Arrival rate | 80 requests/s | **assumption**: ~29 % of the 5-node setup's maximum throughput, so S2's 3× burst reaches ~86 % (§4) |
| TTFT SLO, interactive | 250 ms | the slides / work distribution §6 |
| TTFT SLO, batch | 1,000 ms | **assumption** |
| Router's output-length estimate | true length × U(0.7, 1.3) | **assumption**, the same spread as Krupesh's mock simulator |
| User regions | New York, Los Angeles, Chicago, Dallas, Atlanta, San Francisco, in proportion to their populations | **data**: 2020 Census metro-area populations (20.14 M, 13.20 M, 9.62 M, 7.64 M, 6.09 M, 4.75 M), from the Census Bureau's top-50 metro areas chart; San Francisco's from New Geography's table of the same counts |

## 2. Network delay (`data/processed/rtt_ms.csv`)

| Number | Value | Where it comes from |
|---|---|---|
| RTT between a user region and a node | median of the hourly average ping between the two cities' servers, over both days and both directions (96 samples per pair) | **data**: WonderProxy global ping data, 2020-07-19/20 |
| Same-city RTT | 2 ms | **assumption**: a server pinging itself reads ~0 ms |
| S5 | +80 ms to one node | brief §5 |

Examples: Manhattan ↔ Chicago 21.7 ms, Manhattan ↔ San Jose 77.9 ms, Los Angeles ↔ San Francisco 11.8 ms. The pings are server to server, so they are a lower bound for end users.

## 3. GPU speed: the latency model (`configs/calibration.yaml`)

The brief's model (§5) is T_prefill = a_p + b_p · input_tokens and T_decode = output_tokens · t_tok · (1 + c · load), with load = running / capacity. It is fitted per GPU type as follows.

1. **a_p, b_p (H100): fit.** This is a least-squares line through four TTFT measurements of Llama 3.1 8B on one H100 under vLLM: 128 → 28.8 ms, 1,024 → 92.7 ms, 2,024 → 200.1 ms and 200 → 47.3 ms (E2E Networks inference benchmarks).
   - These were measured under load, so the fixed cost includes typical batching delay.
   - Llama 3.1 8B has the same layers and KV heads as Llama 3 8B.
2. **Other GPUs: scaled by spec.**
   - b_p scales by dense BF16 compute: H100 989.5 TFLOPS and A100 312 TFLOPS, from NVIDIA's product pages. Dense compute is half the "with sparsity" figure NVIDIA headlines.
   - a_p scales by memory bandwidth: H100 3.35 TB/s and A100 2.039 TB/s. **Assumption**: the fixed cost is mostly one memory-bound forward pass.
3. **t_tok: spec plus one assumption.** Decoding is memory-bound: every output token reads all 16.06 GB of weights (8.03 B parameters × 2 bytes, bf16). So t_tok = 16.06 GB ÷ (bandwidth × 0.7).
   - The 0.7 is an **assumption** for the share of peak bandwidth that decoding reaches. No published low-load measurement for this model was found, so this is the main number to calibrate against a real vLLM run.
4. **c: fit.** The benchmark's mean time per output token at saturation (22.3, 22.1, 35.5 and 21.6 ms) equals t_tok · (1 + c).
5. **Throughput: fit.** The four benchmark runs were each offered more requests than they completed, so their completed rates are throughput limits.
   - A least-squares fit of 1 / throughput = p · input + d · output gives the GPU time per input and per output token on the H100.
   - On other GPUs, p scales by compute and d by bandwidth.
   - For the workload's mean request this is the GPU's maximum throughput.
6. **Capacity: fit.** Capacity is the number of running requests per GPU at which the model above reaches that maximum throughput: max req/s × service time at load 1.
7. **KV cache: spec.**
   - Each token holds 2 (keys and values) × 32 layers × 8 KV heads × 128 dims × 2 bytes = 128 KiB (Llama-3-8B's `config.json`).
   - Per GPU, that gives (80 GB × 0.9 − 16.06 GB) ÷ 128 KiB tokens. The 0.9 is vLLM's default `gpu_memory_utilization`.

`python3 simulator/calibration.py` prints all of this; `tests/test_calibration.py` checks that the block below matches it:

<!-- calibration:start -->
```text
workload mean request: 1437 input tokens, 153 output tokens
KV cache: 131,072 bytes per token; weights 16.06 GB
TTFT fit on H100-SXM: a_p = 19.85 ms, b_p = 0.08574 ms/token
     128 tokens: measured   28.84 ms, fitted   30.83 ms
    1024 tokens: measured   92.74 ms, fitted  107.66 ms
    2024 tokens: measured  200.06 ms, fitted  193.40 ms
     200 tokens: measured   47.25 ms, fitted   37.00 ms
GPU time fit on H100-SXM: 0.0466 ms per input token, 0.1400 ms per output token
     128 in /   128 out: measured  35.04 req/s, fitted  41.86 req/s
    1024 in /    30 out: measured  19.03 req/s, fitted  19.25 req/s
    2024 in /   128 out: measured   8.95 req/s, fitted   8.90 req/s
     200 in /  2024 out: measured   3.42 req/s, fitted   3.42 req/s

GPU               a_p ms b_p ms/tok t_tok ms     c cap/GPU KV tok/GPU max req/s/GPU
H100-SXM           19.85    0.08574     6.85  2.70      45    426,788         11.31
A100-80GB-SXM      32.62    0.27193    11.25  2.70      27    426,788          4.04
```
<!-- calibration:end -->

**What this means:**
- An A100 needs 32.6 + 0.272 × 1,437 ≈ 424 ms to start the mean request, so it cannot meet the 250 ms interactive SLO for long prompts. An H100 needs ≈ 143 ms.
- Learning this interaction between request length and node type is exactly what a contextual policy is for.
- **Limits:** the model has no load term for prefill, and a request's speed is fixed when it starts.

## 4. Nodes (`configs/nodes_5.yaml`, `configs/nodes_10.yaml`)

| Number | Value | Where it comes from |
|---|---|---|
| Node | one 8-GPU server serving Llama-3-8B | **spec**: DGX H100 / DGX A100 have 8 GPUs |
| Capacity | 8 × 45 = 360 (H100), 8 × 27 = 216 (A100) | **fit** (§3) |
| KV cache | 8 × 426,788 = 3,414,304 tokens | **spec** (§3) |
| Max throughput | 90.4 req/s (H100 node), 32.3 req/s (A100 node); 277.8 req/s for the 5-node setup, 613.7 for 10 nodes | **fit** (§3) |
| Sites | Manhattan, Buffalo, Albany, San Jose, Los Angeles (5); plus Garden City, Syracuse, Fremont, Sacramento, San Diego (10) | cities with both a WonderProxy server and a NYISO / CAISO price zone |
| Telemetry period | 1 s | handbook §5.2 |

## 5. Power

| Number | Value | Where it comes from |
|---|---|---|
| Server max power | 10.2 kW (H100), 6.5 kW (A100) | **spec**: NVIDIA DGX H100 / DGX A100 user guides |
| Idle draw | 30 % of max | **assumption** |
| Utilization | load × (1 + c) / (1 + c × load): the share of maximum token throughput the decode model implies | derived from §3. With c = 2.7, 10 % of the slots already produce 29 % of the maximum tokens/s |
| Draw | max × (0.3 + 0.7 × utilization) | |
| Site supply | max × 1.25 | **assumption** |
| Power headroom | site supply − draw (0 when down) | |

With Jyotir's 2 kW minimum, an A100 node is filtered out above ~92 % utilization.

## 6. Temperature

| Number | Value | Where it comes from |
|---|---|---|
| Inlet air | 25 °C | **assumption**, inside the DGX operating range of 5–30 °C (NVIDIA user guides) |
| Rise at full power | 50 °C, so 40 °C idle and 75 °C at full power | **assumption** |
| Response | first order, time constant 30 s, toward inlet + 50 °C × (draw / max) | **assumption** |
| Throttling | none below 80 °C, linear to 2× slower at 90 °C | **assumption** |
| Filter limit | 85 °C | Jyotir's `feasibility.yaml` |
| S4 | inlet +40 °C, to 65 °C | **assumption**: a severe cooling failure. The node then throttles whenever it has work and crosses 85 °C above ~14 % utilization (§8) |

## 7. Prices and cost

| Number | Value | Where it comes from |
|---|---|---|
| Electricity price | each site's zone (NYISO N.Y.C., WEST, CAPITL, LONGIL, CENTRL; CAISO NP15, SP15), day-ahead, hourly; $/MWh ÷ 1,000 | **data**: NYISO zonal LBMP and CAISO OASIS hub LMP |
| Day | 2024-04-17, a Wednesday | **data**: the weekday of April 2024 closest to the month's median at 19:00 and 02:00 UTC |
| Base hour | 19:00 UTC (12:00 in California) | California hubs $0.00–3.23/MWh (SP15 is negative, floored), New York $21–27 |
| S3 hour | 02:00 UTC the next day (19:00 in California) | California $46.11–49.92, New York $23.40–26.97 |
| Price floor | 0 | the telemetry contract needs prices ≥ 0, and a site still pays delivery charges |
| GPU rent | $3.99 (H100), $2.79 (A100) per GPU-hour | **spec**: Lambda's public price list, 8-GPU instances |
| Energy per request | its share of the node's draw (draw / running when it starts) × its service time | |
| Cost per request | that energy × the site's price + its share of the node's rent (8 GPUs × rent / running) × its service time | |

A lightly used node therefore costs more per request, as a real idle server does.

## 8. The six scenarios (`event_traces/`)

| Scenario | Change at t0 = 200 s | Basis |
|---|---|---|
| S1 | nothing | brief |
| S2 | arrival rate × 3 for 120 s | brief |
| S3 | prices switch from 19:00 to 02:00 UTC of the real day | **data** (§7) |
| S4 | us-east-nyc cooling air +40 °C | brief, with an assumed size |
| S5 | us-east-nyc delay +80 ms | brief |
| S6 | us-east-nyc down; back at 400 s, "warming" and 3× slower, falling to normal over 60 s, then "up" | brief; the 3× and 60 s are **assumptions** |

S4, S5 and S6 hit us-east-nyc, the H100 node next to the largest user region. Each scenario was checked to change what it should (`tests/test_cluster.py`).

## 9. What to calibrate first against a real vLLM run

1. **The decode bandwidth share (0.7).** It sets t_tok, which sets c and capacity.
2. **TTFT at low load.** The fitted a_p and b_p come from loaded runs.
3. **GPU temperature and power at a few loads.** These are the idle share, the rise at full power and the time constant.
4. **The warm-up time and slowdown after a restart.**
