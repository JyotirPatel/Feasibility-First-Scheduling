"""Test helpers: build NodeState / Request quickly."""

from api_contract.types import NodeState, Request


def node(node_id="n1", **kw) -> NodeState:
    base = dict(
        node_id=node_id,
        status="up",
        rtt_ms={"nyc": 15.0},
        queue_len=0,
        running=2,
        capacity=32,
        kv_used_frac=0.3,
        models_loaded=["llama-3-8b"],
        power_headroom_kw=5.0,
        temperature_c=60.0,
        energy_price_usd_kwh=0.1,
        gpu_price_usd_hr=2.0,
        t=0.0,
    )
    base.update(kw)
    return NodeState(**base)


def request(rid="r-1", **kw) -> Request:
    base = dict(
        request_id=rid,
        t_arrival=1.0,
        user_region="nyc",
        model="llama-3-8b",
        input_tokens=850,
        expected_output_tokens=200,
        slo_class="interactive",
        ttft_slo_ms=250.0,
    )
    base.update(kw)
    return Request(**base)
