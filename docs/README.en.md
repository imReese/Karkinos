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

See the [configuration reference](config-reference.zh.md) for runtime,
notification, and local-data settings. The reference is currently maintained
in Chinese; contracts and field names remain language-independent.

## Documentation map

| Need | Document |
| --- | --- |
| Product North Star and long-term boundaries | [Goal](KARKINOS_GOAL.md) |
| Current priorities and release gates | [Roadmap](ROADMAP.md) |
| Components, flows, and authority boundaries | [Architecture](ARCHITECTURE.md) |
| Completed release and validation summary | [Implementation log](IMPLEMENTATION_LOG.md) |
| Local runtime configuration | [Configuration reference](config-reference.zh.md) |
| Account Truth import contract | [Account Truth import](account-truth-import.zh.md) |
| Portfolio-return accounting | [Return accounting](return-accounting.zh.md) |
| Broker-order lifecycle evidence | [Lifecycle ingestion](broker-order-lifecycle-ingestion.zh.md) |
| Controlled-execution safety gates | [Controlled execution plan](CONTROLLED_EXECUTION_PLAN.md) |
| External project reference boundary | [Benchmarks](BENCHMARKS.md) |

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

### AI research

AI workflows read persisted evidence through deny-by-default tools. Model
output is cited, non-authoritative research; it is not an account fact, risk
decision, capital authorization, OMS transition, or broker instruction.

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

