"""Tests for sliding-window LinUCB (sliding_window_linucb/sw_linucb.py)."""

import numpy as np
import pytest
from pydantic import ValidationError

from linucb import LinUCB
from reward import compute_reward
from sliding_window_linucb import SlidingWindowLinUCB, load_config
from sur_factories import load_yaml, make_node, make_outcome, make_request

LAM = 1.0


def sw(size=1000, mode="per_node", rebuild_every=1000, **overrides):
    cfg = load_yaml("sw_linucb.yaml")
    cfg["window"] = {"size": size, "mode": mode, "rebuild_every": rebuild_every}
    cfg.update(overrides)
    return SlidingWindowLinUCB(cfg)


def feed(policy, node, i, rng):
    """Route one request to `node` (the only candidate) and return its (x, r)."""
    request = make_request(f"r-{i}", input_tokens=int(rng.integers(10, 4000)))
    met = bool(rng.random() < 0.6)
    outcome = make_outcome(slo_met=met, ttft_ms=float(rng.uniform(50, 600)))
    policy.choose(request, [node])
    x = policy.features.build(request, node)
    r = compute_reward(node, outcome, policy.config.reward)
    policy.update(request, node["node_id"], outcome)
    return x, r


def exact(samples, dim):
    X = np.array([x for x, _ in samples]).reshape(-1, dim)
    R = np.array([r for _, r in samples])
    return LAM * np.eye(dim) + X.T @ X, X.T @ R


# ── the window keeps exactly the right outcomes ──────────────────────────────


def test_per_node_window_keeps_the_last_w_outcomes_of_each_node():
    policy = sw(size=5, mode="per_node")
    rng = np.random.default_rng(0)
    a, b = make_node("a"), make_node("b", queue_len=0)
    seen = {"a": [], "b": []}
    for i in range(12):
        seen["a"].append(feed(policy, a, i, rng))
    for i in range(12, 15):
        seen["b"].append(feed(policy, b, i, rng))
    assert policy.window_counts() == {"a": 5, "b": 3}
    for node_id, keep in (("a", seen["a"][-5:]), ("b", seen["b"])):
        A, bvec = exact(keep, policy.dim)
        np.testing.assert_allclose(policy._models[node_id].A, A, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(policy._models[node_id].b, bvec, rtol=1e-10, atol=1e-10)


def test_global_window_keeps_the_last_w_outcomes_overall():
    policy = sw(size=6, mode="global")
    rng = np.random.default_rng(1)
    nodes = {"a": make_node("a"), "b": make_node("b", queue_len=0)}
    sequence = ["a", "a", "b", "a", "b", "b", "a", "b", "a", "a", "b"]
    history = [(nid, feed(policy, nodes[nid], i, rng)) for i, nid in enumerate(sequence)]
    last6 = history[-6:]
    assert sum(policy.window_counts().values()) == 6
    for node_id in ("a", "b"):
        A, bvec = exact([s for nid, s in last6 if nid == node_id], policy.dim)
        np.testing.assert_allclose(policy._models[node_id].A, A, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(policy._models[node_id].b, bvec, rtol=1e-10, atol=1e-10)


def test_global_window_returns_an_unused_node_exactly_to_the_prior():
    policy = sw(size=3, mode="global")
    rng = np.random.default_rng(2)
    a, b = make_node("a"), make_node("b")
    feed(policy, a, 0, rng)
    for i in range(1, 4):
        feed(policy, b, i, rng)
    np.testing.assert_array_equal(policy._models["a"].A, LAM * np.eye(policy.dim))
    np.testing.assert_array_equal(policy._models["a"].b, np.zeros(policy.dim))
    assert policy.model_counts()["a"] == 0


def test_floating_point_drift_stays_tiny_and_rebuilds_are_exact():
    rng = np.random.default_rng(3)
    node = make_node("a")
    never = sw(size=50, rebuild_every=10**9)
    often = sw(size=50, rebuild_every=7)
    samples = []
    for i in range(3000):
        samples.append(feed(never, node, i, rng))
    rng = np.random.default_rng(3)
    for i in range(3000):
        feed(often, node, i, rng)
    A, b = exact(samples[-50:], never.dim)
    np.testing.assert_allclose(never._models["a"].A, A, rtol=0, atol=1e-9)  # drift without rebuilds is tiny
    np.testing.assert_allclose(never._models["a"].b, b, rtol=0, atol=1e-9)
    np.testing.assert_allclose(often._models["a"].A, A, rtol=1e-12, atol=1e-12)


def test_huge_window_behaves_exactly_like_plain_linucb():
    plain_cfg = load_yaml("linucb.yaml")
    plain = LinUCB(plain_cfg)
    windowed = sw(size=10**9)
    rng_p, rng_w = np.random.default_rng(4), np.random.default_rng(4)
    nodes = [make_node("a"), make_node("b", queue_len=30), make_node("c", rtt_ms={"nyc": 90})]
    for i in range(300):
        request = make_request(f"r-{i}")
        cp, cw = plain.choose(request, nodes), windowed.choose(request, nodes)
        assert cp == cw
        p = 0.8 if cp == "a" else 0.4
        plain.update(request, cp, make_outcome(slo_met=bool(rng_p.random() < p)))
        windowed.update(request, cw, make_outcome(slo_met=bool(rng_w.random() < p)))
    for node_id in ("a", "b", "c"):
        np.testing.assert_allclose(windowed._models[node_id].A, plain._models[node_id].A)


# ── forgetting helps after a change (the point of the method) ────────────────


def _run(policy, rounds, p_met, seed):
    """Two identical-looking nodes whose SLO-hit probability is p_met(round, node)."""
    rng = np.random.default_rng(seed)
    nodes = [make_node("a"), make_node("b")]
    picks = []
    for i in range(rounds):
        request = make_request(f"r-{i}")
        chosen = policy.choose(request, nodes)
        met = bool(rng.random() < p_met(i, chosen))
        policy.update(request, chosen, make_outcome(slo_met=met, ttft_ms=150.0 if met else 400.0))
        picks.append(chosen)
    return picks


def _rounds_to_switch(picks, change_at, run_len=50, share=0.8):
    """Rounds after the change until "b" gets >= 80% of a 50-round stretch (inf if never)."""
    for t in range(change_at, len(picks) - run_len):
        if picks[t : t + run_len].count("b") / run_len >= share:
            return t - change_at
    return float("inf")


def _plain():
    return LinUCB(load_yaml("linucb.yaml"))


def test_forgetting_reacts_fast_and_plain_linucb_slows_down_with_history():
    """
    The best node gets worse at round T ("a": 0.9 -> 0.3, "b": 0.3 -> 0.9).
    Plain LinUCB's long history anchors it, so the later the change, the longer
    it takes to switch; a sliding window reacts in about the same time whenever
    the change happens. (Measured with these settings, seeds 0-2: plain LinUCB
    134 / 214 / 196 rounds at T=1500 and 487 / 1763 / 732 at T=6000; per-node
    windows 52 / 20 / 28 and 66 / 12 / 21; global windows 17 / 16 / 6 and 11 / 7 / 18.)
    """
    seeds = (0, 1, 2)
    switch = {}
    for T in (1500, 6000):

        def p(i, c, T=T):
            return (0.9 if c == "a" else 0.3) if i < T else (0.3 if c == "a" else 0.9)

        for label, make in (
            ("plain", _plain),
            ("per_node", lambda: sw(size=100, mode="per_node")),
            ("global", lambda: sw(size=100, mode="global")),
        ):
            switch[label, T] = [_rounds_to_switch(_run(make(), T + 2500, p, s), T) for s in seeds]

    for T in (1500, 6000):
        for label in ("per_node", "global"):
            assert max(switch[label, T]) <= 150, (label, T, switch[label, T])
            assert np.median(switch["plain", T]) > 3 * np.median(switch[label, T]), (label, T, switch)
    assert np.median(switch["plain", 6000]) > np.median(switch["plain", 1500]), switch


def test_only_a_global_window_rediscovers_a_node_it_had_abandoned():
    """
    "b" is useless early, then becomes the best node at round 300 ("a" stays at 0.5).
    LinUCB's uncertainty about a node only changes when that node is picked, so a
    node it stopped picking keeps its stale estimate. With a per-node window that
    stale data never leaves either; with a global window it ages out, b's bonus
    grows back and b is retried. This is the S6 situation (a node that comes back).
    """

    def p(i, c):
        return 0.5 if c == "a" else (0.0 if i < 300 else 1.0)

    for seed in (0, 1, 2):
        share = {
            label: _run(make(), 900, p, seed)[600:].count("b") / 300
            for label, make in (
                ("plain", _plain),
                ("per_node", lambda: sw(size=200, mode="per_node")),
                ("global", lambda: sw(size=200, mode="global")),
            )
        }
        assert share["global"] > 0.9, share
        assert share["per_node"] < 0.05, share
        assert share["plain"] < 0.05, share


# ── config and checkpoints ───────────────────────────────────────────────────


def test_default_config_file_loads():
    cfg = load_config()
    assert cfg.policy == "sw_linucb"
    assert cfg.window.size == 1000 and cfg.window.mode == "per_node"


@pytest.mark.parametrize(
    "window",
    [
        {"size": 0, "mode": "per_node", "rebuild_every": 10},
        {"size": 10, "mode": "sideways", "rebuild_every": 10},
        {"size": 10, "mode": "global", "rebuild_every": 0},
        {"size": 10, "mode": "global"},
    ],
)
def test_bad_window_config_is_rejected(window):
    cfg = load_yaml("sw_linucb.yaml")
    cfg["window"] = window
    with pytest.raises(ValidationError):
        SlidingWindowLinUCB(cfg)


def test_sliding_window_needs_its_own_config_type():
    with pytest.raises(ValidationError):
        SlidingWindowLinUCB(load_yaml("linucb.yaml"))  # no window, wrong policy name


@pytest.mark.parametrize("mode", ["per_node", "global"])
def test_checkpoint_round_trip_continues_identically(tmp_path, mode):
    original = sw(size=40, mode=mode)
    rng = np.random.default_rng(7)
    nodes = [make_node("a"), make_node("b", queue_len=20)]
    for i in range(150):
        request = make_request(f"r-{i}")
        chosen = original.choose(request, nodes)
        original.update(request, chosen, make_outcome(slo_met=bool(rng.random() < 0.6)))
    path = tmp_path / f"sw_{mode}.npz"
    original.save_checkpoint(path)
    restored = sw(size=40, mode=mode)
    restored.load_checkpoint(path)
    assert restored.window_counts() == original.window_counts()

    rng_o, rng_r = np.random.default_rng(8), np.random.default_rng(8)
    for i in range(150, 300):
        request = make_request(f"r-{i}")
        co, cr = original.choose(request, nodes), restored.choose(request, nodes)
        assert co == cr
        original.update(request, co, make_outcome(slo_met=bool(rng_o.random() < 0.6)))
        restored.update(request, cr, make_outcome(slo_met=bool(rng_r.random() < 0.6)))
    for node_id in ("a", "b"):
        np.testing.assert_allclose(restored._models[node_id].A, original._models[node_id].A, rtol=1e-10, atol=1e-10)


def test_checkpoint_refuses_a_different_window_or_tampered_window(tmp_path):
    policy = sw(size=40)
    rng = np.random.default_rng(9)
    for i in range(60):
        feed(policy, make_node("a"), i, rng)
    path = tmp_path / "sw.npz"
    policy.save_checkpoint(path)

    with pytest.raises(ValueError, match="window"):
        sw(size=80).load_checkpoint(path)
    with pytest.raises(ValueError, match="window"):
        sw(size=40, mode="global").load_checkpoint(path)
    with pytest.raises(ValueError, match="policy"):
        LinUCB(load_yaml("linucb.yaml")).load_checkpoint(path)

    with np.load(path, allow_pickle=False) as data:
        arrays = {k: data[k] for k in data.files}
    arrays["window_r"] = arrays["window_r"] + 0.5
    tampered = tmp_path / "tampered.npz"
    np.savez(tampered, **arrays)
    with pytest.raises(ValueError, match="do not match"):
        sw(size=40).load_checkpoint(tampered)
