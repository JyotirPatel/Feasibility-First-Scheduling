# """Evaluate router v1 logs. Original synthetic calculator remains unchanged."""

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd


def evaluate(df, duration):
    if duration <= 0 or not np.isfinite(duration):
        raise ValueError("duration must be positive and finite")
    required = {
        "request_id",
        "decision",
        "outcome_status",
        "slo_met",
        "ttft_ms",
        "e2e_ms",
        "t_arrival",
        "t_complete",
        "cost_usd",
        "energy_kwh",
        "reject_reason",
        "constraint_violation",
    }
    if required - set(df):
        raise ValueError(f"Missing columns: {sorted(required - set(df))}")
    if df.request_id.isna().any() or df.request_id.duplicated().any():
        raise ValueError("Missing or duplicate request IDs")
    b = df.slo_met.astype(str).str.lower()
    if not b.isin(["true", "false"]).all():
        raise ValueError("slo_met must be true/false")
    ok = df.outcome_status.eq("ok")
    success = b.eq("true")
    if (success & ~ok).any():
        raise ValueError("SLO success on non-ok outcome")
    n = len(df)
    result = {
        "requests": n,
        "slo_successes": int(success.sum()),
        "goodput_rps": int(success.sum()) / duration,
        "goodput_convention": "arrival cohort in [0,duration), including drained completions; matches router summary",
        "duration_s": duration,
    }
    if not ((df.t_arrival >= 0) & (df.t_arrival < duration)).all():
        raise ValueError("Arrival outside measurement cohort")
    for status in ["ok", "failed", "rejected", "unfinished"]:
        result[status + "_requests"] = int(df.outcome_status.eq(status).sum())
    result["rejection_rate"] = float(df.decision.eq("reject").mean()) if n else None
    result["no_feasible_node_rejection_rate"] = (
        float(
            (df.decision.eq("reject") & df.reject_reason.eq("no_feasible_node")).mean()
        )
        if n
        else None
    )
    result["failure_rate"] = float(df.outcome_status.eq("failed").mean()) if n else None
    result["constraint_violations"] = int(df.constraint_violation.notna().sum())
    for col in ["ttft_ms", "e2e_ms"]:
        values = pd.to_numeric(df.loc[ok, col], errors="raise")
        if values.isna().any() or not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("Invalid successful latency")
        for p in [95, 99]:
            result[f"p{p}_{col}"] = (
                float(values.quantile(p / 100)) if len(values) else None
            )
    for col in ["cost_usd", "energy_kwh"]:
        values = pd.to_numeric(df[col], errors="raise")
        if (values.dropna() < 0).any() or not np.isfinite(values.dropna()).all():
            raise ValueError("Invalid resource value")
        total = float(values.sum()) if values.notna().all() else None
        result["total_" + col] = total
        result[col + "_per_slo_success"] = (
            total / int(success.sum()) if total is not None and success.sum() else None
        )
        result[col + "_coverage"] = float(values.notna().mean()) if n else None
    if "true_state_violation" in df:
        violations = df.true_state_violation.fillna("").astype(str).str.strip().ne("")
        result["true_state_violations"] = int(violations.sum())
        routed = int(df.decision.eq("route").sum())
        result["true_state_violation_rate"] = (
            int(violations.sum()) / routed if routed else None
        )
    else:
        result["true_state_violations"] = None
        result["true_state_violation_rate"] = None
    result["recovery_status"] = "requires event anchors; runner writes recovery.json"
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    p = Path(a.log)
    df = pd.read_csv(p) if p.suffix == ".csv" else pd.read_parquet(p)
    result = evaluate(df, a.duration)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
