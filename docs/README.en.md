# Karkinos — Personal Quantitative Trading Assistant

[中文](README.zh.md) | [Back to Summary](../README.md)

---

## Overview

Karkinos is a personal quantitative trading system designed for the Chinese market. It features an event-driven architecture with a backtest-first, daily-bar-oriented design, supporting A-shares, ETFs, gold spot, and exchange-traded bonds.

Key Features:

- **Event-Driven Architecture** — All components communicate through EventBus, ensuring deterministic backtesting
- **Multi-Asset Support** — A-shares, ETFs, gold spot, exchange-traded bonds; Instrument field values carry asset differences
- **Target Weight Signals** — Strategies output target weights (0~1), Portfolio auto-converts to share counts
- **T+1 Support** — Built-in freeze/thaw mechanism in Position, auto-advanced on settlement day
- **Live Monitoring** — Standalone Live mode + built-in Scheduler in Web service, with signal push notifications
- **Notifications** — Console / Telegram / WeChat (ServerChan) channels
- **Web UI** — React + TypeScript + TanStack Router + TanStack Query + ECharts workspace
- **Docker One-Click Deploy** — Multi-stage build, all-in-one frontend + backend image

## Architecture

```
DataHandler → EventBus → Strategy → Portfolio → OrderIntent → Risk Gate → Order/Gateway
                        ↑                                                     |
                        └──────────────── FillEvent ──────────────────────────┘
```

Backtests use deterministic OrderIntent approval wiring. Live mode uses
`PreTradeRiskManager` before `ManualConfirmGateway`; the legacy `RiskManager`
subscribes by priority but EventBus handlers do not consume or stop propagation.

**Core Principles:**

- **Event-Driven**: All components communicate through EventBus, ensuring deterministic backtesting
- **Target Weight Signals**: Strategies output target weights (0~1), Portfolio converts to share counts
- **Instrument Carries Asset Differences**: All asset-specific behavior is expressed through field values — no isinstance checks downstream
- **Backtest First**: Synchronous event bus with SimulatedClock for reproducibility
- **T+1 Support**: Built-in freeze/thaw mechanism in Position, auto-advanced on settlement day

## Project Structure

```
Karkinos/
├── core/                   # Core infrastructure
│   ├── types.py            # Type definitions (Symbol, Money, enums, constants)
│   ├── events.py           # Event types (Market, Signal, Order, Fill, RiskAlert)
│   ├── event_bus.py        # Synchronous event bus (priority-based subscription)
│   └── clock.py            # Clock abstraction (SimulatedClock / LiveClock)
├── domain/                 # Domain model layer
│   ├── instrument.py       # Instrument (frozen dataclass + factory functions)
│   ├── bar.py              # Bar data (OHLCV)
│   ├── tick.py             # Tick data
│   ├── order.py            # Order (state tracking)
│   ├── fill.py             # Fill record
│   ├── position.py         # Position (T+1 freeze/thaw, mark-to-market, P&L)
│   └── portfolio.py        # Portfolio (target weight → share count conversion)
├── data/                   # Data pipeline layer
│   ├── source.py           # DataSource ABC
│   ├── providers/          # Data source adapters
│   │   ├── akshare_source.py  # AKShare adapter (stock/ETF/gold/bond)
│   │   └── tushare_source.py  # Tushare adapter (stock daily)
│   ├── store.py            # Parquet + SQLite storage engine
│   ├── handler.py          # DataHandler (bar replay)
│   ├── features.py         # FeatureEngine (SMA/EMA/RSI/ATR/Bollinger)
│   ├── live.py             # LiveDataFeed (real-time quote polling)
│   └── manager.py          # DataManager (cache-first → fetch-on-demand)
├── strategy/               # Strategy framework layer
│   ├── base.py             # Strategy ABC (on_init/on_data/on_fill)
│   ├── signals.py          # SignalType + Signal data model
│   └── examples/           # Example strategies
│       ├── dual_ma.py      # Dual moving average crossover
│       └── monthly_rebalance.py  # Monthly target-weight rebalance
├── execution/              # Execution engine layer
│   ├── engine.py           # ExecutionEngine ABC
│   ├── simulator.py        # SimulatedExecution (backtest)
│   ├── broker.py           # LiveExecution (placeholder)
│   ├── slippage.py         # Slippage models (fixed/percent/volume)
│   └── commission.py       # Commission models (A-share/ETF/gold/bond)
├── risk/                   # Risk management layer
│   ├── manager.py          # RiskManager (legacy OrderEvent checks; cannot consume EventBus events)
│   ├── rules.py            # RiskRule ABC + RiskCheckResult
│   └── limits.py           # Position limit / max drawdown / concentration rules
├── backtest/               # Backtest engine
│   ├── engine.py           # BacktestEngine (main loop)
│   ├── result.py           # BacktestResult (result container)
│   └── viewer.py           # matplotlib equity curve visualization
├── analytics/              # Analytics layer
│   ├── metrics.py          # Sharpe / Sortino / max drawdown / win rate / annualized return
│   ├── report.py           # Report generation
│   └── equity.py           # Equity curve utilities
├── server/                 # Web service layer
│   ├── app.py              # FastAPI app factory + lifecycle management
│   ├── __main__.py         # CLI entry point (--host/--port/--reload/--no-live)
│   ├── bridge.py           # EventBusBridge (sync → async event bridging)
│   ├── db.py               # SQLite persistence (signals/backtests/quote snapshots/ledger)
│   ├── models.py           # Pydantic v2 request/response models
│   ├── scheduler.py        # TradingScheduler (live trading loop)
│   ├── dependencies.py     # FastAPI dependency injection
│   ├── routes/             # REST routes
│   │   ├── market.py       #   /api/market — quotes/watchlist/kline
│   │   ├── portfolio.py    #   /api/portfolio — snapshot/allocation/equity-curve
│   │   ├── signals.py      #   /api/signals — history/latest
│   │   ├── backtest.py     #   /api/backtest — run/results
│   │   └── settings.py     #   /api/settings — config/live/notifications
│   └── ws/                 # WebSocket
│       ├── hub.py          #   ConnectionHub (connection management + broadcast)
│       └── handlers.py     #   /ws endpoint (real-time event push)
├── notification/           # Notification system
│   ├── notifier.py         # Notifier ABC + factory + message formatting
│   ├── console.py          # ConsoleNotifier (terminal output)
│   ├── telegram.py         # TelegramNotifier (Bot API)
│   └── wechat.py           # WeChatNotifier (ServerChan)
├── web/                    # React frontend
│   ├── src/
│   │   ├── app/            # Router, layout, global preferences, i18n copy
│   │   ├── features/       # Account / portfolio / activity modules
│   │   └── styles/         # Tailwind-powered global styles
│   └── package.json
├── tools/                  # Local developer / operations CLI tools
│   ├── run_backtest.py     # Local backtest tool
│   └── live_monitor.py     # Compatibility standalone monitor (Web service uses TradingScheduler)
├── live.py                 # Compatibility wrapper; prefer tools.live_monitor
├── config.py               # Typed configuration loader (BacktestConfig + ServerConfig)
├── main.py                 # Compatibility wrapper; prefer tools.run_backtest
├── config.example.json     # Configuration template
├── Dockerfile              # Multi-stage build (Node build + Python runtime)
├── docker-compose.yml      # One-click deployment
└── tests/                  # Tests
```

## Installation

### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager

### Install Dependencies

```bash
# Clone the repository
git clone <repo-url> && cd Karkinos

# Install core dependencies (uv creates .venv automatically)
uv sync

# Install server extras (FastAPI / uvicorn / aiosqlite / websockets)
uv sync --extra server
```

## Quick Start

### Run Backtest

```bash
# Run default dual moving average strategy with synthetic data
uv run python -m tools.run_backtest
```

Example output:

```
==================================================
         Karkinos Backtest Report
==================================================
Initial Cash:      1,000,000.00 CNY
Final Equity:        985,210.62 CNY
Total P&L:          -14,789.38 CNY
Total Return:            -1.48%
Annualized Return:       -3.11%
Sharpe Ratio:            -3.24
Sortino Ratio:           -3.55
Max Drawdown:             1.98%
Win Rate:                 8.40%
Duration (days):           168
--------------------------------------------------
Positions:
  600519: qty=500, avg_cost=1749.04, pnl=-15430.31
==================================================
```

### Start Web Server

```bash
# Install server dependencies
uv sync --extra server

# Development mode with reload, background process, PID and log files
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000

# Stop the service
./scripts/stop_server.sh

# Production-style startup
./scripts/start_server.sh prod --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000> for the Web dashboard.

In development mode the launcher starts both backend and frontend:

```bash
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
```

This starts:

- backend API on `http://127.0.0.1:8000`
- Vite frontend on `http://127.0.0.1:5173`

Stop both with:

```bash
./scripts/stop_server.sh
```

Open <http://localhost:5173> for the React UI during local development, or use `http://localhost:8000` for the production build served by FastAPI.

### Docker Deployment

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f
```

By default the container reads `./config.json` as runtime config and persists market cache / SQLite data in the `karkinos-data` volume. `config.json` is not market data, holdings, or asset metadata storage; those records belong in local SQLite tables such as `latest_quotes`, `market_bars`, `ledger_entries`, and `instrument_metadata`.

See [Docker Deployment](#docker-deployment) section for details.

## Configuration

### config.json Fields

Do not hand-edit tokens into `config.json`. Use the local onboarding command:

```bash
uv run python scripts/configure_data_source.py
```

The command lets you choose `akshare` or `tushare`, prompts for a TuShare token only when needed, hides token input, and writes ignored local `config.json` for you. `config.example.json` is only a reference for advanced runtime fields.

#### Server Runtime Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"127.0.0.1"` | Server listen address |
| `port` | int | `8000` | Server listen port |
| `live_auto_start` | bool | `true` | Auto-start Web built-in live monitoring |
| `data_source` | string | `"akshare"` | Data source (`akshare` / `tushare`) |
| `tushare_token` | string | `""` | Local TuShare token written by the onboarding script; `TUSHARE_TOKEN` can also be used |
| `notification` | object | `{"type":"console"}` | Notification config |
| `live_poll_interval` | int | `60` | Live polling interval (seconds) |
| `cors_allowed_origins` | array | local Vite origins | Frontend origins allowed to call the API |

Capital, holdings, watchlists, asset names, historical prices, and latest quotes are not runtime config: capital and trades come from the ledger, user-tracked assets come from `watchlist_assets`, asset identity comes from `instrument_metadata`, latest quotes come from `latest_quotes`, and historical bars come from `market_bars` / the local data cache.

#### notification Format

```json
"notification": {
    "type": "console",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "wechat_sendkey": ""
}
```

`type` values: `console`, `telegram`, `wechat`

### Environment Variables

| Variable | Description | Config Field |
|----------|-------------|-------------|
| `TUSHARE_TOKEN` | Tushare API token | — (auto-enables Tushare data source) |
| `KARKINOS_HOST` | Server listen address | `ServerConfig.host` |
| `KARKINOS_PORT` | Server listen port | `ServerConfig.port` |

### Priority Chain

```
CLI args > Environment variables > config.json > Defaults
```

Example: `python -m server --port 9000` takes precedence over `KARKINOS_PORT=8080`, which takes precedence over `"port": 8000` in config.json.

## CLI Reference

### python -m tools.run_backtest (Local Backtest Tool)

```bash
uv run python -m tools.run_backtest
```

Reads `config.json`, runs backtest, and outputs report. Uses `DataManager` cache-first strategy for data fetching.
The root `main.py` file is only a compatibility wrapper. It is not the Web service entry point.

### python -m server (Server)

```bash
uv run python -m server [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--host` | str | `0.0.0.0` | Listen address |
| `--port` | int | `8000` | Listen port |
| `--reload` | flag | `False` | Enable hot-reload dev mode |
| `--no-live` | flag | `False` | Disable auto-start of live monitoring |

### python -m tools.live_monitor (Standalone Monitor Tool)

```bash
uv run python -m tools.live_monitor
```

Standalone compatibility monitor, independent of the Web server. It reads `config.json`, polls market data, runs strategy, and pushes signals via notification channels. The professional Web/Live path should use `python -m server` or `./scripts/start_server.sh`; that path uses `TradingScheduler`, `PreTradeRiskManager`, and `ManualConfirmGateway`. The root `live.py` file is only a compatibility wrapper. Press `Ctrl+C` to exit.

## API Reference

### REST Endpoints

#### Market — /api/market

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/market/watchlist` | Get watchlist + latest quotes |
| GET | `/api/market/quote/{symbol}` | Get quote for a single symbol |
| GET | `/api/market/kline/{symbol}?start=&end=` | Get historical K-line data |

#### Portfolio — /api/portfolio

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Get portfolio snapshot (cash/equity/positions/allocation) |
| GET | `/api/portfolio/cockpit` | Get cockpit weights, actual weights, drift, action queue, and risk alerts |
| GET | `/api/portfolio/state` | Get account overview, snapshot, risk summary, and next step |
| GET | `/api/portfolio/risk-summary` | Get portfolio risk summary |
| GET | `/api/portfolio/live-holdings` | Get live holdings grouped by asset class |
| GET | `/api/portfolio/allocation` | Get asset allocation weights |
| GET | `/api/portfolio/equity-curve` | Get equity curve |

#### Signals — /api/signals

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/signals?limit=&offset=` | Get signal history (paginated) |
| GET | `/api/signals/latest?limit=` | Get latest signals |
| GET | `/api/signals/actions?limit=` | Get action cards with latest risk-gate summary |
| GET | `/api/signals/journal?limit=&offset=` | Get signal → action → risk audit chain |
| POST | `/api/signals/journal/{signal_id}/review` | Record a post-decision signal review/outcome event |

Action cards expose `risk_gate_status` as `not_checked`, `passed`, or `blocked`
so an actionable signal without a risk decision is never presented as executable.
They also expose manual-confirmation readiness: `awaiting_risk_gate`,
`ready_for_manual_confirmation`, or `blocked_by_risk_gate`. Even when the risk
gate passes, manual confirmation remains required before execution.

`POST /api/signals/journal/{signal_id}/review` records the later outcome and
review notes for a generated signal as an immutable audit event. It does not
change an action task, create an order, submit to a broker, or mark a fill.

#### Decision Cockpit — /api/decision

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/decision/today` | Get today's read-only decision summary, candidate actions, evidence bundle, and no-action reasons |
| GET | `/api/decision/intraday` | Get a read-only intraday candidate-action view for stocks and common exchange-traded ETFs |

`GET /api/decision/today` aggregates existing action tasks, risk-gate state,
signal journal entries, and latest quote freshness into `buy`, `sell`, `hold`,
`rebalance`, `no_action`, or `review_required`. It reads existing facts only:
it does not create orders, submit to a broker, or change the manual-confirmation
default.

`GET /api/decision/intraday` uses the same evidence-bundle shape but only admits
stock and common exchange-traded ETF candidates. Open-end fund and long-horizon
allocation actions stay in the daily lane. The endpoint is for polling/minute-
level cockpit review, not high-frequency or millisecond trading, and it never
executes automatically.

#### Trading Controls — /api/trading

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/trading/actions/{action_id}/manual-order` | Create a pending manual order only from a risk-passed action card |
| POST | `/api/trading/shadow-runs/daily` | Record a daily paper/shadow run from risk-passed action cards |
| GET | `/api/trading/orders?status=` | List manual orders awaiting or past operator confirmation |
| POST | `/api/trading/orders/{order_id}/confirm` | Mark a manual order as operator-confirmed |
| POST | `/api/trading/orders/{order_id}/reject` | Mark a manual order as operator-rejected |
| GET | `/api/trading/order-facts` | List shared order facts for manual, paper, and live-like paths |
| POST | `/api/trading/order-facts/{order_id}/shadow-divergence-review` | Record paper/shadow divergence review evidence |
| GET | `/api/trading/fills` | List persisted fill facts |
| GET | `/api/trading/kill-switch` | Read the runtime kill switch |
| PUT | `/api/trading/kill-switch` | Update the runtime kill switch |

`POST /api/trading/actions/{action_id}/manual-order` accepts an operator-supplied
quantity and stores a `pending_confirm` manual order plus shared order fact. It
rejects `awaiting_risk_gate` and `blocked_by_risk_gate` actions and does not
submit to a broker or mark the order filled. Confirming or rejecting that manual
order updates the originating action card decision state (`acted` or `ignored`)
and is surfaced in the signal journal audit chain.

`POST /api/trading/shadow-runs/daily` records deterministic `paper_shadow`
order facts for action cards that already passed the risk gate. It skips
blocked or not-yet-checked actions, does not create manual orders, does not
submit to a broker, and does not mark fills. Re-running the same `run_date` and
action reuses the existing order fact; `shadow_run_schema_version`,
`reused_count`, and `reused_orders` make idempotent reruns auditable without
writing duplicate orders or order events.
Before writing, the daily shadow run also checks `latest_quotes` for the action
symbol. Missing quotes, non-`live` quote status, or non-positive prices are
reported in `data_quality.issues` and skipped with a `data_quality:*` reason
without creating a shadow order.

`POST /api/trading/order-facts/{order_id}/shadow-divergence-review` records an
operator review such as `within_expectations` on an existing `paper_shadow`
order fact. It does not change order status, submit to a broker, or create a
fill.

#### Backtest — /api/backtest

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/backtest/strategies` | List strategies with v0.2 benchmark / OOS / after-cost requirements |
| GET | `/api/backtest/strategy-validation` | Get the v0.2 benchmark strategy after-cost / OOS evidence matrix |
| GET | `/api/backtest/strategy-promotion-readiness` | Get promotion-readiness gates for benchmark strategies |
| POST | `/api/backtest/run` | Run backtest (in thread pool), return result |
| GET | `/api/backtest/results` | List all backtest result summaries |
| GET | `/api/backtest/results/{result_id}` | Get single backtest detail + equity curve |

`GET /api/backtest/strategy-validation` reads saved backtest results and reports
whether each v0.2 benchmark strategy has after-cost and out-of-sample evidence.
It is for audit and promotion checks, not investment advice.

`GET /api/backtest/strategy-promotion-readiness` combines saved after-cost/OOS
validation, blocked-risk evidence, paper/shadow order facts, and explicit
paper/shadow divergence review evidence. It never promotes a strategy
automatically and does not change execution defaults.

#### Settings — /api/settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Read current configuration |
| PUT | `/api/settings` | Update in-memory runtime settings; business state remains in SQLite |
| POST | `/api/settings/live/start` | Start live monitoring |
| POST | `/api/settings/live/stop` | Stop live monitoring |
| GET | `/api/settings/live/status` | Query live monitoring status |
| POST | `/api/settings/notification/test` | Send test notification |

### WebSocket — /ws

Streams EventBus events in real-time after connection. Each message includes an `event_type` field:

| event_type | Fields |
|------------|--------|
| `MarketEvent` | timestamp, symbol, open, high, low, close, volume, frequency, asset_class |
| `SignalEvent` | timestamp, strategy_id, symbol, target_weight, price |
| `OrderEvent` | timestamp, order_id, symbol, side, order_type, quantity, price |
| `FillEvent` | timestamp, fill_id, order_id, symbol, side, fill_price, fill_quantity, commission, slippage |
| `RiskAlertEvent` | timestamp, alert_id, rule_name, severity, message, symbol, order_id |

## Docker Deployment

### Dockerfile (Multi-Stage Build)

- **Stage 1** (`node:20-alpine`): Builds React frontend with `npm ci && npm run build`, output to `web/dist/`
- **Stage 2** (`python:3.12-slim`): Copies source + frontend dist, installs server dependencies, sets `KARKINOS_CONFIG_PATH=/app/config.json` and `KARKINOS_DATA_DIR=/app/data/store`, then starts with `python -m server`

### docker-compose.yml

```yaml
services:
  karkinos:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - karkinos-data:/app/data/store
      - ./config.json:/app/config.json:ro
    environment:
      - TZ=Asia/Shanghai
      - TUSHARE_TOKEN=${TUSHARE_TOKEN:-}
      - KARKINOS_HOST=0.0.0.0
      - KARKINOS_PORT=8000
      - KARKINOS_CONFIG_PATH=/app/config.json
      - KARKINOS_DATA_DIR=/app/data/store
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/settings', timeout=5).read()"]
      interval: 30s
```

### Usage

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Override Port

```bash
# Use port 9000
KARKINOS_PORT=9000 docker compose up -d
# Or modify ports in docker-compose.yml to "9000:9000"
```

### Data Volumes

- `karkinos-data`: Mounted at `/app/data/store`, stores Parquet files and SQLite database. Data persists across container rebuilds.

## Web Frontend

### Tech Stack

React 19 + TypeScript + TanStack Router + TanStack Query + ECharts/Recharts + Vite

### Views

| View | Path | Description |
|------|------|-------------|
| DashboardView | `/` | Dashboard, portfolio overview + live indicators |
| PortfolioView | `/portfolio` | Position details + allocation pie chart |
| ActivityView | `/activity` | Trades, dividends, cash flows, and manual adjustments |
| MarketView | `/market` | Market quotes + K-line chart |
| SignalsView | `/signals` | Signal history + signal badges |
| BacktestView | `/backtest` | Run backtest + equity curve |
| SettingsView | `/settings` | Config management + live control + notification test |

Initial screens do not seed effective user assets, trades, or fund names.
Portfolio assets, holdings, and ledger activity come from the local database or
explicit private runtime configuration; Activity batch fund candidates are
derived from held fund positions instead of frontend defaults.

### Development

```bash
cd web
npm install
npm run dev       # Dev server, proxies /api → localhost:8000
npm run build     # Build production bundle to dist/
```

## Strategy Development

Extend the `Strategy` base class and implement `on_init` and `on_data`:

```python
from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy

class MyStrategy(Strategy):
    def __init__(self, event_bus: EventBus):
        super().__init__("my_strategy", event_bus)

    def on_init(self, symbols: list[Symbol]) -> None:
        self.symbols = symbols

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        # Your trading logic here
        if event.close > 1850:
            self.emit_signal(event.symbol, target_weight=1.0, price=float(event.close))
        else:
            self.emit_signal(event.symbol, target_weight=0.0, price=float(event.close))
```

`emit_signal(symbol, target_weight, price)` publishes a `SignalEvent` to the EventBus. Portfolio converts the target weight to specific share counts.

## Notification System

Three notification channels:

| Channel | type value | Description |
|---------|-----------|-------------|
| Console | `console` | Terminal output (default) |
| Telegram | `telegram` | Push via Bot API |
| WeChat | `wechat` | Push via ServerChan |

### Configuration Examples

```json
{
    "notification": {
        "type": "telegram",
        "telegram_bot_token": "123456:ABC-DEF",
        "telegram_chat_id": "987654321"
    }
}
```

```json
{
    "notification": {
        "type": "wechat",
        "wechat_sendkey": "SCTxxxxx"
    }
}
```

Signal push message format:

```
📈 Trading Signal
Symbol: 600519
Direction: LONG
Target Weight: 100.0%
Price: 1850.50
Strategy: dual_ma
Time: 2025-06-15 14:30:00
```

## Technical Indicators

`FeatureEngine` supports the following indicators:

| Indicator | Method | Output Columns |
|-----------|--------|---------------|
| SMA | `sma(df, col, period)` | `sma_5`, `sma_20`, `sma_60` |
| EMA | `ema(df, col, period)` | `ema_12`, `ema_26` |
| RSI | `rsi(df, col, period)` | `rsi` |
| ATR | `atr(df, period)` | `atr` |
| Bollinger Bands | `bollinger(df, col, period)` | `boll_mid`, `boll_upper`, `boll_lower` |

Usage example:

```python
from data.features import FeatureEngine

engine = FeatureEngine()
df_with_features = engine.add_all_features(df)
# Includes columns: sma_5, sma_20, sma_60, ema_12, ema_26, rsi, atr, boll_mid, boll_upper, boll_lower
```

## Risk Management

The legacy `RiskManager` subscribes to `OrderEvent` at `priority=-10`, so it can audit orders and publish risk alerts before Execution (priority=0). The synchronous EventBus does not let one handler consume an event, so this class cannot stop later handlers by itself.

The current Live safety path is `OrderIntentEvent` → `PreTradeRiskManager` → `RiskDecisionEvent`/`OrderEvent` → `ManualConfirmGateway`. Backtests use deterministic compatibility wiring inside `BacktestEngine` to approve `OrderIntentEvent` without depending on Live state.

Three built-in rules:

| Rule | Class | Description |
|------|-------|-------------|
| Position Limit | `PositionLimitRule(max_quantity)` | Rejects buys that would exceed max quantity per symbol |
| Max Drawdown | `MaxDrawdownRule(max_drawdown_pct)` | Rejects buys when portfolio drawdown exceeds threshold |
| Concentration | `ConcentrationRule(max_concentration)` | Rejects buys that would make a single symbol exceed max portfolio weight |

Usage example:

```python
from risk.manager import RiskManager
from risk.limits import PositionLimitRule, MaxDrawdownRule, ConcentrationRule
from decimal import Decimal

risk_mgr = RiskManager(event_bus)
risk_mgr.add_rule(PositionLimitRule(max_quantity=Decimal("1000")))
risk_mgr.add_rule(MaxDrawdownRule(max_drawdown_pct=Decimal("0.15")))
risk_mgr.add_rule(ConcentrationRule(max_concentration=Decimal("0.30")))
```

In the `PreTradeRiskManager` path, rejected orders publish `RiskDecisionEvent` / `RiskAlertEvent` and do not produce an `OrderEvent`. The legacy `RiskManager` requires cooperation from the execution layer to block an order.

## Commission Models

| Asset Type | Commission | Stamp Tax | Transfer Fee |
|-----------|-----------|-----------|-------------|
| A-Share | max(amount x 0.03‰, ¥5) | Sell 0.05‰ | 0.01‰ |
| ETF | max(amount x 0.03‰, ¥5) | None | 0.01‰ |
| Gold Spot | amount x 0.08% | — | — |
| Exchange Bond | max(amount x 0.004‰, ¥1) | — | — |

`MultiAssetCommission` auto-routes to the correct calculator based on `CommissionType`.

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Event Bus | Synchronous + Priority | Backtest determinism; risk checks before execution |
| Signal Model | Target Weight | Strategy doesn't need to care about lot sizes |
| Instrument | Frozen Dataclass | Immutable + field values carry asset differences |
| Money Type | Decimal | Avoid floating-point precision issues |
| Time Advance | SimulatedClock | Externally controlled, reproducible |
| Data Storage | Parquet + SQLite | Columnar storage efficiency + flexible metadata queries |
| Event Bridge | EventBusBridge | Lossless sync EventBus → async WebSocket conversion |
| Live Scheduling | TradingScheduler | Daemon thread + Event.wait() for instant stop |

## License

MIT
