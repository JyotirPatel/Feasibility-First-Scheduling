"""
Feasibility filter — owner: Jyotir

Takes a request and a list of node snapshots.
Returns (allowed, rejected):
  allowed  — nodes that passed every rule. Warming nodes that are
             allowed carry the extra key _warming=True so the policy
             can apply a penalty.
  rejected — list of {node_id, reason} for every node removed.

If allowed is empty, the router must reject the request entirely
with reason "no_feasible_node". The filter never makes that call
itself — it only returns an empty allowed list.

Rule order (fail-fast: first failure wins):
  1. Status        — node must be "up" or "warming"
  2. Model         — requested model must be loaded on the node
  3. Memory        — KV cache usage must be below the configured limit
  4. Power         — power headroom must be above the configured minimum
  5. Temperature   — GPU temperature must be below the configured limit
"""

import os
import yaml

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "configs", "feasibility.yaml"
)


def load_config(path: str = _DEFAULT_CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def feasibility_filter(
    request: dict,
    nodes: list[dict],
    config: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Parameters
    ----------
    request : dict
        Must contain at least: "model" (str)
        Example: {"model": "llama-3-8b", "input_tokens": 850, ...}
    nodes : list[dict]
        Each node snapshot from the simulator / fake_node.py.
    config : dict, optional
        Loaded from feasibility.yaml if not provided.

    Returns
    -------
    allowed : list[dict]
        Node snapshots that passed all rules.
        A warming node that is allowed carries _warming=True.
    rejected : list[dict]
        Each entry: {"node_id": str, "reason": str}
    """
    if config is None:
        config = load_config()

    allowed = []
    rejected = []

    for node in nodes:
        reason = _check_node(request, node, config)

        if reason is None:
            allowed.append(node)

        elif reason == "node_warming":
            if config.get("allow_warming_nodes", True):
                tagged = dict(node)
                tagged["_warming"] = True
                allowed.append(tagged)
            else:
                rejected.append({"node_id": node["node_id"], "reason": "node_warming"})

        else:
            rejected.append({"node_id": node["node_id"], "reason": reason})

    return allowed, rejected


def _check_node(request: dict, node: dict, config: dict) -> str | None:
    """
    Returns None if the node passes every rule.
    Returns a reason string on the first rule it fails.
    """

    # ── Rule 1: Status ────────────────────────────────────────────────────────
    status = node.get("status", "up")
    if status == "down":
        return "node_down"
    if status == "warming":
        return "node_warming"  # caller decides whether to allow or reject

    # ── Rule 2: Model available ───────────────────────────────────────────────
    requested_model = request.get("model")
    if requested_model not in node.get("models_loaded", []):
        return "model_missing"

    # ── Rule 3: KV cache has room ─────────────────────────────────────────────
    kv_limit = config.get("kv_cache_max_frac", 0.90)
    if node.get("kv_used_frac", 1.0) >= kv_limit:
        return "memory_full"

    # ── Rule 4: Power headroom above minimum ──────────────────────────────────
    power_min = config.get("power_headroom_min_kw", 2.0)
    if node.get("power_headroom_kw", 0.0) < power_min:
        return "power_limit"

    # ── Rule 5: Temperature below limit ───────────────────────────────────────
    temp_limit = config.get("temperature_limit_c", 85.0)
    if node.get("temperature_c", 999.0) >= temp_limit:
        return "temperature_high"

    return None  # all rules passed
