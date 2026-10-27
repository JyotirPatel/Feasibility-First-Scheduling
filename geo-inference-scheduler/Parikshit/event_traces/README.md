# Parikshit / event_traces

**Owner:** Parikshit. **Used by:** Riya's experiment runner, which replays every trace for every policy × seed (brief §8), and Sur's window sweep.

These are the six change scenarios of brief §5 as replayable trace files. Each run is 600 s of simulated time, and the change starts at t0 = 200 s. A trace file + a seed + the files in `../configs/` and `../data/processed/` fix a run completely: the same inputs give the same requests and the same node behaviour.

| File | What changes |
|---|---|
| `s1_stable.yaml` | nothing |
| `s2_traffic_burst.yaml` | the arrival rate is 3× for 120 s |
| `s3_price_shift.yaml` | electricity prices switch from the real noon hour to the real evening hour of 2024-04-17 (Pacific time): California's hubs jump from ~$0–3 to ~$46–50/MWh and New York becomes the cheap region |
| `s4_thermal_throttle.yaml` | the cooling air of us-east-nyc gets 40 °C hotter: it throttles, and when busy it crosses the filter's 85 °C limit |
| `s5_network_degradation.yaml` | the delay from every user region to us-east-nyc rises by 80 ms |
| `s6_outage_recovery.yaml` | us-east-nyc fails at t0, then returns at 400 s, "warming" and 3× slower, back to normal over 60 s |

Event kinds: `arrival_rate`, `energy_prices`, `inlet_temperature`, `rtt`, `node_down` and `node_return`. Their fields are checked by `simulator/config.py`: a misspelled key, an event after the end of the run, or a return without an outage is refused.

Paired comparisons: the base requests of S2 are exactly those of S1 (the burst only adds requests), and S3–S6 have exactly S1's requests.

Why each number: `../simulator/NUMBERS.md` §8. Tests: `../tests/test_configs.py` and `../tests/test_cluster.py`, which run every scenario and check that it changes what it should.
