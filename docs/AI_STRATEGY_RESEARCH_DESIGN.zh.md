# AI 策略研究详细设计

[产品目标](KARKINOS_GOAL.zh.md) | [架构](ARCHITECTURE.zh.md) | [路线图](ROADMAP.zh.md)

## 文档归属

本文档统一承载 Karkinos 使用 DeepSeek 等模型，以及 direct HTTPS、受控本地 DSH 等模型
运行时改进量化策略研究的详细设计。
产品边界和长期权限不变量仍由 `KARKINOS_GOAL.zh.md` 与 `ARCHITECTURE.zh.md` 统一定义。

本文中的“本地 DSH”只表示 harness 进程运行在本机，不表示模型权重、本次推理或数据处理
必然发生在本机。只要 DSH 的最终模型路由仍指向外部服务，全部外发授权、最小披露、调用预算
和 provider 审计规则原样适用。

全文使用陈述式定义目标协议和完成条件，不表示对应代码、部署或运营证据已经存在。实现状态
只允许写入 Implementation Log 或验收 artifact；后续实现模型必须以本文不变量和测试矩阵为
约束，不能把设计文字本身当作完成证据。

## 设计决策

Karkinos 将外部模型限定为有界的**研究假设提出者与模型批评者**，而不是选股器、参数
优化器、组合权限主体、策略晋级主体或订单生成器。

以下裁决权始终由本地 canonical 系统持有：

- point-in-time 行情与股票范围事实；
- 公式校验与可执行语义；
- 参数搜索与组合构建；
- 回测、费用、基准、统计与风险门禁；
- 候选选择与证据 lineage；
- 策略晋级、资金额度和每一次订单决策。

`provider`、`model`、`runtime adapter`、`profile` 与 `workflow` 是五个独立身份。DeepSeek 是
provider，具体模型 revision 是 model，OpenAI-compatible HTTPS 或 DSH subprocess 是 runtime，
DSH 的组合配置是 profile，五组 hypothesis/critique 竞赛是 workflow。任何实现都不得把
“本机启动了 DSH”解释为 provider 已变成本地、调用不再外发，或原授权可以跨 runtime 复用。

目标产品是一个证据绑定的研究竞赛，用来验证模型提出的经济假设是否相对于透明的确定性
基线带来可复现增量，而不是一个无人值守的盈利机器人。

## 设计目标

1. **阻断自适应泄漏。** 模型可见的验证结果与最终 sealed 证据严格分离。
2. **统一研究与生产语义。** 回测、验证、paper/shadow 与每日全池扫描共享同一组合实现。
3. **建立 point-in-time 数据口径。** 股票成员、复权、公司行动和可交易状态均可复现。
4. **保守模拟 A 股成交。** 费用、滑点、市场冲击、涨跌停、停牌与部分成交均进入模型。
5. **控制多重检验。** 所有语义不同的公式与参数试验进入统一统计试验族。
6. **隔离运行故障域。** 收盘后研究与有截止时间的 Daily Decision 完全解耦。
7. **衡量 AI 增量价值。** DeepSeek 必须在 sealed 数据上与匹配的非模型搜索基线比较。
8. **冻结模型运行时。** 模型路由、运行时、profile、工具、进程和重试行为均可审计、可重放。

## 范围

本文只覆盖 daily-candidate 工作流中的 A 股股票研究。基金和 ETF 继续属于 Account Truth、
估值与组合风险事实，但不进入公式研究、策略晋级或订单票据范围。

设计范围包括：

- 不可变实验身份；
- point-in-time 研究数据集与股票池切分；
- 模型请求和响应契约；
- 本地公式及参数搜索；
- canonical 组合模拟与 A 股成交模型；
- 防泄漏验证和多重检验控制；
- provider/runtime 调用编排、DSH 进程协议、重启恢复与运行隔离；
- 人工晋级、paper/shadow 与效果证据。

本文不接入自动下单、不扩大资本授权、不允许模型生成任意代码，也不承诺投资收益。

## 权限与安全不变量

以下规则不可退让：

- 模型输出只是非权威研究证据。
- 模型不能调用券商、OMS、账本、风险 mutation、策略注册、资本授权或订单提交工具。
- 模型返回的权重、数量、现金数值和订单全部丢弃。
- 公式只能通过版本化、allowlisted DSL 执行。
- 输入缺失、过期、部分、估算、冲突、漂移或不可复现时，必须在外发或候选评估前
  fail closed。
- provider 调用完成、研究竞赛完成或历史结果通过，都不能自动晋级策略。
- 每个上游模型请求都必须由 Karkinos 预先 claim 并计入预算；DSH 内部 title、retry、
  compaction、search、subagent 或其他隐藏模型请求一律不得存在。
- DSH 不能读取 Karkinos 仓库、项目 `.env`、个人 DSH home、账户导出、运行数据库或未进入
  Research Pack 的本机文件；仅设置 `read-only` 不能替代该读取隔离。
- runtime 不可用时不能在同一实验内静默切换到另一 runtime。runtime/profile 变化必须重新
  冻结 charter，并取得与新 payload/runtime 精确绑定的外发授权。
- paper/shadow 准入、生产 assignment、回滚和任何资金额度变更都是相互独立、绑定指纹、
  有界且可撤销的人工决策。
- 每日 Decision 只消费此前已人工晋级的不可变策略 artifact，绝不等待模型。

## 目标架构

```text
point-in-time Universe Truth + 统一复权的冻结行情
                         │
                         ▼
                不可变 Research Charter
                         │
                         ▼
             Karkinos 模型运行时边界
       ┌─────────────────┴─────────────────┐
       │                                   │
 direct structured HTTPS       isolated DSH machine runtime
       └─────────────────┬─────────────────┘
                         │
                         ▼
        模型提出多个相互独立的经济假设
      （看不到最终 holdout，也看不到账户绝对规模）
                         │
                         ▼
             本地 DSL 校验与训练集搜索
                         │
                         ▼
       canonical 组合引擎 + 自适应验证集
                         │
                         ▼
                  冻结唯一 champion
                         │
                         ▼
 sealed 时间 holdout + sealed 横截面 challenge
       + 多重检验校正 + 多基准门禁
                         │
                         ▼
          人工批准仅进入有界 shadow
                         │
                         ▼
             前瞻证据与人工 GO / NO-GO
                         │
                         ▼
          再次人工决定 production assignment
                         │
                         ▼
              已晋级不可变策略 artifact
                         │
                         ▼
 每日 Decision -> 本地风险/费用/账户门禁 -> 票据/NO-ACTION
```

研究平面与每日运行平面只通过内容寻址的持久化 artifact 通信。provider 可用性永远不能
成为每日交易的前置条件。在再次人工决定 production assignment 前，每日路径继续使用当前
incumbent，并忽略研究候选。

## 不可变 Research Charter

每次研究竞赛都从一份不可变 manifest 开始。任何字段变化都必须创建新实验，不能在新语义
下续跑旧 lineage。

必须冻结的身份包括：

- 实验 ID、schema 版本、owner 授权、创建时间和目标市场日；
- provider ID、endpoint 类型、精确模型 revision、prompt contract 版本、响应 schema、
  sampling profile，以及 logical/retry/physical 三类调用上限；
- `workflow_descriptor`：workflow ID/version、拓扑、lane 数与身份、stage 映射、每个 stage 的
  logical-call allocation、并发规则、selector/tie-break、停止条件，以及实质 logical call、
  transport retry、物理上游请求与 purpose-specific runtime process 四类独立 ceiling；
- runtime adapter kind、实现版本、代码 revision、运行时 descriptor fingerprint；若使用
  DSH，还包括 executable/Node/package closure、profile/composed config/plugin lock、persona、
  tool schema、环境 allowlist、sandbox、网络出口和 machine protocol 的指纹；
- DSL 版本、算子 allowlist、组合策略版本、成交模型版本、指标版本和 gate policy 版本；
- 行情快照 ID、复权模式、公司行动来源、交易日历、股票池快照 ID 和数据质量指纹；
- discovery、adaptive validation、sealed time、sealed cross-section 四类切分；
- incumbent 策略、现金、市场指数、横截面基准，以及预声明 deterministic/random challenger
  generator、计算预算与冻结 artifact policy；
- 已复核费用表、研究名义资金 policy 和账户容量证据指纹，但不包含账户绝对值；
- 最大公式复杂度、参数域限制、调用预算、本地计算预算和总运行 deadline。

任何 provider 调用前都必须先计算 manifest hash。每个 stage 结果同时绑定该 hash 与直接
父 artifact。

外部证据外发需要一项单独 owner 决策，精确绑定 manifest、provider descriptor、响应
schema、workflow descriptor、logical/physical 调用上限、到期时间和允许的 payload family。
每个请求都同时绑定该授权和自身 payload
fingerprint。授权不能复用于改变后的 payload family、静默扩容，也不能解释为策略、shadow、
production、订单或资本权限。

本文默认的“四条独立探索 lane + 一条 refinement”是独立 workflow version。它与旧的五轮
严格串行 hypothesis/critique 链在拓扑、模型可见上下文、payload family 和统计试验族上均不
兼容：必须创建新 experiment、冻结新 `workflow_descriptor` 并取得新外发授权。旧 workflow
的中间产物、未用调用 slot、provider receipt 与授权不得自动迁移。

Formula discovery 当前固定使用 1,000,000 CNY 归一化研究名义资金，并以版本化策略
`karkinos.ai.normalized_research_notional.cny_1m.v1` 绑定该金额；成本使用 canonical 预估模型。
它不要求同日 Account Truth，也不读取 broker provider。生成的 candidate 必须保持
research-only；由于没有账户专属、已对账成本和容量证据，现有 promotion、shadow 准入、
Daily Decision 和 execution 门禁继续 fail closed。当前尚未实现对既有 normalized candidate
独立补录 Account Truth、以账户专属成本重算并产生可晋级证据的 qualification/replay service；
不得把现有 fail-closed 门禁表述为该服务已上线，也不得为此向模型外发账户证据。

## Dataset 与 Universe Truth

### Point-in-time 成员关系

历史验证必须重建每个决策日当时可知的信息。数据集需要包含上市和退市日期、历史 ST 状态、
停牌、交易所/板块涨跌停规则、可交易状态与公司行动。不能用“当前仍上市股票目录”代替
历史成员关系。

### 价格身份

同一实验内所有股票使用一套经复核的复权和收益口径。快照需要绑定原始价格、复权因子或
总收益处理、公司行动来源与实际消费的有序数据行。provider 诊断不能覆盖已经漂移或不完整
的 consumed frame。

### 研究切分

四种数据切分职责必须分离：

| 切分 | 迭代期间可见 | 用途 |
| --- | ---: | --- |
| Discovery/train | 是 | 本地公式与参数搜索 |
| Adaptive validation | 是 | 比较轮次并选择 finalist |
| Sealed time holdout | 否 | 只测试一次未来时段泛化 |
| Sealed universe challenge | 否 | 只测试一次横截面泛化 |

在唯一 champion 的公式、参数与组合 policy 冻结前，模型 prompt、DSH capability、中间
selector、finalist 比较和任何 pre-freeze stage 都不能访问 sealed 切分。本文 workflow 不允许
以 candidate family 代替唯一 champion；只有已经冻结的唯一 champion 可以获得一次性
`sealed_test` capability。

sealed 分区一旦开封，就在该 research family 内永久消耗并降级为 adaptive evidence。
失败结果不能反馈给同一实验；新实验必须使用真正未见的未来时段或互斥横截面分区，仅创建
新的 experiment ID 不能让已经揭示的数据重新变成未见数据。

默认 40 股研究面板只能作为受计算预算约束的 discovery surface，而且必须 point-in-time，
并按板块、行业、市值、流动性和交易状态分层。它不能独立满足晋级；冻结后的唯一 champion
还必须由 sealed evaluator 一次性完成互斥 universe challenge 与全池验证。任何 pre-freeze
工具、selector 或多个 finalist 的比较都不能读取该数据或其聚合结果。

## 模型契约

### 模型职责

模型可以提出：

- 经济假设与预期机制；
- 仅使用已公布算子的 Formula DSL 结构；
- 有界参数域，而不是声称某个值最优；
- 预期适用行情、失效条件和证伪测试；
- 由本地引擎执行的消融与对照方案；
- 对请求中精简证据的 claim-level 引用。

模型不能选择最终参数、组合权重、订单数量、胜出候选、晋级结果或资本配置。

### 最小 Research Pack

外部请求只包含提出假设所需的信息：

- 版本化 DSL/算子能力；
- 冻结股票池特征与标准化行情摘要；
- 以收益率、比例、基点、排名和风险区间表达的公式及基准结果；
- 必要时的父假设、证伪结果和 critique；
- 经明确授权的脱敏股票代码；
- 与模型需要提出的论断对应的稳定 evidence ID。

禁止外发账户标识、券商原始行、凭证、valuation/ledger ID、绝对余额、持仓数量、组合绝对
估值、绝对 PnL/费用、交易计划与券商能力。账户容量只在本地检查；研究规模使用归一化名义
资金或粗粒度 policy bucket 表示。

### 响应契约

模型只返回语义内容。不可变 selection 字段、dataset identity、公式 binding、lineage、
citation 和 fingerprint 都由本地代码附加。模型内容必须是严格 UTF-8、恰好一个顶层 JSON
object。唯一允许的 normalization 是移除该 object 前后的 RFC JSON whitespace，并在严格解析
成功后按 canonical JSON 规则重新序列化；它不产生新的 provider 调用。

解析器必须拒绝 duplicate key、NaN/Infinity、comment、trailing comma、Markdown fence、前后
说明、多对象、非 UTF-8、未知字段、字段丢弃、类型强制转换、默认值猜测和任何语义推断。
outer machine result 也必须是精确 canonical JSON bytes，最多只允许一个末尾 LF；不能搜索
大括号、截取最后一行或修补无效 JSON。语义歧义、不支持算子、范围变化或伪造证据一律
fail closed。

模型 critique 应标记为 `model_critique`；除非来自独立标识的第二模型或人工 reviewer，不能
称为 independent critique。无论 critique 文本如何，确定性本地门禁始终拥有裁决权。

## 模型运行时与本地 DSH

### 身份与抽象边界

Karkinos 的 workflow 和 `StrategyResearchModelProvider` 持有研究语义：它们决定何时读取哪份
Research Pack、当前是 `hypothesis` 还是 `critique`、允许的响应 schema、citation catalog、
调用预算以及结果如何进入 Stage Ledger。模型运行时只负责把一份已经冻结、已经脱敏、已经
授权的请求交给精确模型，并返回机器可验证的 completion receipt。

运行时必须实现一个 provider-neutral 的语义接口；具体语言签名可以调整，但字段和失败语义
不得弱化：

```python
class ModelCompletionRuntime(Protocol):
    @property
    def runtime_descriptor(self) -> ModelRuntimeDescriptor: ...

    def complete(
        self,
        request: CompletionInvocationEnvelope,
        *,
        binding: CompletionAttemptBinding,
    ) -> ModelRuntimeOutcome: ...

    def collect_existing(
        self,
        request: CompletionCollectEnvelope,
        *,
        binding: CollectorAttemptBinding,
    ) -> ModelRuntimeOutcome: ...
```

`openai_compatible_https_v1` 与 `dsh_subprocess_json_v1` 实现该 single-completion protocol。
`CompletionInvocationEnvelope = ModelInvocationEnvelope | CanaryInvocationEnvelope`，
`CompletionAttemptBinding = RuntimeAttemptBinding | CanaryAttemptBinding`；所有分支按 `purpose`
严格区分。`CompletionCollectEnvelope` 只绑定原 purpose/invocation、provider call、authorization、
session/turn/runtime/payload fingerprints，不含 messages、credential 或 provider permission。
`CollectorAttemptBinding` 只授权新的本地 collector identity/deadline，不授权 physical request；DSH
variant 还必须持有 spawn 前原子签发的 purpose-specific collector+total process-slot reservation，
HTTPS variant 只有 adapter attempt identity，不能伪造 process slot。
`dsh_bounded_lane_v1` 不伪装成一次 `complete()`；它实现独立
`StrategyResearchLaneRuntime.run_turn(DshLaneTurnEnvelope, RuntimeAttemptBinding)` 与同等级
`collect_turn(...)`，返回版本化
lane turn/tool/final-submit union。Factory 返回的顶层 union 必须 exhaustive dispatch，调用方不能
用 capability flag 把两种 protocol 混在同一实例中。

`ModelInvocationEnvelope` 由 Karkinos 在 runtime 外构造，至少包含：

- `experiment_id`、workflow/stage/lane identity 和语义稳定的 `logical_call_id`；
- manifest、runtime descriptor、provider descriptor、export authorization、
  `ProviderExportReceipt` 与 payload fingerprint；
- `stage=propose|critique`、role、精确 system prompt、脱敏 Research Pack 和 citation catalog；
- response schema/version、sampling、max output tokens、预算 policy/ceiling 与 deadline-policy
  fingerprint。具体 reservation、attempt 起止时间和 lease 不属于语义 envelope。

`ModelInvocationEnvelope` 是语义请求，不包含 `stage_attempt_id`、attempt/lease generation、
`dsh_attempt_id`、`physical_request_id`、`retry_of`、PID/session 或上游 `provider_request_id`。
其中只有可预分配的 stage/attempt/generation/lease、runtime/DSH attempt 与 planned spool identity
进入 pre-grant `RuntimeAttemptBinding`，且不参与 invocation envelope fingerprint。Physical/grant
identity 进入 Claim/Grant；实际 PID/start token、session/turn 进入 `DshAttemptEvent/Receipt`；
provider identity 只来自 durable ProviderCallEvent/TerminalReceipt。后出现的事实不得回写 binding。

Canary 不伪造 research stage。它使用独立的 `CanaryInvocationEnvelope`：

```text
purpose: runtime_canary
canary_id + stable logical_call_id
runtime_descriptor_fingerprint
canary_manifest_fingerprint + canary_authorization_fingerprint
fixed non-financial messages + random nonce
exact response schema + sampling
provider_budget: {logical_calls: 1, retries: 0, physical_requests: 1}
runtime_budget:
  HttpsCanaryBudget {adapter_attempts: 1}
  | DshCanaryBudget {fresh_processes: 1, collect_processes: 1, total_processes: 2}
deadline-policy fingerprint + credential_reference_version
```

`DshCanaryBudget` 的三个简写字段分别映射同一 canonical ceiling semantics：
`fresh_process_start_ceiling`、`collector_process_start_ceiling`、
`total_process_start_ceiling`；持久化 receipt/ledger 使用 canonical 名称。

该 envelope 不含 experiment、Research Pack、research export authorization、strategy、账户或
sealed identity，并使用独立 `CanaryAttemptBinding`。Canary failure 不得自动 retry；再次探测必须
取得新的 canary ID/authorization 并创建新的 evidence family。

Canary host 把 common runtime outcome 封装为严格 adapter union：
`RuntimeCanaryReceipt = LiveHttpsCanaryReceipt | LiveDshCanaryReceipt`。两者共享 canary envelope、
authorization、descriptor、1/0/1 provider accounting 与 semantic result；HTTPS variant 必须绑定
client/wire/TLS/credential evidence 且禁止 DSH install/process/FD 字段，DSH variant 必须绑定
install/profile/process/spool/FD/credential evidence。Factory 必须按 descriptor exhaustive 返回精确
variant，任一 mixed/missing field 都拒绝。

`RuntimeAttemptBinding` 是 pre-grant、不可变 binding：公共字段是唯一 `runtime_attempt_id`、
research stage/attempt/generation/lease、invocation fingerprint、logical/local-compute reservation、
absolute stage/global deadline 与 runtime-attempt lineage；transport 字段只能是：

```text
HttpsAttemptBinding {adapter attempt identity}
| DshAttemptBinding {
    dsh_attempt_id,
    ProcessStartReservation {purpose, kind=fresh, category_ordinal, total_ordinal, budget_fingerprint},
    typed spool identity
  }
```

HTTPS 不得生成或伪造 `dsh_attempt_id`。`CanaryAttemptBinding` 采用同样 transport union，但用
canary ID/authorization 代替 experiment/stage。Effective hard deadline 只有一个：spawn 前记录
`deadline_computed_at`，再计算 `min(deadline_computed_at + descriptor hard cap,
absolute stage-or-canary deadline, absolute global reconciliation deadline)`；计算时刻和三个 absolute
输入全部写入 binding，machine request 只传该 absolute effective deadline。Soft SLA 为
`min(deadline_computed_at + descriptor soft cap, effective_hard_deadline_at)`。恢复不能重置任何
absolute deadline。

Deadline 的时间锚也必须 durable，而不是在恢复时读取“现在”：research job 在 `admit` 时记录
`run_started_at` 并由 charter 的 duration 计算唯一 `absolute_global_reconciliation_deadline_at`；每个
provider stage 在首次 `planned` 时记录 `stage_planned_at` 并计算 `absolute_stage_deadline_at`。
Canary manifest/authorization 在创建时直接冻结 absolute canary/reconciliation deadline。Fresh
binding 的 effective hard deadline 成为 claim 的输入；claim 还一次性计算并冻结
`collect_deadline_at = min(effective_hard_deadline_at + descriptor collect-grace cap,
absolute stage-or-canary deadline, absolute global reconciliation deadline)`。Collector 的 effective
deadline 为 `min(collector_started_at + descriptor collect-grace cap,
claim.collect_deadline_at, claim.absolute_global_reconciliation_deadline_at)`；
`result_unknown` 只能对账到 frozen global reconciliation deadline。Lease takeover、worker restart、
新 collector 或 wall-clock 回拨都不得延长这些时间。

`physical_request_id`、physical/Token/金额 commit、grant nonce 与 retry-of-physical 只在后置的
`ProviderCallClaim`/`ProviderCallGrantFrame` 中产生；不得修改 pre-grant binding。Outer result
始终回显 immutable binding fingerprint；claim、physical 与 grant-consumed event 只按实际 durable
lifecycle 有条件回显，submit event 同理；不能为较早 lifecycle 补造尚未发生的身份。

五类 ID 的唯一含义如下，任何实现不得互换：

- `stage_attempt_id`：Stage Ledger 中一次 stage 执行；只有 terminal retryable 后新建
  `attempt_generation`，lease takeover 只改变 `lease_generation`；
- `logical_call_id`：一份语义不变的模型请求；exact transport retry 共享它，prompt、Pack、
  schema、model、profile、tool policy 或授权变化必须新建；
- `dsh_attempt_id`：一次本地 DSH process/collector 生命周期；fresh、local pre-submit retry 和
  `collect_existing` 各自使用新的 ID，但都绑定原 logical call；
- `physical_request_id`：Karkinos 在一次上游发送获得许可前生成的本地唯一 ID；每次可能的
  上游重试使用新 ID，永不复用；
- `provider_request_id`：上游 provider 返回的 request identity；它可能暂时缺失，绝不能由
  Karkinos、DSH session ID 或 physical ID 伪造。

结果是严格 discriminated union：

```text
ModelRuntimeOutcome =
  ModelCompletion {
    kind: "completion",
    call_status: "completed",
    runtime_disposition: structured_valid | output_invalid | schema_invalid,
    ...completed receipt and sanitized semantic result...
  }
  | ModelInvocationFailure {
    kind: "failure",
    status: proven_not_sent | failed_retryable | failed_terminal,
    external_effect: proven_not_sent | completed | unknown,
    ...typed failure and receipt refs...
  }
  | ModelInvocationPending {
    kind: "pending",
    status: collect_pending | result_unknown,
    external_effect: completed | unknown,
    ...open call/session/reconciliation refs...
  }
```

`ModelCompletion` 只表示存在 durable、identity-matched 的 provider terminal response、adapter
terminalization，以及 atomic result；DSH 还一律要求 completed turn 与 session flush，包括
`output_invalid`/`schema_invalid`。只有 `runtime_disposition=structured_valid` 才交给通用研究
validator。后续 citation/DSL/经济语义校验另产不可变 `ModelSemanticValidationReceipt`，其结果为
`semantic_valid | citation_invalid | dsl_invalid | semantic_invalid`；不得回写 `ModelCompletion`。
只有 `semantic_valid` 才能产生候选输入。

若 durable provider terminal response 已存在但 DSH session 尚未 terminal+flush，当前结果只能是
`ModelInvocationPending(status=collect_pending, external_effect=completed)`，并允许在 deadline 前
用 `collect_existing` 尝试形成确定的 terminal outcome；collect deadline 到期后才转为 immutable
`failed_terminal/external_effect=completed`。没有 durable terminal response 才是
`ModelInvocationPending(status=result_unknown, external_effect=unknown)`。`proven_not_sent` 不能有
provider request ID、sent/response/completed time 或
usage。`result_unknown` 可以引用 durable `request_sent` event 中真实获得的 provider request ID
和 sent time，以便对账，但 response/completed time 与 usage 必须为 null。
`failed_retryable`/`failed_terminal` 只有引用真实 completed terminal receipt 时才可投影 completed
字段。

每个 outcome 至少返回：

- invocation envelope fingerprint、payload fingerprint、`runtime_attempt_id`、research
  `stage_attempt_id` 或 canary ID，以及 adapter-specific `dsh_attempt_id`（仅 DSH）；
- 本地 `physical_request_id`（如已签发）与上游 `provider_request_id`（如 durable 获得）；
- 与输入完全一致的 purpose-specific identity：research experiment/workflow/stage 或 canary ID，
  以及 logical-call/runtime identity；
- 实际解析的 provider、model revision 与 endpoint class；
- `external_effect`、发送/接收时间、finish reason、usage、调用次数和 sanitized failure code；
- sanitized 唯一语义响应、响应 bytes fingerprint、response-schema validation status；
- runtime/profile receipt，以及 adapter-specific session/turn/process result refs（如适用）。

运行时不得读取数据库来补齐 request，不得选择 Research Pack，不得更改 prompt、预算或 model，
也不得把模型回显的 identity 当作可信 identity。所有 outer-envelope identity 必须由本地 adapter
根据冻结输入生成并重验。API key、credential 内容和原始账户事实永远不进入 envelope、日志或
fingerprint；只记录 secret reference 的版本化身份。

DSH credential transport 使用唯一受支持路径：runtime host 先验证 purpose-specific context——
research completion 与 bounded-lane turn 验证 descriptor、charter、workflow/lane/turn 与对应
export authorization，canary 验证 descriptor、canary manifest 与 canary authorization——再通过
host secret broker 解析 `credential_reference`，并把 secret
写入一次性、继承的 sealed/pipe FD。raw value 不得进入 argv、环境变量、普通文件、session、
event/result spool、日志、异常、fingerprint 或 artifact；child 只允许 provider adapter 在发送前
读取一次，随后关闭 FD，并对临时 buffer 做 best-effort zeroization。持久化内容只有 secret
reference 的 name/version 与 `CredentialBrokerReceipt` fingerprint。该 receipt 绑定 purpose、
runtime descriptor、research experiment/stage/workflow/lane/turn 或 canary ID、对应 authorization、
DSH attempt、FD handoff/close 状态和 parent refs，但绝不含 raw value。无法建立该通道时必须在 user-turn
submit 前 `proven_not_sent`，不得回退到环境变量或个人 DSH 登录态。

只有当 runtime descriptor 绑定内容寻址的本地模型、网络出口被技术性关闭且 canary 证明没有
外部 provider request 时，调用才能标记为 local inference；仅使用 loopback endpoint、代理或
本机 DSH 进程不满足该证明。Local inference 仍是非权威研究证据，不获得任何策略或交易权限。

### 允许的 runtime kind

| `adapter_kind` | 允许语义 | 关键约束 |
| --- | --- | --- |
| `openai_compatible_https_v1` | 一次结构化 completion | 一个 claim 对应至多一个上游请求；Karkinos 本地校验 JSON、citation 与 DSL |
| `dsh_subprocess_json_v1` | 通过专用 DSH runner 完成一次结构化 completion | 不使用 stock headless；无模型工具、无隐式模型调用、继承 FD + durable spool machine protocol |
| `dsh_bounded_lane_v1` | 在一条隔离 lane 内保持受控 session，并按 charter 发起多次显式模型 turn | 每个 turn 单独 claim；只允许 capability-bound pre-sealed 研究工具；独立预算和验收 |

两种 completion kind 共享完全相同的 sanitized Research Pack 与 response schema；bounded lane
则使用独立 lane schemas，但每个 outbound turn 仍共享同一 sanitizer/privacy/export pipeline，
最终提交仍共享同一本地 DSL compiler、回测、selector 和统计 gate。
`dsh_subprocess_json_v1` 不是自动进入 `dsh_bounded_lane_v1` 的兼容升级；启用后者
会改变模型可见上下文、工具面、调用数和试验族，必须使用不同 descriptor、新 charter 和新
owner export authorization。

运行时之间不得透明 fallback。DSH 启动失败时，只能把当前 stage 标记为可证明未外发、
`result_unknown` 或 terminal failure；不能在同一 attempt 内改走 HTTPS。若 owner 希望改用另一
runtime，必须创建新实验，重新冻结 provider/runtime/payload family，并确保没有把已开封的
sealed evidence 当作未见数据。

### DSH 专用 profile

正式研究只能使用版本化的 `karkinos-research-json` 或 `karkinos-research-lane` profile。通用
coding profile、个人 profile 和 shipped stock `headless` 都不是允许的生产研究 runtime，
因为“接受一段 task 并打印最后一条 assistant 文本”不能证明请求次数、session identity、
结构化输出、恢复点或工具隔离。

专用 profile 的最终 composed tree 必须满足：

- 使用 Karkinos 专属、权限为 `0700` 的 DSH home；不加载个人 home patch、个人 settings、
  个人 skills、项目 instructions、项目或用户 `.env`；
- 工作目录是当前 attempt 专属的空隔离目录，不是仓库、账户导出目录、runtime database 目录
  或用户 home；Research Pack 不以普通文件暴露给模型；
- 禁用 shell/pwsh、任意 filesystem/search/editor、jobs、skills、MCP、Web、user question、
  subagent、workflow、Ralph、goal/todo 和动态 plugin 安装；
- 禁用 session-title LLM、内部 LLM retry、自动 compaction、模型驱动 summarization、telemetry
  和任何未进入调用账本的辅助模型请求；
- 禁用 HMR、动态 settings、未冻结 overlay 与运行中 model/profile 切换；
- 只加载完成 machine protocol 所必需的最小 plugin closure；通过 late patch 标记 `disabled`
  只有在 activation report 证明对应 tool/provider 路由从未注册时才可接受；
- 默认无模型可见工具。只有 `dsh_bounded_lane_v1` 可以加载下文定义的 capability-bound 工具，
  且实际 tool catalog、schema 和 capability policy 必须进入 descriptor fingerprint；
- 网络出口仅允许 purpose-specific authority 冻结的 provider endpoint：research/bounded lane 使用
  charter+export authorization，canary 使用 canary manifest+authorization。DNS、代理、证书策略
  与 endpoint class 变化均视为 runtime drift；
- `read-only` sandbox 只是写入限制，不是保密证明。部署还必须通过空 cwd、最小环境、最小
  plugin closure、文件读取 deny policy 或独立 OS 身份阻断对其他本机路径的读取；
- profile source、最终 composed config、ordered bundle list、plugin lock、全部 package bytes、
  persona/system-prompt sections 和 tool presentation 必须内容寻址。

Session/event persistence 只能写入 attempt 专属、owner-only 的受限 store，并绑定 retention
policy。Completion profile 只保留恢复所需的 sanitized input/output、turn terminal 与 provider
receipt；raw reasoning、credential 和未授权旁路上下文不得落盘。Lane profile 若需要持久 session，
也只能保存已授权 Research Pack 与 sanitized tool trace，不能使用个人或共享 DSH session history。

`ModelRuntimeDescriptor` 是 provider-neutral common fields 加 adapter-specific discriminated union；
HTTPS 不得伪造 DSH install/profile 字段，DSH 不得伪造 HTTPS transport 字段：

```text
common {
  adapter_kind + adapter_contract_version + adapter_code_revision,
  provider_route + exact_model_revision + sampling,
  credential_reference_version + network_egress_policy_fingerprint,
  soft/hard/collect-grace caps + total limits,
  internal_retry_count=0 + hidden_provider_calls_allowed=false
}
adapter_details:
  HttpsRuntimeIdentity {
    http_client/library revision, endpoint class, TLS/proxy/DNS policy,
    request/response wire-contract fingerprint, credential transport,
    connect/read/body limits
  }
  | DshRuntimeIdentity {
    install registry/receipt + installed closure manifest,
    DSH/Node realpath + sha256 + reported version,
    profile source + bundle/plugin lock + composed config,
    persona/prompt + tool catalog/schema,
    sandbox/read boundary + environment allowlist,
    machine protocol + spool root/lifecycle policy,
    stdout/stderr/invocation/event/result limits + termination grace,
    telemetry_disabled=true
}
```

`RuntimeDescriptorManifest` 是 factory 在构造 descriptor 前生成的非自引用 canonical object：

```text
schema_version + adapter_kind/contract/code_revision
strict_config_payload_fingerprint
provider_route + exact_model_revision
adapter_identity_input_fingerprint
ordered_parent_refs  # HTTPS=[]；DSH=[install receipt, spool policy]
resolver_policy_version
```

`ModelRuntimeDescriptor.payload` 必须内嵌该 exact manifest 和解析后的 adapter union；
`RuntimeDescriptorScope.descriptor_manifest_fingerprint` 只哈希上述 manifest canonical bytes，明确
排除 artifact wrapper、scope、artifact/payload fingerprint、created_at 和该 fingerprint 自身。
整个 descriptor payload 另算 `payload_fingerprint`。Canonical owner 是
`strategy_research_factory.build_runtime_descriptor_manifest`；consumer 必须重算二者并核对，不能
用 config fingerprint、payload fingerprint 或“最新 descriptor”替代。Manifest 的
`ordered_parent_refs` 必须与 artifact wrapper 的 `parent_refs` 逐字节相等。

被选 variant 的字段全部必填，另一 variant 字段必须不存在。任一字段无法解析、使用浮动版本、
与 canary 不一致或在调用前发生变化，都必须在 provider transport 前 fail closed。DSH descriptor
强制以 install receipt/policy 为 parent；HTTPS descriptor 没有 install parent。不能只记录
`dsh --version`；同版本 executable、Node、package closure、profile 或 home overlay 不同仍是
不同 runtime。

### DSH machine protocol

Karkinos 必须以 `shell=False`、绝对 executable 和显式 argv 启动 runner。argv 只能携带
`--profile`、machine-mode flag 与不敏感的 opaque attempt ID；system prompt、Research Pack、
股票代码、公式和 credential 均不得出现在 argv、process title 或普通环境变量中。

请求通过有界、继承的专用只读 FD 传入；production 不使用可被其他 shell/process 继承的普通
stdin。请求是以下严格 discriminated union：

```text
DshMachineRequest =
  FreshResearchInvocation {
    schema_version: "karkinos.ai.dsh_invocation.v1",
    mode: "fresh_research",
    dsh_attempt_id,
    runtime_attempt_binding,
    invocation_envelope_fingerprint,
    logical_call_id,
    manifest/runtime/provider/export_authorization/provider_export_receipt/payload fingerprints,
    stage: propose | critique,
    messages: ordered sanitized messages,
    response_contract: {schema_version, json_schema_fingerprint},
    limits: {max_output_tokens, soft_sla_at, effective_deadline_at},
    provider_permission: "request_claim_v1"
  }
  | FreshCanaryInvocation {
    schema_version: "karkinos.ai.dsh_invocation.v1",
    mode: "fresh_canary",
    dsh_attempt_id,
    canary_attempt_binding,
    canary_invocation_envelope_fingerprint,
    logical_call_id,
    runtime_descriptor_fingerprint,
    canary_manifest_fingerprint,
    canary_authorization_fingerprint,
    payload_fingerprint,
    messages: ordered fixed non-financial messages,
    response_contract: {schema_version, json_schema_fingerprint},
    limits: {max_output_tokens, soft_sla_at, effective_deadline_at},
    provider_permission: "request_claim_v1"
  }
  | CollectExisting {
    schema_version: "karkinos.ai.dsh_invocation.v1",
    mode: "collect_existing",
    purpose: "research_completion" | "runtime_canary",
    dsh_attempt_id,
    collector_attempt_binding,
    original_attempt_binding_fingerprint,
    semantic_invocation_envelope_fingerprint,
    logical_call_id,
    existing_session_id + existing_turn_id,
    existing_provider_call_claim_fingerprint,
    existing_payload/runtime/provider/purpose_authorization fingerprints,
    provider_permission: "none",
    expected_provider_request_delta: 0
  }
```

只有两个 fresh variant 允许携带 `messages`；它们开始时没有 `physical_request_id`。Research
variant 绑定 research export authorization；canary variant 绑定独立 canary manifest/authorization
与 1/0/1 调用预算，二者不得互换。runner 创建 session 并 durable reserve turn 后，通过控制
channel 请求一次 `ProviderCallGrant`。父进程只有在原子
写入 `ProviderCallClaim`、提交 logical/physical/Token/金额预算并 fsync 后，才返回包含新
`physical_request_id` 与 claim fingerprint 的一次性 grant。没有 grant，runner 不得 submit user
turn。`CollectExisting` 不得含 messages、sampling override、credential grant 或任何 provider
permission；它只能读取已存在的 terminal event/result，整个收集的 provider request delta 必须
为零。

`ProviderCallGrantFrame` 必须是版本化、防重放 schema：

```text
schema_version + grant_nonce + provider_call_claim_fingerprint
purpose: research_completion | runtime_canary | bounded_lane_turn
stage_attempt_id/attempt_generation/lease_generation | canary_attempt_id
runtime_attempt_id + dsh_attempt_id + session_id + turn_id
workflow/lane identity: required for bounded_lane_turn
logical_call_id + physical_request_id + payload/runtime/provider fingerprints
issued_at + expires_at + single_use=true
```

runner 必须逐字段比对当前 process/session/turn，发送 `grant_consumed` event，并等待 parent fsync ACK
后才 submit user turn。grant 不能跨 attempt、lease、session、turn 或 lane 使用，过期、重复消费、
旧 lease 或 nonce mismatch 都在 submit 前终止。Bounded lane 的每个 provider turn 也独立执行该
握手。

Machine protocol 使用三个预创建、最小权限的 protocol channel；两个 fresh variant 另有第四个
one-shot credential FD，`CollectExisting` 不得收到 credential FD：

1. 只读 invocation FD 传入上述 request；
2. length-prefixed control/event `socketpair` 传输 typed frame。父进程把每个 event 追加到
   append-only event spool，`fsync` 成功后才 ACK；未 ACK 的 event 不可作为恢复事实；
3. result FD 指向 parent 预创建的 `0600` temporary spool。runner 写入一个 outer result 后
   `fsync`，父进程完成 schema/identity/fingerprint 校验，再以同目录 atomic rename 安装最终
   result 并 `fsync` 目录。

Credential FD 的 identity、broker receipt、handoff/read/close 时刻进入 attempt receipt；secret
内容不进入。Collect 只能使用 invocation/control/result channel，不能重新取得 provider
credential。

stdout/stderr 只是有 byte ceiling 的脱敏诊断 channel，production 应为空；即使出现合法 JSON，
也不是 authoritative result、provider receipt 或恢复依据。不能从 stdout、stderr、exit code、
PID 或 DSH session existence 推导 provider external effect。

result spool 必须且只能包含一个 exact canonical JSON object bytes，最多允许一个末尾 LF，不允许
其他 whitespace、日志、Markdown fence、多个对象或 normalization：

```text
schema_version: karkinos.ai.dsh_completion.v1
outcome_kind: completion | pending | failure
dsh_attempt_id + logical_call_id
attempt_mode: fresh | collect
research_stage_attempt_id: null | opaque string
canary_attempt_id: null | opaque string
original_attempt_binding_fingerprint: sha256
collector_attempt_binding_fingerprint: null | sha256
invocation_envelope_fingerprint + payload_fingerprint
physical_request_id: null | opaque string
provider_call_claim_fingerprint: null | sha256
grant_consumed_event_fingerprint: null | sha256
user_turn_submitted_event_fingerprint: null | sha256
runtime_descriptor_fingerprint
session: null | {session_id, turn_start_seq, turn_end_seq, turn_reason}
resolved_provider + resolved_model_revision
provider_request_id: null | opaque string
request_sent_at: null | rfc3339_utc
response_received_at: null | rfc3339_utc
external_effect: proven_not_sent | completed | unknown
usage: null | {input_tokens, output_tokens, cached_tokens, provider_cost}
finish_reason: null | string
sanitized_semantic_content: null | object
sanitized_semantic_content_fingerprint: null | sha256
session_flush_receipt_fingerprint: null | sha256
provider_terminal_receipt_fingerprint: null | sha256
runtime_disposition: null | structured_valid | output_invalid | schema_invalid
pending: null | {status: collect_pending | result_unknown}
failure: null | {status, class, code}
```

Conditional schema 必须逐 variant 校验：`proven_not_sent` 的 request ID/times/usage 全为 null；
`result_unknown` 可含 durable request ID/sent time，但 response time、terminal receipt、finish/usage
为 null；`collect_pending` 必须含 durable terminal receipt、response time 和 completed external effect，
但在 session flush 与 atomic result 成立前不得含 completion；`completed` 必须含 response time、
terminal receipt 与 finish/usage policy 所要求字段。Fresh 的 collector fingerprint 必须为 null；
collect 必须同时绑定 original 与 collector fingerprint。Pre-claim failure 的
physical/claim/grant-consumed/submit 全部为 null；claim/grant-issued 但未 consume 时
physical+claim 必填、grant-consumed/submit 为 null；grant-consumed 后、submit 前
physical+claim+grant-consumed 必填、submit 为 null，且 durable proof 仍可形成 `proven_not_sent`；
一旦 submit，四者全部必填。Collector 只能回显原调用已有的 lifecycle 字段，不能生成新
claim/grant。三个 outcome variant 的非本 variant 字段必须为 null。

outer envelope 由本地 runner 生成；模型只能产生随后被剥离 reasoning 并严格校验的语义 content。
Karkinos 在 subprocess
返回后先校验 outer schema、identity、字节数、UTF-8 与 fingerprint，再按模型响应契约的严格
JSON 白名单校验 `sanitized_semantic_content`，形成 immutable `ModelCompletion`。随后通用研究
validator 才执行 citation 与 Formula DSL 校验并另写 `ModelSemanticValidationReceipt`。Outer
result 不做 normalization；inner content 只允许“响应契约”已经列出的 surrounding whitespace
移除与 canonical reserialization。

DSH session、event/result spool、stdout/stderr、provider response/failure capture 和普通日志都
不得保存 raw reasoning 或 provider 的 reasoning 字段。Provider adapter 必须在 durable write 前
丢弃 raw reasoning，只留下 sanitized semantic content、状态、长度、usage 和 receipt；若无法在
内存边界完成该剥离，该 runtime 不合格。诊断 capture 也不得保存 credential、Research Pack
全文或 raw provider body。

### Durable spool ownership

Runtime host（research worker 或显式 canary executor）内唯一的 `DshSpoolStore` 拥有 spool；
runner 只获得预开的 FD，不能选择路径、
rename、unlink 或执行 GC。Trusted root 必须是绝对路径、owner-only `0700`、不位于 repo/home/
账户目录，root 与每个 entry 均通过 directory FD、`O_NOFOLLOW|O_EXCL`、owner/mode 检查和容量
ceiling 创建。Symlink、hard-link、path traversal、跨文件系统 rename 或现有未知 inode 一律拒绝。

`DshSpoolLifecyclePolicy` 是 versioned canonical object，由 strict config parser 加载、
`DshSpoolStore` 唯一消费并重算 fingerprint；不得只有悬空 hash。默认 completion policy 为：

```text
schema_version: karkinos.ai.dsh_spool_policy.v1
total_capacity_bytes: 536870912
max_entries: 2048
per_attempt_event_bytes: 8388608
per_provider_sanitized_response_bytes: 1048576
per_outer_result_bytes: 1048576
retention:
  adopted_or_completed_days: 90
  proven_not_sent_days: 30
  open_or_result_unknown_auto_gc: false
  quarantined_auto_gc: false
capacity_exhaustion: fail_closed_new_runtime_attempts
```

该 object 同时以 `RuntimeInstallScope` 的内容寻址 artifact 发布；config 中的内嵌 object 必须与
该 artifact payload 的 canonical bytes 完全相同，并通过 parent ref 进入 descriptor。不能按 policy
名称、版本号或“最新记录”查找替代内容。

Config 必须携带该 object 的 canonical bytes 与 fingerprint；descriptor 冻结 fingerprint，manifest
冻结 fingerprint 与具体 retention class。任何 policy 字段变化都产生新 policy artifact 与新
descriptor；Owner 可以收紧容量/byte ceiling 或延长 retention，放宽还必须取得新的 charter/
deployment review。Cleanup 使用 policy 中与 spool kind/outcome 精确匹配的 retention，不得使用
代码默认值或“最近 policy”。

Provider sanitized response、outer result 与 append-only event log 使用不同的 typed
`DshSpoolManifest`，每个 manifest 至少绑定：

```text
opaque_spool_ref + kind
experiment/stage/attempt/generation/lease | canary attempt
runtime_attempt_id + dsh_attempt_id + logical/physical call
root/policy fingerprint + inode/device/open-FD identity
created_at + byte ceiling + retention class
content length/fingerprint: null until fsynced
```

权威 lifecycle 为：

```text
allocated -> open -> fsynced -> atomically_committed -> adopted
                                             adopted -> cleanup_eligible -> cleaned
allocated/open/fsynced/committed --identity mismatch--> quarantined
```

Provider response 必须先 fsync sanitized bytes，再 commit manifest，之后
`provider_response_received` event 才能引用它。Outer result 先 fsync temporary entry，再由 store
CAS 校验 lease/attempt 后 atomic rename、fsync directory 并 commit。Lease takeover 只能通过 opaque
ref 读取并重验相同 manifest；旧 lease/child 的迟到 write 可以留作审计，但不能 commit/adopt。

只有 terminal outcome、Stage adoption、全部 parent artifact/receipt durable 且最短 retention 到期
后，entry 才能进入 `cleanup_eligible`。Adoption 必须先把 sanitized semantic bytes 提交到 canonical
immutable artifact store 并重验相同 content fingerprint；`ModelCompletion` 不能把可删除 spool
当作唯一内容来源。每次删除都写 `DshSpoolCleanupReceipt`。任何 open claim、
`result_unknown`、待 reconciliation、未采用 terminal result 或 quarantined entry 都禁止自动 GC；
容量不足时阻断新研究并告警，不能通过删除未知证据腾空间。普通账本只保存 opaque ref、kind、
长度、sanitized content fingerprint 与 manifest/cleanup receipt，不保存本机路径或 raw body。

### 进程、调用 claim 与恢复

一次 DSH subprocess 不等于一次 provider call。权威计数来自 runner 在每个真实模型请求前后
通过 event channel 交给 parent 并 durable ACK 的 typed provider-call records。
`dsh_subprocess_json_v1` 必须证明每个物理进程最多产生
一次上游请求；`dsh_bounded_lane_v1` 的每个 turn 都必须先返回 Karkinos 取得新 claim，不能在
runner 内自行继续下一次模型请求。

Provider lifecycle 使用三个不同 schema，不能把尚未完成的调用伪装成一条完整 receipt：

- `ProviderCallClaim`：purpose、stage attempt/generation/lease 或 canary attempt、runtime/DSH
  attempt、session/turn、logical/physical identity、grant nonce/expiry/single-use state、
  invocation/payload/runtime/provider/authorization 与 purpose-conditional export-receipt
  fingerprints、retry lineage、预算、frozen collect/global-reconciliation deadlines
  reservation/commit 与 claim time；不含尚未知的 `provider_request_id`、completed time 或 usage；
- `ProviderCallEvent`：append-only、单调 sequence 的 `grant_issued`、`grant_consumed`、
  `user_turn_submitted`、`request_sent` 或 `provider_response_received`。后者若要支持 pre-flush
  recovery，必须先把剔除 raw reasoning 的
  sanitized semantic response 写入受限 spool 并 fsync，再让 event 引用其 fingerprint；做不到时
  pre-flush crash 只能是 `result_unknown`；
- `ProviderCallTerminalReceipt`：`proven_not_sent`、`completed_success`、
  `completed_retryable_error` 或 `completed_terminal_error`。只有 completed variant 可以包含
  provider request ID、response time、finish reason 和 usage；`result_unknown` 没有 terminal
  receipt，只有 open claim/events 与 `ModelInvocationPending`。

进程状态至少遵循：

```text
reserved -> spawn_claimed -> process_started -> session_created
         -> turn_reserved
         -> provider_call_claimed + budget_committed -> grant_issued -> grant_consumed
         -> user_turn_submitted -> request_sent -> external_in_flight
         -> provider_response_received -> provider_terminal_recorded
         -> session_flushed -> result_committed -> output_validated
         -> succeeded | completed_invalid | failed_retryable | failed_terminal

spawn_claimed/process_started/session_created/turn_reserved
  --durable proof user turn not submitted--> proven_not_sent | failed_terminal
provider_call_claimed --durable proof user turn not submitted--> proven_not_sent
proven_not_sent --local launch allowance remains--> new RuntimeAttemptBinding/new dsh_attempt_id
proven_not_sent --local launch allowance exhausted--> Stage failed_terminal
user_turn_submitted/request_sent/external_in_flight
  --terminal receipt absent--> result_unknown
provider_response_received/provider_terminal_recorded --pre-flush interruption--> collect_pending
collect_pending --collect_existing, request delta 0--> session_flushed/result_committed
  -> succeeded | completed_invalid | failed_retryable | failed_terminal
collect_pending --collect deadline--> failed_terminal(external completed)
session_flushed -> result_committed
  -> succeeded | completed_invalid | failed_retryable | failed_terminal
```

`completed_invalid` 是 runtime 层“上游已完成但输出不可采用”的审计子态，在 Stage Ledger 中
确定性投影为 `failed_terminal`；它不能投影为 provider retryable，也不能追加模型调用。

实现必须满足：

- 在 spawn 前原子 claim StageAttempt、logical call、预算 reservation 与专属 event/result spool；
  同一 generation 只允许一个 lease owner；physical request 只在 session/turn reserved 后通过
  `ProviderCallGrant` 分配；
- 使用独立 process group、PID 加 OS process-start identity 防止 PID 复用；记录 started/TERM/
  KILL/exit 时间、exit code、signal、resource limit 与 output limit；
- 严格执行 `session_created -> turn_reserved -> provider_call_claimed+budget_committed ->
  grant_issued -> grant_consumed -> user_turn_submitted -> request_sent`。`turn_reserved` 不能包含
  已提交的 user content；若 DSH API
  把 user submit 与自动模型调用合为一步，claim 必须在调用该 API 之前完成；
- 父进程重启时先检查 attempt claim、PID/start identity、事件 spool、session 和 final result，
  不能先启动替代进程；
- 只有 typed durable event 证明失败发生在 user-turn submit 前，才能标记 `proven_not_sent` 并
  settlement 未使用的 provider capacity。user turn 一经 submit，即使缺少 `request_sent` event，
  也必须视为可能自动触发 provider call；
- `proven_not_sent` 终结当前 immutable runtime attempt，但可在 local-launch allowance 内于同一
  StageAttempt、attempt generation 和 `logical_call_id` 下创建新 `RuntimeAttemptBinding` 与新
  `dsh_attempt_id`；它不增加 logical/physical/provider-retry 计数，已 reservation 的 physical
  capacity 只按既有 settlement 归还。Allowance 用尽时 Stage 投影 `failed_terminal`，不得伪装为
  provider `failed_retryable` 或递增 Stage attempt generation；
- 只要请求可能已经发送而缺少可对账终态，非零退出、signal、hard timeout、输出溢出和本地
  KILL 都进入 `result_unknown`。终止本地进程不证明远端请求已取消；
- exit code 0 既不充分也不能替代 receipt。只有 completed provider terminal、session flush、
  atomic result、匹配 outer envelope 和合法 inner response 全部存在时才可 `structured_valid`；
- durable terminal receipt 已存在但 DSH turn/flush/result 不完整时，不得形成 `ModelCompletion`；
  先进入 `collect_pending`，只能 collect；到 collect deadline 才以
  `failed_terminal/external_effect=completed` 结束；
- `result_unknown` 消耗 substantive logical slot 和一个物理请求 allowance，禁止自动重发，只能
  对同一 session/turn/call 执行 `collect_existing` 或 receipt reconciliation；
- 只有 durable terminal receipt 明确分类为 retryable 429/5xx，才能在 retry allowance 和物理
  request ceiling 内创建新的 physical request。无响应、connection reset、timeout 或本地网络
  错误不能证明 provider 未处理；除非 typed transport evidence 证明 user turn/request 从未发送，
  否则不得重试；
- semantic/schema/citation/DSL invalid、模型拒绝和 `completed_terminal_error` 永不 retry；只有
  上述 `completed_retryable_error` 可以消费 retry allowance；
- 每次真实外发使用新的 `physical_request_id`，相同语义 retry 保留同一 `logical_call_id`、
  payload fingerprint 与 `retry_of`；
- unknown 到 global reconciliation deadline 后，Stage 以 terminal operational failure 结束，但
  底层 call 的 `external_effect=unknown` 永久保留；仍不得重试、改 runtime 或把 budget 退回；
- hard deadline 先对整个 process group 发送 TERM，经过冻结 grace 后 KILL。soft deadline 只
  告警，不改变 evidence status。

stock headless session 的存在、PID 退出或 stdout 文本都不能作为上述 record。若 runtime 不
提供 provider-call claim、request-sent、session-flush 和 collect-existing 协议，只能采用保守
at-most-once：进程一旦可能启动外发，任何不确定结果都 terminal fail closed，不能宣称
crash-safe resume 或 exactly-once。

### 受控 lane agent 模式

`dsh_bounded_lane_v1` 用于真正利用 DSH 的 session 编排能力，而不是把 DSH 当成不透明 Chat API
外壳。它是独立 workflow，不是默认十个 logical-call tournament 的 runtime 替换项，也不能复用
后者的授权、slot、stage mapping 或统计试验族。它仍不获得本机通用工具。每条 lane 使用独立
session；lane 之间不可见，refinement session 只获得 workflow descriptor 明确授权且由 selector
提供的 parent artifact。session 不跨 experiment、research family 或 runtime descriptor 复用。

该 workflow 必须定义并版本化四种不同 schema：

```text
DshLaneTurnEnvelope {
  schema_version, experiment/workflow/lane/lane_session/lane_turn identity,
  logical_call_id, turn_purpose, immutable semantic invocation fingerprint,
  runtime/provider/export fingerprints,
  parent_artifact_refs,
  actual_outbound_messages,
  payload_fingerprint + actual_outbound_bytes_fingerprint,
  response_union_schema_fingerprint,
  per-turn budget ceilings/policy + deadline-policy fingerprint
}

LaneToolCallFrame {
  schema_version, lane/session/turn/tool_call identity,
  operation: presealed_compile | presealed_evaluate,
  idempotency_key, parent fingerprints, strict typed arguments
}

LaneToolResultFrame {
  schema_version, matching call identity,
  disposition, sanitized result, evidence IDs,
  result fingerprint, trial registration and budget settlement refs
}

LaneFinalSubmit {
  schema_version, lane/session/final_turn identity,
  exactly_one_formula_draft, bounded parameter domain,
  economic claims, failure conditions, citation refs,
  complete lane lineage fingerprint
}
```

`lane_session_id`/`lane_turn_id` 是 parent 在 spawn 前分配的 Karkinos logical identity，不是 DSH
随后创建并报告的 observed session/turn ID；后者只进入 event、claim 与 machine outcome，二者
不得互相伪造。

Lane runtime 使用独立、同等级的 machine request union，不把 turn 塞进 completion schema：

```text
DshLaneMachineRequest =
  FreshLaneTurn {
    schema_version: "karkinos.ai.dsh_lane_invocation.v1",
    mode: "fresh_lane_turn",
    dsh_attempt_id,
    runtime_attempt_binding: exact canonical RuntimeAttemptBinding,
    lane_turn_envelope: exact canonical DshLaneTurnEnvelope,
    experiment/workflow/lane/lane_session/lane_turn/logical_call identity,
    payload/runtime/provider/export_authorization/export_receipt fingerprints,
    response_union_schema_fingerprint,
    limits: {max_output_tokens, soft_sla_at, effective_deadline_at},
    provider_permission: "request_claim_v1"
  }
  | CollectLaneTurn {
    schema_version: "karkinos.ai.dsh_lane_invocation.v1",
    mode: "collect_lane_turn",
    collector_attempt_binding: exact canonical CollectorAttemptBinding,
    original_attempt_binding_fingerprint + lane_turn_envelope_fingerprint,
    existing claim + observed DSH session/turn identity,
    experiment/workflow/lane/lane_session/lane_turn/logical_call identity,
    provider_permission: "none",
    expected_provider_request_delta: 0
  }
```

Lane result FD 使用独立但同等级严格的 outer union；它不能直接写一段 `LaneToolCallFrame` 或
`LaneFinalSubmit` 冒充进程结果：

```text
DshLaneMachineOutcome {
  schema_version: "karkinos.ai.dsh_lane_outcome.v1",
  outcome_kind: completion | pending | failure,
  attempt_mode: fresh | collect,
  dsh_attempt/logical_call + experiment/workflow/lane/lane_session/lane_turn identity,
  original_attempt_binding_fingerprint: sha256,
  collector_attempt_binding_fingerprint: null | sha256,
  lane_turn_envelope/payload/runtime fingerprints,
  physical_request_id + provider_call_claim/grant_consumed/turn_submitted fingerprints: null | value,
  observed_session: null | {session_id, turn_id, terminal_reason, flush_receipt_fingerprint},
  resolved_provider/model + provider_request/times/usage/finish/external_effect,
  provider_terminal_receipt_fingerprint: null | sha256,
  runtime_disposition: null | structured_valid | output_invalid | schema_invalid,
  semantic_outcome: null | LaneToolCallFrame | LaneFinalSubmit,
  pending: null | {status: collect_pending | result_unknown},
  failure: null | {status, class, code}
}
```

其 attempt-mode、pre-claim/grant-consumed/submit、terminal/flush、pending/failure 条件与
completion outer schema 完全相同。只有 `completion + structured_valid` 可含恰好一个严格验证的
semantic outcome，tool call 与 final submit 互斥；`output_invalid|schema_invalid` 的 semantic
outcome 必须为 null，仍消费已发生的调用预算且不得 transport retry。Completed provider error
使用 failure variant、真实 terminal receipt 与 retryable/terminal status，不伪装成 disposition。
`LaneToolResultFrame` 是本地 capability 的响应，经下一 turn 的 sanitizer/authorization 后才进入
新的 `DshLaneTurnEnvelope`，不是本次 machine completion。

Fresh lane turn 使用相同的四 FD、spool、credential broker 和 claim/grant/event lifecycle；collect
lane turn 没有 credential FD。`ProviderCallGrantFrame.purpose` 枚举为
`research_completion | runtime_canary | bounded_lane_turn`，bounded variant 还必须绑定
workflow/lane/session/turn，防止跨 lane 重放。

`DshLaneTurnEnvelope` 是每个 provider turn 的实际外发契约，不是初始 Research Pack 的别名。
每个 turn 对应一个 immutable semantic invocation 和稳定 `logical_call_id`；exact transport retry
只通过 `RuntimeAttemptBinding` 改变 DSH/physical/retry identity，并保持 turn purpose、messages、
payload、response union、model/profile 与 authorization 不变。
每一次外发前，都必须把 system/user/session history、parent artifact 摘要和将回送给模型的 tool
results 序列化为最终 bytes，重新经过字段 allowlist、隐私扫描、canonical fingerprint 与该 turn
的 export authorization 核验，并生成独立 `ProviderExportReceipt`。任何历史新增、顺序变化或
tool result 变化都会产生新 payload fingerprint。Local capability ID/token、FD、secret、budget
authority 与 issuer metadata 永远不得进入 model-visible messages 或 provider payload。
`ProviderExportReceipt` 绑定语义 payload/authorization，exact retry 确定性引用同一 receipt；
每次 physical send 的 reservation、effective absolute deadline、claim/grant 与发送 receipt 只存在于
attempt binding/provider records，不进入 lane envelope。

允许的模型可见工具最多包括：

- `formula.compile`：提交 Formula template，返回 DSL compiler 的 deterministic rejection 或
  validated AST fingerprint；
- `research.presealed_evaluate`：对已经注册的 AST/参数域运行受预算约束的 discovery/adaptive
  评估，只返回脱敏、标准化、带 evidence ID 的结果。

`LaneFinalSubmit` 不是工具调用，而是一个 model turn 的 terminal outcome。它必须与 tool-call
response union 互斥；一旦严格校验并 durable commit，当前 lane session 关闭，不得再调用工具或
追加 turn。提交只产生候选草稿，不能注册策略或触发 sealed test。

工具由 research worker 内的 Karkinos capability service 执行。Worker 为每个 lane 创建专用
Unix `socketpair` 或等价继承式全双工 FD，只把其中一个 FD 交给 DSH；禁止监听 TCP、使用通用
HTTP/MCP、暴露 filesystem socket path 或允许 method discovery。DSH 只持有绑定 experiment、
lane、session、stage、partition class、允许 operation、次数、deadline 和 runtime descriptor 的
短时 opaque capability。

本地 runner 在 provider 返回 tool intent 后才注入 `capability_id`；该字段不能出现在模型历史或
后续 provider payload。Capability channel 的每个 request/response 绑定
`capability_id`、单调 sequence、tool call ID、idempotency key、method、argument/result fingerprint
和 byte limit；未知 method/field、乱序、重复但不一致、超限、过期或 parent identity 漂移立即
关闭 channel 并终止 lane。Service 不返回数据库连接、文件路径、通用查询、完整 symbol/date
列表或 sealed capability。工具参数和结果都写入 Stage Ledger 和 `ToolCallReceipt`；每个新
Formula/参数向量必须在返回评估结果前进入统计试验 registry。

Tool invocation 物化为独立的 `LaneCapabilityAttempt`，其 operation 只能是
`presealed_compile` 或 `presealed_evaluate`；它不是顶层 `compile/search/validate`
StageAttempt，也不能产生 authoritative CandidateArtifact。每条 lane 完成 `LaneFinalSubmit` 后，
outer workflow 必须对该唯一草稿再执行一次 canonical 顶层 `compile -> search -> validate`；只有
这次结果可以进入 selector。探索期 tool output、模型复述和 DSH session state 都不能替代该
authoritative 路径。

charter 必须分别冻结每条 lane 的最大 model turns、provider requests、tool calls、独立 Formula
drafts、local backtests、输入/输出 bytes、wall time 与金额预算。一次 tool call 后若需要新的模型
turn 才能继续，该 turn 必须先返回 Karkinos 取得新的 provider-call claim，并消费 substantive
slot；不存在免费的“agent 内部思考轮次”。预算耗尽、capability 过期、工具重复、partition
越权或 session lineage 不一致立即终止 lane，不自动追加调用。

Bounded-lane charter 还必须冻结全 workflow 的 `local_launch_retry_ceiling`、
`fresh_process_start_ceiling`、`collector_process_start_ceiling` 与 `total_process_start_ceiling`。
Fresh ceiling 等于已授权 model turns、transport retries 与 local pre-submit retries 的精确和；
collector ceiling 等于需要恢复保障的 physical-call ceiling，默认每个 physical call/session 最多
一个 collector；total 必须严格等于 fresh+collector。任一 ceiling 缺失时 bounded lane 禁用，
不能继承 completion 的 22/12/34，也不能通过重启获得新额度。

模型不能通过工具选择 champion、访问 sealed 数据、写入 CandidateArtifact、调用 strategy
registry、批准 shadow 或触发订单。Outer Stage Ledger 仍拥有 `compile/search/validate/select/
freeze/sealed_test` 的 authoritative artifact；DSH session 只是提出与批评候选的可审计工作面。

受控 session 的恢复只允许：

- `collect_existing`：绑定同一 session、turn、logical call、payload、profile 和 model，只读取
  既有 terminal events/flush result，不能发送新 user message 或 provider request；
- `continue`：显式创建下一 model turn，必须拥有新的 StageAttempt/provider-call claim 与预算。

把新消息重新提交给旧 session、创建新 session 重放同一 turn，或把“session 已存在”推断为
请求已完成，均被禁止。

## 研究竞赛

默认有界竞赛保留最多五组 hypothesis + critique、十个实质 logical call，但用“先探索、
后利用”取代单一线性变异链：

1. 四条独立 hypothesis lane 从同一份冻结 charter 出发，彼此看不到结果。
2. 每个假设在本地编译，在 discovery 数据上搜索，在 adaptive validation 上评估，并接受
   一次模型 critique。
3. 确定性 selector 只使用 adaptive-validation 证据，最多选择一条 lane 进行第五次有界
   refinement。
4. 第五个 hypothesis 与 critique 用完十个实质 logical-call slot；最多两个 exact transport retry
   另行消费 retry allowance，但全部真实外发仍受十二个物理上游请求的绝对 ceiling 约束。
5. 确定性 adaptive-validation 规则冻结唯一 champion 及其本地选择参数。
6. 只对该 champion 执行一次 sealed 测试，期间不联系 provider。

该 workflow descriptor 必须精确列出十个 logical call 对五组 hypothesis/critique 的 stage/lane
映射、最多两个 retry 和十二个 physical request ceiling；owner 外发授权同时绑定三项数字。
它可以选择 HTTPS 或 `dsh_subprocess_json_v1` 承载每次受控 completion，但不隐含 bounded-lane
权限。`dsh_bounded_lane_v1` 必须使用新的 experiment、workflow descriptor、逐 turn/tool/trial
预算、payload family 与 owner authorization；不能在默认竞赛中临时开启工具、追加 agent turn，
也不能迁移旧串行五轮或此前 completion workflow 的 artifact。

本地确定性、随机 DSL 和简单 grid/evolutionary search 在匹配的计算预算下作为正式
challenger，而不是装饰性基准。如果模型在 sealed holdout 上没有增量，Karkinos 应只用它
生成解释、证伪想法和新特征建议。

Challenger 不是第二组可选优候选。Sealed 开封前必须把每个 comparator 的算法/code revision、
公式/参数、输入、随机 seed、计算预算和 adaptive evidence 冻结为 `SealedComparatorArtifact`。
Sealed evaluator 在 champion 的同一原子 consumption claim 中，对唯一 champion 与全部 frozen
comparators 使用相同 rows、费用、组合/成交语义和指标一次性计算，并写入同一
`SealedEvaluationReceipt`。Comparator 不获得独立 sealed capability，不能触发第二次开封，
sealed 结果也不能用于调整 comparator、替换 champion 或再选择 winner。

## Canonical 组合与信号语义

研究、验证、paper/shadow 和生产扫描必须共享唯一的组合构建实现。

每个交易日必须依次：

1. 加载 point-in-time 合格股票池与当前股票持仓；
2. 只用冻结决策 cutoff 前可知的信息计算全部信号；
3. 应用配置的信号滞后与下一交易日冻结执行窗口规则；
4. 先处理维护/退出，再处理新建仓；
5. 用一套冻结、确定性的规则统一排序所有合格买入候选；
6. 最多选择配置的四个股票槽位；
7. 应用现金、整手、集中度、换手、流动性和风险限制；
8. 使用经复核的 A 股成交模型模拟订单；
9. 每个交易日只记录一个组合 mark 和一个收益观察值。

股票遍历顺序不能影响订单、成交、权益、指标或胜出者。相同冻结输入下，历史引擎与每日
全池扫描必须得到相同候选集合。

## 参数搜索与公式复杂度

模型提出有界参数域，本地引擎只使用 discovery 数据选择参数。每个训练窗口内部执行嵌套
选择，并在下一验证窗口及两个 sealed 测试前冻结参数。

搜索必须记录每个公式、参数向量、拒绝、超时、重试和重复项。公式复杂度、有效自由度、
换手与敏感度都是明确惩罚项。

稳健性必须检查真正相邻的参数值以及多个行情 regime。一个最佳点周围全是弱结果时，即使
headline return 很高也不能晋级。

## 验证与统计门禁

真正的 walk-forward 必须在每个训练窗口内部完成选择，冻结候选后在下一个窗口执行，最后
只拼接未触碰的 forward returns。把一次全区间回测生成的 equity curve 分段，只是描述性
切片，不是 walk-forward validation。

每个 finalist 都必须在同一冻结 charter 下满足：

- 成本后效果为正，并超过预先声明的最小实质性阈值；
- paired 或 block bootstrap 对比的置信区间可接受；
- 对完整实验 registry 内每个语义不同的候选进行保守多重检验校正；完全相同的 transport
  retry 留在审计账本，但在统计试验族中只计一次；
- 回撤、换手、集中度、容量和 regime 稳定性通过；
- 相对人工确认 incumbent 非劣或更优；
- 同时与现金、适当 CSI/指数和全市场横截面基准比较；
- 两个 sealed 切分都没有实质性崩塌；
- 相同输入可复现完全相同的 bytes、信号、订单、成交与指标。

样本量允许时，应使用 Deflated Sharpe、PBO 或经过复核的同等保守方法。任何单一指标都
不能覆盖失败的数据、费用、风险或可复现门禁。

20 个交易日/约 50 笔订单的前瞻运行用于验证运营可靠性和语义一致性，本身不证明盈利。
收益证据和运营证据是两个独立的人工 GO/NO-GO 门禁。

## A 股成交模型

canonical simulator 必须版本化，并由基线与候选共享。至少建模：

- 经复核佣金、最低佣金、印花税、过户费及交易所舍入；
- `D-1` 信息 cutoff、`D` 日订单窗口和对应价格口径；
- 可配置 spread/slippage 与随规模变化的市场冲击；
- 100 股整手、现金预留、可卖数量与 T+1；
- 停牌、涨跌停、一字板和不可交易状态；
- 拒绝、未成交与部分成交；
- 单笔及全日累计 participation/capacity 限制。

零滑点只能作为显式诊断场景，不能满足晋级资格。

## Stage Ledger 与重启恢复

默认 tournament 研究必须由以下通用持久化 stage 组成，而不是继续增加事故专用 resume 分支：

```text
admit -> prepare
      -> [propose -> compile -> search -> validate -> critique] x 4 lanes
      -> select_refinement
      -> [propose -> compile -> search -> validate -> critique] x 1 refinement
      -> select_champion -> freeze -> sealed_test -> finalize
```

每个 `StageAttempt` 绑定 experiment manifest、stage 输入指纹、attempt generation、可能存在
的 provider-call claim、lease owner、heartbeat、deadline、checkpoint、状态、失败分类与
输出指纹。

使用 DSH 时，每个 provider stage 还必须拥有独立的 `DshAttemptReceipt` 与 append-only
进程事件流。它们记录 runtime/profile identity、logical/physical call、PID/start identity、
session/turn、provider records、credential broker、typed spool manifests/cleanup、stdout/stderr
和 external-effect 确定性，但不能
代替 StageAttempt。`compile/search/validate/select/freeze/sealed_test` 仍是 Karkinos 本地 stage；
bounded lane 中由模型请求的工具只物化为 `LaneCapabilityAttempt` 和统计试验记录，随后仍须
执行 workflow descriptor 指定的 authoritative 顶层 `compile/search/validate`。

必须具备：

- 原子 claim 和幂等完成；
- 可过期 lease 与确定性 stale-attempt takeover；
- 从任意已完成 stage 崩溃安全续跑；
- 不确定的 provider call 必须留痕，不能静默重试；
- 只对 durable provider terminal receipt 明确分类的 retryable 429/5xx 有界重试；无响应网络
  错误进入 `proven_not_sent` 或 `result_unknown`，不能靠错误字符串猜测；
- 实质 logical-call ceiling、retry allowance 与 physical upstream-request ceiling 是三个显式
  预算；
- 每个 stage deadline 与总运行 deadline；
- provider/model/runtime/profile/prompt/tool policy 漂移时创建新实验，而不是续跑旧实验；
- 用通用恢复替换 citation、truncation 或特定轮次专用表。

## 运行隔离与调度

目标部署中，AI 研究必须运行在独立的收盘后 `research-worker` 进程，使用专属 executor 和
短时有界数据库事务。API 与 Daily Decision service 只创建或读取 durable research job/status，
不执行研究工作、不持有 DSH child PID，也不消费 runtime result channel。

Research DSH 只能由该 worker 作为受限子进程启动；非金融 canary 只能由显式 operator-only
canary executor 依据独立 authorization 启动。两者是仅有的 launch authority，均不接受任意文件
或页面 payload。API/read endpoint、Web 页面、health check、应用 startup、Daily Decision、
票据生成和生产 scheduler 均不得直接或间接拉起 DSH。Runtime host 与
DSH 使用独立 CPU/内存/文件描述符/进程数限制；DSH 卡死、生成后代进程或耗尽资源时只能使
当前 research stage/canary 失败，不能挤占 Daily Decision 的 executor、连接池或绝对 deadline。

准入必须在加载 universe 或运行基线前完成廉价检查：交易日历、收盘后窗口、policy、与 capital mode 匹配的
成本模型（normalized-notional discovery 使用 canonical 预估；未来 account-bound qualification 才需已复核费用）、
既有 run/lease 和不可变研究输入可用性。Account Truth 只在 charter 明确进入本地账户
容量或 shadow 准入 stage 时检查，不得阻断归一化名义资金下的 Formula discovery。

积压补跑只能发生在显式收盘后维护窗口。默认 Asia/Shanghai 09:00–10:00 为 Daily Decision
隔离 blackout：禁止启动或恢复 universe preparation 和本地研究回测；DeepSeek 模型发送还受
下述更宽的计费窗口约束。08:30–09:00 仍可用于收口已准入的 overnight research，但完整批次
必须在 09:00 前完成，越过该 deadline 的结果不能写入 completed research artifact 或当日
authoritative outcome。Daily Decision 继续使用独立绝对 deadline。

DeepSeek 计费时段由独立、版本化的 provider call-window policy 负责，不得混入 HTTP transport、
业务 route 或 `after_close_time`。北京时间周一至周五 `[09:00,12:00)`、`[14:00,18:00)`
为禁止发送窗口，12:00 与 18:00 边界可发送，周末全天为低谷。所有 DeepSeek 出站调用——包括
策略 hypothesis/critique、外部回测报告、外部记忆分析和连通性 canary——在 service admission
与 provider send edge 使用同一 policy；手工 API 不提供 force bypass。

完整策略迭代还必须满足收盘后、下一工作日 09:00 前完成的 overnight 约束。编排器在加载 universe、
运行基线或 claim research run 前，为十次串行调用预留 125 分钟连续低谷余量；因此正常工作日
从 18:00 起跑，午间两小时不启动完整批次，早晨余量不足时延期到当日 18:00。单次 provider
send 在调用额度 claim 前及实际发送前再次检查当前窗口，并至少保留 600 秒 hard timeout 加
5 秒收口余量。批次准入时冻结当前低谷段的下一高峰左边界为 attempt deadline；基线、
每轮候选以及最终 artifact 发布后均复核该 deadline，09:00 后完成的批次不得发布为 completed。
整批尚未 claim 时的窗口延期是
`deferred`，不得计为失败、不得占 provider call/token/retry budget，并必须返回
`next_eligible_at` 与 policy fingerprint；已运行批次若异常跨界，后续调用仍须在 claim/send 前
fail closed，且 proven-not-sent 记录不得消耗实际调用预算。
standing research policy 必须持久化 call-window schema、policy ID 与 fingerprint；run 输入也绑定
同一版本，provider 调价时创建新 policy revision，不能原地改写旧运行的计费语义。

每日路径只读取已晋级 artifact 与当前 canonical facts。provider 故障、模型缓慢、研究进程
崩溃或调用预算耗尽，都不能延迟每日 ticket/NO-ACTION。

## AI 效果与运营证据

系统在不暴露私有账户事实的前提下记录：

- 合法响应率与 AST 可编译率；
- 独立假设和算子族多样性；
- provider 延迟、Token、费用、重试、超时和失败类型；
- runtime/profile/model identity、DSH 启动与进程开销、实际上游调用数、工具调用数以及任何
  hidden-call/profile-contract violation；
- 本地计算时长和候选数量；
- 相对匹配非模型基线的 adaptive-validation 与 sealed-holdout lift；
- 对预期 regime 和失效条件的校准程度；
- paper/shadow 信号、订单、成交和组合语义一致性；
- 前瞻存活、回撤、换手和成本后基准比较。

provider success 只表示契约调用完成，不表示投资成功。服务在运行、mock 测试全绿或十个
实质 logical call
完成，都不能证明模型提高了策略质量。

## 人工生命周期

历史研究只能产生以下状态：

- `no_candidate`：没有 finalist 通过全部确定性门禁；
- `candidate_for_shadow_review`：一个精确 finalist 可供人工复核；
- `research_invalid`：实验或证据不可复现；
- `research_failed`：运营故障导致无法完成。

只有 `candidate_for_shadow_review` 可以获得绑定指纹的人工批准，生成只用于有界
paper/shadow 的 `shadow_admitted_artifact`。第一次批准不会替换 incumbent、修改资本、
创建订单或联系券商。

经过另行复核的前瞻运行后，人工可以对精确候选和证据期间记录 GO、继续或 NO-GO。GO 后
仍需第二次显式、绑定指纹且可撤销的 production-assignment 决策；在此之前 Daily Decision
继续使用当前 incumbent。回滚必须显式发生并立即阻止后续使用，同时保留全部历史证据。

## 失败语义

- 输入缺失或过期：外发前阻断。
- Dataset 或 manifest 漂移：使实验失效，不原地修复。
- Formula 不支持或有歧义：拒绝候选，不执行。
- Provider 在未知是否返回时超时：进入 `result_unknown`，只允许 collect/reconciliation；禁止
  自动 retry，也不能推断成功或未发送。
- DSH 在可能发送 provider request 后崩溃、被杀或丢失结果：进入 `result_unknown`，只允许
  `collect_existing` 对账，不自动启动新 session 或切换 HTTPS。
- DSH exit 0 但 machine envelope、session flush、provider terminal receipt、usage 或 inner
  schema 缺失：仅 provider terminal durable 而尚未 flush 时是 `collect_pending`，deadline 后才是
  `failed_terminal/external_effect=completed`；terminal+flush 已 durable 但 output/schema 无效才是
  completed-invalid；没有 durable terminal 才是 `result_unknown`。三者都不从 stdout 猜候选。
- DSH executable/profile/plugin/model/tool policy 漂移：外发前阻断；若外发后才发现则使实验
  失效，不能把结果绑定到旧 charter。
- 本地回测或指标失败：保留 stage 证据，不生成候选。
- Sealed 测试失败：不产生 winner，也不能在同一实验中把结果反馈给新轮次。
- Research worker 崩溃：通过 lease generation 和 checkpoint identity 恢复，不能重复不确定
  外部调用。
- 与每日窗口冲突：推迟研究；每日 Decision 获得资源优先级并保持 provider-free。

研究 fail closed 表示“没有可晋级 AI 候选”，不会覆盖 incumbent，也不会独立决定每日交易
结果是 NO-ACTION。

## 验收标准

只有确定性证据证明以下条件后，才能称本文设计完成。

### 数据与语义

- Point-in-time 成员关系、复权、公司行动和可交易 identity 内容寻址且可重放。
- 研究、验证、paper/shadow 和每日扫描共享唯一组合构建器与成交模型。
- 股票顺序不能改变信号、订单、成交、每日权益或指标。
- 决策时点之后才可知的数据不能进入该决策。

### 统计有效性

- 参数和公式选择在训练切分内部完成。
- 候选冻结前无法访问 sealed 时间与股票池切分。
- 每个 attempt 与 retry 都进入审计账本；每个语义不同的候选在统计试验族中恰好计一次。
- Incumbent 与 benchmark identity 必须写入 manifest，不能用“最近保存回测”的隐式
  fallback 满足最终验证。
- 最终证据包含不确定性、实质性、incumbent、现金和市场基准对比。

### AI 增量价值

- 使用不含私有账户数据的 live provider canary 验证精确 model/prompt/schema 契约。
- 匹配实验将模型与确定性及随机搜索对比。
- 使用模型的理由来自 sealed-holdout 增量或研究效率，而不是 API 调用成功。

### 可靠性与安全

- Crash/restart 测试能恢复每个 stage，且不重复不确定调用。
- 研究不能在每日关键 blackout 窗口启动或恢复。
- Provider 故障不能延迟或修改 Daily Decision 结果。
- 外发 payload 不包含禁止的账户、券商、权限或绝对规模事实。
- 任何 stage 都不能自动晋级策略、修改资本、创建或提交券商订单。
- HTTPS 与 DSH single-completion runtime 消费相同 canonical Research Pack bytes；bounded lane
  每个 turn 的实际 outbound bytes 重新经过同一 sanitizer、citation、DSL 和 authority pipeline。
- DSH profile composition、executable、Node/package closure、provider/model route 和 tool
  catalog 均可重算指纹；任何漂移在 transport 前或结果接受前阻断。
- Controlled completion 的一个 provider claim 恰对应至多一个上游请求；title、internal retry、
  compaction、search 和 child-agent 隐式调用均为零；logical/retry/physical ceiling 分别守恒。
- argv、环境、cwd、普通日志与 UI 不泄露 Research Pack、credential、账户事实或诊断
  stdout/stderr；raw reasoning 在 session、spool、capture 与 persistence 中均不存在。
- transport 前、transport 后、provider 完成前后、session flush 前后和结果提交前后的 crash
  injection 都不会造成未解释的重复外发。

### 前瞻运行

- Plan、simulation 与 observed execution 在同一策略和组合语义下完成对账。
- 运营可靠性 gate 与收益证据 gate 始终分离。
- 人工批准、暂停、回滚和 NO-GO 路径均绑定指纹、有界、可撤销并完成演练。

## 明确拒绝的设计

- 让模型直接从全市场或当前持仓中挑股票。
- 向模型发送原始账户或券商数据，让它决定交易规模。
- 让模型根据自己的回测摘要决定 winner。
- 把 adaptive-validation 结果复用为最终 OOS。
- 不保留 lineage 地并行依赖型 refinement 轮次。
- 仅通过提高 timeout 或允许早盘运行来解决延迟。
- 从 Karkinos 仓库目录直接执行 stock `dsh --profile headless`，并把最后一段 stdout 当成
  canonical response。
- 因为 DSH 进程在本机，就省略 external export authorization、provider identity 或网络出口
  审计。
- 复用个人 `DSH_HOME`、个人 settings/skills/home patch、项目 `.env` 或动态 `--patch`。
- 允许 DSH 内部 title、retry、compaction、Web、subagent 或其他未 claim 的 provider call。
- 把 exit code 0、session 存在、PID 退出或 stderr 文本当作“请求完成/未发送”的证明。
- 在 `result_unknown` 后自动重放 prompt、创建新 session 或改用另一 runtime。
- 自动晋级模型候选、自动分配资本或自动提交订单。

## 每次实验必须冻结的人工参数

启动任何 experiment 前，owner 必须显式冻结：

- discovery、validation 与 sealed 切分的精确日期和规模；
- point-in-time universe 与公司行动数据源；
- 生产组合排序规则和成交模型校准；
- 基准集合、最小实质性阈值与多重检验方法；
- 精确 provider/model/runtime/profile revision、prompt contract、tool policy、workflow descriptor、
  logical-call allocation、retry allowance、physical-request ceiling 与金额预算；
- DSH adapter kind、profile/composed-config fingerprint、允许的 provider endpoint、machine
  protocol、环境/网络/文件隔离、stdout/stderr ceiling、fresh/collect/total process ceilings 与进程
  终止 policy；
- 若使用 bounded lane，逐 lane 的 model turns、tool calls、Formula drafts、本地回测、Token、
  金额和 wall-clock 上限，以及每个 outbound turn 的 payload family 与 export authorization；
- paper/shadow 时长，以及统计和运营两个独立 GO/NO-GO 阈值。

上述配置只定义研究边界，不授予 provider、策略、执行或资本权限。

## 附录 A：核心 Artifact Schema

所有 artifact 使用 canonical JSON：对象键按字典序排列，Decimal 以十进制字符串表示，时间统一
为 UTC RFC 3339，集合先按稳定 identity 排序。`payload_fingerprint` 为 canonical JSON 的
SHA-256；任何具有经济语义的字段变化都产生新 artifact，禁止原地覆盖。

```text
schema_version: string
artifact_type: string
artifact_id: string
scope:
  ResearchScope {
    kind: "research",
    experiment_id: string,
    research_manifest_fingerprint: sha256
  }
  | RuntimeCanaryScope {
    kind: "runtime_canary",
    canary_id: string,
    canary_manifest_fingerprint: sha256
  }
  | RuntimeDescriptorScope {
    kind: "runtime_descriptor",
    runtime_descriptor_id: string,
    descriptor_manifest_fingerprint: sha256
  }
  | RuntimeInstallScope {
    kind: "runtime_install",
    install_id: string,
    installed_closure_manifest_fingerprint: sha256
  }
parent_refs: ordered[{artifact_type, artifact_id, payload_fingerprint}]
producer_identity: {component, code_revision}
created_at: rfc3339_utc
payload_fingerprint: sha256
payload: object
```

四个 scope 严格互斥且对应字段全部必填；禁止用 null、空字符串、伪造 experiment 或同时填写
多个 scope 来复用 schema。Credential/spool/attempt/cleanup artifact 跟随其实际 research 或 canary
parent scope；runtime descriptor 使用 descriptor scope，DSH install receipt/policy 使用 install
scope。DSH descriptor 强制 parent-ref 精确 install receipt/policy；HTTPS descriptor 不得伪造该
parent。Research 与 canary 再通过 parent refs 精确引用 descriptor。

| Artifact | 必填 payload | 核心不变量 |
| --- | --- | --- |
| `ResearchCharter` | provider/model/runtime/profile/prompt/sampling/tool policy、workflow descriptor、DSL/组合/成交/指标版本、数据与四类切分、benchmark、预算、owner export authorization | 第一次 provider call 前冻结；任何字段变化创建新 experiment |
| `WorkflowDescriptor` | workflow ID/version、拓扑、lane/stage/call allocation、selector、停止条件、logical/retry/physical 与 purpose-specific process ceilings | 串行链、默认 tournament 与 bounded lane 互不兼容；不能迁移 authorization、预算或 artifact |
| `ResearchDatasetTruth` | point-in-time security master、交易日历、raw/adjusted bars、公司行动、tradeability、benchmark rows、partition IDs、receipt fingerprints | consumed rows 有序且内容寻址；sealed partition 不授予任何 pre-freeze stage 读取能力 |
| `StageAttempt` | stage、generation、input fingerprint、lease、deadline、call claim、checkpoint、status、failure class、output fingerprint | 同一 generation 只有 lease owner 可完成；输入漂移不能续跑 |
| `DshRuntimeInstallReceipt` | registry/source/installer、install-root、ordered closure manifest、final realpath、owner/mode/atomic-commit proof | 只从 trusted registry 按 fingerprint 读取；descriptor 强制引用，实际 bytes/权限持续重验 |
| `DshSpoolLifecyclePolicy` | schema version、总容量/entry/typed-byte ceilings、逐 outcome retention、unknown/quarantine GC 与容量耗尽行为 | install scope 下内容寻址；config 嵌入的 canonical payload 必须逐字节一致，store 只消费该精确版本 |
| `ModelRuntimeDescriptor` | non-self-referential descriptor manifest、common adapter/provider/model/deadline/retry identity + HTTPS wire/TLS/client variant 或 DSH install/profile/process/spool variant | descriptor scope 下双 fingerprint；只允许一个 adapter variant，DSH 强制 install parents，HTTPS 禁止伪造它们 |
| `ProviderExportReceipt` | purpose、workflow/stage/lane/turn、logical call、payload family、authorization、sanitizer/serializer/scanner versions、实际 canonical bytes ref/length/fingerprint、runtime/provider | 发送前形成并 fsync；exact retry 复用同一 receipt；不得用构造前 object 或事后重算替代实际 bytes |
| `ReasoningPersistenceAbsenceReport` | runtime/attempt scope、被扫描的 session/event/result/stream/provider-capture/log manifests、scanner/version、逐 surface 结果 | manifest 覆盖全集且命中数为零；缺 surface、截断或 scanner error 不是通过 |
| `ModelInvocationEnvelope` | workflow/stage/lane、logical call、manifest/runtime/provider/export-authorization/export-receipt/payload fingerprints、messages/schema、预算/deadline policy | 不含具体 reservation、stage/DSH/physical/provider execution ID；语义字段变化产生新 logical call |
| `CanaryInvocationEnvelope` | canary/logical ID、runtime/canary-manifest/authorization/payload、固定消息/schema、provider 1/0/1 与 adapter-specific runtime 预算 | 不伪造 research experiment/stage/export authorization；HTTPS/DSH budget variant 互斥 |
| `RuntimeAttemptBinding` | pre-grant runtime attempt、research stage/workflow/logical lane/turn、generation/lease、invocation、logical/local reservation、时间锚与 absolute deadlines、HTTPS attempt 或 DSH fresh+total process-slot union | 不含 physical/grant/observed process-session；HTTPS 不含 DSH ID/slot；binding 永不原地修改 |
| `CanaryAttemptBinding` | pre-grant canary/runtime attempt、canary manifest/authorization、invocation、logical/local reservation、absolute deadlines、HTTPS attempt 或 DSH fresh+total process-slot union | 不含 experiment/stage/physical/grant/observed process-session；再次 canary 使用新 binding 与 evidence family |
| `CompletionCollectEnvelope` | purpose、原 invocation/binding/call/session/turn/runtime/payload/authorization | 不含 messages/credential/provider permission；request delta 必须为零 |
| `CollectorAttemptBinding` | 新 collector runtime/DSH attempt、原 binding、lease、frozen collect/global-reconciliation 与 effective absolute deadline、spool refs；DSH atomic collector+total process-slot reservation | 只授权本地收集；started reservation 只能 attach/adopt、不能再次 exec，restart 不延长 deadline/额度 |
| `ProviderCallClaim` | purpose、stage/canary/workflow/lane/runtime/DSH/session/turn、logical/physical、grant nonce/expiry、invocation/payload/runtime/provider/authorization、purpose-conditional export receipt、retry/预算、frozen collect/reconciliation deadlines | user turn submit 前 durable；不含尚未知的 `provider_request_id`、completed time 或 usage |
| `ProviderCallEvent` | claim、单调 seq、grant-issued/consumed、turn-submitted、request-sent/response-received、sanitized response spool fingerprint | append-only 且 fsync 后才 ACK；response event 不保存 raw reasoning |
| `ProviderCallTerminalReceipt` | proven-not-sent 或 completed variant、conditional provider request ID/times/usage/finish/failure、external effect | completed 字段只存在于 completed variant；unknown 没有 terminal receipt |
| `DshAttemptEvent` | attempt/lease generation、单调 seq、previous-event fingerprint、进程/session/turn/provider/result transition | append-only；旧 lease 事件可审计但不能提交 authoritative terminal state |
| `CredentialBrokerReceipt` | purpose、runtime、research stage/workflow/lane/turn 或 canary、authorization、DSH attempt、secret-reference version、FD handoff/read/close status | canonical owner 是 runtime persistence；不含 secret value/hash |
| `ResearchPackPrivacyReport` | scope kind、sanitizer/allowlist/scanner/schema versions、payload family、expected/observed claim 与 export receipt 全集、adapter parity、禁止字段扫描、reasoning-absence report ref | install-scope fixture report 不授权真实外发；research-scope report 必须覆盖该 experiment 每个实际 outbound turn/request，missing/extra/banned hit 均为零 |
| `DshSpoolManifest` | opaque ref/kind、attempt/lease/call、root/policy、inode/FD、ceiling/retention、length/content fingerprint | provider-response/event/result 分型；unknown/open/quarantined 禁止 GC |
| `DshSpoolCleanupReceipt` | manifest、terminal/adoption refs、retention expiry、deleter/code、deleted-at | 只有 cleanup-eligible 可生成；不能删除未知证据 |
| `DshAttemptReceipt` | invocation、runtime/profile、process-slot reservation/settlement、argv/cwd/env policy、PID/start token、session/turn、provider/credential/spool records、streams、external effect、budget settlement | 由有序 events 折叠；exit/PID/stdout 不能单独证明成功或未外发 |
| `ModelCompletion` | invocation/attempt refs、resolved provider/model、adapter terminalization；DSH turn+flush、usage/finish、sanitized semantic-result ref、runtime disposition | 只表示 durable completed call；仅 `structured_valid` 可进入 downstream validator，永不保存 raw reasoning |
| `ModelSemanticValidationReceipt` | completion、citation catalog、DSL/semantic validator versions、validation disposition、typed errors | 不回写 completion；仅 `semantic_valid` 可产生候选输入 |
| `ModelInvocationPending` | invocation、origin/collector binding、open claim/events、status、external effect、frozen collect/global-reconciliation deadlines | collect-pending/result-unknown 只能 collect/reconcile，不能新外发或延长 deadline |
| `ModelInvocationFailure` | invocation/attempt refs、runtime-attempt terminal status、external effect、typed failure、record refs、budget settlement | 不可继续 collect；DSH proven-not-sent 仅允许有界 local new attempt，provider retryable 只来自明确 terminal receipt |
| `LiveHttpsCanaryReceipt` | canary envelope/attempt、HTTPS descriptor、logical/physical/provider、client/wire/TLS/credential/result/call accounting | provider 恰好 1/0/1；禁止 DSH install/process/FD 字段，不授权研究或策略 |
| `LiveDshCanaryReceipt` | canary envelope/attempt、DSH descriptor/install、logical/physical/provider、fresh/collect process、credential、channels/result/call accounting | provider 恰好 1/0/1、process 不超过 1/1/2，不授权研究或策略 |
| `DshLaneTurnEnvelope` | logical lane-session/turn、logical call/purpose、semantic invocation、实际 outbound messages/bytes、parent refs、export receipt、预算 | exact retry 保持语义 identity；每 turn 重做隐私扫描/授权，capability 不外发 |
| `DshLaneMachineOutcome` | fresh/collect、binding、lane-turn、claim/grant/submit、observed session/flush、terminal/provider/usage、disposition/semantic/pending/failure union | outer lifecycle 条件与 completion 同级；只有 structured-valid completion 含互斥 tool-call/final-submit，invalid 消耗预算且不 retry，collect 零外发 |
| `LaneCapabilityAttempt` | typed operation、tool frames、trial registration、budgets、sanitized result | 只是 pre-sealed exploratory evidence，不替代 authoritative stage |
| `LaneFinalSubmit` | 唯一 draft、参数域、经济论断/失效条件/citation、完整 lane lineage | 提交后必须重新走顶层 canonical compile/search/validate |
| `CandidateArtifact` | Formula AST、参数、复杂度、组合 policy、训练与 adaptive evidence、试验族 identity、critique、parent lineage | 不包含 sealed 结果、账户绝对值、权重、订单或晋级状态 |
| `SealedComparatorArtifact` | generator/algorithm/code、公式/参数/seed、匹配计算预算、adaptive evidence、冻结输入 | 只作不可选优 comparator；开封后不可修改，不单独取得 sealed capability |
| `SealedPartitionConsumptionReceipt` | research family、partition refs、evaluator、原子 access claim、claimed-at time | 必须在读取 sealed bytes 前 append；一旦 claim，评估失败或崩溃也保持 consumed |
| `SealedEvaluationReceipt` | champion、frozen comparator refs、单一 consumption receipt、同 rows/费用/语义结果、统计校正、gate | 唯一 champion + 不可选优 comparators 原子计算；不得另开 partition 或开封后选优 |
| `ShadowAdmittedArtifact` | candidate/receipt fingerprints、reviewer、允许范围、起止时间、风险/资金上限、revocation policy | 只授权 paper/shadow，不替换 incumbent，不创建真实订单 |
| `ProductionAssignmentArtifact` | shadow artifact、完整 forward evidence、GO review、账户/费用/风险 policy、effective/expiry time、rollback policy | 必须是第二次独立人工决定；权限有界、到期且可撤销 |

Schema 兼容只允许增加不影响语义的 optional 字段。字段删除、默认值变化、枚举含义变化、
算法版本变化或 fingerprint 规则变化都必须提升 major schema，并创建新 experiment。
消费者禁止用“最新记录”推断身份，必须重验精确 parent refs；人工批准、撤销与回滚使用
append-only 决策 artifact，不能修改原记录。
Shadow 与 production 的当前有效性分别由原 artifact、到期时间和独立
`ShadowRevocationReceipt`/`AssignmentLifecycleReceipt` 投影；任何撤销、暂停或回滚都不得
回写原批准。sealed consumed 状态同理由 consumption receipts 投影，不能修改 DatasetTruth。

## 附录 B：Stage 状态机、Lease 与调用预算

### Stage 输入输出

下表是默认 tournament 的冻结 stage mapping。Bounded lane 不得套用该表冒充相同 workflow；
它先按自身 descriptor 产生 `LaneFinalSubmit`，随后只把最终 draft 交给表中的 authoritative 本地
stage。Bounded-lane run 相对于默认 tournament 使用不同 experiment/authorization/budget family，
但该 run 内从首个 turn、tool trial、`LaneFinalSubmit` 到 canonical stages 必须保持同一
experiment、charter 与统计试验族；不得在 handoff 处偷换 experiment 或丢失 lineage。

| Stage | 主要输入 | 主要输出 | Provider |
| --- | --- | --- | ---: |
| `admit` | charter、日历、policy、export authorization | admission receipt | 否 |
| `prepare` | dataset truth、benchmark、费用与 research notional | normalized Research Pack | 否 |
| `propose` | Research Pack、lane identity | hypothesis + Formula template | 是 |
| `compile` | Formula template、DSL version | validated AST 或 rejection | 否 |
| `search` | AST、parameter domains、discovery partition | frozen local parameter result | 否 |
| `validate` | candidate、adaptive partition、benchmarks | adaptive evidence | 否 |
| `critique` | 精简 candidate evidence | model critique | 是 |
| `select_refinement` | 四条独立 lane evidence、固定 tie-break | 唯一 refinement parent | 否 |
| `select_champion` | 四条 lane 与 refinement evidence、固定 tie-break | 唯一 champion identity | 否 |
| `freeze` | champion 全量本地 binding | frozen champion artifact | 否 |
| `sealed_test` | frozen champion、sealed capability | sealed receipt | 否 |
| `finalize` | 全部 receipts 与 gates | `no_candidate` 或 shadow-review candidate | 否 |

### 状态转移

```text
planned -> leased -> running -> succeeded
                    |      -> failed_retryable -> planned(new attempt)
                    |      -> failed_terminal
                    `-> external_in_flight -> succeeded | failed_retryable
                                           -> failed_terminal | collect_pending | result_unknown
collect_pending --collect_existing--> succeeded | failed_retryable | failed_terminal
collect_pending --collect deadline--> failed_terminal(external_effect completed)
result_unknown --receipt reconciliation--> succeeded | failed_retryable | failed_terminal | collect_pending
result_unknown --global reconciliation deadline--> failed_terminal(external_effect remains unknown)
leased/running --lease expired, no transport--> leased(same attempt, lease_generation+1)
external_in_flight --lease expired--> result_unknown
running --runtime proven_not_sent, local allowance remains--> running(new runtime binding, same StageAttempt/logical call)
running --runtime proven_not_sent, allowance exhausted--> failed_terminal
```

- `succeeded` 与 `failed_terminal` 为不可变终态；`collect_pending` 和 `result_unknown` 是只能
  collect/reconcile、不能新外发的非终态；`failed_retryable` 终结当前 attempt，但可按
  policy 新建 attempt。
- 只有输入 fingerprint 完全相同时才能复用 `succeeded` 输出。
- Stale takeover 只通过 compare-and-swap 递增同一 attempt 的 `lease_generation`；只有终态
  `failed_retryable` 才递增 `attempt_generation` 并新建 attempt。
- Runtime `proven_not_sent` local retry 不改变 Stage `attempt_generation`、logical call 或 provider
  retry 计数，只创建新 runtime/DSH attempt；allowance 用尽后 Stage 为 `failed_terminal`。
- 旧 lease generation 后到结果不得写入 authoritative artifact；只要 provider transport
  可能发生，lease 过期就必须进入 `result_unknown` 并先对账，不能重新外发。
- `result_unknown` 表示外部效果可能发生，只能通过相同 request/logical-call identity 的 provider
  record 对账为确定成功或失败；自动重发被禁止。运营 deadline 可以结束 stage，但不能把底层
  external effect 改写为 `proven_not_sent`。
- 每次物理发送使用新 `physical_request_id`；相同语义 retry 共享 `logical_call_id` 与 payload
  fingerprint。
- 本地 deterministic stage 可重算，但输出 fingerprint 必须与已持久化值完全一致。

### 默认预算

| Policy | 默认值 | Fail-closed 规则 |
| --- | ---: | --- |
| substantive logical calls | 10 | 精确映射五组 hypothesis/critique；预算耗尽即停止 |
| transient transport retries | 全实验 2 次、每 logical call 最多 1 次 | 仅限 durable terminal receipt 的 retryable 429/5xx；无响应和语义错误不得重试 |
| total physical upstream requests | 12 | 包含首发与 retry；任何 actual 或 possibly-sent 请求都计入，绝对不得突破 |
| DSH local launch retries | 每 logical call 全生命周期最多 1 次 | 只有 typed record 证明 user turn 未提交且 provider request 为零才可使用；不消费 provider retry |
| DSH process starts | completion workflow 总计 34：fresh ≤22，collect ≤12 | 10 initial + 最多 10 local retry + 2 transport retry；每个 physical call/session 最多 1 collector，新 `dsh_attempt_id` 不重置 ceiling |
| DSH canary process starts | fresh ≤1，collect ≤1，total ≤2 | collect 不是 provider retry；新 canary 才能获得新 evidence family/budget |
| DSH bounded-lane process starts | charter 精确冻结 fresh/collect/total，且 total=fresh+collect | 不继承 completion/canary；process ceiling 缺失或耗尽即停止 |
| hidden/auxiliary provider calls | 0 | title、internal retry、compaction、search、subagent 等任一调用使 runtime contract 失败 |
| bounded lane agent | 默认禁用 | 只有独立 charter 明确 turns/tools/trials/Token/金额预算时可启用 |
| lease / heartbeat | 90 秒 / 30 秒 | 连续失去 lease 后旧 worker 不得提交 |
| provider soft SLA / hard deadline | 90 秒 / 600 秒 | soft 只告警；hard 或全局剩余时间先到即终止 |
| DSH collect grace cap | 60 秒 | claim 冻结 absolute collect deadline；restart/collector 不得重新计时 |
| total run deadline | 45 分钟 | 超时保存 checkpoint，不发布 candidate |
| DeepSeek provider peak window | 工作日 09:00–12:00、14:00–18:00（Asia/Shanghai） | 所有 AI 出站调用延期；route 不得绕过 provider send admission |
| complete-batch off-peak runway | 125 分钟，且须在 09:00 前完成 | 余量不足不加载 universe、不跑基线、不 claim run/call；下次默认 18:00 |
| single-call completion runway | provider hard timeout + 5 秒 | 余量不足不 claim/send；DeepSeek 策略调用当前为 605 秒 |
| Daily Decision isolation blackout | Asia/Shanghai 09:00–10:00 | 禁止启动或恢复 universe preparation 与本地研究 stage；08:30–09:00 只允许收口已准入批次，09:00 后不得发布 completed research artifact |

所有 DSH purpose 使用同一守恒公式：`fresh_process_start_ceiling = physical_request_ceiling +
local_launch_retry_ceiling`，`collector_process_start_ceiling = physical_request_ceiling`，
`total_process_start_ceiling = fresh_process_start_ceiling + collector_process_start_ceiling`。
Ceiling 是上限而非必须启动数；未实际需要 collector
不能为了“用满预算”启动进程。

每次 DSH spawn 前，process-budget ledger 必须用一次 CAS 原子增加对应 fresh/collector category
与 total counter，并把 category/total ordinal、purpose、budget fingerprint 和 reservation ID 写入
immutable attempt binding；两项不能分开提交。只有 durable OS evidence 证明 process 从未启动时
才能 append settlement 归还两项。Process 一旦 started，slot 永久消费；collector crash、lease
takeover 或 worker restart 必须采用原 binding/reservation，不能先签发新 slot。Pre-start settlement
不恢复 local-launch retry allowance；如 policy 允许 replacement binding，它仍须消费同一冻结的
per-logical/global local-launch allowance，防止零 start 的无限循环。对 started reservation 的
adoption 只能 attach/observe 尚存的同一 OS process 或采用已有 event/spool/result，绝不能以同一
reservation 再次 exec；原 collector 已退出且没有可采用结果时保持 pending，到 frozen deadline
后 terminal，不 respawn。

logical slot 在 stage admission 时 reserve；`ProviderCallClaim` 必须在 user-turn submit 前原子
commit logical slot 与一个 physical capacity reservation。只有 durable evidence 证明 user turn
从未提交且请求不可能发送时，settlement 才能归还未使用 capacity；user turn 一经提交，logical
slot 与一次 physical allowance 均保持消费。相同语义的 exact transport retry 不增加 logical
call，但消费 retry allowance 和一个新的 physical allowance。无效语义内容与 `result_unknown`
都保持消费，不能通过追加调用静默扩大授权。

所有具体 reservation ID、金额、Token、physical capacity 和 settlement 只存在于
`RuntimeAttemptBinding`/`ProviderCallClaim`，不进入稳定的 `ModelInvocationEnvelope`。Exact retry
创建新 binding/claim，但 envelope fingerprint 不变。

Provider 请求数、DSH 进程数、model turn 数、tool call 数和统计试验数是不同计数器。一个
logical call 的 exact transport retry 在统计试验族中只计一次，但每个物理请求的 Token 和金额
都计入成本；任何 prompt、Research Pack、model、profile、tool capability 或 response schema
变化都产生新的 logical call 和统计 trial。`collect_existing` 不发送请求，所有 provider 计数
delta 必须为零。

Research Charter 与 owner export authorization 必须同时绑定 `logical_ceiling=10`、
`retry_allowance=2` 和 `physical_upstream_request_ceiling=12`。任何 hidden/auxiliary request 即使
导致 runtime contract 失败，也必须计入物理请求、Token 和费用证据，且不能借故把 ceiling
提高。

## 附录 C：默认统计与 A 股成交 Policy

所有默认值都写入 `ResearchCharter`。Owner 可以收紧；放宽会创建新 charter、新 experiment，
且不能复用已经开封的 sealed partition。

### 统计 policy

| 项目 | 默认值 |
| --- | --- |
| 最短原始历史 | `leading warm-up + discovery usable + adaptive usable + sealed usable + partition gaps`，各部分均绑定交易日历 |
| 时间切分 | discovery usable ≥ `504 + G + 4×63` 日；adaptive 与 sealed time 各 ≥252 日；二者之间各留 `G` 日 gap |
| sealed universe | 按发行主体、板块、行业、规模、流动性和交易状态分层抽取 20%，且不少于 200 只；研究阶段完全不可见 |
| 内层 walk-forward | 504 日训练、`G` 日隔离、63 日 forward、63 日 step，至少 4 个有效 fold |
| warm-up / purge / embargo | `L=max formula lookback`，`G=max(5, holding horizon + execution lag - 1)`；warm-up 不计收益 |
| 唯一 champion | adaptive validation 上按预声明 lexicographic key 选择；依次比较 gate、成本后 excess、回撤、换手、复杂度、candidate ID |
| 最小实质性 | 相对 primary benchmark 成本后年化 excess 至少 2% |
| 不确定性 | paired stationary block bootstrap：20 日 block、10,000 次、固定 seed、95% CI 下界大于 0 |
| 多重检验 | primary family 使用 Holm–Bonferroni、FWER α=0.05；适用时另要求 DSR ≥ 0.95、PBO ≤ 0.20 |
| 风险约束 | 最大回撤 ≤15% 且不得比 incumbent 恶化超过 2 个百分点；年换手 ≤800%，incumbent 非零时还须 ≤其 1.5 倍 |
| 基准集合 | Pre-freeze 用现金、人工冻结 incumbent、公开 CSI 指数及 development-universe 等权；deterministic/random comparators 在开封前冻结；全量 universe 等权及 comparator sealed result 只由同一 sealed evaluator 原子计算；primary benchmark 唯一指定 |

sealed time 与 sealed universe 都必须满足最小实质性和 bootstrap 门槛；任何一项失败都不产生
shadow-review candidate。20 日/约 50 单前瞻门槛只评价运营可靠性，不替代上述统计门槛。
每只股票按每个决策日单独检查是否具备 `L` 日历史；新上市股票在满足 warm-up 后即可进入，
不能用固定全历史长度永久排除。两维 sealed 评估分别报告已知 universe/未知时间、未知
universe/已知时间及二者交集，三者均不得被用于开封后的二次选优。

### A 股成交 policy

| 项目 | 默认值 |
| --- | --- |
| 信号 cutoff | `D` 日信号与排序只使用 `D-1` 收盘前已发布并冻结的事实 |
| 订单意图/票据 | 在 `D` 日决策时点仅使用信号、当时可见 quote、Account Truth、ADV20 和冻结 order policy；此后不得改股票、方向、目标数量或价格规则 |
| 价格口径 | 信号使用统一复权价格；成交、费用和涨跌停判断使用可对账 raw price |
| Fill simulation | 09:35–09:45 结束后使用完整冻结 raw minute bars 的 VWAP 与窗口成交量；只能决定 fill/partial/no-fill，不能改订单意图 |
| 费用 | 只使用 fingerprint-bound reviewed fee schedule，逐组件和逐订单舍入 |
| 滑点与冲击 | 每边不利调整为 `10bps + 0.5 × vol20 × sqrt(order_notional/ADV20_notional)`；超过 100 bps 默认拒绝 |
| 容量 | 订单不超过 ADV20 的 2%，窗口成交不超过实际窗口量的 5%；取两者较小值并允许 partial fill |
| 整手与 T+1 | 买入按 100 股向下取整；卖出受可卖数量和 T+1 限制，清仓碎股按交易所规则处理 |
| 停牌/无量 | `volume <= 0`、停牌或交易状态不完整时不成交 |
| 涨跌停 | 买入涨停或卖出跌停且窗口价量无法证明可成交时不成交；一字板一律不成交 |
| 模糊状态 | 无法由冻结日线证明成交可能性时采用 no-fill，不采用乐观成交 |
| 现金预算 | 买入不得依赖预期卖出 proceeds，并预留 `max(20bps × 名义额, 最低佣金)` 缓冲 |

`vol20` 为过去 20 个可用交易日的日收益波动率，`ADV20` 为过去 20 日成交额中位数；二者只能
使用 cutoff 前数据。零滑点、同 bar 成交、当日收盘价替代早盘窗口或事后成交量只能用于
非晋级诊断场景。

## 附录 D：设计—测试—证据追踪矩阵

| ID | 设计条款 | 确定性验收 | Evidence Artifact |
| --- | --- | --- | --- |
| `AI-DATA-01` | Point-in-time Data/Universe Truth | 上市、退市、ST、停牌、公司行动与缺行 fixture 可重放且漂移阻断 | `ResearchDatasetTruthReceipt` |
| `AI-LEAK-01` | Sealed capability isolation | 所有 pre-freeze propose/search/validate/critique/select stage 均无法读取 sealed rows、symbols、dates 或 aggregate | `SealedAccessBoundaryReport` |
| `AI-LEAK-02` | Sealed 只开封一次 | 开封后任何公式/参数变化必须使用新未见 partition | `SealedPartitionConsumptionReceipt` |
| `AI-SEM-01` | 研究—生产同语义 | 打乱 symbol/row 顺序后信号、目标、订单、成交和指标字节一致 | `PortfolioSemanticParityReport` |
| `AI-TIME-01` | 防未来数据 | 篡改 `D` 日执行窗口数据只能改变 fill，不能改变事前 signal、ticket 或 order intent | `DecisionTimingReplayReport` |
| `AI-STAT-01` | 试验族与统计 gate | 所有语义候选恰计一次，DSR/PBO/bootstrap 可由 receipts 重算 | `StatisticalEligibilityReport` |
| `AI-EXEC-01` | A 股成交真实性 | T+1、整手、费用、停牌、涨跌停、partial fill、capacity fixture 全通过，且窗口数据只影响 fill | `ExecutionConformanceReport` |
| `AI-PRIV-01` | 最小化外发 | 序列化后的真实 provider payload 不含禁止账户、券商、权限或绝对规模字段 | `ProviderExportReceipt` |
| `AI-PRIV-02` | Raw reasoning 零持久化 | session、event/result、stdout/stderr、provider capture 与日志扫描均无 reasoning/raw body | `ReasoningPersistenceAbsenceReport` |
| `AI-PRIV-03` | 隐私证据闭包 | fixture/install 报告覆盖所有 payload family 与 adapter；每个 research 报告将全部 outbound claim/turn 与 export receipt 双向集合相等，missing/extra/banned hit 为零 | `ResearchPackPrivacyReport` |
| `AI-PROV-01` | Provider/runtime identity | builder、endpoint、model、runtime、profile、tool、prompt 任一漂移均在 transport 前阻断 | `ProviderContractReceipt` |
| `AI-RT-DESC-01` | Descriptor discriminated identity | manifest/payload 双 hash 可重算；mixed/missing variant、错误 scope/parent、HTTPS 携 install 或 DSH 缺 install/policy 全部在构造/消费前拒绝 | `RuntimeDescriptorConformanceReport` |
| `AI-WF-01` | Workflow/授权绑定 | 串行、tournament、bounded-lane artifact/slot/授权交叉复用全部在外发前被拒绝 | `WorkflowAuthorizationBoundaryReport` |
| `AI-RT-01` | Runtime adapter parity | HTTPS 与 DSH completion 对相同 canonical Pack 使用同一 strict response parser、citation/DSL gate，adapter-specific 字段不进入 Candidate | `RuntimeParityReport` |
| `AI-RT-CANARY-01` | Runtime canary union | HTTPS/DSH exhaustive 产生精确 receipt variant；HTTPS 无 DSH 字段、DSH 字段完整，mixed/missing/scope mismatch 拒绝 | `LiveHttpsCanaryReceipt` / `LiveDshCanaryReceipt` |
| `AI-DSH-ISO-01` | DSH 隔离 | 恶意 prompt 无法读取 repo、`.env`、DSH personal home、账户导出或 runtime DB，也无法使用 shell/fs/Web/subagent | `DshProfileIsolationReport` |
| `AI-DSH-INSTALL-01` | Installed closure | partial/tampered/replaced/权限漂移 closure 在 exec 前拒绝；同 bytes 可由 receipt 重验 | `DshInstallIntegrityReport` |
| `AI-DSH-IO-01` | Machine protocol | completion/lane argv 不含 payload；继承 FD、event fsync、atomic result、exact JSON/identity/UTF-8 任一错误均 fail closed；lane invalid disposition 不产 semantic outcome，stdout 无权威性 | `DshMachineProtocolReport` |
| `AI-DSH-SPOOL-01` | Durable spool lifecycle | 实际 canonical policy bytes/fingerprint 与 config/descriptor/manifest 一致；逐 kind ceiling、90/30 日 retention、unknown/open/quarantine 不 GC、capacity fail-closed、terminal adopt/cleanup 均可重放 | `DshSpoolLifecycleReport` |
| `AI-DSH-CRED-01` | Credential transport | research completion、bounded-lane turn 与 canary secret 只经一次性 inherited FD；broker receipt 可对账，argv/env/file/log/artifact 无 raw value | `CredentialBoundaryReport` |
| `AI-DSH-CALL-01` | 调用守恒 | 每 claim 至多一个请求；默认 completion 为 10/2/12 与 process 22/12/34，canary 为 1/0/1 与 1/1/2，bounded lane 严格等于 charter ceilings；fresh/collector category+total slot 原子且 takeover 不增额，隐藏调用均为零 | `ProviderCallAccountingReport` |
| `AI-DSH-REC-01` | Subprocess 恢复 | pre/post-send、pre/post-flush、pre/post-result crash injection 不重复 uncertain call，collect-existing 的 request delta 为零 | `DshRecoveryDrillReport` |
| `AI-DSH-DRIFT-01` | Profile 漂移 | executable、Node、package、profile、overlay、settings、model route 或 tool schema 漂移在 spawn/accept 前阻断 | `DshRuntimeConformanceReport` |
| `AI-DSH-AGENT-01` | Bounded lane | 独立 workflow；每 turn 实际 bytes 重新授权，capability 不外发，tool attempt 不替代 authoritative stage，output/schema invalid 消耗调用且不 retry/产出 tool/final-submit，任一预算耗尽即停止 | `DshBoundedLaneReport` |
| `AI-DSH-CANARY-01` | Live DSH canary | 独立 envelope/auth、非金融 payload、精确 route、FD/credential、provider 1/0/1、process 1/1/2 与零隐藏调用可对账 | `LiveDshCanaryReceipt` |
| `AI-REC-01` | Stage 恢复 | 每个 stage 边界 crash injection 均可恢复且不重复 uncertain call | `StageRecoveryDrillReport` |
| `AI-ISO-01` | Daily critical-path isolation | provider 卡死期间 Daily Decision 仍在 deadline 内产生独立结果 | `CriticalPathIsolationReport` |
| `AI-AUTH-01` | 两次人工权限边界 | shadow admission 不能赋予 production assignment，撤销立即阻断后续使用 | `PromotionLifecycleReport` |
| `AI-VALUE-01` | AI 增量价值 | 在相同数据、试验族和计算预算下与 deterministic/random search 完成 sealed 对比 | `ModelIncrementalValueReport` |

所有 acceptance artifact 都必须绑定代码 revision、精确 scope 与输入/输出 fingerprint。
Research-scope evidence 额外绑定 charter、dataset 与算法版本；runtime-install evidence 绑定
registry/install receipt/closure/policy；runtime-descriptor evidence 绑定 adapter variant、provider/
model route 与 descriptor manifest；runtime-canary evidence 绑定 canary manifest/authorization 与
runtime descriptor。禁止为空缺字段伪造 experiment 或 research identity。Mock、静态检查或
服务存活只能满足相应软件契约，不能替代 live provider canary、sealed 统计证据或 paper/shadow
前瞻证据。

## 附录 E：DSH Feature 实施蓝图

本附录定义代码所有权和依赖顺序。文件名可以在实现审查中做等价调整，但层次、协议和禁止
依赖不能改变；若调整文件名，必须在同一变更中更新本文与 import-boundary tests。

### 后续实现模型执行契约

新的实现模型接手本 feature 时，必须把本文当作 target contract，而不是把陈述句当成现状。
采取任何修改前先读取仓库协作规则、产品目标、架构、相关 README 和 Implementation Log，
再基于当前 source/test/persisted schema 生成一份 `ImplementationTracePlan`，逐项列出：

- 本次覆盖的设计/验收 ID、受影响 canonical owner、caller 与持久化 schema；
- 计划修改的精确模块、migration/rollback、import boundary 和禁止依赖；
- 每个不变量的失败注入、contract test、集成测试与 evidence artifact；
- 不能在当前环境验证的 live provider、OS isolation、真实 binary 或运营边界。

实施必须按本附录依赖顺序分成可审查的 vertical slice；前一 slice 的 contract/evidence 未成立，
不得用 mock green 跳到下一层。任何 live provider/canary、真实 Research Pack 外发或新 payload
family 都需要对应 owner authorization，不能因为本文推荐 DSH 而推定已授权。后续模型只有在
“最终 DSH feature 验收证据”全部存在并重放通过后，才能报告 runtime feature 完成；策略有效、
shadow/production readiness 和每日交易权限仍需各自独立证据与人工决定。

### 目标模块

| 目标位置 | 唯一责任 | 禁止责任 |
| --- | --- | --- |
| `server/ai_runtime/completion_runtime.py` | `ModelRuntimeDescriptor`、`CompletionInvocationEnvelope`、purpose-specific attempt binding、`CompletionCollectEnvelope`/collector binding、completion/pending/failure outcome union | provider-specific transport、业务 gate、数据库访问 |
| `server/ai_runtime/lane_runtime.py` | `StrategyResearchLaneRuntime.run_turn/collect_turn` 与 lane-turn outcome protocol | single-completion 兼容 shim、默认 tournament stage mapping |
| `server/ai_runtime/openai_https_completion_runtime.py` | 将统一 envelope 映射为一次 HTTPS completion | Formula/citation 解析、业务 retry、权限判断 |
| `server/ai_runtime/dsh_completion_runtime.py` | 验证 descriptor，直接 exec 专用 DSH runner，管理继承 FD/event ACK/atomic result/process group | shell 拼接、repo 访问、透明 fallback、研究选择 |
| `server/ai_runtime/dsh_machine_protocol.py` | fresh/collect union、typed frames、exact JSON、provider grant 和 result binding | 容错 JSON 修复、业务语义、从 stdout 推断结果 |
| `server/ai_runtime/dsh_spool_store.py` | 严格加载 lifecycle policy，预创建 typed spool、FD/inode/lease binding、atomic commit/adopt/cleanup | 代码默认 retention、让 child 选路径、删除 unknown、持久化 raw body |
| `server/ai_runtime/dsh_lane_protocol.py` | fresh/collect lane machine union、turn/tool/result/final-submit schemas、grant binding 与 per-turn export | 通用 agent loop、sealed evaluator 或 strategy mutation |
| `server/ai_runtime/dsh_runtime_descriptor.py` | 解析 executable/Node/package/profile/tool/env/network identity 并生成 fingerprint | 启动模型请求或读取金融事实 |
| `server/ai_runtime/credential_broker.py` | 验证 secret reference，创建一次性 inherited FD，返回 broker receipt 并关闭/zeroize | 将 raw secret 写入 env、argv、文件、日志或 persistence |
| `server/ai_runtime/dsh_research_capability_service.py` | 为 bounded lane 创建继承 FD、签发短时 capability、执行两种 typed pre-sealed 工具并写 ToolCallReceipt | 通用 RPC、文件/数据库路径暴露、sealed/账户/权限访问 |
| `server/ai_runtime/strategy_research.py` | 构建唯一 sanitized Research Pack，调用通用 completion runtime，执行响应/citation/DSL 校验 | 按 adapter kind 分叉研究、回测或 selection 语义 |
| `server/config_types.py` | 严格 discriminated runtime config 与启动期验证 | 根据空字段、PATH 或可用性猜测 runtime |
| `server/services/strategy_research_factory.py` | canonical 构造非自引用 descriptor manifest，exhaustive 构造精确 runtime，并把 descriptor 暴露给 charter/stage/audit | DSH 失败后改走 HTTPS、切换 provider/model 或从“最新记录”补 identity |
| `server/services/ai_research_jobs.py` | 创建、查询、原子 claim durable research job，绑定 charter/worker lease/result | 在请求线程中启动模型或把 job success 当作策略晋级 |
| `server/workers/ai_research_worker.py` | 唯一 claim job、驱动 Stage Ledger、启动/收集 runtime、续租和提交终态 | 提供 HTTP/read UI、运行 Daily Decision 或共享其 executor |
| `scripts/run_ai_research_worker.py` | 显式启动独立 worker，校验部署 identity 与 shutdown/blackout policy | 启动 API、自动批准外发或绕过 durable job claim |
| `server/ai_runtime/provider_connectivity.py` | 构建独立 canary envelope/attempt，按 descriptor exhaustive 执行显式非金融 1/0/1 canary 并返回 `RuntimeCanaryReceipt` 精确 variant | 伪造 research stage、混合 adapter 字段，或在 health/read/daily path 自动探测/外发 |
| `scripts/run_dsh_runtime_canary.py` | operator-only canary launcher，校验 canary authorization/manifest 与 launch isolation | 接收金融 payload、由 scheduler/health 调用或创建 research job |
| `server/persistence/ai_model_runtime.py` | append-only invocation、provider claim/event/terminal、process-slot reservation/settlement、credential-broker、spool、DSH attempt 与 lane receipts | credential raw value、broker 原始事实、raw provider body 或任意 raw reasoning 的任何形式持久化 |
| `server/persistence/dsh_runtime_install_registry.py` | append-only trusted install-receipt store、按 fingerprint lookup、registry descriptor/完整性重验 | 相信 executable 邻接 receipt、任意 config path 或修改旧 receipt |
| `runtime/dsh/karkinos-research-json/` | 版本控制中的最小 completion profile/runner/lock/composition 构建源 | 直接作为生产 DSH home 或 writable runtime closure |
| `runtime/dsh/karkinos-research-lane/` | 版本控制中的 bounded-lane profile/capability client 构建源 | 复用 completion profile flag 偷开工具或自治循环 |
| `scripts/install_dsh_research_runtime.py` | 原子生成仓库外只读 closure，并把 install receipt 发布到 trusted registry | 复制 credential、创建 personal overlay、启动 provider call |
| `scripts/audit_dsh_research_runtime.py` | persisted-only conformance/replay；显式 flag 下执行无金融 live canary | 默认联系 provider、修改研究/策略/订单状态 |
| `scripts/audit_ai_research_privacy.py` | 对 fixture/install 或指定 experiment 做 claim/turn/export 双向集合核验、禁止字段扫描和 reasoning-absence 聚合，生成 `ResearchPackPrivacyReport` | 发起 provider call、补造缺失 receipt、修改授权或自动放行 runtime |
| `tests/ai_runtime/`、`tests/server/` | contract、parity、隔离、预算、crash/recovery、composition guard | 用 mock 结果声称 live provider 或运营验收完成 |

依赖方向固定为：

```text
strategy_research -> completion_runtime protocol
                         ^
                         ├── openai_https_completion_runtime
                         `── dsh_completion_runtime -> subprocess boundary

dsh_* -X-> account_truth / valuation / ledger / execution / risk mutation / broker
daily_candidate -X-> completion_runtime / dsh_*

API/operator service -> durable research job only
research-worker -> claim job -> Stage Ledger -> completion runtime
operator-only canary executor -> provider_connectivity -> DSH runtime
API/app/Daily Decision -X-> subprocess runtime / child process / result channel
```

DSH-specific 类型不能进入 CandidateArtifact、BacktestResult、SealedEvaluationReceipt、
ShadowAdmittedArtifact 或 ProductionAssignmentArtifact。上述 canonical artifact 最多引用通用
`ModelCompletion`、`ModelSemanticValidationReceipt` 或 `ModelRuntimeDescriptor` fingerprint，
不能根据 runtime kind 改变金融语义。

仓库内 `runtime/dsh/...` 只是审查和构建源。Release/install 阶段必须将精确依赖闭包安装到
仓库外、非 group/world-writable、运行期只读的内容寻址目录，并生成 install receipt；descriptor
绑定 installed executable/profile/package bytes，不绑定源码目录。Writable DSH home、attempt
spool 与 session event store 位于另一 owner-only data root。Research worker 的 cwd 和 read
allowlist 都不得包含仓库源码或构建目录。

`DshRuntimeInstallReceipt` 是 descriptor 的强制父 artifact，不是安装脚本的提示输出。Installer
必须在可信 install root 下创建同文件系统 temporary directory，生成 ordered closure manifest
（每个相对路径、kind、SHA-256、owner、mode、size，以及 executable/profile/package/config
entrypoints 与 Node runtime dependency），拒绝 symlink/hard-link、缺失/额外文件、
group/world-writable entry 和 root 逃逸，
逐文件与目录 fsync 后按 closure fingerprint 原子 rename 为只读目录，再 fsync install root。
Receipt 至少绑定 source revision/profile、installer code revision、install-root identity、closure
manifest fingerprint、最终 realpath、owner/mode verification 和 atomic-commit proof。

Receipt 只能发布到 deployment-owned `DshRuntimeInstallRegistry`：registry root 为固定、owner-only
`0700`、append-only/content-addressed store，拥有独立 registry ID/descriptor fingerprint，并以
receipt payload fingerprint 作为唯一 lookup key。发布使用 temporary+fsync+atomic rename；相同
key 的不同 bytes、symlink、权限漂移或 registry root replacement 均拒绝。Runtime config 只携带
用于定位 closure 的受信 registry ID/fingerprint 与 receipt fingerprint；它可以冗余 pin 预期
closure/entrypoint fingerprint，但不得提供 install root 或 executable 路径。Factory 通过依赖注入的
registry lookup API 读取 canonical receipt bytes 并由其中的 entrypoint 生成绝对 realpath，绝不读取
executable 邻接文件、caller 提供路径或 cwd 中的 receipt。

`resolve_runtime_descriptor`、每次 canary/research spawn 与结果接受都必须通过 install receipt 找到
closure，重新枚举实际文件并与 manifest 比对；partial install、tamper、权限漂移、路径替换或
active receipt/closure mismatch 均在 exec/accept 前 fail closed。同 bytes 的 reinstall 可以复用
closure fingerprint，但必须生成/采用可审计 receipt；不同 bytes 永远是新 descriptor。

### 配置 discriminated union

配置必须显式区分 shared provider/model identity 与 adapter-specific transport：

```text
AIResearchModelConfig:
  enabled: bool
  upstream_provider_id: string
  exact_model_revision: string
  prompt_contract_version: string
  response_schema_version: string
  sampling_profile: object
  adapter:
    OpenAICompatibleHttpsConfig
    | DshSubprocessJsonConfig
    | DshBoundedLaneConfig
```

不得把 DSH executable 塞进 `base_url`，不得要求 DSH 伪造 HTTPS API key 字段，也不得通过某个
字段是否为空猜测 adapter kind。建议的 DSH completion 配置形状为：

```json
{
  "kind": "dsh_subprocess_json_v1",
  "install_registry_id": "deployment-owned-registry-id",
  "install_registry_descriptor_fingerprint": "sha256:...",
  "install_receipt_fingerprint": "sha256:...",
  "installed_closure_manifest_fingerprint": "sha256:...",
  "executable_sha256": "sha256:...",
  "expected_dsh_version": "exact-version",
  "node_executable_sha256": "sha256:...",
  "profile_id": "karkinos-research-json",
  "profile_source_fingerprint": "sha256:...",
  "plugin_lock_fingerprint": "sha256:...",
  "composed_config_fingerprint": "sha256:...",
  "expected_upstream_provider_id": "deepseek",
  "expected_model_revision": "exact-provider-revision",
  "credential_reference": "secret-ref-name-and-version",
  "soft_sla_cap_seconds": 90,
  "hard_deadline_cap_seconds": 600,
  "collect_grace_cap_seconds": 60,
  "termination_grace_seconds": 5,
  "max_invocation_fd_bytes": 196608,
  "max_event_frame_bytes": 262144,
  "max_result_fd_bytes": 1048576,
  "max_stdout_bytes": 16384,
  "max_stderr_bytes": 16384,
  "spool_root_path": "/absolute/owner-only/runtime-data/spool",
  "spool_lifecycle_policy": {
    "schema_version": "karkinos.ai.dsh_spool_policy.v1",
    "total_capacity_bytes": 536870912,
    "max_entries": 2048,
    "per_attempt_event_bytes": 8388608,
    "per_provider_sanitized_response_bytes": 1048576,
    "per_outer_result_bytes": 1048576,
    "retention": {
      "adopted_or_completed_days": 90,
      "proven_not_sent_days": 30,
      "open_or_result_unknown_auto_gc": false,
      "quarantined_auto_gc": false
    },
    "capacity_exhaustion": "fail_closed_new_runtime_attempts"
  },
  "spool_lifecycle_policy_fingerprint": "sha256:...",
  "cwd_policy": "empty_ephemeral",
  "environment_policy": "explicit_allowlist",
  "network_policy": "exact_provider_endpoint_only",
  "credential_transport": "one_shot_inherited_fd_v1",
  "telemetry": "disabled",
  "internal_retry_count": 0,
  "tool_policy": "none",
  "machine_protocol": "karkinos.ai.dsh_completion.v1"
}
```

数字默认值必须最终进入 charter，不能只留在代码常量。实现可以收紧 byte/deadline 上限；放宽
会改变 descriptor 和 charter。配置 parser/factory 必须拒绝未知 kind、未知字段、install receipt
解析出的非绝对或逃逸 closure 的 entrypoint、caller 提供的 executable/install path、浮动 model
alias、缺失 fingerprint、
group/world-writable binary/profile、启用 telemetry、
非零内部 retry、install receipt/closure mismatch 或不匹配的 provider/model route。Parser 还必须
对 `spool_lifecycle_policy` 做 exact schema 校验和 canonical reserialization，重算 fingerprint，
拒绝 object/fingerprint 不一致、未知 retention class、缺失 typed ceiling 或任何隐式默认值。

`DshBoundedLaneConfig` 不能继承 completion 配置后只加 `tools=true`；它必须使用独立 kind、
profile fingerprint、tool schema、capability issuer、每 lane provider/tool/trial/local-compute
预算与独立 owner authorization。Capability transport 固定为 `inherited_fd_frames_v1` 或经过
同等级安全评审的后继版本；配置必须冻结 frame schema、method allowlist、byte/sequence/deadline
上限和 issuer fingerprint。

### Factory 与 descriptor resolution

Descriptor resolution、canary 与 research binding 是三个独立动作，不能让无金融 canary 依赖
某个 research experiment 的外发授权：

```text
resolve_runtime_descriptor(config)
  -> locally verified immutable descriptor

run_runtime_canary(descriptor, canary_authorization, canary_manifest)
  -> RuntimeCanaryReceipt = LiveHttpsCanaryReceipt | LiveDshCanaryReceipt

bind_research_runtime(descriptor, research_charter, export_authorization)
  -> exact runtime available to one experiment
```

`resolve_runtime_descriptor` 必须严格解析 config，解析 upstream provider/model 和 adapter-specific
executable/profile/package/tool/env/network identity，构造 fingerprint，再 exhaustive match 构造
runtime；全程不联系 provider。`run_runtime_canary` 只接受独立 canary authorization 和无金融
manifest。`bind_research_runtime` 才重验 Research Charter、research export authorization、
runtime descriptor 与 provider/model/payload family 的完全一致性。

同一 resolved descriptor 提供给 strategy service、Stage Ledger、canary 与 audit。每次 canary
或 research spawn 前、结果接受前都重新解析并比对 descriptor；任一漂移直接 fail closed，
不尝试另一 runtime。

Factory 的选择必须是显式穷尽分支：

```python
match config.adapter.kind:
    case "openai_compatible_https_v1":
        ...
    case "dsh_subprocess_json_v1":
        ...
    case "dsh_bounded_lane_v1":
        ...
    case _:
        raise UnsupportedResearchModelRuntime
```

运行时 availability 不是选择依据。binary 存在、个人 DSH 已登录、某 endpoint 暂时可用或上次
实验成功，都不能触发自动选择。

### Research Pack 单一实现

HTTPS 与 DSH completion 必须消费同一函数生成的 canonical bytes；bounded lane 的每个实际
outbound turn 也必须调用同一 sanitizer/authorizer 重新生成 bytes。Sanitizer 使用显式字段 allowlist，
而不是仅维护 denylist；序列化完成后还要执行禁止字段、账户样式值、绝对规模和 credential
扫描。`ProviderExportReceipt` 绑定实际发送的 bytes、长度、payload fingerprint、authorization
和 runtime descriptor，不能只绑定构造前 Python object。

实现必须用 fixture 证明：

- 调整 JSON key、股票或 evidence 顺序不会改变 canonical payload；
- `initial_cash`、`final_equity`、绝对 PnL/费用、账户/券商/valuation/ledger identity、持仓数量、
  原始路径和 authority 字段无法进入两种 adapter；
- DSH argv、环境、普通日志、session title 与 process name 中没有 Research Pack；
- HTTP 与 DSH 对同一请求记录相同 payload fingerprint；
- adapter-specific provenance 不进入模型的经济假设或 CandidateArtifact。

`ResearchPackPrivacyReport` 的 expected set 来自指定 scope 下全部 research-completion/bounded-lane
`ProviderCallClaim` 与实际 outbound turn，observed set 来自其精确引用的 `ProviderExportReceipt`；
审计器必须双向比较 identity 与 payload fingerprint，聚合禁止字段扫描和
`ReasoningPersistenceAbsenceReport`，且不得补造 receipt。Install-scope 报告覆盖所有已注册 payload
family、adapter 与边界 fixture；每个 experiment 在 `finalize` 前另生成 research-scope 报告。
任一 missing、extra、adapter mismatch、未覆盖 bytes 或 scanner failure 都 fail closed。

### Runtime canary 与 DSH variant

Canary 是显式 operator action，不由 health、read API、页面加载、应用启动或每日 scheduler 自动
触发。它使用固定 system prompt、随机 nonce 和精确 JSON response schema，不含股票、行情、
公式、账户或其他金融 evidence；每次 canary 使用新 canary/logical/physical ID、独立 canary
manifest/authorization 和独立费用记录。其调用预算固定为 logical/retry/physical = 1/0/1。
Canary executor 仍遵守 research blackout、独立资源限制和 Daily Decision 优先级。HTTPS variant
验证 client/wire/TLS/route 且不得出现 DSH 字段；以下 process/FD/profile 条款专属于 DSH variant。

Canary 必须验证：

- executable/Node/profile/plugin lock/composed config identity；
- 实际 provider/model route 与 runtime descriptor、canary manifest/authorization 一致；
- controlled completion 恰好产生一个上游 provider request；除此之外的 title、internal retry、
  compaction、search、subagent request、tool call 和 telemetry 均为零；
- 正常路径 fresh process 恰好为 1、collect 为 0；仅 crash recovery 可使用同 evidence family
  唯一的 collect slot，任何路径 fresh/collect/total 都不得超过 1/1/2；
- invocation/control/event/result/credential inherited FD schema、usage、finish reason、上游 request
  ID、`CredentialBrokerReceipt` 与 process exit 可对账，普通 stdin 不参与协议；
- cwd/repo/home/account paths 不可见，process tree 完整退出；
- `LiveDshCanaryReceipt` 可绑定 canary envelope/attempt、logical/physical/provider call、payload、
  runtime、credential broker 和 response fingerprints。

Canary success 只证明 runtime contract 可用，不证明 Research Pack 合格、候选有效、sealed lift、
paper/shadow readiness 或生产权限。

最终 DSH feature gate 必须取得 `LiveDshCanaryReceipt`；`LiveHttpsCanaryReceipt` 只能证明 HTTPS
variant，不能替代 DSH install/profile/process/FD 证据。

### 实现依赖顺序

后续实现任务按以下依赖顺序拆分；每一步先通过对应 contract tests，再允许下一步依赖它：

1. 定义通用 descriptor、invocation/attempt 身份、outcome union、provider lifecycle records 与
   failure taxonomy；
2. 从现有策略研究 provider 中抽取 HTTPS runtime，保持 payload、strict parser/gates 和错误语义不变；
3. 建立 HTTP/DSH 共用的 canonical Research Pack sanitizer、privacy fixtures、双向 receipt coverage
   audit 与 `ResearchPackPrivacyReport`；
4. 引入严格配置 union、descriptor resolver 与 architecture import guard；
5. 构建最小 `karkinos-research-json` profile、runner、lock 与 composition manifest；
6. 实现 atomic installed closure、trusted install registry、`DshRuntimeInstallReceipt` lookup 与
   resolve/spawn/accept 完整性重验；
7. 实现 `DshSpoolStore` lifecycle、credential broker 与四 FD machine framing；
8. 实现 direct exec、继承 invocation/control/result/credential FD、event fsync、atomic result、
   环境/文件/网络隔离、process group 与 output limits；
9. 接入 Stage Ledger、provider claim/grant/event/terminal、DshAttemptEvent/Receipt 和
   `result_unknown` collect/reconciliation；
10. 建立 offline profile audit、fake-runner contract tests 与 crash-injection suite；
11. 实现显式、非金融 live canary；
12. 只在独立 after-close research worker 中启用受控 runtime，并完成 critical-path isolation；
13. 若需要 agent 能力，再以新 experiment、独立 workflow/charter/profile/逐 turn 授权实现
    bounded lane；completion 的验收不能自动授予 bounded-lane 能力；
14. 研究产物仍依次经过本地 DSL、search、adaptive validation、sealed gate 和两次人工生命周期。

抽取 HTTPS runtime 的 fixture bytes、请求次数、错误码和本地响应 artifact 必须与抽取前完全
一致；这是证明“增加 DSH 没有改变既有研究语义”的基线。实现任务不得同时重写 Formula DSL、
回测、selector、晋级或 Daily Decision。

### 最终 DSH feature 验收证据

只有以下 artifact 全部存在、未过期、指纹一致且可重放时，指定 runtime descriptor 才能用于
新的受控 AI research：

- `RuntimeParityReport`；
- `RuntimeDescriptorConformanceReport`；
- `ResearchPackPrivacyReport`；
- `DshRuntimeConformanceReport`；
- `DshRuntimeInstallReceipt` 与 `DshInstallIntegrityReport`；
- `DshProfileIsolationReport`；
- `DshMachineProtocolReport`；
- `DshSpoolLifecycleReport`；
- `CredentialBoundaryReport`；
- `ProviderCallAccountingReport`；
- `DshRecoveryDrillReport`；
- `LiveDshCanaryReceipt`；
- `CriticalPathIsolationReport`；
- 使用 bounded lane 时额外需要 `DshBoundedLaneReport`。

缺少任一证据只禁用对应 DSH runtime，不影响 incumbent、Daily Decision、人工票据或
NO-ACTION。证据齐全也不自动创建 research charter、外发授权、shadow approval、production
assignment、订单或资本权限。

## 附录 F：DSH Crash 与反例验收矩阵

以下反例必须在 fake provider、fake runner 和真实进程边界分层验证。所有测试共同要求：
provider request 数不超过 policy、同一 logical call 不存在未解释的并行 session、unknown 明确
可见，且 Daily Decision 始终 provider-free。

| ID | 注入点或反例 | 必须观察到的行为 | Evidence |
| --- | --- | --- | --- |
| `AI-DSH-X01` | 两个 worker 同时认领同一 logical call | 只有一个 atomic claim 和一个 subprocess；另一 worker 零外发 | `DshCallClaimRaceReport` |
| `AI-DSH-X02` | reservation 后、spawn 前崩溃 | 可证明 `proven_not_sent`，恢复 reservation，provider request 为零 | `PreSpawnCrashReceipt` |
| `AI-DSH-X03` | profile boot/session 创建前失败 | proven-not-sent runtime attempt immutable；同 Stage/logical、新 runtime/DSH ID 有界 local retry，不消费 provider/physical retry；allowance 尽则 Stage terminal | `PreSubmitFailureReceipt` |
| `AI-DSH-X04` | session/turn reserved 后、user-turn submit 前崩溃 | durable event 证明未 submit；可新建 DSH attempt，provider request 为零 | `SessionPreCallCrashReport` |
| `AI-DSH-X05` | provider claim 后崩溃，分别注入 submit 前与 submit 后 | submit 前可 `proven_not_sent`；一旦 submit 或无法证明则 `result_unknown`，不得重发 | `TurnSubmissionBoundaryReport` |
| `AI-DSH-X06` | provider response 后、session flush 前崩溃 | sanitized terminal 已 fsync 则 collect；按 terminal 分类进入 success/retryable/terminal-invalid，未形成 durable terminal 才 unknown；request delta 为零 | `PreFlushRecoveryReport` |
| `AI-DSH-X07` | session flush 后、result spool commit 前崩溃 | 收集得到字节一致 completion，不追加 user message | `PostFlushRecoveryReport` |
| `AI-DSH-X08` | result spool commit 后、StageAttempt commit 前崩溃 | 新 worker 幂等采用既有结果；只有一个 completion fingerprint | `AtomicAdoptionReport` |
| `AI-DSH-X09` | lease 过期但旧 child 仍运行 | 新 owner 只核验/等待/收集；旧 lease 不得提交，零重复外发 | `StaleLeaseIsolationReport` |
| `AI-DSH-X10` | PID 被复用或 orphan child 存活 | OS start identity 防止 attach/kill 错进程；原 child 被安全收集或终止 | `ProcessIdentityReport` |
| `AI-DSH-X11` | soft SLA 与 hard deadline | soft 只告警；hard 按 TERM/grace/KILL，in-flight 结果为 unknown，不自动重发 | `DeadlineContainmentReport` |
| `AI-DSH-X12` | child 忽略 TERM 并创建后代 | process-group KILL 后无孤儿；provider external-effect 独立判定 | `ProcessTreeTerminationReport` |
| `AI-DSH-X13` | completion/lane atomic result 空、fence/双 JSON、截断、超限或 schema invalid | terminal+flush durable 才 completed-invalid 且无 lane semantic outcome/retry；仅 terminal、未 flush 先是 collect-pending，collect deadline 后才 failed/external-completed；无 terminal 是 unknown | `MachineOutputRejectionReport` |
| `AI-DSH-X14` | exit 非零或 stdout 含合法 JSON | stdout 始终被忽略；只按 durable event/terminal/flush/atomic result 组合分类 | `ExitContractReport` |
| `AI-DSH-X15` | stdout/stderr 超限或诊断 capture 截断 | 永不解析截断内容；不保存 raw reasoning/body；external effect 独立判定 | `OutputBoundReport` |
| `AI-DSH-X16` | envelope 的 attempt/input/session/provider/profile 任一错配 | 拒绝结果，不能绑定到其他 StageAttempt 或旧 charter | `EnvelopeBindingReport` |
| `AI-DSH-X17` | typed 429/5xx 后 exact retry | 新 physical request ID、相同 logical/payload；消费 retry，统计 trial 仍为一 | `ExactTransportRetryReport` |
| `AI-DSH-X18` | retry 时修改 prompt、Pack、model、profile 或 tool policy | transport 前拒绝；要求新 logical call、charter 与统计 trial | `RetryDriftRejectionReport` |
| `AI-DSH-X19` | `collect_existing` 意外发送新消息 | provider request count 增加即测试失败，不能伪装成零成本 resume | `ResumeNoSendReport` |
| `AI-DSH-X20` | profile 访问 repo、`.env`、账户文件、shell 或非 provider 网络 | capability/OS isolation 确定性拒绝；Research Pack 是唯一模型输入 | `DshIsolationReport` |
| `AI-DSH-X21` | hidden title/retry/compaction/search/subagent request | runtime contract terminal failure，完整记录额外 request，不接受模型结果 | `HiddenCallDetectionReport` |
| `AI-DSH-X22` | unknown 持续到 global deadline | research terminal operational failure，但 call external effect 永久为 unknown；不得重试 | `UnknownDeadlineReport` |
| `AI-DSH-X23` | secret 出现在 argv/env/file/session/log/result/error 任一位置 | pre-submit surface 零外发阻断；post-submit 发现则 terminal security failure，保留 effect/预算、隔离证据、禁用该 secret version 并触发 rotation-required，不采用结果 | `CredentialLeakRejectionReport` |
| `AI-DSH-X24` | bounded-lane 第二 turn 复用首 turn 授权或把 capability 放进 history | 外发前拒绝；零 provider delta，不采用 lane 结果 | `LanePerTurnAuthorizationReport` |
| `AI-DSH-X25` | installed closure partial/tampered/symlink/权限漂移或 receipt 换绑 | resolve/spawn/accept 前拒绝，零 provider delta；旧 descriptor 不采用结果 | `DshInstallTamperReport` |
| `AI-DSH-X26` | spool symlink/path traversal/跨 attempt 换绑，或 GC open/unknown entry | store 确定性拒绝且未知证据仍在；空间不足 fail closed，不删除证据 | `DshSpoolAdversarialReport` |
| `AI-DSH-X27` | grant 被旧 lease、另一 process/session/turn 重放或重复 consume | submit 前拒绝；对应 physical request 不外发，claim/nonce 可对账 | `ProviderGrantReplayReport` |
| `AI-DSH-X28` | descriptor cap、stage/canary absolute deadline、collect grace 与 global reconciliation deadline 冲突 | fresh/collector effective deadline 精确取最早值并进入 binding/claim；跨 lease/restart/时钟回拨均不延长 | `EffectiveDeadlineReport` |
| `AI-DSH-X29` | 两个 worker 并发签发 collector slot，或 collector started 后 takeover/退出 | category+total 只有一组原子 ordinal；同 reservation 第二次 exec 被拒绝，started slot 不归还，实际 process starts 不突破 ceiling | `CollectorProcessSlotRaceReport` |

Mock runner 证明协议实现，fake provider 证明调用守恒，真实 binary canary 证明精确 profile/model
组合能够运行；三类证据不能互相替代。真实金融 Research Pack、sealed 数据、账户事实、shadow 或
订单不进入 live canary。
