# Karkinos — 个人量化交易辅助系统

[English](README.en.md) | [返回摘要](../README.md)

---

## 概述

Karkinos 是一个面向中国市场的个人量化交易辅助系统，采用事件驱动架构，以回测优先、日线为主的设计理念，支持 A 股、ETF、黄金现货、交易所债券等资产类型。

核心特性：

- **事件驱动架构** — 所有组件通过 EventBus 解耦通信，保证回测确定性
- **多资产支持** — A 股、ETF、黄金现货、交易所债券，Instrument 字段值承载差异
- **目标权重信号** — 策略输出目标权重（0~1），Portfolio 自动转换为具体股数
- **T+1 支持** — Position 内置冻结/解冻机制，每日结算自动推进
- **实时监控** — 独立 Live 模式 + Web 服务内建 Scheduler，支持策略信号推送
- **通知推送** — Console / Telegram / 微信 三通道
- **Web UI** — React + TypeScript + TanStack Router + TanStack Query + ECharts 资产工作台
- **响应式驾驶舱布局** — 主要页面按桌面/窄屏宽度重排，宽表格只在各自面板内横向滚动
- **持仓与行情详情** — Portfolio 持仓行情看板只做资产类别汇总，单只标的的行情、成本和 OHLC/K 线在持仓详情页与 Market 研究工作台中查看
- **收益日历** — 基于审计归因数据查看月内每日、年内每月与年度收益分布；周日作为每周第一列，日历主口径使用市场盈亏，历史日收盘优先读取本地 `market_bars` OHLC 缓存再回退到 daily-close 快照，当日市场变动会拆成股票/基金/其他资产，入金、出金、分红和手工调整作为外部资金事件展示，非交易日、陈旧或盘中终端行情不生成日历收益，相邻估值覆盖不足的周期会标记为缺价而不是展示成伪造收益，曲线视图保留横纵坐标
- **Docker 一键部署** — 多阶段构建，前后端一体镜像

## 架构

```
DataHandler → EventBus → Strategy → Portfolio → OrderIntent → Risk Gate → Order/Gateway
                        ↑                                                     |
                        └──────────────── FillEvent ──────────────────────────┘
```

回测路径使用确定性的 OrderIntent 审批胶水；Live 路径使用 `PreTradeRiskManager`
在 `ManualConfirmGateway` 之前做强制风控。旧 `RiskManager` 依赖订阅优先级，但
EventBus handler 不能消费或阻止后续 handler 传播。

**核心原则：**

- **事件驱动**：所有组件通过 EventBus 解耦通信，保证回测确定性
- **目标权重信号**：策略输出目标权重（0~1），由 Portfolio 转换为具体股数
- **Instrument 承载资产差异**：所有资产差异通过字段值表达，下游无 isinstance 判断
- **回测优先**：同步事件总线，SimulatedClock 保证可复现
- **T+1 支持**：Position 内置冻结/解冻机制，每日结算自动推进

## 项目结构

```
Karkinos/
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
│   ├── manager.py          # RiskManager（旧 OrderEvent 风控；不能消费 EventBus 事件）
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
│   ├── db.py               # SQLite 持久化（信号/回测/行情快照/流水）
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
├── web/                    # React 前端
│   ├── src/
│   │   ├── app/            # 路由、布局、全局偏好、多语言词典
│   │   ├── features/       # 账户 / 组合 / 流水模块
│   │   └── styles/         # 基于 Tailwind 的全局样式
│   └── package.json
├── tools/                  # 本地开发 / 运维 CLI 工具
│   ├── run_backtest.py     # 本地回测工具
│   └── live_monitor.py     # 兼容独立监控工具（Web 服务使用 TradingScheduler）
├── live.py                 # 兼容 wrapper；优先使用 tools.live_monitor
├── config.py               # 类型化配置加载（BacktestConfig + ServerConfig）
├── main.py                 # 兼容 wrapper；优先使用 tools.run_backtest
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
git clone <repo-url> && cd Karkinos

# 安装核心依赖（uv 自动创建 .venv）
uv sync

# 安装服务端额外依赖（FastAPI / uvicorn / aiosqlite / websockets）
uv sync --extra server
```

## 快速开始

### 运行回测

```bash
# 使用模拟数据运行默认双均线策略回测
uv run python -m tools.run_backtest
```

输出示例：

```
==================================================
         Karkinos 回测报告
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
总成交额:        1,000,000.00 CNY
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

# 安装前端依赖，用于构建 8000 产品入口需要的 web/dist
cd web && npm install && cd ..

# 开发模式启动：先构建产品前端包，再启动后端和 Vite 热更新服务
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000

# 停止服务
./scripts/stop_server.sh

# 生产方式启动
./scripts/start_server.sh prod --host 0.0.0.0 --port 8000
```

访问 <http://localhost:8000> 打开 Web 仪表盘。这个地址是产品/客户入口，刷新或直接打开 `/portfolio`、`/activity`、`/risk`、`/decision`、`/market`、`/settings` 等页面时，后端会返回前端应用入口并保留当前 URL。

开发模式下，启动脚本会同时拉起后端和前端：

```bash
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
```

它会同时启动：

- 产品入口 + 后端 API：`http://127.0.0.1:8000`
- 前端 Vite 热更新入口：`http://127.0.0.1:5173`

停止时统一执行：

```bash
./scripts/stop_server.sh
```

对外演示、客户使用、刷新/分享页面路径时使用 <http://localhost:8000。只有在编辑前端代码并需要热更新时才访问> <http://localhost:5173。>

如果手动使用 `prod` 模式，需先生成前端构建产物：

```bash
cd web
npm run build
cd ..
./scripts/start_server.sh prod --host 0.0.0.0 --port 8000
```

### Docker 部署

```bash
# 构建并启动
docker compose up -d

# 查看日志
docker compose logs -f
```

默认读取项目根目录的 `config.json` 作为运行配置，并把行情缓存 / SQLite 持久化到 `karkinos-data` 卷。`config.json` 不是行情、持仓或资产元数据存储；这些数据应写入本地 SQLite 表，例如 `latest_quotes`、`market_bars`、`ledger_entries` 和 `instrument_metadata`。

详见 [Docker 部署](#docker-部署) 章节。

## 配置

### config.json 字段说明

不要手工把 token 写进 `config.json`。推荐使用本地引导命令：

```bash
uv run python scripts/configure_data_source.py
```

该命令会引导你选择 `akshare` 或 `tushare`，仅在选择 TuShare 时隐藏输入 token，并自动写入已被 Git 忽略的本地 `config.json`。`config.example.json` 只作为高级运行字段参考。

#### 服务运行配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | string | `"127.0.0.1"` | 服务监听地址 |
| `port` | int | `8000` | 服务监听端口 |
| `live_auto_start` | bool | `true` | 是否自动启动 Web 内建实时监控 |
| `data_source` | string | `"akshare"` | 数据源（`akshare` / `tushare`） |
| `tushare_token` | string | `""` | 由配置引导脚本写入的本地 TuShare token；也可使用环境变量 `TUSHARE_TOKEN` |
| `notification` | object | `{"type":"console"}` | 通知配置 |
| `live_poll_interval` | int | `60` | 实时轮询间隔（秒） |
| `cors_allowed_origins` | array | 本地 Vite 地址 | 允许访问 API 的前端 origin |

资金、持仓、关注列表、资产名称、历史行情和当前行情不属于运行配置：资金和交易来自账本，用户关注资产来自 `watchlist_assets`，资产身份来自 `instrument_metadata`，当前行情来自 `latest_quotes`，历史行情来自 `market_bars` / 数据缓存。

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
| `KARKINOS_HOST` | 服务监听地址 | `ServerConfig.host` |
| `KARKINOS_PORT` | 服务监听端口 | `ServerConfig.port` |

### 优先级链

```
CLI 参数 > 环境变量 > config.json > 默认值
```

示例：`python -m server --port 9000` 优先于 `KARKINOS_PORT=8080`，优先于 `config.json` 中的 `"port": 8000`。

## CLI 参考

### python -m tools.run_backtest（本地回测工具）

```bash
uv run python -m tools.run_backtest
```

读取 `config.json`，运行回测并输出报告。使用 `DataManager` 缓存优先策略获取数据。
根目录 `main.py` 仅保留为兼容 wrapper，不是 Web 服务入口。

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

### python -m tools.live_monitor（独立监控工具）

```bash
uv run python -m tools.live_monitor
```

独立的兼容监控工具，不依赖 Web 服务。读取 `config.json`，轮询行情数据，运行策略并通过通知通道推送信号。专业 Web/Live 路径应使用 `python -m server` 或 `./scripts/start_server.sh`，由 `TradingScheduler`、`PreTradeRiskManager` 和 `ManualConfirmGateway` 负责。根目录 `live.py` 仅保留为兼容 wrapper。`Ctrl+C` 退出。

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
| GET | `/api/portfolio/cockpit` | 获取组合驾驶舱：目标权重、实际权重、漂移、action queue、风险提示 |
| GET | `/api/portfolio/state` | 获取账户总览、组合快照、风险摘要和下一步提示 |
| GET | `/api/portfolio/risk-summary` | 获取组合风险摘要 |
| GET | `/api/portfolio/live-holdings` | 获取按资产类别分组的实时持仓 |
| GET | `/api/portfolio/allocation` | 获取资产配置权重 |
| GET | `/api/portfolio/equity-curve` | 获取权益曲线 |

#### 信号 — /api/signals

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/signals?limit=&offset=` | 获取信号历史（分页） |
| GET | `/api/signals/latest?limit=` | 获取最新信号 |
| GET | `/api/signals/actions?limit=` | 获取待执行动作卡，并附带最近一次风控闸门摘要 |
| GET | `/api/signals/journal?limit=&offset=` | 获取 signal → action → risk audit chain |
| POST | `/api/signals/journal/{signal_id}/review` | 记录信号后续 outcome / review 复盘事件 |

Action card 的 `risk_gate_status` 显式区分 `not_checked`、`passed`、`blocked`，
用于避免把尚未风控的 actionable signal 误读为可执行。它还暴露人工确认就绪状态：
`awaiting_risk_gate`、`ready_for_manual_confirmation` 或
`blocked_by_risk_gate`。即使风控通过，也仍然要求人工确认后才能进入执行。

`POST /api/signals/journal/{signal_id}/review` 会把生成信号的后续 outcome 与
review notes 作为不可变审计事件写入 journal。它不会修改 action task，不会创建订单，
不会提交到券商，也不会记录成交。

#### 决策驾驶舱 — /api/decision

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/decision/today` | 获取今日只读决策摘要、候选动作、证据包和 no-action 原因 |
| GET | `/api/decision/intraday` | 获取股票 / 常见场内 ETF 的只读盘中候选动作视图 |

`GET /api/decision/today` 聚合已有 action task、风控闸门状态、signal journal
和最新 quote freshness，输出 `buy`、`sell`、`hold`、`rebalance`、`no_action`
或 `review_required`。候选动作会按 `strategy_id` 附上最新已保存回测的
after-cost / 样本外验证证据；如果没有匹配证据，会显式返回缺失原因。它只读现有事实，
不创建订单、不提交券商，也不改变人工确认默认值。

决策摘要的 `summary` 字段同时包含组合现金 / 持仓 / 权益概览、latest quote 缓存健康、
action task 状态计数，以及 signal / journal / risk-gate 审计计数，便于驾驶舱解释
“为什么行动或不行动”。

`GET /api/decision/intraday` 复用相同证据包，但只把股票和常见场内 ETF 代码纳入
盘中候选动作；场外基金 / 长期配置 action 会被排除并留给日级 lane。该接口用于
分钟级或轮询级驾驶舱展示，不是高频或毫秒级交易系统，也不会自动执行。

#### 交易控制 — /api/trading

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/trading/actions/{action_id}/manual-order` | 仅从风控通过的 action card 创建待人工确认订单 |
| POST | `/api/trading/shadow-runs/daily` | 从风控通过的 action card 记录每日 paper/shadow run |
| GET | `/api/trading/orders?status=` | 获取等待或已完成人工确认的订单 |
| POST | `/api/trading/orders/{order_id}/confirm` | 将人工订单标记为操作者确认 |
| POST | `/api/trading/orders/{order_id}/reject` | 将人工订单标记为操作者拒绝 |
| GET | `/api/trading/order-facts` | 获取 manual / paper / live-like 路径共用订单事实 |
| POST | `/api/trading/order-facts/{order_id}/shadow-divergence-review` | 记录 paper/shadow divergence review 证据 |
| GET | `/api/trading/fills` | 获取已持久化成交事实 |
| GET | `/api/trading/kill-switch` | 读取运行时 kill switch |
| PUT | `/api/trading/kill-switch` | 更新运行时 kill switch |

`POST /api/trading/actions/{action_id}/manual-order` 接收操作者输入的数量，
只会写入 `pending_confirm` 人工订单和共享订单事实。它会拒绝
`awaiting_risk_gate` 与 `blocked_by_risk_gate` action，不会提交到券商，
也不会把订单标记为已成交。确认或拒绝该人工订单会把来源 action card 的
决策状态更新为 `acted` 或 `ignored`，并在 signal journal 审计链中显示。

`POST /api/trading/shadow-runs/daily` 会为已经通过风控的 action card 记录
确定性的 `paper_shadow` 订单事实。它会跳过 blocked / not-yet-checked action，
不会创建人工订单，不会提交到券商，也不会记录成交。同一 `run_date` 和 action
重复运行时会复用已有订单事实；响应中的 `shadow_run_schema_version`、
`reused_count` 和 `reused_orders` 用于审计幂等重跑，而不是再次写入订单或事件。
每日 shadow run 还会在写入前检查 action 对应的 `latest_quotes`：缺失 quote、
非 `live` 状态或非正价格会被记入 `data_quality.issues`，并以
`data_quality:*` 原因跳过该 action，不生成 shadow order。

`POST /api/trading/order-facts/{order_id}/shadow-divergence-review` 会在已有
`paper_shadow` 订单事实上记录操作者 review，例如 `within_expectations`。
它不会改变订单状态，不会提交到券商，也不会创建成交。

#### 回测 — /api/backtest

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/backtest/strategies` | 获取可用策略、typed 参数 schema、资产范围、频率及 v0.2 基准角色 / OOS / after-cost 验证要求 |
| GET | `/api/backtest/strategy-validation` | 获取 v0.2 基准策略 after-cost / OOS 证据矩阵 |
| GET | `/api/backtest/strategy-promotion-readiness` | 获取基准策略晋级 readiness 闸门 |
| POST | `/api/backtest/run` | 运行回测（线程池执行），返回结果 |
| POST | `/api/backtest/sweep` | 对单个策略运行有界参数网格，保存每个配置并返回确定性排名与多重测试警告 |
| POST | `/api/backtest/compare` | 在同一冻结数据快照上比较多个策略或显式策略参数集 |
| GET | `/api/backtest/results` | 获取所有回测结果摘要 |
| GET | `/api/backtest/results/{result_id}` | 获取单个回测详情 + 权益曲线 |

`POST /api/backtest/run` 支持通用 `params` 字段，例如
`{"short_period": 5, "long_period": 20}`；系统会按策略参数 schema
做类型转换、范围校验、未知参数拦截和交叉字段校验。旧的
`short_period` / `long_period` 字段仍保持兼容，但新策略实验入口应优先使用
`params`。非法参数会返回 422，不会静默忽略或进入回测执行。

Web 回测实验室会读取 `/api/backtest/strategies` 的策略注册表，把 typed
参数 schema 渲染成表单控件，并支持从浏览器输入单个标的代码发起研究回测。
标的留空时沿用后端配置资产池；所有输出仍是研究证据，不会触发真实资金自动交易。

`POST /api/backtest/sweep` 接收 `param_grid`，例如
`{"short_period": [3, 5], "long_period": [9]}`。服务端会先检查组合数量不超过
`max_combinations`，再对每组参数复用策略 schema 校验并保存独立回测结果。返回排名
仅作为研究证据，并会附带多重测试 / 过拟合提示；不能绕过 OOS、after-cost、风控、
paper/shadow 或人工确认。Web 回测实验室也可以基于当前策略和可选单标的运行同一个
有界参数扫描，并展示已测试配置排名、保存的结果 id、分数、成本和多重测试警告，便于在
晋级或 paper/shadow 前复核参数扰动证据。

`POST /api/backtest/compare` 可以接收 `strategies`，也可以接收显式 `runs`
（每项包含 `strategy` 与 `params`），用于比较多个策略或同一策略的不同参数集。
端点会先确认每个结果都使用同一个 `metrics_json.dataset_snapshot.snapshot_id`，
只有快照一致才保存结果并返回排名材料；如果快照缺失或不一致，会返回 409，避免把
不同数据输入悄悄放在一起比较。返回项包含保存后的结果 id、归一化参数、指标、
权益曲线和共享数据快照 id，供审计复核使用。

`POST /api/backtest/run` 也可选传入 `oos_split_date`（YYYY-MM-DD）和
`benchmark_return`，用于在回测结果的 `metrics_json.oos_validation` 中附带
样本外 after-cost 验证证据；该证据用于审计与策略晋级，不构成投资建议或收益承诺。
每次回测还会在 `metrics_json.dataset_snapshot` 中记录本次交给引擎的数据快照：
配置的数据源、可用 source、缓存/元数据状态、请求日期范围、标的 universe、每个标的
的行数与首尾时间、可用的复权模式、缓存 dataset id 以及数据质量诊断。该快照用于复现
和比较研究结果，不代表行情数据完整性保证。Web 回测报告会把该快照展示为数据审计
面板，覆盖当前运行结果和已保存历史报告。
同一报告也会展示 after-cost 证据包与样本外验证 payload：净/毛收益、成本拖累、
成交额、基准角色与状态、切分点、假设和限制。这些面板只作为研究证据，不代表执行审批。
`GET /api/backtest/strategy-validation` 读取已保存回测结果，报告三条 v0.2
基准策略是否具备 after-cost 与样本外验证证据；该矩阵只用于审计与晋级检查。
`GET /api/backtest/strategy-promotion-readiness` 会组合 after-cost/OOS 证据、
被风控阻断的证据、paper/shadow 订单事实以及明确的 paper/shadow divergence
review 证据。它不会自动晋级策略，也不会改变执行默认值。

#### 设置 — /api/settings

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 读取当前配置 |
| PUT | `/api/settings` | 更新内存运行设置；业务状态继续保存在 SQLite |
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

- **Stage 1**（`node:20-alpine`）：构建 React 前端，`npm ci && npm run build`，输出到 `web/dist/`
- **Stage 2**（`python:3.12-slim`）：复制源码与前端产物，安装服务端依赖，设置 `KARKINOS_CONFIG_PATH=/app/config.json` 和 `KARKINOS_DATA_DIR=/app/data/store`，并以 `python -m server` 启动

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
KARKINOS_PORT=9000 docker compose up -d
# 或修改 docker-compose.yml 中 ports 为 "9000:9000"
```

### 数据卷

- `karkinos-data`：挂载到 `/app/data/store`，存储 Parquet 文件和 SQLite 数据库，容器重建后数据不丢失

## Web 前端

### 技术栈

React + TypeScript + TanStack Router + TanStack Query + ECharts/Recharts + Vite

### 视图说明

| 视图 | 路径 | 说明 |
|------|------|------|
| Overview | `/` | 账户概览、实时持仓摘要、权益曲线 |
| Portfolio | `/portfolio` | 持仓明细、资产筛选、配置分组 |
| Activity | `/activity` | 交易、分红、现金流、手工调整流水 |
| Risk | `/risk` | 风险指标、回撤、集中度、权益解释 |
| Decision | `/decision` | 日级 / 盘中候选动作、风控、证据和人工确认入口 |
| Market | `/market` | 研究看板、关注列表、K 线与研究笔记 |
| Settings | `/settings` | 设置入口 |

初始界面不会内置任何看起来像用户资产、交易或基金名称的有效数据。
资产、持仓和流水来自本地数据库或显式私有运行配置；例如 Activity 的批量基金加仓候选
来自已持有基金仓位，而不是前端硬编码默认基金。

Web cockpit 会按当前界面语言展示资产类别，例如中文界面显示“现金 / 股票 / 基金”，英文界面显示
“Cash / Stock / Fund”。流水行会优先展示可解析的标的名称和代码，并列出金额、份额/数量、价格、
手续费，同时隐藏自动确认等技术元数据。收益日历只把估值日期明确属于当日的报价纳入当日
收益；陈旧或盘中的终端 quote 不会被挂到当前日期制造收益。

### 开发

```bash
cd web
npm install
npm run dev       # 热更新开发入口：http://localhost:5173，代理 /api → localhost:8000
npm run build     # 构建产品入口需要的 web/dist
```

客户入口仍然是后端托管的 <http://localhost:8000；`5173`> 只用于前端热更新开发。

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

### 本地扩展策略

私有研究策略放在 `strategy/extensions/`，或通过
`KARKINOS_STRATEGY_EXTENSION_DIR` 指向另一个本地目录。Karkinos 只自动发现
`*.strategy.json` manifest；仓库里的 `.example` 文件只是模板，不会被加载。

```bash
cp strategy/extensions/examples/local_momentum.py.example \
  strategy/extensions/local_momentum.py
cp strategy/extensions/examples/local_momentum.strategy.json.example \
  strategy/extensions/local_momentum.strategy.json
```

manifest 使用 `schema_version: "karkinos.strategy.v1"`，声明稳定
`strategy_id`、显示名称、`module:ClassName` 格式的 `class_path`、资产范围、频率
和 typed 参数 schema。扩展 manifest 不能声明 live trading、broker submission、
auto-trading 或真实资金执行能力；回测输出只作为研究证据，不能绕过风控、
paper/shadow 复核、信号日志或人工确认。

如果私有策略脚本直接放在扩展目录中，`class_path` 可以写成同目录模块形式，
例如 `local_momentum:LocalMomentumStrategy`。Karkinos 只会在研究回测实例化该
已注册扩展策略时加载对应类，并先按 manifest 中的 typed 参数 schema 完成参数校验。

## 通知系统

三种通知通道：

| 通道 | type 值 | 说明 |
|------|---------|------|
| Console | `console` | 终端输出（默认） |
| Telegram | `telegram` | 通过 Bot API 推送 |
| 微信 Server酱 | `wechat` | 通过 Server酱 推送 |

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

旧 `RiskManager` 以 `priority=-10` 订阅 `OrderEvent`，可在 Execution（priority=0）之前审计并发布风险告警；但同步 EventBus 不支持 handler 消费事件，因此它本身不能阻止后续 handler 继续执行。

当前 Live 安全链路是 `OrderIntentEvent` → `PreTradeRiskManager` → `RiskDecisionEvent`/`OrderEvent` → `ManualConfirmGateway`。回测路径使用 `BacktestEngine` 内的确定性兼容胶水审批 `OrderIntentEvent`，不依赖 Live 状态。

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

在 `PreTradeRiskManager` 路径中，订单被拒绝时会发布 `RiskDecisionEvent` / `RiskAlertEvent`，且不会生成 `OrderEvent`。旧 `RiskManager` 需要执行层配合才可阻断订单。

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
