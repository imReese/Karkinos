# 受控券商撤单

[English](controlled-broker-cancellation.en.md) | [架构](ARCHITECTURE.zh.md) | [路线图](ROADMAP.zh.md)

## 范围

`karkinos.controlled_broker_cancellation.v1` 是 Karkinos 针对已提交受控订单的
provider-neutral、one-shot 撤单命令。它是执行边缘安全契约，不表示已经安装、审查、注册或官方
支持任何真实券商 adapter。

生产 factory 只有在项目所有者单独提供以下条件后才可能解除阻断：

- 一个已经明确审查的 execution gateway；
- 与精确 gateway 和账户别名绑定、当前有效且签名的 `manual_each_order` release；
- 一个受信任的本地 Ed25519 操作员身份；
- 精确的已提交 controlled intent，以及仍有剩余数量的最新持久化 lifecycle evidence。

该契约不引入 QMT、PTrade 或其他 provider 专用依赖。Strategy 和 AI 都不能调用它。

## 命令流程

```text
persisted controlled intent + OMS order
+ 最新精确 broker lifecycle observation
+ 当前签名 release + 已缓存 gateway health
-> 只读撤单 preview
-> 对精确 fingerprint 做短时离线签名
-> BEGIN IMMEDIATE claim 与证据重检
-> 最多一次 gateway cancel 调用
-> 已净化、非权威的命令结果
-> 显式摄取更新 lifecycle
-> reconciliation / Account Truth 复核
```

Preview 绑定 submit fingerprint、OMS order fingerprint、provider、gateway/account/broker/client
身份、lifecycle observation/evidence fingerprint、source sequence、订单/已成交/已撤/剩余数量、
release fingerprint、gateway-health fingerprint 与 operator identity。

最终命令要求：

- action `cancel_exact_controlled_broker_order`；
- artifact type `controlled_broker_cancellation`；
- acknowledgement `request_one_exact_broker_cancellation_once`；
- 来自已配置公钥身份且未过期的 proof。

精确重试只返回已持久化命令，不再次调用外部 gateway；冲突重试 fail closed。并发请求和服务重启
都不能产生第二次撤单 effect。

## 结果语义

持久化命令状态只有：

- `prepared`：已经 claim 外部 effect，但 finalization 可能尚未完成；
- `cancel_requested`：收到了身份完全匹配的 gateway 响应；
- `cancel_rejected`：Karkinos 确认没有调用 gateway，或 gateway 返回精确且确定的拒绝；
- `cancellation_unknown`：调用结果或响应身份不明确。

这些状态都不能证明券商已经撤单。即使 gateway 响应名为 `cancelled`，在显式摄取并对账更新的
lifecycle observation 前也只是净化后的边缘 telemetry。该命令不会更新 OMS、canonical lifecycle、
fills、ledger、risk、kill switch、interlock 或 capital authority。

Kill switch 会阻断新提交。它不会静默创建撤单权限，但也不会阻止一个已满足全部独立审查与签名
条件、用于降低风险的撤单命令。

## 只查询恢复

`karkinos.controlled_broker_cancellation_recovery.v1` 处理 `prepared`、已请求、已拒绝或 unknown
结果，绝不再次撤单。Recovery 要求另一份精确离线签名：

- action `query_exact_broker_cancellation_outcome`；
- artifact type `controlled_broker_cancellation_recovery`；
- acknowledgement
  `query_exact_broker_cancellation_outcome_once_without_recancel`。

经过确定性的 30 秒等待后，原子 claim 对该签名 recovery fingerprint 最多放行一次 query。
重复请求和重启 replay 复用已有 claim。查询结果仍会被净化并保持非权威；最终仍必须摄取更新的
持久化 lifecycle evidence。

## API 边界

受控提交 router 在 `/api/automation/controlled-broker-submission` 下提供显式 status、preview、
command、history 与 query-recovery endpoints。Pydantic model 拒绝包括凭证在内的未知字段。
Preview 与 history 不联系券商；不存在 Strategy/AI route，也没有自动 retry。

原有人工撤单 ticket 继续作为零券商接触的 fallback。Gateway 或签名 release 缺失、过期、不健康、
撤销或未审查时，签名命令保持 blocked，操作员只能在另行审查的券商界面操作，再显式摄取证据。

## 确定性验证

```bash
uv run pytest tests/test_controlled_broker_cancellation.py -q
uv run pytest tests/server/test_controlled_broker_submission_routes.py -k cancellation -q
uv run pytest tests/test_operator_approval.py tests/test_acceptance_audit.py -q
```

测试只使用 deterministic local fake，覆盖默认关闭、精确签名域、lifecycle drift、剩余数量、并发、
幂等 replay、从 `prepared` 重启、timeout/unknown、确定拒绝、query-only recovery、kill-switch
语义、敏感字段净化，以及不修改 OMS/ledger/authority 的边界。
