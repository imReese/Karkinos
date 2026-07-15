# Karkinos

> Investing is a chronic condition. Here is your scalpel.  
> 投资是一种慢性病。这是你的手术刀。

Karkinos is a China-market personal quant research and trading platform. It
connects reproducible research, portfolio evidence, risk control, daily plans,
paper/shadow execution, reconciliation, and human-supervised controlled
execution in one local-first application.

Karkinos 是面向中国市场的个人量化投研与交易平台，将可复现研究、组合证据、风控、每日计划、
paper/shadow 执行、对账与人工监督的受控执行连接成一个本地优先的金融应用。

[中文文档](docs/README.zh.md) | [English documentation](docs/README.en.md) |
[Roadmap](docs/ROADMAP.md) | [Architecture](docs/ARCHITECTURE.md)

## What Karkinos provides

- Deterministic backtests with frozen datasets, after-cost metrics, OOS
  evidence, parameter sweeps, comparisons, and strategy extensions.
- A daily decision and trading-plan workflow with explicit buy, sell, hold,
  rebalance, no-action, and review-required outcomes.
- Portfolio, ledger, valuation, Account Truth, broker evidence, and
  reconciliation views built from persisted facts.
- Mandatory risk, data-quality, paper/shadow, reconciliation, and operator
  gates before live-like actions.
- Paper Broker, OMS, manual order tickets, execution reconciliation, and a
  default-closed controlled-execution foundation.
- Evidence-bound AI research workflows, including human-gated allowlisted
  Formula DSL experiments over saved canonical backtests. Their output remains
  non-authoritative research and never becomes trading authority by itself.
- React/Vite product UI, FastAPI backend, SQLite persistence, Docker runtime,
  deterministic tests, and acceptance-audit evidence.

## Safety boundary

Karkinos is a personal research and trading platform, not investment advice.
Historical results and AI-generated research do not guarantee future returns.

- Strategy code and AI output cannot call a broker directly.
- Real-money submission is disabled by default.
- Controlled execution requires explicit, bounded, expiring human authority
  plus fresh risk, account, market, gateway, and reconciliation evidence.
- Missing, stale, partial, ambiguous, or conflicting financial evidence fails
  closed.
- Broker passwords, API keys, private account exports, runtime databases,
  logs, and screenshots containing private data must not enter source control.

## Current status

Research, daily planning, paper/shadow operations, OMS, Account Truth,
reconciliation, and the non-submitting controlled-execution foundation are
implemented. The active milestone is v1.8: validate one real broker edge
through a read-only soak and a human-confirmed per-order pilot.

See [the roadmap](docs/ROADMAP.md) for priorities and release gates. Completed
implementation evidence lives in
[the implementation log](docs/IMPLEMENTATION_LOG.md), not in this README.

## Quick start

Requirements:

- Python 3.12+
- Node.js 24.x
- `uv`
- Docker, optionally

Install backend and frontend dependencies:

```bash
uv sync --extra server --extra dev --frozen
npm ci --prefix web
```

Build the product frontend and start the local server without the live
scheduler:

```bash
npm --prefix web run build
uv run python -m server --no-live
```

The product entry point is `http://127.0.0.1:8000` unless configured
otherwise.

Run the primary checks:

```bash
uv run python -m pytest
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

Docker:

```bash
docker compose up --build
```

Use fake or sanitized data for development. Do not commit a real `config.json`
containing credentials or private account information.

## Documentation

| Topic | Languages |
| --- | --- |
| Product introduction, installation, and workflow index | [中文](docs/README.zh.md) / [English](docs/README.en.md) |
| Product North Star and durable boundaries | [中文](docs/KARKINOS_GOAL.zh.md) / [English](docs/KARKINOS_GOAL.md) |
| Current priorities, milestones, and acceptance gates | [中文](docs/ROADMAP.zh.md) / [English](docs/ROADMAP.md) |
| Components, flows, and authority boundaries | [中文](docs/ARCHITECTURE.zh.md) / [English](docs/ARCHITECTURE.md) |
| Local runtime configuration | [中文](docs/config-reference.zh.md) / [English](docs/config-reference.en.md) |
| Account Truth import and review contract | [中文](docs/account-truth-import.zh.md) / [English](docs/account-truth-import.en.md) |
| Portfolio return and cost accounting | [中文](docs/return-accounting.zh.md) / [English](docs/return-accounting.en.md) |
| Broker-order lifecycle ingestion | [中文](docs/broker-order-lifecycle-ingestion.zh.md) / [English](docs/broker-order-lifecycle-ingestion.en.md) |
| Controlled-execution safety plan | [中文](docs/CONTROLLED_EXECUTION_PLAN.zh.md) / [English](docs/CONTROLLED_EXECUTION_PLAN.md) |
| Completed release evidence | [中文](docs/IMPLEMENTATION_LOG.zh.md) / [English](docs/IMPLEMENTATION_LOG.md) |
| External-project reference boundary | [中文](docs/BENCHMARKS.zh.md) / [English](docs/BENCHMARKS.md) |

## Repository layout

```text
analytics/       reports, attribution, evidence, and acceptance audit
backtest/        deterministic backtesting and experiment services
core/            events, portfolio primitives, and shared contracts
data/            market-data providers, cache, and reliability evidence
execution/       paper broker, OMS, gateway, and controlled execution
risk/            pre-trade and runtime risk controls
server/          FastAPI application and routes
strategy/        built-in strategies, registry, and runtime
tests/           deterministic backend and safety tests
web/             React/Vite product UI
docs/            durable product, architecture, reference, and runbook docs
```

## License

MIT
