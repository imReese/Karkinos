# Karkinos Profit Engine 实施计划

## 1. 目标

Karkinos 的长期目标不是成为一个功能堆叠的看盘或策略展示应用，而是成为一个个人可运营、可审计、可持续迭代的中国市场量化研究与投资系统。

North Star：

> Karkinos 能否持续把原始市场数据变成可复现、样本外有效、扣除真实成本后仍具有正期望的投资组合，并在优势消失时及时识别并停止继续依赖它？

这里的“Profit Engine”不承诺盈利。它定义的是一条可以被工程化验证的盈利研究链路：

```text
market data
-> point-in-time datasets
-> alpha discovery
-> alpha validation
-> alpha combination
-> portfolio construction
-> realistic execution simulation
-> paper/shadow observation
-> live attribution
-> alpha degradation / retirement
```

现有 evidence、valuation、risk、Decision、audit、paper/shadow 和 controlled-execution 基础设施继续保留，但它们从“产品中心”调整为贯穿 Profit Engine 的安全与可复现基础设施。

---

## 2. 总体原则

### 2.1 先稳定，再扩功能

在任何新的 Alpha、AI、分钟策略或交易能力之前，必须先完成 Reliability Gate。单个 provider、market refresh、scheduler、research worker 或 publication attempt 的失败，不得把已经验证成功且仍与当前 committed facts 一致的 Portfolio/Overview 变成无解释的全局 503。

同时，任何需要“最新证据”的 Decision、Risk、Order 或 Execution 行为必须继续 fail closed。

### 2.2 市场数据与金融事实分离

```text
Market Data Plane
    raw observations / bars / fundamentals / universe
    -> large immutable datasets
    -> research inputs

Financial Fact Plane
    validated market evidence
    -> canonical quote / close
    -> valuation / ledger / risk / authority
```

市场历史数据不是 execution authority。金融事实也不应承担大规模量化数据湖的职责。

### 2.3 研究输出优先是 Alpha，而不是 BUY/SELL

Alpha 的基础输出是某个时点对一个横截面 universe 的预测 score：

```text
symbol       alpha_score
000001       +0.81
002594       +1.34
600066       -0.42
...
```

BUY/SELL 是 Portfolio Construction、cost、risk、lot、liquidity 等约束之后的下游结果。

### 2.4 所有研究必须 point-in-time

任何可用于 Alpha 或回测的数据都必须回答：

- 这条数据在当时是否真实可见？
- 对应哪个 market session？
- 是否存在 future leak？
- universe 是否含 survivorship bias？
- 财务数据使用的是报告期还是真实公开日？
- 复权因子是否只使用当时已知信息？
- 数据 revision 是否可重放？

### 2.5 Backtest、Shadow、Live 尽量共享语义

数据输入可以不同，但以下语义不得各写一套：

- signal timing；
- order timing；
- T+1；
- 100 股 lot；
- 涨跌停；
- 停牌；
- fee / tax；
- slippage；
- turnover；
- position limits；
- risk gates。

---

# Phase A — Reliability Gate

Profit Engine 的所有后续阶段都依赖 Phase A。Phase A 未完成时，不扩展真钱能力，也不继续扩大 AI 自动化范围。

## A1. Last-good publication 与 latest attempt 分离

目标状态：

```text
valuation_snapshot_publication
    = 当前最后一次成功、可读取的 canonical publication

valuation_snapshot_publication_attempt
    = 最近一次 publication attempt 的结果
```

行为：

```text
candidate publish success
-> 原子更新 current publication
-> latest attempt = success

candidate publish failure
-> latest attempt = failed
-> 已有 current publication 不变
```

只有当 committed financial facts 已经发生变化、导致 last-good snapshot 不再匹配当前事实时，read gate 才可以拒绝读取。

### A1 验收

- 成功 publication 后 current 和 latest attempt 均可重放。
- publication transaction 故障会完整 rollback candidate facts。
- transaction rollback 后 last-good Portfolio/Overview 继续可读。
- latest attempt 明确保留 run id、reason、error type。
- 如果没有任何 last-good publication，读取继续 fail closed。
- 如果 ledger/quote facts 已经独立 committed 并与 last-good identity 不一致，读取继续 fail closed。

## A2. Read availability 与 action readiness 分离

建立统一 readiness projection：

```text
process
scheduler
market_ingestion
valuation_read
portfolio_read
research
shadow
risk
execution
```

每个 lane 至少包含：

```text
status = ready | degraded | blocked | unavailable
as_of
reason
safe_next_action
```

示例：

```text
valuation_read = ready
as_of = 2026-09-04T15:00:00+08:00

market_ingestion = degraded
reason = post_close_publication_failed

risk = blocked
reason = latest_market_evidence_unavailable
```

### A2 验收

- `/api/health` 仍只声明 process liveness，不伪装 financial readiness。
- 新的 application-readiness projection 不联系 provider、不写 DB、不授予 authority。
- Overview 能区分“上一份 verified 数据可读”与“最新刷新失败”。
- Decision/Risk/Execution 不能因为 UI 可读而自动放行。

## A3. Writer / Reader failure domain 隔离

所有 candidate writer 统一满足：

```text
stage
-> validate
-> build candidate
-> atomic publish
-> switch current pointer
```

失败只能产生：

```text
failed attempt + incident evidence
```

不能改变 last-good pointer。

优先检查：

- quote ingestion；
- post-close promotion；
- valuation publication；
- portfolio read snapshot；
- research dataset publication；
- strategy promotion；
- release activation。

## A4. Production-state Replay Suite

创建 `tests/replay/`，将真实事故抽象为脱敏的 deterministic fixture，而不是只依赖小单元测试。

首批场景：

1. `PRE_CLOSE` 被 provider 标成当前 quote date；
2. verified 15:00 close 与错误 PRE_CLOSE 冲突；
3. last-good valuation 后 publication transaction 失败；
4. provider timeout / partial batch；
5. DB lock；
6. restart during stage；
7. restart after stage before publish；
8. same-timestamp authority conflict；
9. timezone-equivalent timestamps；
10. market holiday；
11. stale quote；
12. out-of-order quote；
13. duplicate run / retry；
14. migration from a sanitized production DB clone；
15. market bars changed while portfolio read snapshot is being built。

### A4 验收

每个 fixture 必须声明：

```text
expected current publication
expected latest attempt
expected read availability
expected Decision/Risk state
expected DB mutation count
expected audit events
```

## A5. Release / upgrade reliability

每个 release candidate 在正常 CI 之外增加：

```text
fresh-db startup
old-version DB migration
sanitized production clone migration
restart replay
failed-publication replay
read-only endpoint smoke
```

任何升级都不得要求手工编辑生产 SQLite 才能恢复。

### Phase A Exit Gate

只有同时满足以下条件才能进入 Phase B：

- 单个 market-data writer 失败不会摧毁一致的 last-good reads；
- application readiness 可解释当前可读性和 action readiness；
- 今天这类事故有 deterministic replay；
- production clone migration 可重复；
- CI / release candidate 全绿；
- 用户正常页面不再把局部 market incident 简化成无上下文“加载失败”。

---

# Phase B — Research Market Data Fabric

目标：建立真正可供 Alpha Factory 消费的数据基础，而不是把 `quote_snapshots` 当作量化历史数据库。

## B1. 数据职责

### SQLite / app.db

保留：

- ledger；
- canonical financial facts；
- valuation publication；
- runtime controls；
- audit/event log；
- Decision/Risk/authority；
- compact dataset metadata / receipts。

### Columnar market store

使用现有 DataStore / Parquet 路线承载：

- daily OHLCV；
- minute OHLCV；
- adjustment factors；
- universe history；
- fundamentals point-in-time snapshots；
- derived feature matrices。

第一阶段不为了“架构漂亮”强制引入 DuckDB。优先使用 Polars scan/read Parquet；只有 benchmark 证明跨表 SQL 查询成为瓶颈时再引入 DuckDB query layer。

## B2. Canonical market dataset contract

任何研究 dataset 必须绑定：

```text
universe identity
instrument identity
calendar identity
source/provider
source receipt
start/end
frequency
adjustment policy
row count
content fingerprint
created_at
quality report
```

必须支持 content-addressed replay。

## B3. Universe history

禁止只用“今天仍上市”的股票回看历史。

实现：

```text
symbol
instrument_type
listed_at
 delisted_at
board
industry_as_of
tradable_on_date
```

研究 universe 必须按研究日重建。

## B4. Daily data 先于 full-market 1m

Profit Engine 第一批 Alpha 以日频横截面研究为主，因为：

- 数据更容易完整；
- 成本模型更稳定；
- 调试更容易；
- 对个人资金容量更适合；
- 可以更快建立统计研究闭环。

优先字段：

```text
OHLCV
amount
turnover
market_cap / float_market_cap
limit state
suspension
adjustment factor
index/industry membership
```

## B5. Minute data

在日频研究稳定后增加：

```text
1m OHLCV + amount
```

阶段顺序：

1. 当前持仓 / watchlist / research panel；
2. 受控 universe；
3. provider capability 和本地存储验证通过后，再考虑 full-market 1m。

分钟数据用于：

- intraday execution simulation；
- VWAP / TWAP benchmark；
- opening / closing behavior；
- volume-price microstructure alpha；
- minute strategy replay。

它不是 execution authority。

### Phase B Exit Gate

- 指定任意历史交易日可以重建当日 universe；
- 同一 dataset identity 多次构建 content fingerprint 相同；
- future leak / duplicate / timestamp / missing-field 检查全部通过；
- raw market data 与 canonical financial facts 明确隔离；
- 至少一套 3 年以上的日频 point-in-time research panel 可稳定重放。

---

# Phase C — Alpha Factory

目标：让 Karkinos 从“跑策略”升级为“批量发现和管理预测信号”。

## C1. 新增一等 Alpha Domain

建议新增顶层 `alpha/` 包，保持现有 `strategy/` 不破坏，逐步迁移。

初始结构：

```text
alpha/
  contracts.py
  registry.py
  transforms.py
  neutralization.py
  labels.py
  diagnostics.py
  correlation.py
  evaluation.py
  library/
```

一个 AlphaDefinition 至少包含：

```text
alpha_id
name
semantic_version
frequency
required_fields
lookback
expression/model_ref
normalization
neutralization
expected_direction
```

## C2. 第一批 Alpha 不追求复杂模型

先建立 20-50 个可解释 baseline alpha：

- short-term reversal；
- medium momentum；
- residual momentum；
- volume expansion；
- turnover anomaly；
- volatility contraction/expansion；
- gap behavior；
- close-location value；
- moving-average distance；
- relative strength；
- liquidity；
- size；
- value/quality（数据足够后）；
- industry-relative signals。

目标不是证明某一个 Alpha 很神，而是验证整个 Alpha Lab 能可靠地区分有效、无效和过拟合信号。

## C3. 标准 Alpha Diagnostics

每个 Alpha 自动输出：

```text
coverage
mean IC
RankIC
IC std
ICIR
positive-IC ratio
1d / 5d / 10d / 20d decay
quantile returns
long-short spread
turnover
cost sensitivity
capacity proxy
industry exposure
size exposure
beta exposure
regime breakdown
```

## C4. Correlation / redundancy

建立 Alpha correlation matrix：

```text
raw score correlation
rank correlation
PnL correlation
turnover correlation
```

高相关 Alpha 不因为名字不同就算多个独立 edge。

## C5. OOS discipline

默认研究流程：

```text
train / discovery window
-> validation window
-> rolling OOS
-> untouched final holdout
```

参数选择只能使用允许的历史窗口。

所有 leaderboard 默认以 OOS after-cost 指标排序，不显示只靠 IS 最优得出的“冠军”。

### Phase C Exit Gate

- 至少 20 个 baseline Alpha 通过同一套 diagnostics；
- 无效随机 Alpha 能被明确识别为无 edge；
- 任一 Alpha 的结果可由 dataset + definition + evaluation policy 完整重放；
- leaderboard 只使用 OOS 指标；
- correlation / redundancy 可见；
- 不存在 Alpha 直接生成真钱 order 的路径。

---

# Phase D — Portfolio Construction

目标：从“哪个股票得分高”升级为“在真实约束下应该持有哪些股票、各持多少”。

## D1. 两个 baseline portfolio

先实现简单但强的对照：

### Baseline A — Top-N Equal Weight

```text
rank alpha
-> top N
-> equal weight
-> single-name cap
-> industry cap
-> turnover cap
```

### Baseline B — Rank Weight

按截面 rank 转换 target weight，并限制 concentration / turnover。

复杂 optimizer 必须优于这两个 baseline 才有存在价值。

## D2. Alpha combination

支持：

```text
fixed weight
IC weighted
rolling IC weighted
risk-adjusted weight
correlation-aware ensemble
```

禁止模型在没有 OOS evidence 的情况下自动扩大权重。

## D3. Risk model

第一阶段：

- historical covariance；
- shrinkage；
- industry exposure；
- size / beta / volatility exposure；
- concentration；
- liquidity。

后续再考虑更复杂的 factor risk model。

## D4. Cost-aware optimization

复用 Karkinos 已有 fee / tax evidence，加入：

```text
commission
minimum commission
stamp tax
spread proxy
slippage curve
turnover penalty
volume participation
```

核心 objective：

```text
expected alpha
- risk penalty
- transaction cost
- turnover penalty
```

## D5. 中国市场约束

必须原生支持：

- T+1；
- 100 股 lot；
- 涨跌停；
- 停牌；
- ST / board constraints；
- 最小成交额 / liquidity；
- 可交易 universe；
- 现金余量。

### Phase D Exit Gate

- 所有 portfolio 都能解释“为什么持有”和“为什么是这个权重”；
- after-cost portfolio 明显优于随机 / market-neutral fake baseline 才能进入 shadow；
- optimizer 必须在 OOS 上优于 simple baseline，否则保留 simple baseline；
- portfolio result 绑定 exact Alpha inputs、risk model、cost model 和 dataset identity。

---

# Phase E — Execution Simulator + Shadow

目标：验证理论收益是否能在真实交易摩擦下存活，而不是立即接自动下单。

## E1. 统一 execution semantics

建立共享 execution kernel，Backtest 和 Shadow 使用同一套：

```text
order intent
market session
lot rounding
T+1
limit state
suspension
fees
slippage
partial fill policy
```

## E2. Minute-assisted fill simulation

日频策略也可以用 1m 数据评估：

- next-open；
- VWAP；
- close auction；
- participation rate；
- adverse move after signal。

## E3. Shadow target portfolio

每天固定产生：

```text
model target portfolio
actual current portfolio
required trades
simulated fills
expected cost
realized next-period outcome
```

默认不触发 broker write。

### Phase E Exit Gate

- 至少一个完整滚动 period 的 shadow 数据；
- expected vs realized slippage 可量化；
- simulated turnover / fills / rejects 可重放；
- Shadow 失败不会改变 production ledger；
- 策略 edge 在执行摩擦后仍为正，才允许进入后续资本讨论。

---

# Phase F — Live Attribution / Alpha Health

目标：知道“为什么赚 / 为什么亏 / edge 是否正在消失”。

## F1. Portfolio attribution

每日归因至少分解：

```text
market beta
industry
size
momentum
volatility
alpha contribution
fees
slippage
unexplained residual
```

## F2. Alpha live health

每个 Alpha 跟踪：

```text
research IC
rolling live IC
expected spread
realized spread
expected turnover
realized turnover
expected cost
realized cost
coverage drift
feature distribution drift
```

状态：

```text
healthy
warning
degraded
quarantined
retired
```

## F3. 自动降级，但不自动扩大 authority

允许自动：

- 降低研究权重；
- quarantine Alpha；
- 停止生成 candidate portfolio；
- 触发人工 review。

不允许自动：

- 提高资金规模；
- 扩大 symbol universe；
- 放宽 risk limits；
- 开启 broker submission；
- 重新启用已 retired Alpha。

### Phase F Exit Gate

- 所有 shadow/live PnL 都能绑定到 exact model / portfolio / cost / fill evidence；
- Alpha degradation 有 deterministic rule；
- retired Alpha 不再影响 target portfolio；
- live attribution 可以解释主要 PnL 来源和 cost leakage。

---

# Phase G — Controlled Capital Pilot

只有 Phase A-F 的 evidence 足够后才进入。

第一阶段仍采用：

```text
human reviewed target portfolio
-> Karkinos order plan
-> human confirmation
-> bounded execution
-> reconciliation
-> attribution
```

不以“自动交易”作为 Profit Engine 的完成标准。

资本扩大必须由独立的人类 review 决定，而且只能基于：

- shadow/live OOS evidence；
- drawdown；
- capacity；
- slippage；
- turnover；
- live IC；
- reconciliation quality；
- incident history。

---

# 3. 具体开发顺序

下面的 slice 尽量保持“一次 PR 可以独立验收”。

## Reliability slices

1. Last-good valuation publication 与 latest attempt 分离。
2. Publication failure regression tests。
3. 删除 read-side 对未知 `previous_close_date` 的猜测；未知就保持 unknown。
4. Application readiness projection。
5. Overview degraded-state UX。
6. `tests/replay/` 基础设施。
7. 2026-09-04 PRE_CLOSE/post-close incident fixture。
8. DB lock / restart / partial batch replay。
9. Sanitized production-clone migration test。
10. Release candidate 加 replay gate。

## Data slices

11. Research dataset identity contract。
12. Historical universe snapshot contract。
13. Point-in-time daily panel builder。
14. Adjustment / tradability / limit-state columns。
15. Dataset quality report + content fingerprint。
16. Multi-year daily panel acceptance fixture。
17. 1m storage contract。
18. Bounded-universe minute ingestion。

## Alpha slices

19. `alpha/` contracts + registry。
20. label generation + no-lookahead tests。
21. first five baseline Alphas。
22. IC / RankIC / decay diagnostics。
23. quantile return / turnover / cost diagnostics。
24. neutralization / exposure report。
25. Alpha correlation matrix。
26. rolling OOS evaluator。
27. 20+ Alpha baseline library。
28. OOS-only Alpha leaderboard。

## Portfolio slices

29. Top-N equal-weight baseline。
30. Rank-weight baseline。
31. turnover / concentration / industry constraints。
32. canonical after-cost evaluator。
33. alpha ensemble weights。
34. covariance / shrinkage risk model。
35. constrained optimizer。
36. optimizer-vs-simple-baseline acceptance。

## Shadow / attribution slices

37. shared execution simulator contract。
38. lot / T+1 / limit / suspension simulator。
39. minute-assisted fill model。
40. daily target portfolio artifact。
41. shadow fill / cost record。
42. portfolio attribution。
43. Alpha live-health report。
44. quarantine / retirement state machine。

---

# 4. CI 与质量门槛

每个 Profit Engine PR 至少属于下面一类 gate：

```text
unit
property / invariant
replay
OOS research acceptance
migration
performance benchmark
browser/operator smoke
```

禁止用“总测试数增加”代替正确性证明。

特别要求：

- 数据时间语义必须有 timezone / session tests；
- research 必须有 no-lookahead tests；
- dataset 必须有 deterministic fingerprint tests；
- portfolio 必须有 cost / lot / T+1 tests；
- publication 必须有 fault injection；
- release 必须有旧 DB migration + replay。

---

# 5. 第一阶段成功标准

在考虑任何真钱自动化之前，Karkinos 至少要证明：

1. 一个局部数据事故不会让整个可读应用失效；
2. 可以稳定构建 point-in-time 的多年度 A 股日频 research panel；
3. 可以批量评估多个 Alpha，而不是只回测一个 Strategy；
4. 可以区分 IS 与 OOS；
5. 可以计算 Alpha correlation / decay / turnover；
6. 可以把多个 Alpha 转成 after-cost target portfolio；
7. 可以用真实中国市场约束做 shadow execution；
8. 可以解释 PnL 和 Alpha degradation；
9. 所有关键结果都可由 content-addressed evidence 重放；
10. AI、Strategy 或 Alpha 本身都不能直接获得资本或 broker authority。

---

# 6. 暂不做

在以上链路稳定之前，明确不优先：

- HFT / tick-level execution；
- FPGA / co-location；
- 全市场逐笔 tick 长期存储；
- 复杂深度学习大模型预测作为第一条 Alpha 主线；
- 无人值守真钱自动交易；
- AI 自动扩仓 / 扩 universe / 改 risk limits；
- 多 broker 机构级 OMS；
- 为了对标别的项目继续堆页面。

---

# 7. 当前最近动作

当前开发顺序固定为：

```text
Reliability Gate
-> Production Replay
-> Point-in-time Daily Data
-> Alpha Factory
-> Portfolio Construction
-> Execution Simulation / Shadow
-> Live Attribution
-> Controlled Capital Pilot
```

只要上一层的 exit gate 没有通过，下一层可以做实验性代码，但不得成为 production authority 或 release readiness 的替代证据。
