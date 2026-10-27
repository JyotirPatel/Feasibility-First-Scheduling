"""The data pipeline (data_sources/): parsing on tiny hand-made inputs, and the committed processed files."""

import gzip
import hashlib
import importlib.util
import io
import json
import os
import zipfile

import pandas as pd
import pytest

from simulator.config import PARIKSHIT_DIR, PROCESSED_DIR


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PARIKSHIT_DIR, "data_sources", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pre = _load("preprocess_traces")
dl = _load("download_data")
RAW_DIR = os.path.join(PARIKSHIT_DIR, "data", "raw")


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_azure_trace_offsets_and_context_limit(tmp_path):
    raw = tmp_path / "trace.csv"
    raw.write_text(
        "TIMESTAMP,ContextTokens,GeneratedTokens\n"
        "2023-11-16 18:15:46.0000000,100,10\n"
        "2023-11-16 18:15:46.5000000,8000,500\n"  # 8,500 tokens: over the 8,192 context window
        "2023-11-16 18:15:48.2500000,300,30\n"
    )
    df, stats = pre.azure_trace(str(raw), 8192)
    assert df["t_s"].tolist() == [0.0, 2.25] and df["input_tokens"].tolist() == [100, 300]
    assert stats["dropped_over_context"] == 1 and stats["rows_out"] == 2
    assert pre.azure_csv_text(df).splitlines()[1] == "0.000000,100,10"


def test_unordered_or_empty_requests_are_refused(tmp_path):
    raw = tmp_path / "bad.csv"
    raw.write_text("TIMESTAMP,ContextTokens,GeneratedTokens\n2023-11-16 18:00:01,5,5\n2023-11-16 18:00:00,5,5\n")
    with pytest.raises(ValueError, match="not in order"):
        pre.azure_trace(str(raw), 8192)
    raw.write_text("TIMESTAMP,ContextTokens,GeneratedTokens\n2023-11-16 18:00:00,0,5\n2023-11-16 18:00:01,5,5\n")
    with pytest.raises(ValueError, match="no input or output"):
        pre.azure_trace(str(raw), 8192)


def _zip(path, name, text):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, text)


def test_nyiso_local_time_becomes_utc_and_caiso_hubs_are_named(tmp_path):
    ny = tmp_path / "ny.zip"
    _zip(
        ny,
        "20240417damlbmp_zone.csv",
        "Time Stamp,Name,PTID,LBMP ($/MWHr),Marginal Cost Losses ($/MWHr),Marginal Cost Congestion ($/MWHr)\n"
        "04/17/2024 15:00,N.Y.C.,61761,26.81,1,0\n"
        "04/17/2024 15:00,WEST,61752,20.99,0,0\n"
        "04/17/2024 15:00,PJM,1,9,0,0\n",
    )
    p = pre.nyiso_prices([str(ny)], ["N.Y.C.", "WEST"], "America/New_York")
    assert sorted(p["zone"]) == ["NYISO:N.Y.C.", "NYISO:WEST"]
    assert set(p["t_utc"]) == {pd.Timestamp("2024-04-17 19:00", tz="UTC")}  # 15:00 EDT = 19:00 UTC
    ca = tmp_path / "ca.zip"
    _zip(
        ca,
        "x.csv",
        "INTERVALSTARTTIME_GMT,NODE,LMP_TYPE,MW\n2024-04-17T19:00:00-00:00,TH_SP15_GEN-APND,LMP,-31.2\n"
        "2024-04-17T19:00:00-00:00,TH_SP15_GEN-APND,MCC,0.0\n2024-04-17T19:00:00-00:00,OTHER,LMP,5\n",
    )
    c = pre.caiso_prices(str(ca), {"SP15": "TH_SP15_GEN-APND"})
    assert c["zone"].tolist() == ["CAISO:SP15"] and c["lbmp_usd_mwh"].tolist() == [-31.2]


def test_a_missing_price_hour_is_an_error():
    hours = pd.date_range("2024-04-17", periods=47, freq="h", tz="UTC")  # one hour short of two days
    p = pd.DataFrame({"t_utc": hours, "zone": "NYISO:WEST", "lbmp_usd_mwh": 20.0})
    with pytest.raises(ValueError, match="one value per hour"):
        pre.keep_days(p, ["2024-04-17", "2024-04-18"])


def test_rtt_is_the_median_over_both_directions(tmp_path):
    servers = tmp_path / "servers.csv"
    servers.write_text('"id","name"\n"1","A"\n"2","B"\n"3","C"\n')
    pings = tmp_path / "pings.csv.gz"
    rows = ["source,destination,timestamp,min,avg,max,mdev"]
    rows += ["1,2,t,0,10,0,0", "2,1,t,0,20,0,0", "1,2,t,0,90,0,0", "1,3,t,0,30,0,0", "2,3,t,0,40,0,0", "1,1,t,0,0,0,0"]
    with gzip.open(pings, "wt") as f:
        f.write("\n".join(rows) + "\n")
    out = pre.city_rtts(str(pings), str(servers), {"Alpha": 1, "Beta": 2, "Gamma": 3})
    got = {(a, b): (ms, n) for a, b, ms, n in out.itertuples(index=False)}
    assert got == {("Alpha", "Beta"): (20.0, 3), ("Alpha", "Gamma"): (30.0, 1), ("Beta", "Gamma"): (40.0, 1)}
    with pytest.raises(ValueError, match="not in"):
        pre.city_rtts(str(pings), str(servers), {"Alpha": 1, "Zeta": 9})


def test_gzip_output_is_byte_for_byte_reproducible(tmp_path):
    a, b = tmp_path / "a.csv.gz", tmp_path / "b.csv.gz"
    pre._write_text(str(a), "x,y\n1,2\n")
    pre._write_text(str(b), "x,y\n1,2\n")
    assert a.read_bytes() == b.read_bytes()
    assert gzip.decompress(a.read_bytes()) == b"x,y\n1,2\n"


def test_committed_processed_files_match_their_manifest():
    with open(os.path.join(PROCESSED_DIR, "manifest.json")) as f:
        manifest = json.load(f)
    for name, info in manifest["outputs"].items():
        path = os.path.join(PROCESSED_DIR, name)
        assert _sha256(path) == info["sha256"], name
        opener = gzip.open if name.endswith(".gz") else open
        with opener(path, "rt") as f:
            assert sum(1 for _ in f) - 1 == info["rows"], name


@pytest.mark.skipif(not os.path.isdir(os.path.join(RAW_DIR, "azure")), reason="raw data not downloaded")
def test_processing_the_raw_downloads_again_gives_the_committed_files(tmp_path):
    manifest = pre.preprocess(RAW_DIR, str(tmp_path))
    with open(os.path.join(PROCESSED_DIR, "manifest.json")) as f:
        committed = json.load(f)
    assert {k: v["sha256"] for k, v in manifest["outputs"].items()} == {
        k: v["sha256"] for k, v in committed["outputs"].items()
    }
    assert manifest["inputs"] == committed["inputs"]


def test_download_plan_and_checked_fetch(tmp_path):
    src = dl.load_sources()
    plan = dl.planned_downloads(src, {"azure", "nyiso", "caiso", "wonderproxy"})
    names = [os.path.basename(dest) for _, dest, _, _ in plan]
    assert "AzureLLMInferenceTrace_conv.csv" in names and "20240401damlbmp_zone_csv.zip" in names
    assert sum(is_caiso for *_, is_caiso in plan) == 1
    assert all(url.startswith(("https://", "http://oasis.caiso.com")) for url, *_ in plan)

    source = tmp_path / "source.txt"
    source.write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    entry = dl.fetch(source.as_uri(), str(tmp_path / "out" / "copy.txt"), digest)
    assert entry["sha256"] == digest and (tmp_path / "out" / "copy.txt").read_bytes() == b"hello"
    with pytest.raises(SystemExit, match="does not match"):
        dl.fetch(source.as_uri(), str(tmp_path / "out" / "copy2.txt"), "0" * 64)


def test_the_processed_files_have_the_expected_shape():
    prices = pd.read_csv(os.path.join(PROCESSED_DIR, "prices_hourly.csv"))
    assert prices.groupby("zone").size().eq(48).all() and prices["zone"].nunique() == 7
    rtt = pd.read_csv(os.path.join(PROCESSED_DIR, "rtt_ms.csv"))
    assert len(rtt) == 14 * 13 // 2 and (rtt["samples"] >= 48).all() and (rtt["rtt_ms"] > 0).all()
    with gzip.open(os.path.join(PROCESSED_DIR, "azure_conv.csv.gz"), "rt") as f:
        conv = pd.read_csv(io.StringIO(f.read()))
    assert (conv["input_tokens"] + conv["output_tokens"] <= 8192).all() and conv["t_s"].is_monotonic_increasing
