# Karkinos 架构

本文只记录长期稳定的系统边界和 invariant。当前开发顺序属于 [PLAN.md](PLAN.md)，源码物理布局属于 [CODEBASE.md](CODEBASE.md)。

## 1. 架构原则

1. **Data integrity before freshness.** 时间语义、来源、身份和可重放性优先于“看起来更新”。
2. **Persisted facts before authority.** Provider、模型和缓存不能直接成为账户、风险或交易事实。
3. **Fail closed on the affected action.** 需要新鲜证据的动作必须阻断，但无关功能不应被连带打死。
4. **Last-good reads survive failed writes.** 一个失败的 candidate publication 不能摧毁已经成功发布的可读快照。
5. **One concept, one owner.** 估值、收益、费用、风险等核心概念只能有一个 canonical 计算所有者。
6. **Replay over guesswork.** 生产故障和研究结果都必须能够用持久化输入确定性重放。
7. **Human-supervised authority.** 权限可以自动暂停或收窄，不能自行续期、扩大或恢复。

## 2. 系统形态

Karkinos 继续采用 **Python modular monolith + 隔离 worker**，而不是为了“专业感”拆成微服务。

```text
React / TypeScript
        |
FastAPI API / Control Process
        |
Application Services
        |
Research | Portfolio | Decision | Risk | OMS | Reconciliation
        |
Persistence / Dataset Boundaries
        |
Market Providers | Model Provider | Broker Edge

Background isolation:
- Research Worker
- Market-data worker / heavy ingestion worker（按需要逐步隔离）
```

API 负责读取、命令入口和控制面；provider-heavy、model-heavy 工作不得成为 API 可用性的单点故障。

## 3. 两个数据平面

### Market Data Plane

负责大量、可复现、point-in-time 的研究数据：

```text
universe
OHLCV (1d / future 1m)
adjustment factors
suspension / limit state
turnover / liquidity / market cap
industry / membership
fundamentals
feature datasets
```

这些数据是研究输入，不是交易权限。高容量历史数据应逐步采用适合分析的列式存储和内容指纹，而不是无限扩张 `app.db`。

### Financial Control Plane

负责小而强一致、可审计、需要事务语义的事实：

```text
canonical quote / close
valuation publication
ledger
fees
Account Truth
risk decisions
Decision
OMS / fills
reconciliation
authority / runtime controls
audit events
```

这里优先使用 SQLite 的事务、唯一约束、WAL、内容身份和 append-oriented audit。

## 4. 当前持久化边界

- `app.db`：authoritative financial/control facts、ledger、risk、OMS、runtime controls、audit。
- `meta.db` / market storage：历史 market bars 和 dataset metadata。
- 后续高容量 market/research datasets 迁移到 Parquet + DuckDB/Polars 属于 [PLAN.md](PLAN.md) 的演进，不要求重写 Financial Control Plane。
- 任何 frozen research dataset 都必须有确定的内容 fingerprint 和 point-in-time 语义。

## 5. Publication 与读取语义

当前估值 publication 使用两个不同概念：

```text
valuation_snapshot_publication
    = 最后一次成功、当前可读取的 canonical publication

valuation_snapshot_publication_attempt
    = 最近一次 publication attempt 的结果
```

正确状态机：

```text
candidate facts
-> validate
-> transaction
   -> success: atomically publish new current
   -> failure: rollback candidate facts + record failed attempt
              current last-good remains unchanged
```

没有任何成功 publication 时，financial reads 继续 fail closed。

已经有成功 publication 时，新写入失败可以让读取进入 `ready/stale/degraded`，但不能把上一份已验证快照直接变成全站 503。与此同时，依赖最新证据的 Decision/Risk/Execution 可以继续 `blocked`。

## 6. Read availability 与 Action readiness

二者必须分开：

```text
Read availability
- ready
- stale/degraded but explainable
- unavailable

Action readiness
- ready
- blocked by freshness / conflict / reconciliation / authority / risk
```

“页面能否查看已有事实”与“现在能否产生新的资金动作”不是同一个问题。

## 7. Domain ownership

| Domain | Owns |
| --- | --- |
| Market data | datasets、bars、quotes ingestion、source health、freshness |
| Research / Alpha | frozen datasets、alpha definitions、experiments、OOS evidence |
| Portfolio | target weights、positions projection、portfolio construction |
| Ledger / Valuation | cash、lots、cost basis、financial events、canonical valuation |
| Decision | account-bound daily actions、blockers、explanations |
| Risk | deterministic pre-trade/runtime risk policy |
| Execution | broker-neutral orders、fills、simulation semantics |
| Reconciliation | broker/account/order/fill agreement and recovery |
| Operations | scheduler、workers、alerts、readiness、runbooks |
| AI research | evidence-bound hypotheses and critiques; never authority |

Presentation 可以格式化和组合 canonical values，但不能重新拥有这些计算。

## 8. Backtest / Shadow / Live 语义

以下语义必须尽量共享实现，而不是各写一套：

- signal timing；
- order timing；
- T+1；
- 100 股 lot；
- 涨跌停 / 停牌；
- fees / taxes；
- slippage；
- turnover；
- position / liquidity limits；
- risk gates。

不同环境可以更换数据源和执行 adapter，但不能悄悄改变金融语义。

## 9. 语言与性能策略

- Python 继续作为 research、orchestration、API 和大部分 domain 的主语言。
- TypeScript/React 继续负责 Web。
- 不进行全量 Rust 重写。
- 只有在 profiler/benchmark 证明 Python + NumPy/Arrow/Polars/DuckDB 无法满足明确 SLO 时，才把热路径下沉到 Rust/native kernel。
- Rust 是可选 compute engine，不是新的产品架构中心。

业务语义错误、时间身份错误和错误状态机不会因为换语言自动消失。

## 10. 故障域

单个 provider、market refresh、research worker、scheduler task 或 candidate publication 的失败必须被限制在对应功能域，并暴露明确状态和安全下一步。

生产 readiness 至少应能够分别表达：API、database、market ingestion、valuation reads、Decision readiness、execution authority，而不是只报告“进程活着”。

## 11. 架构变更规则

只有以下变化才更新本文：

- 长期组件边界改变；
- 数据 ownership 改变；
- transaction / publication / replay invariant 改变；
- 进程或故障域改变；
- 语言边界或存储职责改变。

版本进度、测试数量、单次事故和完成日志不写进本文。
