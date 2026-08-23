# Karkinos 中文文档

Karkinos 是面向中国市场的个人量化投研与交易平台。本页是中文文档入口，不重复维护完整的产品说明、API 清单或实现日志。

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

Decision 与 Daily Trading Plan 汇总组合、行情、策略、信号、风险、Account Truth 和 paper/shadow 证据，输出 buy、sell、hold、rebalance、no-action 或 review-required。晋级后先生成 `paper_shadow_required` 计划意图；只有同日持久化 run 精确绑定 action、输入 fingerprint、模拟订单且无偏差才进入人工确认。出票写边重查 Account Truth、行情、风控、Kill Switch、晋级、费用及 shadow；任一异常均 no-action。

生产每日候选运行不接受调用方提供的账户或交易事实：它按“当前 Decision/计划 → 批量风控 → 精确 paper/shadow → 当前计划重放”只输出 `manual_order_ticket_candidate` 或 `no_action`。v3 记录绑定估值快照、ledger cutoff、同市场日 Account Truth 晋级源、同日可信报价、账户专属费用、风险决策、策略晋级、模拟身份和前序真实执行闭环，并生成带指纹的只读人工票据候选。Owner 启用的后台运行只在已复核上交所交易日的上海时间 09:35–09:45 窗口内触发，并在读取计划前原子认领当日唯一 fail-closed 尝试；计划陈旧、失败、中断或重启都不会打开自动重试。Automation Cockpit v4 除了准确展示 owner 配置和后台 task 存活状态，还提供 `karkinos.daily_candidate_financial_preflight.v1`：它以只读、零写入、不联系 provider 的方式汇总当前 Decision/计划、同日 Account Truth 与持久化行情、冻结策略重放、有效费用复核、安全自动化策略及前序执行闭环。预检通过也只允许进入 canonical 风控与 paper/shadow 尝试，绝不创建人工票据、提交订单、修改 OMS/账本、扩大资本授权或证明盈利；最终票据仍只能由模拟后的生产门禁判定。前瞻试运行读取完整持久化历史，只累计最新一轮冻结策略与费用周期中已复核交易日历、单一输入 fingerprint 且模拟无偏差的日期；旧周期保留为已归档证据，绝不并入后来周期。达到 20 个合格交易日和 50 笔模拟订单后，也只允许人工记录 GO/继续/NO-GO，不会创建订单、授予权限、扩大资本或证明未来盈利。详见[每日候选交易生产运行手册](DAILY_CANDIDATE_PRODUCTION_RUNBOOK.zh.md)。最终 Decision 与计划生成时间也必须处于该窗口，每个汇总及逐意图行情在决策时不得超过 300 秒；页面会在窗口外禁用人工运行，直接调用也只能形成不计入前瞻样本的可审计 `no_action`。系统还会逐意图重验最终 Decision 的 canonical 订单生成门禁，并让 snapshot 与带指纹票据共享同一组策略晋级、已复核费用、比较、人工批准、冻结基准/候选数据集和 persisted-only 重放身份；只要最新一次运行被排除，即使旧计数达到门槛也不能开放 GO 复核。

Account Truth 绑定额外只保存导入事件、人工复核、不可变估值和 cutoff 内历史账本的脱敏内容 fingerprint；trial 按原 cutoff 重算，允许之后追加账本行，但任一历史来源、复核、估值或账本漂移都会排除该日。

账户策略贡献现在只投影持久化事实：成交必须已写入生产账本，并绑定同一精确估值快照与 ledger cutoff 后才可展示收益。证据缺失或漂移会给出明确人工复核步骤；策略尚无成交时不会制造虚假阻断。该投影不能联系 provider、写账本或授予执行与资本权限。

在 Strategy Lab 中，人工可把精确 strategy id 与 canonical contribution report 冻结进 AI 上下文；策略或 valuation/ledger identity 漂移会被拒绝，不完整证据保持 blocked，捕获不重算收益也不调用模型。

Owner 授权的收盘后 shadow 研究每个持久化市场日期只运行一次：本地刷新基线并绑定完整账户证据，数据集 identity 哈希实际送入引擎的有序 timestamp/OHLCV，原子 claim 最多 10 次 DeepSeek 调用、记录 Token 用量但 Karkinos 不设每日累计 Token 上限，外发保存回测和严格 allowlist 风险/配置投影（删除绝对金额、持仓数量/成本及 valuation/ledger 标识），在本地校验 Formula DSL、运行 canonical 成本后 rolling OOS，再发送规范化结果做 critique。每次启用的站立运行必须执行完整 5 轮严格串行修订：每轮只生成 1 个版本，完成本地权威回测、确定性晋级门与 critique 后，把上一轮公式、指标、阻断项和 critique 的脱敏指纹包绑定进下一轮；因此 5 轮需要 10 次模型调用。若原始调用和已授权完整重试各有 1 次真实调用因 citation contract 失败，只有在“上限恰好 +1 后仍正好剩余 10 次”时，owner 才能追加一条绑定该零候选失败的不可变授权；它只能消费一次，不能成为通用提额，也不增加策略、订单、券商或资本权限。若随后第三次真实调用因 DeepSeek 思考内容耗尽输出预算而得到 `provider_output_truncated`，策略研究会改为显式关闭思考、把 12,288 token 全部保留给最终 JSON；只有在既有 citation extension 已消费、调用数恰好为 3、上限恰好从 12 增至 13 后仍正好剩余 10 次时，owner 才能追加另一条一次性不可变授权。若同一 run 已完整持久化前四轮、仅第 5 轮 hypothesis 因 `provider_timeout` 失败，则 owner 还能追加一条只把 ceiling 从 13 提到 14 的一次性断点续跑授权；系统会重验并绑定四轮 session、draft、回测、critique、candidate、父链和 8 次成功调用，只从第 5 轮继续，绝不重跑前四轮。旧超时记录保持不可变，任何证据或输入漂移都会 fail-closed。已有未用 slot 与新增 1 个 slot 只够第 5 轮 hypothesis 和 critique 两次调用；DeepSeek 策略研究单次超时为 600 秒，其他 provider 超时不变。每次 hypothesis 仍先校验完整路径目录，但只向模型暴露稳定的 `cite_01` 至 `cite_05` 必需证据锚点；每个草稿必须按原顺序返回完整短 ID 列表，少报、多报、改写、直接返回路径或未知 ID 都会在本地 fail-closed。单次请求输出和上下文窗口仍受 provider 技术限制，但不是 Karkinos 的每日 Token 预算。旧的有界 Token 或较小启用策略仅保留供审计，在 owner 明确保存完整策略之前，会在准备证据或调用模型前以 `blocked_by_policy` 阻断。轮次、父 candidate、父 draft 或公式指纹任一缺失/错配都会 fail-closed，不能产生新优胜者。DeepSeek 不负责选优。只有完整通过确定性晋级门的候选才进入预声明字典序排序，依次比较税费后超额、OOS 平均/最差超额、回撤、换手和稳定 candidate identity；候选集合不完整、任一评估未完成或无人通过时只表示没有新候选胜出、不会发生新晋级，当前已人工批准策略保持不变，并不直接推出当天 `NO-ACTION`。当天是否产生票据候选，仍由独立 Decision 链以当前 Account Truth、行情、费用、策略、风险、paper/shadow 与对账证据确定。完成的每日候选集合会生成只含可复现 Formula DSL 与串行 lineage 的脱敏、内容寻址备份及不可变数据库回执；备份缺失或指纹漂移会阻断公开 paper/shadow 批准。晋级 readiness 只持久化 run/date/winner 与 selection/backup 指纹，不保存私有路径；之后每次 paper/shadow、Decision 和出票门禁都会只读重开并重哈希该备份，旧晋级记录缺少绑定、文件删除或批准后漂移都立即阻断。确定性晋级门还要求有界参数扰动、冻结行情状态、回撤、换手、容量、已与券商账单对账的账户专属税费证据，以及“研究本金不超过同一估值/账本身份下当前已对账账户权益”的脱敏指纹证据；未绑定或超额选择会在模型外发前阻断。内置费率只是估算，当前明确不能满足晋级。`ai_formula_shadow:*` 票据会重新解析候选、基准/候选回测、critique、人工批准和 paper 状态，下一批还必须绑定指纹有效的 plan/paper/actual 对比。任一事实缺失、过期、冲突、漂移或不可复现均 `research_blocked`/no-action；这些记录不能替换生产策略、创建/提交订单或扩大资本权限。账户专属模型只能由可撤销、绑定 fingerprint 的 Account Truth 费用复核生成；持久化的安全费用条款会真正进入基准与候选计算。来源漂移、撤销或回测/票据日期超出有效区间时，会在不联系 provider/券商的前提下立即阻断。下一批对账还必须把前序订单全部解析为当前同一策略；策略 lineage 缺失、混合或无关均 no-action。

Decision 的信号审计日志现在支持显式“决策后复盘”。系统先只读预览持久化的 signal/action/risk/order/fill 链和同一 canonical contribution report，再把人工结论绑定到该精确
fingerprint。只有具备成交、估值快照与 ledger cutoff 的完整绑定证据，已执行信号才能记录
“证据支持/不支持”；未执行或被风控阻断的信号使用独立非财务结果。复盘主记录与 append-only
事件链都必须通过审计重放。Strategy Lab 只把每个信号最新、仍与当前 canonical target 精确绑定
的人工复盘转成确定性安全下一步；篡改或漂移会阻断学习，“证据不支持”也只生成供另行人工启动
研究任务复制的问题。该 GET 不调用 AI、不创建记忆、不联系 provider、不改策略/财务事实，也不授予交易或资本权限。

Decision 还提供证据绑定的北极星“决策质量分数”。当前投影固定检查数据与 Account Truth 完整、
确定性风控、基准对照、日志和后续复盘身份；操作员可以针对精确每日 fingerprint 显式固化为
append-only、可重放的捕获。纵向覆盖只统计已显式捕获日期；该分数衡量过程证据，不衡量收益，
也不构成建议或权限。

Overview 的行情/净值复核只消费绑定 valuation snapshot、quote-set fingerprint、ledger cutoff/fingerprint 的 canonical 当前非零持仓投影；观察列表、大盘指数和已清仓事实不能抬高数量。
Market 会列出精确标的、原因和安全人工下一步；GET 不联系 provider、不写库。基金确认净值使用独立、请求幂等的 confirmation-only 可审计 ingestion；同一请求只重放持久化批次且不再次联系 provider，估值和前一日净值不能清除复核。只有更新且已确认的持久化证据生成新快照后才能清除复核项。

### Paper/Shadow 与 Operations

Operations 展示数据、计划、paper/shadow、OMS、对账、告警和恢复任务。Paper/shadow 可以模拟订单、成交、费用和偏差，但不会提交真实券商订单或修改生产账本。`/operations` 只读证据中心直接展示 canonical persisted-facts payload、子系统健康度、来源证据与安全下钻；它不联系 provider、不写库且无执行权限。每个非正常子系统还会展示确定性 attention fingerprint、安全下一步和精确证据解除条件；仅查看不能改变状态。
旧 Trading daily-shadow 端点只委托该 canonical 服务，并拒绝调用方传入账户权益。

受控订单会把按时间排列的审计历史与操作员优先级分开。系统检查有界范围内全部持久化 journey；
较早的 unknown、prepared 或 open-order 结果不会被较新的低风险或已闭环旅程遮蔽。紧凑关注队列
为每一项显示唯一安全下一步，但它仍是只读投影，不能联系 provider，也不能修改交易、账本、风控、
kill switch 或任何权限。

### Account Truth 与对账

券商导入默认先 preview，再记录为独立 broker evidence。证据不完整的中信历史成交还可经
二次人工确认记录为隐私最小化的待补证来源或明确拒绝；显式配置的私有目录可按需扫描且不返回路径或文件名，但它不会保存成交事件，也不属于 Account Truth。对账比较现金、持仓、订单、成交、费用、税和成本基础；券商事实不能静默改写
账本。每份待补证来源还可追加一份可撤销、绑定精确 fingerprint 的券商查询日期复核；日期不能根据观察到的事件反推。目录扫描会只读检查当前声明日期是否连续或重叠，但即使全部连续也只清除来源级待办，不会提升为 Account Truth。来源待处理、扫描截断、读取失败、日期缺口或重叠还会阻断受控执行消费的 Account Truth promotion evidence，但不能生成 canonical 账户事实或独立开放执行。
请只使用本地真实文件，不要把账号或导出提交到仓库。账户事实页面还会把持久化 score、待补证复核与账户/日期/资产范围投影为 canonical 证据就绪清单；观察到的首末记录不等于完整覆盖，只有显式 owner 复核才能把精确导入绑定到浏览器本地哈希的账户引用与声明时段，而且该复核可撤销。任何缺失、漂移或不可读证据都会保持阻断；查看清单不会写库、联系券商、执行对账或授予执行/资本权限。

### 受控执行

真实资金能力默认关闭。当前目标是一个 provider、逐单人工确认、明确资金边界、完整生命周期、
执行对账和显式入账。当前已能基于持久证据对完整成交、零成交撤单和部分成交后撤单执行单独签名
的精确终态 clearance；随后还需要另一份最终操作员签名，才可在单一事务内 exactly once 地把
实际 fills 写入生产账本。零成交撤单只记录 no-op posting。入账边界会重新核验 OMS、lifecycle、
券商证据、Account Truth 与 ledger identity，不能提交或撤销券商订单、联系 provider 或改变资本
权限。单独签名的 append-only correction 现在可仅根据 canonical replay 反向纠正一个 posting，
保留原交易与费用，并在完成后要求更新的 Account Truth import。该可选纠正现在可以从既有 order
journey 显式打开：选择 allowlisted 原因、复核确定性 delta、验证离线签名，再 exactly once 地追加
补偿事件；UI 不能输入现金、数量或价格。Decision 也提供精确 preview、离线签名的单向 session 撤销：只关闭未来准入，不能 submit/cancel，未结订单仍需 lifecycle 与对账。详细门禁见[路线图](ROADMAP.zh.md)。

Trading 还会只读展示精确 connector 的 20 日 soak、三阶段、恢复演练、Account Truth 和签名 owner acceptance 门禁；默认折叠的 adapter release 复核可在不改数据库的前提下签名接受/拒绝/撤销，并把精确 manifest、最新 conformance、当前 review 与 operator approval 绑定；独立 write-edge 复核则完成最长 12 小时的签名放行与单向撤销。两者都在本地拦截凭据键，不提供 submit/cancel、adapter 注册、provider 连接或资本授权；未配置时保持中性且不执行 promotion。
默认折叠、非提交的逐单证据复核只列出 canonical `manually_confirmed` OMS 候选，并从持久化事实解析最新精确资本评估、前序批次对账与网关验证，避免人工抄写三组 fingerprint；随后还会绑定与 connector/gateway/account 精确匹配、仍为 accepted、conformance clear 且处于只读观测的最新 adapter release。
v5 dossier 还会把 Account Truth、Decision action、risk decision 与 paper/shadow 引用解析到匹配的持久化来源，要求同一 capital evaluation 精确包含这些引用，并阻断订单、标的、策略或数量漂移。
三分钟离线签名只能追加精确复核事实；旧人工工单与人工成交操作必须取得最新已签名逐单 confirmation，再重新解析当前资本、四类来源、adapter/soak、gateway 与前序批次对账，并绑定 confirmation、dossier 及四个来源 fingerprint；缺失、阻断、漂移或有界扫描不完整时
继续 blocked。两者都不能 submit/cancel、联系 provider 或修改 OMS、ledger、risk、kill switch、capital authority；release 撤销或 scope drift 也会使旧签名失效。
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
