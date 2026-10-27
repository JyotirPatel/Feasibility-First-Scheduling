"""
Independent cross-checks: each production function is compared with a separate,
deliberately simple re-implementation on many random inputs. A disagreement means
one of the two is wrong, so these tests do not rely on the production code's own logic.
"""

import math

import numpy as np
import pytest

from context_vector import ContextBuilder
from reward import compute_reward
from sliding_window_linucb import SlidingWindowLinUCB
from standins.adaptation import adaptation_time, goodput_series, smooth
from sur_factories import load_yaml, make_node, make_outcome, make_request

FEATURES = load_yaml("sw_linucb.yaml")["features"]
REWARD = load_yaml("sw_linucb.yaml")["reward"]


# ── context vector ───────────────────────────────────────────────────────────


def reference_features(req, node, cfg):
    rng = cfg["ranges"]

    def scaled(value, name):
        lo, hi = rng[name]["min"], rng[name]["max"]
        if value == math.inf:
            return 1.0
        return min(1.0, max(0.0, (value - lo) / (hi - lo)))

    rtts = node["rtt_ms"]
    region = req.get("user_region")
    if region in rtts:
        rtt = rtts[region]
    elif rtts:
        rtt = sum(rtts.values()) / len(rtts)
    else:
        rtt = math.inf
    slo = req["ttft_slo_ms"] if "ttft_slo_ms" in req else req["slo_ms"]
    warming = node.get("status") == "warming" or bool(node.get("_warming", False))
    return [
        1.0,
        scaled(req["input_tokens"], "input_tokens"),
        scaled(req["expected_output_tokens"], "expected_output_tokens"),
        *[1.0 if req.get("slo_class") == c else 0.0 for c in cfg["slo_classes"]],
        scaled(slo, "ttft_slo_ms"),
        scaled(rtt, "rtt_ms"),
        scaled(node["queue_len"], "queue_len"),
        min(1.0, max(0.0, node["running"] / node["capacity"])),
        min(1.0, max(0.0, node["kv_used_frac"])),
        scaled(node["energy_price_usd_kwh"], "energy_price_usd_kwh"),
        scaled(node["gpu_price_usd_hr"], "gpu_price_usd_hr"),
        scaled(node["temperature_c"], "temperature_c"),
        1.0 if warming else 0.0,
    ]


def random_request_and_node(rng, i):
    regions = ["nyc", "chi", "sfo", "tokyo"]
    req = make_request(
        f"r-{i}",
        input_tokens=int(rng.integers(0, 20000)),
        expected_output_tokens=int(rng.integers(0, 5000)),
        slo_class=str(rng.choice(["interactive", "batch", "other"])),
        user_region=str(rng.choice(regions)),
        ttft_slo_ms=float(rng.uniform(1, 3000)),
    )
    if rng.random() < 0.3:  # Jyotir's stub spelling
        req["slo_ms"] = req.pop("ttft_slo_ms")
    if rng.random() < 0.1:
        del req["user_region"]
    rtt = {r: float(rng.uniform(0, 500)) for r in rng.choice(regions[:3], size=int(rng.integers(0, 4)), replace=False)}
    node = make_node(
        f"n-{i}",
        rtt_ms=rtt,
        queue_len=int(rng.integers(0, 200)),
        running=int(rng.integers(0, 600)),
        capacity=int(rng.integers(1, 512)),
        kv_used_frac=float(rng.uniform(-0.2, 1.2)),
        energy_price_usd_kwh=float(rng.uniform(-0.2, 1.0)),
        gpu_price_usd_hr=float(rng.uniform(0, 9)),
        temperature_c=float(rng.uniform(0, 130)),
        status=str(rng.choice(["up", "warming"])),
    )
    if rng.random() < 0.2:
        node["_warming"] = True
    return req, node


def test_context_vector_matches_an_independent_implementation():
    rng = np.random.default_rng(10)
    builder = ContextBuilder(FEATURES)
    for i in range(3000):
        req, node = random_request_and_node(rng, i)
        np.testing.assert_allclose(
            builder.build(req, node),
            reference_features(req, node, FEATURES),
            rtol=0,
            atol=1e-12,
            err_msg=f"case {i}: {req} {node}",
        )


# ── reward ───────────────────────────────────────────────────────────────────


def reference_reward(node, out, cfg):
    w = cfg["weights"]

    def clip(v):
        return min(1.0, max(0.0, v))

    def worst_if_unknown(v, scale):
        return 1.0 if v is None or not math.isfinite(v) else clip(v / scale)

    met = 1.0 if out["slo_met"] else 0.0
    latency = worst_if_unknown(out[cfg["latency_metric"]], cfg["latency_max_ms"])
    if cfg["energy_cost_source"] == "energy_usd":
        kwh = out["energy_kwh"]
        usd = None if kwh is None or not math.isfinite(kwh) else kwh * node["energy_price_usd_kwh"]
    else:
        usd = out["cost_usd"]
    energy = worst_if_unknown(usd, cfg["energy_cost_max_usd"])
    temp = node["temperature_c"]
    thermal = (
        1.0
        if not math.isfinite(temp)
        else clip((temp - cfg["thermal_safe_c"]) / (cfg["thermal_limit_c"] - cfg["thermal_safe_c"]))
    )
    return w["slo_met"] * met - w["latency"] * latency - w["energy_cost"] * energy - w["thermal_stress"] * thermal


@pytest.mark.parametrize(
    "variant",
    [
        {},
        {"latency_metric": "e2e_ms", "latency_max_ms": 20000.0},
        {"energy_cost_source": "cost_usd"},
        {"weights": {"slo_met": 2.0, "latency": 0.5, "energy_cost": 0.3, "thermal_stress": 0.7}},
    ],
)
def test_reward_matches_an_independent_implementation(variant):
    cfg = {**REWARD, **variant}
    rng = np.random.default_rng(11)
    for i in range(3000):
        node = make_node(temperature_c=float(rng.uniform(-30, 150)), energy_price_usd_kwh=float(rng.uniform(-0.3, 2.0)))
        pick = rng.random()
        out = make_outcome(
            slo_met=bool(rng.random() < 0.5),
            ttft_ms=None if pick < 0.05 else (math.inf if pick < 0.1 else float(rng.uniform(0, 4000))),
            e2e_ms=float(rng.uniform(0, 60000)),
            energy_kwh=math.nan if rng.random() < 0.05 else float(rng.uniform(0, 0.005)),
            cost_usd=float(rng.uniform(-0.0002, 0.002)),
        )
        assert compute_reward(node, out, cfg) == pytest.approx(reference_reward(node, out, cfg), abs=1e-12), i


# ── sliding window: compare with a brute-force rebuild after every outcome ───


@pytest.mark.parametrize("mode", ["per_node", "global"])
@pytest.mark.parametrize("size", [1, 2, 5, 17])
def test_sliding_window_matches_brute_force_after_every_outcome(mode, size):
    cfg = load_yaml("sw_linucb.yaml")
    cfg["window"] = {"size": size, "mode": mode, "rebuild_every": 7}
    policy = SlidingWindowLinUCB(cfg)
    lam, d = policy.lam, policy.dim
    rng = np.random.default_rng(size * 31 + (mode == "global"))
    history: list[tuple[str, np.ndarray, float]] = []
    nodes = ["a", "b", "c", "d"]
    for step in range(400):
        node_id = nodes[int(rng.choice(4, p=[0.55, 0.3, 0.1, 0.05]))]
        x, r = rng.random(d), float(rng.uniform(-0.4, 1.0))
        policy._learn(node_id, x, r)
        history.append((node_id, x, r))
        if mode == "global":
            window = history[-size:]
        else:
            window = [h for n in nodes for h in [e for e in history if e[0] == n][-size:]]
        for n in nodes:
            mine = [(x_, r_) for n_, x_, r_ in window if n_ == n]
            A = lam * np.eye(d) + sum((np.outer(x_, x_) for x_, _ in mine), np.zeros((d, d)))
            b = sum((r_ * x_ for x_, r_ in mine), np.zeros(d))
            if n in policy._models:
                model = policy._models[n]
                np.testing.assert_allclose(model.A, A, rtol=1e-9, atol=1e-9, err_msg=f"step {step} node {n}")
                np.testing.assert_allclose(model.b, b, rtol=1e-9, atol=1e-9, err_msg=f"step {step} node {n}")
                np.testing.assert_allclose(model.theta, np.linalg.solve(A, b), rtol=1e-7, atol=1e-9)
                assert model.n == len(mine)
            else:
                assert not mine


# ── goodput and adaptation time ──────────────────────────────────────────────


def reference_adaptation(G, t0, steady_from, steady_to, fraction, hold):
    g_star = sum(G[t0 + steady_from : t0 + steady_to]) / (steady_to - steady_from)
    for t in range(t0, len(G) - hold + 1):
        if all(G[t + k] >= fraction * g_star for k in range(hold)):
            return t - t0, g_star
    return None, g_star


def test_goodput_smoothing_and_adaptation_match_independent_implementations():
    rng = np.random.default_rng(12)
    for case in range(300):
        n_req = int(rng.integers(0, 3000))
        t = rng.uniform(-5, 610, size=n_req)
        met = rng.random(n_req) < rng.uniform(0.2, 1.0)
        raw = goodput_series(t, met, 600, 1.0)
        ref_raw = [0.0] * 600
        for ti, mi in zip(t, met, strict=True):
            if mi and 0 <= ti < 600:
                ref_raw[int(math.floor(ti))] += 1
        np.testing.assert_array_equal(raw, ref_raw)

        series = rng.uniform(0, 100, size=600) * (1 - 0.8 * (rng.random(600) < 0.2))
        smoothed = smooth(series, 5)
        ref_smooth = [float(np.mean(series[max(0, i - 4) : i + 1])) for i in range(600)]
        np.testing.assert_allclose(smoothed, ref_smooth, rtol=1e-12, atol=1e-12)

        a, g = adaptation_time(smoothed, 200, bin_s=1.0, steady_from_s=60, steady_to_s=120, fraction=0.9, hold_s=10)
        ra, rg = reference_adaptation(list(smoothed), 200, 60, 120, 0.9, 10)
        assert g == pytest.approx(rg, rel=1e-12)
        assert (a is None and ra is None) or a == pytest.approx(ra), case
