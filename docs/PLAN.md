# Karkinos 实施计划

本文是唯一当前计划。不要再创建第二份 roadmap、Profit Plan 或实现日志。

## North Star

```text
raw market data
-> point-in-time datasets
-> alpha discovery
-> alpha validation
-> alpha combination
-> portfolio construction
-> realistic execution simulation
-> paper/shadow
-> attribution
-> controlled capital
```

目标不是承诺盈利，而是工程化地提高发现、验证、部署和淘汰正期望 edge 的能力。

## 当前优先级

现在只做 **Phase A — Reliability Gate**。Phase A 没通过之前，不扩大 broker 写权限，不继续扩 AI 自动化，也不为了分钟数据或新页面绕开稳定性工作。

---

## Phase A — Reliability Gate

### A1. Market fact 时间语义与 last-good publication

状态：核心修复已落到 `main`，待随稳定 release 进入 production。

已经做：

- `PRE_CLOSE` 只有在能证明属于严格更早 market session 时才可物化为 daily close。
- verified same-day close 继续作为独立 authoritative evidence。
- `valuation_snapshot_publication` 与 `valuation_snapshot_publication_attempt` 分离。
- failed candidate publication 回滚并记录 incident，不再覆盖已有 ready publication。

还要做：删除 read-side 对未知 `previous_close_date` 的猜测，确保显示层也不重新制造错误时间身份。

**Exit gate:** 今天已经复现过的 PRE_CLOSE/official-close 冲突不能再次污染 canonical close；失败 publication 后 last-good portfolio read 仍可重放。

### A2. Read availability / Action readiness 分离

实现统一 readiness projection：

```text
API                  ready/degraded/down
database             ready/degraded/down
market ingestion     ready/degraded/failed
valuation read       ready/stale/unavailable
decision             ready/blocked
risk                 ready/blocked
execution authority  disabled/ready/blocked
```

Overview/Portfolio 可以明确显示上一份已验证快照及其 `as_of`，而 Decision/Risk/Execution 对最新证据继续 fail closed。

**Exit gate:** 一个 market refresh 失败不能无解释地让 Overview/Portfolio 全部 503；UI 必须展示数据时间和 blocker。

### A3. Writer / Reader 故障域隔离

- provider-heavy ingestion 不在 GET 路径执行；
- research worker、market ingestion、API 生命周期独立观测；
- candidate writer 只能原子替换 current publication；
- failed writer 不修改 last-good pointer；
- retry 必须幂等，不允许“为了恢复”直接改数据库 marker。

**Exit gate:** provider timeout、worker crash、partial batch 和 publication exception 都只影响对应域。

### A4. Production-state Replay Suite

建立匿名化真实事件 fixtures，不只做小单元测试：

- realtime PRE_CLOSE -> 15:00 verified close；
- same-instant conflict；
- out-of-order quote；
- market holiday / weekend；
- provider timeout / partial batch；
- DB lock；
- crash between stage and commit；
- restart during recovery；
- failed post-close publication after a complete snapshot；
- migration from the previous stable production schema。

每个 fixture 都验证最终 read state、action readiness、audit 和幂等性。

**Exit gate:** release candidate 必须通过生产状态 replay，而不仅是 fresh test DB。

### A5. Release / Migration Reliability

- candidate 在 disposable state 上验证；
- stable activation 在真实 mutable-state clone 上做 schema/state preflight；
- migration 不得“修正”无法证明的历史金融事实；
- activation failure 自动回滚 pointer 和 mutable state；
- production status 显示 exact release identity 与 recovery state。

**Exit gate:** 从当前 stable 的真实 state clone 升级、启动、读取、回滚均确定性通过。

### Phase A 完成条件

满足以下条件后才进入 Phase B：

- 无单一 market/research provider 故障可导致无解释全站不可用；
- last-good reads 与 latest action readiness 完全分离；
- 真实事故 fixture 进入 CI；
- 当前 production 可以通过受支持 release path 升级到包含这些修复的 stable release。

---

## Phase B — Point-in-time Market Data Fabric

先做日频，再决定 full-market 1m。

### B1. Historical universe

保存每个交易日真实可交易 universe，而不是用今天的股票列表回放历史。处理上市、退市、停牌、ST/板块和历史成分变化。

### B2. Canonical daily dataset

统一：

- raw OHLCV；
- adjustment factors；
- previous close / official close；
- limit state；
- turnover / amount / liquidity；
- market cap；
- industry membership；
- source and revision identity。

### B3. Point-in-time fundamentals

财务特征使用真实可用日期/公告日期，不按报告期日期偷看未来。

### B4. Dataset storage

高容量历史/研究数据迁移到：

```text
Parquet / Arrow
+ DuckDB / Polars
+ content fingerprint
```

SQLite 保留 Financial Control Plane，不成为大规模量化数据湖。

### B5. Dataset snapshot contract

每次研究绑定 exact universe、date range、columns、source revisions、row hash 和 quality report。

### B6. Data quality acceptance

检测 missing bars、duplicates、non-monotonic timestamps、future data、identity conflicts、survivorship leak 和 adjustment drift。

**Phase B Exit gate:** 任意日频研究结果可以从同一 snapshot identity 完整重放，且不存在已知 survivorship/future leak。

---

## Phase C — Alpha Factory

### C1. Alpha 作为一等 domain

Alpha 输出优先是 cross-sectional score / expected return，而不是 BUY/SELL。

每个 Alpha 保存：definition、inputs、dataset identity、parameters、version、author、created_at。

### C2. Standard diagnostics

自动计算：

- IC / RankIC / ICIR；
- 1/5/10/20d decay；
- quantile spread；
- turnover；
- cost sensitivity；
- coverage；
- industry/size/beta exposure；
- regime stability；
- capacity proxy。

### C3. Baseline alpha library

先建立 20–50 个简单、可解释、可复现 baseline：momentum、reversal、volatility、volume/price、liquidity、quality、value、growth 等。

简单 Alpha 是 benchmark，不允许为了复杂模型删除它们。

### C4. Alpha correlation / redundancy

计算 alpha-alpha correlation、conditional correlation 和 marginal contribution，避免堆叠同一个风险因子的不同名字。

### C5. Validation discipline

时间切分、rolling OOS、walk-forward、regime split、parameter sensitivity、multiple-testing awareness 均成为标准产物。

### C6. ML escalation

只有当 simple baselines 和数据质量稳定后，再引入 tree/GBDT、MLP/temporal、ensemble。复杂模型必须在同一 OOS/cost framework 中赢过简单基线。

**Phase C Exit gate:** 至少一个 alpha ensemble 在多个 OOS 窗口、真实成本敏感性和风险暴露约束下仍有稳定统计证据。

---

## Phase D — Portfolio Construction

### D1. Baselines

实现并长期保留：Top-N Equal Weight、Rank Weight。

### D2. Risk model

至少覆盖 market beta、industry、size、volatility 和 concentration；后续再扩展 factor covariance。

### D3. Cost model

统一佣金、最低佣金、印花税、过户/交易费用、spread/slippage、turnover 和 liquidity participation。

### D4. Optimizer

目标形式：

```text
expected alpha
- risk penalty
- transaction cost
- turnover penalty
```

约束包括单股、行业、流动性、lot size、cash、T+1、涨跌停和停牌。

### D5. Portfolio attribution before deployment

解释目标权重来自哪些 Alpha、风险约束和成本取舍。

**Phase D Exit gate:** 复杂 optimizer 必须在 OOS after-cost 结果上稳定优于或明确补充 simple baselines；否则使用简单方案。

---

## Phase E — Execution Simulation and Shadow

### E1. Shared execution semantics

Backtest、paper、shadow、未来 live 共用 T+1、lot、fees、limits、suspension、order timing 和 fills 语义。

### E2. Fill/slippage simulator

支持 open/close/VWAP-like assumptions、volume participation、partial fill 和 no-fill。

### E3. Target -> order planner

从 target weights 生成可解释、可重放的 order plan；不直接授予 broker 权限。

### E4. Shadow operation

每日冻结 target portfolio、expected return、expected risk、expected cost 和 planned orders，再观察真实后续价格和可成交性。

### E5. 1m data decision

只有日频 Alpha/portfolio 闭环需要更细 execution evidence 时，才建设 full-market 1m。不要因为 TSP 有 1m 就把它当先决条件。

**Phase E Exit gate:** shadow 的 realized slippage、turnover、fills 和 returns 可以与 backtest assumptions 定量比较。

---

## Phase F — Attribution, Decay and Controlled Capital

### F1. PnL attribution

拆分 market、industry、size/style、alpha、execution cost 和 unexplained residual。

### F2. Research vs shadow monitoring

持续比较 research IC / turnover / cost 与 shadow realized values。

### F3. Alpha health state

```text
healthy -> warning -> degraded -> quarantine -> retired
```

状态由确定性规则和人工复核驱动，AI 可以解释但不能自行扩大资本。

### F4. Strategy/ensemble lifecycle

promotion、rollback、replacement 和 retirement 都绑定 exact research/shadow evidence。

### F5. Controlled capital pilot

只有在完整 replay、shadow、cost、attribution 和 reconciliation evidence 足够时，才允许极小资本、逐单人工确认的 pilot。

Broker 写路径不是盈利来源，也不是前几个 Phase 的主任务。

**Phase F Exit gate:** 系统能回答“赚/亏来自哪里、edge 是否还存在、继续使用它需要哪些证据”，再讨论扩大资本。

---

## 明确推迟

在前置 Phase 未通过前，不优先做：

- 新的 broker write adapter；
- session-bounded 自动真钱交易；
- 大范围 AI 自动化；
- full-market tick；
- 为了架构审美的全量 Rust 重写；
- 社区策略市场、多账户机构 OMS；
- 与 Profit Engine 无关的新页面堆叠。

## 最近的实施顺序

1. 完成 A1 后续 read-side 时间语义清理。
2. 实现 A2 readiness state model，并让 Overview 展示 last-good `as_of` 和最新失败原因。
3. 建立 A4 第一批真实事故 replay fixtures。
4. 做 A5 当前 stable -> candidate 的 state-clone migration/rollback 验证。
5. 发布包含 Reliability Gate 核心修复的新 stable release 并升级 production。
6. 开始 B1/B2：historical universe + canonical daily dataset。
7. 进入 Alpha Factory 前再做一次有限 architecture review；不进行语言重写。
