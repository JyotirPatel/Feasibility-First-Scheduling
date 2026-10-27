# Sur / standins (temporary)

**Owner:** Sur. These are **temporary placeholders** that let Sur test the policies and run the window sweep before Parikshit's simulator and Riya's metrics code existed. This is the same idea as `Jyotir/stubs/`.

| File | Stands in for | Status |
|---|---|---|
| `toy_cluster.py` + `toy_cluster.yaml` | Parikshit's node simulator, node configs and six scenario traces | **Replaced for the sweep:** it now runs on Parikshit's `simulator/` through Krupesh's router (`../window_sweep/parikshit_backend.py`). The stand-in stays for fast unit tests, `window_sweep/diagnostics.py` and the earlier results (`window_sweep/RESULTS_standin.md`). |
| `adaptation.py` | Riya's goodput / adaptation-time metric code | Still in use: Riya's `metrics/` has no adaptation-time code yet. Replace it when hers exists. |

## toy_cluster

This is a small event-driven simulator of 5 nodes that follows the brief's models:

- **Latency (§5):** TTFT = network + queue wait + prefill, with prefill = a_p + b_p·input tokens and decode = output tokens · t_tok · (1 + c·running/capacity).
- **Node state:** queue, running requests, KV cache, power headroom, temperature with thermal throttling, prices, and status up / down / warming.
- **Scenarios:** the six of §5. Each run is 600 s with the change at t0 = 200 s; in S6 the node returns at 400 s and needs a 60 s warm-up.
- **Formats:** the agreed field names for telemetry (§10.1), requests (§10.2) and decision-log rows (§10.3).

Every request goes through **Jyotir's real feasibility filter**, and only then through the policy:

- If the policy returns a node outside the filter's allowed list, `SafetyViolation` is raised.
- Each chosen node is also re-checked against the filter's limits, and failures are counted. That is how the known warming-node bug in Jyotir's filter was found: `tests/test_toy_cluster.py::test_s6_warming_node_respects_hard_rules`.

Arrivals depend only on the seed, so every policy gets the same requests. Every routed request gets exactly one feedback, including requests lost in an outage, which come back as failures.

**The numbers are made up to be plausible, not measured.** Anything produced with this simulator is preliminary. The window sweep has been re-run on Parikshit's simulator (`window_sweep/RESULTS.md`).

## adaptation

This implements the frozen definitions from work distribution §6: goodput in 1-s bins smoothed over 5 s, G* as the mean over t0+60 to t0+120 s, and adaptation time as the first moment G ≥ 0.9·G* holds for 10 s. A run that never gets there is "did not recover". It also computes the deepest dip. Two choices the definition leaves open are made here, and both are easy to change:
- a request counts in the bin of its arrival time;
- the moving average is trailing.

Lost goodput needs Riya's oracle, so it isn't computed here.

Tests: `tests/test_toy_cluster.py`, `tests/test_adaptation.py`.
