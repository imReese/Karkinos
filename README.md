# Karkinos

Karkinos: Investing is a chronic condition. Here is your scalpel.
（Karkinos：投资是一种慢性病。这是你的手术刀。）

个人量化交易辅助系统 — 面向中国市场的回测 + 实时监控 + Web 仪表盘

[中文文档](docs/README.zh.md) | [English Docs](docs/README.en.md)

---

**Highlights**

- Event-driven architecture with deterministic backtesting
- Multi-asset: A-shares / ETF / Gold / Bond
- Target-weight signals — strategy outputs 0~1, Portfolio handles share counts
- T+1 freeze/thaw built into Position
- Live monitoring with Telegram / WeChat push notifications
- React + TanStack Query + TanStack Router portfolio workspace
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
uv run python main.py                  # run backtest
uv sync --extra server                 # install server extras
cd web && npm install && cd ..
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
./scripts/stop_server.sh
```

`http://localhost:8000` is the product/customer entry. It serves the built React app from `web/dist`, so direct links such as `/portfolio`, `/activity`, `/risk`, `/market`, and `/settings` can be refreshed without returning home.

In `dev` mode the script also starts Vite at `http://localhost:5173` for hot-reload frontend editing. Treat `5173` as a developer-only URL; use `8000` for product-like demos and customer flow checks.

**Docker**

```bash
docker compose up -d                   # build & start → http://localhost:8000
```

Uses `./config.json` as runtime config and persists market cache / SQLite data in the `karkinos-data` Docker volume.

**Tech Stack**

Python 3.12 + FastAPI + React + TanStack Query + TanStack Router + ECharts + SQLite + Parquet

**License**

MIT
