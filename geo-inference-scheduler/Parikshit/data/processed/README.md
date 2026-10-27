# Parikshit / data / processed

**Owner:** Parikshit. These are the cleaned data the simulator reads, written by `../../data_sources/preprocess_traces.py`. Do not edit by hand; re-run the script instead (`manifest.json` records the input and output hashes).

| File | Rows | Columns | From |
|---|---|---|---|
| `azure_conv.csv.gz` | 19,365 | `t_s, input_tokens, output_tokens` | Azure LLM inference trace, conversation |
| `azure_code.csv.gz` | 8,819 | `t_s, input_tokens, output_tokens` | Azure LLM inference trace, code |
| `prices_hourly.csv` | 336 | `t_utc, zone, lbmp_usd_mwh` | NYISO (5 zones) and CAISO (2 hubs), day-ahead, 2024-04-17/18 UTC |
| `rtt_ms.csv` | 91 | `city_a, city_b, rtt_ms, samples` | WonderProxy pings, 2020-07-19/20 |
| `manifest.json` | — | inputs, parameters, outputs | — |

**Attribution:**
- **Azure LLM inference traces:** CC-BY, Microsoft Azure Public Dataset; cite Patel et al., Splitwise, ISCA 2024.
- **Ping data:** WonderNetwork / WonderProxy (https://wonderproxy.com/blog/a-day-in-the-life-of-the-internet/).
- **Prices:** NYISO and CAISO public market data.
