"""Tests for the stand-in simulator (standins/toy_cluster.py) and the full loop through it."""

import os

import numpy as np
import pytest
import yaml

from linucb import LinUCB
from sliding_window_linucb import SlidingWindowLinUCB
from standins.toy_cluster import (
    DECISION_LOG_COLUMNS,
    SCENARIOS,
    ClusterConfig,
    SafetyViolation,
    _hard_rule_problems,
    generate_workload,
    load_cluster_config,
    simulate,
)
from sur_factories import SUR_DIR, load_yaml, make_node, make_request

with open(os.path.join(SUR_DIR, "standins", "toy_cluster.yaml")) as f:
    FULL = yaml.safe_load(f)


def short_cluster(rate=40.0) -> ClusterConfig:
    """The stand-in cluster, shrunk to a 300 s run so tests stay fast."""
    cfg = yaml.safe_load(yaml.safe_dump(FULL))
    cfg["duration_s"], cfg["t0_s"] = 300, 60
    cfg["workload"]["base_rate_rps"] = rate
    cfg["scenarios"]["s2_traffic_burst"]["duration_s"] = 60
    cfg["scenarios"]["s6_outage_recovery"].update({"return_s": 150, "warmup_s": 30})
    scale = rate / FULL["workload"]["base_rate_rps"]
    for node in cfg["nodes"]:  # keep utilization similar to the full config
        node["capacity"] = max(int(node["capacity"] * scale), 8)
        node["kv_capacity_tokens"] = max(int(node["kv_capacity_tokens"] * scale), 6000)
    return ClusterConfig.model_validate(cfg)


CLUSTER = short_cluster()


class Recorder:
    """A policy that picks the first candidate and remembers what it saw."""

    name = "recorder"

    def __init__(self):
        self.seen, self.updates = [], 0

    def choose(self, request, candidates):
        self.seen.append((request["t_arrival"], [dict(c) for c in candidates]))
        return candidates[0]["node_id"]

    def update(self, request, node_id, outcome):
        self.updates += 1


def test_the_shipped_cluster_config_is_valid():
    cfg = load_cluster_config()
    assert cfg.duration_s == 600 and cfg.t0_s == 200  # brief §5
    assert len(cfg.nodes) == 5


# ── workload ─────────────────────────────────────────────────────────────────


def test_workload_does_not_depend_on_the_order_of_regions_or_classes_in_the_yaml():
    """Two configs that are equal as data must give the same requests (yaml.safe_dump re-sorts keys)."""
    as_written = load_cluster_config()
    data = as_written.model_dump()
    data["workload"]["regions"] = dict(reversed(list(data["workload"]["regions"].items())))
    data["workload"]["classes"] = dict(reversed(list(data["workload"]["classes"].items())))
    reordered = ClusterConfig.model_validate(data)
    assert list(reordered.workload.regions) != list(as_written.workload.regions)  # the order really differs
    for scenario in ("s1_stable", "s2_traffic_burst"):
        assert generate_workload(reordered, scenario, 7) == generate_workload(as_written, scenario, 7)


def test_workload_depends_only_on_the_seed():
    a, b = generate_workload(CLUSTER, "s1_stable", 3), generate_workload(CLUSTER, "s1_stable", 3)
    assert a == b
    assert a != generate_workload(CLUSTER, "s1_stable", 4)
    for r in a:
        assert {
            "request_id",
            "t_arrival",
            "user_region",
            "model",
            "input_tokens",
            "expected_output_tokens",
            "slo_class",
            "ttft_slo_ms",
        } <= set(r)
        assert 0 <= r["t_arrival"] < CLUSTER.duration_s
    times = [r["t_arrival"] for r in a]
    assert times == sorted(times)


def test_traffic_burst_triples_the_arrival_rate_for_its_duration():
    t = np.array([r["t_arrival"] for r in generate_workload(CLUSTER, "s2_traffic_burst", 0)])
    before = np.sum(t < 60) / 60
    during = np.sum((t >= 60) & (t < 120)) / 60
    after = np.sum(t >= 120) / 180
    assert during / before == pytest.approx(3.0, rel=0.1)
    assert after / before == pytest.approx(1.0, rel=0.1)


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError):
        generate_workload(CLUSTER, "s7_meteor", 0)


# ── the loop ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_request_is_logged_once_with_the_decision_log_columns(scenario):
    result = simulate(LinUCB(), scenario, 0, cluster=CLUSTER)
    rows = result.rows
    assert len(rows) == result.stats["requests"] == result.stats["routed"] + result.stats["rejected"]
    assert len({r["request_id"] for r in rows}) == len(rows)
    assert all(tuple(r) == DECISION_LOG_COLUMNS for r in rows)
    for r in rows:
        if r["decision"] == "route":
            assert r["node_id"] in r["feasible_nodes"] and r["reward"] is not None
        else:
            assert r["reject_reason"] == "no_feasible_node" and r["node_id"] is None


@pytest.mark.parametrize("make", [LinUCB, SlidingWindowLinUCB])
def test_the_bandit_gets_exactly_one_feedback_per_decision(make):
    policy = make()
    result = simulate(policy, "s6_outage_recovery", 1, cluster=CLUSTER)
    assert policy.stats["decisions"] == policy.stats["updates"] == result.stats["routed"]
    assert policy.stats["ignored_feedback"] == 0 and policy.pending_count == 0
    assert policy.stats["reward_mismatch"] == 0  # the stand-in fills outcome.reward with the policy's own reward


def test_logged_reward_is_the_reward_the_bandit_learned_from():
    class Spy(LinUCB):
        def __init__(self):
            super().__init__()
            self.learned = {}

        def update(self, request, node_id, outcome):
            super().update(request, node_id, outcome)
            self.learned[request["request_id"]] = self.last_reward

    spy = Spy()
    rows = simulate(spy, "s1_stable", 2, cluster=CLUSTER).rows
    for r in rows:
        if r["decision"] == "route":
            assert r["reward"] == pytest.approx(spy.learned[r["request_id"]])


def _fingerprint(scenario: str, seed: int) -> str:
    """Hash of a run's decision log and the learned sliding-window state."""
    import hashlib

    policy = SlidingWindowLinUCB()
    records = simulate(policy, scenario, seed, cluster=CLUSTER).records
    digest = hashlib.sha256(repr(records).encode())
    for node_id in sorted(policy._models):
        digest.update(policy._models[node_id].A.tobytes() + policy._models[node_id].b.tobytes())
    return digest.hexdigest()


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_same_seed_gives_identical_runs(scenario):
    assert _fingerprint(scenario, 5) == _fingerprint(scenario, 5)


def test_same_seed_gives_identical_runs_in_separate_processes():
    """The sweep runs each job in its own process; results must not depend on which one (e.g. set order)."""
    import subprocess
    import sys

    code = (
        "import sys; sys.path[:0] = {paths!r}; "
        "from test_toy_cluster import _fingerprint; print(_fingerprint('s6_outage_recovery', 2))"
    )
    paths = [os.path.dirname(os.path.abspath(__file__)), SUR_DIR, os.path.join(os.path.dirname(SUR_DIR), "Jyotir")]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    runs = {
        subprocess.run(
            [sys.executable, "-c", code.format(paths=paths)],
            capture_output=True,
            text=True,
            check=True,
            env={**env, "PYTHONHASHSEED": str(h)},
        ).stdout.strip()
        for h in (1, 2, 3)
    }
    assert len(runs) == 1 and next(iter(runs))


def test_a_policy_that_ignores_the_filter_is_stopped():
    class Rogue(Recorder):
        def choose(self, request, candidates):
            return "ap-south-1-does-not-exist"

    with pytest.raises(SafetyViolation):
        simulate(Rogue(), "s1_stable", 0, cluster=CLUSTER)


# ── scenarios change what the router sees ────────────────────────────────────


def _seen(scenario, seed=0):
    rec = Recorder()
    simulate(rec, scenario, seed, cluster=CLUSTER)
    return rec


def test_s6_node_is_unavailable_during_the_outage_then_warming():
    rec = _seen("s6_outage_recovery")
    for t, candidates in rec.seen:
        ids = {c["node_id"]: c for c in candidates}
        if 60 <= t < 150:
            assert "us-east-1" not in ids
        elif 150 <= t < 180 and "us-east-1" in ids:
            assert ids["us-east-1"]["status"] == "warming" and ids["us-east-1"].get("_warming")
        elif t >= 180 and "us-east-1" in ids:
            assert ids["us-east-1"]["status"] == "up"


def test_s6_requests_on_the_failed_node_come_back_as_failures():
    result = simulate(Recorder(), "s6_outage_recovery", 0, cluster=CLUSTER)  # Recorder loads us-east-1 first
    assert result.stats["failed"] > 0
    lost = [r for r in result.rows if r["decision"] == "route" and r["ttft_ms"] == float("inf")]
    assert len(lost) == result.stats["failed"] and not any(r["slo_met"] for r in lost)


def test_s5_raises_the_delay_to_one_node():
    rec = _seen("s5_network_degradation")
    rtts = {(t >= 60): c["rtt_ms"]["nyc"] for t, cs in rec.seen for c in cs if c["node_id"] == "us-east-1"}
    assert rtts[True] - rtts[False] == pytest.approx(80)


def test_s3_changes_prices_at_t0():
    rec = _seen("s3_price_shift")
    prices = {(t >= 60, c["node_id"]): c["energy_price_usd_kwh"] for t, cs in rec.seen for c in cs}
    assert prices[True, "us-west-1"] == pytest.approx(prices[False, "us-west-1"] * 0.3)
    assert prices[True, "us-central-1"] == pytest.approx(prices[False, "us-central-1"] * 4.0)


def test_s4_heats_up_the_node():
    rec = _seen("s4_thermal_throttle")
    temps = [(t, c["temperature_c"]) for t, cs in rec.seen for c in cs if c["node_id"] == "us-east-1"]
    before = max(temp for t, temp in temps if t < 60)
    later = max(temp for t, temp in temps if t >= 60)
    assert later > before + 10


# ── safety audit ─────────────────────────────────────────────────────────────


def test_hard_rule_recheck_matches_the_filter_rules():
    limits = {
        "temperature_limit_c": 85.0,
        "power_headroom_min_kw": 2.0,
        "kv_cache_max_frac": 0.9,
        "allow_warming_nodes": True,
    }
    assert _hard_rule_problems(make_request(), make_node(), limits) == []
    bad = make_node(
        status="warming", temperature_c=99.0, kv_used_frac=0.95, power_headroom_kw=0.5, models_loaded=["llama-3-70b"]
    )
    assert _hard_rule_problems(make_request(), bad, limits) == [
        "model_missing",
        "memory_full",
        "power_limit",
        "temperature_high",
    ]
    assert _hard_rule_problems(make_request(), make_node(status="down"), limits) == ["status=down"]


@pytest.mark.parametrize("scenario", SCENARIOS[:5])
def test_no_hard_rule_is_broken_in_s1_to_s5(scenario):
    for make in (LinUCB, SlidingWindowLinUCB):
        assert simulate(make(), scenario, 0, cluster=CLUSTER).stats["hard_rule_violations"] == 0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known bug in Jyotir's filter: a node with status 'warming' skips the model, memory, power and "
        "temperature checks (filter.py, rule 1 returns early), so a full warming node is still allowed. "
        "When the filter is fixed this test passes and strict=True turns that into a failure: remove this marker."
    ),
)
def test_s6_warming_node_respects_hard_rules():
    from baselines import MinRTT

    cluster = short_cluster(rate=120.0)  # enough traffic to fill the warming node's KV cache
    assert simulate(MinRTT(), "s6_outage_recovery", 0, cluster=cluster).stats["hard_rule_violations"] == 0


def test_no_context_ablation_runs_through_the_whole_loop():
    policy = SlidingWindowLinUCB(load_yaml("sw_linucb_no_context.yaml"))
    result = simulate(policy, "s2_traffic_burst", 0, cluster=CLUSTER)
    assert policy.dim == 1 and policy.stats["updates"] == result.stats["routed"]


def test_latency_energy_and_cost_follow_the_brief_formulas_exactly():
    """
    At very low load nothing queues and nothing heats up, so every request must have exactly
      TTFT = network + prefill,  prefill = a_p + b_p · input_tokens            (brief §5, no queue wait)
      decode = e2e − TTFT  within  out · t_tok · (1 + c · k/capacity) for k = 1..capacity
      energy = power_per_running · service_time,  cost = energy · price + GPU rent share
    """
    cfg = yaml.safe_load(yaml.safe_dump(FULL))
    cfg["duration_s"], cfg["t0_s"] = 300, 60
    cfg["workload"]["base_rate_rps"] = 2.0
    cfg["scenarios"]["s2_traffic_burst"]["duration_s"] = 60
    cfg["scenarios"]["s6_outage_recovery"].update({"return_s": 150, "warmup_s": 30})
    cluster = ClusterConfig.model_validate(cfg)
    specs = {n.node_id: n for n in cluster.nodes}
    requests = {r["request_id"]: r for r in generate_workload(cluster, "s1_stable", 4)}
    rows = simulate(LinUCB(), "s1_stable", 4, cluster=cluster).rows
    assert len(rows) == len(requests) > 300
    for row in rows:
        req, s = requests[row["request_id"]], specs[row["node_id"]]
        rtt = s.rtt_ms[req["user_region"]]
        prefill = s.prefill_a_ms + s.prefill_b_ms_per_token * req["input_tokens"]
        assert row["ttft_ms"] == pytest.approx(rtt + prefill, abs=1e-9)
        decode = row["e2e_ms"] - row["ttft_ms"]
        base = req["expected_output_tokens"] * s.t_tok_ms
        assert base * (1 + s.decode_c / s.capacity) - 1e-9 <= decode <= base * (1 + s.decode_c) + 1e-9
        service_h = (prefill + decode) / 1000 / 3600
        assert row["energy_kwh"] == pytest.approx(s.power_per_running_kw * service_h, rel=1e-12)
        expected_cost = row["energy_kwh"] * s.energy_price_usd_kwh + s.gpu_price_usd_hr * service_h / s.capacity
        assert row["cost_usd"] == pytest.approx(expected_cost, rel=1e-12)
        assert row["slo_met"] == (row["ttft_ms"] <= req["ttft_slo_ms"])


def test_scenario_changes_happen_exactly_when_the_config_says():
    rec = _seen("s6_outage_recovery")
    times_with_node = sorted(t for t, cs in rec.seen if any(c["node_id"] == "us-east-1" for c in cs))
    assert max(t for t in times_with_node if t < 150) < 60  # gone from t0 = 60 ...
    assert min(t for t in times_with_node if t >= 60) >= 150  # ... until return_s = 150
    s5 = _seen("s5_network_degradation")
    for t, cs in s5.seen:
        for c in cs:
            if c["node_id"] == "us-east-1":
                assert c["rtt_ms"]["nyc"] == (12 + 80 if t >= 60 else 12)
