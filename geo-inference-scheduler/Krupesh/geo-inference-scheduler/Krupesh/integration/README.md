# Krupesh / integration

**Owner:** Krupesh. Connects teammates' modules to the router and tests the whole loop.

| File | What |
|---|---|
| `jyotir_adapter.py` | Jyotir's **original, unmodified** filter + 6 baselines behind the router's interfaces (reads his own `feasibility.yaml`) |
| `run_end_to_end.py` | Closed loop: simulator → router → node → delayed feedback → reward → update → decision log (in-process or HTTP) |
| `integration_guide.md` | How each teammate plugs in, and what is still needed from them |
| `mocks/` | **TEMPORARY MOCKS** of modules that do not exist yet: `mock_simulator.py` (Parikshit), `mock_policy.py` + `mock_reward.py` (Sur). Not their implementations — delete each one when the owner's module is connected |

Run: `python -m integration.run_end_to_end [--policy mock:learning] [--outage] [--mode http --url ...]`
