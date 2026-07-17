# Karkinos 路线图

[English Roadmap](ROADMAP.md) | [战略目标](KARKINOS_GOAL.zh.md) | [架构](ARCHITECTURE.zh.md) | [实现记录](IMPLEMENTATION_LOG.zh.md)

## 文档职责

本文件只回答四个问题：

1. 哪些能力已经完成？
2. 当前版本目标是什么？
3. 应该按照什么顺序开发？
4. 满足哪些证据才能宣布完成？

详细实现历史、测试数量、逐 commit 进度和旧版本完整验收清单属于
`IMPLEMENTATION_LOG.md` 与 Git 历史；使用说明属于 README；战略边界属于
`KARKINOS_GOAL.md`。

## 产品方向

Karkinos 是面向中国市场的个人量化投研与交易平台，目标是形成由人监督、资本授权有界的
完整操作闭环：

```text
研究 → 回测 → 决策 → 风控 → paper/shadow
→ 受控执行 → 对账 → 复盘
```

券商执行只是一种受控能力，不是投资收益来源。策略代码和 AI 可以产出研究或计划，不能授予
权限、绕过风控或直接调用券商。

## 当前基线

| 主线 | 状态 | 已具备能力 |
| --- | --- | --- |
| v0.2-v0.5 | 已完成 | 研究闭环、Strategy Lab、可复现的扣费后/OOS 证据、数据质量门禁 |
| v0.6-v0.9 | 已完成 | Account Truth、复核工作流、策略归因、可靠行情数据平面 |
| v1.0-v1.3 | 已完成 | 策略 runtime、Paper Broker/OMS、券商证据、专业 Decision 工作流 |
| v1.4-v1.7 | 已完成 | 账本/快照绑定的贡献归因与费用精度、Daily Trading Plan、Operations runbook、非提交式受控桥接 |
| v1.8 控制面 | 基础已实现 | 签名限时授权、原子预算、session、实时门禁、暂停/replacement、单笔提交边界、互锁、broker-neutral 生命周期证据、完整成交/partial-cancel/零成交撤单精确终态 clearance、扩缩容评审 |
| v1.8 adapter acceptance | Provider-neutral 基础已实现 | 版本化 manifest、deterministic local conformance 证据、capability/boundary matrix、append-only accept/reject/revoke review、live collector 精确绑定与 persisted-only operator readiness 可见性；尚未选择或注册真实 provider |
| AI 原生 Phase 1-1.18 + 结果/复盘/质量桥接 | 已实现 | provider-neutral、证据绑定的研究、记忆、Formula DSL/回测/批判、人工显式选择的 canonical 策略贡献、signal→执行事实→人工决策后复盘，以及每日 Decision Quality Score 捕获；不具备交易权限 |

Account Truth 和对账继续作为强制安全门，但不再是下一阶段产品主线。Phase 1.18 已按一次明确
授权完成公式研究纵向闭环；v1.8 仍是当前产品目标。新增的只读结果捕获、人工复盘和决策质量
桥接不启动 Phase 1.19，也不会自动进入 AI prompt 或长期记忆。Decision Quality 是只覆盖显式
捕获日期的五维过程证据指标，不是收益指标或执行门禁。进一步 AI、语义记忆扩展和自动 prompt
注入继续延后，直到受控执行形成真实运营闭环。

## 当前目标：v1.8 — 真实券商受控试点

### 目标结果

只连接一个经过明确选择和审查的券商边缘，完成并证明以下闭环：

```text
真实只读券商事实
→ 逐单预检与人工确认
→ 单笔受控提交
→ 生命周期采集与异常恢复
→ 执行对账
→ 对账后显式入账
→ Account Truth 与运营复盘
```

默认模式保持 `manual_each_order`。`session_bounded` 必须由后续真实运营证据晋级，不能成为
绕过 v1.8 逐单验证的捷径。

### 功能优先级

| 优先级 | 能力 | 本阶段结论 |
| --- | --- | --- |
| P0 | 单券商适配器决策与隔离边界 | 最先完成 |
| P0 | 真实只读 adapter 与 20 个交易日 soak | 必须完成 |
| P0 | 部分成交、撤单、拒单、超时、断线和 unknown recovery | 必须完成 |
| P0 | 人工确认、exactly-once 的对账后入账 | 必须完成 |
| P0 | `manual_each_order` 端到端试点 | v1.8 发布门槛 |
| P1 | Operator UX、告警、adapter conformance、故障注入、部署和回滚 runbook | 发布门槛 |
| P2 | `session_bounded` 试点、第二券商适配器 | v1.8 之后评审 |
| P3 | AI Phase 1.19+、语义记忆、自动 prompt 注入 | 延后 |

## 里程碑

### M0 — Adapter ADR 与范围冻结

选择一个 provider 和连接模式，明确进程边界、capability、鉴权、数据所有权、callback/poll、
频率限制、失败语义、部署、回滚和隐私边界。生产环境默认仍不注册 write adapter 或 release
provider。

**退出门：** capability matrix 和威胁模型通过审查；strategy、risk、Decision 和 AI 模块不能
import provider SDK。

当前状态：provider-neutral release manifest、deterministic local conformance suite、append-only
report 与 review gate 已实现，包含 conformance-to-review 精确绑定以及 prepare/commit 时的 drift
与 revocation 复核。Operations 现在通过单一 persisted-only readiness view 投影 release、conformance
和 collector 证据：未配置 provider 是中性状态，证据漂移或 active collector 失败则显式提示；该
页面不提供注册或 review mutation 控件。该 suite 验证 Karkinos 契约，不验证真实 adapter。真实 provider 选择、实际
ADR/威胁模型接受和 deployment 授权仍未完成，必须由项目所有者显式确认。

### M1 — 只读 Adapter 与 Soak

通过现有 broker-neutral collector 契约采集现金、持仓、订单、成交、交易时段、心跳、源时间、
schema version、cursor、batch 和 deployment identity。GET 和告警路径不得隐式轮询券商。

**退出门：** 连续 20 个已复核交易日具备完整 startup/intraday/EOD 证据，没有未解决的 critical
现金、持仓、订单或成交差异；断线、重复、乱序、cursor gap、schema drift、partial batch、
adapter restart 和 Karkinos restart 演练均确定性降级并安全阻断。
每个 drill 与 conformance result 必须绑定精确 connector/release scope；无关证据不能满足门禁，
同 scope 的较新失败会使旧 pass 失效。

### M2 — 完整订单生命周期与恢复

补齐 dry-run、submit、query、callback/poll、cancel 和幂等 client order identity 的 adapter
conformance。明确 accepted、rejected、partial、partial-cancelled、filled、cancelled、unknown
和 recovery-required。Unknown 只允许查询，绝不自动重提；cancel 是独立的人审命令。

**退出门：** 并发、超时、重启、重复/乱序回调、部分成交、撤单竞态、断线、拒单和 broker
not-found 不会产生重复提交、成交、撤单或虚假终态；任何未解决订单继续阻断不同订单。

**已实现基础：** 独立的 default-closed 本地 execution-edge suite 已证明固定的
dry-run/submit/query/cancel/idempotency 契约，覆盖并发、超时、重启、not-found、断连与
partial-fill/cancel 竞态，且不注册 adapter 或联系 provider。Deterministic evidence 也可进入签名精确终态 clearance 和 copy-only 人工撤单资料；独立签名的显式撤单基础只放行一次 cancel effect，recovery 只能查询，且 gateway 响应不成为 canonical 事实。真实 adapter integration 与 recovery 证据仍属于发布工作。

### M3 — 对账后显式入账

新增版本化 preview-confirm-apply 命令，绑定 OMS、controlled intent、broker/client order、
lifecycle、fills、fees、taxes、reconciliation、Account Truth、ledger cutoff 和 operator approval。
所有 ledger events 在一个事务内写入；纠错采用补偿事件，不删除历史。

**退出门：** 入账 exactly once；partial+cancelled 只按实际成交入账；不完整或冲突证据 fail
closed；入账后 Ledger、Holdings、Equity Curve、Overview、realized P/L 和 Account Truth 一致。

**已实现基础：** provider-neutral 的
`karkinos.controlled_submission_ledger_posting.v1` 已提供单独签名的 preview 与 exactly-once 原子
apply。写事务内会重新核验精确终态 clearance、OMS 与 controlled intent、lifecycle 与 statement
证据、fills 与成本、Account Truth identity、valuation snapshot 以及 ledger cutoff/fingerprint。
完整成交、部分成交后撤单、零成交撤单、重复重试、证据 drift、ledger race，以及第二笔成交、posting
记录或完成事件写入中断均有 deterministic 原子回滚验收。Posting 不能联系 provider，也不能授予
submit、cancel、strategy、AI、risk、kill switch 或 capital authority。Provider-neutral 的
`karkinos.controlled_submission_ledger_correction.v1` 现可从 canonical replay 推导唯一的 append-only
纠正，要求独立签名，在写事务中复核全部 identity，保留原交易与费用，并在重试、重启和并发下
exactly once。Deterministic acceptance 已覆盖 Ledger、Holdings、Allocation、Equity、Overview、
Cockpit、Account State、realized P/L、valuation/ledger identity，以及纠正后刻意触发的 Account
Truth stale gate。Operations/Decision 证据旅程现可通过只读 deterministic delta preview、匹配
可信公钥身份、短时离线 Ed25519 challenge、proof verification 与最终显式确认完成 posting 步骤。
可选 correction 也可从持久化 order journey 显式打开：操作员选择一个 allowlisted reason，复核
replay 推导的 delta，验证独立离线 proof，再 exactly once 地追加补偿事件。原子 posting checkpoint
故障注入已覆盖；端到端真实 provider 故障证据仍未完成，因此 M3 尚不是发布完成声明。

### M4 — Operator Journey

在 Operations/Trading 中统一 preflight、确认、资金风险、阻断、提交状态、unknown recovery、
cancel、reconciliation、posting 和 kill switch。每个阻断状态必须显示证据和唯一安全下一步。

**已实现基础：** canonical、persisted-only 的 controlled-execution operator projection 现会把
每个近期 controlled intent 与 execution reconciliation、exact-terminal clearance、reconciled
ledger posting 以及任何 append-only correction 串成一条证据链，并给出唯一安全的人工下一步。
Unknown outcome 只允许查询。单独打开的签名式复核现可在无需手改数据库的情况下依次完成
reconciliation-to-terminal-clearance 与 terminal-clearance-to-ledger-posting：preview 保持只读，
私钥留在离线本地签名器，每次最终 apply 都由既有后端事务重新核验证据。投影本身不联系 provider、
不修改账本，也不授予 submit、cancel、resume 或 capital authority。Unknown outcome 现在也有单独
签名、原子 claim、只查询且防重复点击/restart 的 operator action。可选 correction 也已经具备
独立的签名 preview/proof/apply 复核，且不接受操作员输入财务 delta。精确持久化 open lifecycle
现在还提供无需手改数据库的人工撤单资料 preview/export；UI 明确要求在 Karkinos 外完成人工操作并
重新导入证据，也没有 cancel endpoint。独立的后端签名撤单契约继续保持默认关闭，在明确选择并
接受真实 provider 前不会接入该 Web journey。Rejected intent 还会提供 drift-checked、已净化且仅供复制
的复核资料；另一个 append-only、exactly-once 的人工确认会绑定复核人和精确 fingerprint，将
旅程收敛为不得重试且不改变任何交易权限。Trading 现在还能列出 canonical
`manually_confirmed` OMS 候选，并从持久化证据自动解析每个候选的最新精确资本评估、前序批次
对账与网关验证引用；操作员无需抄写三组 fingerprint，即可记录一条经独立签名验证的 append-only
逐单复核事实。缺失、歧义、较新阻断或扫描截断的证据一律 fail closed；Web 不暴露提交或撤单
动作，也不能修改 OMS、账本、风控、kill switch 或资本授权。Automation Cockpit 与 Decision 会先
fail-closed 核验并汇总同一 persisted-only 候选契约，再仅下钻到 Trading；来源漂移会阻断下钻。显式 scan 复用该投影写入幂等阻断告警，ready 候选仍是普通任务。Overview 与 Market 还会消费同一 valuation/ledger 绑定的当前持仓行情证据复核；只有显式定向 ingestion 得到更新且已确认的持久化证据后才能清除。Broker-neutral 的签名式 one-shot submission 与签名撤单基础已经实现；真实 adapter integration/recovery 证据和完整、经 provider 批准的 operator journey 仍未完成。v4 operator view 会检查有界范围内的全部持久化 intent，并让较早的关键未完成旅程优先于较新的低风险或已闭环旅程。

**退出门：** 操作者无需手改数据库即可完成正常和恢复流程；刷新、重复点击和服务重启不会重复
side effect；所有提交门禁在写事务内重新检查，而不是只依赖 UI 预览。

### M5 — 受控逐单试点

试点只允许一个 provider、一个账户别名、一个已复核策略、明确 symbol allowlist，同一时间最多
一个 unresolved controlled intent，并设置由操作者授权的资金、单笔、标的、换手、亏损、回撤、
rate 和 expiry 上限。任一 critical incident 立即退回 `disabled`。

**v1.8 发布门：**

- P0/P1 capability audit、完整后端/Web/build 检查全部通过。
- 只读 soak、真实 adapter 部署和回滚证据完整。
- 已验证 filled、rejected、unknown recovery、partial、cancel/partial-cancel、disconnect、restart、
  reconciliation 和 posting 路径。
- 每笔真实订单都具有完整的策略、Decision、风控、Account Truth、paper/shadow、资本、gateway、
  operator、lifecycle、reconciliation 和 ledger lineage。
- Duplicate submit、cancel、fill 和 ledger posting 均为 0。
- 发布时不存在未解决的 critical reconciliation。

## 推荐开发顺序

1. **基础已实现：** adapter ADR/capability/threat/deployment manifest 契约。
2. **基础已实现：** provider-neutral deterministic conformance fixture 与 release 绑定。
3. **待显式批准真实 provider 后：** provider 只读 adapter、collector integration、health 和 soak。
4. **本地基础已实现：** query/callback 生命周期、签名的完整成交/partial-cancel/零成交撤单
   精确终态对账、签名式 query-only unknown recovery，以及独立签名且具备重复/restart 防护的精确
   cancel/query-only-recovery 命令；真实 adapter recovery 证据仍待完成。
5. 默认关闭的真实 write adapter integration 与经 provider 批准的逐单 submit/cancel operator journey。
6. **基础已实现：** 单独签名、exactly-once 的 reconciled ledger posting、append-only 补偿纠正与
   核心跨页面验收。
7. Operations/Trading 端到端 UX 与告警。
8. 部署、回滚、故障演练和受控试点发布。

20 日 soak 是发布门槛，不是开发空窗。后续里程碑可以在 soak 期间使用 deterministic fixture 和
脱敏记录证据开发，但真实 write path 在验收通过前必须保持关闭。

## v1.8 之后

只有至少积累 20 个已复核交易日和 50 笔 provenance 完整的真实受控订单，且没有未解决的
critical reconciliation，并能计算滑点、拒单、延迟、回撤、divergence、事故和容量证据后，
`session_bounded` 才能进入评审。新授权必须限时、等于或小于已复核边界、可自动暂停，且不能
自行恢复、续期、扩大范围或扩资。

## 非目标

- 无人值守或永久授权的全账户交易。
- 策略或 AI 直接调用券商。
- 自动扩权或扩资。
- 在 Karkinos 中保存券商密码。
- v1.8 同时支持多个真实券商或机构级多账户 OMS。
- 高频或低延迟交易。
- 保证收益或投资建议式表达。

## 文档治理

- `KARKINOS_GOAL.md`：只维护 North Star、产品边界和长期 operating loop。
- `ROADMAP.md` / `ROADMAP.zh.md`：只维护当前基线、当前里程碑、优先级、顺序和退出门。
- `IMPLEMENTATION_LOG.md`：记录已完成切片、日期、commit、验证命令和测试数量。
- `ARCHITECTURE.md`：维护稳定组件、数据流、权限边界和不变量。
- README：维护当前安装、配置、工作流和用户可见行为。
- 专题文档：维护无法放入上述文件的稳定契约和 operator runbook。

里程碑完成时，只在 ROADMAP 中更新几行状态，把证据摘要写入 `IMPLEMENTATION_LOG.md`。不得再向
路线图追加实现日记、完整 diff、逐测试记录或重复的安全声明。
