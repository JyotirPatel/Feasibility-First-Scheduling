# Parikshit / data_sources

**Owner:** Parikshit. **Used by:**
- the simulator, which reads only `../data/processed/`;
- Riya, who gets realistic workloads from it.

| File | What it is |
|---|---|
| `sources.yaml` | every URL, checksum, licence, date, price zone and city → server mapping |
| `download_data.py` | downloads the raw files into `../data/raw/` (not in git); checks SHA-256 where it is known |
| `preprocess_traces.py` | turns them into the small files in `../data/processed/` (in git); byte-for-byte reproducible |

```bash
python3 data_sources/download_data.py         # ~52 MB, mostly the ping data
python3 data_sources/preprocess_traces.py     # rewrites data/processed/ and its manifest.json
```

## Sources

| What | Dataset | Terms |
|---|---|---|
| Request arrivals and token counts | Azure LLM inference traces 2023: conversation (19,366 requests) and code (8,819), one hour on 2023-11-16 | CC-BY. Cite: P. Patel, E. Choukse, C. Zhang, A. Shah, Í. Goiri, S. Maleki, R. Bianchini, *Splitwise: Efficient generative LLM inference using phase splitting*, ISCA 2024. |
| Electricity prices, New York | NYISO day-ahead zonal LBMP, hourly (April 2024 archive) | public market data from NYISO |
| Electricity prices, California | CAISO OASIS day-ahead LMP at the NP15 and SP15 trading hubs, hourly | public market data from CAISO |
| Network delay | WonderNetwork / WonderProxy global ping data, 2020-07-19/20 (hourly pings between ~250 servers) | credit and link WonderProxy (https://wonderproxy.com/blog/a-day-in-the-life-of-the-internet/). Their live ping pages ask not to be scraped, so only this published download is used. |
| GPU speed | E2E Networks' published vLLM benchmark of Llama 3.1 8B on one H100, plus NVIDIA's GPU and DGX specifications | numbers quoted in `../configs/calibration.yaml` |

## What preprocessing does

- **Azure.**
  - Arrival times become seconds after the first request.
  - Requests whose input + output exceed Llama-3-8B's 8,192-token context are dropped: 1 request.
- **Prices.**
  - The NYISO zones N.Y.C., WEST, CAPITL, LONGIL and CENTRL, and the CAISO hubs NP15 and SP15, become UTC hours.
  - The two days kept are 2024-04-17 and 2024-04-18 (UTC), and every zone must have all 48 hours.
  - The raw $/MWh is kept, including negative prices; the simulator floors them.
- **RTT.** The RTT is the median of the hourly average ping between two cities, over both days and both directions. Every pair of the 14 cities must be present, each with at least 96 samples.

`../data/processed/manifest.json` records the SHA-256 of every input and output. `tests/test_data_sources.py` checks the following:
- the committed files still match the manifest;
- when the raw files are present, preprocessing them again reproduces the committed files exactly.
