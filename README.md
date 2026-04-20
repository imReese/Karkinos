# MyQuant

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
git clone <repo-url> && cd MyQuant
cp .env.example .env                   # optional: set tokens / runtime paths
uv sync                                # install dependencies
uv run python main.py                  # run backtest
uv sync --extra server                 # install server extras
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
./scripts/stop_server.sh

cd web
npm install
npm run dev                            # start React frontend → http://localhost:5173
```

**Docker**

```bash
docker compose up -d                   # build & start → http://localhost:8000
```

Uses `./config.json` as runtime config and persists market cache / SQLite data in the `myquant-data` Docker volume.

**Tech Stack**

Python 3.12 + FastAPI + React + TanStack Query + TanStack Router + ECharts + SQLite + Parquet

**License**

MIT
