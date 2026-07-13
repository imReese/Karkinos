# Read-Only Broker Connector Soak Runbook

This runbook operates the v1.8 Stage 1 broker-connector soak. It reads only an
explicitly configured broker-neutral local JSON export. It does not accept
broker credentials and cannot submit or cancel orders, mutate OMS or the
production ledger, or grant capital authority.

## Preconditions

1. Configure an enabled `local_export_readonly` connector with an account alias
   and local export path. No connector is registered by default.
2. Refresh the local export before each run. The export must contain a supported
   schema version, source timestamp, connector health, cash, positions, orders,
   and fills.
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

## Daily operating sequence

| Phase | Operator action | Passing evidence | Fail-closed behavior |
| --- | --- | --- | --- |
| `startup` | Refresh the export after broker login/session initialization, then record a run. | Every configured connector produces a healthy, fresh, provider-calendar-backed observation. | Missing connectors or unhealthy observations block the run and create Operations alerts. |
| `intraday` | Refresh and record at the chosen polling/review cadence. | The same health, capability, freshness, cash, and calendar gates pass. | Stale, failed, incomplete, or submit-capable connectors do not count as healthy soak evidence. |
| `end_of_day` | Refresh after final order/fill facts, run execution reconciliation, then record the phase. | Every connector is healthy and execution reconciliation is `clear` with zero open items. | Missing/open reconciliation blocks the run; no ledger mutation is attempted. |

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

Drills never disconnect a broker, edit an export, restart the application, or
invoke a write capability by themselves. The operator prepares only the local
read-only condition, invokes the drill, and verifies the recorded expected safe
state.

| Drill | Safe local preparation | Expected result |
| --- | --- | --- |
| `disconnect` | Temporarily make the configured local export unavailable, without changing broker settings. | A connector read failure is recorded as blocked; no broker-write contact occurs. Restore the path after evidence review. |
| `schema_drift` | Use a disposable copy of the export with an unsupported schema version. | `UnsupportedLocalJsonSnapshotSchema` is recorded as blocked. Restore the supported export after review. |
| `stale_data` | Use a disposable export whose `captured_at` exceeds the configured maximum age. | `snapshot_stale` is recorded as degraded and does not count as a healthy trading day. |
| `duplicate_evidence` | No destructive preparation. | Two sequential reads resolve to the same persisted observation event; the second is marked reused. |
| `restart_recovery` | No destructive preparation. | A newly constructed service instance reuses the persisted observation. This proves application-state-independent replay, not a full operating-system or broker-terminal restart. |

Run a drill with:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/automation/broker-soak/drills \
  -H 'Content-Type: application/json' \
  -d '{"drill_type":"duplicate_evidence","max_snapshot_age_seconds":900}'
```

Review persisted results through `GET /api/automation/broker-soak/drills` and
the shared Operations alert queue. A failed drill is evidence requiring manual
review; it never authorizes a retry through a broker-write path.

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
days with clear, zero-open-item execution reconciliation; find passed startup,
intraday, and end-of-day runs for every selected day; find all five passed
drills; retain one stable account alias/hash; and recompute current Account
Truth as pass, fresh, and zero-unresolved. The Account Truth fingerprint changes
when its import, ledger projection, reconciliation items, or manual reviews
change.

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
import belongs to the same reviewed account alias and that a full application-
process plus broker-terminal restart/recovery exercise was actually performed.
The automatic `restart_recovery` drill proves only that a new service instance
can reuse persisted evidence; it does not prove an operating-system process or
broker-terminal restart.

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
