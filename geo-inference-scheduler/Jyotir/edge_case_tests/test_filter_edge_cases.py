"""
Edge case tests for the feasibility filter — owner: Jyotir

Three cases that must work correctly even though they are uncommon:
  1. All nodes are too hot   → empty allowed list, controlled rejection
  2. Only one node passes    → that one node is returned, no crash
  3. Node is warming up      → allowed with _warming=True (default config)
                               rejected when allow_warming_nodes=False

Run with:  pytest edge_case_tests/test_filter_edge_cases.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from feasibility_filter.filter import feasibility_filter, load_config

# ── shared fixtures ────────────────────────────────────────────────────────────

BASE_REQUEST = {
    "request_id": "r-test-001",
    "model": "llama-3-8b",
    "input_tokens": 850,
    "expected_output_tokens": 200,
    "slo_class": "interactive",
    "slo_ms": 250,
    "user_region": "nyc",
}

BASE_CONFIG = {
    "temperature_limit_c": 85.0,
    "power_headroom_min_kw": 2.0,
    "kv_cache_max_frac": 0.90,
    "allow_warming_nodes": True,
}

def _make_healthy_node(node_id: str) -> dict:
    return {
        "node_id": node_id,
        "status": "up",
        "models_loaded": ["llama-3-8b"],
        "kv_used_frac": 0.50,
        "power_headroom_kw": 5.0,
        "temperature_c": 65.0,
        "queue_len": 3,
        "running": 10,
        "rtt_ms": {"nyc": 15},
        "energy_price_usd_kwh": 0.10,
        "gpu_price_usd_hr": 2.00,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Edge Case 1: ALL nodes are too hot
# ══════════════════════════════════════════════════════════════════════════════

class TestAllNodesTooHot:

    def _overheated_nodes(self):
        nodes = []
        for i in range(4):
            n = _make_healthy_node(f"node-{i}")
            n["temperature_c"] = 90.0  # above the 85 °C limit
            nodes.append(n)
        return nodes

    def test_allowed_list_is_empty(self):
        allowed, _ = feasibility_filter(BASE_REQUEST, self._overheated_nodes(), BASE_CONFIG)
        assert allowed == [], "All overheated nodes should be rejected"

    def test_every_node_is_rejected(self):
        nodes = self._overheated_nodes()
        _, rejected = feasibility_filter(BASE_REQUEST, nodes, BASE_CONFIG)
        assert len(rejected) == len(nodes), "Every node should appear in rejected"

    def test_rejection_reason_is_temperature_high(self):
        _, rejected = feasibility_filter(BASE_REQUEST, self._overheated_nodes(), BASE_CONFIG)
        for r in rejected:
            assert r["reason"] == "temperature_high", (
                f"Expected 'temperature_high', got '{r['reason']}' for {r['node_id']}"
            )

    def test_filter_does_not_crash_on_empty_result(self):
        # The filter must return cleanly — not raise — when nothing passes.
        # The router is responsible for converting an empty allowed list into a rejection.
        try:
            allowed, rejected = feasibility_filter(BASE_REQUEST, self._overheated_nodes(), BASE_CONFIG)
        except Exception as e:
            raise AssertionError(f"Filter raised an exception on all-rejected input: {e}")
        assert isinstance(allowed, list)
        assert isinstance(rejected, list)


# ══════════════════════════════════════════════════════════════════════════════
# Edge Case 2: Exactly ONE node passes
# ══════════════════════════════════════════════════════════════════════════════

class TestOnlyOneNodeFeasible:

    def _one_good_three_bad(self):
        good = _make_healthy_node("good-node")

        down    = _make_healthy_node("down-node");    down["status"] = "down"
        hot     = _make_healthy_node("hot-node");     hot["temperature_c"] = 90.0
        no_mem  = _make_healthy_node("mem-node");     no_mem["kv_used_frac"] = 0.95

        return [good, down, hot, no_mem]

    def test_exactly_one_node_allowed(self):
        allowed, _ = feasibility_filter(BASE_REQUEST, self._one_good_three_bad(), BASE_CONFIG)
        assert len(allowed) == 1

    def test_correct_node_is_allowed(self):
        allowed, _ = feasibility_filter(BASE_REQUEST, self._one_good_three_bad(), BASE_CONFIG)
        assert allowed[0]["node_id"] == "good-node"

    def test_three_nodes_rejected(self):
        _, rejected = feasibility_filter(BASE_REQUEST, self._one_good_three_bad(), BASE_CONFIG)
        assert len(rejected) == 3

    def test_rejection_reasons_are_correct(self):
        _, rejected = feasibility_filter(BASE_REQUEST, self._one_good_three_bad(), BASE_CONFIG)
        reason_map = {r["node_id"]: r["reason"] for r in rejected}
        assert reason_map["down-node"]  == "node_down"
        assert reason_map["hot-node"]   == "temperature_high"
        assert reason_map["mem-node"]   == "memory_full"

    def test_baselines_handle_single_candidate_without_crash(self):
        from baselines import RoundRobin, MinRTT, LeastLoad, LowestEnergy, StaticWeighted, PowerOfTwo

        allowed, _ = feasibility_filter(BASE_REQUEST, self._one_good_three_bad(), BASE_CONFIG)

        for PolicyClass in [RoundRobin, MinRTT, LeastLoad, LowestEnergy, StaticWeighted, PowerOfTwo]:
            policy = PolicyClass()
            chosen = policy.choose(BASE_REQUEST, allowed)
            assert chosen == "good-node", (
                f"{PolicyClass.__name__} did not return the only feasible node"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Edge Case 3: Node recovering from outage (warming status)
# ══════════════════════════════════════════════════════════════════════════════

class TestWarmingNode:

    def _warming_cluster(self):
        healthy = _make_healthy_node("healthy-node")
        warming = _make_healthy_node("warming-node")
        warming["status"] = "warming"
        return [healthy, warming]

    def test_warming_node_allowed_by_default(self):
        allowed, rejected = feasibility_filter(BASE_REQUEST, self._warming_cluster(), BASE_CONFIG)
        allowed_ids = [n["node_id"] for n in allowed]
        assert "warming-node" in allowed_ids, "Warming node should be allowed when allow_warming_nodes=True"

    def test_warming_node_is_tagged(self):
        allowed, _ = feasibility_filter(BASE_REQUEST, self._warming_cluster(), BASE_CONFIG)
        warming_nodes = [n for n in allowed if n["node_id"] == "warming-node"]
        assert len(warming_nodes) == 1
        assert warming_nodes[0].get("_warming") is True, (
            "Warming node must be tagged with _warming=True so the policy can apply a penalty"
        )

    def test_healthy_node_is_not_tagged(self):
        allowed, _ = feasibility_filter(BASE_REQUEST, self._warming_cluster(), BASE_CONFIG)
        healthy_nodes = [n for n in allowed if n["node_id"] == "healthy-node"]
        assert len(healthy_nodes) == 1
        assert "_warming" not in healthy_nodes[0], "Healthy node must not carry _warming tag"

    def test_warming_node_rejected_when_config_disables_it(self):
        config_no_warming = {**BASE_CONFIG, "allow_warming_nodes": False}
        allowed, rejected = feasibility_filter(BASE_REQUEST, self._warming_cluster(), config_no_warming)

        allowed_ids  = [n["node_id"] for n in allowed]
        rejected_ids = [r["node_id"] for r in rejected]

        assert "warming-node" not in allowed_ids,  "Warming node must be rejected when allow_warming_nodes=False"
        assert "warming-node" in rejected_ids,     "Warming node must appear in rejected list"

    def test_warming_rejection_reason(self):
        config_no_warming = {**BASE_CONFIG, "allow_warming_nodes": False}
        _, rejected = feasibility_filter(BASE_REQUEST, self._warming_cluster(), config_no_warming)
        reason_map = {r["node_id"]: r["reason"] for r in rejected}
        assert reason_map.get("warming-node") == "node_warming"
