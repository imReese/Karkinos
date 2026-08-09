# Read-Only Broker Connector Soak Runbook

This runbook operates the v1.8 Stage 1 broker-connector soak. It reads only an
explicitly configured broker-neutral local JSON export. It does not accept
broker credentials and cannot submit or cancel orders, mutate OMS or the
production ledger, or grant capital authority.

## Preconditions

1. Configure an enabled `local_export_readonly` connector with an account alias
   and local export path. No connector is registered by default.
2. Refresh the local export before each run. The only supported schema is
   `karkinos.readonly_broker_snapshot_export.v2`; legacy v1 exports fail closed.
   Each v2 export binds its connector and deployment identity, batch, cursor,
   trading day, session phase, heartbeat, and explicit completeness for cash,
   positions, orders, and fills.
3. Load provider market-calendar evidence for the trading day. A weekday is not
   assumed to be a trading day without that snapshot.
4. Keep the global kill switch available. Stage 1 does not execute orders, but
   a degraded connector or unresolved reconciliation must still be visible to
   the operator before later-stage work.

Never place broker passwords, session tokens, private keys, or raw account ids
in API requests, configuration notes, screenshots, or drill annotations.
QMT, PTrade, local-file watchers, and other provider-specific adapters are not
part of this runbook. They require a separate review and explicit user
authorization; their names do not imply Karkinos support.

## Reviewed v2 export contract

The ignored local JSON file must use this shape. Values below are synthetic;
the configured `connector_id` must exactly match the file. All timestamps must
carry a timezone, and `trading_day` is the Shanghai date of `captured_at`.

```json
{
  "schema_version": "karkinos.readonly_broker_snapshot_export.v2",
  "connector_id": "reviewed-readonly-connector",
  "source_name": "reviewed local read-only exporter",
  "account_id": "broker-local-account-reference",
  "captured_at": "2026-07-03T15:01:00+08:00",
  "health": {"status": "healthy", "checked_at": "2026-07-03T15:01:00+08:00"},
  "source_contract": {
    "deployment_identity": "reviewed-exporter-release",
    "batch_id": "immutable-batch-id",
    "cursor": {"previous": 0, "current": 1},
    "trading_day": "2026-07-03",
    "session_phase": "end_of_day",
    "heartbeat_at": "2026-07-03T15:01:00+08:00",
    "completeness": {"cash": true, "positions": true, "orders": true, "fills": true}
  },
  "cash": {"currency": "CNY", "balance": "100000.00", "available": "90000.00"},
  "positions": [],
  "orders": [],
  "fills": []
}
```

An empty array is evidence of zero facts only when the exporter actually read
the complete scope for that batch. Otherwise its completeness flag must be
`false`, which blocks soak qualification. Unknown fields, identity drift,
partial list shapes, invalid or non-finite numbers, stale heartbeat, and any
incomplete scope are blocked. The local file may contain the account reference
needed for hashing and reconciliation, but Karkinos persists only its hash in
soak evidence; never copy the raw value into API requests or repository files.

The canonical cursor uses the same consecutive form as the lifecycle
collector: the first complete batch is `{"previous":0,"current":1}` and every
new complete batch increments both values by one. A partial batch never
advances state. Exact replay reuses the original observation; cursor gaps,
out-of-order cursors, cursor/evidence conflicts, batch reuse, deployment drift,
and non-increasing source time are blocked. Sequence validation, observation
append, and cursor advance execute in one SQLite `BEGIN IMMEDIATE` transaction,
so concurrent conflicting batches cannot both become healthy evidence.
`soak_status="healthy"` by itself means only that one snapshot was readable.
It does not count as an operational soak day, pass a daily phase, or satisfy a
duplicate/restart drill. Those gates require the complete v2 source contract
and an atomically accepted sequence record. Status exposes observed healthy
days separately from sequence-accepted qualifying days.

## Daily operating sequence

| Phase | Operator action | Passing evidence | Fail-closed behavior |
| --- | --- | --- | --- |
| `startup` | Refresh the export after broker login/session initialization, then record a run. | Every configured connector produces a healthy, fresh, provider-calendar-backed observation whose v2 sequence is atomically accepted. | Missing connectors, unhealthy observations, or unaccepted sequence evidence block the run and create Operations alerts. |
| `intraday` | Refresh and record at the chosen polling/review cadence. | The same health, capability, freshness, cash, calendar, and accepted-sequence gates pass. | Stale, failed, incomplete, unsequenced, or submit-capable connectors do not count as healthy soak evidence. |
| `end_of_day` | Refresh after final order/fill facts, run execution reconciliation, then record the phase. | Every connector is healthy with accepted sequence evidence and execution reconciliation is `clear` with zero open items. | Missing/open reconciliation or unaccepted sequence evidence blocks the run; no ledger mutation is attempted. |

Record a phase with:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/automation/broker-soak/runs \
  -H 'Content-Type: application/json' \
  -d '{"phase":"startup","max_snapshot_age_seconds":900}'
```

Use `intraday` or `end_of_day` for the other phases. Review history through
`GET /api/automation/broker-soak/runs`, snapshot evidence through
`GET /api/automation/broker-soak/observations`, and aggregate coverage through
`GET /api/automation/broker-soak/status`.

## Recovery drills

One-shot drills never disconnect a broker, edit an export, restart the
application, or invoke a write capability by themselves. The operator prepares
only the local read-only condition, invokes the drill, and verifies the recorded
expected safe state. `karkinos_restart` is different: it uses an explicit
prepare/restart/complete sequence, while Karkinos still never initiates the
restart itself.

| Drill | Safe local preparation | Expected result |
| --- | --- | --- |
| `disconnect` | Temporarily make the configured local export unavailable, without changing broker settings. | A connector read failure is recorded as blocked; no broker-write contact occurs. Restore the path after evidence review. |
| `schema_drift` | Use a disposable copy of the export with an unsupported schema version. | `UnsupportedLocalJsonSnapshotSchema` and a missing v2 source contract are recorded as blocked. Restore the supported export after review. |
| `stale_data` | Use a disposable export whose `captured_at` exceeds the configured maximum age. | `snapshot_stale` is recorded as degraded and does not count as a healthy trading day. |
| `cursor_gap` | After a valid baseline, provide a disposable export whose `cursor.previous` is greater than the committed cursor. | `source_sequence_cursor_gap` is blocked and cursor state does not advance. Restore the missing next batch before continuing. |
| `cursor_out_of_order` | After at least two valid batches, provide a disposable older cursor with different evidence. | `source_sequence_cursor_out_of_order` is blocked and the committed cursor remains unchanged. |
| `partial_batch` | Provide a disposable v2 export with at least one completeness flag set to `false`. | `source_sequence_partial_batch` is blocked and the batch cannot initialize or advance the cursor. |
| `duplicate_evidence` | No destructive preparation. | Two sequential reads with accepted v2 sequence evidence resolve to the same persisted observation event; the second is marked reused. |
| `restart_recovery` | No destructive preparation. | A newly constructed service instance reuses the persisted, sequence-accepted observation. This proves application-state-independent replay, not a full operating-system or broker-terminal restart. |
| `karkinos_restart` | Prepare a checkpoint, fully stop the single Karkinos server process, keep the reviewed export unchanged, restart Karkinos, then complete the checkpoint. | Completion passes only when the runtime-instance fingerprint changed and the new instance reuses the exact persisted, sequence-accepted observation event. Same-instance completion fails. |

Run a drill with:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/automation/broker-soak/drills \
  -H 'Content-Type: application/json' \
  -d '{"drill_type":"duplicate_evidence","max_snapshot_age_seconds":900}'
```

Review persisted results through `GET /api/automation/broker-soak/drills` and
the shared Operations alert queue. A failed drill is evidence requiring manual
review; it never authorizes a retry through a broker-write path.

Run the two-stage Karkinos restart drill only against a single-worker local
server. First prepare and retain the returned `checkpoint_id`:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/automation/broker-soak/restart-checkpoints \
  -H 'Content-Type: application/json' \
  -d '{"max_snapshot_age_seconds":900}'
```

Fully stop the Karkinos process and verify that the old process has exited. Do
not refresh or edit the reviewed export between the two calls. Restart Karkinos,
then complete the exact checkpoint:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/automation/broker-soak/restart-checkpoints/complete \
  -H 'Content-Type: application/json' \
  -d '{"checkpoint_id":"<checkpoint-id>","max_snapshot_age_seconds":900}'
```

Review checkpoints with
`GET /api/automation/broker-soak/restart-checkpoints`. A pass proves a changed
Karkinos runtime-instance token plus exact persisted replay. It is corroborating
evidence, not independent proof that the old operating-system process exited:
another worker or an in-process module reload can also rotate the token. The
operator must therefore perform and record the full stop/start as written.
This drill does not restart or prove recovery of a broker terminal or external
adapter. The separate M1 `adapter_restart` evidence remains unavailable until a
reviewed real adapter exposes a versioned adapter-instance identity.

## Signed promotion review

After at least 20 trading days, review the dedicated Stage 1.1 evidence status:

```bash
curl -sS http://127.0.0.1:8000/api/automation/broker-soak/promotion/status
```

For one connector, preview the exact dossier:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/automation/broker-soak/promotion/dossiers/preview \
  -H 'Content-Type: application/json' \
  -d '{"connector_id":"<readonly-connector-id>"}'
```

The preview remains blocked unless it can select exactly 20 unique healthy
days whose v2 source contracts have atomically accepted sequence evidence and
clear, zero-open-item execution reconciliation; find passed startup, intraday,
and end-of-day runs that reference each exact selected observation id and
snapshot fingerprint; find all nine passed drills scoped exactly to that
connector; retain one stable account alias/hash; and recompute current Account
Truth as pass, fresh, and zero-unresolved. A legacy `healthy` boolean without
accepted sequence evidence cannot qualify. An unscoped drill, a drill for
another connector, or a mixed-connector drill cannot satisfy the dossier. For
each drill type, the newest matching scoped result wins, so a later failure
invalidates an older pass and any prior acceptance. The Account Truth
fingerprint changes when its import, ledger projection, reconciliation items,
or manual reviews change.

If the dossier is review-ready, request an operator-approval challenge with:

* `action="accept_broker_connector_soak_promotion"`
* `artifact_type="broker_connector_soak_promotion_dossier"`
* `artifact_fingerprint=<dossier_fingerprint>`

Sign the returned canonical payload outside Karkinos with the owner's Ed25519
private key, then submit only the challenge id and signature to the verification
endpoint. Karkinos stores the configured public key, never the private key.
Record acceptance with the resulting `operator_approval_id`, matching
`operator_label`, exact dossier fingerprint, and acknowledgement:

```text
accept_exact_readonly_soak_and_account_truth_promotion_without_execution_authority
```

Before signing, the owner must independently confirm that the Account Truth
import belongs to the same reviewed account alias, that `karkinos_restart` was
performed as a real full process stop/start, and that broker-terminal recovery
was separately exercised. `restart_recovery` proves only new-service-instance
replay. `karkinos_restart` adds a distinct runtime-instance checkpoint, but does
not independently prove operating-system process exit, broker-terminal restart,
or adapter restart.

A matching acceptance makes only the Stage 1.1 promotion-evidence status ready.
It does not enable the connector, grant capital/runtime authority, reserve
budget, change OMS/ledger state, or enable Stage 2 submission. Any source drift
requires a new preview and signature.

## Review and escalation

For every blocked run, failed drill, or reconciliation gap:

1. Preserve the observation, run/drill id, snapshot fingerprint, connector id,
   trading day, and blocker list.
2. Confirm that no raw account id or credential entered the evidence payload.
3. Restore only the local read-only input or connector process.
4. Repeat the phase or drill. Deterministic sequential reruns should reuse the
   same evidence when inputs have not changed.
5. Do not count the day toward promotion while critical cash, position, order,
   fill, freshness, schema, or reconciliation evidence remains unresolved.

Twenty healthy trading days complete only the operational soak metric. The
signed promotion dossier additionally requires clear reconciliation, full daily
phase coverage, all drills, current Account Truth, and explicit owner
assertions. Even a complete Stage 1.1 evidence record cannot enable Stage 2
submission by itself.
