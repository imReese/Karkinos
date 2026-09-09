# Karkinos

> Investing is a chronic condition. Here is your scalpel.

[简体中文](README.zh.md)

Karkinos is a **local-first quantitative research and investing platform for the China market**.

It is built around a simple idea: investment research should be reproducible,
falsifiable, cost-aware, and connected to portfolio decisions without turning
the product into an unattended trading bot.

Karkinos helps turn market data into research evidence, forecasts, portfolio
decisions, simulation results, and explainable investment actions while keeping
financial state and capital authority explicit.

## Why Karkinos

Many quantitative tools make it easy to produce a backtest and much harder to
answer the questions that matter afterward:

* Did the strategy use information that was actually available at the time?
* Does the result survive out-of-sample evaluation and realistic costs?
* Is the apparent edge distinct from market or factor exposure?
* How should multiple forecasts affect the portfolio?
* What changed between research expectations and simulated or realized results?
* When should an edge be reduced, quarantined, or retired?

Karkinos is designed around that full research lifecycle rather than around
strategy count, infrastructure complexity, or broker connectivity.

## Core workflow

```text
Market Data
-> Point-in-time Dataset
-> Research
-> Forecast
-> Portfolio Target
-> Rebalance Plan
-> Risk
-> Simulation / Paper / Shadow
-> Human-supervised Action
-> Accounting / Reconciliation
-> Attribution
-> Edge Monitoring / Retirement
```

The center of the product is the path from **trustworthy data to trustworthy
investment decisions**.

Automated trading is not the product goal.

## Current capabilities

The repository currently includes foundations for:

* China-market data integration and local market-data persistence;
* quantitative strategies, backtesting, transaction-cost modeling, parameter
  exploration, and out-of-sample evaluation;
* reproducible research and point-in-time data workflows;
* portfolio, valuation, fee, return-accounting, and reconciliation workflows;
* risk-gated simulation, paper, and shadow evaluation;
* locally owned financial state and user configuration;
* optional AI-assisted research whose output remains non-authoritative;
* a FastAPI backend and React/TypeScript web application.

Some areas of the existing codebase are intentionally being simplified. The
current engineering scope is defined only in
[docs/PLAN.md](docs/PLAN.md).

## Design principles

### Research before automation

An Alpha, model, score, ranking, probability, or expected return expresses an
investment view. It does not automatically become an order.

Research evidence, portfolio construction, risk, execution, and accounting are
separate responsibilities.

### Point-in-time by default

Research must distinguish what happened from when that information became
available.

Historical universe membership, corporate actions, suspensions, price limits,
trading calendars, and other China-market constraints must not be reconstructed
using future information.

### Reproducible evidence

Meaningful research results should remain traceable to the data, assumptions,
parameters, time boundaries, and implementation that produced them.

A backtest is evidence only when its inputs and financial assumptions are
credible.

### Local-first ownership

Core research, portfolio state, financial state, and primary calculations are
owned locally by default.

External providers may supply data, models, notifications, or optional
capabilities, but they do not become the source of authority for the core
workflow.

Local-first does not mean offline-only.

### Human-supervised capital

Real-money automation is not the default product mode.

Research code, AI, providers, and UI state cannot grant themselves capital
authority or bypass portfolio and risk boundaries.

## Quick start

### Requirements

* Python 3.12+
* Node.js 24.x
* [uv](https://docs.astral.sh/uv/)
* Git

### Development

Clone the repository and switch to the normal development branch:

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
git switch dev
```

Start the development environment:

```bash
./scripts/start_server.sh dev
```

Then open:

```text
http://127.0.0.1:5173
```

The development runtime uses a dedicated local environment and does not need to
reuse a normal Karkinos account.

Stop it with:

```bash
./scripts/stop_server.sh dev
```

For the managed `main` runtime, logs, status commands, existing-account startup,
or the legacy immutable-release workflow, see
[scripts/README.md](scripts/README.md).

## Development checks

Install the locked development environment:

```bash
uv sync --locked --extra server --extra dev
```

Run the backend test suite:

```bash
uv run --locked python -m pytest
```

Run the main frontend checks:

```bash
npm --prefix web run format:check
npm --prefix web run test
npm --prefix web run build
```

Run narrow checks first when working on a focused change. The repository CI is
the authoritative full verification path.

## Documentation

Start with [docs/README.md](docs/README.md).

The canonical engineering documents are intentionally small:

* [Goal](docs/GOAL.md) — product purpose and hard boundaries.
* [Architecture](docs/ARCHITECTURE.md) — durable domain and ownership rules.
* [Plan](docs/PLAN.md) — current development scope.
* [Engineering](docs/ENGINEERING.md) — current codebase reality, structural debt,
  and engineering guidance.
* [References](docs/REFERENCES.md) — mature open-source designs used for
  conceptual comparison.

Stable operational and financial notes live under
[docs/guides/](docs/guides/).

Implementation history belongs in Git rather than in parallel roadmaps or
implementation diaries.

## Project status

Karkinos is under active development.

`dev` is the normal development branch. `main` receives verified development
commits through the repository promotion workflow.

Current priorities are intentionally kept out of this README; see
[docs/PLAN.md](docs/PLAN.md).

## Safety

Karkinos is research and investing software, not investment advice or a
guarantee of returns.

Do not commit or publish:

* API keys or credentials;
* broker passwords or private authentication material;
* real account exports or transaction history;
* runtime databases;
* private logs or screenshots containing financial information.

Use sanitized synthetic data for tests and public bug reports.

See [SECURITY.md](SECURITY.md) for the security policy.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before making repository changes.

Substantial quantitative-domain or architecture work should also consult
[docs/REFERENCES.md](docs/REFERENCES.md) before introducing a new
Karkinos-specific abstraction.

## Technology

Python · FastAPI · SQLite · React · TypeScript · Vite

Additional data and analytical dependencies are documented in
`pyproject.toml` and `web/package.json`.

## License

Karkinos is released under the [MIT License](LICENSE).
