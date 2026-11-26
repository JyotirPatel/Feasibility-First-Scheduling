"""Tests for the stand-in goodput / adaptation-time metric (standins/adaptation.py)."""

import numpy as np
import pytest

from standins.adaptation import adaptation_time, deepest_dip, goodput_series, smooth, steady_level

FROZEN = {"bin_s": 1.0, "steady_from_s": 60, "steady_to_s": 120, "fraction": 0.9, "hold_s": 10}
T0 = 200


def test_goodput_counts_slo_met_requests_per_bin_by_arrival_time():
    t = [0.1, 0.5, 0.9, 1.2, 2.5, 2.6, 7.0]
    met = [True, False, True, True, True, False, True]
    # 7.0 is after the end of the run and is not counted
    np.testing.assert_array_equal(goodput_series(t, met, duration_s=4, bin_s=1.0), [2, 1, 1, 0])
    np.testing.assert_array_equal(goodput_series(t, met, duration_s=4, bin_s=2.0), [1.5, 0.5])  # per second


def test_trailing_moving_average():
    np.testing.assert_allclose(smooth(np.array([5, 10, 15, 20, 25, 30.0]), 3), [5, 7.5, 10, 15, 20, 25])
    np.testing.assert_array_equal(smooth(np.array([1.0, 2.0]), 1), [1.0, 2.0])
    with pytest.raises(ValueError):
        smooth(np.ones(3), 0)


def series(fn, n=600):
    return np.array([fn(i) for i in range(n)], dtype=float)


def test_no_change_means_zero_adaptation_time():
    a, g_star = adaptation_time(series(lambda i: 100.0), T0, **FROZEN)
    assert (a, g_star) == (0.0, 100.0)


def test_a_dip_then_recovery_is_measured_from_t0():
    G = series(lambda i: 20.0 if T0 <= i < T0 + 15 else 100.0)
    a, g_star = adaptation_time(G, T0, **FROZEN)
    assert (a, g_star) == (15.0, 100.0)
    assert deepest_dip(G, T0, bin_s=1.0, until_s=120) == 20.0


def test_a_short_blip_does_not_count_as_recovered():
    # 5 good seconds inside the dip are shorter than the 10-second hold
    G = series(lambda i: 100.0 if (i < T0 or T0 + 5 <= i < T0 + 10 or i >= T0 + 30) else 20.0)
    a, _ = adaptation_time(G, T0, **FROZEN)
    assert a == 30.0


def test_settling_lower_is_judged_against_the_new_level():
    # a weak policy that settles at half the old goodput "recovers" at once: G* exposes it
    a, g_star = adaptation_time(series(lambda i: 100.0 if i < T0 else 50.0), T0, **FROZEN)
    assert (a, g_star) == (0.0, 50.0)


def test_never_holding_the_level_is_did_not_recover():
    G = series(lambda i: 100.0 if i < T0 or (i // 5) % 2 == 0 else 0.0)  # flips every 5 s after t0
    a, g_star = adaptation_time(G, T0, **FROZEN)
    assert a is None
    assert g_star == pytest.approx(50.0)


def test_steady_window_must_fit_in_the_run():
    with pytest.raises(ValueError):
        steady_level(np.ones(250), T0, 1.0, 60, 120)
