# Karkinos scripts

Run repository commands from the repository root. The top-level scripts are the
ordinary lifecycle interface:

```bash
./scripts/start_server.sh       # source development
./scripts/start_server.sh prod  # selected immutable production release
./scripts/stop_server.sh        # stop exact tracked development services
./scripts/stop_server.sh prod   # stop the supervised production service
./scripts/stop_server.sh all    # explicitly stop both
```

Everything below a subdirectory is a specialized owner/operator, maintenance,
CI, or internal implementation command. Canonical financial and safety logic
remains in application packages such as `data`, `account_truth`, `analytics`,
and `server`.

## Service lifecycle

| Command | Purpose | Boundary |
| --- | --- | --- |
| `./scripts/start_server.sh` or `./scripts/start_server.sh dev` | Start the current source tree: reloadable backend on `127.0.0.1:8001` plus Vite on `127.0.0.1:5173`. | Isolated from stable production on port 8000. Writes only source-worktree PID/log state and may install missing frontend dependencies. |
| `./scripts/start_server.sh prod` | Start the supervised immutable release already selected by `~/Library/Application Support/Karkinos/current`. | Never builds from the checkout, copies source into a release, updates `current`, or falls back to source execution. It fails closed when no valid packaged controller exists. |
| `./scripts/stop_server.sh` or `./scripts/stop_server.sh dev` | Stop only the exact tracked development processes. | Symmetric with the default development start and never touches production. |
| `./scripts/stop_server.sh prod` | Stop only the exact supervised production service. | Uses the packaged controller and persisted service port; it does not kill unknown listeners or sweep ports. |
| `./scripts/stop_server.sh all` | Explicitly stop both development and production. | Validates recorded PID, process command, and start identity for every target. |

Bootstrap records the production port once in the private managed-runtime
receipt (`.service-config.json`), defaulting to 8000. Updates, rollback,
recovery, status, start, and stop reuse that value automatically. The wrappers
only pass `KARKINOS_BACKEND_PORT` when it is explicitly set; a value that does
not match the receipt fails closed instead of silently moving the service to a
different port. To bootstrap on a non-default port, pass `--service-port` once
or set `KARKINOS_BACKEND_PORT` for that bootstrap command.

The live scheduler always starts with every backend and has no service-level off
switch. Its liveness is required before startup succeeds. Automatic trading is
a different, default-off runtime gate on the Trading page; an operator can open
or close it without restarting the service. That gate grants no capital or
broker authority by itself, and automatic broker submission is not implemented.

Set `KARKINOS_LOG_MAX_BYTES` to a positive byte count to change the default
20 MiB development-log archive threshold. Archives remain under `logs/`; the
start script does not delete them.

## Immutable native release workflow

The production runtime has one mutable root and immutable release directories:

```text
~/Library/Application Support/Karkinos/
  current  -> releases/sha-<40-hex-commit>
  previous -> releases/sha-<40-hex-commit>
  releases/
  data/
  config/
  logs/
  .service-config.json  # private persisted production-port receipt
```

The native macOS artifact is built by CI with a locked Python runtime and
`web/dist`. Downloaded bytes are accepted only after architecture, checksum,
manifest identity, Release metadata/digest where applicable, and GitHub
build-provenance attestation agree. Native production neither requires nor uses
a local Docker service, local `web/dist`, or a build from the source checkout.

For the companion container image, the candidate manifest's OCI digest is the
authoritative immutable identity. SemVer and `sha-*` tags are treated as
write-once by the release workflow, but GHCR does not expose repository-owned
tag-immutability enforcement here; access to package-write credentials remains
an external administrative control.

After the one-time bootstrap, use the packaged controller. These commands do
not require a source checkout:

```bash
KARKINOS_CTL="$HOME/Library/Application Support/Karkinos/current/bin/karkinosctl"
"$KARKINOS_CTL" status
"$KARKINOS_CTL" service-start
"$KARKINOS_CTL" service-stop
```

The repository wrappers are convenience adapters: `./scripts/start_server.sh
prod` delegates to `service-start`, and `./scripts/stop_server.sh prod`
delegates to `service-stop`. `status` probes the persisted port and reports the
exact HTTP release identity, scheduler state, and any retained recovery journal;
it does not claim financial readiness.

### Test an exact candidate without a tag

Before the first stable bootstrap there is no packaged `current` controller.
From the repository checkout, the supported pre-bootstrap candidate entry is:

```bash
SHA=0123456789abcdef0123456789abcdef01234567
UV_CACHE_DIR=.uv-cache uv run python scripts/release/manage_release.py \
  candidate --commit-sha "$SHA"
```

This source command is only a verifier/launcher for disposable candidate bytes;
it cannot select a production pointer. After bootstrap, use the packaged
controller instead. Authenticate `gh` (or provide `GH_TOKEN` without putting it
in an argument), then pass the full lowercase 40-hex commit from the candidate
CI run:

```bash
SHA=0123456789abcdef0123456789abcdef01234567
"$KARKINOS_CTL" candidate --commit-sha "$SHA"
```

The command fetches and verifies that exact Actions artifact, stages it, and
runs it in the foreground on `127.0.0.1:18000` by default with disposable `data/`,
`config/`, and `logs/`. It never points `current` or `previous` at the candidate
and discards the staged candidate when the run exits or fails. A Git tag is not
required for this validation. If production itself is configured on 18000, the
implicit candidate port becomes 18001; an explicit `--port` equal to the
persisted production port fails closed. If the same commit has been rebuilt or rerun, the
fetcher selects the latest completed successful official `main` Release
Candidate run attempt, then binds its run id, run attempt, artifact id, artifact digest,
and manifest identity in `candidate-selection.json`; artifacts from older
attempts do not make the result ambiguous. A changing or incomplete Actions
listing fails closed. Manual dispatch must use the exact commit selected as the
workflow ref because GitHub provenance binds that immutable workflow SHA.

### Install a published stable release

A stable update requires authenticated GitHub CLI access and a published,
non-draft, non-prerelease strict SemVer tag such as `v0.3.2`; tags are stable
release markers, not candidate-test prerequisites:

```bash
TAG=v0.3.2
"$KARKINOS_CTL" update --tag "$TAG" --confirm "UPDATE $TAG"
```

The update verifies that the tag, Release, asset digest, archive, checksum,
manifest, attested workflow, and exact commit agree. It then locks the runtime,
probes the artifact with disposable state, stops production, snapshots the real
mutable state, runs the target's provider-free state preflight on a clone,
atomically switches `current`, starts the service, and verifies exact version,
commit SHA, artifact fingerprint, process health, and scheduler liveness.
It then keeps the durable journal and unsafe HTTP guard in place, opens only the
scheduler gate in an explicit readiness phase, and requires at least one
completed loop iteration or initialized-idle pass before committing. A failed
post-guard iteration therefore rolls back instead of being discovered after
the journal has already been cleared.

`v0.3.2` is the activation-protocol floor for this managed updater. Native
manifests bind `release_control_protocol=1`; an installed controller accepts
only that exact protocol. Use `v0.3.4` or newer for the one-time legacy
bootstrap so the controller reuses the installer's downloaded archive and
authenticated GitHub session. A future activation-protocol change must bump the
value and ship an explicit target-controller handoff/bootstrap path, so an
older updater fails closed instead of silently applying newer bytes with
obsolete transaction semantics.
An activation failure restores the saved mutable state and old pointers before
restarting the old release. If recovery itself is inconclusive, the durable
journal is retained and later mutations fail closed for explicit recovery.

`status` reports `recovery.required=true` and the retained phase. Recover with
the exact fixed acknowledgement:

```bash
"$KARKINOS_CTL" recover --confirm "RECOVER RELEASE STATE"
```

If an interrupted switch left `current` absent, execute the same command with
the still-validated `previous/bin/karkinosctl`. If neither pointer provides an
executable controller, stop and retrieve the exact attested controller for the
journal's release; do not guess a release directory or clear the journal.

After a successful update, only `current` and `previous` remain under
`releases/`; older versions remain downloadable from GitHub. `current` is the
running stable version and `previous` is the single local rollback target.
Restarting with `./scripts/start_server.sh prod` never changes either pointer.

Inspect `previous` with `status`, then roll back with its exact SHA:

```bash
"$KARKINOS_CTL" rollback \
  --confirm "ROLLBACK <previous-40-hex-commit>"
```

### One-time migration from the legacy source service

When production still uses the old source-based LaunchAgent and has no managed
`current`/`previous`, obtain and externally verify the stable Release asset
`bootstrap_installer.sh`. Its tracked source is
`scripts/release/bootstrap_installer.sh`; obtain and verify the published copy
as described in
[`scripts/release/BOOTSTRAP_INSTALLER.md`](release/BOOTSTRAP_INSTALLER.md).
Then run the one-time handoff without executing release tooling from the source
checkout:

```bash
TAG=v0.3.6
"$BOOTSTRAP_DOWNLOAD_DIR/bootstrap_installer.sh" \
  --tag "$TAG" \
  --legacy-workdir "/absolute/path/to/Karkinos" \
  --legacy-plist "$HOME/Library/LaunchAgents/com.karkinos.daily-candidate.plist" \
  --confirm "BOOTSTRAP $TAG"
```

The standalone entry point validates the local path shape before retrieving its
attested packaged controller. Before that controller performs the complete
release verification, bootstrap validates the exact owner-selected LaunchAgent,
legacy source state, managed-root layout, and the old `releases/prod` inventory.
It verifies the stable artifact, snapshots `.env`, `config.json`, and
`data/store`, checks them with the new runtime, moves mutable state into the
managed `config/` and `data/` directories, switches to immutable `current`, and
requires exact production health and scheduler identity. Any ordinary failure
restores the legacy files, plist, service, and release layout. A successful
bootstrap uses the same journaled scheduler-readiness proof before commit and
deliberately retains an exact legacy quarantine for rollback review.

After observing the new service and checking the production audit, delete only
that validated quarantine with:

```bash
"$KARKINOS_CTL" finalize-bootstrap \
  --confirm "FINALIZE LEGACY BOOTSTRAP"
```

Finalization is explicit and irreversible; it first requires the exact current
release to remain healthy. Do not finalize merely because bootstrap returned
success.

### Internal release and service mechanics

`scripts/service/manage_launch_agent.sh` is the locked service-manager backend.
Do not call its `install`, `restart`, or `uninstall` mutations directly; use
`./scripts/start_server.sh prod`, `./scripts/stop_server.sh prod`, or the packaged
controller so release locking and exact identity checks cannot be bypassed.

`scripts/release/manage_release.py` is the controller. Its public workflows are
`candidate`, `update`, `bootstrap`, `rollback`, `recover`,
`finalize-bootstrap`, `status`, `service-start`, and `service-stop`. Local
`stage`, `discard`, `promote`, `prune`, `adopt-legacy`, `bootstrap-legacy`,
`run-candidate`, and `download` helpers are Python implementation details and
are deliberately not CLI commands: a self-consistent local archive is not
stable-release authorization and cannot enter production through the packaged
controller.
`scripts/release/update_workflow.py` and
`scripts/release/bootstrap_legacy.py` are internal modules and are not invoked
directly.

## Owner/operator helpers

| Command | Purpose | Local writes or external contact |
| --- | --- | --- |
| `uv run python scripts/service/audit_daily_candidate_production.py --pretty` | Read the running local service's exact financial preflight, monitor, five-round research policy, 20-day / 50-order trial, and compact dependency-ordered operator checklist into one sanitized readiness report. | Loopback GET only; no provider/broker contact or database write. Exit `0` means ready to continue bounded forward paper/shadow collection, not GO, profit, execution, or capital authority; exit `2` is fail-closed non-ready. |
| `uv run python scripts/data/configure_data_source.py` | Owner-facing, occasional local setup helper for selecting AKShare or Tushare. It is not an internal service hook and is not needed for routine start/stop. | Updates the explicitly selected ignored `config.json` and `.env`; Tushare tokens are entered interactively and never accepted as CLI arguments. It does not restart the service. |
| `python scripts/service/repair_legacy_fund_trade_duplicates.py` | Exceptional legacy-data repair, not an ordinary user command. Preview first and use only for the narrowly scoped duplicate correction. | Requires its explicit acknowledgement; remains provider-free and does not submit orders, change capital authority, or silently rewrite unrelated ledger facts. |

For managed production paths, pass them explicitly to the setup helper and then
restart only if the changed configuration requires it:

```bash
uv run python scripts/data/configure_data_source.py \
  --config-path "$HOME/Library/Application Support/Karkinos/config/config.json" \
  --env-file "$HOME/Library/Application Support/Karkinos/config/.env"
```

## Market-data maintenance

| Command | Purpose | Safety boundary |
| --- | --- | --- |
| `uv run python scripts/data/sync_market_bars_to_db.py` | Import existing Parquet bar mirrors into `data/store/meta.db.market_bars`. | Does not fetch remote data. It updates the selected local `DataStore`. |
| `uv run python scripts/data/verify_market_bars.py --symbol SYMBOL --start YYYY-MM-DD --end YYYY-MM-DD` | Fetch one provider range and compare it with persisted local bars. | Contacts the selected market-data provider but does not overwrite local bars. |

These commands maintain or verify historical bars. They do not start the live
quote scheduler.

## Broker evidence and compatibility

| Command | Purpose |
| --- | --- |
| `uv run python scripts/broker/preview_citic_history_xls.py --path FILE_OR_DIRECTORY` | Privacy-minimized, read-only schema and evidence-gap preview for local CITIC `历史成交` legacy XLS exports. It never prints event/account values or persists evidence. |
| `uv run python scripts/broker/import_broker_order_lifecycle.py --file FILE` | Validate one broker-neutral exact-order lifecycle export. |
| `uv run python scripts/broker/ingest_broker_order_lifecycle_collector_batch.py --file FILE` | Validate one broker-neutral collector batch and its cursor transition. |
| `uv run python scripts/broker/migrate_legacy_qmt_order_lifecycle.py --file FILE` | Explicitly convert the retired QMT v1 export schema into the canonical broker-neutral schema. It does not import the QMT SDK or contact a broker. |

The CITIC history command is preview-only and deliberately remains blocked
until itemized settlement components plus cash and position snapshots are
supplied through separately reviewed evidence. Preview is the default for the
other three commands. Persistence requires `--record`
and the exact acknowledgement printed by the command contract. Recording only
stores validated evidence; it does not submit or cancel orders, mutate the
production ledger, or grant execution authority.

The retired `scripts/broker/import_qmt_order_lifecycle.py` compatibility entry point
was removed. Use the explicit migration command for old QMT exports or the
canonical import command for current broker-neutral exports.

## Broker release validation and operator approval

| Command | Purpose |
| --- | --- |
| `uv run python scripts/broker/review_broker_adapter_release.py --file FILE --db DB` | Preview or explicitly record an adapter release decision. |
| `uv run python scripts/broker/run_broker_adapter_conformance.py --file FILE --db DB --run-id ID` | Run deterministic provider-neutral adapter fixtures. |
| `uv run python scripts/broker/run_broker_execution_edge_conformance.py --file FILE --db DB --run-id ID` | Run deterministic submit/query/cancel boundary fixtures without contacting a broker. |
| `uv run python scripts/broker/operator_signer.py init ...` | Create a local Ed25519 private key and print its public configuration fragment. |
| `uv run python scripts/broker/operator_signer.py sign ...` | Validate and sign one short-lived canonical challenge read from standard input. |

`operator_signer.py` never calls the Karkinos API or edits `config.json`. Keep
the private key outside the repository with permissions `0600` or stricter.

## CI and release checks

| Command | Purpose |
| --- | --- |
| `uv run python scripts/ci/check_docs_health.py` | Check core documentation budgets, local links, language pairs, and roadmap/test separation. |
| `uv run python scripts/ci/export_acceptance_audit.py --audit all` | Export acceptance manifests and optionally bind deterministic test evidence. |
| `uv run python scripts/ci/verify_docker_runtime.py` | Confirm a built container starts with the live scheduler running while broker and capital authority remain disabled. |

Do not delete or rename CI entry points without updating their workflow,
acceptance-registry, documentation, and test consumers.
