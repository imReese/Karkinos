# Broker adapter deterministic conformance

[中文](broker-adapter-conformance.zh.md) | [Release review](broker-adapter-release-review.en.md) | [Lifecycle ingestion](broker-order-lifecycle-ingestion.en.md)

Karkinos requires a versioned, provider-neutral conformance report before a
candidate adapter release can be accepted. The suite is started explicitly,
runs only built-in deterministic fake/local fixtures in an isolated temporary
database, and contacts no broker or market-data provider.

This evidence proves that the current Karkinos read-only connector and Broker
Order Lifecycle ingestion contracts still fail safely. It **does not** prove
that a real broker adapter, SDK, account, network, or deployment works. A real
adapter still requires separate owner authorization, third-party review,
read-only implementation review, deployment approval, and the full 20-day
soak.

## Fixed v1 scenario matrix

The v1 suite has an exact scenario set and expected outcome:

| Area | Scenarios | Required result |
| --- | --- | --- |
| Snapshot | healthy | healthy and no submit capability |
| Snapshot | disconnected, stale, permission-limited, incomplete | blocked |
| Snapshot | unsupported schema | blocked |
| Lifecycle | same-run replay | reused |
| Lifecycle | duplicate evidence | duplicate without another fact |
| Lifecycle | out-of-order cursor | blocked |
| Lifecycle | disconnect, partial batch | blocked without cursor advance |
| Lifecycle | process restart replay | recorded once, then reused |

Missing, duplicate, unknown, or expectation-changing scenarios make a report
unrecordable. An observed result that differs from the fixed expectation is a
recordable failure, so a regression remains append-only evidence. Sensitive
fields and unknown top-level fields are rejected.

## Explicit run and record

Preview runs the suite but does not create the target evidence database:

```bash
uv run python scripts/run_broker_adapter_conformance.py \
  --file /path/to/adapter-release.json \
  --db data/store/karkinos.db \
  --run-id conformance-2026-001
```

Recording is a separate explicit action:

```bash
uv run python scripts/run_broker_adapter_conformance.py \
  --file /path/to/adapter-release.json \
  --db data/store/karkinos.db \
  --run-id conformance-2026-001 \
  --record \
  --acknowledgement \
  record_deterministic_broker_adapter_conformance_without_provider_contact_or_execution_authority
```

The append-only canonical table is
`broker_adapter_conformance_reports`. A run id is idempotent only for the exact
same report fingerprint. Reusing it with different evidence is rejected.

## Release and collector binding

An `accepted` release review resolves the latest conformance report by exact
`release_evidence_ref`, requires the report's manifest fingerprint and status
to match, and persists the conformance run/report fingerprints in the review
event. Rejection and revocation remain recordable without conformance.

Live-labeled `callback` and `poll` collector preparation and commit both
resolve the latest report again. A missing, failed, tampered, or drifted report
blocks ingestion. Even a newer passing report requires a new human release
review because the old acceptance was bound to a different report. A newer
failure therefore cannot be hidden behind an older pass.

Fixture and replay collection remain offline and do not require release
acceptance. Conformance never registers an adapter, reads runtime credentials,
contacts a provider, advances a production collector cursor, or mutates OMS,
fills, production ledger, risk, kill switch, capital authority, submit, or
cancel state.

## Assumptions, validation, and risk impact

- **Assumption:** the built-in suite validates Karkinos contracts, not a future
  third-party adapter implementation.
- **Validation:** deterministic tests cover the fixed matrix, restart,
  idempotency, duplicate, out-of-order, disconnect, partial batch, schema
  drift, sensitive/unknown fields, report tampering, latest-result precedence,
  exact re-review, and prepare/commit evidence drift.
- **Risk impact:** the new gate can only prevent release acceptance or live
  read-only lifecycle ingestion. It creates no broker-write or capital path.
