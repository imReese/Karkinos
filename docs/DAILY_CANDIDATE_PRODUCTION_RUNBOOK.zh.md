# 每日候选交易生产运行手册

[English](DAILY_CANDIDATE_PRODUCTION_RUNBOOK.md) | [产品目标](KARKINOS_GOAL.zh.md) | [架构](ARCHITECTURE.md) | [受控执行](CONTROLLED_EXECUTION_PLAN.zh.md)

## 生产边界

本手册将 Karkinos 作为人工监督的每日决策系统运行。每次运行只能产生：

- `manual_order_ticket_candidate`：当前持久化证据允许人工继续进入独立的逐单票据流程；
- `no_action`：仍有明确阻断项，或策略当天没有可执行动作。

两种结果都不会创建或提交券商订单，不修改生产账本，不授予执行权限，不变更策略分配，也不扩大资金额度。候选订单不代表盈利承诺。

## 合格运行的前置证据

1. 策略已有人工复核的 `paper_shadow` 晋级，并绑定完整的 `karkinos.strategy_advancement_gate.v2`。当前订单生成门禁还必须重放持久化冻结数据集，确认基准与候选 manifest 一致，保留已复核比较与人工批准 fingerprint，并继续关闭 provider 联系和 live-like 权限。
2. 脱敏 Account Truth 晋级证据为 `clear`、`pass`、新鲜且账本覆盖为 `covered`，未解决不一致为零，并绑定计划所属上海市场日期内、且不晚于最终 Decision 的当前现金与持仓快照。采集时间取两类最新快照时间中更早者；更晚的本地文件导入时间只记录为 `imported_at`，不能把旧账单刷新成新证据。系统从快照采集时间和 Decision 时间重算年龄，必须处于已复核上限内，同时绑定源 fingerprint、估值快照和正数 ledger cutoff。
3. 最终 Decision 与计划只能在上海时间 09:35 至 09:44 生成。每个订单意图使用当前持久化行情而不是历史信号价格，并绑定正数价格、来源、带时区时间和决策时行情年龄；该时间与 Decision、交易计划属于同一市场日期，且行情年龄不得超过 300 秒。
4. 账户专属费用复核覆盖操作日期，每个意图都由该版本费用规则计算出非负费用。
5. 每个意图都通过并绑定唯一的盘前风控决策。
6. Kill Switch 和自动化策略只允许 paper/shadow；券商提交继续关闭。

证据缺失、过期、冲突、估算、部分完成、未来时间或不可复现时，一律 `no_action`。

## 每日操作顺序

1. 在每日决策截止前显式导入或复核当前行情与 Account Truth。任何 GET 页面都不会隐式刷新 provider。
2. 若存在前序非模拟 OMS 订单，先运行执行对账并完成当前 `plan → paper → actual` 或零成交终态闭环；再打开“决策 → 自动化”，检查账户、执行闭环、行情、策略、风控和费用阻断项。
3. 在页面显示的 09:35–09:45 决策窗口内，从应用启动 canonical 运行，或调用 `POST /api/automation/run/daily-candidate`。该接口不接受调用方传入的计划、价格、数量、账户余额或策略 fingerprint。窗口外页面会禁用人工运行按钮；直接调用 API 也只能持久化带明确原因的 `no_action`，不能计入样本。
4. Karkinos 重建当前 Decision 与计划，运行 canonical 批量风控，持久化一次确定性 paper/shadow，再次重建计划后才给出生产结论。
5. 若结果为 `no_action`，只修复返回的具体证据源，为下一个干净市场日做准备。同日人工重跑仍会保留审计；若 input fingerprint 改变，当日不会计入试运行。不得编辑运行记录或手工绕过门禁。
6. 若结果为 `manual_order_ticket_candidate`，人工检查模拟订单、当前报价、费用、风控/约束、证据指纹、偏差、失效条件和当前 Kill Switch。返回产物只读且不会创建 OMS 订单；之后也只能进入现有逐单人工确认流程。
7. 若人工在券商端执行，必须导入精确成交并完成 plan → paper → actual 对账，才能进入下一批。

Owner 启用实时监控后，后台循环先读取持久化且已官方复核的上交所日历，只能在上海时间 09:35 至 09:44 调用同一服务。调用前会原子认领当日唯一后台尝试；即使当前计划日期陈旧、运行失败、任务中断或应用重启，该认领也保持 fail-closed，不会用更晚信息自动重试。休市或日历未复核时不会写入；09:45 后没有认领则报告错过窗口，不使用更晚信息回填。完全相同的人工输入仍幂等复用；`karkinos.daily_candidate_input_identity.v2` 只忽略底层事实和门禁结论未变时自然增长的当前年龄计数，同时绑定生产阻断、脱敏风控错误指纹、冻结策略重放、准确 paper/shadow 结果和前序执行闭环。同一市场日任何来源或结果发生变化都会保留为不同 input fingerprint，该日期不计入试运行，而不是覆盖早先记录。

每个已原子认领的后台尝试都会为 `no_action`、只读票据待复核、中断或 fail-closed 失败持久化一条隐私最小化 Operations 告警。若配置了通知，`no_action` 消息只包含市场日期和最多八个具名阻断项，发送最长等待十秒。attempt 会记录告警/通知状态；告警存储、超时或发送失败不能触发重试、创建 OMS 订单、联系券商、修改账本或改变资金额度。

“决策 → 自动化”还会展示 `karkinos.daily_candidate_runtime_status.v1`，分别证明 owner 配置是否启用了后台监控，以及当前进程内的准确监控 task 是否仍在运行。即使决策窗口已打开，task 被禁用、缺失、已结束、被取消或失败时，自动尝试也必须按运营阻断处理；人工运行窗口是另一项独立事实。task 存活绝不代表 Account Truth、行情、策略、费用、风控或对账已达到财务就绪，读取该状态也不联系 provider、不写数据库、不执行券商动作或改变权限。

Automation Cockpit v4 还会展示 `karkinos.daily_candidate_financial_preflight.v1`。该只读投影从持久化事实重建当前 Decision 与计划，并逐项检查同日 Account Truth 采集时间、可信持久化行情、精确晋级策略与冻结数据集重放、当前费用复核及日期覆盖、安全自动化策略和前序执行闭环。绿色预检只表示可以在已复核窗口内启动一次 canonical 风控加 paper/shadow 尝试；它不会执行风控、模拟订单、创建票据、修改 OMS 或生产账本、联系 provider/券商、扩大资本或证明盈利。模拟后的生产门禁仍是只读人工票据候选的唯一判定者；任何来源缺失或漂移都会显示为具名 `NO-ACTION` 原因。

预检同时按依赖顺序返回只读 `operator_checklist`：先处理 Account Truth、账户费用和策略人工复核，再处理前序执行闭环、当前行情、Decision/计划及运行窗口。每一步都携带准确阻断项和完成模式，但不会自动执行修复、写入证据、批准策略、创建票据或改变执行/资本权限；全部门禁已通过时，清单也只指向一次 canonical paper/shadow 尝试。

在 owner 自行运行的 Mac 上，终端后台子进程不构成持久服务证据。准备下一个决策窗口前，先运行 `./scripts/manage_launch_agent.sh print-plist` 检查本地用户级定义，再显式执行 `./scripts/manage_launch_agent.sh install`；随后必须由 `./scripts/manage_launch_agent.sh status` 同时确认 LaunchAgent 已加载且进程存活。该服务只监听 `127.0.0.1`，意外退出后会重启，并可通过 `uninstall` 完整撤销。安装不会修改 `config.json` 或 `.env`，不会自行开启 `live_auto_start`，不会联系 provider，也不证明财务就绪。若后端端口已有 listener，安装会保持原进程不动并失败；operator 必须明确处理该准确进程，禁止两个每日候选服务共用一个本地运行数据库。

## 前瞻运营试运行

只有同时满足以下条件，日期才计入样本：

- 已复核的上交所日历将其标为交易日；
- 当天只有一个 daily-candidate input fingerprint；
- 该 input fingerprint 可从持久化 Decision/计划身份、生产阻断、脱敏风控失败、冻结策略绑定、paper/shadow 结果和前序执行闭环重新计算；
- 生产门禁通过并产生人工票据候选；
- 每份只读票据的指纹可重放，日期、处于复核窗口内的最终 Decision/计划时间、年龄不超过 300 秒的当前报价、paper/shadow 身份和前序执行闭环精确一致，并明确保持“不创建 OMS、不提交券商、不改变资金权限”；
- 每份票据与 daily snapshot 必须携带完全相同的策略门禁绑定：策略晋级、已复核费用、比较、人工批准、冻结基准/候选数据集身份以及数据集重放 fingerprint；
- 每份票据与 daily snapshot 必须携带完全相同的隐私最小化 Account Truth 绑定：源 fingerprint、采集/决策时年龄、已复核年龄上限、估值快照、ledger cutoff、对账和覆盖状态；其中不含账户标识或余额；
- 同日 Account Truth 来源、采集时间不晚于 Decision、决策时年龄处于已复核上限内且完整账本覆盖仍然有效，全部前序非模拟订单都已完成当前对账；
- paper/shadow 日期、fingerprint、候选/订单数量完全一致，状态与偏差均为 `within_expectations`；
- 当前试运行周期绑定同一组非空策略晋级和已复核费用 fingerprint。

策略晋级或费用复核绑定变化时，系统从首次观察到新绑定的 daily record 自动建立新试运行周期。旧周期的合格日期保留为已归档证据，但绝不会并入新周期的 20 日 / 50 单计数；即使后来重新使用旧绑定，也会再次开启新周期。

最低阈值为 20 个合格交易日和 50 笔模拟订单。达到阈值后只开放绑定当前 trial fingerprint 的人工结论：

- `continue_paper_shadow`：继续积累证据；
- `no_go`：记录不应晋级；
- `go_to_bounded_manual_trial`：仅记录可进入另行授权、小额、可撤销人工试单的研究结论。

人工结论必须包含复核人、说明和完整确认短语。它不会签发订单、执行授权或资金额度；后续证据漂移会形成新 fingerprint，必须重新复核。

## 失败与恢复

| 证据状态 | 必须结果 | 安全恢复 |
| --- | --- | --- |
| Account Truth 缺失、过期或不一致 | `no_action` | 显式导入并对账更新证据 |
| Account Truth 非计划所属上海日期采集，或账本覆盖不是 `covered` | `no_action` | 导入并复核当日账户快照 |
| Account Truth 晚于 Decision 才采集，或决策时年龄超过已复核上限 | `no_action`，日期不计入 | 等待新的已复核快照和下一个干净决策窗口 |
| 前序非模拟订单缺少当前对账，或 plan/paper/actual 源发生变化 | `no_action` | 完成精确执行对账，不得绕过或手改证据 |
| 报价时间缺失或不属于计划日期 | `no_action` | 持久化当前日期可信行情 |
| Decision/计划生成时间不在 09:35–09:45，或行情年龄超过 300 秒 | `no_action`，日期不计入 | 等待下一个已验证窗口，并在运行前刷新持久化行情 |
| 意图价格与其绑定的当前报价不同，或报价来源缺失 | `no_action` | 从当前持久化行情重建 Decision 与计划 |
| 策略晋级或费用绑定缺失 | `no_action` | 回到 Strategy Lab 或费用复核 |
| 冻结数据集重放、比较、人工批准或票据/snapshot 策略绑定漂移 | `no_action`，最新日期阻断 GO 复核 | 重建并人工复核 canonical 策略晋级证据，不得修改 daily record |
| 风控未完成或阻断 | `no_action` | 处理返回的风控/数据质量原因 |
| paper/shadow 失败、偏差、缺失或数量不符 | `no_action` | 检查持久化模拟，不得手改 |
| 同日出现两个输入 fingerprint | 日期不计入 | 复核漂移，等待后续干净交易日 |
| 持久化 daily input identity 无法重放 | 日期不计入 | 保留原记录，调查来源漂移或篡改，等待后续干净交易日 |
| 后台告警或通知失败 | 候选结论保持不变且不得重试 | 在下个窗口前检查 attempt 中脱敏的 `operator_alert` / `notification` 状态 |
| 后台监控被禁用、缺失、已结束、被取消或失败 | 不执行自动尝试，runtime 状态 fail closed | 保持停止，或仅在 owner 明确启用后重启，并在下个窗口前确认 `background_monitor_running=true` |
| macOS LaunchAgent 未加载或进程存活不可用 | 不形成持久自动 monitor 结论 | 显式检查或重装该准确用户级服务；不得从 launchd 状态推断财务就绪 |
| 后台窗口结束仍无当日记录 | `missed_decision_window`，不回填 | 在下一个已验证交易日窗口前准备好当前证据 |
| 策略或已复核费用 fingerprint 变化 | 开始新试运行周期 | 旧样本保留为已归档证据，不并入新周期 |
| Kill Switch 不可用或已开启 | `no_action` | 恢复并复核交易控制证据 |

## 不能由此证明的事项

20 日和 50 单只能检验可复现性、执行假设和运营纪律，不能证明未来收益为正。回测晋级、前瞻运营样本、小额人工真实结果、税费后收益、回撤以及 plan/paper/actual 偏差必须保持为不同证据层。任何资金额度变化仍需走现有资本复核，并由人工重新明确授权。
