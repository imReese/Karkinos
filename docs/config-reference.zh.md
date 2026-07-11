# config.json 配置字段参考

`config.json` 是本机运行配置，默认已被 Git 忽略。它不应该保存完整资金账号、券商密码、券商登录凭证、截图、交割单、真实账户导出或运行时数据库。

JSON 标准不支持注释，因此不要在 `config.json` 里写 `//` 或 `/* ... */`。字段说明放在本文档，安全示例放在项目根目录的 `config.example.json`。

## 顶层字段

| 字段 | 类型 | 是否建议手工改 | 说明 |
| --- | --- | --- | --- |
| `host` | string | 可改 | 后端服务监听地址。本机开发通常使用 `127.0.0.1`。 |
| `port` | number | 可改 | 后端服务监听端口，默认 `8000`。 |
| `live_auto_start` | boolean | 可改 | Web 服务启动时是否自动启动内建调度器。不会自动下单。 |
| `data_source` | string | 可改 | 行情数据源，例如 `akshare` 或 `tushare`。 |
| `tushare_token` | string | 建议用引导脚本 | TuShare token。推荐用 `uv run python scripts/configure_data_source.py` 写入，避免命令行和日志泄露。 |
| `broker_fee_schedule` | object | 可改 | 本机券商费用规则。只放费用建模参数和脱敏账户别名，不放完整账户号。 |
| `broker_connectors` | array | 谨慎 | 只读券商事实 connector 配置。不得保存密码、token、secret 或 credential。 |
| `controlled_bridge_policy` | object | 谨慎 | 未来受控券商桥接白名单预览。只用于复核 connector、账户别名、策略和标的范围；v1.7 不允许打开 automation 或券商提交。 |
| `trusted_operator_identities` | array | 谨慎 | Stage 2.2/3.2 签名审批的 Ed25519 公钥白名单；只存公钥，不得存私钥、secret 或签名凭证。 |
| `notification` | object | 可改 | 通知配置，例如 `{"type": "console"}`。 |
| `live_poll_interval` | number | 可改 | 行情/调度轮询间隔，单位秒。 |
| `cors_allowed_origins` | array | 部署时可改 | 允许访问 API 的前端 origin。 |

不再建议使用顶层 `account_commission_rate` 和 `account_min_commission`。它们只作为老配置迁移输入读取；正式费用配置应写在 `broker_fee_schedule` 内。

## capital-authority v2 evaluation payload

资本授权接口接收的是一次性评估 payload，不是 `config.json` 权限配置。v2 policy 使用：

* `evidence_connector_ids`：允许提供只读账户/soak/Account Truth 证据的 connector id。
* `execution_gateway_ids`：未来允许进入受控写入复核的 gateway id；必须与前者不重叠。
* `connector_ids`：仅保留为兼容展示字段，不再具有授权含义。

v2 context 必须分别提供 `evidence_connector_id`、`execution_gateway_id`、
`evidence_connector_health_status`、`evidence_connector_can_submit`、
`execution_gateway_health_status`、`execution_gateway_can_submit` 和
`connector_account_binding_status="verified"`。两个 id 相同、policy 集合重叠、只读侧可提交、
任一侧不健康、执行侧不可提交或账户关系未验证都会 fail closed。旧的 `connector_id`、
`connector_health_status` 和 `connector_can_submit` 只作为兼容事实保留，不能单独授权。

即使评估 `allowed=true`，execution gateway 仍返回 runtime-unverified：API 不签发 authority、
不联系券商、不提交/撤单，也不修改 OMS 或生产账本。

Stage 2.4 的非提交式 runtime verifier 接口为：

* `GET /api/automation/execution-gateway-verification/status`
* `POST /api/automation/execution-gateway-verification/preview`
* `POST/GET /api/automation/execution-gateway-verification/records`
* `POST /api/automation/execution-gateway-verification/resolve`

preview 只接受 gateway/evidence-connector/account alias、OMS order id、64 位 order
fingerprint，以及 limit order 的 symbol/side/asset class/quantity/price；未知字段和任何
credential/password/token/secret 会被拒绝。record 还必须携带当前 verification fingerprint
和固定 acknowledgement `record_non_submitting_execution_gateway_verification`。生产运行期
gateway registry 默认是空的，且不能由这组 API 注册 gateway。clear record 最长有效五分钟，
resolve 会重新检查账户绑定、能力、60 秒内的健康来源和零副作用 dry-run。所有接口均不签发
authority、不预留预算、不修改 OMS/账本，也没有 submit、cancel、resume 或 scale-up 动作。

每单 dossier preview/confirmation 还必须提供
`execution_gateway_verification_fingerprint`。confirmation 中该字段是必填的 64 位小写十六进制
指纹；preview 允许空值用于查看 fail-closed 原因。对应的已记录 `manual_each_order` 资本评估
必须已经包含精确的 `execution_gateway_verification:<fingerprint>` evidence ref。每次调用都会
重新 resolve 当前 verification，并核对 execution gateway、只读 evidence connector、账户
别名、OMS order id、规范化订单指纹、脱敏 dry-run 订单条款以及 disabled authority/submission
边界。该字段不是凭证，
也不允许通过 per-order API 注册 gateway、签发权限或提交订单。

Stage 3.4 的 session-start Account Truth 接口为：

* `GET /api/automation/session-start-account-truth/status`
* `POST /api/automation/session-start-account-truth/preview`
* `POST/GET /api/automation/session-start-account-truth/records`
* `POST /api/automation/session-start-account-truth/resolve`

preview 只接受只读 `evidence_connector_id` 与脱敏 `account_alias`，并从当前应用状态重建最新
Account Truth 来源。来源必须 clear/pass/fresh、零未决差异、带有效 source fingerprint 且不
超过 120 秒。record 还需当前 fingerprint 和固定 acknowledgement
`record_non_authorizing_session_start_account_truth`。resolve 会重新计算来源并在记录超过
120 秒后阻断。接口拒绝 credential/private account 字段，不签发资本/runtime authority、
不预留预算、不修改 Account Truth/OMS/生产账本，也不联系券商。

Stage 3.5 的原子预算预留接口为：

* `GET /api/automation/controlled-sessions/budget-reservations/status`
* `POST /api/automation/controlled-sessions/budget-reservations/preview`
* `POST/GET /api/automation/controlled-sessions/budget-reservations/records`
* `GET /api/automation/controlled-sessions/budget-reservations/records/{reservation_id}`

preview 只接受已记录 attestation id；record 还要求精确 reservation fingerprint 和固定
acknowledgement `reserve_exact_non_authorizing_controlled_session_budget`。服务会在写事务内检查
资本、现金、当日换手和订单数，拒绝 credential/private account 字段。记录只占用边界内预算，
不会签发 runtime session、修改 OMS/生产账本、联系券商、提交/撤单、恢复/续期或扩容。

## broker_fee_schedule

`broker_fee_schedule` 是账户费用规则的唯一正式配置入口。Karkinos 会用它估算手工交易的佣金、印花税、过户费、其他费用、总费用和净现金影响；券商交割单仍是最终权威来源。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | string | 配置结构版本，例如 `karkinos.broker_fee_schedule.v1`。 |
| `account_profile_id` | string | 机器读取的稳定配置档案 ID，例如 `primary-broker-account`。不要写完整资金账号。 |
| `broker_name` | string | 券商名称，例如 `中信证券` 或 `示例券商`。 |
| `schedule_id` | string | 费用规则 ID，用于账本审计引用。 |
| `display_name` | string | UI 可读名称，推荐使用脱敏账户别名，例如 `中信证券88**16账户费用规则`。 |
| `currency` | string | 币种，当前通常为 `CNY`。 |
| `source_type` | string | 规则来源，例如 `broker_app_commission_query`、`broker_statement` 或 `manual_profile`。 |
| `account_identifier_saved` | boolean | 是否保存完整账户标识。应保持 `false`；如果为 `true`，配置会被拒绝。 |
| `screenshots_saved` | boolean | 是否保存截图。应保持 `false`；如果为 `true`，配置会被拒绝。 |
| `private_exports_saved` | boolean | 是否保存私有导出文件。应保持 `false`；如果为 `true`，配置会被拒绝。 |
| `precedence` | string | 口径优先级。推荐 `broker_statement_overrides_config`，表示交割单优先于本地估算。 |
| `stock_a_commission_rate` | number/string | A 股佣金率，例如万 1.5 写作 `0.00015`。 |
| `stock_a_min_commission` | number/string | A 股最低佣金，例如 `5.0`。 |
| `fund_etf_commission_rate` | number/string | ETF/场内基金佣金率。 |
| `fund_etf_min_commission` | number/string | ETF/场内基金最低佣金。 |
| `stamp_tax_rate` | number/string | 股票卖出印花税率。 |
| `transfer_fee_rate` | number/string | 默认过户费率。 |
| `exchange_transfer_fee_rates` | object | 按交易所覆盖过户费率，例如 `{"shanghai": 0.00001, "shenzhen": 0.0}`。 |
| `other_fee_rate` | number/string | 其他费用率；未知或无则用 `0.0`。 |
| `rules` | array | 更细的费用规则表，可按资产类别、市场、方向、费用组件建模。解析器会从规则表派生运行时所需的佣金/税费摘要。 |
| `broker_absorbed_components` | array | 由券商吸收、不进入用户总费用的费用组件说明。 |
| `limitations` | array | 已知限制，例如监管费用是否假设由券商吸收、未知规则是否需要人工复核。 |

### rules[] 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 单条规则 ID。 |
| `component` | string | 费用组件，例如 `commission`、`stamp_tax`、`transfer_fee`。 |
| `asset_classes` | array | 适用资产类别，例如 `stock`、`fund`、`etf`、`bond`。 |
| `instrument_types` | array | 适用标的类型，例如 `a_share`、`etf`、`convertible_bond`。 |
| `markets` | array | 适用市场，例如 `SSE`、`SZSE`、`BSE`。 |
| `side` | string | 适用方向：`buy`、`sell` 或 `both`。 |
| `rate` | string/null | 费率。建议用字符串保留精度，例如 `"0.00015"`。 |
| `rate_base` | string | 计费基准，例如 `gross_amount`。 |
| `min_fee` | string/null | 最低费用；没有最低费用时用 `null`。 |
| `payer` | string | 支付方，例如 `account`、`seller` 或 `broker`。 |
| `included_in_total_fee` | boolean | 是否计入用户总费用。券商吸收项应为 `false`。 |
| `status` | string | 可选。未知规则可写 `unknown`。 |
| `required_action` | string | 可选。未知规则需要人工确认时填写。 |

## broker_connectors

`broker_connectors` 只用于只读券商事实同步的本地配置，不允许保存任何登录凭证。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `connector_id` | string | connector 本地 ID，例如 `local-qmt-readonly`。 |
| `connector_type` | string | connector 类型，例如 `qmt_readonly`、`ptrade_readonly`，或从本地导出快照读取的 `local_export_readonly`、`qmt_readonly_export`、`ptrade_readonly_export`。 |
| `enabled` | boolean | 是否启用。默认建议 `false`。 |
| `client_path` | string | 本机券商客户端路径；当 `connector_type` 为 `local_export_readonly`、`qmt_readonly_export` 或 `ptrade_readonly_export` 时，这是被 `.gitignore` 排除的本地 JSON snapshot 路径。不得包含密码或 token。 |
| `account_alias` | string | 脱敏账户别名，例如 `中信证券88**16`。不要写完整资金账号。 |

`local_export_readonly`、`qmt_readonly_export` 和 `ptrade_readonly_export`
都只解析本地 JSON 快照文件里的资金、持仓、订单和成交证据，并通过 Broker Gateway
的只读 snapshot contract 返回。JSON 文件必须声明
`schema_version="karkinos.readonly_broker_snapshot_export.v1"`；缺失或不支持的
schema 会被标记为 runtime degraded，而不会读取账户号、资金、持仓、订单或成交事实。
这些 connector 不会启动券商客户端、不会保存凭证、不会提交或撤销券商订单，也不会写 OMS
或生产账本。

启用本地只读导出后，可使用以下 Stage 1 soak 接口：

* `POST /api/automation/broker-soak/capture`：捕获一次只读快照 observation。
* `GET /api/automation/broker-soak/status`：查看真实交易日覆盖、健康度和剩余 soak 天数。
* `GET /api/automation/broker-soak/observations`：复核脱敏的历史 observation。
* `POST/GET /api/automation/broker-soak/runs`：记录或复核 startup、intraday、
  end-of-day 只读运营阶段；end-of-day 必须绑定 clear 且无 open item 的执行对账。
* `POST/GET /api/automation/broker-soak/drills`：记录或复核断连、schema drift、
  stale data、重复证据和 service-instance restart recovery 演练。
* `GET /api/automation/broker-soak/promotion/status`：汇总各 connector 的签名晋级证据
  就绪状态；不会修改旧 Stage 1 汇总或 Stage 2 执行门禁。
* `POST /api/automation/broker-soak/promotion/dossiers/preview`：生成绑定最早 20 个
  clear-reconciled 交易日、完整阶段/演练覆盖和当前 Account Truth 来源的确定性 dossier。
* `POST /api/automation/broker-soak/promotion/acceptances`：使用与精确 dossier 绑定的
  Ed25519 approval 记录 owner acceptance。
* `GET /api/automation/broker-soak/promotion/acceptances`：只读复核追加式 acceptance
  记录；当前事实漂移会使历史 acceptance 不再满足就绪条件。

soak 只接受本地 provider market-calendar snapshot 明确标识的交易日；缺日历证据、周末/
休市日、陈旧快照和 connector 降级都不计入 20 日目标。配置中的 `enabled=true` 只允许
读取本地导出，不表示通过 Account Truth、允许券商提交或获得资本执行授权。

完整人工操作步骤见
[`BROKER_CONNECTOR_SOAK_RUNBOOK.md`](BROKER_CONNECTOR_SOAK_RUNBOOK.md)。这些接口
拒绝未声明字段/凭证，不具备提交、撤单、OMS/账本写入或资本授权能力。

promotion dossier 还要求稳定的脱敏账户别名/哈希、每天 startup/intraday/end-of-day
覆盖、五类恢复演练，以及 clear、pass、24 小时内、未清项为零的当前 Account Truth
证据。owner 必须签署 Account Truth 导入属于同一复核账户和已在服务外完成完整进程/
券商终端重启的声明。当前 service-instance restart 演练本身不等于完整外部重启验证。
签名成功仅表示 Stage 1 evidence readiness；它尚未接入 Stage 2 执行硬门禁。

## trusted operator public keys

Stage 1.1/2.2/3.2 的签名审批只在根配置 `trusted_operator_identities` 中保存公钥：

```json
{
  "trusted_operator_identities": [
    {
      "operator_id": "local-owner",
      "key_id": "owner-ed25519-2026-01",
      "algorithm": "ed25519",
      "public_key_base64": "<32-byte-raw-public-key-base64>",
      "enabled": true
    }
  ]
}
```

仅支持原始 32 字节 Ed25519 公钥的 Base64 表示。配置拒绝重复 operator/key、未知字段、
非 Ed25519 算法、非法长度，以及任何 `private_key`/secret 字段；操作员私钥必须保留在
Karkinos 之外。停用或轮换公钥会使旧 approval 在后续解析时失效。

本地审批接口：

* `GET /api/automation/capital-authority/operator-approvals/status`
* `POST/GET /api/automation/capital-authority/operator-approvals/challenges`
* `POST /api/automation/capital-authority/operator-approvals/verifications`
* `GET /api/automation/capital-authority/operator-approvals`

challenge 只能选择 `attest_per_order_dossier`/`per_order_dossier`、
`attest_controlled_session_envelope`/`controlled_session_envelope`，或
`accept_broker_connector_soak_promotion`/`broker_connector_soak_promotion_dossier`，并必须
携带精确 64 位工件指纹；TTL 只能为 30 至 300 秒。客户端对返回的 canonical signing
payload 签名后，
只提交 `challenge_id` 与 `signature_base64`。成功 verification 返回的 `approval_id` 必须
继续传入对应 promotion acceptance、per-order confirmation 或 session attestation。审批
只证明“配置身份确认了这份精确工件”，不签发资本/runtime authority，也不增加
gateway/券商写能力。

## controlled-bridge per-order dossier

Stage 2 foundation 提供以下本地证据接口：

* `GET /api/automation/controlled-bridge/status`
* `POST /api/automation/controlled-bridge/orders/{order_id}/dossier/preview`
* `POST /api/automation/controlled-bridge/orders/{order_id}/confirmations`
* `GET /api/automation/controlled-bridge/orders/{order_id}/confirmations`

preview 可传已记录的 `capital_evaluation_input_fingerprint`、明确的
`prior_batch_reconciliation_fingerprint` 与
`execution_gateway_verification_fingerprint`。确认请求必须携带这三个精确指纹、当前
`dossier_fingerprint`、与签名身份一致的 `operator_label`、对应 `operator_approval_id`，以及
固定 acknowledgement `confirm_exact_non_submitting_dossier_for_review`。资本评估还必须包含
同一条 `execution_gateway_verification:<fingerprint>` evidence ref。接口拒绝额外 credential
字段。每次 preview 都从当前应用状态解析精确 `evidence_connector_id` 的签名
Stage 1 promotion，并把 promotion dossier、运营来源、Account Truth 来源和 verified
acceptance id 纳入每单 dossier 指纹；缺失、非法、connector 不匹配、provider 失败或来源
漂移会 fail closed。不同的 `execution_gateway_id` 会单独绑定，并在当前 Stage 2.4 记录精确
匹配 gateway/connector/account/order/fingerprint/dry-run 条款前保持 runtime-unverified。
有效 promotion 只清除 Stage 1 子阻断；clear gateway verification 只清除 runtime-
verification 阻断。runtime authority、live gateway 和 broker submission 仍保持 disabled，
因此签名通过的 attestation 也不能成为券商命令。
每次 dossier preview 都会相对当前时间重新检查最新 soak observation；默认超过 900 秒即
进入 `connector_soak_evidence_not_fresh` 阻断，不能复用历史 healthy 标签绕过新鲜度门禁。

精确 batch evidence 接口位于 `/api/execution-reconciliation/batch-evidence/*`，提供 status、
preview、record、resolve 和 list。输入只接受 batch id、唯一 order id 集合、指定 run id、
精确 fingerprint、operator label 和固定 acknowledgement；不接受凭证。clear 记录也不会
授权下一批、修改 OMS/账本、预留预算、联系券商或提交/撤单。

## controlled-session envelope proposal

Stage 3 foundation 提供以下本地非执行接口：

* `GET /api/automation/controlled-sessions/status`
* `POST /api/automation/controlled-sessions/envelopes/preview`
* `POST /api/automation/controlled-sessions/attestations`
* `GET /api/automation/controlled-sessions/attestations`

preview 必须传 `capital_evaluation_input_fingerprint`、与资本评估一致的
`prior_batch_reconciliation_fingerprint`、1 至 50 个显式 `order_ids`、键集合与订单集合
完全相同的 `execution_gateway_verification_fingerprints`，以及带时区的
`requested_start_at`/`requested_expires_at`，还必须提供 64 位
`session_start_account_truth_fingerprint`。每个 map value 必须是唯一的 64 位小写十六进制
指纹，且已记录的资本评估必须包含完全相同的
`execution_gateway_verification:<fingerprint>` 引用集合。窗口最长 1800 秒，并且必须位于
资本 policy 的有效期内；资本评估还必须含有同一条
`session_start_account_truth:<fingerprint>` 引用。attestation 还需当前
`envelope_fingerprint`、与签名身份一致的
`operator_label`、对应 `operator_approval_id` 和固定 acknowledgement
`approve_exact_non_executing_session_envelope_for_review`。所有接口拒绝额外 credential
字段；不提供 issue、enable、runtime pause、resume、revoke-runtime、submit、cancel 或
scale-up 操作，也不预留/消费 runtime budget。
envelope 从资本评估中分别绑定只读 evidence connector 与 execution gateway；只读侧暴露
submit capability 会阻断。每笔订单的 verification 都会重新 resolve，并核对 gateway、
connector、账户、order id、规范化订单指纹、dry-run 条款与 disabled authority/submission
边界；任一失败都会阻断整个 envelope。全部 clear 只清除 runtime-verification blocker，
不会签发 session、预留预算或提交订单。session-start Account Truth 也会重新 resolve 并核对
connector、账户别名和来源指纹；clear 只清除 Account Truth evidence blocker。

## capital-scaling evidence review

Stage 4 foundation 提供以下本地审计接口：

* `GET /api/automation/capital-scaling/status`
* `POST /api/automation/capital-scaling/reviews/preview`
* `POST/GET /api/automation/capital-scaling/reviews/evaluations`
* `POST/GET /api/automation/capital-scaling/reviews/decisions`

review payload 必须包含版本化 current/proposed tier、带时区评审窗口、运行/订单/成交/拒单
样本、对账延迟和未清项、滑点、成本后结果、回撤、容量/流动性、paper-shadow divergence、
断连、违规、事故及带类型前缀的 `evidence_refs`。scale-up 最低门槛为 20 个复核交易日和
50 笔订单，并要求所有质量/来源门禁通过。human decision 绑定 evaluation fingerprint、
未认证 `operator_label` 和固定 acknowledgement
`record_scaling_review_decision_without_authority_change`。即使选择
`request_new_authorization_for_scale_up`，也只记录请求；接口不签发授权、不修改 runtime
limit、不恢复执行、不提交/撤单，也不自动扩容。
当前 `evidence_source_resolution_status=persisted_fail_closed_resolution`：
`account_truth`、`broker_soak`、`execution_reconciliation`、`paper_shadow`、`after_cost`、
`risk`、`incident`、`capacity` 和 `operating_sample` 都必须解析到持久化事实，并检查评审
窗口、fact fingerprint、clear 状态及声明指标与计算指标是否一致；resolution fingerprint
会与 review input 共同形成 evaluation identity。任何缺失或不一致都会把 scale-up 转为
hold。

Stage 4.2 还提供只读聚合证据接口：

* `GET /api/automation/capital-scaling/evidence/status`
* `GET /api/automation/capital-scaling/evidence/account-truth-snapshots/preview`
* `POST/GET /api/automation/capital-scaling/evidence/account-truth-snapshots`
* `POST /api/automation/capital-scaling/evidence/windows/preview`
* `POST/GET /api/automation/capital-scaling/evidence/windows`

Account Truth snapshot record 只接受固定 acknowledgement；window preview/record 只接受带时区
起止时间与 1–168 小时的边界容差，不接受收益、事故、滑点或容量指标。所有接口拒绝额外
credential 字段，不签发授权、不修改 OMS/runtime/生产账本、不接触券商，也不自动扩容。
同一 window 会在 Stage 4.3 额外计算 `operating_sample`：只读 broker soak 交易日、非
paper OMS 订单终态、真实成交链接、最新逐订单对账覆盖/p95 延迟、paper/shadow divergence
和现金流单位化最大回撤。接口仍不接受这些聚合指标；来源缺失或扫描截断只会返回 blocked。

## controlled_bridge_policy

`controlled_bridge_policy` 是 v1.7 的受控桥接白名单预览配置。它只让
gateway status 暴露本地复核范围，不会开启券商提交、券商撤单或自动实盘。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `policy_id` | string | 本地策略 ID，默认 `default-controlled-bridge-disabled`。 |
| `enabled` | boolean | 是否把白名单显示为本地 review policy。即使为 `true`，v1.7 仍不会提交券商订单。 |
| `allowed_connector_ids` | string[] | 允许进入未来复核范围的只读 connector id。 |
| `allowed_account_aliases` | string[] | 脱敏账户别名。不要写完整资金账号。 |
| `allowed_strategy_ids` | string[] | 允许进入未来复核范围的策略 id。 |
| `allowed_symbols` | string[] | 允许进入未来复核范围的标的代码。 |
| `per_order_confirmation_required` | boolean | 必须为 `true`；配置为 `false` 会被拒绝。 |
| `automation_allowed` | boolean | 必须为 `false`；配置为 `true` 会被拒绝。 |

该配置会拒绝 password、token、secret、credential 等字段，也不会保存 broker
登录凭证。真实券商成交或账户事实仍应通过 broker evidence / reconciliation
进入本地审计流程。

## 不应写入 config.json 的内容

- 完整资金账号、客户号、券商登录号。
- 券商密码、token、secret、credential。
- 交割单、截图、真实账户导出。
- 运行时数据库、行情缓存、日志。
- 真实持仓样例、真实关注列表或资产元数据。

这些内容应分别进入 SQLite 运行库、受忽略的本地文件、手工导入流程或完全不保存。
