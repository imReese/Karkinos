# Karkinos Codebase Guide

[文档入口](README.md) | [目标](GOAL.md) | [目标架构](ARCHITECTURE.md) | [实施计划](PLAN.md)

本文回答两个问题：当前代码的结构性债务在哪里，以及如何在不 big-bang rewrite 的前提下迁移到目标架构。

## 1. 当前代码审计

值得保留的基础：

- `core/` 已有 clock/event/types 基础；
- `data/` 已有 typed market identity、calendar、replay、daily ingestion；
- `analytics/` 已有 dataset snapshot、PIT membership、OOS、multiple testing、holdout 等研究资产；
- `backtest/` 已是 event-driven simulation 雏形；
- `execution/` 已有 commission/slippage/paper evidence；
- Financial facts、valuation publication、ledger、risk、reconciliation 已有大量事务/幂等测试；
- immutable release + research worker 已证明少量多进程运行是可行的。

主要结构性债务：

1. `server/services/` 过于扁平，正在成为“所有 use case 的默认目录”。
2. API lifespan 仍直接启动多个 scheduler/automation/background loop，故障域过大。
3. `data/store.py` 把 SQLite market bars 当 primary store，同时写 Parquet mirror；不适合未来全市场研究数据规模。
4. `analytics/` 混合 research analytics 与 release/acceptance governance。
5. `strategy/` 把 signal/strategy 放在研究中心，而目标架构需要 Alpha/Forecast/Portfolio 分层。
6. `backtest` 仍有默认批准 risk 的 compatibility glue，和真实 order path 语义未完全统一。
7. Paper OMS、broker lifecycle、server OMS/persistence 存在多套状态模型的风险。
8. `account_truth/` 与 broker-controlled-execution 代码规模已经远超当前 edge research 主线，应冻结扩张。
9. `domain/` 同时容纳 bar/fill/order/portfolio/position，容易继续成为 generic dumping ground。
10. `AppDatabase` 仍是广泛 compatibility facade。
11. `tools/check_python_architecture.py` 只保护部分 package，`server`/`analytics` 仍缺目标 DAG 约束。

## 2. 目标 bounded contexts

最终 conceptual ownership：

| Target context | Owns |
| --- | --- |
| `core` | ids、clock、events、shared value primitives |
| `market` | calendar、instrument reference、provider normalization、PIT datasets |
| `research` | features、Alpha/Model specs、experiments、forecasts、diagnostics |
| `portfolio` | ensemble、risk/exposure model、construction、target、rebalance plan |
| `accounting` | ledger、lots、positions、valuation、PnL、fees、Account Truth/reconciliation |
| `execution` | order/fill contracts、OMS lifecycle、sim/paper/broker adapters |
| `risk` | pre-trade/runtime authorization policy |
| `simulation` | deterministic backtest/replay using shared market/portfolio/execution/accounting semantics |
| `ops` | jobs、leases、scheduler、readiness、incidents、release/runtime state |
| `ai` | research assistants over explicit research ports; never authority |
| `app` | commands、queries、use-case orchestration、API composition |
| `adapters` | external market/model/broker/file implementations |
| `web` | presentation only |

这些是 ownership 目标，不要求立刻创建全部目录。

## 3. 目标依赖方向

业务层不依赖 FastAPI/React/SQLite implementation：

```text
core
├── market
├── accounting
└── execution contracts

market -> research -> portfolio
accounting + market + portfolio + execution contracts -> risk
research + portfolio + accounting + execution + risk -> simulation
research -> ai
all domain contexts -> app composition
ports <- adapters
ops coordinates jobs but does not own financial formulas
```

外层可以依赖内层；反向依赖通过 Protocol/port 实现。

## 4. 当前 -> 目标映射

| Current | Migration direction |
| --- | --- |
| `data/` | 逐步成为 `market`，先引入 DatasetCatalog/Parquet-primary seam |
| `analytics/` research files | 迁入 `research` ownership |
| `analytics/acceptance*` | 迁到 `quality/acceptance` 或 `tools/acceptance`，不得污染 research API |
| `strategy/` | compatibility；新 Alpha/Forecast 不再放这里 |
| `backtest/` | 演进为 `simulation` |
| `domain/portfolio*` | 拆向 `portfolio` / `accounting` owning context |
| `execution/` | 保留并统一 Order/Fill lifecycle |
| `account_truth/` | 收敛到 accounting/reconciliation + broker adapters；暂不扩功能 |
| `server/persistence/` | 继续作为迁移期 implementation；按 owning context 暴露窄 repository/UoW |
| `server/services/` | 新代码按 context 组织，不再增加无分类平铺文件 |
| `server/projections/` | 继续保持 provider-free read model，再逐步迁到 app/query ownership |
| `notification/` | 归 Operations adapter |
| `AppDatabase` | compatibility facade，逐步让 callers 改用窄 ports |

## 5. Persistence 规则

- Financial transaction 必须在一个明确 UnitOfWork 内原子完成。
- 新 repository 不返回“万能 dict”作为长期公共 API；在 boundary 稳定后使用 typed value/result。
- Dataset bytes 不进入 `app.db`。
- Dataset/artifact 用 immutable content ID；catalog 只保存 manifest/pointer。
- 跨 lake/catalog/control 不实现分布式 transaction；先写 immutable artifact，再 publish reference。
- Schema/fingerprint/idempotency 的任何变化都必须有 migration/replay test。

## 6. Application / process 规则

- Route 只做 HTTP validation、auth/context、response mapping。
- Use case 进入 app/service context，不允许 route-to-route import。
- Query provider-free / zero-write。
- Command typed / idempotent。
- 长期 background work 进入 durable JobRun，不在 API lifespan 里无身份运行。
- Worker 通过 durable state 协作，不共享 in-memory truth。

## 7. Simulation / trading 规则

新功能不得继续强化 `Signal -> Order` 的直接耦合。

目标链：

```text
Forecast
-> PortfolioTarget
-> RebalancePlan
-> OrderIntent
-> RiskDecision
-> Order
-> Fill
-> Accounting
```

Paper/live 不再各自发明 OMS 状态。Adapter 只翻译外部协议，canonical lifecycle 属于 `execution`。

## 8. 重构规则

1. 先写 characterization/replay test，再移动代码。
2. Structural move 与金融语义 change 分 PR。
3. 新代码依赖 narrow port，不依赖 God facade。
4. 先新增 target module + compatibility adapter，再迁 caller，最后删除旧实现。
5. 不做大规模 import-only rename PR。
6. 禁止新的 generic `utils.py` / `helpers.py`。
7. 每稳定一个 context，就把依赖方向加入 executable architecture check。
8. Broker/AI legacy code可维护修 bug，但在 PLAN 解冻前不继续扩 architecture surface。

## 9. 语言策略

Python 保持主语言；TypeScript/React 保持 Web。

优先顺序：

```text
better semantics
-> vectorized Python
-> Arrow / Polars / DuckDB
-> profiling
-> native/Rust only for measured hot paths
```

Rust 未来最多作为 simulation/optimizer/data kernel，不成为新的 orchestration 层。

## 10. 完成 Architecture Migration 的定义

不是“目录都换了名字”，而是：

- API 不再承载 provider-heavy/background 业务；
- 新 research 只依赖 DatasetRef/Experiment contracts；
- bulk market data 不再以 SQLite row store 为主；
- Alpha、Portfolio、Order、Accounting 是独立 ownership；
- paper/backtest/live 共享 execution/accounting semantics；
- `AppDatabase` 只剩 compatibility 或很薄的 composition facade；
- executable dependency rules覆盖主要 contexts；
- production replay 能证明迁移未改变金融语义。
