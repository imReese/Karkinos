"""Schema migration definitions for canonical current-quote materialization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_V9_STATEMENTS = (
    """
            ALTER TABLE quote_snapshots
            ADD COLUMN quote_instant_utc TEXT
            """,
    """
            CREATE INDEX idx_quote_snapshots_identity_instant
            ON quote_snapshots(
                symbol, asset_class, quote_instant_utc DESC, id DESC
            )
            """,
    """
            CREATE INDEX idx_quote_snapshots_missing_instant
            ON quote_snapshots(id)
            WHERE quote_instant_utc IS NULL
            """,
)

_V10_BLOCKERS = (
    (
        """
                SELECT 1
                FROM quote_snapshots
                WHERE fetch_run_id IS NOT NULL
                GROUP BY fetch_run_id, symbol, asset_class
                HAVING COUNT(*) > 1
                LIMIT 1
                """,
        "quote snapshot fetch-run identity is not unique",
    ),
)

_V10_STATEMENTS = (
    """
            CREATE TABLE quote_current_materialization_state (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                snapshot_cutoff_id INTEGER NOT NULL
                    CHECK(snapshot_cutoff_id >= 0),
                revision INTEGER NOT NULL CHECK(revision >= 0),
                updated_at TEXT NOT NULL CHECK(trim(updated_at) <> '')
            )
            """,
    """
            CREATE INDEX idx_quote_snapshots_symbol_instant
            ON quote_snapshots(symbol, quote_instant_utc DESC, id DESC)
            """,
    """
            CREATE UNIQUE INDEX uq_quote_snapshots_fetch_run_identity
            ON quote_snapshots(fetch_run_id, symbol, asset_class)
            WHERE fetch_run_id IS NOT NULL
            """,
)


def build_quote_schema_migrations(
    migration_factory: Callable[..., Any],
) -> tuple[Any, Any]:
    """Build quote migrations without coupling their data to the registry type."""

    return (
        migration_factory(
            version=9,
            name="index_canonical_quote_instants",
            statements=_V9_STATEMENTS,
        ),
        migration_factory(
            version=10,
            name="checkpoint_current_quote_materialization",
            blockers=_V10_BLOCKERS,
            statements=_V10_STATEMENTS,
        ),
    )


__all__ = ["build_quote_schema_migrations"]
