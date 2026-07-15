# `config.json` field reference

[中文](config-reference.zh.md) | [Documentation](README.en.md)

`config.json` is local runtime configuration and is ignored by Git by default.
It must not contain a full brokerage account number, broker password, login
credential, screenshot, statement, real account export, or runtime database.

JSON does not support comments. Keep field explanations here and safe examples
in the repository-root `config.example.json`.

## Top-level fields

| Field | Type | Manual editing | Description |
| --- | --- | --- | --- |
| `host` | string | allowed | Backend listen address; usually `127.0.0.1` for local development. |
| `port` | number | allowed | Backend port; default `8000`. |
| `live_auto_start` | boolean | allowed | Starts the built-in scheduler with the Web service; never enables automatic ordering. |
| `data_source` | string | allowed | Market-data source such as `akshare` or `tushare`. |
| `tushare_token` | string | prefer setup script | Use `uv run python scripts/configure_data_source.py` to reduce shell/history exposure. |
| `broker_fee_schedule` | object | allowed | Local fee-model parameters and a sanitized account alias only. |
| `broker_connectors` | array | caution | Read-only broker-fact connectors; credentials are forbidden. |
| `controlled_bridge_policy` | object | caution | Controlled-bridge review allowlist; does not enable automation or submission. |
| `trusted_operator_identities` | array | caution | Ed25519 public-key allowlist; never store private keys or signing credentials. |
| `notification` | object | allowed | Notification configuration, for example `{"type": "console"}`. |
| `live_poll_interval` | number | allowed | Market/scheduler polling interval in seconds. |
| `cors_allowed_origins` | array | deployment | Frontend origins allowed to call the API. |

Top-level `account_commission_rate` and `account_min_commission` are legacy
migration inputs. New fee configuration belongs in `broker_fee_schedule`.

## Capital-authority v2 evaluation payload

The capital-authority API accepts a one-time evaluation payload, not authority
configuration stored in `config.json`.

- `evidence_connector_ids`: connectors allowed to supply read-only account,
  soak, and Account Truth evidence.
- `execution_gateway_ids`: gateways eligible for later controlled-write
  review; this set must not overlap the evidence connectors.
- `connector_ids`: compatibility display field with no authorization meaning.

The v2 context separately supplies `evidence_connector_id`,
`execution_gateway_id`, both health/can-submit states, and
`connector_account_binding_status="verified"`. An identical id, overlapping
policy sets, write capability on the read side, unhealthy edges, a non-writing
execution edge, or an unverified account relationship fails closed. Legacy
`connector_id`, `connector_health_status`, and `connector_can_submit` fields
cannot authorize by themselves.

Even when evaluation returns `allowed=true`, the gateway remains
runtime-unverified. The API issues no authority, contacts no broker, submits or
cancels no order, and mutates neither OMS nor the production ledger.

### Stage 2.4 non-submitting gateway verification

Endpoints:

- `GET /api/automation/execution-gateway-verification/status`
- `POST /api/automation/execution-gateway-verification/preview`
- `POST/GET /api/automation/execution-gateway-verification/records`
- `POST /api/automation/execution-gateway-verification/resolve`

Preview accepts only gateway, evidence connector, account alias, OMS order id,
a 64-character order fingerprint, and sanitized limit-order terms. Unknown
fields and credential/password/token/secret values are rejected. Recording
also requires the current verification fingerprint and acknowledgement
`record_non_submitting_execution_gateway_verification`.

The production gateway registry is empty by default and these APIs cannot
register a gateway. A clear record lasts at most five minutes. Resolve
rechecks account binding, capability, health evidence no older than 60 seconds,
and a zero-side-effect dry run. No endpoint issues authority, reserves budget,
mutates OMS/ledger, or exposes submit, cancel, resume, or scale-up.

Per-order dossier preview/confirmation also carries
`execution_gateway_verification_fingerprint`. Confirmation requires the exact
64-character lowercase fingerprint, and the recorded `manual_each_order`
capital evaluation must reference
`execution_gateway_verification:<fingerprint>`. Every call re-resolves the
current verification and exact gateway/connector/account/order/dry-run terms.
The fingerprint is not a credential.

### Stage 3.4 session-start Account Truth

Endpoints:

- `GET /api/automation/session-start-account-truth/status`
- `POST /api/automation/session-start-account-truth/preview`
- `POST/GET /api/automation/session-start-account-truth/records`
- `POST /api/automation/session-start-account-truth/resolve`

Preview accepts a read-only `evidence_connector_id` and sanitized
`account_alias`, then rebuilds the latest Account Truth source. The source must
be clear/pass/fresh, have no pending difference, carry a valid fingerprint, and
be no older than 120 seconds. Recording requires the current fingerprint and
`record_non_authorizing_session_start_account_truth`. Resolve recomputes the
source and blocks expired records. These endpoints reject private fields and
issue no authority, reserve no budget, mutate no state, and contact no broker.

### Stage 3.5 atomic budget reservation

Endpoints:

- `GET /api/automation/controlled-sessions/budget-reservations/status`
- `POST /api/automation/controlled-sessions/budget-reservations/preview`
- `POST/GET /api/automation/controlled-sessions/budget-reservations/records`
- `GET /api/automation/controlled-sessions/budget-reservations/records/{reservation_id}`

Preview accepts only a recorded attestation id. Recording additionally requires
the exact reservation fingerprint and
`reserve_exact_non_authorizing_controlled_session_budget`. A write transaction
checks capital, cash, daily turnover, and order count. The record only reserves
bounded budget; it cannot create a session or broker authority.

Stage 3.6 also requires `per_symbol_runtime_limits`. Its keys exactly match the
projected symbols; values are positive CNY limits with at most four decimal
places and cannot exceed the recorded capital evaluation. The map participates
in envelope, attestation, and reservation fingerprints. Missing, extra,
over-precision, projected-over-limit, and concurrent-over-limit values block.

### Stage 3.7–3.11 runtime visibility and authority

Read-only rate-limit visibility:

- `GET /api/automation/controlled-sessions/runtime-rate-limit/status`
- `GET /api/automation/controlled-sessions/runtime-rate-limit/admissions`

Automatic-pause visibility and evaluation:

- `GET /api/automation/controlled-sessions/automatic-pause/status`
- `GET /api/automation/controlled-sessions/automatic-pause/events`
- `GET /api/automation/controlled-sessions/automatic-pause/states/{session_id}`
- `POST /api/automation/controlled-sessions/automatic-pause/evaluations`
- `GET /api/automation/controlled-sessions/automatic-pause/gate-snapshots`
- `GET /api/automation/controlled-sessions/automatic-pause/gate-snapshots/{session_id}`

Evaluation requires the exact session id and one-time token. It may only
capture a snapshot and produce clear/no-op or a one-way pause. There is no
direct pause, resume, renew, widen, admit, or broker route. Snapshots older than
30 seconds, market data older than 120 seconds, three rate rejections within 60
seconds, or an invalid/missing hard fact tend toward pause. Missing broker or
ledger values are never assumed clear.

Runtime-authority endpoints:

- `GET /api/automation/controlled-sessions/runtime-authority/status`
- `POST /api/automation/controlled-sessions/runtime-authority/issuance/preview`
- `POST/GET /api/automation/controlled-sessions/runtime-authority/sessions`
- `GET /api/automation/controlled-sessions/runtime-authority/sessions/{session_id}`
- `POST /api/automation/controlled-sessions/runtime-authority/sessions/{session_id}/replacement/preview`
- `POST /api/automation/controlled-sessions/runtime-authority/sessions/{session_id}/replacements`
- `POST /api/automation/controlled-sessions/runtime-authority/sessions/{session_id}/revocation/preview`
- `POST /api/automation/controlled-sessions/runtime-authority/sessions/{session_id}/revocations`
- `GET /api/automation/controlled-sessions/runtime-authority/replacements`
- `GET /api/automation/controlled-sessions/runtime-authority/revocations`

Issuance and revocation require short-lived Ed25519 approvals for
`issue_controlled_session` and `revoke_controlled_session`, plus matching
possession proof. History APIs do not return raw signatures. A runtime token is
shown only in the initial response; the database stores a salted hash. No
resume/renew/widen/admit/submit/cancel path exists, and session authority cannot
expand capital authority or mutate OMS/ledger.

A Stage 3.11 replacement is not an in-place resume. It needs a new reservation,
exact replacement fingerprint, short-lived
`replace_paused_controlled_session` approval, matching signature, and fixed
acknowledgement. Clear gate evidence must be continuous for 60 seconds and the
latest snapshot no older than 30 seconds. The new scope can only stay equal or
narrow. One transaction revokes the old session and creates a one-time token.

## `broker_fee_schedule`

This object is the authoritative local fee-rule configuration. Karkinos uses it
to estimate commission, stamp tax, transfer and other fees, total fees, and net
cash impact. Broker statements remain final authority.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | string | Structure version, for example `karkinos.broker_fee_schedule.v1`. |
| `account_profile_id` | string | Stable sanitized profile id; never a full account number. |
| `broker_name` | string | Broker display name. |
| `schedule_id` | string | Fee-rule id referenced by ledger audit. |
| `display_name` | string | Human-readable sanitized alias. |
| `currency` | string | Usually `CNY`. |
| `source_type` | string | Such as `broker_app_commission_query`, `broker_statement`, or `manual_profile`. |
| `account_identifier_saved` | boolean | Must remain `false`. |
| `screenshots_saved` | boolean | Must remain `false`. |
| `private_exports_saved` | boolean | Must remain `false`. |
| `precedence` | string | Prefer `broker_statement_overrides_config`. |
| `stock_a_commission_rate` | number/string | A-share commission; 1.5 bps is `0.00015`. |
| `stock_a_min_commission` | number/string | Minimum A-share commission. |
| `fund_etf_commission_rate` | number/string | ETF/exchange-fund commission rate. |
| `fund_etf_min_commission` | number/string | ETF/exchange-fund minimum. |
| `stamp_tax_rate` | number/string | Stock sell-side stamp-tax rate. |
| `transfer_fee_rate` | number/string | Default transfer-fee rate. |
| `exchange_transfer_fee_rates` | object | Per-exchange overrides. |
| `other_fee_rate` | number/string | Other fee rate; use `0.0` if none or unknown. |
| `rules` | array | Detailed rules by asset, market, side, and component. |
| `broker_absorbed_components` | array | Components paid by the broker, excluded from user totals. |
| `limitations` | array | Known assumptions and items requiring review. |

### `rules[]` fields

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Rule id. |
| `component` | string | `commission`, `stamp_tax`, `transfer_fee`, and so on. |
| `asset_classes` | array | Such as `stock`, `fund`, `etf`, `bond`. |
| `instrument_types` | array | Such as `a_share`, `etf`, `convertible_bond`. |
| `markets` | array | Such as `SSE`, `SZSE`, `BSE`. |
| `side` | string | `buy`, `sell`, or `both`. |
| `rate` | string/null | Prefer a string to preserve precision. |
| `rate_base` | string | For example `gross_amount`. |
| `min_fee` | string/null | `null` when no minimum applies. |
| `payer` | string | Such as `account`, `seller`, or `broker`. |
| `included_in_total_fee` | boolean | Broker-absorbed items use `false`. |
| `status` | string | Optional; unknown rules may use `unknown`. |
| `required_action` | string | Optional human action for an unknown rule. |

## `broker_connectors`

The default is an empty list. Connectors are explicitly registered read-only
edges and cannot store login credentials.

| Field | Type | Description |
| --- | --- | --- |
| `connector_id` | string | Local id such as `local-fixture-readonly`. |
| `connector_type` | string | Built-in canonical type is only `local_export_readonly`; broker-specific types require separate implementation and review. |
| `enabled` | boolean | Explicit opt-in; defaults to `false`. |
| `client_path` | string | Git-ignored local JSON snapshot path; not an SDK executable path. |
| `account_alias` | string | Sanitized alias, never a full account number. |

`local_export_readonly` parses cash, position, order, and fill evidence from a
local JSON snapshot with
`schema_version="karkinos.readonly_broker_snapshot_export.v1"`. An absent or
unsupported schema degrades runtime health without reading facts. The connector
does not start a broker client or retain authentication data. It cannot submit
or cancel orders and cannot write OMS/ledger. Legacy broker-named export types
do not automatically create adapters; a third-party adapter needs dependency,
authentication, capability, recovery, release, and rollback review plus
explicit authorization.

Stage 1 soak endpoints:

- `POST /api/automation/broker-soak/capture`
- `GET /api/automation/broker-soak/status`
- `GET /api/automation/broker-soak/observations`
- `POST/GET /api/automation/broker-soak/runs`
- `POST/GET /api/automation/broker-soak/drills`
- `GET /api/automation/broker-soak/promotion/status`
- `POST /api/automation/broker-soak/promotion/dossiers/preview`
- `POST /api/automation/broker-soak/promotion/acceptances`
- `GET /api/automation/broker-soak/promotion/acceptances`

Only explicitly identified trading days from the local market-calendar
snapshot count toward the 20-day target. Missing calendar evidence, non-trading
days, stale snapshots, and degraded connectors do not count. `enabled=true`
only permits local-export reads; it does not pass Account Truth or grant broker
submission/capital authority. See
[`BROKER_CONNECTOR_SOAK_RUNBOOK.md`](BROKER_CONNECTOR_SOAK_RUNBOOK.md).

Promotion additionally requires a stable sanitized account identity, daily
startup/intraday/end-of-day coverage, five recovery drills, and current
clear/pass Account Truth evidence no older than 24 hours with zero open items.
Signed acceptance means Stage 1 evidence readiness only.

## Trusted operator public keys

Only Ed25519 public keys belong in `trusted_operator_identities`:

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

The configuration rejects duplicate identities, unknown fields, non-Ed25519
algorithms, invalid lengths, and private-key/secret fields. Private keys remain
outside Karkinos. Disabling or rotating a key invalidates old approvals during
later resolution.

Approval endpoints:

- `GET /api/automation/capital-authority/operator-approvals/status`
- `POST/GET /api/automation/capital-authority/operator-approvals/challenges`
- `POST /api/automation/capital-authority/operator-approvals/verifications`
- `GET /api/automation/capital-authority/operator-approvals`

Challenges bind an allowed action/artifact pair and exact 64-character
fingerprint, with a 30–300 second TTL. A successful verification proves only
that the configured identity confirmed that exact artifact; it issues no
capital/runtime authority and adds no gateway capability.

## Controlled-bridge per-order dossier

Endpoints:

- `GET /api/automation/controlled-bridge/status`
- `POST /api/automation/controlled-bridge/orders/{order_id}/dossier/preview`
- `POST /api/automation/controlled-bridge/orders/{order_id}/confirmations`
- `GET /api/automation/controlled-bridge/orders/{order_id}/confirmations`

Confirmation binds the recorded capital evaluation, prior-batch
reconciliation, gateway verification, current dossier fingerprint, matching
operator identity/approval, and
`confirm_exact_non_submitting_dossier_for_review`. Preview re-resolves signed
Stage 1 promotion, operational sources, Account Truth, gateway/account/order
terms, and evidence freshness. A healthy observation older than 900 seconds is
blocked. Even a valid attestation remains non-submitting and non-authorizing.

Exact batch-evidence APIs under
`/api/execution-reconciliation/batch-evidence/*` provide status, preview,
record, resolve, and list. A clear record cannot authorize another batch,
reserve budget, contact a broker, or mutate OMS/ledger.

## Controlled-session envelope proposal

Endpoints:

- `GET /api/automation/controlled-sessions/status`
- `POST /api/automation/controlled-sessions/envelopes/preview`
- `POST /api/automation/controlled-sessions/attestations`
- `GET /api/automation/controlled-sessions/attestations`

Preview binds the capital evaluation, prior-batch reconciliation, 1–50 explicit
orders, an exact gateway-verification fingerprint per order, a timezone-aware
window no longer than 1,800 seconds, and a session-start Account Truth
fingerprint. Attestation additionally requires the current envelope
fingerprint, matching operator approval, and
`approve_exact_non_executing_session_envelope_for_review`. No endpoint issues,
enables, pauses, resumes, revokes, submits, cancels, scales, reserves, or
consumes runtime authority.

## Capital-scaling evidence review

Endpoints:

- `GET /api/automation/capital-scaling/status`
- `POST /api/automation/capital-scaling/reviews/preview`
- `POST/GET /api/automation/capital-scaling/reviews/evaluations`
- `POST/GET /api/automation/capital-scaling/reviews/decisions`

The payload includes versioned tiers, a timezone-aware review window,
run/order/fill/rejection samples, reconciliation latency/open items, slippage,
after-cost result, drawdown, capacity/liquidity, divergence, disconnects,
violations, incidents, and typed `evidence_refs`. Scale-up requires at least 20
reviewed trading days and 50 orders plus every quality/provenance gate. A human
decision is still only a recorded request; it does not issue authority or
change runtime limits.

Persisted fail-closed resolution covers Account Truth, broker soak, execution
reconciliation, paper/shadow, after-cost, risk, incident, capacity, and the
operating sample. Missing or inconsistent evidence converts scale-up to hold.

Read-only aggregation endpoints:

- `GET /api/automation/capital-scaling/evidence/status`
- `GET /api/automation/capital-scaling/evidence/account-truth-snapshots/preview`
- `POST/GET /api/automation/capital-scaling/evidence/account-truth-snapshots`
- `POST /api/automation/capital-scaling/evidence/windows/preview`
- `POST/GET /api/automation/capital-scaling/evidence/windows`

They compute bounded evidence windows and an operating sample without accepting
caller-supplied result metrics. Missing sources or truncated scans block.
Current review requires v2 execution-scope provenance for every sampled order.
The process never migrates authority or contacts a broker.

## `controlled_bridge_policy`

This v1.7 allowlist exposes a local review scope but never enables submission,
cancellation, or automatic live trading.

| Field | Type | Description |
| --- | --- | --- |
| `policy_id` | string | Local id; default `default-controlled-bridge-disabled`. |
| `enabled` | boolean | Shows the review policy; still does not submit orders. |
| `allowed_connector_ids` | string[] | Read-only connectors eligible for review. |
| `allowed_account_aliases` | string[] | Sanitized aliases only. |
| `allowed_strategy_ids` | string[] | Strategies eligible for review. |
| `allowed_symbols` | string[] | Symbols eligible for review. |
| `per_order_confirmation_required` | boolean | Must be `true`. |
| `automation_allowed` | boolean | Must be `false`. |

Password, token, secret, and credential fields are rejected. Real broker facts
still enter through broker evidence and reconciliation.

## Content forbidden in `config.json`

- Full account, customer, or broker-login identifiers.
- Broker password, token, secret, or credential.
- Statement, screenshot, or real account export.
- Runtime database, market cache, or log.
- Real position, watchlist, or asset-metadata examples.

Use the SQLite runtime store, a Git-ignored local file, an explicit import
workflow, or do not retain the data at all.
