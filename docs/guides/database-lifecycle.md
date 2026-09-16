# Database preparation and recovery

The normal source commands remain `./scripts/start_server.sh dev` and
`./scripts/start_server.sh main`. Development keeps its fixed development home;
there is no sandbox manager, automatic database-per-commit, reset, or downgrade.
Uncommitted development code and appended migrations are allowed.

## Startup

The source launcher prepares state in the foreground, before the API health
check deadline. A worktree target is always inspected/prepared by that target's
own Python and registry, never by the launching checkout's registry. Older target
branches without the new CLI retain their own startup behavior. Frontend build
failure does not first migrate the stable database.

`python -m server` also prepares the application database before starting
Uvicorn, its reloader, or managed workers. Managed processes hold shared database
runtime locks; preparation needs exclusive ownership. Stop all older/unmanaged
API, worker, CLI, and SQLite writers before migration. These advisory locks do
not control unrelated SQLite clients or older Karkinos processes.

`AppDatabase.init_sync()` remains an explicit preparation entry point for tools
and test fixtures. Asynchronous application/worker initialization validates an
already-prepared database rather than applying schema changes in lifespan.
Direct ASGI deployments must prepare their data first. A migration changed during
hot reload requires restarting through the normal launcher; reloader children
must not upgrade the live database behind the parent.

When the registry and database already agree, preparation does not create another
backup/archive or repeat schema initialization. Unknown migrations, changed
checksums, inconsistent history, and schema drift stop preparation before DDL.
The existing migration registry, checksums, and structure validation remain the
compatibility authority. Never edit an already-applied migration to make a check
pass; append a corrective migration instead.

## Read-only diagnosis

The following commands operate on the selected runtime environment. For the
usual development home, explicitly supply its data path when running the CLI
outside the source launcher:

```bash
KARKINOS_DATA_DIR="${KARKINOS_DEV_HOME:-$HOME/.karkinos/development}/data" \
  .venv/bin/python -m server --database-status

KARKINOS_DATA_DIR="${KARKINOS_DEV_HOME:-$HOME/.karkinos/development}/data" \
  .venv/bin/python -m server --database-status --json
```

Diagnosis never creates a missing database or runs migrations. SQLite read-only
WAL access can still use SQLite-managed sidecar/locking files; this is not a
promise that every filesystem metadata byte remains unchanged.

`--prepare-database` explicitly prepares the selected database without starting
HTTP or workers. Normal launch already invokes it; users do not need a separate
migration command for ordinary startup. The historical `--check-state` command
continues to **prepare/migrate** isolated release copies for compatibility with
existing release tooling; it is not the read-only diagnostic command.

## Backups and provenance

Preparation archives under the selected data directory:

```text
backups/schema/app.db/<run-id>/
  migration.json
  app.db          # present only when a previous app.db existed
  meta.db         # present only when the sibling store existed
```

The private JSON record includes the exact migration definitions and checksums,
source location, available Git commit, persistence-worktree dirty status, prior
ledger, result, and backup hashes. It does not archive environment variables,
credentials, `.env`, arbitrary working-tree diffs, or user financial data as
provenance. Database backup files naturally contain private application data:
keep the entire backup directory private and out of Git.

Backups use SQLite's backup API and include committed WAL data. Backup or integrity
failure prevents migration. Schema scripts and migration ledger writes run inside
an explicit transaction; initialization failure rolls it back. Existing SQL text
and historical migration checksums are not rewritten by the transaction change.

Records are durable diagnostics, not an alternative migration ledger or code that
may be executed automatically. If a process exits after database commit but before
writing the final receipt, diagnosis compares the authoritative ledger with the
record's before/target histories. `target_present` describes the current match,
not proof of which process committed. Only existing digest-verified backups are
advertised as verified.

These are SQLite-store backups, **not a complete application restore point**.
Application artifacts/configuration may need coordinated recovery as well. Existing
managed release transactions retain ownership of complete activation/rollback.
The database preparer never automatically overwrites live state from a backup.

## Recovery boundaries

Restore matching source first when a database has an unknown migration. A version
number or a migration name mentioning an index is not enough to invent its SQL or
prove backwards compatibility. Legacy databases without archived source correctly
report that provenance is unavailable.

A reviewed restore must stop all writers, preserve the current state, verify the
backup and compatible code, and account for writes made after that backup. Treat
restoring an older backup as a potentially data-losing operation; it is never an
automatic response to startup failure. Never delete migration ledger rows, lower
version numbers, rewrite checksums, or silently start on an empty replacement DB.

A known API startup failure is reported to the development supervisor even when
the reloader parent remains alive. Vite starts only after API readiness, and
failure cleanup targets only processes created by that supervisor.
