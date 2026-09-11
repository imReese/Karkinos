# Karkinos Plan

This document defines the current development scope.

## Current focus — Engineering Reset and platform reliability

Karkinos currently has more implementation complexity than its core quantitative
workflow justifies.

Before expanding AI autonomy or adding new product capabilities, the project
must establish a reliable quantitative platform foundation. Data, datasets,
research, portfolio construction, simulation, accounting, and evidence must work
correctly and be independently verifiable without relying on AI orchestration.

The current platform path is:

```text
Market Data
-> PIT Dataset
-> Research / Evaluation
-> Published Forecast
-> Portfolio
-> Simulation / Shadow
-> Evidence / Feedback
```

AI may drive research iteration on top of this path, but it must not compensate
for unstable data, missing financial semantics, or unreliable platform behavior.

## In scope

- Align the repository with the canonical architecture and remove conflicting
  historical abstractions.
- Classify major code areas as **KEEP**, **SIMPLIFY**, **FREEZE**, **DELETE**, or
  **REPLACE** based on real product value and compatibility requirements.
- Stabilize the continuous data path: acquisition, normalization, point-in-time
  publication, freshness, revision handling, and failure recovery.
- Restore a clear research path from Dataset through evaluation and Published
  Forecast into portfolio construction and simulation.
- Ensure core platform capabilities remain usable and testable independently of
  AI providers and AI orchestration.
- Remove or simplify accidental acceptance, conformance, compatibility, runtime,
  and infrastructure complexity.
- Validate a small set of high-value end-to-end product journeys using realistic
  local workflows.
- Improve tests and CI where they protect meaningful behavior, financial
  semantics, persisted compatibility, and important boundaries.

## Out of scope

Until the Engineering Reset is complete, do not expand:

- live trading or new broker integrations;
- capital-authority or automatic-execution infrastructure;
- autonomous AI trading or new AI orchestration frameworks;
- new acceptance or conformance frameworks;
- hosted accounts, cloud control planes, or cloud sync;
- unrelated product features;
- large rewrites, microservice migrations, or language rewrites done primarily
  for architectural preference.

Maintenance fixes remain allowed when required to preserve user data, security,
financial correctness, persisted compatibility, or currently supported behavior.

## Exit criteria

The Engineering Reset is complete when:

- major code areas have explicit KEEP / SIMPLIFY / FREEZE / DELETE / REPLACE
  decisions;
- meaningful accidental complexity has actually been removed or frozen;
- the Data -> PIT Dataset path is reliable, observable, and replayable;
- the core research, portfolio, simulation, accounting, and evidence workflow
  has clear ownership and works end to end;
- those platform capabilities work correctly without AI orchestration;
- normal local development and runtime behavior are predictable;
- a small set of real product journeys passes reliably;
- tests and CI primarily protect behavior, financial semantics, compatibility,
  and important boundaries rather than obsolete implementation structure.

## After the reset

Do not automatically resume an old roadmap.

Choose the next development focus from `GOAL.md`, current product evidence, user
needs, and the simplified codebase, then replace the current focus in this file.
Historical milestones and unfinished acceptance items do not re-enter scope merely
because they once existed.
