# 券商执行边缘一致性验证

[English](broker-execution-edge-conformance.en.md) | [路线图](ROADMAP.zh.md) |
[受控执行](CONTROLLED_EXECUTION_PLAN.zh.md)

## 目的

本契约是在选择任何真实 write adapter 之前验证执行边缘语义的 provider-neutral M2 基础，和只读
[券商 adapter 一致性验证](broker-adapter-conformance.zh.md)相互独立。

内置 runner 只使用 `DeterministicFakeExecutionEdge`。它不会加载 provider SDK、读取凭证、注册
adapter、联系券商、提交或撤销真实订单，也不会修改 OMS、Ledger、Risk、kill switch 或资本权限。
通过报告只证明 Karkinos 的契约 harness，不代表支持 QMT、PTrade 或任何其他 provider。

## 契约

`karkinos.broker_execution_edge_manifest.v1` 声明一份精确审查范围：

- execution edge、adapter、version、provider、gateway、account alias 与 deployment identity；
- dry-run、submit、query、cancel 和幂等 client-order-id capability；
- 包括 `default_registered=false`、`production_enabled=false` 的强制边界；
- ADR、capability、威胁、部署、回滚、事故和隐私 review 引用；
- limitations，绝不包含凭证。

声明 write capability 只是描述待验证接口，并不会激活它。未知字段、敏感 key、缺失 capability，
或任何会启用生产能力的 boundary 都会 fail closed。

`karkinos.broker_execution_edge_conformance_result.v1` 把一份精确 manifest fingerprint 绑定到固定
场景矩阵。Report append-only 且使用唯一 run id；相同 run 重放幂等，同一 run id 内容改变会被
拒绝，同 scope 的较新失败会使旧 pass 失效。

## 固定 v1 矩阵

| 场景 | 必须结果 |
| --- | --- |
| capability contract | 完整但 default-closed |
| dry run | accepted 且零副作用 |
| 精确 submit identity | order/client identity 完全一致 |
| 确定性 submit 拒单 | rejected 且不产生 accepted order effect |
| 重复 submit | 只存一个订单，重放 reused |
| 并发 submit | 一次 accepted effect、一次 reused |
| accepted 后超时 | 显式 unknown outcome |
| unknown query | 使用同一 client id 查询且不重提 |
| broker not found | blocked，submit count 仍为零 |
| 进程重启 | 新 fixture instance 只查询共享证据 |
| 缺少精确 cancel command | cancel 调用前 blocked |
| 精确 cancel | 一次确定撤单结果 |
| 重复 cancel | 只存一个 cancel，重放 reused |
| partial-fill/cancel 竞态 | 成交量和撤销量分别保留 |
| query 断连 | blocked 且不会回退 submit |

重复/乱序 callback、cursor gap 和 partial batch 仍由 broker-order lifecycle collector conformance
负责，避免把执行命令语义和 lifecycle ingestion 事实混成一套契约。

## 本地运行

Preview 不创建数据库：

```bash
uv run python scripts/run_broker_execution_edge_conformance.py \
  --file /path/to/execution-edge-manifest.json \
  --db data/karkinos.db \
  --run-id local-execution-edge-v1
```

记录报告必须单独显式确认：

```bash
uv run python scripts/run_broker_execution_edge_conformance.py \
  --file /path/to/execution-edge-manifest.json \
  --db data/karkinos.db \
  --run-id local-execution-edge-v1 \
  --record \
  --acknowledgement record_local_execution_edge_conformance_without_provider_contact_or_authority
```

只会创建 `broker_execution_edge_conformance_reports`。Report 不能注册 gateway、满足真实 provider
验收、清除 live gate 或授予 submit/cancel 权限。

## 假设、验证和风险影响

假设：

- client order identity 在 retry、timeout 和 restart 后保持稳定；
- unknown outcome 只允许 query，绝不自动重提；
- cancel 是独立精确命令，不能作为 submit recovery 的隐式动作；
- local fake 没有网络和生产数据库能力。

确定性验证覆盖严格 schema、缺失/重复/篡改场景、敏感字段、重启、幂等、并发、超时、not-found、
断连、cancel replay、partial-fill/cancel 数量、report tamper、manifest drift、latest-result precedence、
显式记录以及不存在交易领域表。

生产风险影响为 low，因为新增边界是离线且无授权能力的；它通过明确 write-edge 预期降低未来接入
风险，但不会降低真实 adapter 的风险等级。真实接入仍需要 owner 明确选择、单独 ADR/威胁审查、
获批 sandbox 与故障证据、部署/回滚审查及新鲜人工授权。在此之前不注册任何 execution adapter。
