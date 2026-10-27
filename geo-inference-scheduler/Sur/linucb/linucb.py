"""
Plain LinUCB (Li et al., 2010) — owner: Sur

One linear model per node a: a matrix A_a (d×d) and a vector b_a (d),
starting at A_a = λI and b_a = 0 (brief §6.4).

  estimate : θ_a = A_a⁻¹ b_a
  score    : score_a = θ_aᵀx + α·√(xᵀ A_a⁻¹ x)    predicted reward + exploration bonus
  choose   : the candidate with the highest score (exact ties broken at random, seeded)
  update   : only the chosen node:  A_a ← A_a + x xᵀ,  b_a ← b_a + r·x

`candidates` are the nodes the feasibility filter allowed: the router runs
the filter first and passes only its allowed list, and choose() always
returns the node_id of one of those candidates.

Plain LinUCB never forgets. It is the "no forgetting" ablation of the
sliding-window version in sliding_window_linucb/.

Delayed feedback: the outcome arrives seconds after the decision
(POST /feedback), and the node's telemetry has changed by then. So choose()
remembers, per request_id, the exact context vector x it used and the node
numbers the reward needs (temperature, electricity price). update() learns
from those, never from newer telemetry. update() always computes the reward
itself with reward.compute_reward() and ignores outcome.reward, so a
placeholder value from the router cannot corrupt learning; the value used is
kept in `last_reward` for the decision log.

Feedback for an unknown request_id (never chosen, already updated, or
dropped because more than max_pending decisions were waiting) is ignored and
counted in `stats`, so nothing is ever learned twice.

Interface: subclasses the shared Policy stub in Jyotir/stubs/stub_policy.py,
the stand-in for Krupesh's base class, exactly like Jyotir's baselines, so the
router can swap any policy with one config line. When Krupesh publishes the
real base class, change only the `from stubs.stub_policy import ...` line.

All numbers (alpha, lambda, feature ranges, reward weights) come from
configs/policies/linucb.yaml. choose() and update() take a lock, so the
router may call them from several threads.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

_SUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JYOTIR_DIR = os.path.join(os.path.dirname(_SUR_DIR), "Jyotir")
for _path in (_SUR_DIR, _JYOTIR_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from context_vector import ContextBuilder, FeatureConfig  # noqa: E402
from reward import NODE_FIELDS, RewardConfig, compute_reward  # noqa: E402
from stubs.stub_policy import Outcome, Policy  # noqa: E402  (stand-in for Krupesh's interface)

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(_SUR_DIR, "configs", "policies")
CHECKPOINT_FORMAT = "sur-linucb-checkpoint"
CHECKPOINT_VERSION = 1


# ── Config ───────────────────────────────────────────────────────────────────


class BanditConfig(BaseModel):
    """Settings shared by plain and sliding-window LinUCB."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    alpha: float = Field(ge=0)
    lambda_: float = Field(gt=0, alias="lambda")
    seed: int
    max_pending: int = Field(gt=0)
    features: FeatureConfig
    reward: RewardConfig


class LinUCBConfig(BanditConfig):
    policy: Literal["linucb"]


def load_config(path: str | os.PathLike | None = None) -> LinUCBConfig:
    """Load and check configs/policies/linucb.yaml (or another file)."""
    return load_yaml_config(path or LinUCB.default_config_path, LinUCBConfig)


def load_yaml_config(path: str | os.PathLike, model: type[BanditConfig]) -> BanditConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return model.model_validate(data)


# ── Per-node model ───────────────────────────────────────────────────────────


class _NodeModel:
    """A_a and b_a for one node, plus the cached A_a⁻¹ and θ_a used for scoring."""

    __slots__ = ("lam", "A", "b", "A_inv", "theta", "n")

    def __init__(self, dim: int, lam: float):
        self.lam = lam
        self.A = lam * np.eye(dim)
        self.b = np.zeros(dim)
        self.n = 0  # outcomes currently in the model
        self._refresh()

    def reset(self) -> None:
        dim = self.b.shape[0]
        self.A = self.lam * np.eye(dim)
        self.b = np.zeros(dim)
        self.n = 0
        self._refresh()

    def add(self, x: np.ndarray, r: float) -> None:
        self.A += np.outer(x, x)
        self.b += r * x
        self.n += 1
        self._refresh()

    def remove(self, x: np.ndarray, r: float) -> None:
        self.A -= np.outer(x, x)
        self.b -= r * x
        self.n -= 1
        self._refresh()

    def rebuild(self, samples) -> None:
        """Recompute A and b exactly from (x, r) pairs."""
        samples = list(samples)
        if not samples:
            self.reset()
            return
        X = np.array([x for x, _ in samples], dtype=float)
        R = np.array([r for _, r in samples], dtype=float)
        self.A = self.lam * np.eye(X.shape[1]) + X.T @ X
        self.b = X.T @ R
        self.n = len(samples)
        self._refresh()

    def estimate_and_bonus(self, x: np.ndarray) -> tuple[float, float]:
        """(θᵀx, √(xᵀA⁻¹x)) — the bonus is multiplied by α by the caller."""
        return float(self.theta @ x), math.sqrt(max(float(x @ self.A_inv @ x), 0.0))

    def _refresh(self) -> None:
        self.A_inv = np.linalg.inv(self.A)
        self.theta = self.A_inv @ self.b


@dataclass(frozen=True)
class _Decision:
    node_id: str
    x: np.ndarray
    node: dict  # the node numbers the reward needs, copied at decision time


# ── Policy ───────────────────────────────────────────────────────────────────


class LinUCB(Policy):
    """Plain LinUCB policy (never forgets). See the module docstring."""

    name: ClassVar[str] = "linucb"
    config_model: ClassVar[type[BanditConfig]] = LinUCBConfig
    default_config_path: ClassVar[str] = os.path.join(CONFIG_DIR, "linucb.yaml")
    # Config sections that define the learned state; a checkpoint only loads if these match.
    _state_keys: ClassVar[tuple[str, ...]] = ("lambda", "features", "reward")

    def __init__(self, config: Any = None, *, seed: int | None = None):
        """
        config : None (the default YAML file), a path to a YAML file, a dict,
                 or an already-checked config object.
        seed   : overrides the config's tie-breaking seed (the experiment
                 runner passes one seed per run).
        """
        self.config = self._resolve_config(config)
        self.alpha = self.config.alpha
        self.lam = self.config.lambda_
        self.features = ContextBuilder(self.config.features)
        self.dim = self.features.dim
        self.seed = self.config.seed if seed is None else seed
        self._rng = np.random.default_rng(self.seed)
        self._models: dict[str, _NodeModel] = {}
        self._pending: OrderedDict[str, _Decision] = OrderedDict()
        self._lock = threading.RLock()
        self.last_reward: float | None = None
        self.stats = {"decisions": 0, "updates": 0, "ignored_feedback": 0, "dropped_pending": 0}

    @classmethod
    def _resolve_config(cls, config: Any) -> BanditConfig:
        if config is None:
            config = cls.default_config_path
        if isinstance(config, cls.config_model):
            return config
        if isinstance(config, (str, os.PathLike)):
            return load_yaml_config(config, cls.config_model)
        if isinstance(config, Mapping):
            return cls.config_model.model_validate(dict(config))
        raise TypeError(f"{cls.__name__}: unsupported config of type {type(config).__name__}")

    # ── Policy interface ─────────────────────────────────────────────────────

    def choose(self, request: dict, candidates: list[dict]) -> str:
        """
        Score every feasible candidate and return the node_id with the highest
        score. candidates is already filtered by the feasibility filter.
        """
        if not candidates:
            raise ValueError("No feasible candidates — router should have rejected this request.")
        request_id = _request_id(request)

        with self._lock:
            node_ids, xs, scores = [], [], []
            for node in candidates:
                node_id = _node_id(node)
                x = self.features.build(request, node)
                estimate, bonus = self._model(node_id).estimate_and_bonus(x)
                node_ids.append(node_id)
                xs.append(x)
                scores.append(estimate + self.alpha * bonus)

            best = self._pick(scores)
            self._remember(request_id, _Decision(node_ids[best], xs[best], _reward_inputs(candidates[best])))
            self.stats["decisions"] += 1
            return node_ids[best]

    def update(self, request: dict, node_id: str, outcome: Outcome) -> None:
        """Learn from the outcome of a request this policy routed."""
        request_id = _request_id(request)

        with self._lock:
            decision = self._pending.get(request_id)
            if decision is None:
                self._ignore(f"feedback for unknown or already-updated request {request_id!r}")
                return
            if node_id != decision.node_id:
                del self._pending[request_id]
                self._ignore(
                    f"feedback for {request_id!r} names node {node_id!r}, but the policy chose {decision.node_id!r}"
                )
                return

            # Compute first: if the outcome is malformed this raises and the
            # decision stays pending, so a corrected retry can still be learned.
            r = compute_reward(decision.node, outcome, self.config.reward)
            del self._pending[request_id]
            self._learn(decision.node_id, decision.x, r)
            self.last_reward = r
            self.stats["updates"] += 1

    # ── Inspection (read-only) ───────────────────────────────────────────────

    def explain(self, request: dict, candidates: list[dict]) -> list[dict]:
        """Per-candidate estimate, bonus and score, without recording a decision."""
        with self._lock:
            rows = []
            for node in candidates:
                node_id = _node_id(node)
                model = self._models.get(node_id) or _NodeModel(self.dim, self.lam)
                estimate, bonus = model.estimate_and_bonus(self.features.build(request, node))
                rows.append(
                    {
                        "node_id": node_id,
                        "estimate": estimate,
                        "bonus": self.alpha * bonus,
                        "score": estimate + self.alpha * bonus,
                        "n": model.n,
                    }
                )
            return rows

    def theta(self, node_id: str) -> np.ndarray:
        """Learned weights θ_a for one node (a copy), aligned with self.features.names."""
        with self._lock:
            return self._models[node_id].theta.copy()

    def model_counts(self) -> dict[str, int]:
        """Number of outcomes currently inside each node's model."""
        with self._lock:
            return {node_id: m.n for node_id, m in self._models.items()}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # ── Checkpoints ──────────────────────────────────────────────────────────

    def save_checkpoint(self, path: str | os.PathLike) -> None:
        """
        Save the learned state to a .npz file (no pickle). Decisions still
        waiting for feedback are not saved, so save between runs.
        """
        with self._lock:
            node_ids = sorted(self._models)
            arrays = {
                "node_ids": np.array(node_ids, dtype=str),
                "A": np.array([self._models[n].A for n in node_ids], dtype=float).reshape(-1, self.dim, self.dim),
                "b": np.array([self._models[n].b for n in node_ids], dtype=float).reshape(-1, self.dim),
                "n": np.array([self._models[n].n for n in node_ids], dtype=np.int64),
            }
            arrays.update(self._extra_checkpoint_arrays(node_ids))
            meta = {
                "format": CHECKPOINT_FORMAT,
                "version": CHECKPOINT_VERSION,
                "policy": self.name,
                "feature_names": self.features.names,
                "config": self.config.model_dump(mode="json", by_alias=True),
                "seed": self.seed,
                "rng_state": self._rng.bit_generator.state,
                "stats": dict(self.stats),
                "saved_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            arrays["meta"] = np.array(json.dumps(meta))
            _atomic_savez(path, arrays)

    def load_checkpoint(self, path: str | os.PathLike) -> None:
        """Load a checkpoint saved by the same policy type with the same state-defining config."""
        with np.load(path, allow_pickle=False) as data:
            arrays = {key: data[key] for key in data.files}
        if "meta" not in arrays:
            raise ValueError(f"{path}: not a LinUCB checkpoint (no meta)")
        meta = json.loads(str(arrays["meta"]))
        self._check_meta(meta, path)

        node_ids = [str(n) for n in arrays["node_ids"]]
        A, b, n = arrays["A"], arrays["b"], arrays["n"]
        k = len(node_ids)
        if A.shape != (k, self.dim, self.dim) or b.shape != (k, self.dim) or n.shape != (k,):
            raise ValueError(f"{path}: array shapes do not match {k} nodes × {self.dim} features")
        if not (np.all(np.isfinite(A)) and np.all(np.isfinite(b))) or np.any(n < 0):
            raise ValueError(f"{path}: checkpoint contains invalid numbers")

        models = {}
        for i, node_id in enumerate(node_ids):
            try:
                np.linalg.cholesky(A[i])  # A must be symmetric positive definite
            except np.linalg.LinAlgError:
                raise ValueError(f"{path}: A for node {node_id!r} is not positive definite") from None
            model = _NodeModel(self.dim, self.lam)
            model.A = A[i].astype(float).copy()
            model.b = b[i].astype(float).copy()
            model.n = int(n[i])
            model._refresh()
            models[node_id] = model

        with self._lock:
            self._restore_extra(models, node_ids, arrays, path)
            self._models = models
            self._pending.clear()
            self._rng.bit_generator.state = meta["rng_state"]
            self.seed = meta.get("seed", self.seed)  # the random state now comes from the checkpoint's run
            self.stats = {key: int(meta["stats"].get(key, 0)) for key in self.stats}
            self.last_reward = None

    # ── Internals (sliding-window LinUCB overrides some of these) ────────────

    def _model(self, node_id: str) -> _NodeModel:
        model = self._models.get(node_id)
        if model is None:
            model = self._models[node_id] = _NodeModel(self.dim, self.lam)
        return model

    def _learn(self, node_id: str, x: np.ndarray, r: float) -> None:
        self._model(node_id).add(x, r)

    def _pick(self, scores: list[float]) -> int:
        s = np.asarray(scores, dtype=float)
        if not np.all(np.isfinite(s)):
            raise RuntimeError(f"{self.name}: non-finite score {scores}; the model state is corrupted")
        top = s.max()
        ties = np.flatnonzero(s >= top - 1e-12 * max(1.0, abs(top)))
        return int(ties[0]) if ties.size == 1 else int(self._rng.choice(ties))

    def _remember(self, request_id: str, decision: _Decision) -> None:
        self._pending.pop(request_id, None)  # re-routed request: keep only the latest decision
        self._pending[request_id] = decision
        while len(self._pending) > self.config.max_pending:
            dropped, _ = self._pending.popitem(last=False)
            self.stats["dropped_pending"] += 1
            logger.warning(
                "%s: no feedback for %s; dropped its decision (max_pending=%d)",
                self.name,
                dropped,
                self.config.max_pending,
            )

    def _ignore(self, why: str) -> None:
        self.last_reward = None
        self.stats["ignored_feedback"] += 1
        logger.warning("%s: ignored %s", self.name, why)

    def _check_meta(self, meta: dict, path: Any) -> None:
        if meta.get("format") != CHECKPOINT_FORMAT or meta.get("version") != CHECKPOINT_VERSION:
            raise ValueError(f"{path}: unsupported checkpoint format {meta.get('format')!r} v{meta.get('version')!r}")
        if meta.get("policy") != self.name:
            raise ValueError(f"{path}: checkpoint is for policy {meta.get('policy')!r}, not {self.name!r}")
        if meta.get("feature_names") != self.features.names:
            raise ValueError(f"{path}: checkpoint features differ from this config's features")
        current = self.config.model_dump(mode="json", by_alias=True)
        saved = meta.get("config", {})
        differing = [key for key in self._state_keys if saved.get(key) != current.get(key)]
        if differing:
            raise ValueError(f"{path}: checkpoint config differs in {differing}; it cannot be loaded into this policy")

    def _extra_checkpoint_arrays(self, node_ids: list[str]) -> dict[str, np.ndarray]:
        return {}

    def _restore_extra(self, models: dict, node_ids: list[str], arrays: dict, path: Any) -> None:
        pass


# ── Helpers ──────────────────────────────────────────────────────────────────


def _request_id(request: Any) -> str:
    rid = request.get("request_id") if isinstance(request, Mapping) else getattr(request, "request_id", None)
    if rid is None or rid == "":
        raise ValueError("LinUCB needs request['request_id'] to match the feedback to its decision")
    return str(rid)


def _node_id(node: Any) -> str:
    node_id = node.get("node_id") if isinstance(node, Mapping) else getattr(node, "node_id", None)
    if node_id is None:
        raise KeyError("candidate node has no 'node_id'")
    return node_id


def _reward_inputs(node: Any) -> dict:
    """Copy the node numbers the reward needs, so later telemetry cannot change them."""
    values = {"node_id": _node_id(node)}
    for key in NODE_FIELDS:
        value = node.get(key) if isinstance(node, Mapping) else getattr(node, key, None)
        if value is None:
            raise KeyError(f"candidate node {values['node_id']!r} has no '{key}' (needed for the reward)")
        values[key] = value
    return values


def _atomic_savez(path: str | os.PathLike, arrays: dict[str, np.ndarray]) -> None:
    """Write to a temporary file, then rename, so a crash never leaves half a checkpoint."""
    path = os.fspath(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        np.savez_compressed(f, **arrays)
    os.replace(tmp, path)
