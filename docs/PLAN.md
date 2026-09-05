# Karkinos 最终形态实施计划

本文是唯一当前实施计划。所有研发都从 [GOAL.md](GOAL.md) 与 [ARCHITECTURE.md](ARCHITECTURE.md) 导出，不再创建平行 roadmap。

## 总原则

研发顺序固定为：

```text
A. Reliability
-> B. Architecture Seams
-> C. Point-in-time Data
-> D. Research / Alpha
-> E. Portfolio / Simulation
-> F. Shadow / Attribution
-> G. Controlled Capital
```

每个 Phase 必须有可执行 exit gate。没有通过前置 gate，不用新页面、AI 自动化或 broker 功能绕过它。

---

## Phase A — Reliability Gate

目标：先让当前系统在真实状态下可预测地失败、降级和恢复。

### A1. 时间语义与 last-good publication

已完成核心修复：

- `PRE_CLOSE` 只有能证明属于严格更早 session 时才可物化为 daily close；
- verified same-day close 独立成为 authoritative evidence；
- current publication 与 latest attempt 分离；
- failed candidate publication 回滚但不覆盖 last-good。

Read-side 已删除对未知 `previous_close_date` 的猜测。未解决的发布失败按持久化请求的 typed instrument 范围保留；启动、账本重算及任何普通刷新均不能清除它。同标的的新报价不证明旧交易日的收盘冲突已修复。事实级修复收据和 resolver 尚未实现，在此之前 incident 保持 unresolved。风险批次按已绑定 action 身份在最终写事务内再次校验。

只读 `preview_daily_close_recovery` 已能绑定未来冲突 incident、完整 staged batch、显式 v2 日线回执与当前 close；回执整批重放复用 market owner，并在同一只读连接固定 meta 证据和 app 状态。它不声称跨库原子 publication generation。当前 close 存储缺少旧 normalization observation 的可重放绑定，即使候选证据通过也返回 `prior_evidence_disposition_unproven`；尚无可执行的 `eligible_to_resolve` 分支。旧 incident 不猜补，价格相等及普通成功 publication 不构成旧争议处置依据。下一步须补齐来源证据契约并完成规则审查，之后才进入 resolver。

### A2. Read availability / Action readiness

建立统一 readiness projection：

```text
api
database
background worker
research worker
market data
valuation read
decision
risk
execution authority
```

每项都有 `status / as_of / last_success / latest_attempt / blockers / safe_next_action`。

`GET /api/health/readiness` 已提供一次只读数据库事务上的基础投影。它区分进程 heartbeat、行情发布故障和持仓估值可读性；Decision/Risk 仍要求精确候选和账户 gate，Execution Authority 返回 `not_evaluated`，不能据此授予权限。Overview/Portfolio 将状态绑定到当前展示的 snapshot id，展示 last-good 时间和最近失败。

Overview/Portfolio 允许解释性 stale/degraded read；Decision/Risk/Execution 对 fresh evidence 继续 blocked。

### A3. Production-state replay

第一批 fixture 固化真实事故：

- realtime PRE_CLOSE -> verified close；
- same-instant conflict / out-of-order quote；
- holiday/weekend；
- provider timeout / partial batch；
- DB lock；
- crash between stage/commit；
- restart during recovery；
- complete snapshot 后的新 publication 失败；
- previous stable schema -> current candidate migration。

### A4. Release/state-clone gate

Candidate 必须在 production mutable-state clone 上证明：

```text
migrate
-> start
-> read
-> background readiness
-> stop
-> restart
-> rollback
```

不可证明的旧金融事实只记录 blocker，不自动“修正”。

受管 macOS `candidate` 路径在有 `data/app.db` 时先执行隔离副本 gate：SQLite backup、写入前验证副本身份、迁移、受 release guard 保护的应用 lifespan/ASGI 读取、账本和未解决 incident 不变量、GET 零写入、JobRun roundtrip、第二个候选进程启动，以及恢复原始副本后的旧版本 `--check-state`。受管入口对进程树施加 OS 网络拒绝；普通工具调用默认只提供 Python socket 检测并显式报告隔离未验证。旧版 preflight 不是 rollback start/read/stop 验收；TCP/LaunchAgent/background readiness 和跨存储一致性仍未验证，报告不授予 release eligibility。

**Phase A Exit:** 当前 production 能通过受支持的 release path 升级；单个 writer/provider 故障不再导致无解释全站不可用；真实事故 replay 进入 CI。

---

## Phase B — Architecture Seams

目标：在不 big-bang 重写的前提下建立最终架构需要的接口和故障域。

### B1. Application container / narrow ports

- 保留 `AppDatabase` compatibility facade；
- 新服务通过 typed container 注入窄 repository/query/command ports；
- 禁止新 route-to-route、service locator 和 God facade 依赖；
- server composition root 只做 wiring。

### B2. Durable background jobs

把匿名/常驻后台循环收敛到通用 job contract：

```text
job_id
kind
input_fingerprint
status
attempt
lease_owner
lease_expires_at
heartbeat_at
result_ref
error
```

先复用当前 research-worker 的 claim/lease 思路，再覆盖 market/calendar/universe/decision-evidence 等任务。

通用 `JobRun/JobStore` 和 SQLite 租约已实现，schema migration 13 添加 `job_runs`。日历任务首先接入：输入指纹幂等、有限重试、过期接管、heartbeat 和 result ref；calendar publication 在同一写事务内校验 owner/attempt/expiry。

### B3. API 与 worker 故障域拆分

目标进程：

```text
karkinos-api
karkinos-worker
karkinos-research-worker
```

API 不再直接运行 provider-heavy polling 或长期业务 loop。真实 broker write 未来才引入独立 execution boundary。

第一条迁移是 `python -m server --data-worker` 的日历采集。标准 Python/打包入口监督独立子进程退出重启；首次 spawn 失败允许 API 降级启动，父进程死亡管道终止旧 worker。采集有执行期限，续租失败和激活开始会终止该 worker；最终日历事务校验 lease 和 release guard。已发布但未完成 job 的接管复用持久化日历收据。API lifespan 不再运行此 provider loop。Market universe、decision evidence 和 live monitoring 仍留在原进程，B3 exit 尚未完成。

### B4. Dataset catalog seam

新增 immutable dataset/artifact manifest contract。新 bulk dataset 不再以 SQLite row store 为第一设计目标。

`data.dataset_catalog` 已提供日频 universe/daily 的内容寻址 Parquet、SQLite manifest/catalog、固定 schema 和 `DatasetRef` 显式读取；修订生成新 identity，读取校验字节 digest。`read_as_of` 要求两个 partition 的整个 generation 当时均已可用，否则拒绝并要求绑定更早的完整 generation，不把过滤后的缺行当成完整面板。它校验调用方提交的证据结构，不证明 provider 的历史覆盖或 availability 声明真实。

### B5. Ownership cleanup ratchet

先加规则，不先搬完所有代码：

- `analytics` 中 research analytics 与 acceptance/release tooling 分开 ownership；
- `server/services` 按 bounded context 收敛；
- `domain` 不再吸收新的跨域对象；
- `strategy` 标记为 legacy compatibility；
- architecture checker 逐步覆盖新 boundary。

**Phase B Exit:** provider-heavy background work 不再以 API process 为主要宿主；新研发可以只通过 narrow ports + durable jobs + dataset refs 接入。

---

## Phase C — Point-in-time Data Fabric

目标：得到真正可用于盈利研究的数据地基。

### C1. Canonical time model

为 market/fundamental/universe 数据统一：

```text
event_time
available_at
captured_at
session_date / revision
```

### C2. Historical universe

保存每个交易日真实可研究/可交易 universe，覆盖上市、退市、停牌、ST/板块和成分变化。

### C3. Daily market dataset

至少包括：

- raw OHLCV / amount / volume；
- adjustment factor；
- official / previous close；
- suspension / limit state；
- liquidity / turnover / market cap；
- industry membership；
- provider/revision identity。

### C4. Point-in-time fundamentals

财务特征按真实公告/可用时间进入研究，不按报告期偷看未来。

### C5. Parquet-primary lake

新数据写入：

```text
immutable Parquet/Arrow
+ catalog manifest
+ DuckDB/Polars query/compute
```

当前 SQLite market-bar 读取保持兼容，逐步迁移，不双重声称 authority。

### C6. Dataset snapshot + quality

Snapshot 绑定 exact universe、time range、columns、source revisions、PIT policy、content hash 和 diagnostics。

检测：missing、duplicate、non-monotonic、future leak、identity conflict、survivorship leak、adjustment drift。

**Phase C Exit:** 任意日频研究可以只凭 DatasetRef 重放，且不存在已知 future/survivorship leak。

---

## Phase D — Research / Alpha Platform

目标：把 Karkinos 从“策略执行器”升级为 Alpha Factory。

### D1. Experiment Recorder

每个 experiment 持久化：

```text
ExperimentRun
DatasetRef
FeatureSetRef
AlphaSpec / ModelSpec
parameters / seed / code identity
ForecastSet
metrics
artifacts
```

### D2. Alpha first-class

Alpha 输出 cross-sectional score / expected return，不直接输出 BUY/SELL。

每个 Alpha 自动产生：

- IC / RankIC / ICIR；
- 1/5/10/20d decay；
- quantile spread；
- coverage / turnover；
- cost sensitivity / capacity proxy；
- industry / size / beta exposure；
- regime stability。

### D3. Baseline library

先做 20–50 个简单、可解释 baseline：momentum、reversal、volatility、volume/price、liquidity、quality、value、growth 等。

简单基线永久保留，作为复杂模型 benchmark。

### D4. Correlation / redundancy

计算 alpha-alpha correlation、conditional correlation、marginal contribution，避免同一风险暴露换名字重复入库。

### D5. Validation discipline

标准化 train/valid/test、rolling OOS、walk-forward、regime split、parameter sensitivity、multiple-testing awareness、sealed holdout。

### D6. ML / AI escalation

只有 baseline 和数据质量稳定后才进入 GBDT/MLP/temporal/ensemble。AI 改为 Research API client：提出假设、组合实验、解释结果；不能拥有独立 canonical backtest/metric pipeline。

**Phase D Exit:** 至少一个 Alpha ensemble 在多个 OOS 窗口、真实成本敏感性与风险暴露约束下仍有稳定统计证据。

---

## Phase E — Portfolio / Simulation

目标：把预测转化为真实可执行、可解释的组合，而不是直接 BUY/SELL。

### E1. Forecast -> PortfolioTarget

实现：

```text
ForecastSet
-> ensemble
-> exposure/risk model
-> cost model
-> PortfolioTarget
```

### E2. Baseline constructors

长期保留 Top-N Equal Weight、Rank Weight。

### E3. Risk / cost model

至少覆盖：

- market beta / industry / size / volatility / concentration；
- commission / min commission / taxes / transfer fees；
- turnover / spread / slippage；
- liquidity participation / capacity。

### E4. Rebalance planner

`PortfolioTarget -> RebalancePlan` 处理 cash、100-share lot、T+1、停牌、涨跌停、最小交易金额等。

### E5. Unified simulation semantics

逐步把现有 backtest compatibility glue 收敛为：

```text
RebalancePlan
-> OrderIntent
-> PreTradeRisk
-> Order
-> ExecutionModel
-> Fill
-> Accounting
```

Paper、shadow、未来 live 使用同一 order/fill lifecycle contract。

### E6. Optimizer

复杂 optimizer 只有在 after-cost OOS 明确优于/补充简单 baseline 时才进入默认路径。

**Phase E Exit:** 组合构建、风险、费用、成交和 accounting 在 backtest/paper/shadow 中共享可验证语义；不存在 paper/live 各自一套核心 OMS 状态。

---

## Phase F — Shadow / Attribution

目标：证明研究 edge 能穿过真实时间和执行摩擦。

### F1. Daily shadow freeze

每日冻结：

```text
Dataset/Forecast identity
PortfolioTarget
expected return/risk/cost
RebalancePlan
```

之后只观察真实未来，不回填改写预测。

### F2. Realized execution diagnostics

对比 expected vs realized：

- tradability / fill；
- slippage；
- turnover；
- fees；
- return；
- exposure drift。

### F3. PnL attribution

至少拆分：

```text
market
industry/style
alpha/model
portfolio construction
execution cost
unexplained residual
```

### F4. Alpha health

统一状态：

```text
healthy -> warning -> degraded -> quarantine -> retired
```

状态由 deterministic evidence + human review 驱动；AI 只能解释。

### F5. 1m data decision

只有当日频闭环显示 execution evidence 是主要误差来源时，再建设 full-market 1m；不把分钟数据当 Alpha Factory 的前置条件。

**Phase F Exit:** 系统可以回答“研究预期为什么变成了实际收益/亏损”和“edge 是否仍存在”。

---

## Phase G — Controlled Capital

目标：在前述证据成熟后，以最小资本验证真实执行，而不是把 broker 接入当研发终点。

前置条件：

- Reliability replay 全绿；
- PIT data / Experiment / Portfolio / Simulation 可重放；
- 足够长的 shadow 证据；
- 成本与归因可解释；
- Account Truth / reconciliation 无关键缺口；
- broker adapter 有独立 conformance/recovery 证据。

首个模式仍为：

```text
small capital
one account
allowlisted symbols/strategy
manual_each_order
one unresolved intent at a time
```

未知 outcome 不自动重提；每个 fill 必须进入 reconciliation/accounting。

扩大资本是新的人工 review，不由模型、策略或历史收益自动触发。

---

## 冻结与推迟

在对应前置 gate 完成前，不优先扩展：

- broker write adapter / session-bounded auto trading；
- 当前庞大的 broker/Account Truth 边界新功能；
- 当前 bespoke AI shadow-research workflow；
- full-market tick；
- 微服务/Kafka/Redis/Celery；
- 全量 Rust 重写；
- 与 Data -> Alpha -> Portfolio -> Shadow 无关的新页面。

已有安全/券商代码保留、测试继续跑，但进入 maintenance/frozen 状态。

## 接下来 10 个实施切片

1. 已实现：删除 read-side `previous_close_date` 猜测并补 replay。
2. 已实现基础投影：System Readiness；精确业务 gate 仍由各自 owner 评估。
3. 已实现：Overview/Portfolio 展示 last-good `as_of` + latest attempt failure。
4. 已加入：PRE_CLOSE/official-close 事故形态的确定性 SQLite replay；不包含私人生产导出。
5. 已加入：DB lock / partial batch / restart replay 和受影响标的范围测试。
6. 已接入 candidate 状态副本 gate；真实打包产物和生产服务生命周期验收仍是 release gate。
7. 已实现：durable `JobRun` contract，日历 loop 首先接入。
8. 已实现首条进程边界：`--data-worker`；其余 provider-heavy loops 待逐条迁移。
9. 已实现：`DatasetRef/DatasetManifest` contract 和 catalog seam。
10. 发布入口和确定性样本验证已实现；第一份真实 PIT historical-universe/daily dataset 的来源、可用时间和覆盖核验仍未完成。

第 10 步完成后，再开始 Alpha domain 实现。
