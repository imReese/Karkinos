# Karkinos — 面向中国市场的个人量化投研与交易平台

[English](README.en.md) | [返回摘要](../README.md) | [战略与路线图](KARKINOS_GOAL.md)

---

## 概述

Karkinos 是一个面向中国市场的个人量化投研与交易平台。

它是一个集回测、策略实验、账户事实、风控、信号、对账与复盘于一体的个人金融应用，采用事件驱动架构，以回测优先、日线为主的设计理念，支持 A 股、ETF、黄金现货、交易所债券等资产类型。

核心特性：

- **事件驱动架构** — 所有组件通过 EventBus 解耦通信，保证回测确定性
- **多资产支持** — A 股、ETF、黄金现货、交易所债券，Instrument 字段值承载差异
- **目标权重信号** — 策略输出目标权重（0~1），Portfolio 自动转换为具体股数
- **T+1 支持** — Position 内置冻结/解冻机制，每日结算自动推进
- **参数稳健性证据** — Strategy Lab 参数 sweep 会返回版本化 robustness artifact，记录最佳参数、邻域稳定性、参数敏感度和基于网格的过拟合警告；该证据仍需配合 after-cost、OOS、风险和数据质量 gate 审核
- **实时监控** — 独立 Live 模式 + Web 服务内建 Scheduler，支持策略信号推送
- **通知推送** — Console / Telegram / 微信 三通道
- **Web UI** — React + TypeScript + TanStack Router + TanStack Query + ECharts 个人金融应用界面
- **响应式平台布局** — 主要页面按桌面/窄屏宽度重排，宽表格只在各自面板内横向滚动
- **持仓与行情详情** — Portfolio 持仓行情看板只做资产类别汇总，单只标的的行情、成本和 OHLC/K 线在持仓详情页与 Market 研究页面中查看
- **单只标的收益追踪** — Portfolio 持仓列表和持仓详情页展示每只股票/基金的今日收益、今日涨跌幅、行情价、成本与日内基准来源，方便把组合级变化追溯到具体标的
- **收盘后估值刷新** — Web 服务内建 Scheduler 在交易日 16:00 刷新收盘行情与日线缓存，用于今日盈亏复核；21:30 再刷新基金净值确认数据。若数据源尚未发布确认值，页面会继续保留待确认或缓存状态。
- **Account Truth 导入预览与暂存证据** — 提供 canonical broker statement CSV 规范和只读解析入口，能校验、标准化、指纹化本地券商 CSV 行并报告重复行；合法预览可暂存为 broker evidence，不写入生产账本
- **Account Truth 复核 API** — 只读列出 staged import runs 与 computed
  reconciliation reports，展示行数、校验状态、重复计数、来源、报告状态、未解决差异、
  建议复核动作和 broker evidence 引用，不自动修改生产账本
- **Account Truth 复核中心** — Web `/account-truth` 页面展示 Account Truth
  Score、导入批次、按状态筛选的对账报告、差异项中的券商值/Karkinos 值/差额、证据引用和
  人工复核动作；这些动作只记录审计状态，不会写入生产账本
- **账户事实闸门联动** — Decision 与 Strategy Lab 晋级复核界面展示 Account
  Truth gate 状态、分数、未解决差异和证据可用性，帮助在人工复核或研究晋级前看清账户事实边界
- **收益日历** — 基于审计归因数据按日、周、月、年查看收益分布，支持日历/曲线/表格视图和金额/收益率切换；周日作为每周第一列，日历主口径使用市场盈亏，历史日收盘优先读取本地 `market_bars` OHLC 缓存再回退到 daily-close 快照，当日市场变动会拆成股票/基金/其他资产，入金、出金、分红和手工调整作为外部资金事件展示，非交易日不生成日历收益，估算、缓存、陈旧或确认净值缺失的周期仍展示收益但标记为待复核/未确认，只有缺失或不可用价格才显示为缺价，曲线视图保留横纵坐标
- **收益与成本口径** — 今日盈亏、买入以来收益、已实现收益、现金事件和基准价优先级记录在 [收益与成本口径](return-accounting.zh.md)，避免页面和后端对同一数字使用不同解释
- **研究证据包** — Strategy Lab 回测会生成版本化 `research_evidence_bundle`，记录 analyzer 输出、数据质量 gate、after-cost 证据引用、single split 或 rolling OOS 证据、中国市场假设缺口和人工复核晋级状态；该证据包不启用自动交易
- **Docker 一键部署** — 多阶段构建，前后端一体镜像

## 如何解读研究证据包

每次 Strategy Lab 实验都应优先查看 `research_evidence_bundle`。其中
`gate_status` 是研究复核状态：`pass` 表示证据在当前口径下足够进入人工
复核，`degraded` 表示数据、OOS、成本或 analyzer 存在需要复盘的警告，
`blocked` 表示存在阻断性证据缺口，不能进入晋级复核。证据包会记录
dataset snapshot id、策略元数据、analyzer 输出、after-cost 和 OOS 证据可用性、
成交/费用统计、中国市场假设、已知限制，以及
`promotion_gate.does_not_enable_execution=true`。它只是研究证据，不是投资建议、
收益承诺，也不是券商下单授权。

内置策略的人话版说明见
[策略入门说明](strategy/README.zh.md)，其中解释了双均线策略、月度再平衡、
布林带均值回归和 RSI 动量/反转的核心假设、当前信号规则、参数、失效场景和
Karkinos 审计重点。该文档只用于理解研究策略，不构成投资建议或收益承诺。

## 市场数据可靠性工作流

Karkinos 使用统一的数据状态词汇标记行情、基金净值、历史 K 线、盘中快照和
replay 数据集：`confirmed`、`live`、`cache`、`estimated`、`missing`、
`stale` 和 `confirmed_nav_missing`。Overview、收益日历、Backtest 数据审计面板
和策略 replay 证据会用这些状态区分确认值、实时值、本地缓存、估算值、缺失报价、
陈旧报价和基金确认净值缺失。

手动刷新和调度器刷新可以更新盘中行情、收盘价 K 线和基金确认净值；这些刷新只改变
本地行情证据，不会改变交易行为、不会提交券商订单，也不会绕过人工确认。冻结的
market-data dataset 可以用于回测、策略 runtime dry-run、paper/shadow 复核和审计
回放，确保同一份输入可以重复验证。

估算、缓存、陈旧、缺失或确认净值缺失的数据只代表数据质量状态。它们不能被展示成
已确认收益，也不构成投资建议、收益承诺或执行授权。行情、历史 K 线和本地缓存属于
SQLite / 数据缓存中的运行时金融事实；`config.json` 只保存本机运行偏好和数据源配置，
不保存券商密码、私有交割单或公开仓位样例。

## Account Truth 导入预览

Account Truth 当前支持 canonical broker statement CSV 的只读预览解析和 staged
broker evidence 持久化，并提供 reconciliation report 核心比较：
`parse_broker_statement_csv()` 会标准化本地 CSV 行、校验必填列和事件类型、
生成文件级与行级 SHA-256 指纹、标记重复行，并返回 broker evidence events。
`BrokerEvidenceRepository.save_preview()` 会记录 import run 元数据和合法 broker
evidence events；重复文件只记录重复 import run，不会重复写入 evidence。它不会写入
生产 `ledger_entries`，不会修改现金或持仓，也不会提交券商订单。
`build_reconciliation_report()` 会比较 broker evidence 与 Karkinos 现金、持仓、
ledger 费用、税费和成本基础，输出 `pass` / `warning` / `mismatch` / `blocked`
状态、差异明细和建议复核动作。
`ManualReviewRepository.record_decision()` 可把 reconciliation item 标记为
`accepted`、`ignored`、`known_difference`、`ledger_candidate` 或
`needs_investigation`；这些标记只记录人工审计状态，不会自动改生产账本。
`build_account_truth_score()` 会把 reconciliation 状态、人工复核状态、数据新鲜度
和未解决差异汇总为 0-100 分与 `pass` / `degraded` / `blocked` gate 状态，供后续
平台决策视图和策略晋级 gate 消费。
Decision Cockpit 和策略晋级 readiness 会把该分数作为 gate 证据；Account Truth
证据为 `degraded`、`blocked` 或缺失时，会阻止 live-like 人工确认 ready 状态或策略
晋级 readiness，但不会授权执行或下单。

v0.7 的第一组只读复核接口已经可用于 Web 或本地工具：

- `GET /api/account-truth/import-runs`
- `GET /api/account-truth/reconciliation-reports`
- `GET /api/account-truth/reconciliation-reports/{import_run_id}`
- `GET /api/account-truth/score`
- `POST /api/account-truth/reconciliation-reports/{import_run_id}/items/{item_key}/review`

列表和报告接口会列出 staged broker import 元数据，并基于当前 Karkinos ledger、
现金、持仓、费用、税费和成本基础计算 reconciliation report。review 接口只记录
`accepted`、`ignored`、`known_difference`、`ledger_candidate` 或
`needs_investigation` 等人工复核状态。`ledger_candidate` 只是审计标签，不会写入
production ledger，不会修改持仓，不保存券商凭证，也不会提交券商订单。
Web 复核中心消费同一组接口，用于人工审计和复盘，不是投资建议，也不是执行授权。

CSV 格式、安全合成样例和隐私边界见
[Account Truth 导入预览](account-truth-import.zh.md)。

后端测试按 pytest marker 分层，便于本地聚焦验证：

```bash
uv run python -m pytest -m unit
uv run python -m pytest -m api_contract
uv run python -m pytest -m acceptance
uv run python -m pytest -m "not slow"
```

完整验证仍使用 `uv run python -m pytest`。

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
│   └── result.py           # BacktestResult（结果容器）
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
│   ├── config.py           # 类型化配置加载（BacktestConfig + ServerConfig）
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
  SYNTH001: 数量=500, 均价=17.4904, 盈亏=-1543.03
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
| `account_commission_rate` | number | `0.0001` | 当前账户股票 / ETF 佣金率规则，例如万1.5写作 `0.00015` |
| `account_min_commission` | number | `5.0` | 当前账户单笔最低佣金规则 |
| `broker_fee_schedule` | object | local defaults | 本地券商费用规则参数，包括股票/ETF 佣金率、最低佣金、印花税、过户费、其他费用率、规则 id 和已知限制；不得保存账户号、截图、交割单、券商密码、token、secret 或 credential |
| `broker_connectors` | array | `[]` | 只读券商事实 connector 的本地配置，只允许 `connector_id`、`connector_type`、`enabled`、`client_path`、`account_alias`；不得保存券商密码、token、secret 或 credential |
| `cors_allowed_origins` | array | 本地 Vite 地址 | 允许访问 API 的前端 origin |

资金、持仓、关注列表、资产名称、历史行情和当前行情不属于运行配置：资金和交易来自账本，用户关注资产来自 `watchlist_assets`，资产身份来自 `instrument_metadata`，当前行情来自 `latest_quotes`，历史行情来自 `market_bars` / 数据缓存。

#### 本地存储边界

- `config.json`：本机运行偏好和环境相关开关，包括数据源、TuShare token、轮询间隔、通知、CORS origin、当前账户佣金率与最低佣金规则、结构化券商费用规则，以及只读券商 connector 的客户端路径和账户别名；券商密码、token、secret、credential、账户号、截图和私有导出不得写入 connector 或费用规则配置。
- SQLite（`data/store/`）：会变化的金融事实和缓存，包括关注列表、资产元数据、交易流水、行情快照、历史 K 线、组合快照、交易控制状态和已保存回测索引。
- `reports/`：一次研究或校验运行生成的人类可读证据，例如回测 JSON 报告、行情对账报告。报告属于运行时产物，不应提交到仓库。

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
| GET | `/api/portfolio/cockpit` | 获取组合平台视图：目标权重、实际权重、漂移、action queue、风险提示 |
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

#### 决策平台 — /api/decision

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
action task 状态计数，以及 signal / journal / risk-gate 审计计数，便于决策视图解释
“为什么行动或不行动”。

`GET /api/decision/intraday` 复用相同证据包，但只把股票和常见场内 ETF 代码纳入
盘中候选动作；场外基金 / 长期配置 action 会被排除并留给日级 lane。该接口用于
分钟级或轮询级决策展示，不是高频或毫秒级交易系统，也不会自动执行。

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
| GET | `/api/backtest/strategies` | 获取可用策略、typed 参数 schema、资产范围、频率及基准角色 / OOS / after-cost 验证要求 |
| GET | `/api/backtest/strategy-validation` | 获取基准策略 after-cost / OOS 证据矩阵 |
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
页面会把策略元数据、适用资产、支持频率、基准角色和验证要求展示在策略选择旁，
并把 `short_period` 等内部参数键渲染成中文业务标签；内部键名仍用于 API contract
和参数集审计。
同数据快照参数对比入口也支持直接输入中文参数名，例如
`短期均线周期=3, 长期均线周期=9`，提交给后端时仍会转换为稳定的
`short_period` / `long_period` API 字段。
标的留空时沿用后端配置资产池；所有输出仍是研究证据，不会触发真实资金自动交易。

已保存回测会写入本地 SQLite 数据库 `data/store/app.db` 的 `backtest_results`
表，供 Web 历史列表、风险页、决策证据和策略晋级流程查询。为了方便人工查看，每条
保存的回测也会默认生成一份 JSON 文件：
`reports/backtest/backtest-result-<id>.json`。可通过
`KARKINOS_BACKTEST_REPORT_DIR` 改变报告输出目录；`reports/` 属于本地运行时数据，
不应提交到 git。

历史 OHLCV 行情保存在本地 SQLite 表 `data/store/meta.db.market_bars`；
`data/store/bars/` 下的 Parquet 文件只是兼容与人工检查用的本地镜像。若已有
Parquet 历史行情，需要在不联网、不重新抓取的情况下灌入 SQLite，可运行
`uv run python scripts/sync_market_bars_to_db.py`。缓存数据会记录 provider、抓取时间、
日期范围、行数和质量诊断，但这不代表它能保证与所有公开网页或供应商永远完全一致；
复权口径、基金净值延迟、停牌/非交易日、源站陈旧数据或供应商后续修正都可能造成差异。
如果需要对某个标的和日期范围做显式校验，可运行例如
`uv run python scripts/verify_market_bars.py --symbol <symbol> --start 2026-06-12 --end 2026-06-15`。
该命令会抓取 provider 数据并输出 JSON 差异报告，但不会自动覆盖本地缓存。

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
Web 回测实验室也可以把当前策略的显式参数集提交到该端点，并展示保存后的结果 id、
归一化参数、收益、回撤、成本、警告和共享快照 id；这些仍是研究证据，不代表执行审批。

`POST /api/backtest/run` 也可选传入 `oos_split_date`（YYYY-MM-DD）和
`benchmark_return`，用于在回测结果的 `metrics_json.oos_validation` 中附带
样本外 after-cost 验证证据；该证据用于审计与策略晋级，不构成投资建议或收益承诺。
每次回测还会在 `metrics_json.dataset_snapshot` 中记录本次交给引擎的数据快照：
配置的数据源、可用 source、缓存/元数据状态、请求日期范围、标的 universe、每个标的
的行数与首尾时间、可用的复权模式、缓存 dataset id 以及数据质量诊断。该快照用于复现
和比较研究结果，不代表行情数据完整性保证。Web 回测报告会把该快照展示为数据审计
面板，覆盖当前运行结果和已保存历史报告。
同时，保存的 `metrics_json.strategy_metadata` 会固定本次运行使用的策略身份、显示名、
描述、资产范围、支持频率、参数 schema、归一化参数、基准角色和验证要求；即使之后
策略注册表或扩展 manifest 调整，旧报告仍能解释当时测试的配置。Web 报告会把它展示为
策略审计快照，用中文策略名、参数名和参数说明作为主文案，`short_period` 等内部键名只
作为 API / 审计字段辅助展示。
同一报告也会展示 after-cost 证据包与样本外验证 payload：净/毛收益、成本拖累、
成交额、基准角色与状态、切分点、结构化成本假设、滑点假设、通用假设和限制。
这些面板只作为研究证据，不代表执行审批。
`GET /api/backtest/strategy-validation` 读取已保存回测结果，报告已注册基准策略是否
具备 after-cost 与样本外验证证据；该矩阵只用于审计与晋级检查。
`GET /api/backtest/strategy-promotion-readiness` 会组合 after-cost/OOS 证据、
被风控阻断的证据、paper/shadow 订单事实以及明确的 paper/shadow divergence
review 证据。它不会自动晋级策略，也不会改变执行默认值。

#### 账户策略 — /api/account-strategy

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/account-strategy` | 读取当前账户研究策略绑定；不会启用自动交易 |
| PUT | `/api/account-strategy` | 保存研究上下文中的策略绑定；服务端强制 `auto_trade_enabled=false` |
| GET | `/api/account-strategy/attribution` | 汇总当前策略可串联到的信号、动作、风控、订单与成交证据 |
| GET | `/api/account-strategy/contribution` | 基于已归属成交和本地最新估值估算策略贡献 |

账户策略绑定只用于研究、复核和审计上下文，不会修改订单、成交、持仓或账本。
贡献报告只从可确定归属到当前策略的成交估算已实现 / 未实现收益、佣金、滑点和净贡献；
手工交易、现金流和缺少证据的市场变动不会默认归到策略收益里。

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

Web 应用会按当前界面语言展示资产类别，例如中文界面显示“现金 / 股票 / 基金”，英文界面显示
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
cp strategy/extensions/template.py.example strategy/extensions/my_strategy.py
cp strategy/extensions/template.strategy.json.example \
  strategy/extensions/my_strategy.strategy.json
```

manifest 使用 `schema_version: "karkinos.strategy.v1"`，声明稳定
`strategy_id`、显示名称、`module:ClassName` 格式的 `class_path`、资产范围、频率
和 typed 参数 schema。扩展 manifest 不能声明 live trading、broker submission、
auto-trading 或真实资金执行能力；回测输出只作为研究证据，不能绕过风控、
paper/shadow 复核、信号日志或人工确认。

如果私有策略脚本直接放在扩展目录中，`class_path` 可以写成同目录模块形式，
例如 `my_strategy:MyStrategy`。Karkinos 只会在研究回测实例化该
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
        "telegram_bot_token": "<telegram-bot-token>",
        "telegram_chat_id": "<telegram-chat-id>"
    }
}
```

```json
{
    "notification": {
        "type": "wechat",
        "wechat_sendkey": "<serverchan-sendkey>"
    }
}
```

信号推送消息格式：

```
📈 交易信号
标的: SYNTH001
方向: LONG
目标权重: 100.0%
价格: 18.5050
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
