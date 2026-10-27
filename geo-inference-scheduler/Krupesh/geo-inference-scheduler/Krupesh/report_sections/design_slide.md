# Design slide — owner: Krupesh

**Title:** How the router works

**Left half — diagram** (copy into the slide):

```
 user request ──► ROUTER ──────────────────────────────► chosen site
                  1 Filter   hard rules: model, memory,      │
                             power, temperature, status      │
                  2 Choose   baseline or (SW-)LinUCB         │ runs it
                  3 Log      one row per request             │
                  4 Learn    ◄──── outcome: TTFT, SLO met, cost
```

**Right half — three bullets:**

- **Safety first:** a site that breaks any hard rule is never chosen; if none is safe, the request is
  rejected on purpose and the reason is logged.
- **Same playing field:** every policy gets the same filtered sites through one interface, so only the
  choosing step differs between methods.
- **Real service, simulated sites:** FastAPI router with `/route`, `/feedback`, `/health`; GPU sites
  simulated; every number comes from the decision log.

**Speaker note (≈40 s):** "Each request goes through four steps. The filter removes sites that cannot
or must not take it — for example a site above 85 °C. A policy then chooses among the safe sites. We
log the decision, and when the site reports how long the request took, the policy learns from it. All
policies see exactly the same safe sites, so comparisons are fair."
