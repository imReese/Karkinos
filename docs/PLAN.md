# Karkinos Plan

This document defines the **current development scope** only.

Long-term product intent belongs to [GOAL.md](GOAL.md), durable system boundaries to [ARCHITECTURE.md](ARCHITECTURE.md), and codebase ownership and engineering guidance to [ENGINEERING.md](ENGINEERING.md).

Implementation history belongs in Git. When the current scope changes, replace obsolete planning content instead of appending a historical roadmap.

## Current focus — Engineering Reset

Karkinos currently has more implementation complexity than its core quantitative workflow justifies.

Before adding new product capabilities, the project should reduce accidental complexity, restore clear ownership, and make the core research and investing workflow reliable and understandable.

The goal is not a cleaner architecture for its own sake. The goal is a simpler platform that makes it easier to discover, validate, and use investment edge.

## In scope

* Align the canonical repository documentation and development rules.

* Audit major subsystems against mature quantitative projects and the actual Karkinos product goal.

* Classify major code areas as **KEEP**, **SIMPLIFY**, **FREEZE**, **DELETE**, or **REPLACE**.

* Remove or simplify accidental acceptance, conformance, compatibility, runtime, and infrastructure complexity.

* Restore a clear core workflow:

  `Market Data -> PIT Dataset -> Research -> Portfolio -> Simulation -> Decision`

* Validate a small set of high-value real product journeys.

* Improve engineering checks where they protect meaningful behavior and maintainability.

## Out of scope

Until the Engineering Reset is complete, do not expand:

* live trading or new broker integrations;
* capital-authority or automatic-execution infrastructure;
* autonomous AI trading or new AI orchestration frameworks;
* new acceptance or conformance frameworks;
* hosted accounts, cloud control planes, or cloud sync;
* unrelated product features;
* large rewrites, microservice migrations, or language rewrites done primarily for architectural preference.

Maintenance fixes remain allowed when required to preserve user data, security, financial correctness, persisted compatibility, or currently supported behavior.

## Exit criteria

The Engineering Reset is complete when:

* major code areas have explicit KEEP / SIMPLIFY / FREEZE / DELETE / REPLACE decisions;
* meaningful accidental complexity has actually been removed or frozen;
* the core quantitative workflow has clear ownership and works end to end;
* normal local development and runtime behavior are predictable;
* a small set of real product journeys passes reliably;
* tests and CI primarily protect meaningful behavior, financial semantics, and important boundaries rather than obsolete implementation structure.

## After the reset

Do not automatically resume an old roadmap.

Choose the next development focus from `GOAL.md`, current product evidence, user needs, and the simplified codebase, then replace the current focus in this file.

Historical milestones and unfinished acceptance items do not re-enter scope merely because they once existed.
