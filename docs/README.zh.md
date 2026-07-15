# Karkinos 中文文档

Karkinos 是面向中国市场的个人量化投研与交易平台。本页是中文文档入口，不重复维护完整的
产品说明、API 清单或实现日志。

[返回项目首页](../README.md) | [English documentation](README.en.md)

## 快速开始

要求：Python 3.12+、Node.js 24.x、`uv`，可选 Docker。

```bash
uv sync --extra server --extra dev --frozen
npm ci --prefix web
npm --prefix web run build
cp config.example.json config.json
cp .env.example .env
uv run python -m server --check-config
uv run python -m server --no-live
```

默认产品入口为 `http://127.0.0.1:8000`。

主要检查：

```bash
uv run python -m pytest
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

更完整的运行参数、通知、数据目录和本地配置见配置参考：
[中文](config-reference.zh.md) / [English](config-reference.en.md)。

## 文档导航

### 核心文档

- [产品目标](KARKINOS_GOAL.zh.md) — 产品北极星、长期承诺和不可跨越的边界。
- [路线图](ROADMAP.zh.md) — 当前优先级、里程碑、验收标准和开发顺序。
- [架构](ARCHITECTURE.zh.md) — 系统分层、核心流程、权限边界和失败语义。

### 操作指南

- [Account Truth 导入与复核](account-truth-import.zh.md) — 预览、证据暂存、对账和人工处置。
- [收益与成本口径](return-accounting.zh.md) — 今日、浮动和已实现收益的统一计算规则。
- [券商订单生命周期](broker-order-lifecycle-ingestion.zh.md) — 只读 lifecycle evidence 与 collector ingestion。
- [券商适配器一致性验证](broker-adapter-conformance.zh.md) — 本地 deterministic fixture、精确
  release 绑定与 latest-result-wins 门禁。
- [券商适配器发布审查](broker-adapter-release-review.zh.md) — provider-neutral capability、威胁、
  部署、回滚、隐私与显式人工 acceptance 证据。
- [受控执行](CONTROLLED_EXECUTION_PLAN.zh.md) — 人工权限、运行门禁、恢复和资本扩容规则。

### 参考资料

- [配置参考](config-reference.zh.md) — 本地运行、数据源、费用、connector 与 authority 字段。
- [实现记录](IMPLEMENTATION_LOG.zh.md) — 已完成版本的发布级成果和验证归属。
- [外部项目参考](BENCHMARKS.zh.md) — 可借鉴的设计主题及禁止形成的产品绑定。

## 日常工作流

### 研究与回测

在 Strategy Lab 选择注册策略、标的或 universe、日期范围和参数。保存的实验会绑定数据快照、
参数、成本、OOS、风险、限制和证据状态。参数 sweep 和策略 comparison 必须复用冻结的数据
输入，结果只能作为研究证据。

### 每日决策

Decision 与 Daily Trading Plan 汇总组合、行情、策略、信号、风险、Account Truth 和
paper/shadow 证据，输出 buy、sell、hold、rebalance、no-action 或 review-required。任何阻断
都应展示原因和下一步，而不是生成看似确定的建议。

### Paper/Shadow 与 Operations

Operations 展示数据、计划、paper/shadow、OMS、对账、告警和恢复任务。Paper/shadow 可以
模拟订单、成交、费用和偏差，但不会提交真实券商订单或修改生产账本。

### Account Truth 与对账

券商导入默认先 preview，再记录为独立 broker evidence。对账比较现金、持仓、订单、成交、
费用、税和成本基础；券商事实不能静默改写账本。请只使用本地真实文件，不要把账号或导出
提交到仓库。

### 受控执行

真实资金能力默认关闭。当前目标是一个 provider、逐单人工确认、明确资金边界、完整生命周期、
执行对账和显式入账。详细门禁和发布条件见[路线图](ROADMAP.zh.md)。

### AI 研究

AI workflow 只能读取已持久化、证据绑定的只读投影。模型输出是带引用的非权威研究，不能成为
账户事实、风控结论、资本授权、OMS transition 或券商指令。

公式研究从已保存的 canonical backtest 和精确数据快照开始。模型只能提出候选假设；人工选择
后，由 allowlisted Formula DSL 和既有 BacktestEngine 计算，最终仍需人工接受、修订或拒绝，
且不会注册生产策略或生成交易权限。

## 隐私与安全

- 不提交券商密码、API Key、真实账号、账户导出、运行数据库、日志或包含私密信息的截图。
- `config.json` 不接受 TuShare/AI 凭证；密钥只放在未提交的 `.env` 或进程环境变量中。
- 不把回测或 AI 报告解释为投资建议或收益保证。
- 缺失、陈旧、partial、ambiguous 或 conflicting 的财务证据必须 fail closed。
- Strategy、AI、scheduler、GET 和告警路径不能获得 submit/cancel 权限。

## 文档维护

本页只作为中文入口。新增说明前先选择唯一归属：产品边界写入 Goal，当前计划写入 Roadmap，
稳定设计写入 Architecture，配置和数据格式写入专题文档，已完成证据写入 Implementation Log。
