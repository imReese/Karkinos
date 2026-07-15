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
| v1.4-v1.7 | 已完成 | 归因与费用精度、Daily Trading Plan、Operations runbook、非提交式受控桥接 |
| v1.8 控制面 | 基础已实现 | 签名限时授权、原子预算、session、实时门禁、暂停/replacement、单笔提交边界、互锁、生命周期证据、扩缩容评审 |
| v1.8 adapter acceptance | Provider-neutral 基础已实现 | 版本化 manifest、deterministic local conformance 证据、capability/boundary matrix、append-only accept/reject/revoke review、live collector 精确绑定与 persisted-only operator readiness 可见性；尚未选择或注册真实 provider |
| AI 原生 Phase 1-1.18 | 公式研究纵向闭环已实现 | provider-neutral、证据绑定、人工复核的研究、记忆、白名单 Formula DSL、canonical 扣费后回测和批判 workflow，不具备交易权限 |

Account Truth 和对账继续作为强制安全门，但不再是下一阶段产品主线。Phase 1.18 已按一次明确
授权完成公式研究纵向闭环；v1.8 仍是当前产品目标。进一步的 AI Phase 1.19+、语义记忆扩展和
自动 prompt 注入继续延后，直到受控执行形成真实运营闭环。

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

### M3 — 对账后显式入账

新增版本化 preview-confirm-apply 命令，绑定 OMS、controlled intent、broker/client order、
lifecycle、fills、fees、taxes、reconciliation、Account Truth、ledger cutoff 和 operator approval。
所有 ledger events 在一个事务内写入；纠错采用补偿事件，不删除历史。

**退出门：** 入账 exactly once；partial+cancelled 只按实际成交入账；不完整或冲突证据 fail
closed；入账后 Ledger、Holdings、Equity Curve、Overview、realized P/L 和 Account Truth 一致。

### M4 — Operator Journey

在 Operations/Trading 中统一 preflight、确认、资金风险、阻断、提交状态、unknown recovery、
cancel、reconciliation、posting 和 kill switch。每个阻断状态必须显示证据和唯一安全下一步。

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
4. Query/callback 生命周期与 partial/cancel/unknown recovery。
5. 默认关闭的 write adapter 与逐单 submit/cancel gate。
6. Reconciled ledger posting 与跨页面财务一致性。
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
