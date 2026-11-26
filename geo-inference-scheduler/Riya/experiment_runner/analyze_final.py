"""Seed-paired final comparison tables, generated only from saved result bundles."""

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from summarize_results import interval

PRIMARY = "sur:sw_linucb"


def analyze(root):
    root = Path(root)
    out = root / "analysis"
    out.mkdir(exist_ok=True)
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    summary = pd.read_csv(root / "summary.csv")
    main = summary.loc[summary.policy.isin(cfg.get("main_policies", cfg["policies"]))]
    main.to_csv(out / "main_runs.csv", index=False)
    n_expected = (
        len(cfg.get("main_policies", cfg["policies"]))
        * len(cfg["scenarios"])
        * len(cfg["seeds"])
    )
    (out / "main_run_coverage.json").write_text(
        json.dumps(
            {
                "expected_runs": n_expected,
                "ok_runs": int(main.status.eq("ok").sum()),
                "complete": len(main) == n_expected and main.status.eq("ok").all(),
            },
            indent=2,
            default=bool,
        ),
        encoding="utf-8",
    )
    rng = np.random.default_rng(20261125)
    effects = []
    metrics = [
        "goodput_rps",
        "p95_ttft_ms",
        "p99_ttft_ms",
        "p95_e2e_ms",
        "p99_e2e_ms",
        "rejection_rate",
        "failure_rate",
        "cost_usd_per_slo_success",
        "energy_kwh_per_slo_success",
        "true_state_violation_rate",
    ]
    for scenario, g in summary.loc[summary.status.eq("ok")].groupby("scenario"):
        target = g.loc[g.policy.eq(PRIMARY)]
        for policy, h in g.loc[~g.policy.eq(PRIMARY)].groupby("policy"):
            paired = target.merge(
                h,
                on=["scenario", "seed"],
                suffixes=("_target", "_other"),
                validate="one_to_one",
            )
            if not paired.workload_sha256_target.eq(paired.workload_sha256_other).all():
                raise ValueError("Unpaired workloads")
            for metric in metrics:
                if metric not in g:
                    continue
                delta = pd.to_numeric(
                    paired[metric + "_target"], errors="coerce"
                ) - pd.to_numeric(paired[metric + "_other"], errors="coerce")
                effects.append(
                    {
                        "scenario": scenario,
                        "target": PRIMARY,
                        "comparator": policy,
                        "metric": metric,
                        "direction": "target minus comparator",
                        **interval(delta, rng),
                    }
                )
    pd.DataFrame(effects).to_csv(out / "paired_effects.csv", index=False)
    cis = pd.read_csv(root / "confidence_intervals.csv")
    key = cis.loc[cis.metric.isin(metrics) & cis.ci_status.eq("available")].copy()
    key.to_csv(out / "key_metrics_with_ci.csv", index=False)
    rec = pd.read_csv(root / "recovery_summary.csv")
    rates = []
    for (policy, scenario, anchor), g in rec.groupby(["policy", "scenario", "anchor"]):
        rates.append(
            {
                "policy": policy,
                "scenario": scenario,
                "anchor": anchor,
                "recovered": int(g.adaptation_time_s.notna().sum()),
                "seeds": len(g),
                "zero_steady_seeds": int(g.zero_steady_goodput.sum()),
            }
        )
    pd.DataFrame(rates).to_csv(out / "recovery_counts.csv", index=False)
    print(f"Analysis written to {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    analyze(ap.parse_args().results)
