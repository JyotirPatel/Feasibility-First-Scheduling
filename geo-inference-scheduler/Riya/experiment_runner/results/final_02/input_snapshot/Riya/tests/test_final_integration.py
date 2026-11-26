import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / "experiment_runner"))
from compare_sources import compare
from run_evaluation import (
    source_files,
    resolve_policy,
    validate_config,
    bundle_hashes,
    verify_cached,
)
from true_state_reference import TrueStatePolicy, immediate_candidates


def test_source_paths_and_crlf(tmp_path):
    p = tmp_path / "Owner"
    p.mkdir()
    (p / "x.py").write_bytes(b"a\nb\n")
    h = hashlib.sha256(b"a\r\nb\r\n").hexdigest()
    assert compare({"source_sha256": {"Owner\\x.py": h}}, tmp_path) == [
        {"path": "Owner/x.py", "status": "line_endings_only"}
    ]
    (p / "x.py").write_text("changed")
    assert (
        compare({"source_sha256": {"Owner\\x.py": h}}, tmp_path)[0]["status"]
        == "content_changed"
    )


def test_generated_results_not_snapshotted(tmp_path):
    for rel in [
        "Jyotir/baseline_logs/decision_log.csv",
        "Sur/window_sweep/results_standin/summary.csv",
        "Riya/experiment_runner/results/x.py",
        "Parikshit/data/processed/azure_conv.csv.gz",
        "Riya/metrics/evaluate.py",
    ]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("example")
    assert {p.relative_to(tmp_path).as_posix() for p in source_files(tmp_path)} == {
        "Parikshit/data/processed/azure_conv.csv.gz",
        "Riya/metrics/evaluate.py",
    }


def test_no_filter_is_explicit_and_default_still_filters():
    cfg = {
        "policy_overrides": {
            "ablation:no_filter": {"implementation": "sur:sw_linucb", "filter": "none"}
        }
    }
    assert resolve_policy("ablation:no_filter", cfg) == ("sur:sw_linucb", "none")
    assert resolve_policy("sur:sw_linucb", cfg) == ("sur:sw_linucb", "jyotir")


def test_bad_filter_name_rejected():
    cfg = json.loads((R / "experiment_runner/config_final_validation.json").read_text())
    cfg["filter_name"] = "passthrough"
    with pytest.raises(ValueError, match="filter"):
        validate_config(cfg)


def test_cache_tamper_is_detected(tmp_path):
    (tmp_path / "metrics.json").write_text('{"requests":1}')
    hashes = bundle_hashes(tmp_path)
    (tmp_path / "status.json").write_text(
        json.dumps({"status": "ok", "bundle_sha256": hashes})
    )
    assert verify_cached(tmp_path) == {"requests": 1}
    (tmp_path / "metrics.json").write_text('{"requests":2}')
    with pytest.raises(ValueError, match="modified"):
        verify_cached(tmp_path)


def test_true_state_reference_uses_request_size_and_actual_admission():
    def node(a, b, rtt):
        return NS(
            consts=NS(a_p_ms=a, b_p_ms_per_token=b),
            rtt_to=lambda _: rtt,
            slowdown=lambda _: 1.0,
            running=[],
            capacity=2,
            queue=[],
            kv_used=0,
            kv_capacity=1000,
        )

    slow = node(20, 0.5, 1)
    fast = node(50, 0.01, 20)
    sim = NS(nodes={"slow": slow, "fast": fast}, env=NS(now=0))
    model = TrueStatePolicy()
    model.simulation = sim
    cs = [NS(node_id="slow"), NS(node_id="fast")]
    assert model.choose(NS(input_tokens=500, user_region="x"), cs) == "fast"
    assert model.choose(NS(input_tokens=1, user_region="x"), cs) == "slow"
    fast.running = [1, 2]
    allowed, rejected = immediate_candidates(NS(), cs, sim, 100)
    assert [c.node_id for c in allowed] == ["slow"]
    assert rejected["fast"] == "reference_no_immediate_slot"
    allowed, _ = immediate_candidates(NS(), cs, sim, 1001)
    assert not allowed


@pytest.mark.parametrize("missing_on_failed", [False, True])
def test_rejected_resources_are_zero_but_failed_unknowns_stay_unknown(
    missing_on_failed,
):
    import pandas as pd
    from evaluate_log import evaluate

    df = pd.DataFrame(
        {
            "request_id": ["a", "b"],
            "decision": ["route", "reject"],
            "outcome_status": ["ok", "rejected"],
            "slo_met": [True, False],
            "ttft_ms": [10, None],
            "e2e_ms": [20, None],
            "t_arrival": [0, 1],
            "t_complete": [0.02, None],
            "cost_usd": [2.0, None],
            "energy_kwh": [1.0, None],
            "reject_reason": [None, "no_feasible_node"],
            "constraint_violation": [None, None],
        }
    )
    if missing_on_failed:
        df.loc[0, ["outcome_status", "slo_met", "cost_usd", "energy_kwh"]] = [
            "failed",
            False,
            None,
            None,
        ]
    result = evaluate(df, 2)
    if missing_on_failed:
        assert result["total_cost_usd"] is None
    else:
        assert result["total_cost_usd"] == 2.0
        assert result["total_energy_kwh"] == 1.0
        assert result["cost_usd_coverage"] == 0.5
        assert result["cost_usd_accounted_coverage"] == 1.0
