# Broker Execution-Edge Conformance

[中文](broker-execution-edge-conformance.zh.md) | [Roadmap](ROADMAP.md) |
[Controlled execution](CONTROLLED_EXECUTION_PLAN.md)

## Purpose

This contract is the provider-neutral M2 foundation for testing execution-edge
semantics before any real write adapter is selected. It is separate from the
read-only [broker adapter conformance](broker-adapter-conformance.en.md) suite.

The built-in runner uses only `DeterministicFakeExecutionEdge`. It does not load
a provider SDK, read credentials, register an adapter, contact a broker, submit
or cancel a real order, or mutate OMS, Ledger, Risk, kill switch, or capital
authority. A passing report proves the Karkinos contract harness, not support
for QMT, PTrade, or any other provider.

## Contracts

`karkinos.broker_execution_edge_manifest.v1` declares one review scope:

- execution-edge, adapter, version, provider, gateway, account alias, and
  deployment identities;
- dry-run, submit, query, cancel, and idempotent client-order-id capabilities;
- mandatory boundaries including `default_registered=false` and
  `production_enabled=false`;
- ADR, capability, threat, deployment, rollback, incident, and privacy review
  references;
- limitations, never credentials.

Declaring write capabilities describes the interface to test. It does not
activate them. Unknown fields, sensitive key names, missing capabilities, or a
boundary that enables production fail closed.

`karkinos.broker_execution_edge_conformance_result.v1` binds one exact manifest
fingerprint to a fixed scenario matrix. Reports are append-only and keyed by a
unique run id. Replaying the same run is idempotent; changing the same run id is
rejected; the latest scoped failure invalidates an older pass.

## Fixed v1 matrix

| Scenario | Required result |
| --- | --- |
| capability contract | complete but default-closed |
| dry run | accepted with zero side effects |
| exact submit identity | accepted with the same order and client ids |
| definitive submit rejection | rejected without an accepted order effect |
| duplicate submit | one stored order, replay reused |
| concurrent submit | one accepted effect, one reused result |
| timeout after acceptance | explicit unknown outcome |
| unknown query | same client id resolves without resubmit |
| broker not found | blocked and submit count remains zero |
| process restart | new fixture instance queries shared evidence only |
| cancel without exact command | blocked before a cancel call |
| exact cancel | one definitive cancellation result |
| duplicate cancel | one stored cancel, replay reused |
| partial-fill/cancel race | filled and cancelled quantities remain explicit |
| query disconnect | blocked without submit fallback |

Callback duplication, callback reordering, cursor gaps, and partial batches
remain owned by the broker-order lifecycle collector conformance suite. This
keeps execution command semantics separate from lifecycle ingestion facts.

## Run locally

Previewing creates no database:

```bash
uv run python scripts/run_broker_execution_edge_conformance.py \
  --file /path/to/execution-edge-manifest.json \
  --db data/karkinos.db \
  --run-id local-execution-edge-v1
```

Recording is a separate explicit act:

```bash
uv run python scripts/run_broker_execution_edge_conformance.py \
  --file /path/to/execution-edge-manifest.json \
  --db data/karkinos.db \
  --run-id local-execution-edge-v1 \
  --record \
  --acknowledgement record_local_execution_edge_conformance_without_provider_contact_or_authority
```

Only `broker_execution_edge_conformance_reports` is created. A report cannot
register a gateway, satisfy real-provider acceptance, clear a live gate, or
grant submission/cancellation authority.

## Assumptions, validation, and risk impact

Assumptions:

- client order identity is stable across retry, timeout, and restart;
- unknown outcomes are query-only and never trigger automatic resubmission;
- cancellation is a separate exact command, never an implicit submit recovery;
- the local fake has no network or production database capability.

Deterministic validation covers strict schemas, missing/duplicate/changed
scenarios, sensitive fields, restart, idempotency, concurrency, timeout,
not-found, disconnect, cancel replay, partial-fill/cancel accounting, report
tampering, manifest drift, latest-result precedence, explicit recording, and
absence of trading-domain tables.

Risk impact is low for production because the new boundary is offline and
non-authorizing. It reduces future integration risk by making write-edge
expectations reviewable. It does not reduce the risk classification of a real
adapter: that still requires explicit owner selection, a separate ADR/threat
review, approved sandbox and failure evidence, deployment/rollback review, and
fresh human authorization. Until then no execution adapter is registered.
