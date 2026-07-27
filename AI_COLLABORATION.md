# Karkinos AI Collaboration Policy

This document is the repository-level source of truth for AI-assisted work. It
is tool-neutral and applies equally to implementation, review, diagnosis, and
documentation changes.

## Product boundary

Karkinos is a China-market personal quant research and trading platform, not a
toy backtester. Prioritize:

1. Data integrity and reproducible datasets.
2. After-cost backtest credibility.
3. Mandatory pre-trade risk gates.
4. Signal journals and auditable evidence.
5. Portfolio action queues and safe human next steps.
6. Paper/shadow operation before live-like workflows.
7. Explicit strategy promotion and rollback paths.

Real-money automatic trading must never become the default. Live-like actions
require explicit human confirmation and bounded, revocable authority.

## Source routing

Before changing code, read `docs/KARKINOS_GOAL.md` and the relevant sections of
`README.md`. Then load only the task-specific source of truth:

- Account, valuation, PnL, market data, risk, paper/shadow, reconciliation, or
  execution: `docs/ARCHITECTURE.md`, especially Architectural Principles,
  Canonical Financial Identity, and Failure Semantics.
- Product UI, information hierarchy, or interaction behavior: `design.md`.
- Milestones and sequencing: `docs/ROADMAP.md`.
- Controlled execution: `docs/CONTROLLED_EXECUTION_PLAN.md`.
- Chinese documentation or localization: `docs/README.zh.md` and the linked
  translated page.

Do not treat deleted, closed, or superseded issue discussions as project goals.

## Financial data integrity

Accuracy, provenance, deterministic replay, and fail-closed behavior take
precedence over freshness or UI convenience.

For account, valuation, PnL, market data, risk, paper/shadow, reconciliation,
and execution workflows:

1. Persisted facts are authoritative. Runtime caches and provider responses are
   ingestion inputs, never authoritative account facts.
2. Read/query endpoints must not contact providers or silently refresh facts.
   Refresh is an explicit ingestion command with an auditable run id.
3. Derived results must bind an explicit market-data snapshot or as-of time and
   a ledger cutoff so they can be deterministically replayed.
4. One financial concept must have one canonical implementation. Other
   surfaces may project it but must not independently recalculate it.
5. Asset, symbol, fee, event-flow, residual, and account-level changes must
   reconcile through deterministic cross-surface tests.
6. Missing, stale, estimated, partial-batch, conflicting, or unreconciled
   evidence must remain explicit and block authoritative results.
7. Provisional in-memory telemetry must not enter risk gates, account truth,
   performance evidence, or execution authority until persisted and validated.

## Human authority and safety

- AI output, research results, reviews, and UI actions do not grant trading or
  capital authority.
- Strategy and research code must not call a broker directly.
- Missing approval, stale evidence, or uncertain execution state fails closed.
- Broker credentials, account identifiers, private exports, screenshots,
  runtime databases, and secrets must not enter source control.
- Destructive or authority-expanding actions require explicit owner direction.

## Engineering and validation

- Preserve unrelated and uncommitted workspace changes.
- Keep one canonical implementation for each financial concept.
- Record assumptions and risk impact for trading-related changes.
- Add deterministic tests for affected invariants and direct consumers.
- State validation boundaries honestly; static, unit, stub, or local checks are
  not evidence of production-provider, broker, remote, or real-money behavior.
- Before committing, inspect both staged and unstaged changes, run relevant
  tests, and confirm no credentials or private account data are included.
- Commit, push, publish, or open a pull request only when the owner requests it.
