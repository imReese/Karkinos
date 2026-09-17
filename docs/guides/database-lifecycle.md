# Database preparation and recovery

The normal source commands remain `./scripts/start_server.sh dev` and
`./scripts/start_server.sh main`. Development keeps its fixed development home;
there is no sandbox manager, automatic database-per-commit, reset, or downgrade.
Uncommitted development code and appended migrations are allowed. The default
development home is intentionally separate from repository-local `data/store`.
On first use, if the default development database is absent while repository-local
state already exists, startup refuses to create a silent empty replacement; clone
or otherwise migrate that state deliberately first.

## Stable database format

Karkinos declares the completed financial persistence foundation as **Database
Format v1**. The format version is intentionally separate from the append-only
migration head: Format v1 currently ends at migration head 17. Migration numbers
are historical lineage identifiers, not product/database major versions.

Ordinary application work, refactors, UI changes, query rewrites, and data-flywheel
algorithm changes do **not** advance the migration head. A new migration is added
only when the durable persistence contract actually changes (for example a new
table/column/index/trigger, a changed database constraint, or a versioned durable
data transformation). Applied migrations remain immutable and are never renumbered
or edited. A future incompatible persistence generation would require an explicit
Database Format v2 decision rather than silently redefining Format v1.

Format v1 guarantees the foundation established through migration head 17:
immutable migration lineage, FULL/FK-aware authoritative writes, verified recovery
bundles, exact financial decimal persistence with provenance, and database-level
financial fact invariants.

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
and test fixtures. API, data-worker, and research-worker runtime initialization
validates an already-prepared database rather than applying schema changes. The
source entry point prepares once in the parent before Uvicorn or workers start.
Direct ASGI deployments must prepare their data first. A migration changed during
hot reload requires restarting through the normal launcher; reloader children
must not upgrade the live database behind the parent.

New application write connections use one explicit SQLite baseline: FULL
synchronous writes, foreign-key enforcement, and a bounded busy timeout. Schema
preparation additionally requires WAL but keeps foreign-key enforcement disabled
while replaying frozen legacy rebuilds whose historical rows predate those runtime
constraints; schema/history contracts remain the compatibility authority during
that maintenance transaction. Read-only diagnostics open with SQLite `mode=ro`
plus `query_only`, so a missing database is never created by inspection. The
effective SQLite runtime version and PRAGMAs are verified by tests; changing this
policy belongs in the shared connection module, not in individual migration code.
Existing repositories migrate to the same helper when their financial write paths
are touched rather than through a blind bulk rewrite.

When the registry and database already agree, preparation does not create another
backup/archive or repeat schema initialization. Unknown migrations, changed
checksums, inconsistent history, and schema drift stop preparation before DDL.
The existing migration registry, checksums, and structure validation remain the
compatibility authority. Never edit an already-applied migration to make a check
pass; append a corrective migration instead. The published-fund-NAV incident is
kept as a concrete compatibility example: the first applied v14 definition is
frozen under its original checksum, while the later dirty-worktree v14 variant is
accepted only by its exact known checksum and converges through the appended v15
reindex migration without rewriting either v14 ledger row.

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
  migration-registry.json  # exact evaluated migration definitions
  app.db          # present only when a previous app.db existed
  meta.db         # present only when the sibling store existed
```

The private receipt includes the exact migration definitions and checksums,
source location, available Git commit, persistence-worktree dirty status, prior
ledger, result, and backup hashes. The separately hashed registry snapshot keeps
the evaluated definitions recoverable even for uncommitted development migrations.
It does not archive environment variables,
credentials, `.env`, arbitrary working-tree diffs, or user financial data as
provenance. Database backup files naturally contain private application data:
keep the entire backup directory private and out of Git.

Backups use SQLite's backup API and include committed WAL data. Backup, registry
snapshot, or integrity failure prevents migration. Legacy schema repair, pending
migrations, preparation backfills, verification, and migration-ledger writes share
one explicit write transaction; a later failure rolls the whole preparation back.
Existing SQL text
and historical migration checksums are not rewritten by the transaction change.

Records are durable diagnostics, not an alternative migration ledger or code that
may be executed automatically. If a process exits after database commit but before
writing the final receipt, diagnosis compares the authoritative ledger with the
record's before/target histories. `target_present` describes the current match,
not proof of which process committed. Only existing digest-verified backups are
advertised as verified.

Migration-preparation backups remain narrow SQLite safety snapshots. For complete
application-state recovery use the verified recovery-bundle workflow, which captures
the selected data root, non-secret configuration identity, hashes, database identity,
and migration lineage and restores only into a new candidate workspace before replay.
Neither workflow automatically overwrites live state.

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
