# Karkinos 实现记录

[English](IMPLEMENTATION_LOG.md) | [路线图](ROADMAP.zh.md) | [架构](ARCHITECTURE.zh.md) | [目标](KARKINOS_GOAL.zh.md)

本文记录发布级成果与验证证据，不是 commit 日记。详细代码历史、中间切片与精确 diff 属于 Git
commit 和 pull request。

## 当前基线

截至 2026-07-17，v0.2 至 v1.7 已完成。v1.8 control-plane 基础以及截至 Phase 1.18 的
AI-native research 基础已经实现。当前产品里程碑是[路线图](ROADMAP.zh.md)中的券商连接、逐单
受控 pilot。

最近完成的跨领域工作包括：

- 将 persisted observations 作为权威读取来源；
- 不可变 valuation snapshot 与 ledger identity；
- evidence-bound 策略贡献 v2，假设受控入账契约以不可变的
  `ledger_entries.source_ref = fill_id` 作为成交身份；关联成交只有在生产账本和估值快照可精确
  重放后才展示收益，读取路径不联系 provider、不写数据库，也不具备交易或资本权限；
- Holdings、Equity Curve、Overview 与 explainability 界面使用一致的 canonical daily performance；
- provider-neutral、evidence-bound 的 AI 研究、复核与 memory lineage，包括人工显式选择精确
  strategy id 后捕获 canonical、已入账且估值绑定的贡献报告，不重算收益，也不产生权限；
- evidence-bound 的人工决策后复盘，将一条持久化 signal/action/risk/order/fill 链与 canonical
  策略贡献快照一起冻结，拒绝证据漂移，以幂等、append-only、可重放方式记录，且不能修改财务
  事实或权限；
- 基于当前持久化 Decision 投影的 canonical 五维 Decision Quality Score，支持人工显式、幂等的
  每日捕获、tamper-evident replay 与 latest-per-day 纵向覆盖，不调用 AI，也不修改财务、风控、
  执行或权限状态；
- Overview 的数据复核范围只统计 canonical 当前非零持仓；观察列表、大盘指数与已清仓行情事实
  继续保留在 Market 或历史中，但不会抬高当前持仓复核数；
- persisted valuation v4 仍展示盘中基金估算值，但在同日确认净值持久化前不把它视为权威事实，
  Decision 与风控完整性门禁会 fail closed，而不会把估算值当作 live；
- 批量风控在估值或候选行情证据不完整时返回可解释的零写入阻断；合格批次的每条风控决策均绑定
  精确 persisted valuation snapshot 与 ledger cutoff，且不会创建订单、写账本或接触券商；
- 基于精确保存数据集、人工门禁和 allowlisted Formula DSL 的研究，由 canonical backtest engine
  以 next-bar 语义执行，不产生生产策略或交易权限副作用；
- fail-fast 分组运行配置、仅限环境变量的 TuShare/AI/通知凭证、已校验的
  Settings 写入契约，以及 Server 与旧 CLI 共用的 dotenv 选择路径；
- 已签名有界执行 policy、原子预算、runtime session、live gate、pause/replacement、submission
  interlock、lifecycle evidence、operator projection 与 capital-scaling review。
- canonical、persisted-only 的 controlled-order journey，将 submission、reconciliation、
  terminal clearance、ledger posting 与 append-only correction 串成一条证据链，并只给出安全
  人工下一步，不产生 read-side authority；v3 会检查有界范围内的全部持久化 intent，使较早的
  关键未完成旅程不会被较新的低风险或已闭环旅程遮蔽；
- Trading 侧 persisted-only 的当前逐单 dossier resolver：只列出 canonical
  `manually_confirmed` OMS 候选，选择最新精确 capital evaluation，解析唯一前序批次对账与网关
  验证引用，并支持离线签名的 append-only 复核；Web 不暴露 broker submit/cancel，也不要求人工
  输入三组财务证据 fingerprint；
- 显式打开的 ledger-posting 操作员复核绑定可信离线 proof 与 exactly-once apply；第二笔成交、
  posting 记录、完成事件三个 checkpoint 的确定性故障都会回滚全部财务与完成审计事实，并允许
  重启后的进程安全重试一次；私钥、broker action 与 authority change 仍留在 Web 路径之外；
- 单独签名的 unknown-submission 恢复复核：先绑定 persisted intent、精确 client order id、既有
  gateway result fingerprint、operator identity 与短时离线 proof，再原子放行一次 query-only
  gateway call；重复点击和服务刚重启后的重复操作不会再次查询，submit、cancel、ledger、risk、
  kill switch 与 authority 路径均不可用；仅允许以确定查询证据收敛既有 controlled intent/OMS
  结果状态；
- 面向精确 open/partial lifecycle 撤单 handoff 与终态拒绝复核的 provider-neutral 操作资料；
  两者都会重检 fingerprint drift 且不联系券商，拒绝复核还可追加一条绑定复核人的精确 no-retry
  审计事实，而不改变执行权限；
- provider-neutral adapter release manifest、append-only 人工 accept/reject/revoke 证据，以及
  live collector prepare/commit 的精确绑定；没有选择或注册真实 provider。
- provider-neutral deterministic conformance fixture、append-only report、精确 manifest/review
  绑定、最新结果优先与 prepare/commit 复核；不宣称支持真实 adapter。
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
- 当前证据逐单入口：先在服务端解析精确 append-only capital、前序批次与网关验证引用，再进入既有
  已签名、非授权的 dossier confirmation；
- gateway verification 与精确 evidence binding；
- session-start Account Truth、原子 account/symbol budget 与 rate limit；
- 已签名且会过期的 runtime session、live gate、pause、revocation 与 equal-or-narrower replacement；
- 默认关闭的 one-shot submission、unknown recovery 与 cross-order interlock；
- 已签名的 exact-terminal clearance，覆盖 full fill、no-fill cancel 与
  partial-fill-then-cancel，并包含 broker-neutral lifecycle ingestion；open partial fill 仍保持
  阻断，clearance 本身仍不能写入 ledger；
- 单独签名、provider-neutral 的 reconciled-ledger posting，在写事务内重新核验 OMS、intent、
  lifecycle、券商证据、Account Truth、valuation 与 ledger identity；精确 fills 在一个事务内只提交
  一次，partial-cancel 只写实际 fills，no-fill cancel 是显式零 entry posting；
- 单独签名且只能由 canonical replay 推导的 append-only correction；写事务会重新推导 plan，保留
  原交易与费用，拒绝 zero-fill、依赖交易、drift 或 tamper，并以 deterministic acceptance 绑定
  Ledger、Holdings、Allocation、Equity、Overview、Cockpit、Account State、realized P/L、valuation
  identity 与 Account Truth stale gate；
- 版本化 adapter capability/boundary manifest 与可撤销的 live collector release review gate；
- 与 release review 绑定并在 live collector prepare/commit 前复核的 deterministic local adapter
  conformance 证据；
- connector-scoped、latest-result-wins 的 soak promotion recovery-drill gate；
- 已持久化 operator projection 与 evidence-based scale review；
- 跨订单 operator attention 覆盖完整的有界 intent 集合，同时另行保留按时间最新的 journey
  用于审计；
- terminal-clearance 到 ledger-posting 步骤现可由操作员无需修改数据库完成；deterministic UI
  测试覆盖 canonical action eligibility、blocker、缺失身份、精确 request body 与无 broker call；
  本地 signer 拒绝覆盖密钥、强制私钥文件权限，并且只签署输入的 challenge payload，不执行网络 I/O。
- 单独的 terminal-clearance 复核只在 canonical `preview_terminal_clearance` action 下出现，绑定精确
  persisted reconciliation run、Account Truth import、lifecycle/broker-evidence fingerprint、终态数量与
  fills；只有另一份离线签名通过后才记录终态并解除 interlock，全程无需手改数据库。
- canonical query-only journey action 现提供无需改数据库的 unknown-outcome 恢复复核；旧的无签名
  naked POST 不再注册。Preview 不联系 provider，apply 必须携带精确 recovery fingerprint、匹配的
  离线 Ed25519 proof 与最终确认，而且数据库会在任何外部调用前先原子记录 query claim。
- canonical open-order 与 rejected-order journey action 现提供无需改数据库的资料包，只导出带
  fingerprint 的持久化 handoff；rejected journey 还可单独追加一条 exactly-once 的复核人/时间/
  fingerprint 确认并收敛为不得重试。两者都不能 query/retry/submit/cancel、修改 OMS/ledger/
  authority、解除 interlock 或证明后续券商结果。

M4 当前逐单 dossier 的假设与风险记录：

- 与精确 OMS order fingerprint 或 manual-confirmation fingerprint 匹配的最新 capital evaluation
  是权威证据，即使它已阻断也绝不回退到旧 pass。必须恰好存在一条有效前序批次引用与一条网关验证
  引用；格式错误、歧义、缺失或扫描截断都 fail closed。
- 确定性验证覆盖无需操作员输入 fingerprint 的当前解析、最新阻断优先、歧义引用、精确 replay、
  append-only 幂等、OMS 不变、严格请求 schema、面板折叠时零读取、empty/blocked 状态、
  Automation/Decision ready/blocked 下钻、来源漂移/失败、离线签名，以及不存在 submit/cancel 请求。
- 风险影响为 low：Automation/Decision 仅增加 fail-closed 投影和 Trading 链接；列表与 preview
  只读持久化事实，最终写入仍是既有逐单 confirmation 审计事实，
  且不具备授权能力。OMS、ledger、Account Truth、risk、kill switch、provider、submit、cancel 与
  capital authority 均不改变；没有选择、注册或宣称支持任何 provider/adapter。

M4 非授权操作资料包的假设与风险记录：

- canonical source list 仍按时间从新到旧，但人工关注项先按严重度排序，同严重度内优先较旧项。
  Unknown、prepared 与 open-order 证据优先于 reconciliation、clearance、posting 和 Account Truth
  后续复核；已完成拒单复核不进入关注队列。测试覆盖“较新 rejected journey 与较早 unknown
  outcome 并存”，并证明 query-only、禁止重提的操作仍保持第一优先级。
- 风险影响为 medium：该变更会改变 Automation Cockpit 与 Decision/Operations 首先展示的人工
  复核项，但它仍是只读投影；没有新增 provider query、submit、cancel、OMS/ledger mutation、
  risk decision、kill-switch change 或 authority change。

- 假设 preview 时最新的 exact-identity 持久化 lifecycle observation 是当前可用的订单证据；操作员
  仍须独立核对 broker/client id 与剩余数量；拒绝复核只承认净化后的持久化结果，artifact 绝不构成
  retry 权限，审计记录只绑定精确 fingerprint。
- 确定性验证覆盖 open/partial、本地/明确拒绝、歧义阻断、restart-stable fingerprint、重复导出、
  exactly-once 并发/重启复用、冲突复核人、事务内 drift、严格 route、UI acknowledgement，以及
  不存在 query/submit/cancel/ledger 调用。
- 风险影响为 low：只写入专用 append-only 复核审计表；OMS、ledger、Account Truth、risk、kill
  switch、capital authority 与 unresolved-submission interlock 全部保持不变。

M4 query-only recovery 的假设与风险记录：

- 假设注册的 edge gateway 按 persisted idempotent client order id 执行只读、有界的 broker order
  query。查询失败或仍不确定时继续保持 `submission_unknown`，绝不授权重提。持久化的 30 秒 claim
  窗口会阻止重复点击与刚重启后的重复查询；进程丢失或 gateway 断连后，只能等窗口结束并重新签名
  才能再次查询。
- 确定性验证覆盖过早 preview 阻断、精确签名 domain、重复 apply、restart、query failure、
  definitive not-found、成功恢复、audit claim、route schema、Web 精确 request body，以及不存在
  submit/cancel/ledger 调用。
- 风险影响为 medium：这会对未知执行状态增加一次显式外部读取，但不能修改生产账本、资本或执行
  权限，也绝不调用 broker submit/cancel。查询结果会先脱敏，再通过既有 controlled intent/OMS
  result transition 持久化；仍有歧义时继续 fail closed。

M4 terminal-clearance UI 的假设与风险记录：

- Operator journey 负责提供可操作的 submission 与 reconciliation identity；Web 不选择任意财务
  事实，也不重算数量、费用、终态或 clearance eligibility。只有 full fill、no-fill cancel 与
  partial-fill-then-cancel 可进入 clearance；open 或冲突证据继续由 canonical service 阻断。
- 验证包括 exact preview、challenge、proof、apply 序列的 deterministic component fixture，以及
  Node 24 全量 Web test、format、production build、后端 safety suite 与 CI。
- 执行证据层风险为 high：clearance 会记录真实 fills、把 OMS 转到已复核终态，并解除 cross-order
  interlock。既有写事务会重新核验最新 reconciliation、lifecycle、Account Truth、order、intent、
  signature 与 fingerprint；UI 不能提供财务数值、写 ledger、联系 provider、提交/撤单或改变权限。

M3 纠正的假设与风险记录：

- 非空 controlled posting 表示同一标的的真实 fills；零 entry cancel 是可审计 no-op，没有可反向的
  财务事实。Correction 只用于本地 ledger recovery，不替代券商事实，因此完成后必须重新导入更新的
  Account Truth。
- 验证命令为 `uv run python -m pytest`、`uv run python -m pytest -m trading_safety`、CI 同款
  coverage，以及在 `web/` 下使用 Node 24 执行 `npm run test`、`npm run format:check` 与
  `npm run build`。
- 风险影响为 high：canonical ledger projector 会影响 cash、position、cost、realized P/L、equity、
  Overview、Cockpit、Account State 与风控输入。缓解措施包括拒绝 operator 输入财务数值、通过
  canonical replay 推导买卖两类 reversal、绑定 valuation/ledger/Account Truth identity、在写锁内
  重算、每次重放核验 before-state、保留历史，并且不授予 OMS、broker、risk、kill switch、
  AI/strategy 或 capital 能力。

M3/M4 纠正操作员旅程的假设与风险记录：

- Correction 只是在非空 posting 已应用后、人工确认错误时使用的可选 recovery，不是日常默认下一步。
  操作员必须选择一个后端 allowlisted reason；Web 不能提交 cash、quantity、price、cost、fee 或
  ledger-entry delta。Preview 与 apply 继续只调用 canonical replay 服务。
- 操作员流程固定为 preview → 3 分钟离线 Ed25519 challenge → detached proof 验证 → 显式
  append-only acknowledgement → exactly-once apply。缺少可信公钥、canonical blocker、fingerprint
  漂移、重复纠正或 Account Truth 陈旧都会使 apply 禁用或被拒绝；成功后会失效所有受影响的
  persisted projection 查询，并明确要求重新导入 Account Truth。
- 风险影响为 high，因为最终签名动作会修改生产账本。缓解措施仍由后端拥有：事务内 replay 与
  identity 重检、append-only 历史、精确 posting scope、禁止任意财务输入、禁止 provider contact，
  且不授予 OMS、broker submit/cancel、risk、kill switch、strategy/AI 或 capital authority 能力。

行情复核修复的假设与风险记录：

- 不假设默认数据源支持全部资产类别。TuShare latest quote 继续只覆盖股票与开放式基金；指数刷新会
  直接路由到已经注册的 AKShare 边缘数据源。东方财富接口不可用时优先使用 AKShare 官方文档列出的
  新浪指数接口，但只有同一适配器的日线接口给出已完成交易日后，才发布持久化收盘价；没有可信
  as-of 的盘中行继续保持 provisional/stale。
- 确定性验证覆盖能力感知的来源选择、有界超时、上海时区 15:00 完成边界、昨收/涨跌推导、Sina
  代码前缀、Eastmoney fallback 与明确 quote-source provenance。本机验收另外通过可审计的手工刷新
  批次验证 399001、399006，并确认两者持久化 as-of 均为 `2026-07-16T15:00:00+08:00`。
- 行情证据边界的风险影响为 medium：该变更可以发布估值输入，但不能修改 ledger、OMS、risk、
  kill switch、capital 或 broker 权限。缺少时间、交易时段未完成或 provider 失败时继续 fail
  closed。基金盘中估值继续明确标记为 provisional；收盘确认只接受目标交易日已经发布的
  confirmed NAV，旧日期净值不能覆盖当天估值，也不能解除复核门禁。
- Overview 复核队列与 Operations 塔台现在消费同一 canonical daily-operations projection；旧的
  Overview 投影只保留为滚动升级 fallback，不能覆盖当前 Operations 响应。

剩余发布工作由路线图负责：一个真实 adapter、只读 soak、真实 cancel/unknown recovery、签名式
submission UI、更广的端到端/provider fault injection 与真实证据验收、operator journey 的其余
步骤与受控逐单 pilot。

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
- 使用 `karkinos.account_strategy_contribution.v2` 替换 latest-quote 估算：只有已写入生产账本且
  绑定同一持久化估值快照的成交才能展示收益；证据缺失、陈旧、漂移或策略库存来源不完整时
  fail closed，并给出明确人工下一步。
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
