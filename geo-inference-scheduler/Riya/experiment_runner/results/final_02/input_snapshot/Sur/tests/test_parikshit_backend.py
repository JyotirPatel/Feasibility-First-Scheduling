"""Tests for the window sweep on Parikshit's simulator (window_sweep/parikshit_backend.py)."""

import math

import pandas as pd
import pytest

from window_sweep.parikshit_backend import RunResult, make_router_policy, scenario_clock
from window_sweep.run_sweep import Job, load_sweep_config, policy_config, run_job

CFG = load_sweep_config()


def test_scenario_clock_gives_the_traces_times():
    clock = scenario_clock("s6_outage_recovery")
    assert (clock.duration_s, clock.t0_s, clock.change_times) == (600.0, 200.0, {"t0": 200.0, "return": 400.0})
    outage = clock.scenarios.s6_outage_recovery
    assert (outage.node, outage.return_s, outage.warmup_s) == ("us-east-nyc", 400.0, 60.0)
    assert scenario_clock("s2_traffic_burst").change_times == {"t0": 200.0}


def test_router_policies_get_the_jobs_settings():
    job = Job("sw_linucb", "s1_stable", 3, mode="global", window=500, alpha=0.5)
    p = make_router_policy(job.family, seed=job.seed, config=policy_config(job))
    assert (type(p).__name__, p.window_size, p.window_mode, p.alpha, p.seed) == (
        "RouterSlidingWindowLinUCB",
        500,
        "global",
        0.5,
        3,
    )
    plain = make_router_policy("linucb", seed=0, config=policy_config(Job("linucb", "s1_stable", 0, alpha=2.0)))
    assert (type(plain).__name__, plain.alpha) == ("RouterLinUCB", 2.0)
    for name in CFG.baselines:  # every baseline in sweep.yaml exists in Krupesh's registry
        assert make_router_policy("baseline", seed=0, baseline=name) is not None


def test_rejected_requests_count_as_missed_and_cost_nothing():
    log = pd.DataFrame(
        {
            "slo_met": [True, False, None],
            "cost_usd": [0.1, 0.2, float("nan")],
            "energy_kwh": [1e-5, 2e-5, None],
            "ttft_ms": [100.0, 400.0, float("nan")],
            "decision": ["route", "route", "reject"],
        }
    )
    r = RunResult(log, {})
    assert r.column("slo_met") == [True, False, False]
    assert r.column("cost_usd") == [0.1, 0.2, 0.0] and r.column("energy_kwh") == [1e-5, 2e-5, 0.0]
    assert r.column("ttft_ms")[2] is None and r.column("decision") == ["route", "route", "reject"]


def test_one_sweep_run_on_the_real_pipeline():
    """A full 600-s S6 run through Parikshit's simulator and Krupesh's router, as in the sweep."""
    job = Job("sw_linucb", "s6_outage_recovery", 0, mode="per_node", window=1000, alpha=1.0)
    row, curve = run_job((job, "parikshit", None, CFG.metrics.model_dump(), None, None))
    assert row["hard_rule_violations"] == 0 and row["reward_mismatch"] == 0  # filter on; router and policy agree
    assert row["requests"] > 40_000 and row["failed"] > 0  # the outage loses the requests on the node
    assert curve.shape == (600,) and 0.0 < row["slo_rate"] <= 1.0
    for key in ("adaptation_s", "g_star", "return_adaptation_s", "return_node_share_after", "true_state_violations"):
        assert key in row, key
    assert math.isfinite(row["g_star"]) and row["return_node_share_before"] > 0
    with pytest.raises(KeyError):
        make_router_policy("baseline", seed=0, baseline="NoSuchBaseline")
