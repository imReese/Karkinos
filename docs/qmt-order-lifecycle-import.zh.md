# 旧 QMT v1 生命周期 schema 兼容迁移（非支持声明）

`karkinos.qmt_order_lifecycle_export.v1` 已退役，不再是 Karkinos 的 canonical
contract。Karkinos 不依赖 QMT SDK，不注册 QMT runtime，也不据此宣称支持 QMT。

正常导入命令 `scripts/import_broker_order_lifecycle.py` 会拒绝旧 schema。确需保留
历史离线 JSON 时，只能通过显式迁移入口转换为
`karkinos.broker_order_lifecycle_export.v1`：

```bash
python scripts/migrate_legacy_qmt_order_lifecycle.py \
  --file /path/to/legacy-qmt-order.json \
  --db data/store/karkinos.db
```

该命令默认仅 preview。持久化仍需同时提供 `--record` 与 canonical 的非授权确认：

```bash
python scripts/migrate_legacy_qmt_order_lifecycle.py \
  --file /path/to/legacy-qmt-order.json \
  --db data/store/karkinos.db \
  --record \
  --acknowledgement \
  record_broker_order_lifecycle_evidence_without_execution_authority
```

迁移只做离线 schema 映射并保留 `provider=qmt` 作为来源标识；它不会加载 SDK、
连接券商、提交或撤单，也不会修改 OMS、fills、生产账本、风控、kill switch 或资本
授权。迁移后的记录按通用生命周期契约执行相同的字段、时效、数量、身份、顺序、
账户和 preview 完整性检查。历史数据库中已经存在的旧记录不会被静默重写；如发生
序号或身份冲突，迁移会 fail closed，需要人工审计。

新的 canonical contract、collector 批次格式和运行边界见
[通用券商订单生命周期证据与 collector ingestion](broker-order-lifecycle-ingestion.zh.md)。
任何第三方 QMT 适配器都必须另行审查并由用户显式授权，且不属于本迁移入口的范围。
