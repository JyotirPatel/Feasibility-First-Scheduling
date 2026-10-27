"""Tests for the S6 diagnostic script (window_sweep/diagnostics.py), on the short stand-in cluster."""

import math

import pytest

from test_toy_cluster import short_cluster
from window_sweep.diagnostics import counterfactual, diagnose, make

CLUSTER = short_cluster(rate=120.0)


def test_policy_specs():
    assert make("plain", 3).name == "linucb" and make("plain", 3).seed == 3
    p = make("global:500", 1)
    assert (p.window_mode, p.window_size, p.seed) == ("global", 500, 1)
    with pytest.raises(ValueError):
        make("per_node", 0)


@pytest.mark.parametrize("spec", ["plain", "per_node:200", "global:200"])
def test_diagnose_reports_rush_queue_and_share(spec):
    out = diagnose(spec, 0, CLUSTER)
    assert out["rush_s"] >= 0 and out["peak_queue"] >= 0
    assert 0.0 <= out["share_after"] <= 1.0
    assert out["lowest_goodput"] >= 0 and out["violations"] >= 0
    assert len(out["trace"]) == 12
    second, share, *_ = out["trace"][0]
    assert second == int(CLUSTER.scenarios.s6_outage_recovery.return_s) and 0.0 <= share <= 1.0


def test_watching_does_not_change_the_run_and_uses_the_sweep_metrics():
    """diagnose() wraps the policy to read its estimates; the run and its metrics must equal an unwatched run."""
    from standins.toy_cluster import simulate
    from window_sweep.run_sweep import compute_metrics, load_sweep_config

    out = diagnose("per_node:200", 0, CLUSTER)
    plain_run = simulate(make("per_node:200", 0), "s6_outage_recovery", 0, cluster=CLUSTER, details=False)
    row, _ = compute_metrics(plain_run, CLUSTER, "s6_outage_recovery", load_sweep_config().metrics)
    assert out["rush_s"] == row["return_rush_s"]
    assert out["share_after"] == row["return_node_share_after"]
    assert out["lowest_goodput"] == row["return_deepest_dip"]
    assert out["goodput_mean"] == row["goodput_mean"]
    assert out["violations"] == plain_run.stats["hard_rule_violations"]


def test_baselines_work_in_every_check():
    """Jyotir's baselines have no name, config, stats or explain(); the checks must still run on them."""
    from window_sweep.diagnostics import cluster_load

    out = diagnose("baseline:StaticWeighted", 0, CLUSTER)
    assert 0.0 <= out["share_after"] <= 1.0 and out["violations"] >= 0
    _, _, _, estimate, bonus, best_other, _ = out["trace"][0]
    assert math.isnan(estimate) and math.isnan(bonus) and math.isnan(best_other)
    assert sum(cluster_load("baseline:LeastLoad", 0, CLUSTER)["traffic_share"].values()) == pytest.approx(1.0)


def test_fixed_filter_what_if_applies_the_hard_rules_to_warming_nodes():
    import feasibility_filter.filter as ff
    from baselines import MinRTT
    from standins.toy_cluster import simulate
    from sur_factories import make_node, make_request
    from window_sweep.diagnostics import fixed_warming_rule

    limits = ff.load_config()
    full = make_node(status="warming", kv_used_frac=0.95)
    original = ff._check_node
    assert [n["node_id"] for n in ff.feasibility_filter(make_request(), [full], limits)[0]] == ["us-east-1"]  # the bug
    with fixed_warming_rule():
        allowed, rejected = ff.feasibility_filter(make_request(), [full], limits)
        assert allowed == [] and rejected == [{"node_id": "us-east-1", "reason": "memory_full"}]
        allowed, _ = ff.feasibility_filter(make_request(), [make_node(status="warming", kv_used_frac=0.1)], limits)
        assert allowed[0]["_warming"] is True
        # the same run that test_toy_cluster.py marks as the known bug (xfail) is safe with the fix
        busy = short_cluster(rate=120.0)
        assert simulate(MinRTT(), "s6_outage_recovery", 0, cluster=busy).stats["hard_rule_violations"] == 0
    assert ff._check_node is original


def test_cluster_load_reports_slot_use_and_traffic_shares():
    from window_sweep.diagnostics import cluster_load

    out = cluster_load("plain", 0, CLUSTER)
    assert 0.0 < out["mean_slot_use"] <= out["p95_slot_use"] <= 1.0
    assert sum(out["traffic_share"].values()) == pytest.approx(1.0)


def test_counterfactual_finds_the_lost_requests_in_a_per_node_window():
    c = counterfactual("per_node:200", 0, CLUSTER)
    assert 0 < c["lost_in_window"] <= c["window"] <= 200
    assert c["last_lost_position"] >= c["lost_in_window"]
    assert all(math.isfinite(c[k]) for k in ("estimate_with", "estimate_without", "best_other_score"))
    with pytest.raises(ValueError):
        counterfactual("plain", 0, CLUSTER)


def test_metric_noise_matches_what_results_md_reports():
    """RESULTS_standin.md: at 25 requests/s, S1 (nothing changes) shows a 6-7 s 'adaptation time' for plain LinUCB
    in seeds 0 and 4 and 0 s in seeds 1-3; at 240 requests/s it shows 0 s. (7 s in both seeds since the reward's
    energy scale moved to $0.00001.)"""
    from window_sweep.diagnostics import metric_noise

    assert [metric_noise("plain", s, 25.0) for s in range(5)] == [7.0, 0.0, 0.0, 0.0, 7.0]
    assert metric_noise("plain", 0, 240.0) == 0.0
