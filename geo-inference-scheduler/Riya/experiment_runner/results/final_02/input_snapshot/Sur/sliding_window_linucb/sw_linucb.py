"""
Sliding-window LinUCB (Cheung, Simchi-Levi & Zhu, 2019) — owner: Sur

Same as plain LinUCB (linucb/), but each node's A_a and b_a are built only
from recent outcomes (brief §6.5). When an outcome leaves the window it is
subtracted back out:  A_a ← A_a − x xᵀ,  b_a ← b_a − r·x.
So old results about a node that has since changed are forgotten.

Which outcomes count as "recent" is an open team question (brief §15), so
both readings are implemented and picked in configs/policies/sw_linucb.yaml:

  window.mode: per_node   the last W outcomes of each node
                          (Sur/README.md, work distribution §4)
  window.mode: global     the last W outcomes over all nodes
                          (brief §6.5, as in Cheung et al.). A node that stops
                          being chosen slowly loses its old data, its
                          uncertainty bonus grows back, and it gets retried.

Outcomes enter the window in the order their feedback arrives. Small W
reacts fast but is noisy; large W is stable but slow. window_sweep/ runs
W = 200, 500, 1000, 2000, 5000 in both modes.

Subtracting many times can build up tiny floating-point error, so every
window.rebuild_every removals a node's A_a and b_a are rebuilt exactly from
the outcomes still in its window. A node whose window empties goes back to
exactly A_a = λI, b_a = 0.
"""

from __future__ import annotations

import os
import sys
from collections import deque
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

_SUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SUR_DIR not in sys.path:
    sys.path.insert(0, _SUR_DIR)

from linucb.linucb import CONFIG_DIR, BanditConfig, LinUCB, _NodeModel, load_yaml_config  # noqa: E402


class WindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: int = Field(gt=0)
    mode: Literal["per_node", "global"]
    rebuild_every: int = Field(gt=0)


class SWLinUCBConfig(BanditConfig):
    policy: Literal["sw_linucb"]
    window: WindowConfig


def load_config(path: str | os.PathLike | None = None) -> SWLinUCBConfig:
    """Load and check configs/policies/sw_linucb.yaml (or another file)."""
    return load_yaml_config(path or SlidingWindowLinUCB.default_config_path, SWLinUCBConfig)


class SlidingWindowLinUCB(LinUCB):
    """LinUCB that learns only from the last W outcomes. See the module docstring."""

    name: ClassVar[str] = "sw_linucb"
    config_model: ClassVar[type[BanditConfig]] = SWLinUCBConfig
    default_config_path: ClassVar[str] = os.path.join(CONFIG_DIR, "sw_linucb.yaml")
    _state_keys: ClassVar[tuple[str, ...]] = ("lambda", "features", "reward", "window")

    def __init__(self, config: Any = None, *, seed: int | None = None):
        super().__init__(config, seed=seed)
        window = self.config.window
        self.window_size = window.size
        self.window_mode = window.mode
        self.rebuild_every = window.rebuild_every
        self._samples: dict[str, deque[tuple[np.ndarray, float]]] = {}  # in-window (x, r) per node, oldest first
        self._order: deque[str] = deque()  # global mode: node of every in-window outcome, oldest first
        self._removals: dict[str, int] = {}  # removals since the node's last exact rebuild

    def window_counts(self) -> dict[str, int]:
        """Number of outcomes currently in each node's window."""
        with self._lock:
            return {node_id: len(s) for node_id, s in self._samples.items()}

    # ── Learning with forgetting ─────────────────────────────────────────────

    def _learn(self, node_id: str, x: np.ndarray, r: float) -> None:
        super()._learn(node_id, x, r)
        self._samples.setdefault(node_id, deque()).append((x, r))
        if self.window_mode == "global":
            self._order.append(node_id)
            while len(self._order) > self.window_size:
                self._forget_oldest(self._order.popleft())
        else:
            while len(self._samples[node_id]) > self.window_size:
                self._forget_oldest(node_id)

    def _forget_oldest(self, node_id: str) -> None:
        samples = self._samples[node_id]
        x, r = samples.popleft()
        model = self._models[node_id]
        if not samples:
            model.reset()  # window empty -> exactly the prior λI, 0
            self._removals[node_id] = 0
            return
        model.remove(x, r)
        self._removals[node_id] = self._removals.get(node_id, 0) + 1
        if self._removals[node_id] >= self.rebuild_every:
            model.rebuild(samples)
            self._removals[node_id] = 0

    # ── Checkpoints: also save the window contents ───────────────────────────

    def _extra_checkpoint_arrays(self, node_ids: list[str]) -> dict[str, np.ndarray]:
        index = {node_id: i for i, node_id in enumerate(node_ids)}
        owners, xs, rs = [], [], []
        for node_id in node_ids:
            for x, r in self._samples.get(node_id, ()):
                owners.append(index[node_id])
                xs.append(x)
                rs.append(r)
        return {
            "window_node": np.array(owners, dtype=np.int64),
            "window_x": np.array(xs, dtype=float).reshape(len(xs), self.dim),
            "window_r": np.array(rs, dtype=float),
            "window_order": np.array([index[n] for n in self._order], dtype=np.int64),
        }

    def _restore_extra(self, models: dict, node_ids: list[str], arrays: dict, path: Any) -> None:
        try:
            owners, X, R, order = (arrays[k] for k in ("window_node", "window_x", "window_r", "window_order"))
        except KeyError:
            raise ValueError(f"{path}: sliding-window checkpoint has no window contents") from None
        k = len(node_ids)
        m = len(owners)
        if X.shape != (m, self.dim) or R.shape != (m,):
            raise ValueError(f"{path}: window arrays have inconsistent shapes")
        if m and (owners.min() < 0 or owners.max() >= k):
            raise ValueError(f"{path}: window refers to an unknown node")
        if not (np.all(np.isfinite(X)) and np.all(np.isfinite(R))):
            raise ValueError(f"{path}: window contains invalid numbers")

        samples = {node_id: deque() for node_id in node_ids}
        for i, x, r in zip(owners, X, R, strict=True):
            samples[node_ids[i]].append((x.copy(), float(r)))

        if self.window_mode == "global":
            if m > self.window_size or len(order) != m or (m and (order.min() < 0 or order.max() >= k)):
                raise ValueError(f"{path}: global window order does not match its contents")
            if np.any(np.bincount(order, minlength=k) != np.bincount(owners, minlength=k)):
                raise ValueError(f"{path}: global window order does not match its contents")
        elif any(len(s) > self.window_size for s in samples.values()) or len(order):
            raise ValueError(f"{path}: per-node window holds more than W outcomes")

        # The window is the source of truth: rebuild every model from it and
        # check that it agrees with the saved A and b.
        for node_id in node_ids:
            rebuilt = _NodeModel(self.dim, self.lam)
            rebuilt.rebuild(samples[node_id])
            saved = models[node_id]
            if not (
                np.allclose(rebuilt.A, saved.A, rtol=1e-6, atol=1e-8)
                and np.allclose(rebuilt.b, saved.b, rtol=1e-6, atol=1e-8)
                and rebuilt.n == saved.n
            ):
                raise ValueError(f"{path}: window contents do not match the saved model of node {node_id!r}")
            models[node_id] = rebuilt

        self._samples = {node_id: s for node_id, s in samples.items() if s}
        self._order = deque(node_ids[i] for i in order)
        self._removals = {}
