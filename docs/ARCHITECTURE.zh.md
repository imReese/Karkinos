# Karkinos 架构

[English](ARCHITECTURE.md) | [目标](KARKINOS_GOAL.zh.md) | [路线图](ROADMAP.zh.md) | [受控执行](CONTROLLED_EXECUTION_PLAN.zh.md)

## 架构原则

1. **先持久化事实，再展示。** API、Web、报告、告警与 AI 读取 canonical persisted
   projections，不独立重建财务真相。
2. **先有证据，再有权限。** 信号、报告、复核或批准都不是执行权限；只有专门门禁可以明确
   授予有界能力。
3. **Fail closed。** 缺失、过期、partial、ambiguous、conflicting 或 drifted 的证据会阻断
   受影响的操作。
4. **提议与修改分离。** Preview、review、approval、apply 与 reconciliation 是具有不同身份的
   独立命令。
5. **外部效果幂等。** 券商提交、取消、证据采集、对账与账本入账使用 canonical fingerprint
   和持久化 claim。
6. **人工监督扩展。** Runtime authority 可以自动过期、暂停、收窄或撤销，但不能自行放宽或
   续期。

## 系统分层

```text
Web UI / CLI
    |
FastAPI routes 与 application services
    |
Research | Decision | Risk | Operations | OMS | Reconciliation
    |
Canonical evidence、audit、ledger 与 valuation stores
    |
Market providers | local files | model edge | broker edge
```

### 展示层

React/Vite 产品界面与 CLI 承载操作员工作流。展示代码可以格式化 canonical values 与组织
导航，但不拥有组合计算、风控决策、权限或券商状态。

### 应用服务层

FastAPI routes 校验请求并委托给 application services。应用服务负责幂等性、事务边界、编排与
响应投影。GET 路径只读：不得隐式初始化 schema、刷新 provider、恢复 workflow 或联系券商。

### 领域层

核心领域彼此独立：

| 领域 | 负责内容 |
| --- | --- |
| 行情数据 | bars、quotes、cache/source health、snapshots、freshness |
| 组合与账本 | 现金、持仓、lots、成本基础、财务事件 |
| 研究 | 策略、实验、证据包、promotion readiness |
| 决策 | 每日候选、目标权重、阻断项、解释 |
| 风控 | 交易前与运行时风控决策、kill-switch 状态 |
| Operations | 定时运行、paper/shadow、告警、复核任务 |
| OMS | canonical order identity、生命周期、转换、成交 |
| 对账 | 券商/账户/订单/成交一致性与复核 |
| 受控执行 | 有界权限、预算、session、提交门禁 |
| AI 研究 | 证据上下文、workflow、artifact、review、memory lineage |

### 证据与持久化

SQLite 保存 append-oriented 的财务、运营、执行与 AI 审计事实。Canonical fingerprint 绑定
输入，使重启、重复处理、漂移检测与重放保持确定性。

外部 provider 都是边缘组件。其运行时响应只有经过校验并持久化后才成为证据，绝不会隐式成为
权限。

## Canonical 财务身份

一个估值视图绑定：

- valuation snapshot id 与 fingerprint；
- 已确认 quote/NAV observations 与 previous-close baselines；
- ledger cutoff 与 ledger fingerprint；
- source、cache、freshness 与 data-quality 证据；
- 在适用时明确标记 estimated 或 unavailable。

Holdings、Equity Curve、Overview、Decision、Account Truth 与 AI evidence 在声称描述同一时点
时必须引用同一个 canonical identity。历史重建不能使用未来价格或不相关的当前报价。

`karkinos.persisted_valuation.v4` 仍允许把盘中基金估算值作为明确的非权威证据展示，但在同日
持久化确认净值出现前必须标记为 `confirmed_nav_missing`。这类快照为 degraded，不能满足
Decision、风控或 Decision Quality 的权威完整性门禁。该分类只读取持久化事实，绝不会让 GET
路径联系 provider。

批量下单前风控边界对同一个 canonical identity 执行 fail-closed：只有完整的持久化估值快照、
大于零的 ledger cutoff，以及每个候选完整的持久化行情证据同时成立，才允许写入风控决策。
被拒绝的批次返回可解释的零写入结果；合格批次则把精确 snapshot 与 cutoff 写入每条风控审计。
两条分支都不会创建订单、提交券商或写账本。

## 核心流程

### 研究

```text
策略定义
-> 冻结数据集快照
-> 确定性回测
-> 成本与 OOS 分析
-> 研究证据包
-> 人工复核与 promotion readiness
```

策略扩展使用有类型的 metadata 与参数。由 Web 触发的任意代码执行不在契约内。研究输出不能
绕过风控、journal、paper/shadow 或人工确认门禁。

### 每日决策

```text
组合 + 行情 + 策略 + 账户证据
-> 候选操作与目标权重
-> 批次构建与成本
-> 风控门禁
-> 买入 / 卖出 / 持有 / 再平衡 / 不行动 / 需要复核
```

每个公开操作都包含证据与阻断项。不行动是一等结果，不是错误或空响应。

### Paper/shadow 运营

```text
每日计划
-> 确定性 paper/shadow 运行
-> 模拟 OMS 订单与成交
-> 成本与偏差
-> 操作员复核与告警
```

Paper/shadow 事实绝不会变成真实成交或账本修改。Operations 负责 run identity、重试、状态、
限制与恢复任务。

### Account Truth 与对账

```text
候选 adapter release manifest
-> deterministic local conformance report
-> 人工 accept / reject / revoke review
-> 精确 live collector deployment binding
-> 显式券商导入或 collector 证据
-> preview 与校验
-> 已持久化券商事实
-> 账户/执行对账
-> 人工复核
-> 可选且单独确认的账本操作
```

原始 provider 事实保留来源身份。重复、序列、账户、数量与 schema 冲突必须 fail closed。

collector 自报的 release-status 字段不是权限。release acceptance 会先把最新通过的
deterministic conformance report 绑定到精确 manifest fingerprint；live callback/poll ingestion
随后解析 append-only adapter release review，并在 prepare 与 commit 两次绑定 collector、deployment fingerprint、
provider、gateway、account alias、authorization、capability matrix、进程边界以及 rollback/privacy
证据。release 证据缺失、rejected、revoked、被篡改或 drifted 时会阻断 ingestion。出现较新
conformance result（包括较新 pass）后必须重新人工复核；较新失败会使旧 eligibility 失效。本地
suite 只验证 Karkinos 契约，不宣称真实 adapter 可用。Acceptance 既不会注册 adapter，也不会
授予券商写权限或资本权限。

Operations 通过 `karkinos.broker_adapter_readiness.v1` 投影同一套已持久化的 release、conformance
与 collector binding。该 projection 以只读方式打开数据库，不创建缺失 schema、不联系 provider，
并把“尚未选择真实 provider”视为中性状态，而不是系统异常。它可以展示 drift 或 collector 失败，
但不能记录 review、注册 adapter，或授予执行与资本权限。

只读 soak promotion 还会把 recovery evidence 绑定到一个精确 connector。无 scope、属于其他
connector 或混合 connector 的 drill 不能满足目标 connector 的 dossier。每种 drill type 以最新
的匹配 scoped result 为准；后来失败会推翻旧 pass 并改变 dossier fingerprint，因此旧 operator
acceptance 不再匹配。

### 受控执行

```text
已复核计划与 OMS 订单
-> 账户/风控/paper-shadow/gateway/对账门禁
-> 已签名资本评估与逐单批准
-> 一个持久化 controlled intent
-> 一个外部效果
-> lifecycle query/callback 证据
-> 对账
-> 明确确认后入账
```

策略代码不能接触 gateway。Prepared、accepted-but-unreconciled 或 unknown intent 会阻断不同
订单。Unknown 结果只能查询，绝不自动重提。

终态 rejected intent 可通过 `karkinos.controlled_broker_rejection_evidence.v1` 复核。该只读契约
绑定 canonical OMS order fingerprint、controlled intent、精确 gateway/account/client-order/operator
身份以及白名单净化结果，并区分网关调用前本地阻断与网关明确拒绝；证据缺失或歧义时 fail closed。
Export 会重新 preview 并拒绝 drift，artifact 仍然只读、仅供复制。单独的
`karkinos.controlled_broker_rejection_review.v1` 会在 `BEGIN IMMEDIATE` 内重检精确 preview
fingerprint 后才追加记录，绑定唯一复核人、处置、证据时间、净化结果 fingerprint 与全部 submission
identity；相同请求在重复/重启后返回原记录，冲突复核人会 fail closed。订单旅程随后收敛为不得
重试。两条边界都不能查询或联系 provider、创建/重试/撤销订单、修改 OMS/ledger/Account Truth/
risk/kill switch/interlock 或改变资本/执行权限。任何后续订单必须从新 Decision 开始并重过全部门禁。

`karkinos.controlled_execution_operator_view.v3` 会在选择操作员下一步之前检查有界范围内的全部
persisted controlled intent。按时间最新的 journey 继续保留用于审计兼容，但首要关注项按照
fail-closed 严重度选择：unknown/prepared 结果与开放券商订单优先于对账、clearance、posting、
Account Truth 后续复核及已经闭环的拒单。紧凑关注队列会让较早但未完成的旅程在出现更新旅程后仍
保持可见。该 GET 只读持久化事实，不能查询 gateway、提交、撤单、写账本或改变任何权限。

精确持久化且仍开放的 lifecycle 可通过
`karkinos.manual_broker_cancellation_ticket.v1` 投影。该 provider-neutral 边界根据 persisted
controlled intent、OMS order fingerprint、broker/client 双重订单 ID 与最新 lifecycle observation
生成可复制的人工操作资料；导出时会重新执行 preview 并拒绝已漂移 fingerprint。它不注册或调用
adapter，不签发撤单，也不修改 OMS/ledger、risk、kill switch、interlock 或 capital authority。
操作员必须在单独复核的券商界面完成人工动作；只有更新导入的 lifecycle observation 加上 Account
Truth/reconciliation 证据才能证明撤单。既有 live-cancel endpoint 继续保持禁用，因此该资料包
不是 M2 显式撤单命令，也不构成任何 provider 支持声明。

Reconciliation clearance 以
`karkinos.controlled_submission_reconciliation_clearance.v3` 作为 canonical 精确终态契约。
签名命令可以记录完整成交、零成交撤单或部分成交后撤单；仍处于开放状态的 partial fill 继续
阻断。成交数量来自独立持久化的券商 statement 与 Account Truth，撤销数量和终态绑定
broker-neutral lifecycle observation；partial-cancel 的成本合计必须在两组证据间一致。Clearance
事务只记录实际 fills、按对应状态推进 OMS 并释放跨订单 interlock；它绝不写生产账本、联系
provider、签发撤单或授予提交/资本权限。后续 lifecycle 或 collector drift 会使 clearance 失效并
重新阻断 interlock。

对账后入账是独立的 `karkinos.controlled_submission_ledger_posting.v1`
preview-confirm-apply 契约。Preview 绑定已 clearance 的 intent 与 OMS 终态、精确 broker/client
order identity、lifecycle observation、statement rows、fills、费用/税/过户费、Account Truth
identity、valuation snapshot、ledger cutoff/fingerprint 和短期 operator approval。写事务在
`BEGIN IMMEDIATE` 内重新读取这些事实及 canonical ledger identity；任一 drift 会拒绝整个批次。
每个真实 fill 只生成一个带 immutable clearance/import lineage 的 confirmed ledger event；
partial-cancel 只写实际 fills，零成交撤单产生 applied 的零 entry posting。Posting record 与全部
ledger events 同事务提交，并在 posting、clearance、intent、order、fill 与 settlement evidence
维度 exactly once。历史不可删除。该边界不联系 provider，也不具备 submit、cancel、strategy、
AI、risk decision、kill switch 或 capital authority 能力。

纠错使用独立的 `karkinos.controlled_submission_ledger_correction.v1` 契约。请求只能包含 immutable
posting id、白名单原因和 operator identity，不能提交 cash、quantity、cost、fee 或 P/L 数值。
Preview 使用 canonical ledger projector 重放两次：一次保留全部事实，另一次只排除原 posting 的
精确 entry ids；补偿现金和完整持仓会计状态只能由两次结果之差生成。Artifact 绑定原 entry
fingerprint、Account Truth import/review、valuation snapshot、ledger cutoff/fingerprint、derived plan
与一份新的短期 operator signature。Apply 在 `BEGIN IMMEDIATE` 内重新推导，并只追加一个受保护的
`controlled_projection_correction` event 和 immutable correction record；原交易、费用与 posting
record 始终可查询。零 entry posting 没有可纠正的财务事实；重放无效、存在依赖交易、identity
drift、冲突重试或 before-state 被篡改时均 fail closed。Apply 后 Ledger、Holdings、Allocation、
Equity、Overview、Cockpit 与 Account State 读取同一个 canonical projection 和 snapshot identity；
Account Truth 会刻意变为 stale，直到更新的券商证据覆盖该纠正。纠错边界不能修改 OMS、联系
provider、submit/cancel、risk、kill switch、strategy/AI 或 capital authority。

入账前 Account Truth 只有在每个 non-pass reconciliation item 都能数学上精确归因于这一笔受控
订单尚未入账的 cash、position、gross、net、fee、tax、transfer fee 与 cost basis delta 时，才可
允许 clearance 继续；缺少 snapshot 或存在任一无关差异仍然阻断。入账后，ledger coverage 只承认
immutable posting lineage 指向同一 broker import 的 ledger rows；任何其他较晚账本事实都会令证据
stale。Post-apply 会发布新 valuation snapshot 并要求 Account Truth 再次一致，否则显式进入人工
复核，不能静默宣称完成。

### 证据绑定的策略贡献

`karkinos.account_strategy_contribution.v2` 是账户策略贡献的 canonical projection。一个策略关联
成交只有在生产账本中存在唯一 trade entry，并且 fill id、标的、资产类型、方向、数量、价格与
佣金完全匹配后才可进入归因。关联但未入账、重复账本记录、身份不一致，或卖出无法从策略自有
买入库存重放时都会阻断贡献，不能输出估算收益。

策略未平库存只能使用报告指明的精确持久化估值快照计价。投影会绑定 snapshot id、valuation
as-of、ledger cutoff/fingerprint、quote-set fingerprint、成交与账本引用及 contribution
fingerprint。证据缺失、陈旧、估算、无效或漂移时，全部贡献金额保持不可用。实际成交价格已经
包含执行滑点，因此滑点只披露、不重复扣减；费用和税来自已入账的 ledger fact。

该投影完全只读：不联系 provider、不写数据库，也不授予 OMS、券商、风控、kill switch、执行
或资本权限。账户只绑定策略但尚无关联或归属不明成交时，当前没有应归因贡献，因此不会形成
Decision 的循环阻断；一旦存在成交，账本、估值或来源证据不完整就会 fail closed，并向
Overview、Decision、Operations 与 Strategy Lab 提供唯一明确的下一步人工操作。

操作员可以通过 `strategy_contribution.read` 明确冻结该投影，用于 AI 辅助的结果复盘。捕获请求
必须指定当前精确 `strategy_id`；适配器只复用 canonical report，并用捕获时的 valuation/ledger
identity 包装，assignment 或 identity 漂移都会被拒绝。只有完全绑定的贡献才是 authoritative；
无成交、缺失或未对账结果仍保持 degraded/blocked。该捕获不联系 provider、不重算财务概念，
也不修改任何权限。

### 证据绑定的决策后复盘

`karkinos.decision_outcome_review.v1` 是一条持久化 signal 结果的 canonical 人工处置。只读 preview
绑定精确 signal、action/risk、订单/成交引用，以及同一标的的 canonical 策略贡献投影；不接受
操作员输入收益，也不重新计算 P/L。记录必须带幂等键、精确 preview fingerprint、allowlisted
结论、复核人、说明和显式无权限确认。证据漂移会拒绝新确认，并让旧结论显式失去当前绑定。

复盘记录及事件 hash chain 均 append-only、可重启重放；写入只追加审计证据，不能修改 OMS、
订单、成交、账本、Account Truth、风控、kill switch、broker submit/cancel、AI memory、prompt 或
资本权限。

### 决策质量北极星证据

`karkinos.decision_quality_target.v1` 是每日决策过程质量的 canonical projection。它只复用当前
Decision payload，固定检查五个维度：持久化估值与 Account Truth 完整、确定性风控已检查、
具备基准对照的回测证据、signal 已入日志，以及稳定的决策后复盘身份。被风控拒绝的决策只要
检查完整仍可合格；基准维度要求明确 benchmark，但不要求跑赢。No-action 日把风控与基准标记为
not applicable，不伪造证据。

诊断百分比是五个维度的满足比例；每日北极星结果仍只有 `qualified` 或 `blocked`。操作员必须
针对精确 target fingerprint 显式追加 `karkinos.decision_quality_capture.v1`。捕获幂等、可重启，
并由逐 capture 的事件 hash chain 保护。纵向报告对每个 decision date 只使用最新且审计有效的
捕获，并明确覆盖范围仅为“显式捕获日期”；未捕获日期不得被静默计入。

GET 投影与 replay 不联系 provider、也不写数据库。Capture 只写审计证据，不能调用 AI、重算
财务事实，或修改 risk、OMS、订单、成交、账本、Account Truth、kill switch、broker
submit/cancel、memory 与资本权限。该分数衡量决策过程证据，不衡量投资收益，也不构成建议或权限。

### AI 研究

```text
显式证据捕获
-> 不可变上下文
-> 人工创建研究任务
-> 权限检查后的只读工具
-> claim / debate / report
-> 人工复核
-> 可选、可撤销的历史 memory
```

Provider、model、role、prompt、workflow、tool、evidence、artifact、review 与 memory 身份保持
独立。每个模型阶段引用当前证据；历史 memory 标记为 non-current。外部调用不获得 provider
工具或交易权限，raw reasoning 与凭证不持久化。

证据绑定的公式研究流程更加狭窄：

```text
已保存 canonical backtest 与精确数据集快照
-> 人工确认假设导出
-> allowlisted Formula DSL 校验
-> 人工选择、具有 next-bar 语义的 canonical backtest
-> 可选且单独确认的证据批评
-> 人工接受 / 修订 / 拒绝
```

Formula DSL 是作用于已持久化 OHLCV 字段的 JSON AST，lookback 与 window 有界。任意代码、
未知 operator 或修改 universe/window/frequency/cost 输入都会被拒绝。受限适配器复用精确保存的
bars 与 canonical BacktestEngine；它不能注册生产策略、创建 Decision 或 trading plan，也不能
接触 OMS、ledger、risk、kill switch、broker、capital 或 authority state。

## 权限边界

| 能力 | Research/strategy | AI | Operator | Controlled runtime |
| --- | ---: | ---: | ---: | ---: |
| 读取已持久化证据 | scoped | scoped | yes | scoped |
| 提议目标权重或计划 | yes | 仅草稿 | yes | no |
| 决定风险 | no | no | policy/review | 确定性门禁 |
| 修改账本 | no | no | 单独确认 | no |
| 发布资本权限 | no | no | 已签名决定 | no |
| 提交一个券商订单 | no | no | 最终批准 | 仅限精确门禁内 |
| 取消一个券商订单 | no | no | 单独批准 | 仅限精确门禁内 |
| 放宽或续期权限 | no | no | 新决定 | never |

Execution gateway 与只读 evidence connector 是不同身份，不得静默共享权限。生产环境默认既不
注册 write adapter，也不注册 release provider。

## 受控权限模型

有效权限是所有适用限制的最小值：

```text
操作员授权
账户与策略 policy
标的与流动性限额
资本、现金、换手、损失与回撤预算
订单价值与订单速率限制
新鲜的账户、行情、gateway 与对账证据
kill-switch 与运营健康
```

Reservation 与 rate admission 串行化。Runtime session 已签名、短期、token-authenticated，并且
只能单向暂停。恢复时创建一个相同或更窄的新 session，而不是原地恢复旧 session。

## 失败语义

- **Rejected：** provider 明确拒绝命令；证据持久化后，恢复流程可以释放 interlock。
- **Unknown：** 外部效果可能已发生；使用相同 client identity 查询，绝不自动重提。
- **Partial：** 保留精确成交与剩余数量，不得归一化成成功或失败。
- **Drifted：** 复核后来源或 fingerprint 改变；使派生 eligibility 失效并要求重新复核。
- **Paused：** 硬门禁失败；后来出现明确证据也不会恢复同一 session。

告警与操作员视图派生自已持久化事实。它们可以指出问题与安全的下一步，但不能以读取副作用
刷新 provider 或修改权限。

## 部署与隐私

- 核心应用 local-first，使用 SQLite 保存持久状态。
- 券商与外部模型适配器保持为可替换边缘组件。
- 凭证在运行时提供给相应边缘组件，绝不保存到 canonical 财务表或审计表。
- 真实账户导出、运行数据库、日志、截图与 secrets 不进入源码控制。
- Adapter release、capability、deployment、authorization、health 与 rollback 证据均明确且有版本。

## 架构变更规则

只有持久组件、数据流、权限边界或 invariant 改变时才更新本文。版本进展、测试数量、逐 endpoint
实现说明与已完成阶段日志属于[实现记录](IMPLEMENTATION_LOG.zh.md)或 Git 历史。
