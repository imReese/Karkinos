# Karkinos Codebase Guide

[Product architecture](ARCHITECTURE.md) | [Goal](KARKINOS_GOAL.md) |
[Roadmap](ROADMAP.md) | [Contributing](../CONTRIBUTING.md)

This guide describes the physical source layout and dependency rules used to
evolve Karkinos as a modular monolith. Product invariants and authority
boundaries remain owned by `ARCHITECTURE.md`; this file owns contributor-facing
code organization.

## Dependency Direction

The left-hand package may import only the listed internal packages:

| Package | Allowed internal dependencies |
| --- | --- |
| `core` | none |
| `domain` | `core` |
| `data` | `core`, `domain` |
| `strategy` | `core`, `data` |
| `risk` | `core`, `domain` |
| `execution` | `core` |
| `account_truth` | none |
| `notification` | none |
| `backtest` | `core`, `data`, `domain`, `execution`, `risk`, `strategy` |

`server` composes the application and may depend on the packages above; its
boundaries are being migrated incrementally and are not covered by this table.

`tools/check_python_architecture.py` is the executable source of truth for the
protected package edges. A diagram or directory name never overrides that
check.

## Python Ownership

| Location | Owns | Must not own |
| --- | --- | --- |
| `core/` | clocks, events, foundational types | Web, persistence, provider, or broker behavior |
| `domain/` | canonical portfolio and instrument rules | HTTP or database orchestration |
| `data/` | market-data contracts, ingestion, replay, providers | account authority or presentation |
| `strategy/` | signal definitions and safe extension registry | broker access or execution authority |
| `risk/` | deterministic risk policy | order submission |
| `execution/` | broker-neutral execution contracts and simulation | strategy selection or capital authority |
| `backtest/` | canonical deterministic backtest engine | HTTP presentation |
| `account_truth/` | broker-evidence ingestion and reconciliation contracts | silent production-ledger mutation |
| `analytics/` | evidence analysis and acceptance reporting | authoritative account facts |
| `server/routes/` | HTTP validation, dependency lookup, error mapping, response models | reusable financial calculation or persistence |
| `server/services/` | application use cases, orchestration, transaction intent | FastAPI route imports |
| `server/persistence/` | bounded SQLite repositories and schema migrations | provider calls or business authority |
| `server/projections/` | canonical read projections | external side effects |
| `server/app.py` | process composition and lifecycle | business calculations or route-private helpers |

`AppDatabase` remains a compatibility facade while repositories are extracted.
New single-context persistence belongs in `server/persistence/`. Cross-context
atomic flows such as controlled submission, reconciliation, posting, and
correction stay on one SQLite connection until a tested unit-of-work boundary
can preserve their exact idempotency and rollback semantics.

## Web Ownership

```text
web/src/app/       providers, router, shell, process-level composition
web/src/features/  domain queries, commands, pages, and local components
web/src/shared/    feature-neutral UI, formatting, and API infrastructure
```

The router loads route pages; it does not implement them. A feature may depend
on shared code, but shared code must not depend on `app` or a feature. Cross-
feature workflow composition belongs in a route page or an explicit public
presentation contract, not a deep import into another feature's internals.
`web/src/architecture/import-boundaries.test.ts` ratchets these rules as the
incremental migration proceeds.

## Refactoring Rules

1. Establish characterization tests before moving behavior.
2. Move logic before redesigning it; avoid mixing structural and semantic
   changes in the same slice.
3. Keep compatibility facades until direct callers and tests have migrated.
4. Add an executable dependency rule for each newly established boundary.
5. Prefer a bounded repository or named application service over generic
   `utils`, `helpers`, or catch-all modules.
6. Keep tests near the level they prove: route tests for HTTP contracts,
   service tests for use-case semantics, repository tests for SQL and atomicity,
   and acceptance tests for cross-surface invariants.
7. Treat file size as a review signal, not an automatic reason to create more
   layers. Split by ownership and change reason.

A structural refactor must not silently change API fields, database schema,
fingerprint bytes, ordering, idempotency keys, financial formulas, provider
contact, broker capability, GET write behavior, or human authority. Any such
change needs a separately stated semantic design and deterministic validation.

## Migration Order

The preferred sequence for remaining architecture debt is:

1. make composition roots thin and enforce route/page boundaries;
2. extract bounded repositories behind compatibility facades;
3. move route-owned use cases into typed application services;
4. remove route-to-route imports through public service contracts;
5. introduce a typed application container while retaining the legacy state
   bridge for unmigrated callers;
6. split large feature APIs, presentation mappings, copy catalogs, and tests by
   workflow; and
7. expand static typing and dependency checks only after each migrated slice is
   clean.

The real-provider adapter, broker soak, and controlled-pilot evidence in the
roadmap are product release gates. A code-organization refactor cannot satisfy
or waive them.
