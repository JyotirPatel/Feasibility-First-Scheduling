# Parikshit / data

**Owner:** Parikshit. This folder holds the public data behind the simulator.

| Folder | What it holds | In git? |
|---|---|---|
| `processed/` | the small cleaned files the simulator reads, with `manifest.json` (see its README) | yes |
| `raw/` | the downloads, about 52 MB, fetched by `../data_sources/download_data.py` | no (`.gitignore`) |

Rebuild `processed/` from `raw/` with `python3 data_sources/preprocess_traces.py`. Sources, licences and citations: `../data_sources/README.md`.
