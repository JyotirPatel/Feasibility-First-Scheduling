"""The checkpoint files shipped in checkpoints/standin/ are valid and load into their policies."""

import glob
import json
import os

import numpy as np
import pytest

from linucb import LinUCB
from sliding_window_linucb import SlidingWindowLinUCB
from sur_factories import SUR_DIR, make_node, make_request

FILES = sorted(glob.glob(os.path.join(SUR_DIR, "checkpoints", "standin", "*.npz")))
POLICIES = {"linucb": LinUCB, "sw_linucb": SlidingWindowLinUCB}


@pytest.mark.skipif(not FILES, reason="no checkpoints yet (run window_sweep/run_sweep.py)")
@pytest.mark.parametrize("path", FILES, ids=os.path.basename)
def test_shipped_checkpoint_loads_and_scores(path):
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
    policy = POLICIES[meta["policy"]](meta["config"])  # the exact config it was saved with
    policy.load_checkpoint(path)
    assert sum(policy.model_counts().values()) > 0  # it really learned something
    rows = policy.explain(make_request(), [make_node(n) for n in policy.model_counts()])
    assert all(np.isfinite(r["score"]) for r in rows)
