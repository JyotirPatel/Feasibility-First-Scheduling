"""Frozen recovery metric, using arrival-time bins like Sur's window sweep.

One-second bins, trailing 5-second mean (partial means at the start), G* in
[t0+60,t0+120), first qualifying 10 bins in [t0,end). S1 is a pseudo-event
control. Recovery search continues to the end; dip uses [t0,t0+120).
"""

import numpy as np
import pandas as pd


def goodput_curve(df, duration_s):
    if duration_s <= 0 or duration_s != int(duration_s):
        raise ValueError("duration must be positive whole seconds")
    met = df.slo_met.astype(str).str.lower().eq("true")
    t = pd.to_numeric(df.t_arrival, errors="raise")
    if not np.isfinite(t).all() or ((t < 0) | (t >= duration_s)).any():
        raise ValueError("arrivals outside observation interval")
    counts = np.bincount(np.floor(t[met]).astype(int), minlength=int(duration_s))
    curve = pd.DataFrame(
        {"time_s": np.arange(int(duration_s)), "goodput_rps": counts.astype(float)}
    )
    curve["smoothed_goodput_rps"] = curve.goodput_rps.rolling(5, min_periods=1).mean()
    return curve


def recovery_metrics(
    df, curve, t0, anchor, affected_nodes=(), control=False, oracle_curve=None
):
    """Do not invent lost goodput without a matched oracle curve.

    Node shares use all arrivals as denominator (rejections stay in denominator).
    Store shares both in the first 120 s and in the same steady window as G*.
    """
    if t0 != int(t0) or t0 < 0 or t0 + 120 > len(curve):
        raise ValueError("event and full steady window must fit the 1-second curve")
    t0 = int(t0)
    g = curve.smoothed_goodput_rps.to_numpy(dtype=float)
    gstar = float(g[t0 + 60 : t0 + 120].mean())
    delay = None
    status = "did not recover"
    # Follow the frozen threshold literally, including a zero G*. Flag its
    # weak steady level explicitly so a numerical delay cannot imply usefulness.
    for i in range(t0, len(g) - 10 + 1):
        if (g[i : i + 10] >= 0.9 * gstar).all():
            delay = float(i - t0)
            status = "recovered"
            break
    result = {
        "anchor": anchor,
        "t0_s": t0,
        "is_control": control,
        "adaptation_time_s": delay,
        "recovery_status": status,
        "steady_goodput_rps": gstar,
        "threshold_rps": 0.9 * gstar,
        "zero_steady_goodput": gstar == 0,
        "deepest_dip_rps": float(g[t0 : t0 + 120].min()),
        "recovery_search_end_s": len(g),
        "recovery_window_end_s": t0 + 120,
        "lost_goodput_requests": None,
        "lost_goodput_status": "unavailable: matched oracle required",
        "node_traffic_shares": {},
    }
    if control:
        result["interpretation"] = "pseudo-event noise diagnostic; no actual change"
    for node in affected_nodes:
        shares = {}
        for name, a, b in [
            ("pre_event", max(0, t0 - 60), t0),
            ("first_120s", t0, t0 + 120),
            ("steady", t0 + 60, t0 + 120),
        ]:
            subset = df.loc[(df.t_arrival >= a) & (df.t_arrival < b)]
            shares[name + "_arrival_share"] = (
                float(subset.node_id.eq(node).mean()) if len(subset) else None
            )
            shares[name + "_requests"] = int(subset.node_id.eq(node).sum())
            shares[name + "_all_arrivals"] = len(subset)
        result["node_traffic_shares"][node] = shares
    if oracle_curve is not None:
        if not np.array_equal(curve.time_s, oracle_curve.time_s):
            raise ValueError("oracle and policy must have identical time bins")
        # Positive-part area over a fixed 120-second window; no cancellation by overshoot.
        gap = oracle_curve.smoothed_goodput_rps.to_numpy() - g
        result["lost_goodput_requests"] = float(np.maximum(gap[t0 : t0 + 120], 0).sum())
        result["lost_goodput_status"] = "matched oracle, positive area over [t0,t0+120)"
    return result
