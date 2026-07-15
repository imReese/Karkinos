# Broker adapter release review

[中文](broker-adapter-release-review.zh.md) | [Conformance](broker-adapter-conformance.en.md) | [Lifecycle ingestion](broker-order-lifecycle-ingestion.en.md) | [Roadmap](ROADMAP.md)

Karkinos does not treat an adapter's own `reviewed` flag as release evidence.
A live `callback` or `poll` collector must bind an exact, persisted, accepted
`karkinos.broker_adapter_release_manifest.v1` plus its latest reviewed local
conformance report before collector preparation and again before a prepared run
is committed after restart.

This boundary is provider-neutral. It does not select a broker, install an SDK,
register an adapter, contact a provider, or grant submit, cancel, OMS, ledger,
risk, kill-switch, capital, or interlock authority.

## Manifest contract

One manifest binds a single candidate deployment:

- release, collector, deployment, version, provider, gateway, account-alias,
  deployment-fingerprint, and operator-authorization identities;
- allowed live collection modes (`callback` and/or `poll`);
- an explicit read/write capability matrix;
- process, credential, data-ownership, and default-registration boundaries;
- references to the adapter ADR, capability matrix, threat model, deployment
  runbook, rollback runbook, and privacy review;
- known limitations.

The v1 capability matrix is exact. Lifecycle ingestion requires read-order and
read-fill capability and requires submit and cancel capability to be false.
Every boundary below is also exact: runtime authentication material stays
outside canonical evidence; strategy and AI do not import the adapter; core
does not import a provider SDK; the adapter does not write OMS, production
ledger, risk, kill switch, or capital authority; and it is not registered by
default.

Unknown fields, auth-material-like keys, malformed identities, writable
capabilities, and boundary violations fail closed. The raw account id and
credentials are not part of this manifest.

## Conformance prerequisite and explicit review command

Run and explicitly record the deterministic local conformance suite first; see
[Broker adapter deterministic conformance](broker-adapter-conformance.en.md).
The suite validates Karkinos contracts only and does not approve a real
provider.

Preview is read-only and does not create the database:

```bash
uv run python scripts/review_broker_adapter_release.py \
  --file /path/to/adapter-release.json \
  --db data/store/karkinos.db
```

An operator records an append-only decision with an external reviewer/reason
reference:

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

`rejected` and `revoked` use the same command and exact manifest. Review events
are append-only. A revoked release cannot be accepted again in place; a new
release identity and a new review are required.

Canonical tables are `broker_adapter_release_manifests`,
`broker_adapter_release_review_events`, and the separate append-only
`broker_adapter_conformance_reports`. An accepted review persists the exact
conformance run and report fingerprints. Repeating the same review id and exact
decision is idempotent; reusing an id or release reference with different
evidence fails closed.

Schema initialization adds the two explicit conformance-binding columns to a
pre-conformance review table. Existing accepted rows have no such binding and
therefore remain fail-closed; record a new human review against the latest
passing report instead of treating the old row as canonical conformance.

## Collector binding

For `fixture` and `replay`, review is not required because Karkinos does not
contact a source. For live-labeled `callback` or `poll` batches:

1. the batch must still declare read-only contact and a reviewed release;
2. prepare resolves the latest persisted review and conformance report by
   `release_evidence_ref`;
3. every collector/deployment/provider/gateway/account/authorization identity
   and the collection mode must match the accepted manifest;
4. a prepared run repeats the same verification before lifecycle persistence
   and cursor commit;
5. missing, failed, rejected, revoked, tampered, or drifted review/conformance
   evidence blocks the run without creating a lifecycle fact or advancing the
   cursor;
6. a newer conformance report requires another human release review, even when
   it passes, because the previous acceptance binds an exact report.

An accepted release review is eligibility evidence only. It never registers an
adapter and cannot satisfy real-provider selection, account agreement, soak,
execution-gateway, per-order approval, reconciliation, or capital gates.

## Assumptions, validation, and risk impact

- **Assumption:** ADR, threat-model, deployment, rollback, and privacy documents
  remain external reviewed artifacts referenced by stable ids; Karkinos binds
  their review, not their prose.
- **Validation:** deterministic fixtures cover preview, sensitive/unknown
  fields, writable capabilities, explicit acceptance, rejection, revocation,
  idempotency, restart verification, deployment/authorization drift, missing
  conformance/review, and conformance-failure or revoke between prepare and
  commit.
- **Risk impact:** this gate can only block or revoke live collector ingestion.
  It does not contact a broker or change OMS, fills, ledger, risk, kill switch,
  capital authority, submission, or cancellation.
