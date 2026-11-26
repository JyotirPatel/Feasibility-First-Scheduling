"""simulator/run_scenario.py: one run through Krupesh's router, its summary, its files and its exit codes."""

import json

import simulator.run_scenario as rs

RATE = 5.0  # requests/s: the full 600-s scenarios, light enough to run in about a second


def test_run_gives_a_valid_log_and_the_policys_counts():
    summary, log = rs.run("s6_outage_recovery", "sur:sw_linucb", 0, rate_rps=RATE)
    assert summary["log_problems"] == [] and summary["reward"] == "sur" and summary["rate_rps"] == RATE
    assert len(log) == summary["simulation"]["requests"] and summary["simulation"]["failed"] > 0
    stats = summary["policy_stats"]
    assert stats["reward_mismatch"] == 0 and stats["updates"] == summary["simulation"]["routed"]


def test_a_reward_disagreement_makes_the_log_invalid(monkeypatch):
    real = rs.krupesh_engine

    def with_another_reward(*args, **kwargs):
        engine, name = real(*args, **kwargs)
        engine.reward_fn = lambda outcome, node: 0.123  # not the reward the policy learns from
        return engine, name

    monkeypatch.setattr(rs, "krupesh_engine", with_another_reward)
    summary, _ = rs.run("s1_stable", "sur:sw_linucb", 0, rate_rps=RATE)
    assert summary["policy_stats"]["reward_mismatch"] > 0
    assert any("rewards disagree" in p for p in summary["log_problems"])


def test_main_writes_the_decision_log_and_the_summary(tmp_path, capsys):
    out = tmp_path / "run"
    args = ["--scenario", "s1_stable", "--policy", "jyotir:least_load", "--rate", str(RATE), "--out-dir", str(out)]
    assert rs.main(args) == 0
    summary = json.loads((out / "run_summary.json").read_text())
    assert summary["status"] == "ok" and (out / summary["decision_log"]).is_file()
    assert set(summary["configs_sha256"]) == {
        "configs/nodes_5.yaml",
        "configs/workload.yaml",
        "configs/calibration.yaml",
        "event_traces/s1_stable.yaml",
    }
    assert '"status": "ok"' in capsys.readouterr().out


def test_main_reports_a_failed_run_with_exit_code_1(tmp_path):
    out = tmp_path / "run"
    assert rs.main(["--policy", "no_such_policy", "--rate", str(RATE), "--out-dir", str(out)]) == 1
    summary = json.loads((out / "run_summary.json").read_text())
    assert summary["status"] == "failed" and "no_such_policy" in summary["error"]
