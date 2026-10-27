# Simulator and workload

*Draft of Parikshit's report section (simulator and workload). Riya merges it into the full report. Citation keys refer to `references.bib` in this folder.*

*Sources of the numbers:*
- *Every number below is produced by the code in `Parikshit/`.*
- *`simulator/NUMBERS.md` gives the source of each one.*
- *The scenario table is printed by `python3 simulator/scenario_effects.py`.*

## Why a simulator

Policies must be compared under identical conditions, including outages, overheating and price changes that cannot be staged on real hardware within the project. We therefore evaluate the router on a discrete-event simulation of geo-distributed inference sites, written with SimPy [simpy].

Wherever public data exist, the simulation uses them:
- real request traces;
- real electricity prices;
- measured network delays;
- a published GPU benchmark.

The other numbers are stated assumptions. They are kept in configuration files, so they can be changed and checked against a real serving engine.

## The simulated cluster

The default setup has five sites in New York State and California. Each site is one 8-GPU server serving Llama-3-8B; two are NVIDIA H100 servers and three are A100 servers. Every site is in a city that has both a WonderProxy ping server and a wholesale electricity price zone, so both its network delay and its electricity price come from data. A 10-node setup adds five more sites in the same two states.

**Sites of the five-node setup.**

| Node | City | GPU | Electricity price zone |
|---|---|---|---|
| us-east-nyc | New York (Manhattan) | H100 | NYISO N.Y.C. |
| us-east-buf | Buffalo | A100 | NYISO WEST |
| us-east-alb | Albany | A100 | NYISO CAPITL |
| us-west-sjc | San Jose | H100 | CAISO NP15 |
| us-west-lax | Los Angeles | A100 | CAISO SP15 |

**Telemetry.** Every second (one tick), each node reports one telemetry record. The record holds the node's:
- status (up, down or warming);
- delay to each user region;
- queue length, running requests and capacity;
- KV-cache use and models loaded;
- power headroom and temperature;
- electricity and GPU prices.

The router decides on the latest records, so its view can be up to one second old, as for a real router that polls its sites.

**Serving.** A node serves requests first come, first served. A request starts when a slot is free and its prompt plus answer fit in the free KV-cache memory; otherwise it waits in the queue. The request's times are fixed when it starts:

> TTFT = network delay + queue wait + T_prefill,  T_prefill = a_p + b_p · input tokens
>
> end-to-end = TTFT + T_decode,  T_decode = output tokens · t_tok · (1 + c · load)

Here *load* is the share of the node's slots in use. Heat and the warm-up after an outage slow down both phases (see below).

## Requests

**The traces.** Requests come from the Azure LLM inference traces of 2023 [patel2024splitwise; azure2023traces]: one hour of production traffic from two services.

| Class | Trace | Requests | Median input | Median output | TTFT SLO |
|---|---|---|---|---|---|
| interactive | conversation | 19,365 | 1,020 tokens | 129 tokens | 250 ms |
| batch | code | 8,819 | 1,469 tokens | 13 tokens | 1,000 ms (assumption) |

One conversation request was dropped: its prompt plus answer exceed Llama-3-8B's 8,192-token context.

**Rates and arrivals.** Each request is a real (input, output) pair from its trace. The classes keep their traces' relative rates (68.3 % interactive, 31.7 % batch) at a total of 80 requests/s.
- **Interactive arrivals:** gaps resampled from the conversation trace. Their coefficient of variation is 1.09, so arrivals are burstier than a Poisson stream.
- **Batch arrivals:** a Poisson stream. The code trace itself comes in on/off bursts (72 % of its hour lies in gaps longer than 5 s), which would make the stable scenario unstable.

**Where requests come from.** Each request comes from one of six user regions: New York, Los Angeles, Chicago, Dallas, Atlanta or San Francisco. Its probability is proportional to the region's 2020 census metro population [census2020metros; newgeography2020metros].

**What the router knows.** The router sees an estimate of each request's output length: the true length × U(0.7, 1.3). The node generates the true length.

**Reproducibility.** All randomness comes from generators seeded by the run's seed, the class and the stream, so a seed fixes every request.
- Every policy sees exactly the same requests.
- Scenarios S3–S6 have exactly the requests of S1; S2 adds its burst on top.

All comparisons are therefore paired.

## Latency model and calibration

**Fitting the constants.** The constants are fitted per GPU type in three steps.

1. **a_p and b_p (H100).** These form a least-squares line through four TTFT measurements of Llama 3.1 8B served by vLLM [kwon2023vllm] on one H100, from E2E Networks' published benchmark [e2e_benchmarks].
   - Llama 3.1 8B has the same layers and KV heads as Llama 3 8B.
   - The line is within 15 ms of every measurement: 28.8 → 30.8, 92.7 → 107.7, 200.1 → 193.4 and 47.3 → 37.0 ms.
2. **t_tok and c.** Decoding is memory-bound: each output token reads all 16.06 GB of weights.
   - So t_tok = 16.06 GB ÷ (memory bandwidth × 0.7). The 0.7, the share of peak bandwidth that decoding reaches, is an assumption.
   - c then follows from the benchmark's time per output token at saturation, which equals t_tok · (1 + c).
3. **The A100.** Its constants are scaled from the H100's by NVIDIA's specifications [nvidia_h100; nvidia_a100].
   - b_p scales by dense BF16 compute: 989.5 vs 312 TFLOPS.
   - a_p and t_tok scale by memory bandwidth: 3.35 vs 2.039 TB/s.

**Throughput and capacity.** Each benchmark run was offered more requests than it completed, so its completion rate is a throughput limit.
- A fit of 1/throughput = p · input + d · output gives each GPU's maximum throughput for the workload's mean request (1,437 input, 153 output tokens). The fit is within 1.2 % on three of the four runs and 19.5 % on the shortest.
- A node's capacity is the number of running requests at which the model reaches that maximum throughput.

**KV cache.** It holds 128 KiB per token, computed from the model's configuration [llama3_config]. Its size is 90 % of GPU memory minus the weights, vLLM's default.

**Fitted constants per GPU.**

| GPU | a_p (ms) | b_p (ms/token) | t_tok (ms) | c | slots per GPU | max requests/s per GPU |
|---|---|---|---|---|---|---|
| H100 | 19.85 | 0.0857 | 6.85 | 2.70 | 45 | 11.31 |
| A100 | 32.62 | 0.2719 | 11.25 | 2.70 | 27 | 4.04 |

**What this means for the cluster.**
- An 8-GPU H100 node serves up to 90 requests/s and an A100 node up to 32.
- The five-node cluster serves up to 278 requests/s. The default 80 requests/s is therefore about 29 % of that, and S2's burst about 86 %.
- The 10-node cluster serves up to 614 requests/s; 177 requests/s gives it the same relative load.

**What the policy can learn.** Even on an idle node, prefill alone exceeds the 250 ms interactive SLO for 59.5 % of interactive requests on an A100, but for only 10.2 % on an H100. For batch requests, 17.3 % exceed 1,000 ms on an A100 and none on an H100. Whether a node can meet a request's SLO thus depends jointly on the request's length and the node's GPU type. A contextual policy can learn this interaction; a fixed rule would have to be told the hardware.

## Network delay, power, heat and prices

**Network delay.** The delay between a user region and a site is the median of the hourly average pings between the two cities' servers, from WonderProxy's public data of 19–20 July 2020 [wonderproxy2020pings]. Each city pair has at least 96 samples. A user in the site's own city gets 2 ms. The pings are server to server, so they are a lower bound for real users.

**Round-trip time from each user region to each site (ms).**

| User region | us-east-nyc | us-east-buf | us-east-alb | us-west-sjc | us-west-lax |
|---|---|---|---|---|---|
| New York | 2.0 | 10.8 | 4.3 | 77.9 | 65.8 |
| Los Angeles | 65.8 | 69.1 | 68.1 | 13.2 | 2.0 |
| Chicago | 21.7 | 19.8 | 27.6 | 53.2 | 58.5 |
| Dallas | 44.2 | 38.2 | 40.8 | 48.1 | 33.5 |
| Atlanta | 18.0 | 27.0 | 24.2 | 64.0 | 51.0 |
| San Francisco | 62.1 | 80.8 | 73.5 | 2.8 | 11.8 |

**Power.**
- **Draw.** An idle server draws 30 % of its maximum power. Its draw then rises linearly with utilization, the share of its maximum token throughput that the decode model implies.
  - The maximum is 10.2 kW for a DGX H100 and 6.5 kW for a DGX A100 [nvidia_dgx_h100; nvidia_dgx_a100].
  - Because of batching, utilization rises quickly: with c = 2.7, 10 % of the slots already produce 29 % of the maximum tokens per second.
- **Headroom.** The site can supply 25 % more than the server's maximum (an assumption). The reported power headroom is that supply minus the current draw.
- **Filter.** With the filter's 2 kW minimum, an A100 node is excluded above about 92 % utilization.

**Temperature.**
- **Response.** GPU temperature follows the power draw with a first-order response (time constant 30 s). It moves toward the inlet air temperature plus 50 °C at full power. With 25 °C inlet air, that is 40 °C idle and 75 °C at full power.
- **Throttling.** Above 80 °C the GPU throttles, up to 2× slower at 90 °C.
- **Filter.** The filter excludes a node at 85 °C or above.
- These thermal constants are assumptions, since no per-site measurements are public.

**Prices.**
- **Electricity.** Each site pays the real hourly day-ahead price of its zone: NYISO zonal LBMP [nyiso_lbmp] or CAISO hub LMP [caiso_oasis].
  - The day is Wednesday, 17 April 2024, a weekday close to the month's median at both hours used.
  - Runs start at 19:00 UTC (noon in California). Solar output then pushes California's prices near zero or below: $3.23/MWh at NP15 and −$31.84/MWh at SP15, floored at zero. New York's prices are $21–27/MWh.
- **GPU rent.** Lambda's on-demand list price per GPU-hour [lambda_pricing]: $3.99 for an H100, $2.79 for an A100.
- **Per request.** A request's energy is its share of the node's power draw over its service time. Its cost adds its share of the node's rent. A lightly used node therefore costs more per request, as a real idle server does.

## The six scenarios

Each scenario is a replayable trace file: 600 s of simulated time, with the change at t0 = 200 s. S4–S6 hit us-east-nyc, the H100 site next to the largest user region.

**What each trace changes, and what it did in one run** with the feasibility filter and the least-load baseline (seed 0). "SLO met" is the share of requests arriving in each window that met their TTFT SLO; rejected and failed requests count as missed.

| Scenario | Change | SLO met 0–200 s | 200–400 s | 400–600 s | Measured effect |
|---|---|---|---|---|---|
| S1 stable | nothing | 73.4 % | 73.4 % | 73.5 % | — |
| S2 traffic burst | arrival rate × 3 for 120 s | 73.4 % | 73.9 % | 73.6 % | 80 → 239 requests/s; slot use 12 % → 67 %; 7,642 requests sent to a node whose true power headroom had already fallen below 2 kW |
| S3 price shift | every site switches to its price at 02:00 UTC (19:00 in California) | 73.4 % | 73.4 % | 73.5 % | the cheapest site changes from Los Angeles ($0.000/kWh) to Buffalo ($0.023); California's sites rise to $0.046–0.050 |
| S4 thermal throttle | us-east-nyc's inlet air +40 °C | 73.4 % | 70.3 % | 68.9 % | the node peaks at 85 °C (49 °C before) and is at or above the limit in 279 of 400 ticks; its share of requests falls from 27 % to 13 %; 519 requests sent to it after it had reached 85 °C |
| S5 network degradation | us-east-nyc's delay +80 ms | 73.4 % | 70.4 % | 70.7 % | the delay from New York rises from 2 to 82 ms; least-load ignores delay and keeps sending the node 27 % of requests |
| S6 outage and recovery | us-east-nyc down at 200 s; back at 400 s, warming (3× slower, normal after 60 s) | 73.3 % | 67.2 % | 71.8 % | 26 running or queued requests lost; none routed to it while down; it gets 19 % of requests while warming, 27 % after |

**What the baseline's SLO share shows.** The least-load baseline balances slots and ignores delay, price and GPU type, so its SLO share shows each change's direct effect.
- Heat, delay and the outage all lower it.
- The price shift does not, since price does not enter the SLO.
- The burst does not either, because the cluster absorbs it below its maximum throughput (see the limitations).

The comparison of policies is in the evaluation section.

## Checks

- **Telemetry.** During every run, each record is checked against the telemetry schema, and a run with an invalid record stops. The tests also check that every record of every scenario passes the router's own validator.
- **Accounting.** Every routed request receives exactly one outcome (served or failed), checked at the end of every run.
- **Reproducibility.** The same seed gives identical outcomes, also in separate processes with different Python hash seeds; different seeds give different outcomes.
- **Integration.** The simulator drives the router both in-process and over HTTP, with identical decisions. The router's decision-log validator accepts the logs.
- **Data.** The processed data files are rebuilt byte for byte from the raw downloads, and their checksums are recorded.
- **Tests and speed.** 122 automated tests cover these checks and every module. A 600-s run of the five-node setup (about 48,000 requests) takes about 7 s.

## Limitations

- **Prefill does not slow down with load**, as in the brief's model. TTFT rises only when a node runs out of slots or KV-cache memory. Real engines interleave prefill with decoding, so their TTFT also grows with load.
  - In S2 the cluster absorbs the burst below its maximum throughput, so an even spread keeps its TTFT.
  - The burst shows instead in slot use, decode time and power headroom, and it hurts policies that concentrate traffic on few nodes.
- **A request's speed is fixed when it starts.** Later changes in load or heat do not affect it.
- **Some numbers are assumptions** to calibrate with one real vLLM run (brief §5 calls that optional):
  - the decode bandwidth share (0.7);
  - the power and thermal constants;
  - the warm-up after a restart.
- **The fitted TTFT includes batching delay.** The benchmark's TTFTs were measured under load, so the fitted a_p includes typical batching delay.
- **Prices are wholesale day-ahead prices.** Retail tariffs add delivery charges, which would shrink the S3 price gap. Negative prices are floored at zero.
- **The delay data** are from 2020 and server to server.
- **The router's view is up to one second old.** This is a property of the system, not a bug in the simulator.
  - As a result, in S2 and S4 some requests go to a node that has just crossed a limit. The table counts them, using each node's true state at the moment of the decision.
  - More frequent telemetry would reduce this. So would counting the router's own recent placements against power and temperature, as it already does for load.
