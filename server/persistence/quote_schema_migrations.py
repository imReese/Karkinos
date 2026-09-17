"""Schema migration definitions for canonical current-quote materialization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# These expressions are frozen schema definitions. Pricing-policy changes that
# affect this index require a new migration, preserving historical checksums.
PUBLISHED_NAV_DATE_SQL = (
    "coalesce(nullif(nav_date, ''), date(quote_instant_utc, '+8 hours'))"
)
PUBLISHED_NAV_SQL_PREDICATE = """
    lower(trim(coalesce(quote_source, ''))) NOT IN
        ('eastmoney_fund_estimate', 'sina_fund_estimate', 'manual', 'manual_mark', 'manual_valuation')
    AND (lower(trim(coalesce(quote_status, ''))) = 'confirmed'
         OR (lower(trim(coalesce(quote_source, ''))) IN
             ('eastmoney_fund_page', 'tushare_fund_nav')
             AND lower(trim(coalesce(quote_status, 'live'))) IN
                 ('live', 'fresh', 'healthy', 'cache', 'cached', 'cache_only',
                  'cache_only_after_market_data_permission_fallback')))
"""

PUBLISHED_NAV_INDEX_SQL = f"""
    CREATE INDEX idx_quote_snapshots_published_nav_date
    ON quote_snapshots(symbol, {PUBLISHED_NAV_DATE_SQL} DESC, quote_instant_utc DESC, id DESC)
    WHERE instrument_type = 'open_end_fund' AND {PUBLISHED_NAV_SQL_PREDICATE}
"""

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
) -> tuple[Any, Any, Any]:
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
        migration_factory(
            version=14,
            name="index_published_fund_nav_marks",
            statements=(PUBLISHED_NAV_INDEX_SQL,),
        ),
    )


__all__ = ["build_quote_schema_migrations"]
