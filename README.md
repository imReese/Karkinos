# MyQuant

个人量化交易辅助系统 — 面向中国市场的回测 + 实时监控 + Web 仪表盘

[中文文档](README.zh.md) | [English Docs](README.en.md)

---

**Highlights**

- Event-driven architecture with deterministic backtesting
- Multi-asset: A-shares / ETF / Gold / Bond
- Target-weight signals — strategy outputs 0~1, Portfolio handles share counts
- T+1 freeze/thaw built into Position
- Live monitoring with Telegram / WeChat push notifications
- Vue 3 + ECharts Web dashboard (6 views)
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
uv sync                                # install dependencies
uv run python main.py                  # run backtest
uv sync --extra server                 # install server extras
uv run python -m server                # start web server → http://localhost:8000
```

**Docker**

```bash
docker compose up -d                   # build & start → http://localhost:8000
```

**Tech Stack**

Python 3.12 + FastAPI + Vue 3 + Pinia + ECharts + SQLite + Parquet

**License**

MIT
