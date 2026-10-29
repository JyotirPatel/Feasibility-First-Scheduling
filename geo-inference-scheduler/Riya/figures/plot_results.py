"""Regenerate figures from successful persisted evaluation bundles only."""

import argparse
import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot(out):
    out = Path(out)
    dest = out / "figures"
    dest.mkdir(exist_ok=True)
    curves = {}
    for s in out.glob("*/*/seed_*/status.json"):
        meta = json.loads(s.read_text(encoding="utf-8"))
        if meta["status"] != "ok":
            continue
        curves.setdefault(meta["scenario"], {}).setdefault(meta["policy"], []).append(
            s.parent
        )
    for scenario, policies in sorted(curves.items()):
        fig, ax = plt.subplots(figsize=(11, 5))
        for policy, folders in sorted(policies.items()):
            data = [pd.read_csv(f / "goodput_curve.csv") for f in folders]
            times = data[0].time_s
            if any(not np.array_equal(d.time_s, times) for d in data):
                raise ValueError("Curve bins differ")
            mean = np.mean([d.smoothed_goodput_rps for d in data], axis=0)
            (line,) = ax.plot(times, mean, label=f"{policy} (n={len(data)})", lw=1.4)
            by_anchor = {}
            for f in folders:
                for r in json.loads((f / "recovery.json").read_text(encoding="utf-8")):
                    by_anchor.setdefault(r["anchor"], []).append(r)
            for anchor, rs in by_anchor.items():
                ax.axvline(rs[0]["t0_s"], color="grey", lw=0.7, ls="--")
                delays = [
                    r["adaptation_time_s"]
                    for r in rs
                    if r["adaptation_time_s"] is not None
                ]
                if delays:
                    x = rs[0]["t0_s"] + np.mean(delays)
                    ax.scatter(
                        [x],
                        [np.interp(x, times, mean)],
                        color=line.get_color(),
                        marker="o",
                        s=28,
                    )
        ax.set(
            title=scenario + " — arrival-time goodput",
            xlabel="Simulation time (s)",
            ylabel="SLO goodput (requests/s)",
        )
        ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1))
        fig.text(
            0.08,
            0.015,
            "Dots: mean seed recovery time, conditional on recovery; S1 dots are control diagnostics.",
            fontsize=8,
        )
        fig.tight_layout(rect=(0, 0.035, 1, 1))
        fig.savefig(dest / (scenario + "_goodput.png"), dpi=160)
        plt.close(fig)
    cis = pd.read_csv(out / "confidence_intervals.csv")
    for (scenario, metric), g in cis.loc[
        cis.ci_status.eq("available")
        & cis.metric.isin(
            [
                "goodput_rps",
                "p95_ttft_ms",
                "p99_ttft_ms",
                "p95_e2e_ms",
                "p99_e2e_ms",
                "rejection_rate",
                "cost_usd_per_slo_success",
                "energy_kwh_per_slo_success",
                "true_state_violation_rate",
            ]
        )
    ].groupby(["scenario", "metric"]):
        fig, ax = plt.subplots(figsize=(10, 5))
        y = g["mean"].to_numpy()
        lo = g.ci_low.to_numpy()
        hi = g.ci_high.to_numpy()
        # A percentile CI need not contain the observed mean; draw its absolute interval.
        x = np.arange(len(g))
        ax.bar(x, y, color="#306f9e")
        ax.vlines(x, lo, hi, color="black", lw=1.2)
        ax.hlines(lo, x - 0.09, x + 0.09, color="black")
        ax.hlines(hi, x - 0.09, x + 0.09, color="black")
        ax.set_xticks(x, g.policy, rotation=25, ha="right")
        ax.set(title=f"{scenario} — {metric} (95% seed bootstrap CI)", ylabel=metric)
        fig.tight_layout()
        fig.savefig(dest / (scenario + "_" + metric + ".png"), dpi=160)
        plt.close(fig)
    print(f"Figures saved to {dest}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    plot(ap.parse_args().results)
