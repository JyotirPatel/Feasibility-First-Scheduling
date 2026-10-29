"""Rebuild tables and seed-level bootstrap intervals from saved bundles only."""

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd


def interval(values, rng):
    v = (
        pd.to_numeric(pd.Series(values, dtype=object), errors="coerce")
        .dropna()
        .to_numpy(dtype=float)
    )
    if not len(v):
        return {
            "n": 0,
            "mean": None,
            "ci_low": None,
            "ci_high": None,
            "ci_status": "unavailable",
        }
    if len(v) < 10:
        return {
            "n": len(v),
            "mean": float(v.mean()),
            "ci_low": None,
            "ci_high": None,
            "ci_status": "insufficient_seeds",
        }
    boot = rng.choice(v, size=(2000, len(v)), replace=True).mean(axis=1)
    low, high = np.quantile(boot, [0.025, 0.975])
    return {
        "n": len(v),
        "mean": float(v.mean()),
        "ci_low": float(low),
        "ci_high": float(high),
        "ci_status": "available",
    }


def summarize(out):
    out = Path(out)
    rows = []
    recoveries = []
    shares = []
    for status_path in sorted(out.glob("*/*/seed_*/status.json")):
        folder = status_path.parent
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status["status"] != "ok":
            rows.append(status)
            continue
        metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
        rows.append({**metrics, "status": "ok"})
        for recovery in json.loads(
            (folder / "recovery.json").read_text(encoding="utf-8")
        ):
            nodes = recovery.pop("node_traffic_shares")
            row = {
                "policy": metrics["policy"],
                "scenario": metrics["scenario"],
                "seed": metrics["seed"],
                **recovery,
            }
            recoveries.append(row)
            for node, values in nodes.items():
                shares.append(
                    {
                        "policy": metrics["policy"],
                        "scenario": metrics["scenario"],
                        "seed": metrics["seed"],
                        "anchor": recovery["anchor"],
                        "node_id": node,
                        **values,
                    }
                )
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "summary.csv", index=False)
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    expected = len(config["policies"]) * len(config["scenarios"]) * len(config["seeds"])
    (out / "run_coverage.json").write_text(
        json.dumps(
            {
                "expected_runs": expected,
                "bundles_found": len(rows),
                "ok_runs": sum(r["status"] == "ok" for r in rows),
                "complete": len(rows) == expected
                and all(r["status"] == "ok" for r in rows),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    recovery = pd.DataFrame(recoveries)
    recovery.to_csv(out / "recovery_summary.csv", index=False)
    share_df = pd.DataFrame(shares)
    share_df.to_csv(out / "node_traffic_shares.csv", index=False)
    if not share_df.empty:
        recovery.merge(
            share_df, on=["policy", "scenario", "seed", "anchor"], how="left"
        ).to_csv(out / "recovery_with_node_shares.csv", index=False)
    if summary.empty:
        return
    valid = summary.loc[summary.status.eq("ok")]
    # Paired comparisons are only valid when policy-independent arrivals match exactly.
    pairing = []
    for (scenario, seed), g in valid.groupby(["scenario", "seed"]):
        pairing.append(
            {
                "scenario": scenario,
                "seed": seed,
                "n_policies": len(g),
                "workloads_match": g.workload_sha256.nunique() == 1,
            }
        )
    pd.DataFrame(pairing).to_csv(out / "pairing_checks.csv", index=False)
    if any(not p["workloads_match"] for p in pairing):
        raise ValueError(
            "Policy runs received different workloads; do not report comparisons"
        )
    rng = np.random.default_rng(20261027)
    cis = []
    excluded = {
        "seed",
        "nodes",
        "duration_s",
        "policy",
        "scenario",
        "status",
        "workload_sha256",
    }
    for (policy, scenario), g in valid.groupby(["policy", "scenario"]):
        for col in g.columns:
            if col in excluded or not pd.api.types.is_numeric_dtype(g[col]):
                continue
            cis.append(
                {
                    "policy": policy,
                    "scenario": scenario,
                    "metric": col,
                    **interval(g[col], rng),
                }
            )
    if not recovery.empty:
        for (policy, scenario, anchor), g in recovery.groupby(
            ["policy", "scenario", "anchor"]
        ):
            for col in [
                "adaptation_time_s",
                "steady_goodput_rps",
                "deepest_dip_rps",
                "lost_goodput_requests",
            ]:
                cis.append(
                    {
                        "policy": policy,
                        "scenario": scenario,
                        "anchor": anchor,
                        "metric": col,
                        "population": "recovered seeds only"
                        if col == "adaptation_time_s"
                        else "all seeds",
                        **interval(g[col], rng),
                    }
                )
            recovered = g.adaptation_time_s.notna()
            cis.append(
                {
                    "policy": policy,
                    "scenario": scenario,
                    "anchor": anchor,
                    "metric": "recovered_fraction",
                    **interval(recovered.astype(float), rng),
                }
            )
    if not share_df.empty:
        for (policy, scenario, anchor, node), g in share_df.groupby(
            ["policy", "scenario", "anchor", "node_id"]
        ):
            for col in [x for x in g if x.endswith("_arrival_share")]:
                cis.append(
                    {
                        "policy": policy,
                        "scenario": scenario,
                        "anchor": anchor,
                        "node_id": node,
                        "metric": col,
                        **interval(g[col], rng),
                    }
                )
    pd.DataFrame(cis).to_csv(out / "confidence_intervals.csv", index=False)
    controls = []
    if not recovery.empty:
        for policy, g in recovery.loc[recovery.is_control].groupby("policy"):
            positive = g.adaptation_time_s.gt(0)
            controls.append(
                {
                    "policy": policy,
                    "n_seeds": len(g),
                    "positive_pseudo_adaptation_seeds": int(positive.sum()),
                    "did_not_recover_seeds": int(g.adaptation_time_s.isna().sum()),
                    "positive_pseudo_delay_min_s": float(
                        g.loc[positive, "adaptation_time_s"].min()
                    )
                    if positive.any()
                    else None,
                    "positive_pseudo_delay_max_s": float(
                        g.loc[positive, "adaptation_time_s"].max()
                    )
                    if positive.any()
                    else None,
                    **{
                        "false_delay_fraction_" + k: v
                        for k, v in interval(positive.astype(float), rng).items()
                    },
                }
            )
    pd.DataFrame(controls).to_csv(out / "stable_noise_floor.csv", index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    args = ap.parse_args()
    summarize(args.results)
