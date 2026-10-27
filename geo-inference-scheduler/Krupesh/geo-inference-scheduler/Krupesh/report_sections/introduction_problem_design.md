# Report sections owned by Krupesh: Introduction · Problem · System design

Draft for team review. No results are quoted here — Riya's results section supplies them.

## 1. Introduction

Large language models are now served from several data centers at once. A provider runs the same
model at five to ten sites and must send every user request to exactly one of them. The sites are not
equal: some are close to the user, some are cheaper to run, some are busy, some are hot or short on
power, and these conditions change during the day — traffic spikes, electricity prices move, cooling
fails, network paths degrade and whole sites go down and come back.

A good router must therefore do two things at once. First, it must never send a request to a site
that cannot or must not take it. Second, among the safe sites, it should pick the one that serves the
request well and cheaply, and keep doing so as conditions change.

This project builds and evaluates such a router. We contribute an integrated, feasibility-first,
change-aware scheduling loop for multi-site LLM inference and a recovery benchmark with six controlled
change events. Sliding-window LinUCB is an existing method that we use inside this loop.

## 2. Problem

**Setting.** N sites (5–10) each run a copy of the model. Requests arrive over time; each has a user
region, a model name, an input length, an expected output length and a time-to-first-token (TTFT)
service-level objective (SLO), e.g. 250 ms. Every second each site reports telemetry: network delay to
each region, queue length, running requests, capacity, KV-cache use, loaded models, power headroom,
temperature and prices, and its status (up, down, warming).

**Decision.** For each request, choose one site or reject the request.

**Hard constraints (must never be broken).** The chosen site must have the model loaded, enough
KV-cache memory for the request, power headroom above a limit, temperature below a limit, and a usable
status. If no site qualifies, the request is rejected on purpose with the reason "no feasible node".

**Objective.** Maximise SLO goodput (requests per second that meet their TTFT SLO) while keeping energy
and GPU cost per successful request low, and recover quickly after changes.

**Why it is hard.** The router only sees summary telemetry, and it is slightly old. The effect of a
choice (TTFT, cost) is known only after the request finishes. And the best site changes over time, so a
rule that was good before a change can be bad after it.

## 3. System design

```
 Workload (requests over time)          Event traces (6 scenarios)
            │                                     │
            ▼                                     ▼
 ┌──────────────────────────┐  telemetry  ┌───────────────────────────────┐
 │   ROUTER (HTTP, FastAPI) │ ◄────────── │  NODE SIMULATOR (5–10 sites)  │
 │ 1 feasibility filter     │  request    │  network + queue + prefill +  │
 │ 2 policy chooses         │ ──────────► │  decode, memory, power, heat, │
 │ 3 log the decision       │             │  price, up / down / warming   │
 │ 4 learn from feedback    │ ◄────────── │  outcome (TTFT, SLO met, cost)│
 └────────────┬─────────────┘             └───────────────────────────────┘
              ▼
   Decision log (one row per request) ──► metrics, confidence intervals, figures
```

**Components and owners.** Router service, API contract, decision log and integration — Krupesh.
Simulator, telemetry and event traces — Parikshit. Feasibility filter and baselines — Jyotir. LinUCB,
sliding-window LinUCB, context and reward — Sur. Metrics, experiments and report — Riya.

**Decision loop (per request).**
1. *Telemetry view.* The router keeps the latest record from each site and adds the requests it has
   itself sent since that record, so it does not overload one site between reports.
2. *Filter.* The feasibility filter removes unsafe sites and records a reason for each.
3. *Choose.* The policy picks one of the remaining sites. All policies — baselines and learning —
   receive the same filtered list through one interface: `choose(request, candidates)`.
4. *Guard.* If the policy returns a site that is not in the list, the router refuses to route.
5. *Log.* Rejections are logged immediately; routed requests are logged when their outcome arrives.
6. *Learn.* When the site reports the outcome, the router computes the reward and calls
   `update(request, site, outcome)`.

**Interfaces.** Three HTTP endpoints (`POST /route`, `POST /feedback`, `GET /health`) plus
`POST /telemetry`; a Python `Policy` interface; a filter function and a reward function as plug-in
points; and a decision log with 17 fixed columns. The same decision code runs in-process for fast
experiments and behind HTTP for the real service.

**Clocks.** Experiments use only simulated time. Real wall-clock time spent in the router is measured
and logged separately and never advances the simulation.

**Reproducibility.** Every run is defined by configuration files and a seed; every policy sees the same
requests and the same change events for a given seed.
