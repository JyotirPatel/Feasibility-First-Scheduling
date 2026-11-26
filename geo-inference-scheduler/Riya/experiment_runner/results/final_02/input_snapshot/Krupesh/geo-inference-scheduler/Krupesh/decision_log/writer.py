"""Decision log writer — owner: Krupesh. One row per request (brief §10.3).

The first 17 columns are the frozen v1 contract, in order. Columns after them are
backward-compatible extensions (readers that only know v1 can ignore them).
feasible_nodes / filtered_out are stored as JSON strings so CSV and Parquet agree.

The log is the authoritative source for every reported metric: evaluation code reads
only these files, never in-memory simulator state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

V1_COLUMNS = [
    "run_id",
    "seed",
    "scenario",
    "policy",
    "request_id",
    "t_arrival",
    "decision",
    "node_id",
    "feasible_nodes",
    "filtered_out",
    "reject_reason",
    "ttft_ms",
    "e2e_ms",
    "slo_met",
    "energy_kwh",
    "cost_usd",
    "reward",
]

EXTENSION_COLUMNS = [
    "outcome_status",  # ok | failed | rejected | unfinished
    "t_complete",
    "user_region",
    "model",
    "slo_class",
    "ttft_slo_ms",
    "input_tokens",
    "expected_output_tokens",
    "chosen_node_status",  # status of the chosen node in the router's telemetry
    "telemetry_age_s",  # how old the router's telemetry was at decision time
    "constraint_violation",  # rule the chosen node broke per router telemetry (must be null)
    "true_state_violation",  # rule the chosen node broke per TRUE simulator state
    "router_wall_ms",  # real (wall-clock) time spent in routing, NOT simulated time
]

COLUMNS = V1_COLUMNS + EXTENSION_COLUMNS
OUTCOME_STATUSES = ("ok", "failed", "rejected", "unfinished")


def empty_row() -> dict[str, Any]:
    return dict.fromkeys(COLUMNS)


class DecisionLogWriter:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.rows: list[dict[str, Any]] = []

    def write(self, row: dict[str, Any]) -> None:
        unknown = set(row) - set(COLUMNS)
        if unknown:
            raise ValueError(f"unknown decision-log columns: {sorted(unknown)}")
        full = empty_row()
        full.update(row)
        for k in ("feasible_nodes", "filtered_out"):
            if not isinstance(full[k], str) and full[k] is not None:
                full[k] = json.dumps(full[k], sort_keys=True)
        self.rows.append(full)

    def to_frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.rows, columns=COLUMNS)
        return df.sort_values(["t_arrival", "request_id"], kind="stable").reset_index(drop=True)

    def close(self) -> pd.DataFrame:
        df = self.to_frame()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.suffix == ".csv":
                df.to_csv(self.path, index=False)
            else:
                df.to_parquet(self.path, index=False)
        return df


def read_log(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    return pd.read_csv(p) if p.suffix == ".csv" else pd.read_parquet(p)


def validate_log(df: pd.DataFrame) -> list[str]:
    """Schema + consistency checks. Returns problems (empty = valid)."""
    errs: list[str] = []
    if list(df.columns[: len(V1_COLUMNS)]) != V1_COLUMNS:
        errs.append("first columns must be the v1 contract, in order")
    if df["request_id"].duplicated().any():
        errs.append("duplicate request_id")
    if not df["decision"].isin(["route", "reject"]).all():
        errs.append("decision must be route|reject")
    rej = df["decision"] == "reject"
    if df.loc[rej, "node_id"].notna().any():
        errs.append("rejected rows must have node_id null")
    if df.loc[rej, "reject_reason"].isna().any():
        errs.append("rejected rows need reject_reason")
    if df.loc[~rej, "node_id"].isna().any():
        errs.append("routed rows need node_id")
    if not df["outcome_status"].isin(OUTCOME_STATUSES).all():
        errs.append("bad outcome_status")
    ok = df["outcome_status"] == "ok"
    if df.loc[ok, ["ttft_ms", "e2e_ms", "reward"]].isna().any().any():
        errs.append("completed rows need ttft_ms, e2e_ms and reward")
    if (df.loc[ok, "e2e_ms"] + 1e-9 < df.loc[ok, "ttft_ms"]).any():
        errs.append("e2e_ms < ttft_ms")
    # every routed node must have been in that row's feasible set (filter on)
    for nid, feas in zip(df.loc[~rej, "node_id"], df.loc[~rej, "feasible_nodes"], strict=True):
        if feas is not None and nid not in json.loads(feas):
            errs.append(f"node {nid} chosen but not in feasible_nodes")
            break
    return errs
