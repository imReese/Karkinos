# Karkinos 实现记录

[English](IMPLEMENTATION_LOG.md) | [路线图](ROADMAP.zh.md) | [架构](ARCHITECTURE.zh.md) | [目标](KARKINOS_GOAL.zh.md)

本文记录发布级成果与验证证据，不是 commit 日记。详细代码历史、中间切片与精确 diff 属于 Git
commit 和 pull request。

## 当前基线

截至 2026-07-15，v0.2 至 v1.7 已完成。v1.8 control-plane 基础以及截至 Phase 1.18 的
AI-native research 基础已经实现。当前产品里程碑是[路线图](ROADMAP.zh.md)中的券商连接、逐单
受控 pilot。

最近完成的跨领域工作包括：

- 将 persisted observations 作为权威读取来源；
- 不可变 valuation snapshot 与 ledger identity；
- Holdings、Equity Curve、Overview 与 explainability 界面使用一致的 canonical daily performance；
- provider-neutral、evidence-bound 的 AI 研究、复核与 memory lineage；
- 基于精确保存数据集、人工门禁和 allowlisted Formula DSL 的研究，由 canonical backtest engine
  以 next-bar 语义执行，不产生生产策略或交易权限副作用；
- fail-fast 分组运行配置、仅限环境变量的 TuShare/AI/通知凭证、已校验的
  Settings 写入契约，以及 Server 与旧 CLI 共用的 dotenv 选择路径；
- 已签名有界执行 policy、原子预算、runtime session、live gate、pause/replacement、submission
  interlock、lifecycle evidence、operator projection 与 capital-scaling review。
- provider-neutral adapter release manifest、append-only 人工 accept/reject/revoke 证据，以及
  live collector prepare/commit 的精确绑定；没有选择或注册真实 provider。
- connector-scoped soak recovery evidence：无 scope、无关或混合 connector 的 drill 不能满足
  promotion，同 scope 的最新失败会使旧 pass 与其签名 dossier acceptance 失效。

本文故意不维护历史测试总数，因为每次变更都会使其过期。CI artifact 与 acceptance-audit export
负责当前数量和证据。

## 发布历史

### v1.8 — 资本有界的受控执行

状态：基础已实现；券商连接 pilot 进行中。

已实现基础：

- 有版本的 capital policy 与 append-only evaluation evidence；
- 独立的只读 evidence connector 与 execution gateway 身份；
- 已签名的逐单和 session attestation；
- gateway verification 与精确 evidence binding；
- session-start Account Truth、原子 account/symbol budget 与 rate limit；
- 已签名且会过期的 runtime session、live gate、pause、revocation 与 equal-or-narrower replacement；
- 默认关闭的 one-shot submission、unknown recovery 与 cross-order interlock；
- 已签名的 exact-full-fill clearance 与 broker-neutral lifecycle ingestion；
- 版本化 adapter capability/boundary manifest 与可撤销的 live collector release review gate；
- connector-scoped、latest-result-wins 的 soak promotion recovery-drill gate；
- 已持久化 operator projection 与 evidence-based scale review。

剩余发布工作由路线图负责：一个真实 adapter、只读 soak、完整 partial/cancel/unknown recovery、
对账后 ledger posting、operator journey 与受控逐单 pilot。

### v1.7 — 受控券商 Bridge 基础

- 增加 manual ticket preview、export、dry run 与 operator evidence。
- 增加只读 connector capability 与 health contract。
- 增加 execution reconciliation 与 broker-evidence handoff。
- 继续关闭生产券商提交、取消与自动账本修改。

### v1.6 — Operations Center 与 Paper/Shadow Runbook

- 增加持久化的定时与操作员触发运行。
- 增加确定性 paper/shadow 订单、成交、成本、偏差、复核、重试与限制。
- 增加 Operations、Decision、Overview 与 Trading 可见性、告警和恢复任务。

### v1.5 — 每日交易计划与组合构建

- 增加候选池、目标权重、order intent、成本、batch risk 与 Today's to-dos。
- 保留 no-action、review-required 与 manual-confirmation 结果。

### v1.4 — 归因与成本基础保真

- 增加订单、成交、费用、税、已实现/未实现 P/L 与 unattributed effects 的策略贡献证据。
- 对齐券商费用、成本基础、proceeds 与公开账本格式。

### v1.3 — 专业决策工作流

- 将组合、行情、信号、研究、风控、Account Truth 与运营证据统一到每日和盘中决策。
- 展示明确的 action、blocker、explanation 与 next-step state。

### v1.2 — 券商证据 Connector

- 增加券商证据导入、staged facts、capability/health status 与 reconciliation inputs，不授予券商
  写权限。

### v1.1 — Paper Broker 与 OMS

- 增加 canonical order identity、transition、idempotency、paper fill，以及
  paper/shadow/manual-ticket 模式。

### v1.0 — 策略 Runtime 基础

- 增加注册策略执行、assignment、evidence binding 与生产安全的扩展边界。

### v0.9 — 数据平面与行情可靠性

- 增加 quote-fetch run、source/cache metadata、stale reason、manual refresh 与确定性
  data-health evidence。

### v0.8 — 策略分配与归因

- 增加 account/symbol strategy assignment、lifecycle state、downstream reference 与 attribution，
  不把人工交易伪装成策略交易。

### v0.7 — Account Truth Review Center

- 增加导入/对账列表、逐项复核、score explanation，以及 Decision/promotion 降级或阻断。

### v0.6 — Account Truth 与对账

- 增加 canonical broker statement import preview、staged evidence、duplicate detection、
  reconciliation、review state 与 Account Truth score。

### v0.5 — 研究证据强化

- 增加 versioned evidence bundle、data-quality gate、更强 OOS 分析、参数稳定性、中国市场假设与
  promotion readiness。

### v0.4 — Strategy Lab

- 增加 typed strategy registry 与 extension、通用参数、Web 回测、冻结数据集、sweep、comparison
  与 after-cost/OOS report。

### v0.3 — 每日与盘中决策平台

- 增加每日/盘中 decision API 与 Web 界面，提供明确 action 与 evidence bundle。

### v0.2 — Profit Discipline MVP

- 完成第一个从确定性数据到回测、信号、风控、dashboard/journal 的操作闭环。

## 验证归属

- 当前自动化证据：CI artifact 与 `scripts/export_acceptance_audit.py`。
- 机器可读的完成状态来源：`analytics/` 下的 acceptance-audit registry。
- 详细变更历史：Git commit 与 pull request。
- 当前优先级和发布门禁：`ROADMAP.zh.md`。

里程碑完成时，只在本文增加简短的发布级结果。不要复制完整测试输出、实现 diff、逐阶段安全
声明或每个中间 commit。
