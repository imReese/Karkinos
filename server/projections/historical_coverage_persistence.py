"""Bind coverage-only evidence to the canonical read snapshot without writes."""

import sqlite3
from contextlib import ExitStack
from datetime import datetime

from server.contracts.http.historical_coverage_models import HistoricalCoverageReport
from server.dependencies import AppState
from server.persistence.database_identity import require_database_path
from server.persistence.market_price_matrix import read_historical_price_observations
from server.persistence.valuation_publication_recovery import unresolved_publications
from server.projections.portfolio_read_market_rows import read_only_connection
from server.projections.portfolio_read_snapshot import (
    PortfolioReadSnapshot,
    PortfolioReadSnapshotRejected,
)
from server.projections.portfolio_read_snapshot_persistence import (
    get_or_build_portfolio_read_snapshot,
    portfolio_read_snapshot_date_window,
    read_persisted_portfolio_snapshot_identity,
)
from server.projections.portfolio_views.historical_coverage import (
    HistoricalCoverageEvidence,
    build_historical_coverage,
)
from server.services.market_hours import get_shanghai_now


def read_historical_coverage(state: AppState) -> HistoricalCoverageReport:
    """Reject drift across app/meta reads; no initialization or unbound fallback."""
    evaluated_at = get_shanghai_now()
    if not isinstance(state, AppState):
        raise PortfolioReadSnapshotRejected(
            "coverage requires a bound application state"
        )
    path = require_database_path(
        state.db,
        PortfolioReadSnapshotRejected("coverage database unavailable"),
    )
    meta_path = path.parent / "meta.db"
    try:
        with ExitStack() as stack:
            observers = [
                stack.enter_context(read_only_connection(p)) for p in (path, meta_path)
            ]
            for connection in observers:
                connection.rollback()
            before = [_data_version(connection) for connection in observers]
            snapshot = get_or_build_portfolio_read_snapshot(state)
            with read_only_connection(path) as connection:
                connection.execute(
                    "ATTACH DATABASE ? AS market_store",
                    (f"{meta_path.resolve().as_uri()}?mode=ro",),
                )
                evidence = _read_evidence(
                    connection, snapshot, evaluated_at=evaluated_at
                )
            if read_persisted_portfolio_snapshot_identity(path) != snapshot.identity:
                raise PortfolioReadSnapshotRejected(
                    "coverage snapshot identity changed during read"
                )
            if before != [_data_version(connection) for connection in observers]:
                raise PortfolioReadSnapshotRejected(
                    "coverage evidence changed during read"
                )
            return build_historical_coverage(snapshot, evidence)
    except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
        raise PortfolioReadSnapshotRejected(
            "persisted historical coverage inputs unavailable"
        ) from exc


def _data_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA data_version").fetchone()[0])


def _read_evidence(
    connection: sqlite3.Connection,
    snapshot: PortfolioReadSnapshot,
    *,
    evaluated_at: datetime,
) -> HistoricalCoverageEvidence:
    start, end = portfolio_read_snapshot_date_window(snapshot)
    symbols = sorted(
        {str(row["symbol"]) for row in snapshot.ledger_rows if row.get("symbol")}
    )
    observations = read_historical_price_observations(
        connection, symbols=symbols, start_date=start, end_date=end
    )
    metadata = []
    for offset in range(0, len(symbols), 400):
        chunk = symbols[offset : offset + 400]
        placeholders = ",".join("?" for _ in chunk)
        metadata.extend(
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM instrument_metadata WHERE symbol IN ({placeholders}) ORDER BY symbol, asset_type",
                chunk,
            )
        )
    calendars = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM market_calendar_snapshots WHERE year BETWEEN ? AND ? ORDER BY exchange, year",
            (int(start[:4]), int(end[:4])),
        )
    ]
    return HistoricalCoverageEvidence(
        snapshot_identity=snapshot.identity,
        evaluated_at=evaluated_at,
        observations=tuple(observations),
        metadata=tuple(metadata),
        calendars=tuple(calendars),
        incidents=tuple(unresolved_publications(connection)),
    )
