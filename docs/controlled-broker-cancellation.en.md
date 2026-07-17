# Controlled Broker Cancellation

[中文](controlled-broker-cancellation.zh.md) | [Architecture](ARCHITECTURE.md) | [Roadmap](ROADMAP.md)

## Scope

`karkinos.controlled_broker_cancellation.v1` is Karkinos's provider-neutral,
one-shot cancellation command for an already submitted controlled order. It is
an execution-edge safety contract, not a claim that any real broker adapter is
installed, reviewed, registered, or supported.

The production factory remains disabled unless the owner separately provides:

- one explicitly reviewed execution gateway;
- a current signed `manual_each_order` release for the exact gateway and
  account alias;
- a trusted local Ed25519 operator identity;
- an exact submitted controlled intent and current persisted lifecycle
  evidence with remaining quantity.

There is no QMT, PTrade, or other provider-specific dependency in this
contract. Strategy code and AI cannot call it.

## Command flow

```text
persisted controlled intent + OMS order
+ latest exact broker lifecycle observation
+ current signed release + cached gateway health
-> read-only cancellation preview
-> short-lived offline signature over the exact fingerprint
-> BEGIN IMMEDIATE claim and evidence recheck
-> at most one gateway cancel call
-> sanitized non-authoritative command result
-> explicit newer lifecycle ingestion
-> reconciliation / Account Truth review
```

Preview binds the submit fingerprint, OMS order fingerprint, provider,
gateway/account/broker/client identities, lifecycle observation and evidence
fingerprints, source sequence, order/filled/cancelled/remaining quantities,
release fingerprint, gateway-health fingerprint, and operator identity.

The final command requires:

- action `cancel_exact_controlled_broker_order`;
- artifact type `controlled_broker_cancellation`;
- acknowledgement `request_one_exact_broker_cancellation_once`;
- an unexpired proof from the configured public-key identity.

An exact retry returns the persisted command without another external call.
A conflicting retry fails closed. Concurrent calls and process restart cannot
produce a second cancel effect.

## Result semantics

The persisted command state is one of:

- `prepared`: the external effect was claimed, but finalization may not have
  completed;
- `cancel_requested`: an exact gateway response was received;
- `cancel_rejected`: Karkinos knows no gateway call occurred or the gateway
  returned an exact definitive rejection;
- `cancellation_unknown`: the call or response identity is ambiguous.

None of these states proves broker cancellation. Even a gateway response named
`cancelled` remains sanitized edge telemetry until a newer lifecycle
observation is explicitly ingested and reconciled. The command never updates
OMS, canonical lifecycle, fills, ledger, risk, kill switch, interlock, or
capital authority.

The kill switch blocks new submissions. It does not silently create cancel
authority, but it also does not block an otherwise fully reviewed,
independently signed risk-reducing cancellation command.

## Query-only recovery

`karkinos.controlled_broker_cancellation_recovery.v1` handles `prepared`,
requested, rejected, or unknown command outcomes without re-cancelling.
Recovery requires another exact offline signature:

- action `query_exact_broker_cancellation_outcome`;
- artifact type `controlled_broker_cancellation_recovery`;
- acknowledgement
  `query_exact_broker_cancellation_outcome_once_without_recancel`.

After a deterministic 30-second wait, an atomic claim permits at most one
query for that signed recovery fingerprint. Duplicate/restart replay reuses the
claim. Query output is sanitized and remains non-authoritative; newer persisted
lifecycle evidence is still required.

## API boundary

The controlled-submission router exposes explicit status, preview, command,
history, and query-recovery endpoints under
`/api/automation/controlled-broker-submission`. Pydantic models reject unknown
fields, including credentials. Preview and history never contact a broker.
There is intentionally no Strategy or AI route and no automatic retry.

The existing manual cancellation ticket remains the zero-broker-contact
fallback. When a gateway or signed release is missing, stale, unhealthy,
revoked, or unreviewed, the signed command stays blocked and the operator must
use a separately reviewed broker interface plus explicit evidence ingestion.

## Deterministic validation

```bash
uv run pytest tests/test_controlled_broker_cancellation.py -q
uv run pytest tests/server/test_controlled_broker_submission_routes.py -k cancellation -q
uv run pytest tests/test_operator_approval.py tests/test_acceptance_audit.py -q
```

Tests use a deterministic local fake only. They cover default closure, exact
signature domains, lifecycle drift, remaining quantity, concurrency,
idempotent replay, restart from `prepared`, timeout/unknown, definitive
rejection, query-only recovery, kill-switch behavior, secret sanitization, and
the no-OMS/no-ledger/no-authority boundary.
