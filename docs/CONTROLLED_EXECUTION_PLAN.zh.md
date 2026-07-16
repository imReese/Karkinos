# 受控资本执行计划

[English](CONTROLLED_EXECUTION_PLAN.md) | [目标](KARKINOS_GOAL.zh.md) | [路线图](ROADMAP.zh.md) | [架构](ARCHITECTURE.zh.md)

## 目标

Karkinos 只有在明确、有界、可观察、可逆且有证据支持的人工权限内，才能提交真实订单。首次
真实验证故意使用受限 envelope，以限制未知故障的影响；账户资本本身不是权限，也不决定产品
长期上限。

本文负责受控执行的 invariant 与 promotion gate。当前开发优先级和状态属于
[路线图](ROADMAP.zh.md)。

## 术语

- **账户资本：** 账户拥有的现金与资产。
- **授权资本：** 操作员明确提供给一个受控 scope 的最大 exposure。
- **风险 envelope：** 账户、策略、标的、流动性、换手、损失、回撤、时间、速率与运营限制的
  最严格组合。
- **Pilot exposure：** 为新适配器、策略、policy 或执行模式故意设置的初始受限 envelope。
- **资本扩容：** 基于已复核运营证据的新人工决定；绝不是利润或可用现金的自动结果。

有效权限是每项适用限制的最小值：

```text
操作员授权
账户与策略 policy
标的、流动性与订单限额
资本、现金、换手、损失与回撤预算
新鲜的行情、账户、gateway 与对账证据
kill switch 与运营健康
```

## 不可协商的 Invariant

1. 没有有效操作员授权时，券商提交必须关闭。
2. `manual_each_order` 是默认 live-like 模式。
3. 策略与 AI 代码不能导入或调用券商适配器。
4. 只读 evidence connector 与可写 execution gateway 使用不同身份和权限。
5. 唯一写路径是：已复核决策 → 账户/风控门禁 → 有界权限 → OMS → gateway → 券商证据 → 对账。
6. Kill switch、过期事实、connector 降级、未解决对账、policy 过期、预算耗尽或来源漂移都会
   阻断新提交。
7. Unknown submission outcome 只能查询，绝不自动重试。
8. 券商 callback 与导入是证据；不会静默改写账本。
9. Session 可以暂停、过期、收窄或撤销；不能自行续期、恢复、放宽或扩容。
10. 凭证与私密账户数据不得进入源码控制或 canonical audit payload。

## 权限模式

| 模式 | 人工权限 | 机器权限 | 默认状态 |
| --- | --- | --- | --- |
| `disabled` | 检查证据 | 无 | yes |
| `manual_each_order` | 确认一个精确订单 | 校验、提交一次、查询、对账、停止 | 当前目标 |
| `session_bounded` | 签署短期狭窄 envelope | 只准入剩余限额内合格订单 | 后续 promotion |

`session_bounded` 不是无人值守交易。操作员可以看到风险资本、过期时间、标的、限额、门禁与
暂停状态。Replacement 需要新证据以及新的相同或更窄签名。

## 交付门禁

### Gate 0 — 契约与默认关闭

所需证据：

- 有版本的 policy、scope、expiry、revocation 与确定性 deny reason；
- 独立 connector/gateway 身份以及同账户绑定；
- 无 gateway、OMS、ledger 或 broker 副作用的纯评估；
- 明确 feature flag，且生产环境默认没有 write adapter；
- 静态 strategy-to-broker 边界。

退出条件：缺失、过期、不匹配、陈旧或超预算证据始终拒绝。一次允许的 policy evaluation 本身
不会发布 runtime authority。

### Gate 1 — 真实只读券商 Soak

所需证据：

- 一个通过 append-only 人工复核接受的 canonical adapter release manifest，精确绑定
  provider、gateway、deployment、version、fingerprint、account alias、mode、capability 与
  process boundary；拒绝、撤销或漂移会阻断新增摄取；
- 一份与该 manifest 和人工 review 精确绑定的最新 passing deterministic local conformance
  report；它验证 Karkinos 契约，不验证真实 adapter；
- 一个经过复核、覆盖现金、持仓、订单、成交、session status、heartbeat 与 source timestamp
  的适配器；
- 不可变 snapshot、cursor、schema、deployment、capability health 与 freshness；
- 启动、盘中与日终对账；
- disconnect、stale、duplicate、out-of-order、partial-batch、schema-drift 与 restart 演练；
- drill evidence 绑定精确 connector/release scope，且同 scope 的最新结果优先于旧 pass；
- 至少 20 个经复核交易日，且没有未解决的 critical mismatch。

退出条件：soak 期间适配器不暴露写能力，每个事实都可追溯到经过复核的
provider/deployment/account scope。

### Gate 2 — 逐单人工确认 Bridge

所需证据：

- dry-run、submit、query、callback/poll、cancel 与幂等 client-order conformance；
- 精确 OMS/order/account/strategy/symbol/policy/gateway 绑定；
- 每次提交前即时生成、短期有效的最终操作员签名；
- accepted、rejected、partial、partial-cancelled、cancelled、filled、unknown、timeout、reconnect
  与 startup-recovery 行为；
- 上一个 controlled intent 完成对账前的跨订单 interlock；
- 显式对账，随后单独确认账本入账。

退出条件：重复请求不能生成重复券商订单。Unknown 或 unreconciled 状态阻断不同订单。Partial
与 cancel 数量守恒，每个账本修改 exactly once。

### Gate 3 — Session-Bounded Pilot

所需证据：

- 一个短期 account/strategy/symbol envelope，具有资本、订单、仓位、换手、损失、回撤、速率、
  时间与错误限额；
- 原子的账户与逐标的 reservation；
- 绑定新鲜 persisted live-gate snapshot 的 authenticated order admission；
- 遇到账户、风控、paper/shadow、对账、gateway、行情、预算、kill-switch、损失、拒绝、账户变化
  或错误事实时单向暂停；
- 单独签名的相同或更窄 replacement，不允许原地恢复；
- 下一批次前完成上一批次对账。

进入条件：逐单 pilot 至少运行 20 个经复核交易日和 50 个 provenance-complete controlled
orders，没有未解决 critical reconciliation，并有可度量的执行质量证据。

### Gate 4 — 基于证据的资本扩容

所需证据：

- 经复核天数与真实订单结果；
- 对账覆盖率与延迟；
- 扣费后收益、slippage、fill quality、rejection、partial/cancel rate；
- drawdown、divergence、incident、disconnect、policy violation、capacity 与 liquidity；
- 每个样本订单的精确 execution-scope provenance；
- 人工 scale-up、hold、scale-down 或 disable 决定。

退出条件：更大权限需要新的、明确且会过期的操作员决定。系统可以建议或强制 hold、scale-down、
pause 或 disable；绝不会自动 scale up。

## 运行时安全规则

- 外部调用前持久化 intent 与 OMS pending state。
- 外部调用只有一个永久 execution claim。
- Timeout 不代表 rejection，也不能释放 interlock。
- Query 与 callback evidence 使用同一 broker/client order identity。
- Lifecycle sequence 与累计数量单调且守恒。
- Full 或 partial fill 在 reconciliation clearance 前需要独立券商证据与 Account Truth。
- 签名的精确终态 clearance 覆盖完整成交、零成交撤单和部分成交后撤单；仍开放的 partial fill
  继续阻断，终态撤单只记录实际 fills，绝不签发券商撤单。
- Reconciliation clearance 与 ledger posting 是两个独立事务和批准。
- Ledger posting 使用版本化 `karkinos.controlled_submission_ledger_posting.v1` artifact 和新鲜的
  最终操作员签名。写事务会重新核验精确 OMS/intent、lifecycle、statement/fill/cost、Account
  Truth、valuation 与 ledger identity binding，再把所有 entries 与 posting record 一起提交。
- Partial-cancel 只写实际 fills；no-fill cancel 记录零 entry no-op。重复重试复用 immutable posting；
  evidence 或 ledger drift 会拒绝整个事务。
- 纠错使用独立的 `karkinos.controlled_submission_ledger_correction.v1` preview 与签名；它不接受财务
  数值，只能通过排除原 posting entries 的 canonical replay 推导精确补偿事件，在写锁内重新推导，
  保留全部原始事实，并在 apply 后要求更新的 Account Truth import。零 fill posting、依赖交易或
  无效重放继续阻断。
- Posting 不具备 provider contact、submit、cancel、strategy/AI、risk decision、kill switch 或
  capital authority 能力。
- GET、告警、报告与 UI rendering 不会隐式联系 gateway。
- 在写事务中，较新的 blocked fact 优先于较旧的 clear preview。

## 操作员可见性

产品必须根据已持久化事实展示：

- 模式、账户、策略、标的、provider 与 gateway；
- 授权资本、有效风险资本与剩余 headroom；
- 订单、现金、换手、损失、回撤与速率限额；
- expiry、最新 live-gate snapshot、pause/revocation state 与 kill switch；
- 最新 controlled intent、broker lifecycle、reconciliation 与 posting；
- 精确阻断项、证据年龄和一个安全的下一步。

任何界面都不得仅因为研究、签名或一次 policy evaluation 通过而暗示已批准执行。

## 发布与监管门禁

启用任何券商连接写能力前，所有者必须审查真实 provider agreement、账户权限、程序化交易报告
与测试义务、部署、凭证、故障行为以及回滚流程。Karkinos 将该审查记录为证据，但不会自行证明
已获得券商或法律批准。

## 完成边界

当已复核策略可以在明确、有界、会过期的人工权限下运行，每个订单都能从持久证据恢复、对账
与入账，并且权限可以安全暂停、收窄、过期或撤销时，受控执行目标才算完成。永久授权、无人值守
的全账户执行仍是非目标。
