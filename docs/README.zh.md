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
- [券商执行边缘一致性验证](broker-execution-edge-conformance.zh.md) — default-closed 的 dry-run、submit、query、cancel 与幂等契约 fixture。
- [受控券商撤单](controlled-broker-cancellation.zh.md) — 精确签名的 one-shot 撤单、原子幂等与 query-only recovery。
- [券商适配器发布审查](broker-adapter-release-review.zh.md) — provider-neutral capability、威胁、部署、回滚、隐私与显式人工 acceptance 证据。
- [受控执行](CONTROLLED_EXECUTION_PLAN.zh.md) — 人工权限、运行门禁、恢复和资本扩容规则。
- [操作员批准的离线签名](operator-approval-signing.zh.md) — 本地 Ed25519 身份配置与不保存私钥的短时签名 mutation 复核。

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

账户策略贡献现在只投影持久化事实：成交必须已写入生产账本，并绑定同一精确估值快照与 ledger
cutoff 后才可展示收益。证据缺失或漂移会给出明确人工复核步骤；策略尚无成交时不会制造虚假
阻断。该投影不能联系 provider、写账本或授予执行与资本权限。

在 Strategy Lab 中，人工可以选择把精确的当前 strategy id 与这份 canonical contribution report
冻结进 AI 研究上下文。策略选择或 valuation/ledger identity 漂移会被拒绝；不完整的贡献证据继续
保持 blocked，不能启动权威分析。捕获不会重算收益，也不会自行调用模型。

Decision 的信号审计日志现在支持显式“决策后复盘”。系统先只读预览持久化的
signal/action/risk/order/fill 链和同一 canonical contribution report，再把人工结论绑定到该精确
fingerprint。只有具备成交、估值快照与 ledger cutoff 的完整绑定证据，已执行信号才能记录
“证据支持/不支持”；未执行或被风控阻断的信号使用独立的非财务结果。复盘记录具备幂等、
append-only 和审计重放，后续证据漂移会使旧结论显式失去当前绑定。该路径不调用 AI、不联系
provider、不修改财务事实，也不授予交易或资本权限。

Decision 还提供证据绑定的北极星“决策质量分数”。当前投影固定检查数据与 Account Truth 完整、
确定性风控、基准对照、日志和后续复盘身份；操作员可以针对精确每日 fingerprint 显式固化为
append-only、可重放的捕获。纵向覆盖只统计已显式捕获日期；该分数衡量过程证据，不衡量收益，
也不构成建议或权限。

Overview 的行情/净值复核只消费绑定 valuation snapshot、quote-set fingerprint、ledger cutoff/fingerprint 的 canonical 当前非零持仓投影；观察列表、大盘指数和已清仓事实不能抬高数量。
Market 会列出精确标的、原因和安全人工下一步；GET 不联系 provider、不写库。基金确认净值使用独立、请求幂等的 confirmation-only 可审计 ingestion；同一请求只重放持久化批次且不再次联系 provider，估值和前一日净值不能清除复核。只有更新且已确认的持久化证据生成新快照后才能清除复核项。

### Paper/Shadow 与 Operations

Operations 展示数据、计划、paper/shadow、OMS、对账、告警和恢复任务。Paper/shadow 可以
模拟订单、成交、费用和偏差，但不会提交真实券商订单或修改生产账本。

受控订单会把按时间排列的审计历史与操作员优先级分开。系统检查有界范围内全部持久化 journey；
较早的 unknown、prepared 或 open-order 结果不会被较新的低风险或已闭环旅程遮蔽。紧凑关注队列
为每一项显示唯一安全下一步，但它仍是只读投影，不能联系 provider，也不能修改交易、账本、风控、
kill switch 或任何权限。

### Account Truth 与对账

券商导入默认先 preview，再记录为独立 broker evidence。对账比较现金、持仓、订单、成交、
费用、税和成本基础；券商事实不能静默改写账本。请只使用本地真实文件，不要把账号或导出
提交到仓库。

### 受控执行

真实资金能力默认关闭。当前目标是一个 provider、逐单人工确认、明确资金边界、完整生命周期、
执行对账和显式入账。当前已能基于持久证据对完整成交、零成交撤单和部分成交后撤单执行单独签名
的精确终态 clearance；随后还需要另一份最终操作员签名，才可在单一事务内 exactly once 地把
实际 fills 写入生产账本。零成交撤单只记录 no-op posting。入账边界会重新核验 OMS、lifecycle、
券商证据、Account Truth 与 ledger identity，不能提交或撤销券商订单、联系 provider 或改变资本
权限。单独签名的 append-only correction 现在可仅根据 canonical replay 反向纠正一个 posting，
保留原交易与费用，并在完成后要求更新的 Account Truth import。该可选纠正现在可以从既有 order
journey 显式打开：选择 allowlisted 原因、复核确定性 delta、验证离线签名，再 exactly once 地追加
补偿事件；UI 不能输入现金、数量或价格。详细门禁和发布条件见 [路线图](ROADMAP.zh.md)。

Trading 还会只读展示精确 connector 的 20 日 soak、三阶段、恢复演练、Account Truth 和签名 owner acceptance 门禁；未配置时保持中性且不执行 promotion。
默认折叠、非提交的逐单证据复核只列出 canonical `manually_confirmed` OMS 候选，并从持久化事实解析最新精确资本评估、前序批次对账与网关验证，避免人工抄写三组
fingerprint。三分钟离线签名只能追加一条精确复核事实，不能 submit/cancel、联系 provider，或修改
OMS、ledger、risk、kill switch 与 capital authority；缺失、歧义、较新阻断或有界扫描不完整时
继续 blocked。
Automation Cockpit 与 Decision 投影同一批 persisted-only 候选；只有显式 alert scan 才为来源或
候选阻断写入幂等告警，ready 候选不伪装异常，且仅提供回到 Trading 的非提交下钻。

Execution reconciliation 到 terminal clearance、以及 clearance 到 posting 的步骤现在都可在各自
显式打开的操作员复核中完成：先查看 deterministic preview，再使用短时离线签名并执行最终确认；
未配置匹配可信公钥时保持禁用。Clearance 只记录精确终态与真实 fills、解除该订单的 cross-order
interlock，不写生产账本；posting 仍是另一份签名的 exactly-once 事务。两条路径都不能提交或撤销
券商订单、联系 provider 或改变资本权限。

当 controlled order 的最新精确持久化 lifecycle 仍为 open 或 partially filled 时，同一 journey
还可以准备 provider-neutral 的人工撤单证据包。它绑定 broker/client 双重订单 ID 与最新 lifecycle
fingerprint，并在导出时重新核验证据；结果只是供人工复制的 handoff。Karkinos 不联系券商，也不
提供 cancel 动作；只有之后导入的更新 lifecycle observation 才能把撤单结果当作事实。

对于 rejected controlled submission，同一 journey 还可准备已净化、带 fingerprint 的拒绝复核
资料，区分网关调用前本地阻断与网关明确拒绝，并明确禁止重试同一 intent 或 client order id。
资料仍仅供复制；单独的 append-only 人工复核会 exactly once 地记录复核人、精确 fingerprint、
处置与时间，并把旅程收敛为“不得重试；如仍需交易则新建 Decision”。重复/重启会复用原记录，
冲突复核人或证据 drift 会 fail closed。该审计写入不会查询、重试、提交、撤单，也不会修改 OMS、
ledger、risk、Account Truth、interlock 或任何权限。

Operations 的订单旅程现在以 canonical Account Truth 作为入账后的最终证据阶段：只有新鲜、完整、
无未解决差异且覆盖当前 ledger 的对账结果才会闭环；部分、降级、陈旧或早于 append-only correction
的证据继续进入人工复核队列。同一 import 的不可变 posting lineage 可以证明对应入账，但不能掩盖
之后无关的 ledger drift。该 GET 投影不会联系 provider，也不会修改 Account Truth、OMS、ledger、
risk、kill switch、broker 或资本权限。

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
