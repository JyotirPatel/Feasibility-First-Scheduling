"""
Goodput and adaptation time — owner: Sur (TEMPORARY stand-in for Riya's metrics code)

Implements the definitions frozen in the work distribution §6 / brief §8, so
the window sweep can report numbers before Riya's evaluation code exists:

  Goodput G(t): requests per second that met their SLO, in 1-second bins,
                smoothed with a 5-second moving average.
  Adaptation time, for a change at t0:
    1. G* = the average of G(t) from t0 + 60 s to t0 + 120 s (new steady level).
    2. Adaptation time = (first t ≥ t0 where G(t) ≥ 0.9 · G* and stays there
       for 10 s in a row) − t0.
    3. If that never happens: "did not recover" (None here), not a number.
    4. Always report G* next to it.
  Deepest dip: the lowest G(t) between t0 and t0 + 120 s.

Choices the definition leaves open, made here and easy to change:
  - a request counts in the bin of its arrival time (its decision moment);
  - the 5-second average is trailing (uses the current and the 4 previous bins).

The numbers (bin, smoothing, 60–120 s, 90 %, 10 s) are passed in from
window_sweep/sweep.yaml, not fixed in this file. Lost goodput needs Riya's
oracle policy, so it is not computed here.
"""

from __future__ import annotations

import math

import numpy as np


def goodput_series(t_arrival, slo_met, duration_s: float, bin_s: float) -> np.ndarray:
    """SLO-met requests per second in each bin of [0, duration_s), by arrival time."""
    t = np.asarray(t_arrival, dtype=float)
    met = np.asarray(slo_met, dtype=bool)
    n_bins = int(math.ceil(duration_s / bin_s))
    idx = np.floor(t[met] / bin_s).astype(int)
    idx = idx[(idx >= 0) & (idx < n_bins)]
    return np.bincount(idx, minlength=n_bins).astype(float) / bin_s


def smooth(series: np.ndarray, window_bins: int) -> np.ndarray:
    """Trailing moving average; the first bins average over what exists so far."""
    if window_bins < 1:
        raise ValueError("window_bins must be >= 1")
    s = np.asarray(series, dtype=float)
    csum = np.concatenate([[0.0], np.cumsum(s)])
    i = np.arange(1, len(s) + 1)
    lo = np.maximum(i - window_bins, 0)
    return (csum[i] - csum[lo]) / (i - lo)


def steady_level(G: np.ndarray, t0: float, bin_s: float, steady_from_s: float, steady_to_s: float) -> float:
    """G* = mean of G over [t0 + steady_from_s, t0 + steady_to_s)."""
    a, b = _bin(t0 + steady_from_s, bin_s), _bin(t0 + steady_to_s, bin_s)
    if b > len(G) or a >= b:
        raise ValueError("the steady window does not fit inside the run")
    return float(np.mean(G[a:b]))


def adaptation_time(
    G: np.ndarray, t0: float, *, bin_s: float, steady_from_s: float, steady_to_s: float, fraction: float, hold_s: float
) -> tuple[float | None, float]:
    """(adaptation time in seconds or None if it did not recover, G*)."""
    g_star = steady_level(G, t0, bin_s, steady_from_s, steady_to_s)
    threshold = fraction * g_star
    hold = max(int(round(hold_s / bin_s)), 1)
    ok = threshold <= G
    start = _bin(t0, bin_s)
    for i in range(start, len(G) - hold + 1):
        if ok[i : i + hold].all():
            return (i - start) * bin_s, g_star
    return None, g_star


def deepest_dip(G: np.ndarray, t0: float, *, bin_s: float, until_s: float) -> float:
    """Lowest G between t0 and t0 + until_s."""
    a, b = _bin(t0, bin_s), min(_bin(t0 + until_s, bin_s), len(G))
    return float(np.min(G[a:b]))


def _bin(t: float, bin_s: float) -> int:
    return int(round(t / bin_s))
