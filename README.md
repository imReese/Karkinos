# Karkinos

Karkinos: Investing is a chronic condition. Here is your scalpel.
（Karkinos：投资是一种慢性病。这是你的手术刀。）

个人量化交易辅助系统 — 面向中国市场的回测 + 实时监控 + Web 仪表盘

[中文文档](docs/README.zh.md) | [English Docs](docs/README.en.md)

---

**Disclaimer**

Karkinos is research and portfolio tooling, not investment advice. Market data,
portfolio valuation, backtest results, and trading outcomes are not guaranteed
to be accurate or complete. Do not use this project as the sole basis for
investment decisions.

Do not commit real account data, brokerage credentials, transaction exports,
personal financial data, runtime databases, logs, or screenshots containing
private information. Use example configuration and fake or sanitized data for
public demos and development.

**Highlights**

- Event-driven architecture with deterministic backtesting
- Multi-asset: A-shares / ETF / Gold / Bond
- Target-weight signals — strategy outputs 0~1, Portfolio handles share counts
- T+1 freeze/thaw built into Position
- Live monitoring with Telegram / WeChat push notifications
- React + TanStack Query + TanStack Router portfolio workspace
- Read-only decision cockpit APIs with portfolio, market-health, and after-cost/OOS evidence review, without automatic trading
- Docker one-click deploy

**Architecture**

```
DataHandler → EventBus → Strategy → Portfolio → RiskManager(-10) → Execution(0)
                        ↑                                              |
                        └──────────── FillEvent ──────────────────────┘
```

**Quick Start**

```bash
git clone <repo-url> && cd Karkinos
cp .env.example .env                   # optional: set tokens / runtime paths
uv sync                                # install dependencies
uv run python -m tools.run_backtest    # run local backtest tool
uv sync --extra server                 # install server extras
cd web && npm install && cd ..
uv run python scripts/configure_data_source.py  # optional: choose AKShare or TuShare safely
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
./scripts/stop_server.sh
```

`http://localhost:8000` is the product/customer entry. It serves the built React app from `web/dist`, so direct links such as `/portfolio`, `/activity`, `/risk`, `/market`, and `/settings` can be refreshed without returning home.

The data-source setup command writes ignored local `config.json` for you. It hides TuShare token input, never accepts tokens as CLI arguments, and is optional when you are happy with the default AKShare provider.

Initial screens do not seed portfolio assets, trades, or fund names. Effective
portfolio data comes from the local database or explicit private runtime
configuration; for example, Activity batch fund candidates are derived from
held fund positions instead of built-in defaults.

In `dev` mode the script also starts Vite at `http://localhost:5173` for hot-reload frontend editing. Treat `5173` as a developer-only URL; use `8000` for product-like demos and customer flow checks.

The API only trusts local Vite origins by default:
`http://localhost:5173` and `http://127.0.0.1:5173`. For a real deployment,
set `KARKINOS_CORS_ALLOWED_ORIGINS` or `cors_allowed_origins` in your private
runtime config to the exact browser origins you operate. Avoid `*` for public
or credentialed deployments.

**Docker**

```bash
docker compose up -d                   # build & start → http://localhost:8000
```

Uses ignored local `./config.json` as runtime configuration and persists market cache / SQLite data in the `karkinos-data` Docker volume. Runtime config is not a market-data store; watchlists, quotes, bars, ledger entries, and portfolio state should live in the local database.

Runtime databases, local logs, exported files, screenshots, and local secret
files should stay on your machine and are not intended to be committed.

**Tech Stack**

Python 3.12 + FastAPI + React + TanStack Query + TanStack Router + ECharts + SQLite + Parquet

**License**

MIT
