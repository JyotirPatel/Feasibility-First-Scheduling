"""Privileged, myopic true-state reference, NOT a global optimum.

Refreshes all node states on every arrival, applies the same hard constraints,
and admits only jobs that can start immediately with their actual token count.
Among them, chooses the lowest true model TTFT. No future event knowledge or
multi-request planning is used; ordinary policies can outperform it in a window.
"""

from api_contract.types import FilterResult
from router_service.policy_base import Policy
from simulator.routers import KrupeshRouter
from simulator.latency_model import prefill_ms


class TrueStatePolicy(Policy):
    name = "reference:true_state"

    def choose(self, request, candidates):
        sim = self.simulation

        def score(candidate):
            node = sim.nodes[candidate.node_id]
            predicted = node.rtt_to(request.user_region) + prefill_ms(
                node.consts.a_p_ms,
                node.consts.b_p_ms_per_token,
                request.input_tokens,
                node.slowdown(sim.env.now),
            )
            return predicted, len(node.running) / node.capacity, candidate.node_id

        return min(candidates, key=score).node_id


class TrueStateRouter(KrupeshRouter):
    def route(self, request):
        self.ingest_telemetry(
            [
                n.telemetry(self.simulation.env.now)
                for n in self.simulation.nodes.values()
            ]
        )
        return super().route(request)


def immediate_candidates(request, candidates, simulation, actual_tokens):
    allowed = []
    rejected = {}
    for c in candidates:
        n = simulation.nodes[c.node_id]
        if n.queue or len(n.running) >= n.capacity:
            rejected[c.node_id] = "reference_no_immediate_slot"
        elif n.kv_used + actual_tokens > n.kv_capacity * 0.90:
            rejected[c.node_id] = "reference_actual_memory_full"
        else:
            allowed.append(c)
    return allowed, rejected


def attach_reference(adapter, simulation, policy):
    # Keep the simulator itself and all teammate source files unchanged.
    adapter.__class__ = TrueStateRouter
    adapter.simulation = simulation
    policy.simulation = simulation
    actual = {
        i.request["request_id"]: i.request["input_tokens"] + i.output_tokens
        for i in simulation.items
    }
    original = adapter.router.filter_fn

    def filter_current(request, nodes):
        result = original(request, nodes)
        allowed, rejected = immediate_candidates(
            request, result.allowed, simulation, actual[request.request_id]
        )
        return FilterResult(allowed=allowed, rejected={**result.rejected, **rejected})

    adapter.router.filter_fn = filter_current
