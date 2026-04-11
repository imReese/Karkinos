# MyQuant — 个人量化交易辅助系统

[English](README.en.md) | [返回摘要](README.md)

---

## 概述

MyQuant 是一个面向中国市场的个人量化交易辅助系统，采用事件驱动架构，以回测优先、日线为主的设计理念，支持 A 股、ETF、黄金现货、交易所债券等资产类型。

核心特性：

- **事件驱动架构** — 所有组件通过 EventBus 解耦通信，保证回测确定性
- **多资产支持** — A 股、ETF、黄金现货、交易所债券，Instrument 字段值承载差异
- **目标权重信号** — 策略输出目标权重（0~1），Portfolio 自动转换为具体股数
- **T+1 支持** — Position 内置冻结/解冻机制，每日结算自动推进
- **实时监控** — 独立 Live 模式 + Web 服务内建 Scheduler，支持策略信号推送
- **通知推送** — Console / Telegram / 企业微信三通道
- **Web UI** — Vue 3 + ECharts 仪表盘，6 个视图实时展示
- **Docker 一键部署** — 多阶段构建，前后端一体镜像

## 架构

```
DataHandler → EventBus → Strategy → Portfolio → RiskManager(-10) → Execution(0)
                        ↑                                              |
                        └──────────── FillEvent ──────────────────────┘
```

**核心原则：**

- **事件驱动**：所有组件通过 EventBus 解耦通信，保证回测确定性
- **目标权重信号**：策略输出目标权重（0~1），由 Portfolio 转换为具体股数
- **Instrument 承载资产差异**：所有资产差异通过字段值表达，下游无 isinstance 判断
- **回测优先**：同步事件总线，SimulatedClock 保证可复现
- **T+1 支持**：Position 内置冻结/解冻机制，每日结算自动推进

## 项目结构

```
MyQuant/
├── core/                   # 核心基础设施
│   ├── types.py            # 类型定义（Symbol, Money, 枚举, 常量）
│   ├── events.py           # 事件类型（Market, Signal, Order, Fill, RiskAlert）
│   ├── event_bus.py        # 同步事件总线（优先级订阅）
│   └── clock.py            # 时钟抽象（SimulatedClock / LiveClock）
├── domain/                 # 领域模型层
│   ├── instrument.py       # 标的资产（frozen dataclass + 工厂函数）
│   ├── bar.py              # K 线数据（OHLCV）
│   ├── tick.py             # 逐笔数据
│   ├── order.py            # 委托单（状态跟踪）
│   ├── fill.py             # 成交记录
│   ├── position.py         # 持仓管理（T+1 冻结/解冻/盯市/盈亏）
│   └── portfolio.py        # 组合管理（目标权重→股数转换）
├── data/                   # 数据管线层
│   ├── source.py           # DataSource ABC
│   ├── providers/          # 数据源适配器
│   │   ├── akshare_source.py  # AKShare 适配器（股票/ETF/黄金/债券）
│   │   └── tushare_source.py  # Tushare 适配器（股票日线）
│   ├── store.py            # Parquet + SQLite 存储引擎
│   ├── handler.py          # DataHandler（K 线回放）
│   ├── features.py         # FeatureEngine（SMA/EMA/RSI/ATR/布林带）
│   ├── live.py             # LiveDataFeed（实时行情轮询）
│   └── manager.py          # DataManager（缓存优先 → 按需抓取）
├── strategy/               # 策略框架层
│   ├── base.py             # Strategy ABC（on_init/on_data/on_fill）
│   ├── signals.py          # SignalType + Signal 数据模型
│   └── examples/           # 策略示例
│       ├── dual_ma.py      # 双均线交叉策略
│       └── monthly_rebalance.py  # 月度目标权重再平衡
├── execution/              # 执行引擎层
│   ├── engine.py           # ExecutionEngine ABC
│   ├── simulator.py        # SimulatedExecution（回测模拟）
│   ├── broker.py           # LiveExecution（实盘预留）
│   ├── slippage.py         # 滑点模型（固定/百分比/成交量）
│   └── commission.py       # 佣金模型（A股/ETF/黄金/债券）
├── risk/                   # 风控管理层
│   ├── manager.py          # RiskManager（priority=-10 拦截订单）
│   ├── rules.py            # RiskRule ABC + RiskCheckResult
│   └── limits.py           # 仓位上限/最大回撤/集中度规则
├── backtest/               # 回测引擎
│   ├── engine.py           # BacktestEngine（主循环）
│   ├── result.py           # BacktestResult（结果容器）
│   └── viewer.py           # matplotlib 资金曲线可视化
├── analytics/              # 分析层
│   ├── metrics.py          # Sharpe/Sortino/最大回撤/胜率/年化收益
│   ├── report.py           # 报告生成
│   └── equity.py           # 权益曲线工具
├── server/                 # Web 服务层
│   ├── app.py              # FastAPI 应用工厂 + 生命周期管理
│   ├── __main__.py         # CLI 入口（--host/--port/--reload/--no-live）
│   ├── bridge.py           # EventBusBridge（同步→异步事件桥接）
│   ├── db.py               # SQLite 持久化（信号/回测/组合快照）
│   ├── models.py           # Pydantic v2 请求/响应模型
│   ├── scheduler.py        # TradingScheduler（实时交易循环）
│   ├── dependencies.py     # FastAPI 依赖注入
│   ├── routes/             # REST 路由
│   │   ├── market.py       #   /api/market — 行情/关注列表/K 线
│   │   ├── portfolio.py    #   /api/portfolio — 组合/配置/权益曲线
│   │   ├── signals.py      #   /api/signals — 信号历史/最新信号
│   │   ├── backtest.py     #   /api/backtest — 运行回测/结果查询
│   │   └── settings.py     #   /api/settings — 配置/实盘/通知
│   └── ws/                 # WebSocket
│       ├── hub.py          #   ConnectionHub（连接管理 + 广播）
│       └── handlers.py     #   /ws 端点（实时事件推送）
├── notification/           # 通知系统
│   ├── notifier.py         # Notifier ABC + 工厂 + 消息格式化
│   ├── console.py          # ConsoleNotifier（终端输出）
│   ├── telegram.py         # TelegramNotifier（Bot API）
│   └── wechat.py           # WeChatNotifier（Server酱）
├── web/                    # Vue 3 前端
│   ├── src/
│   │   ├── views/          # 6 个视图（仪表盘/组合/行情/信号/回测/设置）
│   │   ├── components/     # 组件（K 线图/权益曲线/配置饼图等）
│   │   ├── stores/         # Pinia 状态管理
│   │   └── api/            # Axios API 客户端
│   └── package.json
├── live.py                 # 独立实时监控入口
├── config.py               # 类型化配置加载（BacktestConfig + ServerConfig）
├── main.py                 # 回测入口
├── config.example.json     # 配置模板
├── Dockerfile              # 多阶段构建（Node 构建 + Python 运行）
├── docker-compose.yml      # 一键部署编排
└── tests/                  # 测试
```

## 安装

### 环境要求

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装依赖

```bash
# 克隆仓库
git clone <repo-url> && cd MyQuant

# 安装核心依赖（uv 自动创建 .venv）
uv sync

# 安装服务端额外依赖（FastAPI / uvicorn / aiosqlite / websockets）
uv sync --extra server
```

## 快速开始

### 运行回测

```bash
# 使用模拟数据运行默认双均线策略回测
uv run python main.py
```

输出示例：

```
==================================================
         MyQuant 回测报告
==================================================
初始资金:      1,000,000.00 CNY
最终权益:        985,210.62 CNY
总盈亏:          -14,789.38 CNY
总收益率:            -1.48%
年化收益:            -3.11%
Sharpe比率:          -3.24
Sortino比率:         -3.55
最大回撤:             1.98%
胜率:                 8.40%
回测天数:              168
--------------------------------------------------
持仓:
  600519: 数量=500, 均价=1749.04, 盈亏=-15430.31
==================================================
```

### 启动 Web 服务

```bash
# 安装服务端依赖
uv sync --extra server

# 启动服务（默认 0.0.0.0:8000，自动开启实时监控）
uv run python -m server

# 开发模式（热重载）
uv run python -m server --reload

# 禁用自动开启实时监控
uv run python -m server --no-live
```

访问 http://localhost:8000 打开 Web 仪表盘。

### Docker 部署

```bash
# 构建并启动
docker compose up -d

# 查看日志
docker compose logs -f
```

详见 [Docker 部署](#docker-部署) 章节。

## 配置

### config.json 字段说明

复制 `config.example.json` 为 `config.json` 并按需修改。

#### BacktestConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `initial_cash` | number | `1000000` | 初始资金（CNY） |
| `start_date` | string | `"2025-01-02"` | 回测起始日期 |
| `end_date` | string | `"2026-04-11"` | 回测结束日期 |
| `assets` | array | `[...]` | 资产列表，每项含 `symbol` 和 `asset_class` |
| `strategy` | string | `"dual_ma"` | 策略名称 |
| `short_period` | int | `5` | 短均线周期 |
| `long_period` | int | `20` | 长均线周期 |
| `commission_rate` | number | `0.0003` | 佣金费率（万三） |
| `data_source` | string | `"akshare"` | 数据源（`akshare` / `tushare`） |
| `notification` | object | `{"type":"console"}` | 通知配置 |
| `live_poll_interval` | int | `60` | 实时轮询间隔（秒） |

#### ServerConfig（继承 BacktestConfig）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | string | `"0.0.0.0"` | 服务监听地址 |
| `port` | int | `8000` | 服务监听端口 |
| `live_auto_start` | bool | `true` | 是否自动启动实时监控 |

#### assets 字段格式

```json
"assets": [
    {"symbol": "600519", "asset_class": "stock"},
    {"symbol": "510300", "asset_class": "etf"},
    {"symbol": "Au99.99", "asset_class": "gold"},
    {"symbol": "sh010107", "asset_class": "bond"}
]
```

`asset_class` 可选值：`stock`、`etf`、`gold`、`bond`

#### notification 字段格式

```json
"notification": {
    "type": "console",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "wechat_sendkey": ""
}
```

`type` 可选值：`console`、`telegram`、`wechat`

### 环境变量

| 变量 | 说明 | 对应配置字段 |
|------|------|-------------|
| `TUSHARE_TOKEN` | Tushare API Token | — （自动启用 Tushare 数据源） |
| `MYQUANT_HOST` | 服务监听地址 | `ServerConfig.host` |
| `MYQUANT_PORT` | 服务监听端口 | `ServerConfig.port` |

### 优先级链

```
CLI 参数 > 环境变量 > config.json > 默认值
```

示例：`python -m server --port 9000` 优先于 `MYQUANT_PORT=8080`，优先于 `config.json` 中的 `"port": 8000`。

## CLI 参考

### python main.py（回测）

```bash
uv run python main.py
```

读取 `config.json`，运行回测并输出报告。使用 `DataManager` 缓存优先策略获取数据。

### python -m server（服务）

```bash
uv run python -m server [选项]
```

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--host` | str | `0.0.0.0` | 监听地址 |
| `--port` | int | `8000` | 监听端口 |
| `--reload` | flag | `False` | 开启热重载开发模式 |
| `--no-live` | flag | `False` | 禁用自动开启实时监控 |

### python live.py（独立监控）

```bash
uv run python live.py
```

独立的实时监控入口，不依赖 Web 服务。读取 `config.json`，轮询行情数据，运行策略并通过通知通道推送信号。`Ctrl+C` 退出。

## API 参考

### REST 端点

#### 行情 — /api/market

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/market/watchlist` | 获取关注列表 + 最新报价 |
| GET | `/api/market/quote/{symbol}` | 获取单个标的报价 |
| GET | `/api/market/kline/{symbol}?start=&end=` | 获取历史 K 线数据 |

#### 组合 — /api/portfolio

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/portfolio` | 获取组合快照（现金/权益/持仓/配置） |
| GET | `/api/portfolio/allocation` | 获取资产配置权重 |
| GET | `/api/portfolio/equity-curve` | 获取权益曲线 |

#### 信号 — /api/signals

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/signals?limit=&offset=` | 获取信号历史（分页） |
| GET | `/api/signals/latest?limit=` | 获取最新信号 |

#### 回测 — /api/backtest

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backtest/run` | 运行回测（线程池执行），返回结果 |
| GET | `/api/backtest/results` | 获取所有回测结果摘要 |
| GET | `/api/backtest/results/{result_id}` | 获取单个回测详情 + 权益曲线 |

#### 设置 — /api/settings

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 读取当前配置 |
| PUT | `/api/settings` | 更新配置（写入 config.json） |
| POST | `/api/settings/live/start` | 启动实时监控 |
| POST | `/api/settings/live/stop` | 停止实时监控 |
| GET | `/api/settings/live/status` | 查询实时监控状态 |
| POST | `/api/settings/notification/test` | 发送测试通知 |

### WebSocket — /ws

连接后实时推送 EventBus 事件，每条消息包含 `event_type` 字段：

| event_type | 字段 |
|------------|------|
| `MarketEvent` | timestamp, symbol, open, high, low, close, volume, frequency, asset_class |
| `SignalEvent` | timestamp, strategy_id, symbol, target_weight, price |
| `OrderEvent` | timestamp, order_id, symbol, side, order_type, quantity, price |
| `FillEvent` | timestamp, fill_id, order_id, symbol, side, fill_price, fill_quantity, commission, slippage |
| `RiskAlertEvent` | timestamp, alert_id, rule_name, severity, message, symbol, order_id |

## Docker 部署

### Dockerfile（多阶段构建）

- **Stage 1**（`node:20-alpine`）：构建 Vue 前端，`npm ci && npm run build`，输出到 `web/dist/`
- **Stage 2**（`python:3.12-slim`）：安装 uv，`uv pip install --system -e ".[server]"`，复制源码 + 前端产物，暴露 8000 端口，默认命令 `python3 -m server`

### docker-compose.yml

```yaml
services:
  myquant:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - myquant-data:/app/data/store    # Parquet + SQLite 数据持久化
      - ./config.json:/app/config.json:ro  # 配置文件（只读）
    environment:
      - TZ=Asia/Shanghai
      - TUSHARE_TOKEN=${TUSHARE_TOKEN:-}
      - MYQUANT_HOST=${MYQUANT_HOST:-0.0.0.0}
      - MYQUANT_PORT=${MYQUANT_PORT:-8000}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/settings"]
      interval: 30s
```

### 使用方式

```bash
# 构建并启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

### 覆盖端口

```bash
# 使用 9000 端口
MYQUANT_PORT=9000 docker compose up -d
# 或修改 docker-compose.yml 中 ports 为 "9000:9000"
```

### 数据卷

- `myquant-data`：挂载到 `/app/data/store`，存储 Parquet 文件和 SQLite 数据库，容器重建后数据不丢失

## Web 前端

### 技术栈

Vue 3 + TypeScript + Pinia + Vue Router + ECharts + Axios + Vite

### 视图说明

| 视图 | 路径 | 说明 |
|------|------|------|
| DashboardView | `/` | 仪表盘，组合概览 + 实时指标 |
| PortfolioView | `/portfolio` | 持仓明细 + 配置饼图 |
| MarketView | `/market` | 行情报价 + K 线图 |
| SignalsView | `/signals` | 信号历史 + 信号徽章 |
| BacktestView | `/backtest` | 运行回测 + 权益曲线 |
| SettingsView | `/settings` | 配置管理 + 实盘控制 + 通知测试 |

### 开发

```bash
cd web
npm install
npm run dev       # 开发服务器，代理 /api → localhost:8000
npm run build     # 构建生产版本到 dist/
```

## 策略开发

继承 `Strategy` 基类，实现 `on_init` 和 `on_data`：

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
        # 你的交易逻辑
        if event.close > 1850:
            self.emit_signal(event.symbol, target_weight=1.0, price=float(event.close))
        else:
            self.emit_signal(event.symbol, target_weight=0.0, price=float(event.close))
```

`emit_signal(symbol, target_weight, price)` 向 EventBus 发布 `SignalEvent`，由 Portfolio 将目标权重转换为具体股数。

## 通知系统

三种通知通道：

| 通道 | type 值 | 说明 |
|------|---------|------|
| Console | `console` | 终端输出（默认） |
| Telegram | `telegram` | 通过 Bot API 推送 |
| 企业微信 | `wechat` | 通过 Server酱 推送 |

### 配置示例

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

信号推送消息格式：

```
📈 交易信号
标的: 600519
方向: LONG
目标权重: 100.0%
价格: 1850.50
策略: dual_ma
时间: 2025-06-15 14:30:00
```

## 技术指标

`FeatureEngine` 支持以下指标：

| 指标 | 方法 | 输出列 |
|------|------|--------|
| SMA | `sma(df, col, period)` | `sma_5`, `sma_20`, `sma_60` |
| EMA | `ema(df, col, period)` | `ema_12`, `ema_26` |
| RSI | `rsi(df, col, period)` | `rsi` |
| ATR | `atr(df, period)` | `atr` |
| 布林带 | `bollinger(df, col, period)` | `boll_mid`, `boll_upper`, `boll_lower` |

使用示例：

```python
from data.features import FeatureEngine

engine = FeatureEngine()
df_with_features = engine.add_all_features(df)
# 包含列: sma_5, sma_20, sma_60, ema_12, ema_26, rsi, atr, boll_mid, boll_upper, boll_lower
```

## 风控管理

`RiskManager` 以 `priority=-10` 订阅 `OrderEvent`，在 Execution（priority=0）之前拦截订单。

三条内置规则：

| 规则 | 类 | 说明 |
|------|-----|------|
| 仓位上限 | `PositionLimitRule(max_quantity)` | 单标的持仓数量不超过上限 |
| 最大回撤 | `MaxDrawdownRule(max_drawdown_pct)` | 组合回撤超限时禁止买入 |
| 集中度限制 | `ConcentrationRule(max_concentration)` | 单标的权重不超过组合总值比例 |

使用示例：

```python
from risk.manager import RiskManager
from risk.limits import PositionLimitRule, MaxDrawdownRule, ConcentrationRule
from decimal import Decimal

risk_mgr = RiskManager(event_bus)
risk_mgr.add_rule(PositionLimitRule(max_quantity=Decimal("1000")))
risk_mgr.add_rule(MaxDrawdownRule(max_drawdown_pct=Decimal("0.15")))
risk_mgr.add_rule(ConcentrationRule(max_concentration=Decimal("0.30")))
```

订单被拒绝时，RiskManager 发布 `RiskAlertEvent` 并阻断订单传递。

## 佣金模型

| 资产类型 | 佣金 | 印花税 | 过户费 |
|---------|------|--------|--------|
| A 股 | max(金额 x 万三, 5元) | 卖出万五 | 万一 |
| ETF | max(金额 x 万三, 5元) | 无 | 万一 |
| 黄金现货 | 金额 x 0.08% | — | — |
| 交易所债券 | max(金额 x 万0.4, 1元) | — | — |

`MultiAssetCommission` 根据 `CommissionType` 自动路由到对应计算器。

## 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 事件总线 | 同步 + 优先级 | 回测确定性，风控先于执行 |
| 信号模型 | 目标权重 | 避免策略关心股数/手数细节 |
| 标的抽象 | frozen dataclass | 不可变 + 字段值承载差异 |
| 金额类型 | Decimal | 避免浮点精度问题 |
| 时间推进 | SimulatedClock | 外部控制，保证可复现 |
| 数据存储 | Parquet + SQLite | 列式存储高效 + 元数据灵活查询 |
| 事件桥接 | EventBusBridge | 同步 EventBus → 异步 WebSocket 无损转换 |
| 实时调度 | TradingScheduler | daemon 线程 + Event.wait() 即时停止 |

## 许可证

MIT
