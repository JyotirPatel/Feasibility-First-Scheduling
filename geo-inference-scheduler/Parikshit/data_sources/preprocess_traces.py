"""
Preprocess the raw public data — owner: Parikshit

Turns the files that download_data.py fetched into ../data/raw/ into the small,
cleaned files the simulator reads, in ../data/processed/ (in git):

  azure_conv.csv.gz   one row per request of the Azure conversation trace:
  azure_code.csv.gz   t_s (seconds after the trace's first request), input_tokens, output_tokens.
                      Requests longer than the model's context window are dropped.
  prices_hourly.csv   t_utc, zone, lbmp_usd_mwh: NYISO zones and CAISO hubs, day-ahead, hourly,
                      for the days in sources.yaml (raw prices; the simulator floors them at 0)
  rtt_ms.csv          city_a, city_b, rtt_ms, samples: median round-trip time between two
                      WonderProxy servers, over both days and both directions
  manifest.json       inputs (SHA-256), parameters, outputs (SHA-256, rows) and what was dropped

The outputs are byte-for-byte reproducible from the same raw files (sorted rows, fixed
number formats, gzip without a timestamp).

Usage (from the Parikshit/ folder):
    python3 data_sources/preprocess_traces.py
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import zipfile
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
PARIKSHIT_DIR = os.path.dirname(_HERE)
SOURCES_PATH = os.path.join(_HERE, "sources.yaml")
RAW_DIR = os.path.join(PARIKSHIT_DIR, "data", "raw")
OUT_DIR = os.path.join(PARIKSHIT_DIR, "data", "processed")
PINGS_CHUNK_ROWS = 500_000


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write_text(path: str, text: str) -> None:
    """Write text; a .gz path gets gzip without a timestamp, so the bytes are reproducible."""
    data = text.encode()
    if path.endswith(".gz"):
        buf = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:
            gz.write(data)
        data = buf.getvalue()
    with open(path, "wb") as f:
        f.write(data)


# ── Azure LLM inference traces ───────────────────────────────────────────────


def azure_trace(raw_csv: str, context_limit: int) -> tuple[pd.DataFrame, dict]:
    """Requests as t_s / input_tokens / output_tokens, without the ones longer than the context window."""
    df = pd.read_csv(raw_csv)
    t = pd.to_datetime(df["TIMESTAMP"], format="mixed")
    if not t.is_monotonic_increasing:
        raise ValueError(f"{raw_csv}: timestamps are not in order")
    out = pd.DataFrame(
        {
            "t_s": (t - t.iloc[0]).dt.total_seconds(),
            "input_tokens": df["ContextTokens"].astype(int),
            "output_tokens": df["GeneratedTokens"].astype(int),
        }
    )
    if (out[["input_tokens", "output_tokens"]] < 1).any().any():
        raise ValueError(f"{raw_csv}: a request has no input or output tokens")
    too_long = out["input_tokens"] + out["output_tokens"] > context_limit
    kept = out[~too_long].reset_index(drop=True)
    stats = {
        "rows_in": len(out),
        "dropped_over_context": int(too_long.sum()),
        "rows_out": len(kept),
        "first_timestamp": str(t.iloc[0]),
        "span_s": round(float(out["t_s"].iloc[-1]), 3),
        "mean_rate_rps": round(len(kept) / float(out["t_s"].iloc[-1]), 4),
    }
    return kept, stats


def azure_csv_text(df: pd.DataFrame) -> str:
    lines = ["t_s,input_tokens,output_tokens"]
    lines += [f"{t:.6f},{i},{o}" for t, i, o in zip(df["t_s"], df["input_tokens"], df["output_tokens"], strict=True)]
    return "\n".join(lines) + "\n"


# ── Electricity prices ───────────────────────────────────────────────────────


def nyiso_prices(zip_paths: list[str], zones: list[str], timezone: str) -> pd.DataFrame:
    frames = []
    for path in zip_paths:
        with zipfile.ZipFile(path) as z:
            for name in sorted(z.namelist()):
                with z.open(name) as f:
                    frames.append(pd.read_csv(f))
    n = pd.concat(frames, ignore_index=True)
    n = n[n["Name"].isin(zones)].copy()
    local = pd.to_datetime(n["Time Stamp"], format="%m/%d/%Y %H:%M")
    n["t_utc"] = local.dt.tz_localize(timezone, ambiguous="infer", nonexistent="raise").dt.tz_convert("UTC")
    n["zone"] = "NYISO:" + n["Name"]
    n["lbmp_usd_mwh"] = n["LBMP ($/MWHr)"].astype(float)
    return n[["t_utc", "zone", "lbmp_usd_mwh"]]


def caiso_prices(zip_path: str, hubs: dict[str, str]) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"{zip_path}: expected one CSV inside, found {names}")
        with z.open(names[0]) as f:
            c = pd.read_csv(f)
    c = c[(c["LMP_TYPE"] == "LMP") & c["NODE"].isin(hubs.values())].copy()
    by_node = {node: hub for hub, node in hubs.items()}
    c["t_utc"] = pd.to_datetime(c["INTERVALSTARTTIME_GMT"], utc=True)
    c["zone"] = "CAISO:" + c["NODE"].map(by_node)
    c["lbmp_usd_mwh"] = c["MW"].astype(float)
    return c[["t_utc", "zone", "lbmp_usd_mwh"]]


def keep_days(prices: pd.DataFrame, days_utc: list[str]) -> pd.DataFrame:
    start = pd.Timestamp(days_utc[0], tz="UTC")
    end = pd.Timestamp(days_utc[-1], tz="UTC") + pd.Timedelta(days=1)
    kept = prices[(prices["t_utc"] >= start) & (prices["t_utc"] < end)]
    kept = kept.sort_values(["t_utc", "zone"]).reset_index(drop=True)
    hours = int((end - start) / pd.Timedelta(hours=1))
    counts = kept.groupby("zone").size()
    if (counts != hours).any() or kept.duplicated(["t_utc", "zone"]).any():
        raise ValueError(f"prices are not one value per hour and zone over {days_utc}: {counts.to_dict()}")
    return kept


def prices_csv_text(prices: pd.DataFrame) -> str:
    lines = ["t_utc,zone,lbmp_usd_mwh"]
    for t, zone, p in zip(prices["t_utc"], prices["zone"], prices["lbmp_usd_mwh"], strict=True):
        lines.append(f"{t.strftime('%Y-%m-%dT%H:%M:%SZ')},{zone},{p:.5f}")
    return "\n".join(lines) + "\n"


# ── Network delay ────────────────────────────────────────────────────────────


def city_rtts(pings_gz: str, servers_csv: str, cities: dict[str, int]) -> pd.DataFrame:
    """Median RTT between every two configured cities, over all hours and both directions."""
    servers = pd.read_csv(servers_csv)
    missing = set(cities.values()) - set(servers["id"])
    if missing:
        raise ValueError(f"server ids {sorted(missing)} are not in {servers_csv}")
    ids = set(cities.values())
    parts = []
    for chunk in pd.read_csv(pings_gz, chunksize=PINGS_CHUNK_ROWS, usecols=["source", "destination", "avg"]):
        parts.append(chunk[chunk["source"].isin(ids) & chunk["destination"].isin(ids)])
    p = pd.concat(parts, ignore_index=True)
    p = p[p["source"] != p["destination"]]
    name_of = {sid: city for city, sid in cities.items()}
    a, b = p["source"].map(name_of), p["destination"].map(name_of)
    p = p.assign(city_a=np.where(a < b, a, b), city_b=np.where(a < b, b, a))
    out = p.groupby(["city_a", "city_b"])["avg"].agg(rtt_ms="median", samples="size").reset_index()
    expected = len(cities) * (len(cities) - 1) // 2
    if len(out) != expected:
        raise ValueError(f"ping data covers {len(out)} of the {expected} city pairs")
    return out.sort_values(["city_a", "city_b"]).reset_index(drop=True)


def rtt_csv_text(rtt: pd.DataFrame) -> str:
    lines = ["city_a,city_b,rtt_ms,samples"]
    for a, b, ms, n in zip(rtt["city_a"], rtt["city_b"], rtt["rtt_ms"], rtt["samples"], strict=True):
        lines.append(f"{a},{b},{ms:.3f},{n}")
    return "\n".join(lines) + "\n"


# ── Main ─────────────────────────────────────────────────────────────────────


def preprocess(raw_dir: str = RAW_DIR, out_dir: str = OUT_DIR, sources_path: str = SOURCES_PATH) -> dict:
    with open(sources_path) as f:
        src = yaml.safe_load(f)
    os.makedirs(out_dir, exist_ok=True)
    inputs, outputs, details = [], {}, {}

    az = src["azure_llm_traces"]
    for name in az["files"]:
        raw_csv = os.path.join(raw_dir, "azure", f"AzureLLMInferenceTrace_{name}.csv")
        df, stats = azure_trace(raw_csv, az["context_limit_tokens"])
        out = os.path.join(out_dir, f"azure_{name}.csv.gz")
        _write_text(out, azure_csv_text(df))
        inputs.append(raw_csv)
        outputs[os.path.basename(out)] = len(df)
        details[f"azure_{name}"] = stats

    ny_zips = [os.path.join(raw_dir, "nyiso", f"{m}01damlbmp_zone_csv.zip") for m in src["nyiso"]["months"]]
    c = src["caiso"]
    ca_zip = os.path.join(raw_dir, "caiso", f"caiso_dam_hubs_{c['start_utc'][:8]}_{c['end_utc'][:8]}.zip")
    prices = pd.concat(
        [nyiso_prices(ny_zips, src["nyiso"]["zones"], src["nyiso"]["timezone"]), caiso_prices(ca_zip, c["hubs"])]
    )
    prices = keep_days(prices, src["price_days_utc"])
    _write_text(os.path.join(out_dir, "prices_hourly.csv"), prices_csv_text(prices))
    inputs += [*ny_zips, ca_zip]
    outputs["prices_hourly.csv"] = len(prices)
    details["prices"] = {"days_utc": src["price_days_utc"], "zones": sorted(prices["zone"].unique())}

    w = src["wonderproxy"]
    pings = os.path.join(raw_dir, "wonderproxy", w["pings_url"].rsplit("/", 1)[1])
    servers = os.path.join(raw_dir, "wonderproxy", w["servers_url"].rsplit("/", 1)[1])
    rtt = city_rtts(pings, servers, w["cities"])
    _write_text(os.path.join(out_dir, "rtt_ms.csv"), rtt_csv_text(rtt))
    inputs += [pings, servers]
    outputs["rtt_ms.csv"] = len(rtt)
    details["rtt"] = {"cities": w["cities"], "min_samples_per_pair": int(rtt["samples"].min())}

    manifest = {
        "written_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "script": "data_sources/preprocess_traces.py",
        "inputs": {os.path.relpath(p, PARIKSHIT_DIR): _sha256(p) for p in inputs},
        "outputs": {
            name: {"rows": rows, "sha256": _sha256(os.path.join(out_dir, name))} for name, rows in outputs.items()
        },
        "details": details,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=RAW_DIR, help="folder with the downloaded files")
    ap.add_argument("--out", default=OUT_DIR, help="folder for the processed files")
    args = ap.parse_args(argv)
    manifest = preprocess(args.raw, args.out)
    for name, info in manifest["outputs"].items():
        print(f"{name}: {info['rows']:,} rows, sha256 {info['sha256'][:12]}…")
    for name, d in manifest["details"].items():
        print(f"{name}: {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
