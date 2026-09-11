# Karkinos Engineering Guide

This document records the current codebase shape, known structural debt,
compatibility policy, and practical validation strategy.

## 1. Current repository reality

| Area | Current responsibility | Current concern |
| --- | --- | --- |
| `core/` | shared time, event, and value primitives | foundational; keep ownership narrow |
| `data/` | providers, market identity, calendar, ingestion, storage, dataset work | provider, storage, and dataset responsibilities are still mixed |
| `analytics/` | quantitative metrics, PIT/OOS/robustness research, plus acceptance/governance code | research and project-governance concerns are mixed |
| `strategy/` | legacy strategy and signal abstraction | signal-centric relative to the target Research -> Forecast -> Portfolio flow |
| `backtest/` | backtest and simulation behavior | still coupled to legacy strategy/execution assumptions |
| `execution/` | costs, order/fill contracts, simulation and paper execution | simulation and execution ownership are not yet cleanly separated |
| `risk/` | financial and pre-trade risk rules | financial policy and operational blocking must remain distinct |
| `account_truth/` | account, broker, evidence, reconciliation, and execution-edge machinery | substantially larger than current research-first scope |
| `server/` | HTTP delivery, composition, persistence, use cases, workers, runtime services | broad responsibilities make ownership difficult to see |
| `server/ai_runtime/` | AI-assisted research and orchestration | should consume stable platform capabilities rather than own quantitative or financial semantics |
| `web/` | user-facing interaction and presentation | must remain derived from canonical platform semantics |
| `scripts/`, release, CI | development and operational support | runtime, release, and verification machinery are substantial for a local-first product |

The Engineering Reset classifies major areas as **KEEP**, **SIMPLIFY**,
**FREEZE**, **DELETE**, or **REPLACE**. A classification should follow repository
evidence and real compatibility requirements, not the current amount of code in
an area.

## 2. Ownership and compatibility

Place behavior with the domain that owns its semantics. API DTOs, projections,
caches, reports, database read models, and UI models may represent canonical
state, but they do not become independent calculation or write owners.

Preserve compatibility when required by:

- persisted user data;
- published external contracts;
- external integrations;
- supported user workflows;
- explicit financial semantics.

Internal helpers, module paths, repository-only interfaces, and obsolete
abstractions do not receive compatibility by default.

When persisted financial state changes, identify the canonical owner and
migration boundary, preserve required atomicity/idempotency/ordering semantics,
and add migration or replay coverage when regression risk is material. Do not
invent missing financial facts during reads.

## 3. Simplification policy

Prefer changes in this order:

```text
delete
-> reuse
-> simplify
-> plain implementation
-> new abstraction
```

A new class, service, repository, protocol, schema, table, worker, framework, or
extension point must represent a stable domain concept or make a concrete current
problem simpler.

Do not preserve project-management vocabulary as production architecture.
Acceptance criteria, milestone names, review checklists, and completion evidence
are not domain concepts.

Do not add permanent compatibility wrappers without a concrete compatibility
consumer. When an internal API is obsolete, migrate its real callers and remove
it when safe.

A successful simplification leaves fewer concepts to understand.

## 4. Testing and validation

Tests should protect behavior and semantics, not implementation volume.

Use the smallest layer that gives sufficient confidence:

1. deterministic unit tests for formulas and domain rules;
2. integration tests for persistence, providers, and meaningful boundaries;
3. migration or replay tests for persisted-state compatibility;
4. simulation correctness tests;
5. a small set of high-value end-to-end product journeys.

Remove or rewrite tests that exist only to preserve obsolete file structure,
private symbols, project-management acceptance criteria, or deleted abstractions.

Run narrow checks first:

```bash
uv run python scripts/ci/check_python_quality.py --base <base-ref-or-sha>
uv run python -m pytest <relevant-tests>
```

For Web changes, use the relevant combination of:

```bash
npm --prefix web run format:check
npm --prefix web run test
npm --prefix web run build
```

Use the full Python suite only when repository-wide risk justifies it:

```bash
uv run python -m pytest
```

For runtime or UI behavior, validate the real product journey when practical.
Report only checks that actually ran.

## 5. Current quality gaps

At the current reset boundary:

- Ruff enforcement is primarily a correctness baseline rather than a broad
  maintainability gate;
- static typing coverage is uneven across packages;
- executable dependency checks cover only part of the repository;
- parts of the test suite protect historical acceptance, release, synthetic
  fixture, or implementation behavior rather than user-facing behavior;
- runtime and release verification are larger than the core local-first workflow
  currently requires;
- green CI does not by itself prove that ownership is clear or that the real
  product flow works.

Improve these gates incrementally as the affected boundaries become simpler and
better understood. Do not start repository-wide churn merely to maximize lint
rules, typing percentage, coverage, or test count.

`.github/workflows/dev-ci.yml` defines development-branch verification.
`.github/workflows/ci.yml` is the full verification path.
