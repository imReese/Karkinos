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
| v1.6 | 进行中 | Operations Center & Paper/Shadow Runbook |
| v1.7 | 进行中 | Controlled Broker Execution Bridge |
| v1.8 | 计划中 | Small-Capital Controlled Auto Pilot |

## 自动化成熟度

自动化按成熟度逐层推进。越靠后的层级，越接近真实资金执行，也越需要更严格的
证据和暂停机制。

| 层级 | 名称 | 含义 |
| --- | --- | --- |
| L0 | 研究证据 | 注册策略、可复现回测、扣费后/OOS 证据、限制说明 |
| L1 | 每日交易计划 | 候选池、阻断原因、费用、风险和人工确认下一步 |
| L2 | Paper/shadow 运行闭环 | 定时模拟执行、偏差复核和运行摘要 |
| L3 | 人工执行辅助 | OMS、手工票据、券商证据导入、执行对账已进入可用路径 |
| L4 | 受控券商桥接 | 每笔订单经过账户事实、风控、paper/shadow 和人工确认门禁 |
| L5 | 小资金自动试点 | 显式开启、强额度上限、可暂停、必须对账后才能继续 |
| L6 | 无人值守真实资金自动化 | 延后，直到上游能力成熟且风险被明确接受 |

## 当前主线：v1.6

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

## 下一阶段：v1.7

v1.7 是受控券商执行桥接，不是默认交易机器人。

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
  边界；策略晋级状态只说明生命周期和证据准备度，不会单独授权执行。
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

## 后续阶段：v1.8

v1.8 才考虑小资金自动试点。它不是全账户无人值守自动交易，而是验证自动化是否能在
严格额度、风险和对账限制下改善执行纪律。

试点要求：

* 账户、策略、连接器和执行模式都必须显式开启。
* 每日、每策略、每标的、每订单都有金额、仓位、换手、亏损和回撤上限。
* 数据过期、账户事实降级、paper/shadow 偏差、券商连接异常、订单拒绝异常、
  对账缺口或 kill switch 开启时自动暂停。
* 下一次自动试点运行前，上一轮执行对账必须 clear 或被人工接受。
* UI 必须展示试点资金风险、剩余额度、最近订单、最近对账结果、当前阻断原因和
  暂停/恢复原因。

## 延后能力

以下能力保持延后：

* 默认真实资金自动交易。
* 全账户无人值守自动下单。
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
* `BENCHMARKS.md`：外部项目参考边界，保留用于解释 PTrade/QMT 等借鉴点。
* `README.zh.md` / `README.en.md`：用户和开发者使用文档。
* `account-truth-import.zh.md`、`config-reference.zh.md`、
  `return-accounting.zh.md`：专题规范文档，避免 README 继续膨胀。
* `strategy/README.zh.md` / `strategy/README.en.md`：策略说明和安全边界。
