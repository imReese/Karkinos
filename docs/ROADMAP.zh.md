# Karkinos 路线图

[English Roadmap](ROADMAP.md) | [返回中文文档](README.zh.md) | [战略目标](KARKINOS_GOAL.md) | [架构](ARCHITECTURE.md)

本文是 [ROADMAP.md](ROADMAP.md) 的中文摘要版，用于快速理解当前方向、
里程碑和自动化成熟度。英文版仍保存完整历史验收标准和更细的实施记录。

## 当前定位

Karkinos 是面向中国市场的个人量化投研与交易平台。路线图的重点不是更快
下单，而是让每一次交易相关动作都经过数据、研究、成本、风控、账户事实、
paper/shadow、人工确认、对账和复盘。

自动实盘下单会作为后续受控能力保留，但不会作为默认入口。未来如果接入券商
桥接，也必须经过明确配置、强门禁、审计记录和可暂停机制。

## 里程碑状态

| 里程碑 | 状态 | 能力 |
| --- | --- | --- |
| v0.2 | 已完成 | Profit Discipline MVP |
| v0.3 | 已完成 | Daily + Intraday Decision Platform |
| v0.4 | 已完成 | Strategy Lab Backtesting Engine |
| v0.5 | 已完成 | Quant Research Quality & Production Evidence Hardening |
| v0.6 | 已完成 | Account Truth & Reconciliation Engine |
| v0.7 | 已完成 | Account Truth Review Center |
| v0.8 | 已完成 | Strategy Assignment & Attribution Engine |
| v0.9 | 已完成 | Data Plane & Market Reliability |
| v1.0 | 已完成 | Strategy Runtime Foundation |
| v1.1 | 已完成 | Paper Broker & OMS |
| v1.2 | 已完成 | Broker Evidence Connector |
| v1.3 | 已完成 | Professional Decision Workflow |
| v1.4 | 已完成 | Strategy Attribution 2.0 + Broker Fee & Cost Basis Fidelity |
| v1.5 | 已完成 | Daily Trading Plan & Portfolio Construction |
| v1.6 | 已完成 | Operations Center & Paper/Shadow Runbook |
| v1.7 | 已完成 | Controlled Broker Bridge Foundation（非提交式） |
| v1.8 | 规划进行中 | Capital-Bounded Controlled Execution（受控资本执行） |
| AI 原生第一阶段 | 基础已实现 | 厂商中立、证据绑定的投研 workflow 运行基础 |
| AI 原生 1.1 | 只读边界已实现 | 不可变 canonical evidence 捕获与 context 绑定读取 |
| AI 原生 1.2 | 捕获边界已实现 | 人工显式启动、无模型调用的 canonical context 捕获 |
| AI 原生 1.3 | 任务/复核边界已实现 | 人工证据绑定任务、复核 UI 与哈希链回放，模型执行关闭 |
| AI 原生 1.4 | 离线 fixture 生命周期已实现 | 已接受任务的 claim/debate/report/memory、漂移失效，无外部模型 |
| AI 原生 1.5 | 人工记忆处置已实现 | 精确分析复核、回忆资格、追加式回放与漂移自动失效 |
| AI 原生 1.6 | 外部连通性边界已实现 | 人工显式、固定非财务 OpenAI-compatible 探针与脱敏幂等审计 |
| AI 原生 1.7 | 保存回测外部报告边界已实现 | 明确外发同意、单条 canonical 证据、单份结构化非权威报告且无交易权限 |
| AI 原生 1.8 | 已复核记忆检索边界已实现 | 显式 ID 白名单、当前证据重绑定、漂移回放，且无自动回忆或 provider 调用 |
| AI 原生 1.9 | 离线记忆辅助分析边界已实现 | 显式消费 retrieval、强制重读当前证据、确定性 claim/debate/report，且无模型或交易权限 |
| AI 原生 1.10 | 外部记忆辅助分析边界已实现 | 显式证据外发、三阶段当前证据绑定调用、保留模型推理模式且无交易权限 |
| AI 原生 1.11 | 外部分析人工复核边界已实现 | 精确处置、质量/延迟/token/成本证据、漂移失效，且无 memory 或交易权限 |
| AI 原生 1.12 | 外部已复核研究 memory 提升已实现 | 人工显式、可撤销、源绑定的历史 artifact，且无自动召回或交易权限 |
| AI 原生 1.13 | 外部已复核 memory 检索已实现 | 独立版本契约、精确 promotion id、当前完整证据重绑定，且不改 v1 或调用模型 |

## AI 原生投研主线

这条主线用于增强问题拆解、证据收集、多角色争论、报告、人工复核和长期研究记忆，
不替代 canonical 财务计算，也不建立第二条交易权限链。

第一阶段“架构与运行基础”包括：

* provider、model、agent role 分离注册，模型厂商不成为核心领域身份；
* 有状态 workflow 绑定一个不可变 context，其中必须包含 valuation snapshot、
  ledger cutoff/fingerprint 和持久化 evidence references；
* claim、debate、report、不可执行的 trade-plan draft、review 和 memory artifact
  使用带证据引用的领域契约；
* 确定性 orchestrator 负责阶段顺序、重启检查点、幂等、重复运行、部分/失败状态、
  证据漂移阻断和审计回放；
* tool permission registry 默认拒绝，只允许已注册的持久化只读工具和纯计算工具，
  OMS、账本、风险决策、kill switch、资本授权、券商和 provider 权限命名空间不可注册；
* SQLite 审计存储只写 `ai_*` 注册、上下文、workflow、run、tool call、artifact
  和哈希链事件表；
* 研究 workflow 唯一 provider 实现仍是本地 deterministic fixture；外部 provider
  不会自动注册进 orchestrator，也不绑定 DeepSeek 或其他单一厂商。

本阶段的确定性验收覆盖重启、幂等、重复运行、阶段失败、部分结果、证据漂移、
越权工具请求与审计重放，并验证 AI trade-plan draft 不会修改 OMS、账本、风控、
kill switch、资本授权或券商 submit/cancel 状态。

1.1 增量已经建立第一层 canonical evidence 只读边界：显式调用方可以把既有
canonical projection 原样封装成内容寻址、不可变的 `ai_canonical_evidence` 记录；
Portfolio、Account State、Operations、Research Evidence、Account Truth 和
paper/shadow 工具只能按冻结 context 内的 evidence reference 读取。所有记录必须
共享精确的 valuation snapshot、ledger cutoff 和 ledger fingerprint；重复捕获幂等，
内容变化产生新引用，重启后仍读取同一记录。partial、stale、estimated 和
unreconciled 证据只可用于诊断，明确标记为非权威。

1.2 增量已经注册唯一的人工显式入口
`POST /api/ai/research-contexts/capture`。请求必须包含确认语句、操作者标签、研究问题、
幂等键、账户别名和精确证据选择；Research Evidence 与 paper/shadow 还必须指定精确的
持久化记录 id。它复用既有 Portfolio、Account State、Operations、Research Evidence、
Account Truth 与 paper/shadow canonical builder/reader，要求 valuation snapshot 已持久化
且可回放，并在完成前再次校验 snapshot、ledger cutoff 和 fingerprint。重启和重复请求
复用同一内容寻址证据；同一幂等键不能更换输入，失败的审计阶段可安全重试。

该入口只写 `ai_canonical_evidence`、`ai_context_snapshots` 和
`ai_context_capture_runs` 等 AI 审计事实，不启动 workflow，不调用 provider/model，
不刷新行情或券商数据，也不修改账户、OMS、账本、风控、对账、kill switch 或资本授权。
scheduler/startup hook、后台 AI 任务和真实 provider 仍未注册。

1.3 增量在 capture 之后加入人工 research task 与 review 边界。任务只能引用已完成的
capture，并再次重放 context/evidence fingerprint、valuation snapshot、ledger cutoff 与
ledger fingerprint。非完整证据保留用于诊断，但任务标记为 `blocked_by_evidence`，不能
接受为可分析上下文。人工可以接受完整上下文、要求修订或不分析并关闭；这些决定只写
`ai_research_tasks`、`ai_research_task_reviews` 和逐任务哈希链
`ai_research_task_events`。Strategy Lab 面板默认关闭且不发请求，显式打开后才读取，
记录时先 capture 再创建 task；可选回测证据必须绑定精确 result id。人工接受上下文也
不会启动 workflow/model，不会产生任何交易权限。

1.4 增量加入第二次人工显式命令：只有 `context_accepted` 且证据完整权威的任务，才能在
确认“无外部模型”的前提下运行离线 deterministic fixture。固定阶段会通过默认拒绝的
canonical tool 边界逐条读取证据，并保存带引用的 claim、debate、report 和待人工复核
memory。精确重试和重启复用同一 workflow；task/context/valuation/ledger 或 evidence
fingerprint 漂移会阻断启动，完成后发生漂移则使绑定、审计回放和 memory 明确失效。
GET 不初始化 schema、不轮询、不刷新 provider，也不启动后台任务。该能力不联网、不读取
API Key、不调用真实模型，不把输出当作账户事实，也不修改 OMS、账本、风控、kill switch、
资本授权或券商 submit/cancel。

1.5 增量加入最终人工 analysis review：复核人必须填写备注，并在“接受为已复核研究记忆、
要求修订、驳回”中选择一次最终处置。接受要求 workflow 完成且非 partial、分析回放有效、
精确 claim/debate/report/memory 生命周期完整、所有工具调用完成、memory 来源绑定正确，
并重新计算每个 artifact fingerprint。review 把这些事实以及 context、valuation/ledger 与
evidence 状态绑定为 analysis-target fingerprint，并写入独立哈希链。重启和并发精确重复
只保留一条 review/event；同键换输入或第二次最终决定 fail closed。每次 GET/replay 都重新
构造 target，后续 evidence、artifact 或审计漂移不会删除历史决定，但会把已接受记忆改为
`invalidated_by_evidence_drift` 并撤销回忆资格。无效分析仍可记录修订或驳回。

1.6 增量加入独立外部模型连通性边界。只有人工携带身份、幂等键和精确确认语句调用
`POST /api/ai/provider-connectivity/checks` 时，通用 `openai_compatible_https` adapter
才会发送一次固定的非财务探针。请求不包含账户、持仓、估值、账本、策略、研究证据、
券商信息或工具定义，也没有自动重试、后台任务和启动钩子。环境变量配置优先；既有忽略
配置中的 `ai.api_keys` 只作为迁移兼容入口。密钥仅短暂存在于请求内存和 Authorization
header，不进入响应或数据库。

幂等记录在网络调用前取得执行权，精确重复不会产生第二次模型调用或费用；同键换输入
fail closed。`ai_provider_connectivity_checks` 只保存 provider/model、endpoint origin、
脱敏状态、延迟、token 用量和内容指纹，不保存 prompt、response body 或密钥。该能力只
证明鉴权和协议可用，不启动 research workflow、不生成 artifact/memory、不进入 Decision，
也不修改 OMS、账本、风控、kill switch、资本授权或券商状态。

1.7 增量只开放一个受限真实分析入口：
`POST /api/ai/external-research/backtest-reports`。操作者必须选择一条已保存
回测、提供身份/幂等键/研究问题，并使用明确表示“把所选保存回测证据发送到已配置
外部模型”的精确确认语句。canonical research capture v2 只投影数据库中已保存的
收益、回撤、测试区间、扣费后证据、成本、研究 gate 和限制，不重新计算；只有
`complete` 且 `analysis_ready` 的记录才能继续。

本地 orchestrator 只授权一次 `research_evidence.read`。外部请求不会包含账户别名、
持仓、valuation/ledger identity、Account Truth、Operations、paper/shadow、风控、OMS、
资本、券商或权限事实，也不给 provider 任何工具。模型输出必须在本地归一化并通过
schema 校验，随后才会作为引用精确 evidence/context fingerprint 的非权威 `REPORT`
保存并要求人工复核。原子 run claim 阻止并发重复计费；终态重复只读原结果，同键换
输入 fail closed，失败不会自动重试。原始畸形响应和 provider error body 不落库；该
边界不生成 memory、Decision 输入、trade-plan draft，不修改任何财务事实或执行权限。
已配置模型的推理模式不会被关闭；版本化 JSON-only prompt 提供精确结构示例和证据审阅
清单，reasoning 原文不落库。本地只接受经过审查的 wrapper、嵌套及中英文常见字段别名，
缺少逐项证据摘要时会明确标为仅来源引用并要求人工复核，不会静默补造金融事实。

1.8 增量加入独立的已复核记忆检索边界：只有人工携带身份、用途、幂等键、精确确认语句、
一个已经持久化的当前 context，以及 1–20 条明确 analysis review id，才能调用
`POST /api/ai/reviewed-memory-retrievals`。每个候选都必须在当次重放后仍为
`reviewed_memory` 且具备回忆资格；系统会重验原分析、artifact、evidence、context 和
review 哈希链，并按 canonical tool identity 把原证据逐项映射到当前 context 中唯一的
`complete` 证据。缺失、partial、stale、estimated、同 tool 重复、指纹漂移或财务身份不一致
都会 fail closed。

返回的 memory 明确标记为“历史已复核研究输入”，同时本地绑定当前 valuation snapshot、
ledger cutoff/fingerprint，并要求未来 workflow 重新读取当前证据，不能把旧结论当作当前
事实。请求和单事件哈希链只写独立 `ai_*` 审计表；每次 GET/list/replay 都重新推导资格，
漂移后不再返回 memory 内容，GET 不初始化 schema。当前没有 embedding、语义搜索、调度、
自动 prompt 注入、provider-side tool、注册的 retrieval tool、外部模型调用、Decision 输入、
trade-plan draft、财务写入或权限效果。

1.9 增量实现独立消费边界，但不把 fixture 宣称为生产 AI 智能。只有人工携带身份、研究问题、
幂等键和精确的“离线且无交易权限”确认语句，才可调用
`POST /api/ai/reviewed-memory-retrievals/{retrieval_id}/fixture-analyses`；输入必须是当次仍有效
的 1.8 retrieval 及其精确持久化 context。retrieval bundle 只在本地作为历史已复核研究
输入绑定，不注册为 provider-side 或 orchestrator retrieval tool。claim role 必须先通过
既有默认拒绝的 canonical tools 独立读取当前 context 中每一条证据，随后本地 deterministic
fixture 才固定生成带引用的 claim、debate 和 report；三者都记录当前证据、retrieval target、
历史 memory 非事实标签和 `authority_effect=none`，且不生成新 memory。

数据库 run lease 与 workflow 幂等键保证重启和并发重复只运行一次；阶段失败和显式 partial
保持终态并可回放，GET 不续跑、不初始化 schema。后续 review、retrieval、context、evidence、
artifact、tool-call 或审计漂移会保留历史结果，但撤销其当前绑定与有效回放资格。该边界没有
外部模型、网络、API Key、语义检索、自动回忆、Decision 输入、trade-plan draft、财务写入、
权限变更、券商动作或执行/资本授权。

1.10 增加一个经过单独审查的真实 provider 边缘入口，但不让 provider 或其推理成为权威。
只有人工携带身份、研究问题、幂等键和精确的“允许外发已选择记忆与当前证据但无交易权限”
确认语句，才可调用
`POST /api/ai/reviewed-memory-retrievals/{retrieval_id}/external-analyses`。
本地 deterministic orchestrator 继续拥有 claim、debate、report 顺序；每一阶段都必须先经
既有默认拒绝的只读工具重新读取全部当前 canonical evidence，随后才发出一次受限的
OpenAI-compatible 请求。retrieval 不会注册成 provider-side tool。

外发内容只包括脱敏后的完整当前证据、人工明确选择的历史已复核 memory，以及前序已归一化
artifact。账户别名/号码、API Key、OMS、风控、资本、券商、权限与执行状态均不进入内容。
prompt v2 不关闭模型自身的推理模式，把精确 JSON schema、结构示例、允许引用的 evidence
目录和最终自检提升到 Karkinos 系统 contract，并把嵌入证据字符串视为不可信数据。DeepSeek
封闭世界规则禁止补写未提供的标的名称、市场惯例/相关性/阈值，也禁止提出 provider/券商刷新、
解除 kill switch 或扩权；推断必须标明缺失证据。DeepSeek 边缘显式启用 thinking/high effort，
使用有界 180 秒、16K 输出预算；provider tools 和自动重试
仍关闭。本地只做有界的等价结构/别名归一化，未知或缺失引用、截断、畸形 JSON、证据不完整
都会 fail closed。系统只保存归一化 artifact、指纹、token、完成原因及 reasoning 是否存在/长度，
不保存原始响应、provider envelope、reasoning 原文或密钥。prompt-v1 终态只保留为不可变历史，
不会被静默改写或重跑；新调用需要新的显式请求和幂等键。

一个永久 analysis run claim 加每阶段一次 insert-once call claim，阻止并发重复和中断后的
自动扣费重试。终态精确重放和所有 GET/list/replay 不加载凭据、不联系 provider，也不续跑。
后续 retrieval、review、context、evidence、artifact、tool read、model call 或审计漂移会保留
历史结果但使回放失效。该 workflow 不创建 memory、Decision 输入或 trade-plan draft，且无
财务写入、权限变更、券商动作或执行/资本授权。

1.11 要求在 1.10 输出被称为“已复核研究”前，必须另行人工处置。只有携带复核人身份、幂等键、
说明、精确无 memory/无权限确认，并选择“接受为已复核研究 / 要求修订 / 拒绝”，才可调用
`POST /api/ai/external-memory-informed-analyses/{analysis_id}/reviews`。复核 target 会独立重放
analysis、retrieval/context/evidence、claim/debate/report 指纹与引用、三次 model call、本地
tool read、provider/model/prompt 身份及 workflow 审计链；无效或不完整 target 不能接受，
但仍可记录修订或拒绝。

人工必须记录证据落地、反方处理、不确定性校准、决策有用性四项 1–5 分 rubric，以及事实错误
和无证据主张数量；任一错误计数非零都阻断接受，不使用不透明总分自动晋级结论或模型。客观
质量证据汇总 schema/引用完整度、provider 报告的 prompt/completion token、阶段/总延迟和
reasoning 是否存在；原始 reasoning 和响应仍不保存。成本证据必须二选一：人工复核的生效期
定价快照，或明确的缺价原因。估算只按“人工定价 × provider token”确定性计算，不冒充账单；
缺 usage 时标记 `partial_usage`，不猜成本。

每个 analysis 只有一个最终复核和一个哈希链事件，并发与重启幂等。GET/list/replay 不初始化
schema、不加载凭据、不调用模型、不刷新事实。后续 evidence、artifact、usage、provider、
prompt 或审计漂移会保留历史复核但撤销当前资格。即使接受，结果仍明确
`memory_recall_eligible=false`、`provider_promotion_eligible=false`，且无 Decision、trade-plan、
财务、券商、权限、资本或执行效果。

1.12 把“接受为已复核研究”和“提升为历史 memory”保留为两次独立人工动作。
`POST /api/ai/external-analysis-reviews/{review_id}/memory-promotions` 只接受当前仍可重放且有效的
1.11 已接受复核，并要求精确无当前事实、无 Decision、无交易权限确认。新的历史 memory
artifact 只复制规范化 report 和安全 provenance，绑定 review/report/context/retrieval/evidence、
provider/model/prompt 与审计身份，不保存原始 reasoning 或 provider 响应。每次 GET/replay 都
重新验证源；漂移会保留历史但隐藏内容并撤销召回资格。

`POST /api/ai/external-reviewed-memory-promotions/{promotion_id}/revocations` 只追加一次终态撤销和
哈希链事件，不删除任何分析、复核、report 或 memory 记录。该阶段不改写既有 retrieval v1，
不自动召回，也不让外部模型消费新 artifact；后续集成必须使用新版本契约并保留 v1 指纹与历史
重放。所有 promotion/revocation 都不调用模型，不产生当前事实、provider 晋级、Decision、
trade-plan、财务、券商、权限、资本或执行效果。

后续仍按独立审查逐步迁移：1.13 只增加版本化显式检索且不使旧 v1 历史失效；下一步才评估
由受限 workflow 显式消费该 retrieval。真实 provider
进入更广泛的 task/debate/memory/Portfolio/Account Truth/Operations/paper-shadow workflow
必须再次单独审查和用户授权。任何 trade-plan draft 进入 Decision 都必须经过独立人工交接，
既有账户事实、风控、paper/shadow、人工确认、资本、OMS、gateway、对账和 kill
switch 门禁继续拥有唯一权威。

1.13 已用独立版本契约完成上述第一步，但尚未让任何模型消费结果。只有人工携带身份、用途、
幂等键、精确确认语句、一个既有持久化 current context 和 1–20 个明确 Phase 1.12 promotion id，
才能调用 `POST /api/ai/external-reviewed-memory-retrievals`。系统逐一重放 promotion、源复核、
analysis、artifact 与审计链，再按 canonical tool identity 把源证据映射到当前 context 中唯一的
`complete` 记录。当前 context 继续复用既有唯一 valuation snapshot、ledger cutoff/fingerprint
校验；partial、stale、estimated、缺失、重复 tool、撤销或任一源/当前/审计漂移都会 fail closed，
并在后续读取时隐藏 memory 内容而不删除历史。

新请求、表和哈希链事件与 Phase 1.8 retrieval v1 隔离；v1 request fingerprint、schema、表和
历史 replay 均保持不变。1.13 没有语义搜索、调度、自动 prompt 注入、provider tool、外部模型
调用、Decision 输入、trade plan、财务写入、券商动作或权限效果。下一步若让离线或真实模型
消费该 retrieval，仍必须另建显式、受审查且包含数据外发确认的边界。

## 自动化成熟度

自动化按成熟度逐层推进。越靠后的层级，越接近真实资金执行，也越需要更严格的
证据和暂停机制。

| 层级 | 名称 | 含义 |
| --- | --- | --- |
| L0 | 研究证据 | 注册策略、可复现回测、扣费后/OOS 证据、限制说明 |
| L1 | 每日交易计划 | 候选池、阻断原因、费用、风险和人工确认下一步 |
| L2 | Paper/shadow 运行闭环（已完成） | 定时模拟执行、偏差复核和运行摘要 |
| L3 | 人工执行辅助（已完成） | OMS、手工票据、券商证据导入、手工成交证据和执行对账已进入可用路径 |
| L4 | 受控券商桥接（计划中） | 未来每笔订单仍须经过账户事实、风控、paper/shadow、connector health、对账和人工确认门禁 |
| L5 | 受控资本执行 | 从小风险敞口试点开始，显式授权、限时限额、可暂停，并依据证据由人决定扩容或缩容 |
| L6 | 无人值守全账户自动化 | 非目标；Karkinos 不要求永久授权、无人监督的真实资金执行 |

## 已完成主线：v1.6

v1.6 的目标是把“今天该做什么”变成可重复运行、可复核、可追踪的日常操作
手册。

范围包括：

* Operations Center 展示数据、账户、策略、风控、paper/shadow、调度和审计
  子系统的健康状态、最近运行、下一步动作和限制。
* 每日交易计划可以进入 paper/shadow 模拟，不创建真实订单、不写生产账本、
  不改变现金或持仓。
* 运行记录保留 run id、输入快照、fingerprint、状态、错误、重试和限制。
* 自动化告警会覆盖 kill switch、执行对账缺口和失败的 paper/shadow automation
  run；失败 run 会带 retry/limitations 和不会提交券商订单的安全证据。
  只读券商 connector 配置不完整时也会生成可确认告警，但不会连接券商客户端或保存凭据。
  每日交易计划已经被风控阻断时，也可以扫描成需要人工复核的告警。
  行情健康快照显示 stale / cache / missing / estimated 等陈旧状态时，也会生成带
  stale 标的样本和下一步动作的人工复核告警。
  账户事实快照处于 degraded / blocked 或存在未解决差异时，也会生成带复核动作、
  阻断原因和不改写账本证据的人工复核告警。
  paper/shadow 运行出现 diverged 或 review_required 状态时，也会生成带 run id、
  偏差数量、证据引用和下一步复核动作的人工复核告警。
  paper/shadow 偏差摘要会同时比较预期策略行为、模拟订单/成交、账户事实状态、
  实现的行情上下文、费用证据和不会提交券商订单的安全标记；Decision 日度交易
  计划面板也会把这些摘要作为只读复核证据展示出来，Overview 今日待办会显示紧凑的
  偏差复核摘要，Trading 执行审计会显示最新 paper/shadow run 证据。已接受的
  偏差复核会保留原始 divergence 状态用于审计，同时暴露 runbook effective status
  作为人工确认交接状态。
  只读券商 connector 运行期快照出现 runtime_degraded / stale / unavailable 等
  降级状态时，也会生成带 heartbeat、错误信息、能力标记、人工复核要求和不会提交
  券商订单证据的告警；这仍然只消费健康快照，不连接券商客户端、不保存凭据、不下单。
* Decision 和 Overview 页面展示下一步动作，但不把候选池数量误写成必须执行的
  交易数量。
* 任何异常状态都要说明是数据问题、账户事实问题、风控阻断、模拟偏差、人工确认
  待办，还是系统运行问题。

v1.6 的关键链路：

```text
每日交易计划
-> 下单前风控
-> paper/shadow 模拟运行
-> 偏差复核
-> 人工确认
-> 后续手工票据或受控桥接
```

## 已完成基础：v1.7

v1.7 完成的是受控券商桥接的**非提交式基础**，不是默认交易机器人，也不表示
L4 实盘提交已经可用。券商 submit、可执行 cancel、自动写生产账本和 v1.8 自动试点
仍不可用。

范围包括：

* 手工票据导出或复制，先支持非提交式执行辅助；当前已支持带证据门禁的
  manual-ticket preview / dry-run / create，导出载荷也会带操作员可读字段标签、
  账户别名、费用税费假设、现金影响、计划后持仓/成本口径预览、交易时段限制和
  不会提交券商订单的安全标记。
* 券商网关能力模型：健康检查、订单预览、dry-run、查询订单/成交/资金/持仓、
  以及默认关闭的提交能力；当前后端已支持 connector health、运行态只读 connector
  snapshot 查询、本地订单 query、基于暂存 broker evidence 的 account-facts 查询、
  fills query，并默认拒绝 broker cancel；手工票据动作会被全局 kill switch 阻断，
  gateway status 会暴露该阻断状态；
  Decision Cockpit 的只读自动化面板也会展示该状态、gateway 查询/读取能力标签、
  暂存成交轮询摘要和本地订单查询证据；当执行对账仍有未处理项时，面板会给出只读的
  暂存成交对账复核提示；这些能力都不会连接券商客户端，也不会提供提交、撤单或账本
  同步控件。Automation Cockpit 和 Decision Cockpit 也会在同一非提交式合约下展示
  运行态只读 connector snapshot 摘要，包括资金、持仓、订单和成交计数，并隐藏账户
  id，不增加提交、撤单或账本同步控件。只读 connector health 也会暴露明确的
  capability scope，以及被阻断的 preview/export/dry-run/cancel/submit 能力，方便后续
  受控桥接评审区分查询权限和执行权限。
  Operations 告警可以通过 broker gateway health contract 消费只读 connector snapshot，
  并保留同一套 capability scope 与 preview/export/dry-run/cancel/submit 阻断字段，
  方便运行手册复核连接器降级时仍能看到执行权限边界。
* 同一个 Decision Cockpit 面板会只读展示策略晋级状态，包括 lifecycle stage、
  paper/shadow 门禁状态、缺失要求、可选回测证据 id，以及明确的 live-like disabled
  边界；人工暂停或退役会作为 audit-only 生命周期证据展示，controlled bridge pilot
  仍默认拒绝并记录审计事件。策略晋级状态只说明生命周期和证据准备度，不会单独授权执行。
* 每个 live-like 动作都必须经过账户事实、研究证据、风控、paper/shadow 和人工
  确认。
* 券商回报或导入成交先进入 broker evidence，再通过执行对账检查，不能直接改
  生产账本；当前已提供 execution reconciliation API 用于比较 OMS、gateway event
  和 broker evidence，匹配到的暂存券商成交证据也会携带只读费用、税费和净额摘要，
  Decision Cockpit 也会展示成交总额、手续费 / 税费、过户费、净额和需复核安全标记，
  供人工复核后再考虑账本动作。
* 手工票据创建后，broker gateway 可以只读预览操作者录入的实际成交价格、数量、
  手续费、税费、过户费、净现金影响、持仓/成本口径预览、ledger entry 草稿和确定性
  preview fingerprint；该预览不创建 gateway 事件、不改变 OMS、不写生产账本，仍要求
  后续人工显式保存。
  Trading approvals 页面会在手工票据导出后展示该只读预览，但不提供保存账本、
  应用成交或提交券商控件。
  gateway 也可以在 preview fingerprint 匹配时记录手工成交 evidence 审计事件，
  用于后续复核串联；该事件不创建成交、不改变 OMS 状态、不写生产账本。
* 策略代码不能直接调用券商适配器；所有桥接动作必须通过 policy、risk、OMS、
  gateway 和 reconciliation 服务。
* Trading 的手工票据导出面板会交接到账户事实流水导入和执行对账。执行对账会比较
  手工成交证据与匹配券商流水中的价格、数量、成交额、手续费、税费、过户费和净额；
  Decision 只读展示逐字段的手工值/券商值，差异进入人工复核队列，不改变 OMS 或
  生产账本，也不提供同步账本、应用成交、撤单或提交控件。

## 规划进行中、执行未开启：v1.8

v1.8 的规划已经启动，但实盘提交和自动执行仍未实现、未开启。这个里程碑不是把产品
永久限制在“小资金”，而是把账户资产与机器权限分开：第一次真实执行使用小风险敞口
限制未知故障影响，后续能否扩大额度必须由人根据实盘证据重新授权。

详细实施顺序见 [受控资本执行计划](CONTROLLED_EXECUTION_PLAN.md)：

1. 非提交式资本授权合约与确定性 fail-closed 测试。
2. 一个真实券商的只读资金、持仓、订单、成交和健康状态运行验证。
3. 每笔订单人工确认的受控提交、回报、撤单、部分成交和恢复链路。
4. 操作者签发的限时限额 session，在额度内受控执行并自动暂停。
5. 根据容量、流动性、滑点、回撤、异常和对账证据人工扩容或缩容。

截至 2026-07-10，第 1 步的首个隔离切片已经完成：已加入版本化资本授权模型、纯
fail-closed 评估、确定性输入指纹、结构化额度/剩余额度/阻断原因和无提交、无撤单、
不改 OMS、不写账本、不能自行扩权的安全标记及测试。当前故意没有接入 config、数据库、
API、UI、OMS、gateway 或券商；这些属于后续独立评审切片。

第二个 Stage 0 切片现已加入追加式评估审计和 status/preview/record/list API。即使评估
返回 `allowed=true`，runtime authority 和 broker submission 仍保持 disabled；没有
issue、revoke、enable、resume、submit 或 cancel 接口。静态配置继续只表示白名单预览，
不能签发资本执行权限。相同输入指纹的顺序重跑会复用已有事件；并发重复请求的数据库级
唯一性仍是后续持久化评审项。

Stage 0 v2 进一步拆分只读 `evidence_connector` 与未来 `execution_gateway`：policy/context
必须分别绑定两个不同且不重叠的身份、独立健康/能力事实和 verified 同账户关系。只读侧
暴露 submit capability 会阻断；执行侧即使声明可提交也保持 runtime-unverified，不能联系
券商、授予权限或解除默认提交阻断。每单 dossier 与 session envelope 已按这两个角色读取
证据，消除了“同一 connector 既必须只读又必须可提交”的结构矛盾。

Stage 1 的 broker-neutral 只读 soak 基础也已落地：显式配置的通用 local export 脱敏
快照可以持久化并按 provider market calendar 统计真实交易日覆盖；缺日历、休市、陈旧、
读取失败、能力不完整或暴露 submit capability 都不会计入健康日，并会进入 Operations
告警。达到 20 个健康交易日只完成运营 soak；旧的 Stage 1 汇总接口不会仅凭天数自动
晋级。

Stage 1 运营 runbook 现已加入 startup、intraday、end-of-day 追加式运行证据；收盘阶段
要求执行对账为 clear 且 open item 为零。断连、schema drift、stale data、重复证据和
service-instance restart recovery 演练会记录确定性 pass/fail 结果，失败会进入统一
Operations 告警。这些接口仍不具备提交、撤单、OMS/生产账本写入或资本授权能力；真实
券商 20 日运行和完整进程/券商终端重启仍需要由操作者在真实环境完成。

Stage 1.1 已加入独立的签名晋级证据 dossier：它绑定最早 20 个 clear-reconciled 交易日、
每天三个运营阶段、五类恢复演练、稳定的脱敏账户身份，以及当前 clear/pass/fresh/零未清项
的 Account Truth 来源指纹。配置公钥验证的 Ed25519 owner acceptance 还必须签署“同一
账户”与“已在服务外完成完整进程/券商终端重启”的明确声明；来源漂移会使 acceptance
失效。该切片只证明 Stage 1 evidence readiness，不授予资本/runtime authority、不改变
OMS、不联系券商。

Stage 2 的非提交式每单确认基础也已开始：系统可把 OMS 订单条款、资本评估、Account
Truth/研究/风控/paper-shadow gateway evidence、最新 connector soak、前序执行对账和
kill switch 归一化为确定性 dossier 指纹；只有 review gate 通过时才能记录精确指纹
attestation，错误指纹和阻断 dossier 会留下追加式拒绝审计。记录现在还必须引用与精确
dossier 绑定、由配置公钥验证的短时 Ed25519 approval。每次 preview 现在还解析精确
capital-policy evidence connector 的当前签名 Stage 1 promotion，并把 promotion dossier、
运营来源、Account Truth 来源和 verified acceptance id 纳入每单指纹；不同的 execution
gateway 单独绑定，并在精确当前 Stage 2.4 记录匹配前保持 runtime-unverified。缺失、非法、
connector 不匹配、provider 失败或来源漂移都会 fail closed；有效 promotion 只清除 Stage 1
子阻断，clear verification 也只清除 runtime-verification 阻断。runtime authority、live
gateway 和 broker submission 继续作为硬阻断。
该记录不修改 OMS、不接触券商、不授予执行权限。

Stage 2.4 已加入独立 runtime execution-gateway verifier：它要求 verified evidence
connector/账户绑定、完整 submit/cancel/query/dry-run/idempotency 能力、60 秒内的健康来源
指纹，以及精确订单的零副作用 dry-run。通过/拒绝记录均追加式持久化；resolve 会重跑当前
检查、检测来源漂移并在五分钟后过期。生产 registry 默认为空，clear verification 也只是
非提交式 readiness evidence，不签发 authority、不预留预算、不修改 OMS/账本、不提交/
撤单。

Stage 2.5 已把 verification 精确绑定回每单 dossier：请求与已记录的 `manual_each_order`
资本评估必须引用同一条 `execution_gateway_verification:<fingerprint>`；每次 preview 和
confirmation 都重新 resolve，并精确匹配 gateway、只读 evidence connector、账户别名、
OMS order id、规范化订单指纹与脱敏 dry-run 订单条款。缺失、过期、来源漂移、provider
失败或 authority/submission 边界不一致会 fail closed，并使旧的签名 dossier 失效。clear
binding 只清除 runtime-
verification 阻断；runtime authority、live gateway、broker submission 与策略直连仍关闭。

Stage 3 的非执行式 session envelope 基础也已加入：proposal 必须引用一条已记录的
`session_bounded` 资本评估、显式 OMS 订单集合和最长 30 分钟的带时区窗口；系统绑定订单
指纹与 gateway evidence，并按不做买卖净额抵消的保守方式投影资本、现金、gross exposure、
换手、单笔、仓位变化、流动性和速率预算。精确 envelope attestation 和拒绝尝试都会追加式
审计，但不预留预算、不签发/恢复 runtime session、不修改 OMS、不联系券商。Stage 1/2
晋级、session-start Account Truth、per-symbol runtime limit、submit capability、原子预算、
runtime 限速/自动暂停和 live gateway 继续硬阻断。attestation 同样必须引用与精确 envelope
绑定的签名 approval，但签名通过不能签发 session。

Stage 3.3 已把相同门禁扩展到多订单 envelope：请求必须为每个 OMS order 提供一条唯一的
gateway-verification fingerprint，且 `session_bounded` 资本评估必须包含完全相同的类型化
引用集合。每次 preview/attestation 都逐单重新 resolve，并匹配 gateway、只读 connector、
账户、OMS order、规范化指纹与 dry-run 条款。缺失、额外、复用、过期、来源漂移或任一订单
错配都会阻断整个 envelope，并使旧签名失效。全部 clear 也只清除 runtime-verification
阻断；session authority、原子预算、自动暂停、live gateway 与 broker submission 继续关闭。

Stage 3.4 已加入短时 session-start Account Truth 证据：来源会根据最新券商导入、对账、当前
账本投影和人工复核重新构建，必须 clear/pass/fresh、零未决差异且不超过 120 秒。通过与拒绝
记录均追加式持久化；resolve 会重跑来源并在 120 秒后过期。session 请求和资本评估必须绑定
同一条类型化指纹、只读 connector 与账户别名。来源漂移、过期或身份错配会阻断 envelope 并
使旧签名失效；clear binding 只清除 Account Truth 证据阻断，仍不预留预算、不签发 session、
不改账户事实/OMS/账本，也不接触券商。

Stage 3.5 已加入原子 session 预算预留：只有当前仍有效的精确签名 envelope 才可进入预留；
系统重新检查资本评估、Account Truth、逐单 gateway dry-run、前批对账、kill switch、时间窗
和操作员签名，并用 SQLite `BEGIN IMMEDIATE` 串行校验同一授权/账户范围内的重叠资本、现金、
中国交易日换手与订单数。精确重跑复用同一条记录，并发超额只能有一个成功。预留不签发
session、不修改 OMS/账本、不联系券商，也不提供提交、撤单、恢复、续期或扩容动作。

Stage 3.6 已把 per-symbol runtime limit 纳入精确签名与原子预留。请求必须覆盖 projected
symbol 的完整集合，每个正数上限不得超过资本评估的 symbol/effective ceiling，也必须容纳
对应保守 gross projection。同一写事务会累计重叠 session 的逐标的预算；同标的并发超额只
允许一个成功，不同标的仍受共享账户预算约束。旧记录缺少逐标的证据时 fail closed；能力仍
不签发 session、不修改 OMS/账本、不联系券商或提交订单。

Stage 3.7 已实现内部 runtime rate admission ledger：服务端时间驱动 60 秒滑动窗口，精确
绑定 session/reservation/order/request，并在同一授权/账户的重叠 session 间采用最严格速率；
最后一个并发名额只允许一个请求成功。Stage 3.9 已接入持久化 token 认证 session provider，
但仍只开放只读 status/history，且没有公开 admit/submit/cancel 接口；它不产生券商权限。

Stage 3.8 已实现内部 automatic pause controller：对精确识别的 session 读取 allowlist 门禁事实，
Account Truth、风控、前批对账、paper/shadow、gateway、行情、预算、速率、kill switch、亏损/回撤、
拒单、账户变化、连续错误任一缺失或失败都会持久化不可变 pause event 与单向 `paused` 状态。
rate admission 在写事务内部复查 pause state，可阻断仍声称 session 启用的陈旧 provider。生产仅
开放只读 status/state/events；Stage 3.9 已提供 session identity，但未注入 live gate provider，
不存在自动恢复或券商写权限。硬阻断缩小为“实时门禁编排未接入”，恢复仍需未来独立的人审协议。

Stage 3.9 已实现独立签名的 runtime session authority。当前 attestation 与原子 reservation 会
被重新解析，owner 必须针对精确 issuance fingerprint 再签一次 Ed25519，并提交匹配签名作为
possession proof；公开 approval history 不回显签名，旧审批不能复用为 runtime 权限。token 只
首次显示且只保存 salted hash。session 到期、来源漂移、pause 或独立签名
revoke 后认证立即 fail closed；admission 写事务还会复查持久化 enabled/expiry/fingerprint/pause，
阻断陈旧 provider 竞态。公开 API 没有 admit、resume、renew、widen 或任何 broker 写动作。

Stage 3.10 已接入持久化 live-gate pause orchestration。系统会先保存 allowlist snapshot，再由
单向 pause controller 评估 Account Truth、风控、paper/shadow、对账、gateway、行情新鲜度、
runtime 预算/速率、kill switch、亏损/回撤、拒单、账户变化和连续错误；事实缺失或非法时 fail
closed 到 pause。监控 resolver 在上游来源漂移后仍能识别原 session，仅用于降低权限，绝不授予
runtime/broker authority。显式启动 scheduler 才会周期运行；token 持有者只能触发自身检查，不能
resume/renew/widen。当前 snapshot/行情/rejection 窗口分别为 30 秒、120 秒和 60 秒内 3 次。

Stage 3.11 已实现签名 paused-session replacement，而不是把旧状态原地改回 enabled。同一授权/
账户/策略存在未过期 paused scope 时普通 issuance 会阻断。replacement 必须绑定新 attestation、
新原子 reservation、暂停后连续至少 60 秒 clear 且最新不超过 30 秒的两条 snapshot，以及独立
`replace_paused_controlled_session` Ed25519 审批和签名 possession proof。账户/策略/操作员、
订单/标的、gross/现金/换手/订单数/逐标的/rate/期限只能不变或缩小；SQLite 单事务 revoke 旧
session 并签发新 token，并发冲突只能一个成功。没有原地 resume、renew、widen 或 broker 写权限。

Stage 3.12 新增默认关闭的单笔券商提交与恢复基础。只有精确 `manually_confirmed` 订单在重新
解析 Account Truth、风控、paper/shadow、前批对账、connector promotion 与 gateway verification
后，才能进入最终签名预览；实际接触券商还需独立 `submit_confirmed_broker_order` Ed25519 签名、
当前签名 release evidence、capability/health/dry-run 和 clear kill switch。SQLite 会先原子保存
intent 并把 OMS 置为 `submission_pending`，并发时只放行一次外部调用。accepted/rejected/unknown
分开持久化，unknown 绝不重提，只能 30 秒后按同一 client order id 查询。生产默认不注入 write
adapter 或 release provider，且没有自动/策略直连、撤单、成交应用、账本同步或扩资路径。

Stage 3.13 增加未对账提交 interlock 与可见性。任一 `prepared`、`submitted` 或
`submission_unknown` controlled intent 都会在 preview 与 `BEGIN IMMEDIATE` 事务内阻断不同
订单，因此不同订单并发只能一个获得外部调用资格。对账会区分 unknown、等待券商证据、匹配
证据、数量/状态冲突和确定性拒绝；unknown 会升级为 critical alert，并在 Operations 中优先展示
query-only 恢复。当前只有确定性拒绝/not-found 解锁；accepted 及匹配券商证据仍持续阻断，直到
未来独立签名的对账清算协议完成，且不会推断成交、修改 OMS/账本或自动提交下一单。

Stage 3.14 已实现该协议中最窄的“精确全量成交”分支。清算只接受当前 `submitted` intent
及其最新匹配对账项；同一验证通过的券商导入内，trade rows 必须精确合计为 OMS 全量，且
120 秒内 clear Account Truth 必须引用相同 import/file、未解决项为 0、ledger coverage 为
covered。独立 `clear_controlled_submission_reconciliation` Ed25519 签名后，SQLite 单事务记录
真实成交、推进 `submitted -> accepted -> filled`、保存 clearance 与终态 no-action 对账，再
解除 interlock；不会自动写生产账本。部分成交、跨导入聚合、撤单、自动/策略直连提交、扩资
仍然关闭。canonical CSV v2 可选保存 broker/client order id，但清算要求两者都与持久化
submit intent 精确一致；缺失、冲突或不安全的标识一律 fail closed，且这些字段不授予写权限。
pilot 前仍必须补齐券商专用、独立验证订单号关联的 partial-fill/cancel callback/poll 证据。

Stage 3.15 已统一为 broker-neutral 的“单笔订单生命周期证据契约”，不增加任何券商连接。
`scripts/import_broker_order_lifecycle.py` 默认只做 preview；只有显式 `--record` 加
`record_broker_order_lifecycle_evidence_without_execution_authority` acknowledgement 才会把
规范化 `exact_order_lifecycle` JSON 写入独立 SQLite 表。原始账户号只生成哈希，源文件路径不
保存；文件/证据指纹、账户/网关单调序号、broker/client order id、订单状态、累计成交/撤单量和
逐笔成交会被确定性绑定。凭证字段、陈旧/未来/无时区时间、数量不守恒、重复成交、序号回退或
复用、账户变化、订单身份/合约漂移、preview 后篡改一律 fail closed。execution reconciliation
只读持久化事实并显式展示 open、partial、partial+cancel、cancel、filled-awaiting-independent-
evidence 或 blocked；不会联系券商、修改 OMS/账本或解除门禁。统一生命周期清算判定同时运行在
签名清算事务、interlock preview 和下一单 `BEGIN IMMEDIATE` 提交事务中：抢在清算前落库的
冲突事实会拒绝清算，清算后新出现的冲突事实会重新把旧 intent 视为 unresolved。全量 lifecycle
证据仍不能替代独立 broker statement、最新 Account Truth 和 Stage 3.14 人工签名。

Stage 3.16 已加入通用、只读、显式启动的 collector ingestion 边界。批次绑定 deployment、
release、用户授权、provider/账户范围、连接/批次状态、cursor 和 callback telemetry；两阶段
prepare/commit 保证重启重放同一 observation 后才推进 cursor。本地 deterministic fixture 已覆盖
幂等、重复、乱序/跳号、断连、部分批次和 deployment drift。callback/poll 只是元数据，不会
加载 SDK 或连接 provider。证据采集不得修改 OMS、fills、账本、风控、kill switch、资本授权或
interlock。QMT、PTrade、本地文件 watcher 等均为默认未注册的可替换边缘适配器，接入前必须
单独审查依赖、权限、失败模式和发布/回滚，并由用户显式授权；Karkinos 不据此宣称官方支持。
旧 QMT v1 schema 只保留显式离线迁移入口，正常 importer 会拒绝它。

Stage 3.17 已把 collector 运行证据绑定到通用 lifecycle resolver。未出现过 collector run 的
provider/gateway/account scope 明确为 `not_configured`，继续允许 Stage 3.15 的显式离线导入；
一旦该 scope 采用 collector，当前 observation 必须能追溯到匹配的 recorded run，最新有效 run
也必须与 cursor state 一致。prepare 后待重启恢复、断连/部分批次等 blocked run、collector 历史
后的未绑定直导入以及 run/state 不一致都会重新阻断签名清算和下一单串行门禁；duplicate retry
不能遮蔽更晚的失败。该规则只从 SQLite 持久化事实派生，只能缩小执行资格，不联系 provider，
也不修改 OMS、fills、账本、风控、kill switch、资本授权或任何券商权限。

Stage 3.18 已把内部 session order-rate admission 与最新持久化 live-gate snapshot 精确绑定。
admission v2 固定 snapshot id、fingerprint、session fingerprint 和 observed time，并独立要求不
超过 30 秒；SQLite 写事务会在检查 replay/rate 前重新读取最新 snapshot。缺失、陈旧、未来、
blocked、身份漂移或被更晚事实取代的 snapshot 都会 fail closed，因此 preview 后出现的新 blocked
事实优先且不会写入 admission。生产只连接已认证 session 与只读 snapshot resolver，API 仍只有
status/history，没有公开 admit、策略直连、broker submit/cancel，也不修改 OMS、fills、账本、
资本授权或 kill switch。

Stage 2.1/3.1 已加入精确 prior-batch reconciliation evidence：唯一非 paper 终态 OMS
订单集合必须绑定指定 reconciliation run，且每笔订单只有一个 `no_action` item、OMS 状态
未漂移；filled 订单还需真实成交数量与 provider、broker order、Account Truth import、同一
run 链接。订单/transition/fill/item/run 任一变化都会使历史指纹失效。per-order 与 session
请求还必须与资本评估引用同一条 clear batch 记录；该记录不授权下一批执行。

Stage 2.2/3.2 已加入签名操作员审批证据：信任配置只接受 Ed25519 公钥，不接受私钥或
secret 字段；短时 challenge 绑定 nonce、operator/key、动作、工件类型、精确指纹与过期
时间。签名 verification 形成追加式 approval，per-order/session 记录必须引用匹配 approval
id；过期、密钥停用/轮换、签名错误和跨工件复用都会 fail closed。该能力只验证“谁确认了
哪份证据”，不签发资本或 runtime authority，也不增加券商写能力。

Stage 4 的证据化扩缩容评审基础也已加入：版本化 current/proposed tier 会绑定运行日数、
订单/成交/拒单、对账延迟/缺口、滑点、成本后结果、回撤、容量/流动性、paper-shadow
divergence、断连、违规和事故证据。至少 20 个复核交易日、50 笔订单及全部质量/来源门禁
通过后，只能形成 `request_new_authorization_for_scale_up`；严重事故/违规/未清对账或回撤
耗尽优先建议 disable，质量恶化建议 scale-down，证据不足则 hold。人工可以选择更保守
结果，但不能越过证据建议扩容；任何决定都不签发授权、不改 runtime limit、不恢复执行、
不接触券商，也不自动扩容。

Stage 4.1 已加入 fail-closed 持久化来源解析：`broker_soak`、
`execution_reconciliation`、`paper_shadow` 和 `risk` 引用会按 typed identifier 查回现有
存储，校验评审窗口和 clear 状态，并把脱敏 source fingerprint 绑定进独立 evaluation
fingerprint。源事实缺失、越窗或不清晰时，数学上可扩容的结果会转为 hold。Account Truth、
成本后、事故窗口和容量/流动性现在必须引用一条计算后持久化的 evidence window；调用方声明
的聚合指标本身不能支持扩容。

Stage 4.2 已加入 computed evidence window：Account Truth 点时快照必须在 broker import 后
15 分钟内记录 pass/fresh/zero-unresolved 脱敏摘要，评审窗口两端需要不同的 clear 快照；
成本后收益按组合总权益和外部现金流计算 Modified Dietz，事故指标来自 critical alerts、被拒
实盘写尝试和 connector 断连，容量/流动性/滑点只使用带 broker、Account Truth、对账、容量
模型和市场数据链接的非模拟成交。接口不接受调用方聚合指标；事实缺失只生成 blocked evidence。
resolver 会复核窗口、fact fingerprint、metric equality 和 fill coverage；即使全部 clear，也
只允许记录“另行申请新授权”，不授予权限、不改 OMS/runtime/账本、不接触券商。

Stage 4.3 已加入 computed operating sample：从健康只读 connector soak 记录计算复核
交易日，从非 paper OMS/transition/真实成交计算 filled、rejected、partial、cancelled、
expired 和 nonterminal 样本；最新对账必须覆盖每笔样本订单，并从最后一条订单/成交/状态
事实到首个 `no_action` 对账项计算 p95 延迟。paper/shadow divergence 取自同窗持久化订单，
最大回撤使用外部现金流单位化后的组合权益。`operating_sample:<window_id>` 是必需 clear
来源，九项调用方指标必须与事实一致；缺失链接、非终态、覆盖不足或 5,000 行扫描截断都会
fail closed。

Stage 4.4 已把 exact execution scope 变成必需证据：v2 evidence window 从同一 computed
operating sample 取得订单集合，每笔订单必须绑定一条持久化 controlled-session admission，
或一条仍然 current/clear 且完整落在评审样本内的 exact batch reconciliation。session 身份、
admission payload、生效/过期窗口、batch 的 OMS/fill/reconciliation 指纹都会重新校验；缺失、
重复歧义、跨窗、孤儿 admission、来源漂移或扫描截断一律阻断。v1 window 只保留追加式历史
审计，不能满足当前扩容评审；迁移入口是从持久化事实重新记录 v2 window，不会重写旧证据。
该事实仍不签发、续期、恢复或扩大授权，也不修改 OMS/账本/风控/kill switch 或联系券商。

执行要求：

* 账户、策略、连接器和执行模式都必须显式开启。
* 授权必须限定账户、策略、标的、模式、生效时间、过期时间和策略版本；默认仍是每单
  人工确认，session 不能自行开启、续期、恢复或扩大权限。
* 每日、每 session、每策略、每标的、每订单都有授权资本、仓位、换手、亏损、回撤和
  订单速率上限。
* 数据过期、账户事实降级、paper/shadow 偏差、券商连接异常、订单拒绝异常、
  对账缺口或 kill switch 开启时自动暂停。
* 下一批受控订单前，上一批执行对账必须 clear 或被人工接受。
* UI 必须展示已授权额度、实际有效风险敞口、剩余额度、授权过期时间、最近订单、
  最近对账结果、当前阻断原因和暂停/恢复原因。
* 扩大额度必须由新的人工决定绑定已复核证据；系统只允许自动暂停或缩容，不允许
  自动扩容。

## 延后能力

以下能力保持延后：

* 默认真实资金自动交易。
* 无人值守或永久授权的全账户自动下单。
* 券商密码存储。
* 黑盒 AI 策略自动买卖。
* 社区策略市场。
* 高频交易。
* 机构级多账户 OMS。
* 保证收益或投资建议式表达。

## 文档整理建议

当前 `docs/` 下的文档仍有明确用途，暂不建议删除：

* `KARKINOS_GOAL.md`：战略目标和产品边界。
* `ARCHITECTURE.md`：分层架构、权限边界、自动化成熟度。
* `ROADMAP.md`：完整英文路线图和历史验收标准。
* `ROADMAP.zh.md`：中文路线图摘要。
* `IMPLEMENTATION_LOG.md`：历史实现记录，可后续归档拆分，但不应直接删除。
* `BENCHMARKS.md`：外部项目参考边界，明确参考不构成依赖、默认路线或支持声明。
* `README.zh.md` / `README.en.md`：用户和开发者使用文档。
* `account-truth-import.zh.md`、`config-reference.zh.md`、
  `return-accounting.zh.md`：专题规范文档，避免 README 继续膨胀。
* `strategy/README.zh.md` / `strategy/README.en.md`：策略说明和安全边界。
