"""
Processed real data — owner: Parikshit

Reads the files in data/processed/, which data_sources/preprocess_traces.py builds from
public data (see data_sources/README.md for the sources and their terms):

  azure_<name>.csv.gz   Azure LLM inference traces: arrival offsets and token counts
  prices_hourly.csv     NYISO and CAISO day-ahead prices per zone and hour (UTC)
  rtt_ms.csv            median round-trip time between two cities (WonderProxy pings)

The simulator never reads the raw downloads.
"""

from __future__ import annotations

import csv
import gzip
import os
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from simulator.config import PROCESSED_DIR


@dataclass(frozen=True)
class Trace:
    """One processed Azure trace: requests in arrival order."""

    name: str
    t_s: np.ndarray  # seconds after the trace's first request
    input_tokens: np.ndarray
    output_tokens: np.ndarray

    @property
    def gaps_s(self) -> np.ndarray:
        return np.diff(self.t_s)

    @property
    def rate_rps(self) -> float:
        return (len(self.t_s) - 1) / float(self.t_s[-1] - self.t_s[0])

    @property
    def mean_input(self) -> float:
        return float(self.input_tokens.mean())

    @property
    def mean_output(self) -> float:
        return float(self.output_tokens.mean())


def load_trace(name: str, processed_dir: str = PROCESSED_DIR) -> Trace:
    path = os.path.join(processed_dir, f"{name}.csv.gz")
    with gzip.open(path, "rt", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 2:
        raise ValueError(f"{path}: needs at least two requests")
    t = np.array([float(r["t_s"]) for r in rows])
    if np.any(np.diff(t) < 0):
        raise ValueError(f"{path}: arrival times are not in order")
    return Trace(
        name,
        t,
        np.array([int(r["input_tokens"]) for r in rows]),
        np.array([int(r["output_tokens"]) for r in rows]),
    )


def _hour(t: datetime) -> datetime:
    if t.tzinfo is None:
        raise ValueError(f"{t} has no time zone")
    t = t.astimezone(UTC)
    if (t.minute, t.second, t.microsecond) != (0, 0, 0):
        raise ValueError(f"{t} is not a whole hour")
    return t


class Prices:
    """Hourly day-ahead price of each zone (raw $/MWh, which can be negative)."""

    def __init__(self, usd_mwh: dict[tuple[str, datetime], float]):
        self._usd_mwh = usd_mwh

    @property
    def zones(self) -> list[str]:
        return sorted({zone for zone, _ in self._usd_mwh})

    def usd_mwh(self, zone: str, hour_utc: datetime) -> float:
        key = (zone, _hour(hour_utc))
        if key not in self._usd_mwh:
            raise KeyError(f"no price for zone {zone!r} at {key[1].isoformat()} in prices_hourly.csv")
        return self._usd_mwh[key]

    def usd_kwh(self, zone: str, hour_utc: datetime, floor_usd_kwh: float) -> float:
        """The price a node reports: $/MWh / 1000, floored (wholesale prices can be negative)."""
        return max(self.usd_mwh(zone, hour_utc) / 1000.0, floor_usd_kwh)


def load_prices(processed_dir: str = PROCESSED_DIR) -> Prices:
    table = {}
    with open(os.path.join(processed_dir, "prices_hourly.csv"), newline="") as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["t_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            table[(r["zone"], t)] = float(r["lbmp_usd_mwh"])
    return Prices(table)


class RttTable:
    """Median round-trip time between two cities, the same in both directions."""

    def __init__(self, ms: dict[tuple[str, str], float]):
        self._ms = ms

    @property
    def cities(self) -> list[str]:
        return sorted({c for pair in self._ms for c in pair})

    def ms(self, city_a: str, city_b: str, floor_ms: float) -> float:
        """RTT between the cities; a user in the node's own city gets floor_ms (a server pinging itself reads ~0)."""
        if city_a == city_b:
            if city_a not in self.cities:
                raise KeyError(f"unknown city {city_a!r} in rtt_ms.csv")
            return floor_ms
        key = (min(city_a, city_b), max(city_a, city_b))
        if key not in self._ms:
            raise KeyError(f"no RTT between {city_a!r} and {city_b!r} in rtt_ms.csv")
        return max(self._ms[key], floor_ms)


def load_rtt(processed_dir: str = PROCESSED_DIR) -> RttTable:
    table = {}
    with open(os.path.join(processed_dir, "rtt_ms.csv"), newline="") as f:
        for r in csv.DictReader(f):
            table[(r["city_a"], r["city_b"])] = float(r["rtt_ms"])
    return RttTable(table)
