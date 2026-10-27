"""
Workload — owner: Parikshit

Builds every request of one run before the run starts, from the processed Azure traces, the
workload config and a seed. The same (scenario, seed) always gives exactly the same
requests, so every policy is compared on the same input (brief §8, handbook §5.2).

For each request class (configs/workload.yaml):
  arrivals  trace_gaps: inter-arrival gaps resampled from the class's trace and rescaled
            to the class rate (share × rate_rps), so the gaps keep the trace's shape.
            poisson: exponential gaps at the class rate.
  tokens    an (input, output) pair drawn from the class's trace, so the two stay as
            correlated as in production.
  region    drawn with probability proportional to the region's population.
  estimate  expected_output_tokens = true output × U(1 - e, 1 + e), rounded, at least 1;
            the router sees the estimate, the node generates the true number.

S2 (an arrival_rate event) adds, during its window, one more stream per class at
(factor - 1) × the class rate. Every (class, stream) pair has its own random generator, so
the requests of the base streams are identical in all six scenarios: S2 only adds requests.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

from simulator.config import ArrivalRate, ClassSpec, Scenario, WorkloadConfig
from simulator.data import Trace


@dataclass(frozen=True)
class WorkItem:
    """One request as the router sees it, plus the true output length only the node knows."""

    request: dict  # brief §10.2 fields: request_id, t_arrival, user_region, model, tokens, slo_class, ttft_slo_ms
    output_tokens: int


def _rng(seed: int, cls: str, stream: int) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(f"{cls}|{stream}".encode())])


def _arrival_times(rng: np.random.Generator, spec: ClassSpec, trace: Trace, rate: float, start: float, end: float):
    """Arrival times in [start, end) of one stream at `rate` requests per second."""
    gaps_seen, times, t = trace.gaps_s, [], start
    batch = max(int(rate * (end - start) * 1.2) + 16, 16)
    while True:
        if spec.arrivals == "trace_gaps":
            gaps = rng.choice(gaps_seen, size=batch) * (trace.rate_rps / rate)
        else:
            gaps = rng.exponential(1.0 / rate, size=batch)
        chunk = t + np.cumsum(gaps)
        inside = chunk[chunk < end]
        times.append(inside)
        if len(inside) < batch:
            return np.concatenate(times)
        t = float(chunk[-1])


def _streams(workload: WorkloadConfig, scenario: Scenario):
    """(class, stream number, start, end, rate) for the base streams and every S2 burst."""
    bursts = [e for e in scenario.events if isinstance(e, ArrivalRate) and e.factor > 1]
    for cls in sorted(workload.classes):
        rate = workload.rate_rps * workload.classes[cls].share
        yield cls, 0, 0.0, scenario.duration_s, rate
        for i, e in enumerate(sorted(bursts, key=lambda e: e.at_s), start=1):
            yield cls, i, e.at_s, e.at_s + e.duration_s, rate * (e.factor - 1)


def generate(workload: WorkloadConfig, scenario: Scenario, seed: int, traces: dict[str, Trace]) -> list[WorkItem]:
    regions = sorted(workload.regions)
    weights = np.array([workload.regions[r].population for r in regions], dtype=float)
    region_p = weights / weights.sum()
    err = workload.expected_output_error

    rows = []  # (t, class, stream, k, region, input, output, estimate)
    for cls, stream, start, end, rate in _streams(workload, scenario):
        spec, trace = workload.classes[cls], traces[workload.classes[cls].trace]
        rng = _rng(seed, cls, stream)
        times = _arrival_times(rng, spec, trace, rate, start, end)
        n = len(times)
        pick = rng.integers(0, len(trace.t_s), size=n)
        region_idx = rng.choice(len(regions), size=n, p=region_p)
        factor = rng.uniform(1.0 - err, 1.0 + err, size=n)
        inputs, outputs = trace.input_tokens[pick], trace.output_tokens[pick]
        estimates = np.maximum(np.rint(outputs * factor), 1).astype(int)
        for k in range(n):
            rows.append(
                (
                    float(times[k]),
                    cls,
                    stream,
                    k,
                    regions[region_idx[k]],
                    int(inputs[k]),
                    int(outputs[k]),
                    int(estimates[k]),
                )
            )
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))

    items = []
    for i, (t, cls, _, _, region, inp, out, est) in enumerate(rows):
        request = {
            "request_id": f"r-{i:06d}",
            "t_arrival": t,
            "user_region": region,
            "model": workload.model,
            "input_tokens": inp,
            "expected_output_tokens": est,
            "slo_class": cls,
            "ttft_slo_ms": workload.classes[cls].ttft_slo_ms,
        }
        items.append(WorkItem(request, out))
    return items
