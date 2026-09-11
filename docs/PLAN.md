# Karkinos Plan

## Current focus

**Engineering Reset and platform reliability**

```text
Market Data
-> PIT Dataset
-> Research / Evaluation
-> Published Forecast
-> Portfolio
-> Simulation / Shadow
-> Accounting / Attribution
-> Evidence / Feedback
```

## In scope

- Align code with the canonical architecture.
- Classify major areas as **KEEP**, **SIMPLIFY**, **FREEZE**, **DELETE**, or **REPLACE**.
- Stabilize data acquisition, normalization, PIT publication, freshness, revision handling, and failure recovery.
- Restore Dataset -> Research -> Published Forecast -> Portfolio -> Simulation flow.
- Keep core platform capabilities usable without AI providers or AI orchestration.
- Remove accidental acceptance, conformance, compatibility, runtime, and infrastructure complexity.
- Validate a small set of high-value local product journeys.
- Keep CI focused on behavior, financial semantics, persisted compatibility, security, and runtime correctness.

## Frozen

- new live-trading or broker integrations;
- automatic capital-authority infrastructure;
- autonomous AI trading;
- new AI orchestration frameworks;
- new acceptance or conformance frameworks;
- hosted accounts, cloud control planes, or cloud sync;
- unrelated product features;
- architecture-driven microservice or language rewrites.

Maintenance fixes remain allowed for user data, security, financial correctness, persisted compatibility, and currently supported behavior.

## Exit criteria

- Major code areas have explicit reset classifications.
- Meaningful accidental complexity is removed or frozen.
- Data -> PIT Dataset is reliable, observable, and replayable.
- Research, Portfolio, Simulation, Accounting, and feedback boundaries are clear and work end to end.
- Core platform workflows work without AI orchestration.
- Local development and runtime behavior are predictable.
- A small set of real product journeys passes reliably.
- Tests and CI protect behavior and semantics rather than obsolete repository structure.
