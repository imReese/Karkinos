# Karkinos Product Design

## 1. Product model

Karkinos 围绕量化研究、组合管理、风险控制和评估闭环组织。

核心界面必须回答：

1. 当前组合状态和表现是什么？
2. 数据截至什么时间，当前估值是否可用？
3. 最近有哪些研究结果和 Published Forecast？
4. Portfolio Target 与 Current Financial Book 有什么差异？
5. Risk 是否允许当前计划继续？
6. Backtest / Paper / Shadow 的结果与研究预期为什么不同？
7. 当前是否存在需要用户处理的事项？

## 2. Information architecture

```text
Overview

Data
  Health
  Datasets

Research
  Experiments
  Forecasts
  Backtests

Portfolio
  Current Book
  Targets
  Rebalance
  Risk

Evaluate
  Paper / Shadow
  Attribution
  Alpha Health

System
  Operations
  Settings
```

真实交易能力必须接入 Portfolio、Risk、Execution 和 Accounting 边界，不作为产品导航中心。

## 3. Overview

Overview 是投资状态摘要，不是系统监控页。

一级信息：

```text
Portfolio value
Cumulative P&L
Latest trading-session P&L
Available cash
Portfolio performance
Current holdings
User attention
Valuation usability
```

二级信息：

```text
Realized / unrealized P&L
Strategy status
Risk summary
Recent activity
Data details
```

默认首屏顺序：

```text
Portfolio summary
Performance
Holdings
Attention / data status
```

约束：

- 总资产是首屏第一视觉层级；
- Performance 是首页主图；
- Holdings 是首页第二核心区域；
- 正常数据状态使用单行摘要；
- 只有影响估值或用户动作的异常进入一级警告；
- 系统健康、refresh attempt、fingerprint、内部状态机字段进入 Data Details 或 Operations；
- 无用户动作时显示明确空状态，不使用系统信息填充 Today Queue；
- Overview 不重复 Portfolio、Risk、Operations 的完整工作区。

## 4. Data

Data 展示数据是否适合估值、研究和决策。

核心字段：

```text
as_of
source / identity
coverage
freshness
quality
revision
point-in-time availability
blocker
safe next action
```

Provider 调用细节、内部重试和运行日志默认进入详细视图。

## 5. Research

Research 以 Experiment 和 evidence 为核心。

```text
Dataset
Feature / Alpha / Model identity
Parameters
Evaluation
Research Evidence
Published Forecast
```

约束：

- Candidate Experiment 与 Published Forecast 必须明确区分；
- AI 仅作为研究入口，不获得额外金融 authority；
- 研究结果必须可追溯至 Dataset、参数和 Evaluation；
- chart 消费平台计算结果，不在浏览器重新计算 canonical metrics。

## 6. Portfolio

Portfolio 必须明确区分：

```text
Published Forecast
Current Financial Book
Portfolio Target
Risk Decision
Rebalance Plan
```

约束：

- Target 必须可追溯到 Forecast、Portfolio Policy、风险暴露和成本假设；
- Risk block 不得被隐藏或改写为来源不明的 Target；
- 当前持仓优先使用可比较的 table；
- 市值、仓位、P&L、收益率和定价状态使用一致语义。

## 7. Evaluate

```text
Backtest      Historical simulation
Paper         Forward-time simulated execution
Shadow        Observation of target / plan outcomes
Attribution   Outcome decomposition
Alpha Health  Evidence decay / persistence
```

Outcome 必须可追溯至 Dataset、Experiment、Forecast 和 Portfolio Target。

## 8. Financial state

现金、持仓、费用、PnL 和估值必须来自明确的 Financial Book。

约束：

- Backtest、Paper、Shadow 和实际账户状态不得混为同一账户；
- 比较不同环境时必须显示 book / environment identity；
- canonical financial metrics 不在前端重复定义；
- 财务指标缺少可靠口径时显示 unavailable，不推导近似值。

## 9. Market, pricing and status semantics

以下概念必须独立表达：

```text
market_session
pricing_kind
pricing_as_of
pricing_authority
valuation_usability
refresh_health
decision_readiness
user_attention
```

状态约束：

- Market session 使用交易日历，不使用 wall-clock age 代替交易日语义；
- market closed + latest completed session data 可作为正常估值状态；
- cache 表示存储来源，不表示 freshness；
- refresh failure 不自动否定仍然有效的 published valuation；
- valuation usability 与 decision readiness 分离；
- system-only 状态不自动进入 user attention；
- 缺失、冲突或不具 authority 的数据保持 fail-closed。

定价展示：

```text
Stock          Realtime quote / session close
ETF            Exchange quote / session close
Open-end fund  Published NAV / estimated NAV
Manual mark    Explicit manual valuation
```

开放式基金不得使用“实时行情”描述 Published NAV。

## 10. Status and evidence

摘要状态优先表达：

```text
what
as_of
usable or blocked
safe next action
```

Evidence detail 可包含：

```text
snapshot identity
ledger cutoff
source identity
fingerprint
refresh history
blocker detail
```

约束：

- 同一概念只保留一个用户可见主状态；
- 正常状态不使用大面积 success banner；
- warning / danger 必须对应实际影响；
- 状态不能只依赖颜色表达；
- 技术证据默认通过 disclosure、drawer 或详细页访问。

## 11. User attention

只有用户现在能够或应该处理的事项进入 Attention Queue。

允许：

```text
Manual confirmation
Risk review
Actionable data repair
Ledger reconciliation
Strategy / forecast review
```

排除：

```text
Healthy subsystem status
Zero counters
Broker disabled
Paper / Shadow inactive
Internal audit guarantees
Non-actionable refresh failures
Expected external publication wait
```

同一根因产生的多个下游 blocker 必须合并为一个用户事项。

## 12. Interaction hierarchy

```text
read / query
refresh / ingestion
research mutation
portfolio proposal
financial mutation
authority mutation
```

更高 authority 的操作必须具有更明确的确认、风险和审计边界。

## 13. Visual system

继续使用 Catppuccin Latte / Mocha，并采用克制、原生、专业金融界面的视觉方向。

布局：

- 使用连续内容画布，不使用等权重 card wall；
- Desktop 以主内容区 + 窄辅助栏为主；
- 主内容区优先承载 Portfolio summary、Performance 和 Holdings；
- 辅助栏仅承载紧凑的 Attention、Data Status 或必要摘要；
- 模块主要通过 spacing、alignment 和 divider 分层；
- 避免 card-in-card 和多层容器。

Typography：

- 总资产和核心财务指标使用最高数字层级；
- 财务数字使用 tabular numerals；
- 标题层级稳定，不使用营销式大标题；
- 时间、代码、identity 使用适合扫描的紧凑样式。

Color：

- Catppuccin surface 作为主要背景层级；
- Mauve 仅用于 primary accent、selection 和主图；
- P&L 颜色遵循统一正负语义；
- warning / danger 只用于实际异常；
- 禁止装饰性 glow、大面积渐变和高饱和背景。

Components：

- table：可比较记录和持仓；
- chart：时间、收益或分布关系；
- timeline：事件序列；
- card：独立对象、独立动作或需要清晰边界的辅助模块；
- badge：短状态，不承载长说明；
- disclosure / drawer：技术证据和详细状态。

禁止为填充页面添加：

```text
Decorative sparkline
Decorative donut chart
Marketing quote
Motivational slogan
Redundant KPI cards
System-health filler
```

## 14. Responsive behavior

Desktop 保留文字导航和可比较 table。

移动端：

- 按任务优先级重排，不机械堆叠桌面布局；
- 首屏优先 Portfolio summary、Performance 和 Attention；
- Holdings 使用可扫描列表或横向精简表；
- 技术 evidence 默认折叠；
- 保持核心 financial semantics 与 Desktop 一致。

## 15. Performance and consistency

- 页面优先消费持久化的 canonical / derived state；
- 普通查询不隐式触发 provider 或 AI；
- 同一金融或研究概念在不同页面使用一致 identity、format 和 status semantics；
- 单个 widget 失败不得吞掉其他可用页面状态；
- 大数据表使用分页、虚拟化或服务端查询；
- Overview 不在 React 中重新定义领域状态机；
- 展示层不得降低 trading / risk path 的 fail-closed 要求。
