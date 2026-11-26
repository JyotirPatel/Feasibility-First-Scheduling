"""
Router plug-in — owner: Sur

Connects Sur's policies and reward to Krupesh's router (geo-inference-scheduler/Krupesh/:
router_service/ and api_contract/) without editing his folder. It provides what his
Interface & Dependency Handbook (§5.3) asks of Sur:

  RouterLinUCB, RouterSlidingWindowLinUCB
      Sur's LinUCB and sliding-window LinUCB as subclasses of Krupesh's
      router_service.policy_base.Policy. They are exactly the policies in linucb/ and
      sliding_window_linucb/ (same names, configs and checkpoints); only his base class
      is added, so isinstance(policy, Policy) holds in his router.
  reward_fn(outcome, node_at_dispatch) -> float
      Sur's reward (reward/) in the RewardFn shape of api_contract/types.py, with the
      weights in configs/policies/sw_linucb.yaml. make_reward_fn(config) builds one for
      another reward section.
  register(extra_policies=None)
      Adds Sur's policies to the router's registry (router_service.registry.EXTRA_POLICIES
      unless another dict is given), under the names in POLICIES.

Krupesh's router computes outcome.reward with the reward_fn it was given before it
calls policy.update(). Sur's policies recompute the reward themselves and count any
difference in stats["reward_mismatch"], which catches a router still using his mock.

Krupesh's code is looked for in geo-inference-scheduler/Krupesh/ and, because his
upload of 2026-10-27 landed one level deeper, in Krupesh/geo-inference-scheduler/Krupesh/.
His folder is appended to sys.path, so Sur's and Jyotir's modules win any name clash.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_SUR_DIR = os.path.dirname(_HERE)
_KRUPESH_DIR = os.path.join(os.path.dirname(_SUR_DIR), "Krupesh")
_KRUPESH_CANDIDATES = (_KRUPESH_DIR, os.path.join(_KRUPESH_DIR, "geo-inference-scheduler", "Krupesh"))

CONFIG_DIR = os.path.join(_SUR_DIR, "configs", "policies")
REWARD_CONFIG_PATH = os.path.join(CONFIG_DIR, "sw_linucb.yaml")
NO_CONTEXT_CONFIG_PATH = os.path.join(CONFIG_DIR, "sw_linucb_no_context.yaml")


def krupesh_dir() -> str:
    """The folder that holds Krupesh's router_service/ and api_contract/ packages."""
    for path in _KRUPESH_CANDIDATES:
        if os.path.isfile(os.path.join(path, "router_service", "policy_base.py")):
            return path
    raise ImportError(f"Krupesh's router code (router_service/policy_base.py) is not in any of {_KRUPESH_CANDIDATES}")


if _SUR_DIR not in sys.path:
    sys.path.insert(0, _SUR_DIR)
if krupesh_dir() not in sys.path:
    sys.path.append(krupesh_dir())

from router_service.policy_base import Policy  # noqa: E402  (Krupesh's base class)

from linucb import LinUCB  # noqa: E402
from reward import RewardConfig, as_reward_config, compute_reward  # noqa: E402
from sliding_window_linucb import SlidingWindowLinUCB  # noqa: E402


class RouterLinUCB(LinUCB, Policy):
    """Sur's plain LinUCB (linucb/) as a subclass of Krupesh's router Policy."""


class RouterSlidingWindowLinUCB(SlidingWindowLinUCB, Policy):
    """Sur's sliding-window LinUCB (sliding_window_linucb/) as a subclass of Krupesh's router Policy."""


def make_reward_fn(config: RewardConfig | Mapping[str, Any] | str | os.PathLike | None = None) -> Callable:
    """
    A RewardFn, reward_fn(outcome, node_at_dispatch) -> float, for Krupesh's RoutingEngine.

    config : None (the reward section of configs/policies/sw_linucb.yaml), a policy YAML
             file whose `reward:` section is used, or a reward section itself (a mapping or
             a RewardConfig, for example policy.config.reward).
    """
    if config is None:
        config = REWARD_CONFIG_PATH
    if isinstance(config, (str, os.PathLike)):
        with open(config) as f:
            config = yaml.safe_load(f)["reward"]
    cfg = as_reward_config(config)

    def reward_fn(outcome: Any, node_at_dispatch: Any) -> float:
        return compute_reward(node_at_dispatch, outcome, cfg)

    return reward_fn


reward_fn = make_reward_fn()


def _linucb(seed: int = 0, **params: Any) -> RouterLinUCB:
    return RouterLinUCB(seed=seed, **params)


def _sw_linucb(seed: int = 0, **params: Any) -> RouterSlidingWindowLinUCB:
    return RouterSlidingWindowLinUCB(seed=seed, **params)


def _sw_linucb_no_context(seed: int = 0, **params: Any) -> RouterSlidingWindowLinUCB:
    params.setdefault("config", NO_CONTEXT_CONFIG_PATH)
    return RouterSlidingWindowLinUCB(seed=seed, **params)


# Registry name -> factory(seed, **params); a `config=` param picks another policy YAML file.
POLICIES: dict[str, Callable[..., Policy]] = {
    "sur:linucb": _linucb,  # plain LinUCB, the "no forgetting" ablation (configs/policies/linucb.yaml)
    "sur:sw_linucb": _sw_linucb,  # sliding-window LinUCB (configs/policies/sw_linucb.yaml)
    "sur:sw_linucb_no_context": _sw_linucb_no_context,  # the "no context" ablation
    "linucb": _linucb,  # the names in Riya/experiment_runner/config.json
    "sliding_window_linucb": _sw_linucb,
}


def register(extra_policies: dict[str, Callable[..., Policy]] | None = None) -> list[str]:
    """Add Sur's policies to the router's registry and return the names added."""
    if extra_policies is None:
        from router_service import registry

        extra_policies = registry.EXTRA_POLICIES
    extra_policies.update(POLICIES)
    return sorted(POLICIES)
