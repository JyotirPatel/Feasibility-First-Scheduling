"""Tests for the checks on Riya's final evaluation (window_sweep/final_eval_check.py)."""

import os

import numpy as np
import pandas as pd
import pytest

from standins.adaptation import adaptation_time
from window_sweep.final_eval_check import (
    DEFAULT_BUNDLE,
    first_hold,
    gaps_after_change,
    nyc_shares,
    s6_outage_times,
    steady,
    sweep_against_final,
)


def curve(smoothed):
    g = np.asarray(smoothed, dtype=float)
    return pd.DataFrame({"time_s": np.arange(len(g)), "goodput_rps": g, "smoothed_goodput_rps": g})


def test_first_hold_with_the_frozen_bar_is_the_frozen_adaptation_time():
    g = np.full(600, 70.0)
    g[200:215] = 30.0  # the change knocks goodput down ...
    g[215:230] = np.linspace(40.0, 72.0, 15)  # ... and it climbs back
    g[230:] = 72.0
    g[233] = 50.0  # a one-bin wobble restarts the 10-bin hold
    expected, g_star = adaptation_time(
        g, 200.0, bin_s=1.0, steady_from_s=60.0, steady_to_s=120.0, fraction=0.9, hold_s=10.0
    )
    c = curve(g)
    assert steady(c, 200.0) == pytest.approx(g_star)
    assert first_hold(c, 200.0, 0.9 * g_star) == expected == 34.0


def test_first_hold_needs_the_whole_hold():
    g = np.full(600, 10.0)
    g[300:309] = 80.0  # 9 bins above the bar: not a recovery
    assert first_hold(curve(g), 200.0, 50.0) is None
    g[400:410] = 80.0  # 10 bins: recovered 200 s after t0
    assert first_hold(curve(g), 200.0, 50.0) == 200.0


bundle_missing = not os.path.exists(os.path.join(DEFAULT_BUNDLE, "node_traffic_shares.csv"))


@pytest.mark.skipif(bundle_missing, reason="Riya's final_02 bundle is not in this checkout")
def test_jyotirs_filter_fix_changed_no_sweep_run():
    # the sweep ran before Jyotir's kv_cache_max_frac fix (5e3b1a6), the final evaluation after it
    check = sweep_against_final(DEFAULT_BUNDLE)
    assert list(check.index) == ["sur:sw_linucb", "sur:linucb"]
    assert (check["runs compared"] == 60).all()
    assert (check["runs with other request counts"] == 0).all()
    assert (check["runs with other SLO-met counts"] == 0).all()


@pytest.mark.skipif(bundle_missing, reason="Riya's final_02 bundle is not in this checkout")
def test_the_final_bundle_supports_the_notes():
    # the S6 times in Riya's report, and the same times against one shared bar
    mean = s6_outage_times(DEFAULT_BUNDLE).mean()
    assert (round(mean["full: own bar"], 1), round(mean["plain: own bar"], 1)) == (18.3, 9.9)
    assert (round(mean["full: shared bar"], 1), round(mean["plain: shared bar"], 1)) == (10.9, 9.9)
    # in S4 and S5 the no-context advantage comes from seeds 3, 8 and 9 only ...
    gaps = gaps_after_change(DEFAULT_BUNDLE)
    losing = [3, 8, 9]
    for s in ("s4_thermal_throttle", "s5_network_degradation"):
        assert (gaps.loc[losing, s] < -3).all()
        assert gaps[s].drop(losing).abs().max() < 0.3
    # ... the seeds where the full policy had put most traffic on New York before the change
    before = nyc_shares(DEFAULT_BUNDLE)["full: before"]
    assert (before[losing] > 70).all() and (before.drop(losing) < 28).all()
