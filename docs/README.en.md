# Karkinos Documentation

Karkinos is a China-market personal quant research and trading platform. This
page is the English documentation index; it does not duplicate the full
product description, endpoint inventory, or implementation history.

[Project home](../README.md) | [中文文档](README.zh.md)

## Quick start

Requirements: Python 3.12+, Node.js 24.x, `uv`, and optionally Docker.

```bash
uv sync --extra server --extra dev --frozen
npm ci --prefix web
npm --prefix web run build
uv run python -m server --no-live
```

The default product entry point is `http://127.0.0.1:8000`.

Primary checks:

```bash
uv run python -m pytest
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

See the configuration reference for runtime, notification, and local-data
settings: [中文](config-reference.zh.md) / [English](config-reference.en.md).

## Documentation map

### Core

- [Product goal](KARKINOS_GOAL.md) — North Star, durable promises, and
  boundaries that must not be crossed.
- [Roadmap](ROADMAP.md) — current priorities, milestones, acceptance gates,
  and development order.
- [Architecture](ARCHITECTURE.md) — system layers, core flows, authority
  boundaries, and failure semantics.

### Guides

- [Account Truth import and review](account-truth-import.en.md) — preview,
  evidence staging, reconciliation, and human disposition.
- [Return and cost accounting](return-accounting.en.md) — shared rules for
  today's, unrealized, and realized results.
- [Broker-order lifecycle](broker-order-lifecycle-ingestion.en.md) — read-only
  lifecycle evidence and collector ingestion.
- [Broker adapter conformance](broker-adapter-conformance.en.md) — local
  deterministic fixtures, exact release binding, and latest-result-wins gates.
- [Broker execution-edge conformance](broker-execution-edge-conformance.en.md) —
  default-closed dry-run, submit, query, cancel, and idempotency contract fixtures.
- [Controlled broker cancellation](controlled-broker-cancellation.en.md) — exact
  signed one-shot cancellation, atomic idempotency, and query-only recovery.
- [Broker adapter release review](broker-adapter-release-review.en.md) —
  provider-neutral capability, threat, deployment, rollback, privacy, and
  explicit human acceptance evidence.
- [Controlled execution](CONTROLLED_EXECUTION_PLAN.md) — human authority,
  runtime gates, recovery, and capital-scaling rules.
- [Offline operator approval signing](operator-approval-signing.md) — local
  Ed25519 provisioning and short-lived signed mutation reviews without private
  key storage.

### Reference

- [Configuration reference](config-reference.en.md) — local runtime, market
  data, fees, connector, and authority fields.
- [Implementation log](IMPLEMENTATION_LOG.md) — release-level outcomes and
  validation ownership.
- [Benchmark notes](BENCHMARKS.md) — design lessons and prohibited product
  bindings from external projects.

## Core workflows

### Research and backtesting

Strategy Lab runs registered strategies against frozen data inputs whose IDs hash the exact ordered timestamp/OHLCV rows. Saved experiments bind parameters, cost assumptions, OOS evidence, risk, limitations, and data-quality status. The deterministic advancement gate additionally requires aligned rolling OOS, bounded parameter and market-state robustness, drawdown, turnover, capacity, account-specific broker-reconciled fee/tax evidence, after-tax excess, critique, and a redacted proof that account-bound research capital does not exceed current reconciled account equity; the built-in fee estimate is explicitly ineligible. Reserved AI-shadow tickets re-resolve the exact persisted sources, and the next batch requires a fingerprint-valid plan/paper/actual comparison. Missing or drifted evidence is no-action; no research record grants execution or capital authority.
The account-specific model is created only by a revocable, fingerprint-bound Account Truth fee review. Its persisted safe terms drive the actual baseline and candidate calculators; source drift, revocation, or an uncovered backtest/ticket date blocks without provider or broker contact. The next-batch reconciliation must also resolve every prior order to the current strategy; missing, mixed, or unrelated strategy lineage is no-action.

### Daily decision

Decision and Daily Trading Plan combine portfolio, market, strategy, signal, risk, Account Truth, and paper/shadow evidence. Outcomes are explicit: buy, sell, hold, rebalance, no action, or review required. Promotion first yields a `paper_shadow_required` plan intent; manual confirmation additionally requires a persisted same-date run bound to the exact action and input fingerprint with no divergence. The ticket edge rechecks Account Truth, market, risk, Kill Switch, promotion, reviewed fees, and shadow evidence; failure is no-action.

Decision outcome reviews freeze one exact persisted signal-to-execution chain
and canonical contribution target. Strategy Lab replays the stored row and
event chain, rebuilds the current target, and turns only the latest valid human
review per signal into a safe learning action. Drift or tampering blocks the
item; an unsupported outcome yields only a copyable question for a separately
human-started research task. The queue is read-only and cannot invoke AI,
create memory, change a strategy, or grant execution or capital authority.

### Paper/shadow and Operations

Operations exposes data, plan, paper/shadow, OMS, reconciliation, alert, and recovery state. Simulation may create paper orders and fills but never submits to a real broker or silently mutates the production ledger. The legacy Trading daily-shadow endpoint delegates here and refuses caller-supplied account equity.
Each non-normal Operations subsystem also exposes a deterministic attention
fingerprint, the safe next action, and the exact evidence condition that clears
it. The `/operations` workbench renders that canonical persisted-facts payload,
subsystem health, source evidence, and safe drill-down without provider contact,
database writes, or execution authority. Viewing alone cannot change status.

### Account Truth and reconciliation

Broker imports are previewed and stored as separate evidence. Incomplete CITIC History Trades files may be explicitly reviewed into a privacy-minimized
follow-up-source queue or rejected; an explicitly configured private directory can be scanned on demand without returning paths or names. Each pending source
may also receive an append-only, revocable, fingerprint-bound review of the exact broker query dates; those dates are never inferred from observed events,
and a directory scan checks the current declared dates for gaps and overlaps without treating continuity as complete coverage. Completing them clears only
that source-level follow-up requirement. Pending, truncated, unreadable, gapped, or overlapping source review also blocks the Account Truth promotion evidence used by controlled execution, but can never create canonical account facts or independently open execution. No parsed event enters Account Truth.
Reconciliation compares cash, positions, orders, fills, fees, taxes, and cost
basis. Broker facts do not silently rewrite the ledger.

The Account Truth page also projects one canonical evidence-readiness checklist for reviewed account/date/asset scope, cash/position snapshots, settlement,
cost basis, freshness/ledger coverage, reconciliation, and incomplete sources. Observed first/last rows do not prove full coverage: only an explicit exact-import
owner review can bind a locally hashed account reference and declared period, and that review remains revocable. Missing, drifted, or unreadable evidence stays
blocked; viewing cannot write, contact a broker, reconcile, or grant authority.

### Controlled execution

Real-money capability is disabled by default. The active milestone validates one
provider through read-only soak, per-order human approval, bounded capital,
complete lifecycle recovery, reconciliation, and explicit posting. Legacy manual
ticket and manual-execution operations require the latest signed current per-order
confirmation, re-resolve capital, four sources, adapter/soak, gateway, and reconciliation,
and bind every fingerprint. Posting and correction need separate signatures; none can
contact a provider, submit/cancel, or change capital authority.
The reconciliation-to-terminal-clearance and terminal-clearance-to-posting
steps are available as separately opened operator reviews with deterministic
previews, short-lived offline signatures, and final acknowledgements. Clearance
records exact terminal fills and releases only that order's interlock without
posting the ledger. No matching trusted public identity keeps either action
disabled.

Trading also exposes default-collapsed, no-database-edit signed reviews for
provider-neutral adapter accept/reject/revoke and for a separate exact
write-edge issue/revocation. Adapter acceptance binds the newest conformance,
current review, and exact operator approval; both journeys block credential-key
manifests locally and provide no broker, registration, or capital-authority action.

A rejected controlled intent exposes a sanitized, fingerprinted copy package
and a separate append-only human review. The review records one exact reviewer,
evidence fingerprint, disposition, and time exactly once; it grants no retry or
authority and closes the journey with “create a new Decision if still needed.”
Evidence drift or a conflicting second reviewer fails closed.

### AI research

AI workflows read persisted evidence through deny-by-default tools. Model
output is cited, non-authoritative research; it is not an account fact, risk
decision, capital authorization, OMS transition, or broker instruction.

Formula research starts from a saved canonical backtest and its exact dataset
snapshot. The model may propose hypotheses; a human selects one, and the
allowlisted Formula DSL plus the canonical BacktestEngine perform the
calculation. The result still requires human disposition and cannot register a
production strategy or create trading authority.

## Privacy and safety

- Never commit broker passwords, API keys, real account identifiers, account
  exports, runtime databases, logs, or private screenshots.
- Do not present a backtest or AI report as investment advice or a return
  guarantee.
- Missing, stale, partial, ambiguous, or conflicting evidence fails closed.
- Strategy, AI, scheduler, GET, and alert paths do not receive submit or cancel
  authority.

## Documentation maintenance

This page remains an index. Product boundaries belong in Goal, current work in
Roadmap, stable design in Architecture, configuration and data contracts in
topic references, and completed evidence in the Implementation Log.
