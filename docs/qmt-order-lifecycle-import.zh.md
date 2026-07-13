# QMT 单笔订单生命周期证据导入

本契约用于把外部只读采集器生成的 QMT 订单状态规范化为 Karkinos 可持久化、可重放的证据。
Karkinos 自身不会在该流程中连接 QMT，也不会提交或撤销订单。

## 权限边界

- 命令默认只 preview，不创建数据库或写入事实。
- 写入必须同时提供 `--record` 和精确 acknowledgement：
  `record_qmt_order_lifecycle_evidence_without_execution_authority`。
- 导入不修改 OMS、fills、生产账本、资本授权、session 或 kill switch。
- 部分成交、撤单和 full-fill lifecycle 都不会自行解除 submission interlock。
- full-fill lifecycle 只是辅助证据；Stage 3.14 仍要求独立 broker statement、最新 clear Account
  Truth、精确双订单号以及单独的人类签名。
- 生产默认没有 QMT collector、write adapter、release provider 或可执行 cancel。

## 规范化输入

文件必须是 UTF-8 JSON，不超过 2 MiB。当前只接受一个
`karkinos.qmt_order_lifecycle_export.v1` / `exact_order_lifecycle` 快照，并且 `orders` 必须恰好
包含一笔订单。`source_sequence` 必须在同一 provider/gateway/account alias 范围内全局单调递增，
不能按单笔订单重新从 1 开始。

```json
{
  "schema_version": "karkinos.qmt_order_lifecycle_export.v1",
  "provider": "qmt",
  "snapshot_kind": "exact_order_lifecycle",
  "gateway_id": "qmt-controlled-write-1",
  "account_id": "raw-account-id-used-only-for-hashing",
  "account_alias": "main-cn-account",
  "captured_at": "2026-07-13T12:00:00+08:00",
  "source_sequence": 42,
  "orders": [
    {
      "broker_order_id": "QMT-ORDER-1",
      "client_order_id": "KARK-client-order-1",
      "symbol": "600519",
      "side": "buy",
      "status": "partially_filled",
      "order_quantity": "100",
      "cumulative_filled_quantity": "40",
      "cancelled_quantity": "0",
      "average_fill_price": "10.5",
      "submitted_at": "2026-07-13T11:59:55+08:00",
      "updated_at": "2026-07-13T11:59:59+08:00"
    }
  ],
  "fills": [
    {
      "broker_trade_id": "QMT-TRADE-1",
      "broker_order_id": "QMT-ORDER-1",
      "client_order_id": "KARK-client-order-1",
      "symbol": "600519",
      "side": "buy",
      "quantity": "40",
      "price": "10.5",
      "fee": "1.2",
      "tax": "0",
      "transfer_fee": "0.02",
      "net_amount": "-421.22",
      "filled_at": "2026-07-13T11:59:58+08:00"
    }
  ]
}
```

所有时间必须包含时区。默认最大快照年龄为 120 秒，可在 30 到 3600 秒范围内调整。金额与数量
建议使用十进制字符串，避免外部采集器先引入二进制浮点误差。

状态与数量必须满足：

| `status` | 约束 |
| --- | --- |
| `submitted` / `open` / `rejected` | `cumulative_filled_quantity = 0` 且 `cancelled_quantity = 0` |
| `partially_filled` | `0 < filled < order_quantity` 且 `cancelled = 0` |
| `filled` | `filled = order_quantity` 且 `cancelled = 0` |
| `cancelled` | `cancelled > 0` 且 `filled + cancelled = order_quantity` |

`fills.quantity` 必须精确合计为累计成交量；每条 fill 的订单号、标的和方向必须与唯一订单一致，
成交编号不得重复，加权平均成交价必须与订单平均价一致。未知字段和任何 password/token/secret/
credential/private-key 类字段都会阻断。

## 操作命令

只做 preview：

```bash
python scripts/import_qmt_order_lifecycle.py \
  --file /path/to/normalized-qmt-order.json \
  --db data/store/karkinos.db
```

显式记录：

```bash
python scripts/import_qmt_order_lifecycle.py \
  --file /path/to/normalized-qmt-order.json \
  --db data/store/karkinos.db \
  --record \
  --acknowledgement \
  record_qmt_order_lifecycle_evidence_without_execution_authority
```

本地文件路径不会写入证据；`account_id` 只形成域隔离哈希。持久化内容包含脱敏 source name、
account hash、capture/observe time、source sequence、file/evidence fingerprint、双订单号、规范化
订单与 fills，以及 validation blockers。

## 幂等、漂移与对账

- 完全相同的 observation id 会幂等复用。
- 同一账户范围的序号回退、同序号不同证据、capture time 非单调、账户哈希变化、任一订单号映射
  变化、标的/方向/数量合约变化都会在 SQLite `BEGIN IMMEDIATE` 内阻断。
- record 会重新计算 preview fingerprint 和 observation id，拒绝 preview 后内存篡改。
- read resolver 在未配置时返回 `not_configured`，不会创建数据库或表。
- execution reconciliation 只读持久化证据，可能展示 open、partial fill、partial fill + cancel、
  zero-fill cancel、filled awaiting independent evidence、identity conflict 或 blocked。
- 如果冲突事实先于签名清算落库，清算事务会拒绝；如果冲突事实晚于旧 clearance 落库，对账会
  重新变成 open mismatch，interlock preview 和下一单提交事务都会把旧 intent 视为 unresolved。

## 正式 pilot 前仍需完成

1. 实现并独立审查真实 QMT callback/poll collector，而不是由人工准备 JSON。
2. 证明断连、重连、进程重启、重复回调、乱序回调、序号恢复和本地文件原子替换行为。
3. 绑定 collector 部署身份、版本、账户范围、审计 run id 与发布/回滚证据。
4. 完成多交易日只读 soak 和异常演练，且 Account Truth、风控、对账和 kill switch 无未解决关键项。
5. 另行审查 broker write adapter 和 release source；不得因为本证据契约存在就默认注册写权限。
