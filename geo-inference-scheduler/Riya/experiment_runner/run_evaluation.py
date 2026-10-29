# """Execute teammate policies through the real router with Parikshit's replayable simulator."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
import numpy as np
import pandas as pd

RIYA = Path(__file__).resolve().parents[1]
ROOT = RIYA.parent
# Explicit paths handle the uploaded nested tree without modifying teammates.
for folder in [ROOT / "Sur", ROOT / "Jyotir", ROOT / "Parikshit", RIYA / "metrics"]:
    sys.path.insert(0, str(folder))
candidates = [ROOT / "Krupesh", ROOT / "Krupesh/geo-inference-scheduler/Krupesh"]
KR = next((p for p in candidates if (p / "router_service/engine.py").exists()), None)
if KR is None:
    raise RuntimeError("Cannot locate Krupesh router")
sys.path.append(str(KR))
from integration import jyotir_adapter

jyotir_adapter.JYOTIR_DIR = ROOT / "Jyotir"
from router_plugin import register, make_reward_fn
from router_service.registry import build_policy, build_filter
from router_service.engine import RoutingEngine, RunMeta
from simulator.cluster import Simulation
from simulator.config import load_cluster, load_scenario, load_workload
from simulator.events import change_times
from simulator.routers import KrupeshRouter
from recovery import recovery_metrics, goodput_curve
from summarize_results import summarize
from decision_log.writer import DecisionLogWriter, validate_log
from evaluate_log import evaluate


def dump(path, obj):
    path.write_text(
        json.dumps(obj, indent=2, allow_nan=False, default=str), encoding="utf-8"
    )


def source_info():
    files = sorted(
        p
        for owner in ["Riya", "Krupesh", "Jyotir", "Sur", "Parikshit"]
        for p in (ROOT / owner).rglob("*")
        if p.suffix in [".py", ".yaml", ".json", ".csv"]
        and not any(x in p.parts for x in ["results", "plans", "__pycache__", ".git"])
    )
    manifest = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    }
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {"git_commit": commit, "source_sha256": manifest}


def run_one(policy, scenario, seed, cfg, folder):
    register()
    model = build_policy(policy, seed=seed)
    reward_cfg = model.config.reward if hasattr(model, "config") else None
    engine = RoutingEngine(
        policy=model,
        filter_fn=build_filter("jyotir"),
        reward_fn=make_reward_fn(reward_cfg),
        meta=RunMeta(f"{scenario}__{policy}__s{seed}", seed, scenario, policy),
        writer=DecisionLogWriter(folder / "decision_log.csv"),
        audit_fn=build_filter("jyotir"),
    )
    trace = load_scenario(scenario)
    duration = trace.duration_s
    workload = load_workload()
    if cfg.get("rate_rps") is not None:
        workload = workload.model_copy(update={"rate_rps": cfg["rate_rps"]})
    cluster_config = load_cluster(cfg["nodes"])
    dump(
        folder / "resolved_inputs.json",
        {
            "scenario": trace.model_dump(),
            "cluster": cluster_config.model_dump(),
            "workload": workload.model_dump(),
            "policy_config": model.config.model_dump()
            if hasattr(getattr(model, "config", None), "model_dump")
            else None,
        },
    )
    adapter = KrupeshRouter(engine)
    cluster = Simulation(
        adapter, trace, seed, cluster=cluster_config, workload=workload
    )
    simulation_stats = cluster.run()
    dump(folder / "simulation_stats.json", simulation_stats)
    engine.finish()
    df = engine.writer.close()
    # Metrics always read the persisted authoritative log.
    df = pd.read_csv(folder / "decision_log.csv", low_memory=False)
    problems = validate_log(df)
    if problems:
        raise ValueError(str(problems))
    if "true_state_violation" not in df:
        raise ValueError("Simulator independent safety annotations are missing")
    result = evaluate(df, duration)
    result.update(policy=policy, scenario=scenario, seed=seed)
    if hasattr(model, "stats"):
        dump(folder / "policy_stats.json", dict(model.stats))
        if model.stats.get("reward_mismatch", 0):
            raise ValueError("Router and policy rewards disagree")
    result.update(
        simulator="Parikshit/simulator (SimPy)",
        nodes=cfg["nodes"],
        goodput_convention="arrival-time bins; drained outcomes attributed to arrival",
    )
    # Workload fingerprint must match across policies for the same trace and seed.
    workload_cols = [
        "request_id",
        "t_arrival",
        "user_region",
        "model",
        "slo_class",
        "ttft_slo_ms",
        "input_tokens",
        "expected_output_tokens",
    ]
    fingerprint = (
        df[workload_cols].sort_values("request_id").to_csv(index=False).encode("utf-8")
    )
    result["workload_sha256"] = hashlib.sha256(fingerprint).hexdigest()
    curve = goodput_curve(df, duration)
    curve.to_csv(folder / "goodput_curve.csv", index=False)
    anchors = change_times(trace)
    event_rows = []
    affected_nodes = sorted(
        {e.node for e in trace.events if getattr(e, "node", None) is not None}
    )
    for anchor, t0 in anchors.items():
        event_rows.append(
            recovery_metrics(
                df, curve, t0, anchor, affected_nodes, control=scenario == "s1_stable"
            )
        )
    dump(
        folder / "events.json",
        {
            "anchors": anchors,
            "events": [e.model_dump() for e in trace.events],
            "actual_events": cluster.event_log,
        },
    )
    dump(folder / "recovery.json", event_rows)
    result["recovery_status"] = "see recovery.json (S1 is a control diagnostic)"
    dump(folder / "metrics.json", result)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--config", default=str(Path(__file__).with_name("config_simulator.json"))
    )
    ap.add_argument("--output", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    if a.limit is not None and a.limit < 1:
        raise ValueError("--limit must be positive")
    if cfg.get("simulator") != "parikshit":
        raise ValueError(
            "Use config_simulator.json for actual simulator evaluation; mock results are historical only"
        )
    if cfg.get("goodput_time_basis") != "arrival":
        raise ValueError("This evaluation uses arrival-time bins, matching Sur's sweep")
    if cfg.get("nodes") not in [5, 10]:
        raise ValueError("nodes must be 5 or 10")
    if cfg.get("rate_rps") is not None and (
        not np.isfinite(cfg["rate_rps"]) or cfg["rate_rps"] <= 0
    ):
        raise ValueError("rate_rps must be positive and finite")
    if len(cfg["policies"]) != len(set(cfg["policies"])) or len(
        cfg["scenarios"]
    ) != len(set(cfg["scenarios"])):
        raise ValueError("Duplicate policy or scenario")
    if len(cfg["seeds"]) != len(set(cfg["seeds"])):
        raise ValueError("Duplicate seeds")
    if not cfg["policies"] or not cfg["scenarios"] or not cfg["seeds"]:
        raise ValueError("Experiment grid is empty")
    for scenario in cfg["scenarios"]:
        load_scenario(scenario)
    out = Path(a.output).resolve()
    if out.exists() and not a.resume:
        raise FileExistsError("Choose a new output folder or --resume")
    out.mkdir(parents=True, exist_ok=True)
    provenance = source_info()
    if (out / "config.json").exists():
        if (
            json.loads((out / "config.json").read_text()) != cfg
            or json.loads((out / "source.json").read_text()) != provenance
        ):
            raise ValueError("Config/source changed; use a new output folder")
    dump(out / "config.json", cfg)
    dump(out / "source.json", provenance)
    # Keep actual configuration/data bytes, not only hashes, in each root bundle.
    for relative in provenance["source_sha256"]:
        original = ROOT / relative
        if original.suffix in [".yaml", ".yml", ".json", ".csv"]:
            target = out / "input_snapshot" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
    rows = []
    total = 0
    for policy in cfg["policies"]:
        for scenario in cfg["scenarios"]:
            for seed in cfg["seeds"]:
                if a.limit is not None and total >= a.limit:
                    break
                total += 1
                folder = out / policy.replace(":", "-") / scenario / f"seed_{seed}"
                folder.mkdir(parents=True, exist_ok=True)
                meta = {
                    "policy": policy,
                    "scenario": scenario,
                    "seed": seed,
                    "simulator": "parikshit",
                    "nodes": cfg["nodes"],
                    "duration_s": load_scenario(scenario).duration_s,
                    "rate_rps": cfg.get("rate_rps"),
                }
                if (
                    a.resume
                    and (folder / "status.json").exists()
                    and json.loads((folder / "status.json").read_text()).get("status")
                    == "ok"
                ):
                    saved = json.loads(
                        (folder / "status.json").read_text(encoding="utf-8")
                    )
                    digests = saved.get("bundle_sha256", {})
                    if not digests or any(
                        not (folder / name).is_file()
                        or hashlib.sha256((folder / name).read_bytes()).hexdigest()
                        != digest
                        for name, digest in digests.items()
                    ):
                        raise ValueError(
                            f"Cached bundle changed or incomplete: {folder}; use a new output directory"
                        )
                    result = json.loads(
                        (folder / "metrics.json").read_text(encoding="utf-8")
                    )
                else:
                    dump(folder / "config.json", {**cfg, **meta})
                    dump(folder / "status.json", {**meta, "status": "running"})
                    try:
                        result = run_one(policy, scenario, seed, cfg, folder)
                        digests = {
                            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in folder.iterdir()
                            if p.is_file() and p.name != "status.json"
                        }
                        dump(
                            folder / "status.json",
                            {**meta, "status": "ok", "bundle_sha256": digests},
                        )
                    except Exception as exc:
                        result = {**meta, "error": str(exc)}
                        dump(
                            folder / "status.json",
                            {**meta, "status": "failed", "error": str(exc)},
                        )
                        (folder / "error.txt").write_text(traceback.format_exc())
                status = json.loads((folder / "status.json").read_text())["status"]
                rows.append({**result, "status": status})
                pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)
                print(f"{total}: {policy} {scenario} seed={seed}: {status}", flush=True)
    summarize(out)
    if any(r["status"] != "ok" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
