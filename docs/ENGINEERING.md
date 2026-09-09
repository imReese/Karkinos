# Karkinos Engineering Guide

This document describes the **current codebase, known structural debt, engineering policy, and quality strategy**.

Product intent belongs to [GOAL.md](GOAL.md), durable system boundaries to [ARCHITECTURE.md](ARCHITECTURE.md), current scope to [PLAN.md](PLAN.md), and external design references to [REFERENCES.md](REFERENCES.md).

This is not a roadmap, target package tree, or implementation log. Update it when the repository's actual ownership, debt, or engineering policy changes.

## 1. Current repository reality

The map below is descriptive. It explains what the repository contains today and where important engineering concerns exist; it does not prescribe a future directory structure.

| Area                             | Current responsibility                                                             | Known concern                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `core/`                          | shared time, event, and value primitives                                           | foundational; keep ownership narrow                                            |
| `data/`                          | providers, market identity, calendar, ingestion, storage, dataset work             | provider, storage, and research-data responsibilities are still mixed          |
| `analytics/`                     | quantitative metrics, PIT/OOS/robustness research, plus acceptance/governance code | research and project-governance concerns are mixed                             |
| `strategy/`                      | legacy strategy and signal abstraction                                             | remains signal-centric relative to the intended research workflow              |
| `backtest/`                      | backtest and simulation behavior                                                   | still contains compatibility with older strategy/execution assumptions         |
| `execution/`                     | costs, order/fill contracts, simulation and paper execution                        | must avoid duplicate lifecycle ownership elsewhere                             |
| `risk/`                          | financial and pre-trade risk rules                                                 | should remain financial policy rather than operational readiness logic         |
| `account_truth/`                 | account, broker, evidence, reconciliation, and execution-edge machinery            | substantially larger than current research-first scope                         |
| `server/`                        | HTTP delivery, composition, persistence, use cases, workers, runtime services      | broad responsibilities and coupling make ownership difficult to see            |
| `server/ai_runtime/`             | AI research and orchestration infrastructure                                       | outside the current core workflow unless explicitly brought into scope         |
| `web/`                           | user-facing product interaction and presentation                                   | must remain derived from canonical backend/domain semantics                    |
| `scripts/`, release, CI, tooling | development and operational support                                                | runtime and release machinery has become substantial for a local-first product |

The Engineering Reset will classify major areas as **KEEP**, **SIMPLIFY**, **FREEZE**, **DELETE**, or **REPLACE**.

Do not pre-fill those decisions from this table. Record a classification only after repository evidence and, where useful, comparative reference research justify it.

A scope freeze in `PLAN.md` means "do not expand now"; it does not by itself mean "delete later."

## 2. Ownership and representations

A financial or research concept has one **canonical owner**, but may have multiple representations.

API DTOs, projections, caches, reports, materialized views, database read models, and UI models may represent canonical state. They must remain derived and must not silently become competing calculation or write owners.

Place behavior with the code that owns its semantics.

General rules:

* financial formulas belong with the financial concept that owns them;
* research semantics belong with research code rather than HTTP, UI, or operational plumbing;
* persistence code owns storage mechanics, not business formulas;
* providers translate external data into Karkinos inputs; provider responses are not canonical state by themselves;
* HTTP routes should primarily validate requests, invoke a use case, and map responses;
* UI code presents and interacts with state rather than reproducing canonical financial calculations;
* operational code coordinates work but does not become the owner of research or financial truth.

FastAPI, React, SQLite, provider SDKs, and similar technologies are implementation details at outer boundaries unless `ARCHITECTURE.md` explicitly establishes otherwise.

Existing legacy code does not need to be reorganized merely to make the directory tree match a conceptual architecture. Improve ownership when a real change justifies touching the boundary.

Avoid using broad locations such as `server/services/`, `domain/`, `utils.py`, or `helpers.py` as default homes for behavior whose owner has not been identified.

## 3. Compatibility and persisted state

Compatibility protects real contracts, not historical abstractions.

Preserve compatibility when required by:

* persisted user data;
* published or documented external contracts;
* external integrations;
* supported user workflows;
* explicit financial semantics.

Internal classes, helpers, module paths, repository-only interfaces, and obsolete abstractions do not receive compatibility by default.

When persisted financial state changes:

* identify the canonical owner and migration boundary;
* preserve atomicity, idempotency, ordering, and replay semantics where the domain requires them;
* add migration or replay coverage when regression risk is material;
* do not silently invent, infer, or repair unknown financial facts during reads.

When simplifying an internal API, migrate its real callers and remove the obsolete path when safe. Do not add a permanent compatibility layer without a real compatibility requirement.

Multiple representations are acceptable; multiple competing sources of financial truth are not.

## 4. Change and refactoring policy

Understand the behavior before changing the structure.

Prefer:

```text
delete
-> reuse
-> simplify
-> plain implementation
-> new abstraction
```

A new class, service, repository, protocol, schema, table, worker, framework, or extension point should either express a stable domain concept or make a concrete current problem simpler. Future flexibility alone is not sufficient.

Avoid:

* one production abstraction per requirement or acceptance criterion;
* translating milestone, review, acceptance, or internal process vocabulary directly into the production domain;
* interfaces with only hypothetical consumers;
* wrapper-on-wrapper migrations that never remove the previous path;
* speculative workers, services, repositories, tables, or ports;
* large rename-only or directory-shuffling refactors;
* retaining accidental complexity solely because old tests encode it.

Runtime `evidence` is appropriate when the product genuinely requires financial, research, or data provenance. Do not create evidence, manifest, acceptance, or conformance frameworks merely to prove project completion.

Keep changes focused on the actual problem. Do not expand adjacent subsystems opportunistically.

When practical, separate structural movement from changes to financial semantics. This is a risk-management preference, not a ritual; combine them when doing so is clearly simpler and safer.

Characterization and replay tests are useful when important existing behavior is insufficiently protected. They are not mandatory ceremony for every refactor.

A successful simplification should leave fewer concepts to understand, not merely move the same complexity behind newer names.

Large or multi-stage changes may use a task-specific execution plan when coordination genuinely requires one. Such a plan does not become durable architecture or repository policy.

## 5. Testing and validation

Tests protect meaningful behavior and semantics rather than implementation volume.

Use the smallest test layer that provides sufficient confidence:

1. deterministic unit tests for financial formulas and domain rules;
2. integration tests for persistence, providers, and meaningful boundaries;
3. migration or replay tests for persisted-state compatibility;
4. simulation correctness tests;
5. a small set of high-value end-to-end product journeys.

Add a regression test when a defect exposes a meaningful gap that can reasonably recur.

Do not mechanically add tests for reversible, low-impact changes that merely mirror implementation details.

Avoid tests whose primary purpose is to:

* enumerate internal files or private symbols;
* preserve obsolete implementation structure;
* prove project-management acceptance criteria;
* inflate coverage or test count;
* require large fixture or manifest frameworks without product value.

When simplification makes an old structural test irrelevant, update or remove the test rather than preserving the obsolete design.

### Local validation

Run the narrowest relevant checks first and broaden only when the affected boundary, a failure, or unresolved risk requires it.

For Python quality checks, prefer the exact task base when known:

```bash
uv run python scripts/ci/check_python_quality.py --base <base-ref-or-sha>
```

For ordinary local work directly against the current remote `dev`, `origin/dev` may be used as the base.

Run relevant Python tests first:

```bash
uv run python -m pytest <relevant-tests>
```

Use the full suite only when repository-wide risk justifies it:

```bash
uv run python -m pytest
```

For Web changes, run the relevant combination of:

```bash
npm --prefix web run format:check
npm --prefix web run test
npm --prefix web run build
```

`.github/workflows/dev-ci.yml` defines development-branch verification.
`.github/workflows/ci.yml` is authoritative for full verification.

For runtime or UI behavior, validate the corresponding real product journey when practical rather than relying only on mocked contracts.

Never weaken meaningful assertions, typing, financial invariants, or fail-closed behavior merely to make a check pass.

Report only checks that actually ran.

## 6. Engineering gates

Configured gates prove only what they actually check.

At the start of the Engineering Reset:

* lint enforcement is primarily a correctness baseline rather than comprehensive maintainability analysis;
* static typing coverage is uneven across packages;
* executable architecture checks cover only part of the repository's dependency structure;
* parts of the test suite protect historical implementation, acceptance, release, or synthetic-fixture behavior in addition to product behavior.

Do not interpret a green CI result as proof that the code is simple, well-owned, or appropriately scoped.

Improve gates incrementally when real work reaches the affected boundary.

Useful ratchets include:

* expanding static typing when a touched boundary is understood;
* adding dependency checks after ownership is established;
* enabling additional lint rules when relevant code can adopt them without unrelated mass churn;
* replacing implementation-structure tests with behavioral tests during simplification;
* adding a real E2E journey when a meaningful product failure was not otherwise observable.

Do not start repository-wide cleanup solely to maximize lint rules, typing percentages, coverage, test count, or architecture-check coverage.

When a durable repository rule can be enforced reliably by tooling, prefer encoding it in linting, type checking, architecture checks, or CI and simplifying the prose rule.

## 7. Maintaining this guide

`PLAN.md` owns current priorities and frozen scope.
`ARCHITECTURE.md` owns durable system boundaries.
`REFERENCES.md` owns lessons from external projects.
Git owns implementation history.

This document owns:

* the current codebase map;
* validated structural debt;
* engineering and compatibility policy;
* testing and quality strategy;
* confirmed Engineering Reset classification decisions.

Update it when those facts materially change.

Do not turn KEEP / SIMPLIFY / FREEZE / DELETE / REPLACE into an acceptance system, database schema, API, manifest format, or governance framework. The labels exist only to make engineering decisions easier.

Do not promote an audit hypothesis into repository policy before evidence supports it.
