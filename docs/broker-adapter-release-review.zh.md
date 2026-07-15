# 券商适配器发布审查

[English](broker-adapter-release-review.en.md) | [一致性验证](broker-adapter-conformance.zh.md) | [生命周期采集](broker-order-lifecycle-ingestion.zh.md) | [路线图](ROADMAP.zh.md)

Karkinos 不再把适配器 payload 自报的 `reviewed` 当成发布证据。任何标记为 live
`callback` 或 `poll` 的 collector，必须先绑定一份已持久化、已人工接受的精确
`karkinos.broker_adapter_release_manifest.v1` 及其最新已复核本地 conformance report；collector
prepare 时检查一次，进程重启后 commit prepared run 前再检查一次。

该边界完全 provider-neutral。它不会选择券商、安装 SDK、注册适配器、联系 provider，也不会
授予 submit、cancel、OMS、账本、风控、kill switch、资本或 interlock 权限。

## Manifest 契约

一份 manifest 只绑定一个候选 deployment：

- release、collector、deployment、version、provider、gateway、account alias、deployment
  fingerprint 与 operator authorization identity；
- 允许的 live 采集模式（`callback` 和/或 `poll`）；
- 明确的读写 capability matrix；
- 进程、鉴权材料、数据所有权与默认注册边界；
- adapter ADR、capability matrix、威胁模型、部署 runbook、回滚 runbook 与隐私审查引用；
- 已知限制。

v1 capability matrix 是严格 schema。生命周期采集必须具备 read-order/read-fill capability，
且 submit/cancel capability 必须为 false。所有 boundary 也必须精确：runtime 鉴权材料留在
canonical evidence 之外；strategy/AI 不 import adapter；core 不 import provider SDK；adapter
不写 OMS、生产账本、风控、kill switch 或资本授权；默认不注册。

未知字段、疑似鉴权材料字段、畸形 identity、写 capability 和 boundary 违规全部 fail closed。
原始 account id 与凭证不属于 manifest。

## Conformance 前置条件与显式审查命令

必须先运行并显式记录 deterministic local conformance suite；详见
[券商适配器确定性一致性验证](broker-adapter-conformance.zh.md)。该 suite 只验证 Karkinos 契约，
不批准真实 provider。

默认 preview 只读且不创建数据库：

```bash
uv run python scripts/review_broker_adapter_release.py \
  --file /path/to/adapter-release.json \
  --db data/store/karkinos.db
```

操作者通过外部 reviewer/reason 引用记录 append-only 决策：

```bash
uv run python scripts/review_broker_adapter_release.py \
  --file /path/to/adapter-release.json \
  --db data/store/karkinos.db \
  --record \
  --review-id release-review-2026-001 \
  --decision accepted \
  --reviewer-ref operator-review-001 \
  --reviewed-at 2026-07-15T16:00:00+08:00 \
  --reason-ref reviewed-adr-and-threat-model \
  --acknowledgement \
  review_broker_adapter_release_without_registration_or_execution_authority
```

`rejected` 与 `revoked` 使用相同命令和精确 manifest。Review event 只追加不覆盖。release
一旦 revoked，不能原地再次 accept；必须创建新的 release identity 并重新审查。

canonical 表是 `broker_adapter_release_manifests`、`broker_adapter_release_review_events`，以及
独立 append-only 的 `broker_adapter_conformance_reports`。accepted review 会持久化精确
conformance run/report fingerprint。同 review id、同 exact decision 重试是幂等的；用同一
review id 或 release ref 提交不同证据会 fail closed。

schema 初始化会为旧 review 表增加两个显式 conformance-binding 列。已有 accepted row 没有该
绑定，因此继续 fail closed；必须针对最新 passing report 记录新的人工 review，不能让旧 row
继续充当 canonical conformance。

## Collector 绑定

`fixture` 与 `replay` 不联系 source，因此不要求 release review。对于 live 标签的 `callback`
或 `poll` batch：

1. batch 仍必须声明只读 contact 与 reviewed release；
2. prepare 按 `release_evidence_ref` 解析最新持久化 review 与 conformance report；
3. collector/deployment/provider/gateway/account/authorization 全部 identity 及 collection mode
   必须与 accepted manifest 精确一致；
4. prepared run 在写 lifecycle 与 commit cursor 前重复相同核验；
5. conformance/review 缺失、失败、rejected、revoked、被篡改或 drifted 时，run 会阻断，不创建
   lifecycle fact，也不前移 cursor；
6. 即使较新 conformance report 通过，也必须再次人工 release review，因为之前的 acceptance
   绑定的是精确 report。

accepted release review 只是 eligibility evidence，不会注册适配器，也不能替代真实 provider
选择、账户协议、soak、execution gateway、逐单批准、对账或资本门禁。

## 假设、验证与风险影响

- **假设：** ADR、威胁模型、部署、回滚与隐私文档是由稳定 id 引用的外部已审查 artifact；
  Karkinos 绑定审查事实，不复制其正文。
- **验证：** deterministic fixture 覆盖 preview、敏感/未知字段、写 capability、显式接受、拒绝、
  撤销、幂等、重启核验、deployment/authorization drift、conformance/review 缺失，以及
  prepare 与 commit 之间 conformance 失败或 release 撤销。
- **风险影响：** 该门禁只能阻断或撤销 live collector ingestion；不会联系券商，也不改变 OMS、
  fills、账本、风控、kill switch、资本授权、提交或撤单能力。
