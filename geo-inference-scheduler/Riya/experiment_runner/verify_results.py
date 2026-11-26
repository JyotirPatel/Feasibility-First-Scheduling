"""Validate coverage, source snapshots, bundle hashes and optional raw metric replay."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd


def verify(root, deep=False):
    root = Path(root)
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    expected = {
        (p, s, k)
        for p in cfg["policies"]
        for s in cfg["scenarios"]
        for k in cfg["seeds"]
    }
    actual = set()
    failures = []
    for status_path in sorted(root.glob("*/*/seed_*/status.json")):
        f = status_path.parent
        s = json.loads(status_path.read_text(encoding="utf-8"))
        key = (s["policy"], s["scenario"], s["seed"])
        if key in actual:
            failures.append(f"Duplicate: {key}")
        actual.add(key)
        if s["status"] != "ok":
            failures.append(f"Failed: {key}")
            continue
        if not s.get("bundle_sha256"):
            failures.append(f"No hashes: {key}")
        for name, h in s.get("bundle_sha256", {}).items():
            p = f / name
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
                failures.append(f"Hash mismatch: {p}")
        if deep:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "metrics"))
            from evaluate_log import evaluate

            p = f / "decision_log.parquet"
            log = (
                pd.read_parquet(p)
                if p.exists()
                else pd.read_csv(f / "decision_log.csv", low_memory=False)
            )
            saved = json.loads((f / "metrics.json").read_text(encoding="utf-8"))
            got = evaluate(log, saved["duration_s"])
            for metric, value in got.items():
                if metric in ["recovery_status", "goodput_convention"]:
                    continue
                expected_value = saved.get(metric)
                if isinstance(value, (int, float)) and isinstance(
                    expected_value, (int, float)
                ):
                    if abs(value - expected_value) > 1e-9 * max(1, abs(value)):
                        failures.append(f"Metric mismatch: {key} {metric}")
                elif value != expected_value:
                    failures.append(f"Metric mismatch: {key} {metric}")
    if actual != expected:
        failures.append(
            f"Grid mismatch: missing={len(expected - actual)}, extra={len(actual - expected)}"
        )
    source = json.loads((root / "source.json").read_text(encoding="utf-8"))
    for n, h in source["source_sha256"].items():
        p = root / "input_snapshot" / n.replace("\\", "/")
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            failures.append(f"Source snapshot mismatch: {n}")
    summary = pd.read_csv(root / "summary.csv")
    if (
        len(summary) != len(expected)
        or summary.duplicated(["policy", "scenario", "seed"]).any()
    ):
        failures.append("Summary grid invalid")
    checks = pd.read_csv(root / "pairing_checks.csv")
    if (
        len(checks) != len(cfg["scenarios"]) * len(cfg["seeds"])
        or not checks.workloads_match.astype(str).str.lower().eq("true").all()
        or not checks.n_policies.eq(len(cfg["policies"])).all()
    ):
        failures.append("Pairing invalid")
    report = {
        "expected_runs": len(expected),
        "found_runs": len(actual),
        "deep_replay": deep,
        "passed": not failures,
        "problems": failures,
    }
    (root / "verification.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--deep", action="store_true")
    a = ap.parse_args()
    verify(a.results, a.deep)
