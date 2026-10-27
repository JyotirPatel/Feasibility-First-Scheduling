"""Jyotir's ORIGINAL code behind Krupesh's interfaces. Nothing in Jyotir/ is edited."""

import subprocess
import sys

import pytest

from integration.jyotir_adapter import (
    JYOTIR_BASELINES,
    JYOTIR_DIR,
    JyotirBaseline,
    make_jyotir_filter,
)
from kr_helpers import node, request


def test_jyotir_own_tests_still_pass():
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "-q",
            "-p",
            "no:cacheprovider",
            "edge_case_tests",
        ],
        cwd=JYOTIR_DIR,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and r.stdout.count(".") >= 14, r.stdout + r.stderr


def test_jyotir_folder_unmodified():
    # Outside a git checkout `git diff` errors with exit code 1, which looks like "modified";
    # only run the check when Jyotir's commit 6c699f7 is actually in the local history.
    has_commit = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "6c699f7^{commit}"],
        cwd=JYOTIR_DIR,
        capture_output=True,
    )
    if has_commit.returncode != 0:
        pytest.skip("not inside a git checkout that contains Jyotir's commit 6c699f7")
    r = subprocess.run(
        ["git", "diff", "--quiet", "6c699f7", "--", str(JYOTIR_DIR)],
        cwd=JYOTIR_DIR,
        capture_output=True,
    )
    assert r.returncode == 0, "files under Jyotir/ differ from Jyotir's commit 6c699f7"


def test_filter_uses_jyotir_config_and_reasons():
    f = make_jyotir_filter()
    assert f.config["temperature_limit_c"] == 85.0
    res = f(
        request(),
        [
            node("ok"),
            node("down", status="down"),
            node("hot", temperature_c=90),
            node("full", kv_used_frac=0.95),
            node("nopower", power_headroom_kw=0.5),
            node("nomodel", models_loaded=["other"]),
        ],
    )
    assert res.allowed_ids == ["ok"]
    assert res.rejected == {
        "down": "node_down",
        "hot": "temperature_high",
        "full": "memory_full",
        "nopower": "power_limit",
        "nomodel": "model_missing",
    }


def test_known_issue_F1_warming_bypass_is_documented_not_fixed():
    res = make_jyotir_filter()(request(), [node("w", status="warming", temperature_c=99)])
    assert res.allowed_ids == ["w"]  # Jyotir to decide on the proposed fix


@pytest.mark.parametrize("name", sorted(JYOTIR_BASELINES))
def test_every_jyotir_baseline_through_policy_interface(name):
    nodes = [node("a", rtt_ms={"nyc": 5}, running=20), node("b", rtt_ms={"nyc": 50}, running=0)]
    assert JyotirBaseline(seed=1, baseline=name).choose(request(), nodes) in {"a", "b"}


def test_min_rtt_and_least_load_semantics_preserved():
    nodes = [
        node("near", rtt_ms={"nyc": 5}, running=20),
        node("idle", rtt_ms={"nyc": 50}, running=0),
    ]
    assert JyotirBaseline(baseline="min_rtt").choose(request(), nodes) == "near"
    assert JyotirBaseline(baseline="least_load").choose(request(), nodes) == "idle"
