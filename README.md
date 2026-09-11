<div align="center">

# Karkinos

**Local-first quantitative research and investing platform for the China market.**

*Investing is a chronic condition. Here is your scalpel.*

[简体中文](README.zh.md) · [Documentation](docs/README.md) · [Releases](https://github.com/imReese/Karkinos/releases)

[![Dev CI](https://github.com/imReese/Karkinos/actions/workflows/dev-ci.yml/badge.svg?branch=dev)](https://github.com/imReese/Karkinos/actions/workflows/dev-ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/imReese/Karkinos?display_name=tag)](https://github.com/imReese/Karkinos/releases)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-24.x-5FA04E?logo=nodedotjs&logoColor=white)](web/package.json)
[![License](https://img.shields.io/github/license/imReese/Karkinos)](LICENSE)

</div>

Karkinos connects China-market data, point-in-time research, portfolio construction,
risk, simulation, accounting, attribution, and optional AI-assisted research in one
local-first workflow.

## Latest

| | |
| --- | --- |
| **Latest release** | [GitHub Releases](https://github.com/imReese/Karkinos/releases) |
| **Current focus** | [Engineering Reset and platform reliability](docs/PLAN.md) |
| **Development** | `dev` is the active development branch; verified commits are promoted to `main` |

## What works today

| Area | Available today |
| --- | --- |
| **Data** | China-market provider integration, local persistence, trading calendars, and point-in-time research inputs |
| **Research** | Strategy research, backtesting, transaction-cost modeling, parameter exploration, out-of-sample and robustness evaluation |
| **Portfolio & Accounting** | Portfolio views, valuation, fees, return accounting, local financial state, and reconciliation workflows |
| **Evaluation** | Backtest, paper, shadow, and risk-gated simulation workflows |
| **AI-assisted Research** | Optional API-backed research assistance; canonical quantitative and financial results remain deterministic |
| **Web App** | FastAPI backend with a React / TypeScript interface and local runtime |

## How Karkinos works

```text
Market Data
    |
    v
PIT Dataset
    |
    v
Research / Evaluation
    |
    v
Published Forecast
    |
    v
Portfolio Target
    |
    v
Risk Decision
    |
    v
Rebalance Plan
   /            \
  v              v
Simulation /    Human-supervised
Paper / Shadow   Execution
  |              |
  v              v
Outcome      Fills / Financial Events
   \            /
    v          v
 Accounting / Attribution
          |
          v
   Alpha / Model Health
          |
          +--------------------> Research
```

## Why Karkinos

- **Point-in-time research** — use information available at the modeled decision time.
- **Reproducible evidence** — bind results to data, assumptions, parameters, and time boundaries.
- **After-cost evaluation** — include fees, taxes, turnover, liquidity, and execution assumptions where they matter.
- **Portfolio before orders** — predictive output becomes portfolio intent before it becomes execution intent.
- **China-market semantics** — calendars, suspensions, price limits, lot rules, and other market constraints are first-class concerns.
- **Continuous feedback** — outcomes feed attribution and Alpha / Model health back into research.
- **AI-assisted, not AI-authoritative** — AI can accelerate research iteration without owning market facts, financial state, or capital authority.
- **Local-first ownership** — core research artifacts, portfolio state, and primary calculations remain locally owned.

## Quick start

Requirements: **Python 3.12+**, **Node.js 24.x**, **uv**, and **Git**.

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
git switch dev
./scripts/start_server.sh dev
```

Open:

```text
http://127.0.0.1:5173
```

Stop the development runtime with:

```bash
./scripts/stop_server.sh dev
```

Runtime and maintenance commands: [scripts/README.md](scripts/README.md)

## Documentation

- [Goal](docs/GOAL.md) — product direction and boundaries
- [Architecture](docs/ARCHITECTURE.md) — domain ownership and system design
- [Plan](docs/PLAN.md) — current development focus
- [Engineering](docs/ENGINEERING.md) — current codebase and engineering constraints
- [Guides](docs/guides/) — configuration and financial semantics
- [References](docs/REFERENCES.md) — upstream quantitative design references

## Project

**Technology:** Python · FastAPI · SQLite · React · TypeScript · Vite

**Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)

**Security:** [SECURITY.md](SECURITY.md)

**License:** [MIT](LICENSE)

Karkinos is research and investing software, not investment advice or a guarantee of returns.
