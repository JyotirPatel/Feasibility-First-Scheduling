"""
Download the real public data — owner: Parikshit

Fetches every file listed in sources.yaml into ../data/raw/<source>/ (not in git) and
writes ../data/raw/MANIFEST.json with each file's URL, size and SHA-256. Files whose
SHA-256 is known (the Azure traces and the WonderProxy pings) are checked, and a
mismatch stops the script. Files already present are kept unless --force is given.

Usage (from the Parikshit/ folder):
    python3 data_sources/download_data.py                  # everything
    python3 data_sources/download_data.py --only azure     # azure | nyiso | caiso | wonderproxy
    python3 data_sources/download_data.py --force          # download again

Then run data_sources/preprocess_traces.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import ssl
import sys
import time
import urllib.request
from datetime import UTC, datetime

import yaml

try:  # python.org builds on macOS ship without a CA store; certifi's bundle keeps HTTPS verified
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

_HERE = os.path.dirname(os.path.abspath(__file__))
PARIKSHIT_DIR = os.path.dirname(_HERE)
SOURCES_PATH = os.path.join(_HERE, "sources.yaml")
RAW_DIR = os.path.join(PARIKSHIT_DIR, "data", "raw")
SOURCES = ("azure", "nyiso", "caiso", "wonderproxy")
CAISO_WAIT_S = 5.0  # OASIS allows about one request every 5 seconds
USER_AGENT = "AMS560-Group20-simulator (course project; contact via the team repository)"


def load_sources(path: str = SOURCES_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: str, expected_sha256: str | None = None, force: bool = False) -> dict:
    """Download url to dest (atomically) unless it is already there; check the SHA-256 if known."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if force or not os.path.exists(dest):
        tmp = dest + ".part"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120, context=_SSL_CONTEXT) as response, open(tmp, "wb") as out:
            shutil.copyfileobj(response, out)
        os.replace(tmp, dest)
    digest = sha256_of(dest)
    if expected_sha256 and digest != expected_sha256:
        raise SystemExit(f"{dest}: SHA-256 {digest} does not match the expected {expected_sha256}")
    return {"url": url, "path": os.path.relpath(dest, PARIKSHIT_DIR), "bytes": os.path.getsize(dest), "sha256": digest}


def planned_downloads(src: dict, only: set[str]) -> list[tuple[str, str, str | None, bool]]:
    """(url, destination, expected sha256, is_caiso) for every file of the chosen sources."""
    plan = []
    if "azure" in only:
        for name, f in src["azure_llm_traces"]["files"].items():
            dest = os.path.join(RAW_DIR, "azure", f"AzureLLMInferenceTrace_{name}.csv")
            plan.append((f["url"], dest, f["sha256"], False))
    if "wonderproxy" in only:
        w = src["wonderproxy"]
        for key in ("pings", "servers"):
            url = w[f"{key}_url"]
            plan.append((url, os.path.join(RAW_DIR, "wonderproxy", url.rsplit("/", 1)[1]), w[f"{key}_sha256"], False))
    if "nyiso" in only:
        for month in src["nyiso"]["months"]:
            url = src["nyiso"]["url"].format(month=month)
            plan.append((url, os.path.join(RAW_DIR, "nyiso", url.rsplit("/", 1)[1]), None, False))
    if "caiso" in only:
        c = src["caiso"]
        url = c["url"].format(start=c["start_utc"], end=c["end_utc"], nodes=",".join(c["hubs"].values()))
        name = f"caiso_dam_hubs_{c['start_utc'][:8]}_{c['end_utc'][:8]}.zip"
        plan.append((url, os.path.join(RAW_DIR, "caiso", name), None, True))
    return plan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", choices=SOURCES, help="download only this source (repeatable)")
    ap.add_argument("--force", action="store_true", help="download again even if the file exists")
    args = ap.parse_args(argv)
    src = load_sources()
    only = set(args.only or SOURCES)

    manifest_path = os.path.join(RAW_DIR, "MANIFEST.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f).get("files", {})
    for url, dest, sha, is_caiso in planned_downloads(src, only):
        if is_caiso and (args.force or not os.path.exists(dest)):
            time.sleep(CAISO_WAIT_S)
        entry = fetch(url, dest, sha, args.force)
        manifest[entry["path"]] = entry
        print(f"{entry['path']}: {entry['bytes']:,} bytes, sha256 {entry['sha256'][:12]}…")
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump({"written_utc": datetime.now(UTC).isoformat(timespec="seconds"), "files": manifest}, f, indent=2)
    print(f"manifest: {os.path.relpath(manifest_path, PARIKSHIT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
