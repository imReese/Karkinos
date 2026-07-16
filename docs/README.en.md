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

Strategy Lab runs registered strategies against frozen data inputs. Saved
experiments bind parameters, cost assumptions, OOS evidence, risk, limitations,
and data-quality status. Sweeps and comparisons remain research evidence and
cannot grant execution authority.

### Daily decision

Decision and Daily Trading Plan combine portfolio, market, strategy, signal,
risk, Account Truth, and paper/shadow evidence. Outcomes are explicit: buy,
sell, hold, rebalance, no action, or review required.

### Paper/shadow and Operations

Operations exposes data, plan, paper/shadow, OMS, reconciliation, alert, and
recovery state. Simulation may create paper orders and fills but never submits
to a real broker or silently mutates the production ledger.

### Account Truth and reconciliation

Broker imports are previewed and stored as separate evidence. Reconciliation
compares cash, positions, orders, fills, fees, taxes, and cost basis. Broker
facts do not silently rewrite the ledger.

### Controlled execution

Real-money capability is disabled by default. The active milestone validates
one provider through read-only soak, per-order human approval, bounded capital,
complete lifecycle recovery, execution reconciliation, and explicit posting.
Posting and append-only correction require separate signatures; correction is
derived only from canonical ledger replay, preserves the original facts, and
requires newer Account Truth evidence afterward. Neither boundary can contact
a provider, submit or cancel an order, or change capital authority.
The terminal-clearance-to-posting step is available as an explicitly opened
operator review with a deterministic preview, short-lived offline signature,
and final acknowledgement; no trusted public identity keeps it disabled.

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
