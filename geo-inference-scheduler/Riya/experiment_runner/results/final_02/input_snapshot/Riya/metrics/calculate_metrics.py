import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def read_boolean_column(column):
    values = column.astype(str).str.strip().str.lower()
    allowed = {"true", "false"}

    if not values.isin(allowed).all():
        raise ValueError(
            f"{column.name} must contain only true or false."
        )

    return values == "true"


def calculate_metrics(log_path, metadata_path):
    df = pd.read_csv(log_path)

    with open(metadata_path, encoding="utf-8") as file:
        metadata = json.load(file)

    required = {
        "request_id",
        "completion_time_s",
        "rejected",
        "latency_ms",
        "slo_met",
        "cost_usd",
        "energy_j",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    if df["request_id"].isna().any():
        raise ValueError("Request IDs cannot be missing.")

    if df["request_id"].duplicated().any():
        raise ValueError("Request IDs must be unique.")

    start = float(metadata["run_start_s"])
    end = float(metadata["run_end_s"])
    duration = end - start

    if not np.isfinite([start, end]).all() or duration <= 0:
        raise ValueError("Run times must be finite and end after start.")

    rejected = read_boolean_column(df["rejected"])
    slo_met = read_boolean_column(df["slo_met"])

    numeric_columns = [
        "completion_time_s",
        "latency_ms",
        "cost_usd",
        "energy_j",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="raise")

        present = df[column].dropna()

        if not np.isfinite(present.to_numpy()).all():
            raise ValueError(f"{column} contains infinite values.")

    for column in ["latency_ms", "cost_usd", "energy_j"]:
        if (df[column].dropna() < 0).any():
            raise ValueError(f"{column} cannot be negative.")

    completed = (~rejected) & df["completion_time_s"].notna()
    unfinished = (~rejected) & df["completion_time_s"].isna()

    if (rejected & df["completion_time_s"].notna()).any():
        raise ValueError("Rejected requests cannot have completion times.")

    if (slo_met & ~completed).any():
        raise ValueError("Only completed requests can meet the SLO.")

    completion_times = df.loc[completed, "completion_time_s"]

    if ((completion_times < start) | (completion_times >= end)).any():
        raise ValueError(
            "Completion times must be inside [run_start_s, run_end_s)."
        )

    latencies = df.loc[completed, "latency_ms"]

    if latencies.isna().any():
        raise ValueError("Completed requests need latency values.")

    total = len(df)
    successes = int((completed & slo_met).sum())

    # If any request lacks cost/energy data, that metric is unavailable.
    cost_available = df["cost_usd"].notna().all()
    energy_available = df["energy_j"].notna().all()

    total_cost = (
        float(df["cost_usd"].sum()) if cost_available else None
    )
    total_energy = (
        float(df["energy_j"].sum()) if energy_available else None
    )

    return {
        "data_type": metadata.get("data_type", "unspecified"),
        "policy": metadata.get("policy"),
        "scenario": metadata.get("scenario"),
        "seed": metadata.get("seed"),
        "duration_s": duration,
        "total_requests": total,
        "completed_requests": int(completed.sum()),
        "unfinished_requests": int(unfinished.sum()),
        "rejected_requests": int(rejected.sum()),
        "slo_successes": successes,
        "goodput_rps": successes / duration,
        "rejection_rate": (
            int(rejected.sum()) / total if total else None
        ),
        "p95_latency_ms": (
            float(latencies.quantile(0.95))
            if len(latencies) else None
        ),
        "p99_latency_ms": (
            float(latencies.quantile(0.99))
            if len(latencies) else None
        ),
        "total_cost_usd": total_cost,
        "total_energy_j": total_energy,
        "cost_per_slo_success_usd": (
            total_cost / successes
            if successes and total_cost is not None else None
        ),
        "energy_per_slo_success_j": (
            total_energy / successes
            if successes and total_energy is not None else None
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    results = calculate_metrics(args.log, args.metadata)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(results, indent=2, allow_nan=False)
    output.write_text(text + "\n", encoding="utf-8")

    print(text)


if __name__ == "__main__":
    main()