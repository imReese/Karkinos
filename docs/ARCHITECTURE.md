# Karkinos 架构

本文定义 Karkinos 的**目标架构**和迁移期间必须保持的 invariant。它不是当前代码树的逐文件说明。实施顺序见 [PLAN.md](PLAN.md)，当前目录映射见 [CODEBASE.md](CODEBASE.md)。

## 1. 架构结论

Karkinos 的最终形态是一个 **single-node、local-first、Python-first 的量化研究与投资系统**。

不采用“大而全微服务”作为目标。目标运行时由少量受监督进程组成，核心数据通过持久化契约连接：

```text
Web
 |
API / Query / Command
 |
+-------------------+--------------------+
|                   |                    |
Data/Operations     Research Worker      Execution Worker (later)
Worker              (heavy/model work)   (broker edge only)
|                   |                    |
+-------------------+--------------------+
                    |
          Persistent contracts
```

系统按三种职责组织，而不是按页面组织：

```text
Research & Data Plane
Financial / Trading Control Plane
Operations Plane
```

## 2. 核心原则

1. **Point-in-time before prediction.** 没有正确时间语义的数据不能进入 Alpha 研究。
2. **Immutable inputs before reproducibility.** 研究和发布都绑定内容身份，不依赖“当前目录里刚好是什么”。
3. **Persisted facts before authority.** Provider、模型、缓存和 UI 都不能直接成为账户或交易事实。
4. **One concept, one owner.** 一个金融概念只能有一个 canonical 计算所有者。
5. **Fail closed on the affected action.** 不确定性阻断受影响动作，不扩大成无关功能的全局故障。
6. **Last-good survives failed attempts.** 最新失败不能摧毁上一份已验证、仍可重放的状态。
7. **Replay over repair-by-guessing.** 生产事故和研究结果都从持久化输入重放，不靠手工改 marker。
8. **Research/live semantic parity where it matters.** 成本、成交、T+1、lot、停牌和风险语义不能各写一套。
9. **Human-supervised capital.** 权限不能自行扩张。
10. **Optimize only measured bottlenecks.** 先修 ownership/语义，再谈 Rust 或分布式系统。

## 3. 三个 Plane

### 3.1 Research & Data Plane

负责可批量分析、可重放、point-in-time 的研究材料：

```text
market calendar
historical universe
OHLCV / 1d / later 1m
adjustment factors
limit / suspension state
turnover / liquidity / market cap
industry / membership
fundamentals
features
alpha outputs
model forecasts
experiment artifacts
```

它回答“当时能知道什么”和“这个研究输入到底是什么”，不拥有账户权限。

### 3.2 Financial / Trading Control Plane

负责小而强一致、需要事务和审计的事实：

```text
canonical quote / close
ledger / lots / cash
valuation publication
fees
Account Truth
portfolio/account state
risk decisions
orders / fills / OMS
reconciliation
authority / runtime controls
audit events
```

这里的事实可以引用 Research/Data Plane 的 immutable identity，但不能依赖可变文件路径或 provider 当前返回值。

### 3.3 Operations Plane

负责系统运行，而不是金融计算：

```text
durable jobs
schedules
leases / heartbeats
retry / backoff
last success / latest attempt
worker readiness
incidents
release identity
activation / rollback state
```

后台工作必须有持久 run identity；API 进程不再是匿名 `asyncio.create_task()` 的总宿主。

## 4. 目标运行时拓扑

### API process

只负责：

- provider-free queries；
- 显式 commands；
- request validation / response projection；
- WebSocket/status；
- 将异步工作写入 durable job queue。

API 不应承担长期 provider polling、全市场 ingestion、模型调用或重研究任务。

### Data / Operations worker

负责：

- scheduler；
- market calendar / universe / quote / bar ingestion；
- dataset publication；
- provider retry/backoff；
- provider-free scheduled operational jobs。

单个 provider timeout 或 ingestion crash 最多让该 worker/domain degraded，不能拖垮 API。

### Research worker

负责：

- feature/Alpha/Model experiments；
- OOS / sweep / diagnostics；
- AI-assisted hypothesis/critique；
- content-addressed artifact publication。

Research worker 没有账户、资本或 broker authority。

### Execution worker

真实 broker 接入前不存在生产写权限。未来启用时，它是独立、default-off 的 adapter boundary，只消费已经通过 account/risk/operator gates 的 exact order identity。

## 5. 存储拓扑

目标数据目录：

```text
data/
  control/
    app.db
  catalog/
    catalog.db
  lake/
    market/daily/...
    market/1m/...
    universe/...
    fundamentals/...
    features/...
  artifacts/
    experiments/<content-id>/
    models/<content-id>/
    reports/<content-id>/
```

### `app.db`

Financial/Trading Control + Operations 的 authoritative transactional facts。继续使用 SQLite/WAL、唯一约束、事务、append-oriented audit。

### `catalog.db`

只保存 dataset/artifact manifest、revision lineage、schema、quality report、publication pointer 和小型索引。可从 immutable artifacts 校验，不保存大规模 bars。

### `lake/`

Parquet/Arrow 是未来大规模市场与研究数据的 primary bulk representation。DuckDB 是 query engine，Polars/NumPy 是 compute engine；它们都不是 financial authority。

当前 `meta.db + SQLite market_bars + Parquet mirror` 通过迁移逐步演进，不做一次性格式重写。

## 6. 统一时间模型

任何外部金融数据至少区分：

```text
event_time / market_time
available_at
captured_at
```

必要时再记录：

```text
session_date
source_revision
published_at
```

语义：

- `event_time`：事实属于市场的哪个时点；
- `available_at`：研究者最早何时可以合法知道；
- `captured_at`：Karkinos 何时取得；
- `published_at`：Karkinos 何时把它提升为某个 canonical/dataset generation。

`PRE_CLOSE`、财报期末、公告日、复权和 universe membership 都必须按这套模型处理，禁止用 request date 猜事实归属。

## 7. Dataset publication contract

Dataset 采用 candidate -> validate -> publish：

```text
raw/staged input
-> normalize
-> validate PIT / identity / schema / quality
-> write immutable partition/artifact
-> compute content digest
-> publish manifest
```

任何 correction/revision 产生新的 generation；不能静默改写已被 experiment 引用的 bytes。

最小 `DatasetRef` 必须能绑定：

- dataset kind / schema version；
- universe identity；
- time range / frequency；
- source revisions；
- PIT policy；
- row/partition counts；
- content digest；
- quality report；
- created/published time。

## 8. Research domain

研究链路是一等系统，不挂在 HTTP route 或 AI workflow 下：

```text
DatasetRef
-> FeatureSet
-> AlphaSpec / ModelSpec
-> ExperimentRun
-> ForecastSet
-> Diagnostics
```

核心对象：

- `FeatureSpec` / `FeatureSetRef`
- `AlphaSpec`
- `ModelSpec`
- `ExperimentRun`
- `ForecastSet`
- `ResearchArtifactRef`

每个 experiment 保存 exact input refs、代码/release identity、参数、seed、结果和 artifacts。

`strategy/` 逐步变为 compatibility layer。最终 “Strategy/Deployment” 是 Alpha/Model + Portfolio Policy + Execution Policy 的组合，不是一个直接发 BUY/SELL 的黑盒。

AI 只通过 Research ports 提出 `AlphaSpec`、实验配置或 critique；它不计算 canonical metrics，也不直接进入 Order path。

## 9. Portfolio domain

Alpha/Model 输出先形成 Forecast，再进入组合构建：

```text
ForecastSet
-> Alpha ensemble
-> risk/exposure model
-> cost model
-> PortfolioTarget
-> RebalancePlan
```

核心输出是 target weights + constraints + reasons，而不是直接订单。

长期保留简单 baseline（Top-N equal weight、rank weight），复杂 optimizer 必须在同一 OOS/after-cost framework 中证明增量价值。

## 10. Simulation / Execution / Accounting

研究计算允许向量化；**成交与账户状态**采用统一事件/时间语义。

```text
RebalancePlan
-> OrderIntent
-> PreTradeRisk
-> Order
-> ExecutionAdapter
-> Fill
-> Accounting
-> Reconciliation
```

Backtest、paper、shadow、live 的区别主要是 clock/data/execution adapter，不是四套金融规则。

目标是一个 canonical order lifecycle。Paper broker、simulator、未来 broker adapter 都投影到同一 Order/Fill 状态模型，避免 paper OMS、broker lifecycle 和 persistence 各维护一套状态真相。

Backtest 不能长期依赖“默认批准风险”的兼容胶水；同一风险/订单约束必须能在 simulation 中真实执行。

## 11. Financial publication 与读取

所有 current pointer 使用同一模式：

```text
last_successful_publication
latest_attempt
```

成功时原子替换 current；失败时记录 attempt/incident，candidate 回滚，last-good 不动。

Read availability 与 Action readiness 永远分离：

```text
read: ready | stale/degraded | unavailable
action: ready | blocked
```

Portfolio/Overview 可以展示 last-good 的 `as_of` 与最新失败原因；Decision/Risk/Execution 对 fresh evidence 继续 fail closed。

## 12. Commands、Queries 与 side effects

- Query：provider-free、zero-write、只读 canonical state。
- Command：显式、typed、idempotent，写事务或 enqueue durable job。
- Background job：有 run id、claim/lease、attempt、heartbeat、result、error 和 replay identity。
- External side effect：先持久 claim，再调用外部系统；使用 client/idempotency identity；unknown outcome 只查询恢复，不盲目重试；最终由 reconciliation 关闭。

跨 SQLite 与 Parquet 不追求分布式事务；通过 immutable content ID + publish pointer 组合一致性。

## 13. Operations / readiness

每个 subsystem 至少公开：

```text
status
last_success
latest_attempt
as_of
freshness
blockers
safe_next_action
```

最低运行状态包括 API、DB、data worker、research worker、market datasets、valuation reads、Decision readiness、execution authority。

`process alive` 不是 product ready。

## 14. 依赖与语言

Python 继续负责 research、domain、orchestration、API；TypeScript/React 负责 Web。

性能路线：

```text
correct ownership/semantics
-> vectorize with NumPy/Polars
-> Arrow/Parquet/DuckDB
-> profile/benchmark
-> only then Rust/native hot path
```

如未来 simulation、optimizer 或数据 kernel 有明确 SLO 且 Python/columnar stack 无法满足，可用 Rust + Arrow/PyO3 下沉。Rust 不承担 product orchestration，也不用于“修复”业务状态机错误。

## 15. 迁移原则

- 不做 big-bang rewrite。
- 不先大搬目录再补行为测试。
- 先建立新 boundary，再让旧 facade/adapter 逐步委托进去。
- 每次迁移先有 characterization/replay tests，再移动 ownership，最后删除 compatibility。
- 当前 broker/controlled-execution 安全工作保留但冻结扩张，直到 Data -> Alpha -> Portfolio -> Shadow 主链成熟。
- 当前 immutable release/rollback 体系继续保留并作为 Operations Plane 基础。

架构参考可以借鉴 Qlib 的 Dataset/Experiment、LEAN 的可替换 data/transaction handler、NautilusTrader 的 research/live 执行语义一致性、vn.py 的 gateway/OMS 边界，以及本地 A 股工具的列式数据实践；Karkinos 不直接绑定或复制其中任何框架。
