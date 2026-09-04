# Karkinos Codebase Guide

[文档入口](README.md) | [目标](GOAL.md) | [架构](ARCHITECTURE.md) | [当前计划](PLAN.md)

Karkinos 保持 **Python modular monolith**。目录拆分服务于 ownership，不服务于“看起来像微服务”。

## Package ownership

| Location | Owns |
| --- | --- |
| `core/` | clocks、events、基础类型 |
| `domain/` | canonical portfolio / instrument rules |
| `data/` | market-data contracts、providers、ingestion、replay |
| `strategy/` | legacy strategy definitions and extension registry |
| `backtest/` | deterministic backtest engine |
| `risk/` | deterministic risk policy |
| `execution/` | broker-neutral execution contracts / simulation |
| `account_truth/` | broker evidence and reconciliation contracts |
| `analytics/` | research/acceptance analysis, never account authority |
| `server/routes/` | HTTP validation and response mapping |
| `server/services/` | application use cases and orchestration |
| `server/persistence/` | SQLite repositories, migrations, units of work |
| `server/projections/` | canonical read projections, no side effects |
| `server/app.py` | process composition and lifecycle |
| `web/src/app/` | router, providers, shell |
| `web/src/features/` | feature pages, queries, commands, local UI |
| `web/src/shared/` | feature-neutral UI / API infrastructure |

未来的 `alpha/`、portfolio-construction 和 columnar dataset modules 应按上述 ownership 原则新增，不塞进 `server/routes` 或 generic `utils`。

## Dependency direction

基础包不能依赖 Web/FastAPI/persistence：

```text
core
  ^
domain
  ^
data / risk / execution
  ^
strategy / backtest / alpha
  ^
server application composition
```

实际受保护边界由 `tools/check_python_architecture.py` 和对应 tests 执行。文档图不能覆盖可执行规则。

## AppDatabase

`AppDatabase` 目前仍是 compatibility facade。新 persistence 应优先进入命名清晰的 repository/UoW；旧调用方逐步迁移后再让 facade 变薄。

不要一次性删除 `AppDatabase` 或大搬目录。跨 context 的原子流程必须在新的 unit-of-work 能证明同样 idempotency/rollback 语义后再迁移。

## Market Data / Financial Control

代码组织应逐步反映 [ARCHITECTURE.md](ARCHITECTURE.md) 的双平面：

- 高容量历史/研究 dataset 属于 Market Data Plane；
- ledger、valuation、risk、OMS、authority 和 audit 属于 Financial Control Plane。

不要为了方便把新的大规模时间序列继续塞进 `app.db`。

## Process boundaries

API、research worker 和未来 heavy market-ingestion worker 可以是独立进程，但仍属于同一个产品和代码库。

只有外部故障域、资源隔离或生命周期确实要求时才增加进程；不要为每个 domain 建服务。

## Refactoring rules

1. 结构变化前先写 characterization/replay tests。
2. 先移动 ownership，再改语义；不要在同一个 slice 同时重构和改金融公式。
3. 新代码依赖窄接口，不依赖 God facade。
4. 一个边界稳定后加 executable dependency rule。
5. 禁止新的 `utils.py` / `helpers.py` catch-all。
6. route 不拥有可复用金融计算；projection 不做外部 side effect。
7. 数据库 schema、fingerprint bytes、ordering、idempotency keys 和 API fields 的变化必须单独说明。
8. 不因为文件大就自动加层；按 change reason 和 ownership 拆。

## Language policy

Python 保持主语言。性能问题先用 profiling、NumPy/Arrow/Polars/DuckDB 解决；只有有明确 benchmark/SLO 证据时才下沉 Rust/native kernel。

不接受“重写语言”作为修复业务状态机、时间语义或数据 ownership 问题的替代方案。
