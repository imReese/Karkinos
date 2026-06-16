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
- Strategy registry exposes typed parameter schemas, and backtest requests can
  use validated generic `params` while preserving legacy moving-average fields
- Backtest parameter sweeps run bounded typed grids, persist each tested
  configuration, and return deterministic rankings with multiple-testing
  warnings; the Web Strategy Lab can run the same bounded sweep and review the
  ranked configurations without approving execution
- Backtest strategy comparisons can run multiple strategies or parameter sets
  against one frozen dataset snapshot, reject mismatched snapshots, and return
  saved result ids for audit; the Web Strategy Lab can submit same-strategy
  parameter-set comparisons and review the shared snapshot evidence
- Backtest reports record a dataset snapshot with data-source/cache metadata,
  requested range, symbol universe, row counts, adjustment mode when available,
  and data-quality diagnostics, and the Web report exposes that audit panel for
  saved and freshly run results
- Backtest results persist a strategy metadata snapshot with strategy identity,
  parameter schema, normalized params, benchmark role, and validation
  requirements so saved reports remain auditable when the registry changes; Web
  reports render the snapshot with readable strategy and parameter labels while
  keeping API keys as secondary audit fields
- Web Backtest reports surface after-cost evidence, out-of-sample split status,
  benchmark comparison, structured cost/slippage assumptions, and limitations
  without turning research output into execution approval
- Web Backtest Strategy Lab selects registry strategies, renders typed
  parameter controls with readable labels, exposes strategy metadata and
  validation requirements, and can run a single-symbol research backtest from
  the browser
- Multi-asset: A-shares / ETF / Gold / Bond
- Target-weight signals — strategy outputs 0~1, Portfolio handles share counts
- T+1 freeze/thaw built into Position
- Live monitoring with Telegram / WeChat push notifications
- React + TanStack Query + TanStack Router portfolio workspace
- Responsive cockpit layout: primary pages reflow at desktop/narrow widths, while wide tables scroll inside their own panels
- Portfolio quote board summarizes asset classes; instrument-level quote, cost, and OHLC/K-line context lives in holding detail pages and the Market research workspace.
- Return calendar cockpit view: inspect audited attribution by day, week, month, or year with calendar/curve/table views and amount/return-rate toggles. The calendar starts weeks on Sunday, uses market PnL for cells, reads historical daily close from the local `market_bars` OHLC cache before falling back to daily-close snapshots, breaks daily market moves into stock/fund/other buckets, keeps deposits, withdrawals, dividends, and manual adjustments as external-flow context, skips non-trading, stale, or intraday terminal quote moves, marks periods with incomplete adjacent valuation coverage instead of presenting fabricated returns, and includes axes in the curve view.
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

`http://localhost:8000` is the product/customer entry. It serves the built React app from `web/dist`, so direct links such as `/portfolio`, `/activity`, `/risk`, `/decision`, `/market`, and `/settings` can be refreshed without returning home.

The data-source setup command writes ignored local `config.json` for you. It hides TuShare token input, never accepts tokens as CLI arguments, and is optional when you are happy with the default AKShare provider. Settings saved from the Web cockpit persist local runtime preferences such as `data_source`, `live_poll_interval`, and the current account commission rule (`account_commission_rate`, `account_min_commission`) back into the same ignored config file.

Use this storage boundary:

- `config.json`: local runtime preferences and deploy-specific knobs, including provider selection, poll interval, notification settings, CORS origins, and the current account commission rule.
- SQLite under `data/store/`: mutable financial facts and cache state, including watchlists, instrument metadata, ledger entries, quotes, bars, portfolio snapshots, trading controls, and saved backtest indexes.
- `reports/`: human-readable generated artifacts such as backtest JSON reports and data reconciliation outputs. Reports are runtime evidence, not source code.

Initial screens do not seed portfolio assets, trades, or fund names. Effective
portfolio data comes from the local database or explicit private runtime
configuration; for example, Activity batch fund candidates are derived from
held fund positions instead of built-in defaults.

The web cockpit localizes portfolio asset classes in the selected UI language
and keeps ledger rows auditable: trade activity surfaces the instrument name
and symbol when present, amount, quantity, price, and commission without
exposing technical confirmation metadata.

Backtest results are indexed in the local SQLite database at
`data/store/app.db` so the Web cockpit, risk workspace, and strategy promotion
checks can query them. Each saved backtest also writes a human-readable JSON
artifact under `reports/backtest/backtest-result-<id>.json` by default. Set
`KARKINOS_BACKTEST_REPORT_DIR` to place those local report files elsewhere.
The report directory is runtime data and should stay out of git.

Historical OHLCV market bars are stored in the local SQLite table
`data/store/meta.db.market_bars`; Parquet files under `data/store/bars/` are a
local mirror for compatibility and inspection. To import existing Parquet
mirrors into SQLite without fetching remote data, run
`uv run python scripts/sync_market_bars_to_db.py`. Cached data is auditable by
provider, fetch time, range, row count, and diagnostics, but it is not a
guarantee that every provider or public website will show identical values;
differences can come from adjustment mode, delayed fund NAVs, suspended
sessions, stale source data, or provider corrections.
For an explicit one-symbol reconciliation report, run for example:
`uv run python scripts/verify_market_bars.py --symbol 603659 --start 2026-06-12 --end 2026-06-15`.
The verifier fetches provider bars for comparison and returns JSON differences;
it does not overwrite the local cache.

In `dev` mode the script also starts Vite at `http://localhost:5173` for hot-reload frontend editing. Treat `5173` as a developer-only URL; use `8000` for product-like demos and customer flow checks.

The API only trusts local Vite origins by default:
`http://localhost:5173` and `http://127.0.0.1:5173`. For a real deployment,
set `KARKINOS_CORS_ALLOWED_ORIGINS` or `cors_allowed_origins` in your private
runtime config to the exact browser origins you operate. Avoid `*` for public
or credentialed deployments.

**Strategy Extensions**

Local research strategies belong under `strategy/extensions/`. Karkinos
discovers sanitized `*.strategy.json` manifests from that directory, or from
`KARKINOS_STRATEGY_EXTENSION_DIR`, and exposes their typed parameter schema via
`/api/backtest/strategies`. The committed `.example` files show the interface;
copied private strategy scripts and manifests stay ignored by git.

For private scripts stored directly in the extension directory, `class_path`
may point to the local module in `module:ClassName` form, for example
`local_momentum:LocalMomentumStrategy`. Karkinos loads that class only when a
registered extension is instantiated for a research backtest, then validates
its declared params before constructing the strategy.

Extension manifests cannot declare live trading, broker submission, or
real-money execution capabilities. Strategy Lab runs remain research evidence
and do not bypass risk gates, paper/shadow review, signal journaling, or manual
confirmation.

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
