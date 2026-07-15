# 券商适配器确定性一致性验证

[English](broker-adapter-conformance.en.md) | [发布审查](broker-adapter-release-review.zh.md) | [生命周期采集](broker-order-lifecycle-ingestion.zh.md)

候选 adapter release 在被接受前，必须先具备一份版本化、provider-neutral 的 conformance
report。该 suite 只能显式启动，只在隔离的临时数据库内运行内置 deterministic fake/local
fixture，不联系券商或行情 provider。

该证据只证明当前 Karkinos 的只读 connector 与 Broker Order Lifecycle ingestion 契约仍能安全
失败；它**不证明**任何真实券商 adapter、SDK、账户、网络或 deployment 已经可用。真实 adapter
仍需项目所有者单独授权、第三方审查、只读实现审查、deployment 批准和完整 20 日 soak。

## 固定 v1 场景矩阵

v1 suite 的场景集合与期望结果不可自行修改：

| 区域 | 场景 | 必须结果 |
| --- | --- | --- |
| Snapshot | healthy | healthy 且无 submit capability |
| Snapshot | disconnected、stale、permission-limited、incomplete | blocked |
| Snapshot | unsupported schema | blocked |
| Lifecycle | same-run replay | reused |
| Lifecycle | duplicate evidence | duplicate，且不新增事实 |
| Lifecycle | out-of-order cursor | blocked |
| Lifecycle | disconnect、partial batch | blocked，且不前移 cursor |
| Lifecycle | process restart replay | 只记录一次，之后 reused |

缺失、重复、未知或篡改期望结果的 scenario 会使 report 不可记录。实际结果与固定期望不同则是
可记录的失败，以便回归继续作为 append-only 证据保留。敏感字段和未知顶层字段直接拒绝。

## 显式运行与记录

Preview 会执行 suite，但不会创建目标 evidence 数据库：

```bash
uv run python scripts/run_broker_adapter_conformance.py \
  --file /path/to/adapter-release.json \
  --db data/store/karkinos.db \
  --run-id conformance-2026-001
```

持久化是另一个显式动作：

```bash
uv run python scripts/run_broker_adapter_conformance.py \
  --file /path/to/adapter-release.json \
  --db data/store/karkinos.db \
  --run-id conformance-2026-001 \
  --record \
  --acknowledgement \
  record_deterministic_broker_adapter_conformance_without_provider_contact_or_execution_authority
```

append-only canonical 表是 `broker_adapter_conformance_reports`。同一个 run id 只有在 report
fingerprint 完全相同时才幂等；用它提交不同证据会被拒绝。

## Release 与 collector 绑定

`accepted` release review 会按精确 `release_evidence_ref` 解析最新 conformance report，要求
manifest fingerprint 和状态匹配，并把 conformance run/report fingerprint 持久化到 review
event。`rejected` 与 `revoked` 不依赖 conformance，仍可记录。

标记为 live 的 `callback` 与 `poll` collector 在 prepare 和 commit 时都会再次解析最新 report。
report 缺失、失败、被篡改或 drifted 都会阻断 ingestion。即使出现较新的 pass，也必须重新进行
人工 release review，因为旧 acceptance 绑定的是另一份 report。因此较新失败不能被旧 pass
掩盖。

`fixture` 与 `replay` 始终离线，不要求 release acceptance。Conformance 不会注册 adapter、读取
runtime 凭证、联系 provider、前移生产 collector cursor，也不会修改 OMS、fills、生产账本、
风控、kill switch、资本授权、submit 或 cancel 状态。

## 假设、验证与风险影响

- **假设：** 内置 suite 验证 Karkinos 契约，不验证未来第三方 adapter 的真实实现。
- **验证：** 确定性测试覆盖固定矩阵、重启、幂等、重复、乱序、断线、partial batch、schema
  drift、敏感/未知字段、report 篡改、最新结果优先、精确重新审查，以及 prepare/commit 间证据
  漂移。
- **风险影响：** 新门禁只能阻止 release acceptance 或 live 只读 lifecycle ingestion；不会创建
  broker-write 或资本权限路径。
