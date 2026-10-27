"""Execute teammate policies through the real router with the MOCK cluster."""
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

RIYA=Path(__file__).resolve().parents[1]
ROOT=RIYA.parent
# Explicit paths handle the uploaded nested tree without modifying teammates.
for folder in [ROOT/"Sur", ROOT/"Jyotir", RIYA/"metrics"]:
    sys.path.insert(0,str(folder))
candidates=[ROOT/"Krupesh", ROOT/"Krupesh/geo-inference-scheduler/Krupesh"]
KR=next((p for p in candidates if (p/"router_service/engine.py").exists()),None)
if KR is None:
    raise RuntimeError("Cannot locate Krupesh router")
sys.path.append(str(KR))
from integration import jyotir_adapter
jyotir_adapter.JYOTIR_DIR=ROOT/"Jyotir"
from router_plugin import register, make_reward_fn
from router_service.registry import build_policy, build_filter
from router_service.engine import RoutingEngine, RunMeta
from integration.mocks.mock_simulator import MockCluster
from decision_log.writer import DecisionLogWriter, validate_log
from evaluate_log import evaluate


def dump(path,obj):
    path.write_text(json.dumps(obj,indent=2,allow_nan=False,default=str),encoding="utf-8")


def source_info():
    files=sorted(p for owner in ["Riya","Krupesh","Jyotir","Sur"] for p in (ROOT/owner).rglob("*") if p.suffix in [".py",".yaml"] and "results" not in p.parts)
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    try:
        commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError):
        commit=None
    return {"git_commit":commit,"source_sha256":manifest}


def run_one(policy,scenario,seed,cfg,folder):
    register()
    model=build_policy(policy,seed=seed)
    reward_cfg=model.config.reward if hasattr(model,"config") else None
    engine=RoutingEngine(policy=model,filter_fn=build_filter("jyotir"),
        reward_fn=make_reward_fn(reward_cfg),
        meta=RunMeta(f"{scenario}__{policy}__s{seed}",seed,scenario,policy),
        writer=DecisionLogWriter(folder/"decision_log.csv"),audit_fn=build_filter("jyotir"))
    duration=cfg["duration_s"]
    outage=("node-east",duration/3,2*duration/3) if scenario=="mock_outage" else None
    cluster=MockCluster(engine,seed=seed,duration_s=duration,rate_rps=cfg["rate_rps"],outage=outage)
    cluster.run()
    engine.finish()
    df=engine.writer.close()
    # Metrics always read the persisted authoritative log.
    df=pd.read_csv(folder/"decision_log.csv")
    problems=validate_log(df)
    if problems:
        raise ValueError(str(problems))
    result=evaluate(df,duration)
    result.update(policy=policy,scenario=scenario,seed=seed)
    if hasattr(model,"stats"):
        dump(folder/"policy_stats.json",dict(model.stats))
        if model.stats.get("reward_mismatch",0):
            raise ValueError("Router and policy rewards disagree")
    # Full completion-time curve includes drain after arrival cutoff.
    end=max(duration,float(df.t_complete.max()) if df.t_complete.notna().any() else duration)
    bins=np.arange(0,np.ceil(end)+1)
    successes=df.slo_met.astype(str).str.lower().eq("true")
    counts,_=np.histogram(df.loc[successes,"t_complete"].dropna(),bins=bins)
    curve=pd.DataFrame({"time_s":bins[:-1],"goodput_rps":counts})
    curve["smoothed_goodput_rps"]=curve.goodput_rps.rolling(5,min_periods=5).mean()
    curve.to_csv(folder/"goodput_curve.csv",index=False)
    dump(folder/"events.json",{"outage_start_s":duration/3 if outage else None,"node_returns_warming_s":2*duration/3 if outage else None,"warmup_s":20,"last_processed_event_s":cluster.now})
    dump(folder/"metrics.json",result)
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(Path(__file__).with_name("config_mock.json")))
    ap.add_argument("--output",required=True)
    ap.add_argument("--limit",type=int)
    ap.add_argument("--resume",action="store_true")
    a=ap.parse_args()
    cfg=json.loads(Path(a.config).read_text())
    if cfg.get("simulator")!="mock" or not set(cfg["scenarios"]) <= {"mock_stable","mock_outage"}:
        raise ValueError("Only documented mock scenarios supported")
    if not cfg["duration_s"]>0 or not cfg["rate_rps"]>0:
        raise ValueError("Duration and rate must be positive")
    out=Path(a.output).resolve()
    if out.exists() and not a.resume:
        raise FileExistsError("Choose a new output folder or --resume")
    out.mkdir(parents=True,exist_ok=True)
    provenance=source_info()
    if (out/"config.json").exists():
        if json.loads((out/"config.json").read_text())!=cfg or json.loads((out/"source.json").read_text())!=provenance:
            raise ValueError("Config/source changed; use a new output folder")
    dump(out/"config.json",cfg)
    dump(out/"source.json",provenance)
    rows=[]
    total=0
    for policy in cfg["policies"]:
        for scenario in cfg["scenarios"]:
            for seed in cfg["seeds"]:
                if a.limit is not None and total>=a.limit:
                    break
                total+=1
                folder=out/policy.replace(":","-")/scenario/f"seed_{seed}"
                folder.mkdir(parents=True,exist_ok=True)
                meta={"policy":policy,"scenario":scenario,"seed":seed,"simulator":"mock","duration_s":cfg["duration_s"],"rate_rps":cfg["rate_rps"]}
                if a.resume and (folder/"status.json").exists() and json.loads((folder/"status.json").read_text()).get("status")=="ok":
                    result=json.loads((folder/"metrics.json").read_text())
                else:
                    dump(folder/"config.json",{**cfg,**meta})
                    dump(folder/"status.json",{**meta,"status":"running"})
                    try:
                        result=run_one(policy,scenario,seed,cfg,folder)
                        dump(folder/"status.json",{**meta,"status":"ok"})
                    except Exception as exc:
                        result={**meta,"error":str(exc)}
                        dump(folder/"status.json",{**meta,"status":"failed","error":str(exc)})
                        (folder/"error.txt").write_text(traceback.format_exc())
                status=json.loads((folder/"status.json").read_text())["status"]
                rows.append({**result,"status":status})
                pd.DataFrame(rows).to_csv(out/"summary.csv",index=False)
                print(f"{total}: {policy} {scenario} seed={seed}: {status}",flush=True)
    valid=pd.DataFrame([r for r in rows if r["status"]=="ok"])
    intervals=[]
    rng=np.random.default_rng(20261027)
    if not valid.empty:
        for (policy,scenario),group in valid.groupby(["policy","scenario"]):
            for metric in ["goodput_rps","p95_ttft_ms","p99_ttft_ms","p95_e2e_ms","p99_e2e_ms","rejection_rate","cost_usd_per_slo_success","energy_kwh_per_slo_success"]:
                values=pd.to_numeric(group[metric],errors="coerce").dropna().to_numpy()
                low=high=None
                if len(values)>=10:
                    samples=rng.choice(values,size=(2000,len(values)),replace=True).mean(axis=1)
                    low,high=np.quantile(samples,[.025,.975])
                intervals.append({"policy":policy,"scenario":scenario,"metric":metric,"n":len(values),"mean":float(values.mean()) if len(values) else None,"ci_low":low,"ci_high":high,"ci_status":"available" if len(values)>=10 else "insufficient_seeds"})
    pd.DataFrame(intervals).to_csv(out/"confidence_intervals.csv",index=False)
    if any(r["status"]!="ok" for r in rows):
        raise SystemExit(1)

if __name__=="__main__":
    main()
