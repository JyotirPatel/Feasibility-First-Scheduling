"""Tests for the window-sweep runner (window_sweep/run_sweep.py)."""

import math

import numpy as np
import pytest

from test_toy_cluster import short_cluster
from window_sweep.run_sweep import (
    Job,
    MetricsSpec,
    aggregate,
    bootstrap_ci,
    build_jobs,
    load_sweep_config,
    make_policy,
    run_job,
)

CFG = load_sweep_config()


def test_the_shipped_sweep_covers_the_required_settings():
    assert CFG.window_sweep.sizes == [200, 500, 1000, 2000, 5000]  # brief §6.5 default sweep
    assert set(CFG.window_sweep.modes) == {"per_node", "global"}
    assert len(CFG.seeds) >= 10  # brief §8
    assert {"s2_traffic_burst", "s6_outage_recovery"} <= set(CFG.scenarios)  # what Riya needs at minimum


def test_jobs_are_unique_and_complete():
    jobs = build_jobs(CFG)
    assert len({j.key for j in jobs}) == len(jobs)
    n_sizes = len(CFG.window_sweep.sizes) + len(CFG.window_sweep.extended_sizes)
    per_cell = n_sizes * len(CFG.window_sweep.modes) + 1 + len(CFG.baselines)
    extra_alphas = len([a for a in CFG.alpha_check.alphas if a != 1.0])
    main_grid = len(CFG.scenarios) * len(CFG.seeds) * per_cell
    alpha_grid = len(CFG.alpha_check.scenarios) * len(CFG.seeds) * extra_alphas
    assert len(jobs) == main_grid + alpha_grid
    ck = [j for j in jobs if j.checkpoint]
    assert {(j.family, j.scenario) for j in ck} == {
        (f, s) for f in ("linucb", "sw_linucb") for s in CFG.checkpoints.scenarios
    }


def test_quick_mode_is_the_configured_subset():
    quick = build_jobs(CFG, quick=True)
    assert 0 < len(quick) < 100
    assert {j.seed for j in quick} == set(CFG.seeds[: CFG.quick.seeds])
    assert {j.scenario for j in quick} == set(CFG.quick.scenarios)
    assert {j.window for j in quick if j.family == "sw_linucb"} == set(CFG.quick.sizes)


def test_policies_are_built_with_the_jobs_settings():
    p = make_policy(Job("sw_linucb", "s1_stable", 3, mode="global", window=500, alpha=0.5))
    assert (p.window_size, p.window_mode, p.alpha, p.seed) == (500, "global", 0.5, 3)
    assert make_policy(Job("linucb", "s1_stable", 0, alpha=2.0)).alpha == 2.0
    assert type(make_policy(Job("baseline", "s1_stable", 0, baseline="StaticWeighted"))).__name__ == "StaticWeighted"


def test_one_run_produces_every_metric():
    cluster = short_cluster()
    job = Job("sw_linucb", "s6_outage_recovery", 0, mode="per_node", window=200, alpha=1.0)
    row, curve = run_job((job, cluster.model_dump(), CFG.metrics.model_dump(), None, None))
    for key in (
        "slo_rate",
        "goodput_mean",
        "rejection_rate",
        "cost_per_good_usd",
        "ttft_p99_ms",
        "adaptation_s",
        "recovered",
        "g_star",
        "deepest_dip",
        "degraded_s",
        "return_g_star",
        "return_adaptation_s",
        "hard_rule_violations",
        "runtime_s",
        "return_node_share_before",
        "return_node_share_after",
        "return_rush_s",
    ):
        assert key in row, key
    assert row["label"] == "sw_linucb[per_node,W=200,alpha=1]"
    assert curve.shape == (300,) and np.all(curve >= 0)
    assert 0.0 <= row["slo_rate"] <= 1.0
    assert 0.0 <= row["return_node_share_before"] <= 1.0 and 0.0 <= row["return_node_share_after"] <= 1.0


def test_returning_node_metrics_on_a_hand_made_log():
    """S6 node us-east-1: 30 % of traffic before t0, a 2-second rush after its return, nothing after warm-up."""
    from standins.toy_cluster import DECISION_LOG_COLUMNS, RunResult
    from window_sweep.run_sweep import _returning_node_metrics

    cluster = short_cluster()  # t0 = 60, return at 150, warm-up 30 s, run 300 s
    records, i = [], 0

    def add(t, node):
        nonlocal i
        row = dict.fromkeys(DECISION_LOG_COLUMNS)
        row.update(request_id=f"r{i}", t_arrival=t, decision="route", node_id=node)
        records.append(tuple(row[c] for c in DECISION_LOG_COLUMNS))
        i += 1

    for k in range(100):  # 0-60 s: 3 of every 10 requests to us-east-1
        add(k * 0.6, "us-east-1" if k % 10 < 3 else "us-west-1")
    for k in range(40):  # 150-152 s: all to us-east-1 (the rush); then 152-300 s elsewhere
        add(150 + k * 0.05, "us-east-1")
    for k in range(100):
        add(152 + k * 1.48, "us-west-1")
    result = RunResult(sorted(records, key=lambda r: r[5]))
    t = np.asarray(result.column("t_arrival"), dtype=float)
    routed = np.ones(len(t), dtype=bool)
    m = MetricsSpec.model_validate(CFG.metrics.model_dump())
    out = _returning_node_metrics(result, cluster, m, t, routed)
    assert out["return_node_share_before"] == pytest.approx(0.3)
    assert out["return_rush_s"] == 2.0
    assert out["return_node_share_after"] == 0.0


def test_a_metrics_confidence_interval_does_not_depend_on_other_metrics():
    m = MetricsSpec.model_validate(CFG.metrics.model_dump())
    base = {
        "label": "x",
        "family": "linucb",
        "mode": None,
        "window": None,
        "alpha": 1.0,
        "baseline": None,
        "scenario": "s1_stable",
        "hard_rule_violations": 0,
    }
    rng = np.random.default_rng(3)
    only_cost = [{**base, "seed": s, "cost_per_good_usd": float(rng.uniform(4e-5, 6e-5))} for s in range(10)]
    with_more = [{**r, "goodput_mean": 230.0 + s, "slo_rate": 0.9} for s, r in enumerate(only_cost)]
    (a,) = aggregate(only_cost, m)
    (b,) = aggregate(with_more, m)
    assert (a["cost_per_good_usd_lo"], a["cost_per_good_usd_hi"]) == (
        b["cost_per_good_usd_lo"],
        b["cost_per_good_usd_hi"],
    )


def test_aggregate_counts_runs_that_abandoned_the_returned_node():
    m = MetricsSpec.model_validate(CFG.metrics.model_dump())
    base = {
        "label": "x",
        "family": "sw_linucb",
        "mode": "per_node",
        "window": 1000,
        "alpha": 1.0,
        "baseline": None,
        "scenario": "s6_outage_recovery",
        "hard_rule_violations": 0,
    }
    shares = [0.0, 0.3, 0.005, 0.32, 0.0]
    rows = [{**base, "seed": s, "return_node_share_after": v} for s, v in enumerate(shares)]
    (summary,) = aggregate(rows, m)
    assert summary["return_node_abandoned_runs"] == 3  # < 1 %


def test_aggregate_gives_means_and_confidence_intervals():
    m = MetricsSpec.model_validate(CFG.metrics.model_dump())
    base = {
        "label": "x",
        "family": "linucb",
        "mode": None,
        "window": None,
        "alpha": 1.0,
        "baseline": None,
        "scenario": "s1_stable",
        "hard_rule_violations": 0,
    }
    rows = [
        {**base, "seed": s, "slo_rate": v, "recovered": s != 2, "adaptation_s": float("nan") if s == 2 else 4.0 + s}
        for s, v in enumerate([0.90, 0.92, 0.94, 0.96])
    ]
    (summary,) = aggregate(rows, m)
    assert summary["seeds"] == 4 and summary["slo_rate"] == pytest.approx(0.93)
    assert summary["slo_rate_lo"] <= 0.93 <= summary["slo_rate_hi"]
    assert summary["recovered_runs"] == 3
    assert summary["adaptation_s"] == pytest.approx((4 + 5 + 7) / 3)


def test_bootstrap_ci_edge_cases():
    rng = np.random.default_rng(0)
    assert bootstrap_ci([], 100, 0.95, rng)[0] != bootstrap_ci([], 100, 0.95, rng)[0]  # nan != nan
    assert bootstrap_ci([3.0], 100, 0.95, rng) == (3.0, 3.0)
    lo, hi = bootstrap_ci([1.0, float("nan"), 3.0], 1000, 0.95, rng)
    assert 1.0 <= lo <= hi <= 3.0 and not math.isnan(lo)
