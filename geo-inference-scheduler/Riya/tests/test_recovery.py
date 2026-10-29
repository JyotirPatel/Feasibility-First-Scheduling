"""Recovery definitions are scientific outputs; test them against the signed spec and Sur."""

import sys
from pathlib import Path
import importlib.util
import numpy as np
import pandas as pd
import pytest

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / "metrics"))
sys.path.insert(0, str(R / "experiment_runner"))
from recovery import recovery_metrics, goodput_curve
from summarize_results import interval

spec = importlib.util.spec_from_file_location(
    "sur_adaptation", R.parent / "Sur/standins/adaptation.py"
)
sur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sur)


def frame(g):
    return pd.DataFrame({"time_s": np.arange(len(g)), "smoothed_goodput_rps": g})


def test_arrival_time_not_completion_time():
    df = pd.DataFrame(
        {
            "t_arrival": [0.1, 1.1, 1.9],
            "t_complete": [4.0, 4.0, 4.0],
            "slo_met": [True, True, False],
        }
    )
    c = goodput_curve(df, 5)
    assert c.goodput_rps.tolist() == [1, 1, 0, 0, 0]
    np.testing.assert_allclose(c.smoothed_goodput_rps, sur.smooth([1, 1, 0, 0, 0], 5))


@pytest.mark.parametrize("seed", range(10))
def test_matches_sur_definition(seed):
    g = sur.smooth(np.random.default_rng(seed).poisson(50, size=600), 5)
    expected, gs = sur.adaptation_time(
        g, 200, bin_s=1, steady_from_s=60, steady_to_s=120, fraction=0.9, hold_s=10
    )
    r = recovery_metrics(pd.DataFrame(), frame(g), 200, "t0")
    assert r["adaptation_time_s"] == expected
    assert r["steady_goodput_rps"] == gs
    assert r["deepest_dip_rps"] == sur.deepest_dip(g, 200, bin_s=1, until_s=120)


def test_hold_must_last_ten_seconds():
    g = np.full(600, 10.0)
    g[200:220] = 0
    g[205:214] = 10  # only nine bins
    r = recovery_metrics(pd.DataFrame(), frame(g), 200, "t0")
    assert r["adaptation_time_s"] == 20


def test_non_recovery_is_null():
    g = np.zeros(600)
    g[260:320:2] = 20
    r = recovery_metrics(pd.DataFrame(), frame(g), 200, "t0")
    assert r["adaptation_time_s"] is None
    assert r["recovery_status"] == "did not recover"


def test_s6_return_and_traffic_share():
    df = pd.DataFrame(
        {"t_arrival": [399, 401, 470, 471], "node_id": ["a", "b", "a", "b"]}
    )
    r = recovery_metrics(df, frame(np.ones(600)), 400, "return", ["a"])
    assert r["t0_s"] == 400
    assert r["node_traffic_shares"]["a"]["steady_arrival_share"] == 0.5
    assert r["node_traffic_shares"]["a"]["first_120s_arrival_share"] == pytest.approx(
        1 / 3
    )


def test_zero_steady_flag_and_missing_oracle():
    r = recovery_metrics(pd.DataFrame(), frame(np.zeros(600)), 200, "t0", control=True)
    assert r["adaptation_time_s"] == 0
    assert r["zero_steady_goodput"]
    assert r["lost_goodput_requests"] is None
    assert r["is_control"]


def test_oracle_positive_gap_and_alignment():
    actual = frame(np.full(600, 8.0))
    oracle = frame(np.full(600, 10.0))
    assert (
        recovery_metrics(pd.DataFrame(), actual, 200, "t0", oracle_curve=oracle)[
            "lost_goodput_requests"
        ]
        == 240
    )
    oracle.time_s += 1
    with pytest.raises(ValueError):
        recovery_metrics(pd.DataFrame(), actual, 200, "t0", oracle_curve=oracle)


def test_no_ci_from_one_seed():
    assert (
        interval([2.0], np.random.default_rng(0))["ci_status"] == "insufficient_seeds"
    )
    r = interval([2.0] * 10, np.random.default_rng(0))
    assert (r["mean"], r["ci_low"], r["ci_high"]) == (2, 2, 2)


def test_missing_steady_window_is_error():
    with pytest.raises(ValueError):
        recovery_metrics(pd.DataFrame(), frame(np.ones(500)), 400, "return")
