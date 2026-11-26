"""Pluggable policy interface — owner: Krupesh (Work Distribution task 4).

Kept here because Krupesh/README.md lists the policy interface under integration/.
The definition lives in router_service/policy_base.py; import from either place.

    from integration.policy_interface import Policy

Any policy (Jyotir's baselines, Sur's LinUCB) implements:
    choose(request, candidates) -> node_id
    update(request, node_id, outcome) -> None
and is selected with one string in router_service/registry.py.
"""

from router_service.policy_base import Policy

__all__ = ["Policy"]
