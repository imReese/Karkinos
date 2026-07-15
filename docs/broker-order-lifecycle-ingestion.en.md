# Broker-neutral order-lifecycle evidence and collector ingestion

[中文](broker-order-lifecycle-ingestion.zh.md) | [Documentation](README.en.md)

The Stage 3.15/3.16 canonical boundary is a broker-neutral read-only evidence
chain, not a broker connection or trading authority. `provider` labels source
only. QMT, PTrade, a local file watcher, or another third-party edge may convert
facts into this contract, but none is registered by default or implied to be
officially supported by Karkinos.

## Authority boundary

- Strategy code cannot call a collector or broker adapter.
- Every command previews by default; persistence requires explicit `--record`
  plus the exact acknowledgement.
- Collector input is an operator-selected local UTF-8 JSON file. Karkinos does
  not open a broker connection, load an SDK, or poll a provider.
- Lifecycle and collector tables are append-only evidence, not write entrances
  to Account Truth, OMS, fills, ledger, risk, kill switch, capital authority,
  or interlock release.
- Submit, cancel, live, release-provider, and auto-start authority are absent by
  default.

## Stage 3.15 canonical lifecycle contract

Input schema is `karkinos.broker_order_lifecycle_export.v1`. Each snapshot
describes exactly one broker/client order identity. `source_sequence` is
globally monotonic within one provider/gateway/account-alias scope and cannot
restart per order.

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

Default maximum age is 120 seconds. Fields are strict and timestamps include a
timezone. Only a provider-scoped account hash is persisted. Order status,
cumulative filled/cancelled quantity, fill totals, weighted average, symbol,
side, and both order ids must agree. Credentials/private keys, unknown fields,
stale or malformed facts, provider/account drift, sequence regression or
conflict, and identity/contract drift all fail closed.

Preview and explicit record:

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

Canonical tables are `broker_order_lifecycle_observations`,
`broker_order_lifecycle_orders`, and `broker_order_lifecycle_fills`. An exact
observation is idempotently reused. A read-only resolver does not create a
database or table when unconfigured. A full-fill lifecycle still cannot
replace an independent broker statement, fresh Account Truth, and human
signature.

## Stage 3.16 collector batch boundary

Collector input schema is
`karkinos.broker_order_lifecycle_collector_batch.v1`. In addition to the
lifecycle it binds:

- `run_id`, `collector_id`, `deployment_id`, `collector_version`, and a
  deployment fingerprint;
- separately reviewed `release_evidence_ref` and `user_authorization_ref`;
- provider/gateway/account scope plus `callback`, `poll`, `replay`, or `fixture`
  mode;
- connection/batch state, current/next cursor, and callback
  received/deduplicated/out-of-order counts;
- one complete batch's canonical lifecycle fact.

`callback` and `poll` are labels reported by a future edge; they trigger no
provider contact. Explicit local execution:

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

Run evidence is stored in `broker_order_lifecycle_collector_runs`; cursor,
account, and deployment state in `broker_order_lifecycle_collector_state`.
Two-phase processing first prepares and persists a sanitized lifecycle
observation, then commits run/cursor state in a transaction. Restarting the same
run id between phases replays the same observation instead of creating a second
fact.

Deterministic rules:

- same run + same input is idempotent; a different run with identical evidence
  is marked duplicate;
- same cursor with different evidence, cursor regression/gap, or deployment,
  release, authorization, or account drift blocks;
- a disconnect or partial batch may be recorded as operational evidence but
  cannot advance the cursor;
- duplicate/out-of-order callback counts are recorded; one complete batch still
  creates one canonical fact;
- read/list/state operations neither connect to a provider nor create a missing
  database.

## Stage 3.17 collector runtime-evidence binding

The lifecycle resolver derives
`karkinos.broker_order_lifecycle_collector_binding.v1` from persisted run/state
tables without calling the collector or provider:

- no run in scope means `not_configured`, `required=false`; explicit offline
  import remains available;
- once a run exists, the selected lifecycle observation must trace to a matching
  recorded run; a later direct import is `unbound` and fails closed;
- prepared-but-uncommitted is `recovery_pending`; disconnect, partial, or other
  failed run is `blocked`; inconsistent run/state/provider/account/cursor
  binding is `inconsistent`;
- only a bound observation, latest valid recorded run, and consistent cursor
  state are `healthy`; a duplicate from another run cannot hide a later
  failure.

When required collector evidence is not healthy, one lifecycle blocker applies
to execution reconciliation, signed-clearance transaction, interlock, and
next-order serialization. It may reject or invalidate old clearance, but cannot
clear an order or modify collector state, OMS, fills, ledger, risk, kill switch,
or capital authority.

## Third-party adapter review gate

No broker SDK, broker-specific runtime, or support claim is added before the
user explicitly identifies the real broker environment. A future adapter needs
separate review of dependency source/license, credential isolation, read-only
capability, account binding, callback/poll semantics, disconnect/restart,
duplicate/out-of-order and partial-batch behavior, release/rollback, sanitized
logging, kill-switch visibility, and multi-day soak, followed by explicit user
authorization. Adapter review cannot also grant submit/cancel or capital
authority.

## Assumptions, validation, and risk impact

- **Assumption:** an edge collector deterministically normalizes raw provider
  events; Karkinos only validates and persists a local batch.
- **Validation:** deterministic local fixtures cover restart, idempotency,
  duplicates, out-of-order/gaps, disconnects, partial batches, callback
  telemetry, preview drift, collector binding, direct-import bypass rejection,
  clearance races, post-clearance reblocking, and database-side-effect bounds.
- **Risk impact:** new facts can only narrow or reblock execution eligibility,
  never expand authority. Incomplete, stale, conflicting, or unauthorized
  evidence fails closed.
