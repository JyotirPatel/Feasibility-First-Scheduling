"""Paired positive goodput deficit relative to the documented true-state reference.

This is reference-relative lost goodput, not a proof of globally optimal service.
Never substitutes a static baseline for an oracle. Uses fixed 120-second windows.
"""

import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def finalize_reference(root):
    root = Path(root)
    statuses = list(root.glob("*/*/seed_*/status.json"))
    for status_path in statuses:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status["status"] != "ok":
            continue
        folder = status_path.parent
        reference = (
            root
            / "reference-true_state"
            / status["scenario"]
            / f"seed_{status['seed']}"
        )
        if not (reference / "status.json").exists():
            continue
        if (
            json.loads((reference / "status.json").read_text(encoding="utf-8"))[
                "status"
            ]
            != "ok"
        ):
            continue
        met = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
        ref_met = json.loads((reference / "metrics.json").read_text(encoding="utf-8"))
        if met["workload_sha256"] != ref_met["workload_sha256"]:
            raise ValueError(f"Unmatched reference workload: {folder}")
        curve = pd.read_csv(folder / "goodput_curve.csv")
        ref_curve = pd.read_csv(reference / "goodput_curve.csv")
        if not np.array_equal(curve.time_s, ref_curve.time_s):
            raise ValueError("Reference time bins differ")
        ref_recoveries = {
            r["anchor"]: r
            for r in json.loads(
                (reference / "recovery.json").read_text(encoding="utf-8")
            )
        }
        records = json.loads((folder / "recovery.json").read_text(encoding="utf-8"))
        for r in records:
            a = int(r["t0_s"])
            b = a + 120
            delta = (
                ref_curve.smoothed_goodput_rps.to_numpy()[a:b]
                - curve.smoothed_goodput_rps.to_numpy()[a:b]
            )
            r["lost_goodput_requests"] = float(np.maximum(delta, 0).sum())
            r["lost_goodput_status"] = (
                "paired myopic true-state reference; positive gap over fixed 120 s"
            )
            r["reference_steady_goodput_rps"] = ref_recoveries[r["anchor"]][
                "steady_goodput_rps"
            ]
            r["reference_policy"] = "reference:true_state"
        write_json(folder / "recovery.json", records)
        status["bundle_sha256"]["recovery.json"] = hashlib.sha256(
            (folder / "recovery.json").read_bytes()
        ).hexdigest()
        write_json(status_path, status)
