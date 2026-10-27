"""Telemetry schema v1: the JSON Schema file, the Python validator, and what the simulator reports every tick."""

import copy
import json

import jsonschema
import numpy as np
import pytest

from helpers import PinRouter, light_workload, short_scenario
from simulator.cluster import Simulation
from simulator.config import scenario_names
from telemetry.schema import OPTIONAL_FIELDS, REQUIRED_FIELDS, SCHEMA_VERSION, load_schema, validate_record

SCHEMA = load_schema()
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)

GOOD = {
    "schema_version": "1.0",
    "t": 312.0,
    "node_id": "us-east-nyc",
    "status": "up",
    "rtt_ms": {"nyc": 2.0, "chi": 21.7},
    "queue_len": 7,
    "running": 22,
    "capacity": 360,
    "kv_used_frac": 0.04,
    "models_loaded": ["llama-3-8b"],
    "power_headroom_kw": 4.5,
    "temperature_c": 51.0,
    "energy_price_usd_kwh": 0.027,
    "gpu_price_usd_hr": 3.99,
    "kv_capacity_tokens": 3414304,
}


def test_schema_file_is_a_valid_json_schema_and_matches_the_module():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert tuple(SCHEMA["required"]) == REQUIRED_FIELDS
    assert set(SCHEMA["properties"]) == set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)
    assert SCHEMA["additionalProperties"] is False


def test_the_brief_example_record_is_valid():
    brief = {  # Project Brief §10.1, verbatim
        "schema_version": "1.0",
        "t": 312.0,
        "node_id": "us-east-1",
        "status": "up",
        "rtt_ms": {"nyc": 12, "chi": 25, "sfo": 70},
        "queue_len": 7,
        "running": 22,
        "capacity": 32,
        "kv_used_frac": 0.68,
        "models_loaded": ["llama-3-8b"],
        "power_headroom_kw": 4.5,
        "temperature_c": 71.0,
        "energy_price_usd_kwh": 0.11,
        "gpu_price_usd_hr": 2.40,
    }
    assert validate_record(brief) == [] and VALIDATOR.is_valid(brief)


@pytest.mark.parametrize(
    "change,needle",
    [
        ({"schema_version": "2.0"}, "schema_version"),
        ({"status": "off"}, "status"),
        ({"running": -1}, "running"),
        ({"running": True}, "running"),  # a bool is not an integer here
        ({"capacity": 0}, "capacity"),
        ({"running": 400}, "exceed capacity"),
        ({"kv_used_frac": 1.2}, "kv_used_frac"),
        ({"rtt_ms": {}}, "rtt_ms"),
        ({"rtt_ms": {"nyc": -3}}, "rtt_ms"),
        ({"models_loaded": ["a", "a"]}, "models_loaded"),
        ({"power_headroom_kw": float("nan")}, "power_headroom_kw"),
        ({"energy_price_usd_kwh": -0.01}, "energy_price"),
        ({"temperature_c": 400.0}, "temperature_c"),
        ({"kv_capacity_tokens": 0}, "kv_capacity_tokens"),
        ({"status": "down"}, "down node"),  # but it still has running requests
    ],
)
def test_bad_records_are_rejected(change, needle):
    problems = validate_record({**GOOD, **change})
    assert any(needle in p for p in problems), problems


def test_missing_and_unknown_fields():
    rec = dict(GOOD)
    del rec["temperature_c"]
    assert validate_record(rec) == ["missing field temperature_c"]
    assert validate_record({**GOOD, "colour": "blue"}) == ["unknown field colour"]
    assert validate_record({**GOOD, "kv_capacity_tokens": None}) == []
    assert validate_record("not a record")


INTEGER_FIELDS = ("queue_len", "running", "capacity", "kv_capacity_tokens")


def _random_record(rng):
    rec = copy.deepcopy(GOOD)
    key = rng.choice([*REQUIRED_FIELDS, "kv_capacity_tokens", "none"])
    options = [-5, -0.5, 0, 0.5, 1, 7, 1e9, True, "x", None, [], {}, ["llama-3-8b"], {"nyc": 3}, "1.3", "up"]
    if key != "none":
        rec[key] = options[rng.integers(len(options))]
    return rec, key


def test_python_validator_agrees_with_jsonschema_on_random_records():
    """Wherever only single-field rules apply, validate_record and the JSON Schema must agree."""
    rng = np.random.default_rng(3)
    checked = 0
    for _ in range(4000):
        rec, key = _random_record(rng)
        ours = validate_record(rec)
        if any("exceed capacity" in p or "down node" in p for p in ours):
            continue  # rules across fields, which JSON Schema cannot express
        value = rec.get(key)
        if key in INTEGER_FIELDS and isinstance(value, float) and value.is_integer():
            # JSON Schema counts 1e9 as an integer; like Krupesh's router (isinstance int) we do not
            assert ours and VALIDATOR.is_valid(rec)
            continue
        assert (ours == []) == VALIDATOR.is_valid(rec), (rec, ours, [e.message for e in VALIDATOR.iter_errors(rec)])
        checked += 1
    assert checked > 3500


@pytest.mark.parametrize("name", scenario_names())
def test_every_tick_of_every_scenario_is_valid(name):
    """The simulator reports one valid record per node per tick, in every scenario (handbook §5.2)."""
    router = PinRouter("us-west-sjc")
    sim = Simulation(router, short_scenario(name), 0, workload=light_workload(), validate_telemetry=False)
    sim.run()
    assert len(router.ticks) == int(sim.scenario.duration_s / sim.cluster.tick_s)
    for tick in router.ticks:
        assert [r["node_id"] for r in tick] == [n.node_id for n in sim.cluster.nodes]
        assert len({r["t"] for r in tick}) == 1
        for r in tick:
            assert validate_record(r) == [], r
            assert VALIDATOR.is_valid(json.loads(json.dumps(r))), r
            assert r["schema_version"] == SCHEMA_VERSION


def test_krupesh_router_accepts_the_records():
    """Krupesh's router validates telemetry at its HTTP boundary; every record must pass his check too."""
    from simulator.routers import use_krupesh

    use_krupesh()
    from api_contract.schemas import validate_telemetry
    from api_contract.types import NodeState

    router = PinRouter("us-east-nyc")
    Simulation(router, short_scenario("s6_outage_recovery"), 1, workload=light_workload()).run()
    for tick in router.ticks:
        for r in tick:
            assert validate_telemetry(r) == []
            assert NodeState.from_dict(r).to_dict() == r  # every field survives his type unchanged
