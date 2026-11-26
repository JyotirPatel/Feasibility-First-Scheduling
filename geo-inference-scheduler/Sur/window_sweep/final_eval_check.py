"""
Checks on the final evaluation — owner: Sur

Riya's final evaluation (Riya/experiment_runner/results/final_02, 600 runs) found two results about
Sur's policy that need an explanation (report/final_evaluation_notes.md):

  1. the "no context" ablation beats the full SW-LinUCB in S4, S5 and S6;
  2. after the S6 outage, SW-LinUCB takes 18.3 s to recover against 9.9 s for plain LinUCB.

This script prints every number the notes quote, and the S3 numbers in window_sweep/RESULTS.md (finding 5):

  part 0     checks that Jyotir's kv_cache_max_frac fix changed none of the window sweep's runs: the sweep
             ran before it, the final evaluation after it (no runs);
  parts 1-3  from Riya's saved goodput curves and traffic shares (no runs);
  parts 4-6  twelve of her runs re-run through the same pipeline (Parikshit's simulator -> Krupesh's router
             -> Jyotir's filter -> Sur's policy), recording the policy's estimates. Each re-run must
             reproduce her goodput curve exactly, or the script stops. About 2 minutes. Part 6 measures
             how little S3's price shift moves the reward under the kept weights.

    python3 window_sweep/final_eval_check.py [--bundle PATH] [--no-reruns]

Nothing outside Sur/ is changed.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_SUR_DIR = os.path.dirname(_HERE)
if _SUR_DIR not in sys.path:
    sys.path.insert(0, _SUR_DIR)

from window_sweep import parikshit_backend as pb  # noqa: E402

DEFAULT_BUNDLE = os.path.join(os.path.dirname(_SUR_DIR), "Riya", "experiment_runner", "results", "final_02")
SWEEP_RUNS = os.path.join(_HERE, "results", "runs.csv")  # the window sweep's per-run results
RUN_DIRS = {"full": "sur-sw_linucb", "no_context": "sur-sw_linucb_no_context", "plain": "sur-linucb"}
CONFIGS = {"full": "sw_linucb.yaml", "no_context": "sw_linucb_no_context.yaml", "plain": "linucb.yaml"}
SEEDS = range(10)
SCENARIOS = (
    "s1_stable",
    "s2_traffic_burst",
    "s3_price_shift",
    "s4_thermal_throttle",
    "s5_network_degradation",
    "s6_outage_recovery",
)
CHANGED = SCENARIOS[3:]  # S4, S5 and S6: each change hits New York
NYC, SJC, LAX = "us-east-nyc", "us-west-sjc", "us-west-lax"
WEST = ("lax", "sfo")  # west-coast user regions

# Settings come from the configs and the event traces, as the sweep's do (brief: no limits, weights or window
# sizes in Python).
with open(os.path.join(_SUR_DIR, "configs", "policies", CONFIGS["full"])) as _f:
    SHIPPED = yaml.safe_load(_f)  # the shipped policy config
WINDOW = int(SHIPPED["window"]["size"])  # the per-node window W
ALPHA = float(SHIPPED["alpha"])
with open(os.path.join(_HERE, "sweep.yaml")) as _f:
    METRICS = yaml.safe_load(_f)["metrics"]  # the frozen adaptation-time definition the sweep uses
_CLOCKS = {s: pb.scenario_clock(s) for s in SCENARIOS}
if len({c.t0_s for c in _CLOCKS.values()}) != 1 or len({c.duration_s for c in _CLOCKS.values()}) != 1:
    raise ValueError("the scenarios no longer share one change time and duration; adapt this script")
T0 = _CLOCKS["s1_stable"].t0_s  # every scenario's change time
DURATION = _CLOCKS["s1_stable"].duration_s
S6_RETURN = _CLOCKS["s6_outage_recovery"].change_times["return"]
N_BINS = int(round(DURATION / METRICS["bin_s"]))
AFTER = T0 + METRICS["steady_from_s"]  # "after the change": from the start of G*'s steady window
SETTLE_S = 20.0  # analysis choice: per-seed gaps and S6 shares leave out the first 20 s after a change


# ── part 1: Riya's saved results ─────────────────────────────────────────────


def load_curve(bundle: str, policy: str, scenario: str, seed: int) -> pd.DataFrame:
    path = os.path.join(bundle, RUN_DIRS[policy], scenario, f"seed_{seed}", "goodput_curve.csv")
    return pd.read_csv(path).sort_values("time_s").reset_index(drop=True)


def mean_goodput(curve: pd.DataFrame, start: float, end: float = np.inf) -> float:
    """Mean SLO goodput (requests/s, 1-s bins by arrival time) over [start, end)."""
    t = curve.time_s
    return float(curve.goodput_rps[(t >= start) & (t < end)].mean())


def steady(curve: pd.DataFrame, t0: float) -> float:
    """G*: the mean smoothed goodput over the frozen steady window [t0 + 60 s, t0 + 120 s)."""
    t = curve.time_s
    a, b = t0 + METRICS["steady_from_s"], t0 + METRICS["steady_to_s"]
    return float(curve.smoothed_goodput_rps[(t >= a) & (t < b)].mean())


def first_hold(curve: pd.DataFrame, t0: float, bar: float, hold: int | None = None) -> float | None:
    """Seconds from t0 until the smoothed goodput first stays >= bar for `hold` bins (default: the frozen 10 s);
    None if it never does. With bar = 0.9 · G* this is the frozen adaptation time; a shared bar compares two
    policies fairly."""
    if hold is None:
        hold = max(int(round(METRICS["hold_s"] / METRICS["bin_s"])), 1)
    ok = (curve.smoothed_goodput_rps >= bar).to_numpy()
    times = curve.time_s.to_numpy()
    for i in np.flatnonzero(times >= t0):
        if i + hold <= len(ok) and ok[i : i + hold].all():
            return float(times[i] - t0)
    return None


def sweep_against_final(bundle: str, sweep_runs: str = SWEEP_RUNS) -> pd.DataFrame:
    """The window sweep ran with Jyotir's filter before his kv_cache_max_frac fix (5e3b1a6); the final evaluation
    ran with the fix. Per policy: how many of the 60 runs (6 scenarios × 10 seeds) differ in requests or SLO-met."""
    sweep = pd.read_csv(sweep_runs)
    final = pd.read_csv(os.path.join(bundle, "summary.csv"))
    in_sweep = {
        "sur:sw_linucb": (sweep.family == "sw_linucb")
        & (sweep["mode"] == "per_node")
        & (sweep.window == WINDOW)
        & (sweep.alpha == ALPHA),
        "sur:linucb": (sweep.family == "linucb") & (sweep.alpha == ALPHA),
    }
    rows = []
    for name, m in in_sweep.items():
        s = sweep[m].assign(slo_met=lambda d: (d.slo_rate * d.requests).round().astype(int))
        j = s.merge(final[final.policy == name], on=["scenario", "seed"], suffixes=("_sweep", "_final"))
        rows.append(
            {
                "policy": name,
                "runs compared": len(j),
                "runs with other request counts": int((j.requests_sweep != j.requests_final).sum()),
                "runs with other SLO-met counts": int((j.slo_met != j.slo_successes).sum()),
            }
        )
    return pd.DataFrame(rows).set_index("policy")


def gaps_after_change(bundle: str) -> pd.DataFrame:
    """Per seed: full minus no-context mean goodput from t0 + SETTLE_S to the end, in S4, S5 and S6."""
    gap = {
        s: [
            mean_goodput(load_curve(bundle, "full", s, k), T0 + SETTLE_S)
            - mean_goodput(load_curve(bundle, "no_context", s, k), T0 + SETTLE_S)
            for k in SEEDS
        ]
        for s in CHANGED
    }
    return pd.DataFrame(gap, index=pd.Index(SEEDS, name="seed"))


def nyc_shares(bundle: str) -> pd.DataFrame:
    """New York's share of arrivals (%) per seed: before the change, in S5's steady window, and in S6's steady
    window after New York returns."""
    t = pd.read_csv(os.path.join(bundle, "node_traffic_shares.csv"))
    t = t[t.node_id == NYC]
    s5 = t[(t.anchor == "t0") & (t.scenario == "s5_network_degradation")]
    s6 = t[(t.anchor == "return") & (t.scenario == "s6_outage_recovery")]
    out = {}
    for policy, name in (("full", "sur:sw_linucb"), ("no context", "sur:sw_linucb_no_context")):
        p, r = (x[x.policy == name].set_index("seed").sort_index() for x in (s5, s6))
        out[f"{policy}: before"] = 100 * p.pre_event_arrival_share
        out[f"{policy}: S5 after"] = 100 * p.steady_arrival_share
        out[f"{policy}: S6 after return"] = 100 * r.steady_arrival_share
    return pd.DataFrame(out)


def s6_outage_times(bundle: str) -> pd.DataFrame:
    """S6 from t0: SW-LinUCB and plain LinUCB against each one's own bar (0.9 · G*) and against one shared bar
    (0.9 · the lower of the two G*)."""
    rows = []
    for k in SEEDS:
        c = {p: load_curve(bundle, p, "s6_outage_recovery", k) for p in ("full", "plain")}
        g = {p: steady(c[p], T0) for p in c}
        shared = METRICS["fraction"] * min(g.values())
        row = {f"G* {p}": g[p] for p in c}
        row |= {f"{p}: own bar": first_hold(c[p], T0, METRICS["fraction"] * g[p]) for p in c}
        row |= {f"{p}: shared bar": first_hold(c[p], T0, shared) for p in c}
        rows.append(row)
    return pd.DataFrame(rows, index=pd.Index(SEEDS, name="seed"))


# ── part 2: re-runs with the policy's estimates recorded ─────────────────────


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _met(s: pd.Series) -> pd.Series:
    return s.eq(True)  # slo_met is None for a request that got no outcome


def rerun(bundle: str, policy: str, scenario: str, seed: int, record_from: float = AFTER):
    """Re-run one of Riya's runs. Returns its decision log and, for each decision from `record_from` on,
    every candidate's estimate θᵀx, exploration bonus α√(xᵀA⁻¹x) and load (running / capacity) at that moment."""
    family = "linucb" if policy == "plain" else "sw_linucb"
    config = os.path.join(_SUR_DIR, "configs", "policies", CONFIGS[policy])
    p = pb.make_router_policy(family, seed=seed, config=config)
    rows, choose = [], p.choose

    def recording_choose(request, candidates):
        if _get(request, "t_arrival") >= record_from:
            load = {_get(c, "node_id"): _get(c, "running", 0) / max(_get(c, "capacity", 1), 1) for c in candidates}
            rid = _get(request, "request_id")
            for e in p.explain(request, candidates):
                node_id = e["node_id"]
                rows.append((rid, node_id, e["estimate"], e["bonus"], load[node_id]))
        return choose(request, candidates)

    p.choose = recording_choose
    log = pb.simulate(p, scenario, seed, policy_name=f"sur:{policy}", run_id=f"check-{policy}-{scenario}-{seed}").log
    bins = np.floor(log.t_arrival[_met(log.slo_met)] / METRICS["bin_s"]).astype(int)
    ours = np.bincount(bins, minlength=N_BINS)[:N_BINS]
    if not np.array_equal(ours, load_curve(bundle, policy, scenario, seed).goodput_rps.to_numpy()[:N_BINS]):
        raise RuntimeError(f"{policy} {scenario} seed {seed}: the re-run differs from Riya's run")
    return log, pd.DataFrame(rows, columns=["request_id", "node_id", "estimate", "bonus", "load"])


def lock_in(bundle: str, seeds=(0, 3, 8, 9)) -> pd.DataFrame:
    """S5: where the full policy sends interactive requests, what San Jose's model has seen when New York
    slows down, what it then predicts for them, and what they actually earn at San Jose (no-context runs)."""
    rows = []
    for k in seeds:
        log, est = rerun(bundle, "full", "s5_network_degradation", k)
        nc, _ = rerun(bundle, "no_context", "s5_network_degradation", k, record_from=np.inf)
        inter, before, after = log.slo_class == "interactive", log.t_arrival < T0, log.t_arrival >= AFTER
        sj = log[log.node_id == SJC].sort_values("t_complete")
        window = sj[sj.t_complete <= T0].tail(WINDOW)  # San Jose's window when the change hits
        win_inter = window[window.slo_class == "interactive"]
        e = est.merge(log[["request_id", "slo_class"]], on="request_id")
        e = e[e.slo_class == "interactive"].groupby("node_id")[["estimate", "bonus"]].mean()
        west_after = after & log.user_region.isin(WEST)
        nc_after = nc.t_arrival >= AFTER
        rows.append(
            {
                "seed": k,
                "interactive -> NY before %": 100 * (log.node_id[inter & before] == NYC).mean(),
                "interactive -> NY after %": 100 * (log.node_id[inter & after] == NYC).mean(),
                "SJ window interactive %": 100 * len(win_inter) / len(window),
                "their median input": win_inter.input_tokens.median(),
                "all interactive median input": log.input_tokens[inter].median(),
                "NY estimate, interactive": e.estimate[NYC],
                "SJ estimate, interactive": e.estimate[SJC],
                "SJ bonus, interactive": e.bonus[SJC],
                "actual at SJ, interactive (no ctx)": nc.reward[
                    nc_after & (nc.slo_class == "interactive") & (nc.node_id == SJC)
                ].mean(),
                "west users -> NY after %": 100 * (log.node_id[west_after] == NYC).mean(),
                "their SLO rate at NY": _met(log.slo_met[west_after & (log.node_id == NYC)]).mean(),
                "SLO rate after: full": _met(log.slo_met[after]).mean(),
                "SLO rate after: no ctx": _met(nc.slo_met[nc_after]).mean(),
            }
        )
    return pd.DataFrame(rows).set_index("seed")


def s6_outage_routing(bundle: str, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """S6 during the outage (t0 + SETTLE_S to the return): each site's share and SLO rate under both policies;
    and, for the full policy, the estimates and San Jose's load when it chose Los Angeles or San Jose."""
    sites, chosen = {}, None
    for policy in ("full", "no_context"):
        log, est = rerun(bundle, policy, "s6_outage_recovery", seed, record_from=T0 + SETTLE_S)
        d = log[(log.t_arrival >= T0 + SETTLE_S) & (log.t_arrival < S6_RETURN)]
        g = d.groupby("node_id").agg(n=("request_id", "size"), slo_rate=("slo_met", lambda s: _met(s).mean()))
        g.loc["all sites"] = [g.n.sum(), _met(d.slo_met).mean()]
        g["share %"] = 100 * g.n / len(d)
        sites[policy] = g[["share %", "slo_rate"]]
        if policy == "full":
            e = est[est.request_id.isin(d.request_id)].pivot(index="request_id", columns="node_id")
            pick = d.set_index("request_id").node_id
            chosen = pd.DataFrame(
                {
                    "chosen": pick.reindex(e.index),
                    "estimate LA": e["estimate"][LAX],
                    "estimate SJ": e["estimate"][SJC],
                    "SJ load": e["load"][SJC],
                }
            )
            chosen = chosen[chosen.chosen.isin([LAX, SJC])].groupby("chosen").mean()
    return pd.concat(sites, axis=1), chosen


def s3_energy_effect(bundle: str, seed: int = 0) -> pd.Series:
    """S1 against S3 with the same seed (full policy): how much the price shift lowers each request's reward,
    and how much of the routing and of the SLO outcomes it changes."""
    s1, _ = rerun(bundle, "full", "s1_stable", seed, record_from=np.inf)
    s3, _ = rerun(bundle, "full", "s3_price_shift", seed, record_from=np.inf)
    both = s1.merge(s3, on="request_id", suffixes=("_s1", "_s3"))
    after = both.t_arrival_s3 >= T0
    same = both.node_id_s1 == both.node_id_s3
    drop = (both.reward_s1 - both.reward_s3)[after & same].groupby(both.node_id_s3[after & same])
    california = both.node_id_s3.isin([SJC, LAX]), both.node_id_s1.isin([SJC, LAX])
    met = _met(both.slo_met_s3[after])
    return pd.Series(
        {
            "reward drop after the shift, San Jose (mean)": drop.mean()[SJC],
            "reward drop after the shift, San Jose (max)": drop.max()[SJC],
            "reward drop after the shift, New York (mean)": drop.mean()[NYC],
            "S3 reward, SLO met minus missed (after)": both.reward_s3[after][met].mean()
            - both.reward_s3[after][~met].mean(),
            "choices that differ from S1": int((~same).sum()),
            "requests": len(both),
            "SLO-met requests, S1": int(_met(both.slo_met_s1).sum()),
            "SLO-met requests, S3": int(_met(both.slo_met_s3).sum()),
            "California share after the shift %, S1": 100 * california[1][after].mean(),
            "California share after the shift %, S3": 100 * california[0][after].mean(),
        }
    )


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Numbers for report/final_evaluation_notes.md.")
    ap.add_argument("--bundle", default=DEFAULT_BUNDLE, help="Riya's final_02 bundle")
    ap.add_argument("--no-reruns", action="store_true", help="only the checks on saved results (no simulator runs)")
    args = ap.parse_args(argv)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    print("0. The sweep (filter before Jyotir's kv_cache_max_frac fix) against the final evaluation (with it)\n")
    print(sweep_against_final(args.bundle).to_string(), "\n")
    gaps = gaps_after_change(args.bundle)
    print(f"1. Full minus no-context goodput from {T0 + SETTLE_S:.0f} s to the end (requests/s), per seed\n")
    print(gaps.round(2).to_string(), "\n\nmean:", gaps.mean().round(2).to_dict(), "\n")
    print("2. New York's share of arrivals (%), per seed\n")
    print(nyc_shares(args.bundle).round(1).to_string(), "\n")
    times = s6_outage_times(args.bundle)
    print("3. S6 after the outage: adaptation time (s) against each policy's own bar and one shared bar\n")
    print(times.round(1).to_string(), "\n\nmean:", times.mean().round(1).to_dict(), "\n")
    if args.no_reruns:
        return 0

    print("4. S5, full policy (seeds 3, 8, 9 lose; seed 0 for contrast). Re-runs match Riya's exactly.\n")
    print(lock_in(args.bundle).round(2).T.to_string(), "\n")
    sites, chosen = s6_outage_routing(args.bundle)
    print(f"5. S6 seed 0, during the outage ({T0 + SETTLE_S:.0f}-{S6_RETURN:.0f} s): each site's share and SLO rate\n")
    print(sites.round(3).to_string(), "\n")
    print("   full policy: mean estimates and San Jose's load (running / capacity) by where the request went\n")
    print(chosen.round(3).to_string(), "\n")
    weights = " / ".join(str(w) for w in SHIPPED["reward"]["weights"].values())
    print(f"6. S3 against S1, seed 0, full policy: what the price shift does with weights {weights}\n")
    print(s3_energy_effect(args.bundle).round(4).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
