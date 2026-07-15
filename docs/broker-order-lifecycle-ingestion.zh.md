# 通用券商订单生命周期证据与 collector ingestion

[English](broker-order-lifecycle-ingestion.en.md) | [中文文档](README.zh.md)

Stage 3.15/3.16 的 canonical 边界是 broker-neutral 的只读证据链，不是券商连接或
交易权限。`provider` 只标记来源；QMT、PTrade、本地文件 watcher 或其他第三方组件
都只能在边缘把事实转换成本文契约，默认不注册，也不代表 Karkinos 官方支持。

## 权限边界

- 策略代码不得调用 collector 或任何券商适配器。
- 所有命令默认只 preview；写入必须显式 `--record` 并提供精确 acknowledgement。
- collector 输入只来自操作者指定的本地 UTF-8 JSON；Karkinos 不打开券商连接、
  不加载 SDK、不轮询 provider。
- 生命周期与 collector 表是追加式证据，不是 Account Truth、OMS、fill、账本、风控、
  kill switch、资本授权或 interlock release 的写入口。
- 默认没有 submit、cancel、live、release provider 或自动启动权限。

## Stage 3.15 canonical 生命周期契约

输入 schema 为 `karkinos.broker_order_lifecycle_export.v1`，每份快照必须只描述一个
broker/client order identity。`source_sequence` 在同一 provider/gateway/account alias
范围内全局单调递增，不能按订单重置。最小示例：

```json
{
  "schema_version": "karkinos.broker_order_lifecycle_export.v1",
  "provider": "deterministic_fixture",
  "snapshot_kind": "exact_order_lifecycle",
  "gateway_id": "fixture-readonly-gateway",
  "account_id": "raw-account-used-only-for-hashing",
  "account_alias": "fixture-account",
  "captured_at": "2026-07-13T12:00:00+08:00",
  "source_sequence": 42,
  "orders": [{
    "broker_order_id": "BROKER-ORDER-1",
    "client_order_id": "KARK-ORDER-1",
    "symbol": "600519",
    "side": "buy",
    "status": "partially_filled",
    "order_quantity": "100",
    "cumulative_filled_quantity": "40",
    "cancelled_quantity": "0",
    "average_fill_price": "10.5",
    "submitted_at": "2026-07-13T11:59:55+08:00",
    "updated_at": "2026-07-13T11:59:59+08:00"
  }],
  "fills": [{
    "broker_trade_id": "BROKER-TRADE-1",
    "broker_order_id": "BROKER-ORDER-1",
    "client_order_id": "KARK-ORDER-1",
    "symbol": "600519",
    "side": "buy",
    "quantity": "40",
    "price": "10.5",
    "fee": "1.2",
    "tax": "0",
    "transfer_fee": "0.02",
    "net_amount": "-421.22",
    "filled_at": "2026-07-13T11:59:58+08:00"
  }]
}
```

默认最大快照年龄为 120 秒。字段必须严格、时间必须带时区、账户只持久化 provider-
scoped hash。订单状态、累计成交/撤单数量、fill 合计、加权均价、标的、方向和双订单号
必须一致。credential/private-key 类字段、未知字段、陈旧/畸形事实、provider 或账户漂移、
序号回退/冲突、身份/合约漂移均 fail closed。

preview 与显式记录：

```bash
python scripts/import_broker_order_lifecycle.py \
  --file /path/to/lifecycle.json \
  --db data/store/karkinos.db

python scripts/import_broker_order_lifecycle.py \
  --file /path/to/lifecycle.json \
  --db data/store/karkinos.db \
  --record \
  --acknowledgement \
  record_broker_order_lifecycle_evidence_without_execution_authority
```

canonical 表为 `broker_order_lifecycle_observations`、
`broker_order_lifecycle_orders` 和 `broker_order_lifecycle_fills`。完全相同的 observation
幂等复用；resolver 只读持久化事实，未配置时不创建数据库或表。生命周期 full fill
仍不能替代独立 broker statement、fresh Account Truth 与人类签名。

## Stage 3.16 collector 批次边界

collector 输入 schema 为 `karkinos.broker_order_lifecycle_collector_batch.v1`。它在 lifecycle
外额外绑定：

- `run_id`、`collector_id`、`deployment_id`、`collector_version` 和 deployment fingerprint；
- 独立审查的 `release_evidence_ref` 与 `adapter_authorization_ref`；
- provider/gateway/account scope 与 `callback`、`poll`、`replay` 或 `fixture` 模式；
- connection/batch 状态、当前与下一 cursor、callback 收到/去重/乱序计数；
- 一个 complete batch 对应的 canonical lifecycle fact。

对于 `callback` 与 `poll`，`release_review_status=reviewed` 只是边缘 telemetry，不能自我授权。
live prepare 前，Karkinos 要求 exact `release_evidence_ref`、deployment、capability、collection
mode 与 authorization 匹配一份已持久化的人工 acceptance，契约见
[券商适配器发布审查](broker-adapter-release-review.zh.md)。该 acceptance 还必须绑定最新通过的
[deterministic conformance report](broker-adapter-conformance.zh.md)。prepared run 在 commit 前会
再次检查，因此 restart recovery 期间出现较新 conformance result 或 review revocation 时，会
阻断 lifecycle 写入与 cursor 前移，直至精确证据再次通过人工复核。

`callback`/`poll` 只是未来边缘适配器上报的模式标签，不会触发任何 provider contact。
本地显式运行：

```bash
python scripts/ingest_broker_order_lifecycle_collector_batch.py \
  --file /path/to/collector-batch.json \
  --db data/store/karkinos.db

python scripts/ingest_broker_order_lifecycle_collector_batch.py \
  --file /path/to/collector-batch.json \
  --db data/store/karkinos.db \
  --record \
  --acknowledgement \
  ingest_broker_order_lifecycle_collector_batch_without_execution_authority
```

运行证据写入 `broker_order_lifecycle_collector_runs`，cursor/account/deployment 状态写入
`broker_order_lifecycle_collector_state`。两阶段顺序是先 prepare 并持久化 sanitized lifecycle
observation，再在事务中 commit run/cursor：进程在两步之间退出时，以相同 run id 重启会重放
同一 observation，不会制造第二个事实。

确定性规则：

- 同 run、同输入精确重试为 idempotent；不同 run、相同 evidence 标记为 duplicate；
- 同 cursor 不同 evidence、cursor 回退、跳号/乱序、deployment/release/authorization/account
  漂移会阻断；
- live batch 即使自报 `reviewed`，canonical conformance/release review 缺失、失败、rejected、
  revoked、被篡改或 drifted 时仍会阻断；
- disconnect 与 partial batch 可记录为运营证据，但不能前移 cursor；
- callback 重复与乱序计数会被记录；一个 complete batch 仍只产生一个 canonical fact；
- read/list/state 操作不会隐式连接 provider 或创建不存在的数据库。

## Stage 3.17 collector 运行证据绑定

lifecycle resolver 会从持久化 run/state 表派生
`karkinos.broker_order_lifecycle_collector_binding.v1`，不会调用 collector 或 provider：

- scope 内从未出现 collector run 时为 `not_configured`，`required=false`，显式离线导入仍可用；
- scope 一旦出现 collector run，所选 lifecycle observation 必须能追溯到匹配的 recorded run；
  后续直导入不会绕开 collector，而是 `unbound` 并 fail closed；
- 两阶段 prepare 尚未 commit 时为 `recovery_pending`；disconnect、partial 或其他阻断 run 为
  `blocked`；run/state/provider/account/cursor 绑定不一致为 `inconsistent`；
- 只有 observation 已绑定、最新有效 run 为 recorded 且 cursor state 一致时才是 `healthy`；
  different-run duplicate 不参与“最新有效 run”选择，不能遮蔽更晚的失败。

required collector evidence 非 healthy 时，统一 lifecycle clearance blocker 会同时作用于 execution
reconciliation、签名清算事务、interlock 与下一单串行事务。它只能拒绝或使旧 clearance 失效，
不能单独清算订单，也不修改 collector state、OMS、fills、账本、风控、kill switch 或资本授权。

## 第三方适配器审查门槛

在用户明确指定实际券商环境之前，不新增任何券商 SDK、专用 runtime 或支持声明。未来适配器
通过版本化[一致性验证](broker-adapter-conformance.zh.md)与
[发布审查边界](broker-adapter-release-review.zh.md)绑定依赖/来源审查、capability、威胁
证据、部署、回滚、隐私和用户显式授权；之后仍必须通过断连/重启、重复/乱序、部分批次、脱敏
日志、kill switch 可见性与多交易日 soak。Adapter acceptance 不会注册适配器，也不能授予
submit/cancel 或资本权限。

## 假设、验证与风险影响

- 假设：边缘采集器能把 provider 原始事件确定性归一化；Karkinos 只验证并持久化本地批次。
- 验证：本地 deterministic fake/fixture 覆盖重启、幂等、重复、乱序/跳号、断连、部分批次、
  callback telemetry、preview 漂移、collector 绑定、直导入绕过拒绝、清算竞态、清算后下一单
  重新阻断和数据库副作用边界。
- 风险影响：新增事实只能缩小或重新阻断执行资格，不能扩大权限；不完整、陈旧、冲突或未经
  授权的证据全部 fail closed。
