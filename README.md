# MyQuant — 个人量化交易辅助系统

[English](#english) | [中文](#中文)

---

<a id="中文"></a>

## 中文

### 概述

MyQuant 是一个面向中国市场的个人量化交易辅助系统，采用事件驱动架构，以回测优先、日线为主的设计理念，支持 A 股、ETF、黄金现货、交易所债券等资产类型。

### 架构

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

### 项目结构

```
MyQuant/
├── core/                   # 核心基础设施
│   ├── types.py            # 类型定义（Symbol, Money, 枚举, 常量）
│   ├── events.py           # 事件类型（Market, Signal, Order, Fill, RiskAlert）
│   ├── event_bus.py        # 同步事件总线（优先级订阅）
│   └── clock.py            # 时钟抽象（SimulatedClock / LiveClock）
├── domain/                 # 领域模型层
│   ├── instrument.py       # 标的资产（frozen dataclass + 5 个工厂函数）
│   ├── bar.py              # K 线数据（OHLCV）
│   ├── tick.py             # 逐笔数据
│   ├── order.py            # 委托单（状态跟踪）
│   ├── fill.py             # 成交记录
│   ├── position.py         # 持仓管理（T+1 冻结/解冻/盯市/盈亏）
│   └── portfolio.py        # 组合管理（目标权重→股数转换）
├── data/                   # 数据管线层
│   ├── source.py           # DataSource ABC
│   ├── providers/          # 数据源适配器
│   │   ├── akshare_source.py  # AKShare 适配器
│   │   └── tushare_source.py  # Tushare 适配器
│   ├── store.py            # Parquet + SQLite 存储引擎
│   ├── handler.py          # DataHandler（K 线回放）
│   └── features.py         # FeatureEngine（SMA/EMA/RSI/ATR/布林带）
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
├── utils/                  # 工具层
│   ├── logger.py           # 结构化日志
│   ├── date_utils.py       # A 股交易日历
│   ├── math_utils.py       # 收益/风险计算辅助
│   └── decorators.py       # 计时/重试装饰器
├── config.py               # 类型化配置加载
├── main.py                 # 入口：组装组件 → 运行回测 → 输出报告
├── config.example.json     # 配置模板
├── secret.example.py       # API key 模板
└── tests/                  # 测试（77 个用例）
```

### 快速开始

#### 环境要求

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器

#### 安装

```bash
# 克隆仓库
git clone <repo-url> && cd MyQuant

# 安装依赖（uv 会自动创建 .venv）
uv sync
```

#### 运行回测

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

#### 运行测试

```bash
# 全量测试
uv run pytest tests/ -v

# 单模块测试
uv run pytest tests/domain/ -v
```

### 使用指南

#### 1. 自定义策略

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

#### 2. 配置回测参数

复制 `config.example.json` 为 `config.json` 并修改：

```json
{
    "initial_cash": "1000000",
    "start_date": "2024-01-02",
    "end_date": "2024-12-31",
    "symbols": ["600519", "510300"],
    "strategy": "dual_ma",
    "short_period": 5,
    "long_period": 20
}
```

#### 3. 使用真实数据

```python
from data.providers.akshare_source import AKShareSource
from data.store import DataStore
from data.handler import DataHandler
from datetime import datetime
from core.types import Symbol, BarFrequency

# 通过 AKShare 获取数据
source = AKShareSource()
df = source.fetch_bars(
    Symbol("600519"),
    start=datetime(2023, 1, 1),
    end=datetime(2023, 12, 31),
)

# 可选：缓存到本地
store = DataStore("data/store")
store.save_bars(Symbol("600519"), BarFrequency.DAILY, df)

# 创建 DataHandler
handler = DataHandler(df, Symbol("600519"))
```

#### 4. 风控规则

```python
from risk.manager import RiskManager
from risk.limits import PositionLimitRule, MaxDrawdownRule, ConcentrationRule
from decimal import Decimal

risk_mgr = RiskManager(event_bus)
risk_mgr.add_rule(PositionLimitRule(max_quantity=Decimal("1000")))
risk_mgr.add_rule(MaxDrawdownRule(max_drawdown_pct=Decimal("0.15")))
risk_mgr.add_rule(ConcentrationRule(max_concentration=Decimal("0.30")))
```

#### 5. 佣金模型

| 资产类型 | 佣金 | 印花税 | 过户费 |
|---------|------|--------|--------|
| A 股 | max(金额 x 万三, 5元) | 卖出万五 | 万一 |
| ETF | max(金额 x 万三, 5元) | 无 | 万一 |
| 黄金现货 | 金额 x 0.08% | — | — |
| 交易所债券 | max(金额 x 万0.4, 1元) | — | — |

### 技术指标

`FeatureEngine` 支持以下指标：

- **SMA** — 简单移动平均
- **EMA** — 指数移动平均
- **RSI** — 相对强弱指标
- **ATR** — 平均真实波幅
- **Bollinger Bands** — 布林带

```python
from data.features import FeatureEngine

engine = FeatureEngine()
df_with_features = engine.add_all_features(df)
# 包含列: sma_5, sma_20, sma_60, ema_12, ema_26, rsi, atr, boll_mid, boll_upper, boll_lower
```

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 事件总线 | 同步 + 优先级 | 回测确定性，风控先于执行 |
| 信号模型 | 目标权重 | 避免策略关心股数/手数细节 |
| 标的抽象 | frozen dataclass | 不可变 + 字段值承载差异 |
| 金额类型 | Decimal | 避免浮点精度问题 |
| 时间推进 | SimulatedClock | 外部控制，保证可复现 |
| 数据存储 | Parquet + SQLite | 列式存储高效 + 元数据灵活查询 |

---

<a id="english"></a>

## English

### Overview

MyQuant is a personal quantitative trading system designed for the Chinese market. It features an event-driven architecture with a backtest-first, daily-bar-oriented design, supporting A-shares, ETFs, gold spot, and exchange-traded bonds.

### Architecture

```
DataHandler → EventBus → Strategy → Portfolio → RiskManager(-10) → Execution(0)
                        ↑                                              |
                        └──────────── FillEvent ──────────────────────┘
```

**Core Principles:**

- **Event-Driven**: All components communicate through EventBus, ensuring deterministic backtesting
- **Target Weight Signals**: Strategies output target weights (0~1), Portfolio converts to share counts
- **Instrument Carries Asset Differences**: All asset-specific behavior is expressed through field values — no isinstance checks downstream
- **Backtest First**: Synchronous event bus with SimulatedClock for reproducibility
- **T+1 Support**: Built-in freeze/thaw mechanism in Position, auto-advanced on settlement day

### Project Structure

```
MyQuant/
├── core/                   # Core infrastructure
│   ├── types.py            # Type definitions (Symbol, Money, enums, constants)
│   ├── events.py           # Event types (Market, Signal, Order, Fill, RiskAlert)
│   ├── event_bus.py        # Synchronous event bus (priority-based subscription)
│   └── clock.py            # Clock abstraction (SimulatedClock / LiveClock)
├── domain/                 # Domain model layer
│   ├── instrument.py       # Instrument (frozen dataclass + 5 factory functions)
│   ├── bar.py              # Bar data (OHLCV)
│   ├── tick.py             # Tick data
│   ├── order.py            # Order (state tracking)
│   ├── fill.py             # Fill record
│   ├── position.py         # Position (T+1 freeze/thaw, mark-to-market, P&L)
│   └── portfolio.py        # Portfolio (target weight → share count conversion)
├── data/                   # Data pipeline layer
│   ├── source.py           # DataSource ABC
│   ├── providers/          # Data source adapters
│   │   ├── akshare_source.py  # AKShare adapter
│   │   └── tushare_source.py  # Tushare adapter
│   ├── store.py            # Parquet + SQLite storage engine
│   ├── handler.py          # DataHandler (bar replay)
│   └── features.py         # FeatureEngine (SMA/EMA/RSI/ATR/Bollinger)
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
│   ├── manager.py          # RiskManager (priority=-10 intercept)
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
├── utils/                  # Utilities
│   ├── logger.py           # Structured logging
│   ├── date_utils.py       # A-share trading calendar
│   ├── math_utils.py       # Return/risk calculation helpers
│   └── decorators.py       # Timing / retry decorators
├── config.py               # Typed configuration loader
├── main.py                 # Entry point: assemble → run backtest → output report
├── config.example.json     # Configuration template
├── secret.example.py       # API key template
└── tests/                  # Tests (77 test cases)
```

### Quick Start

#### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager

#### Installation

```bash
# Clone the repository
git clone <repo-url> && cd MyQuant

# Install dependencies (uv creates .venv automatically)
uv sync
```

#### Run Backtest

```bash
# Run default dual moving average strategy with synthetic data
uv run python main.py
```

Example output:

```
==================================================
         MyQuant Backtest Report
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

#### Run Tests

```bash
# Full test suite
uv run pytest tests/ -v

# Single module
uv run pytest tests/domain/ -v
```

### Usage Guide

#### 1. Custom Strategy

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

#### 2. Configure Backtest Parameters

Copy `config.example.json` to `config.json` and modify:

```json
{
    "initial_cash": "1000000",
    "start_date": "2024-01-02",
    "end_date": "2024-12-31",
    "symbols": ["600519", "510300"],
    "strategy": "dual_ma",
    "short_period": 5,
    "long_period": 20
}
```

#### 3. Use Real Market Data

```python
from data.providers.akshare_source import AKShareSource
from data.store import DataStore
from data.handler import DataHandler
from datetime import datetime
from core.types import Symbol, BarFrequency

# Fetch data via AKShare
source = AKShareSource()
df = source.fetch_bars(
    Symbol("600519"),
    start=datetime(2023, 1, 1),
    end=datetime(2023, 12, 31),
)

# Optional: cache locally
store = DataStore("data/store")
store.save_bars(Symbol("600519"), BarFrequency.DAILY, df)

# Create DataHandler
handler = DataHandler(df, Symbol("600519"))
```

#### 4. Risk Management Rules

```python
from risk.manager import RiskManager
from risk.limits import PositionLimitRule, MaxDrawdownRule, ConcentrationRule
from decimal import Decimal

risk_mgr = RiskManager(event_bus)
risk_mgr.add_rule(PositionLimitRule(max_quantity=Decimal("1000")))
risk_mgr.add_rule(MaxDrawdownRule(max_drawdown_pct=Decimal("0.15")))
risk_mgr.add_rule(ConcentrationRule(max_concentration=Decimal("0.30")))
```

#### 5. Commission Models

| Asset Type | Commission | Stamp Tax | Transfer Fee |
|-----------|-----------|-----------|-------------|
| A-Share | max(amount x 0.03‰, ¥5) | Sell 0.05‰ | 0.01‰ |
| ETF | max(amount x 0.03‰, ¥5) | None | 0.01‰ |
| Gold Spot | amount x 0.08% | — | — |
| Exchange Bond | max(amount x 0.004‰, ¥1) | — | — |

### Technical Indicators

`FeatureEngine` supports the following indicators:

- **SMA** — Simple Moving Average
- **EMA** — Exponential Moving Average
- **RSI** — Relative Strength Index
- **ATR** — Average True Range
- **Bollinger Bands**

```python
from data.features import FeatureEngine

engine = FeatureEngine()
df_with_features = engine.add_all_features(df)
# Includes columns: sma_5, sma_20, sma_60, ema_12, ema_26, rsi, atr, boll_mid, boll_upper, boll_lower
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Event Bus | Synchronous + Priority | Backtest determinism; risk checks before execution |
| Signal Model | Target Weight | Strategy doesn't need to care about lot sizes |
| Instrument | Frozen Dataclass | Immutable + field values carry asset differences |
| Money Type | Decimal | Avoid floating-point precision issues |
| Time Advance | SimulatedClock | Externally controlled, reproducible |
| Data Storage | Parquet + SQLite | Columnar storage efficiency + flexible metadata queries |

### License

MIT
