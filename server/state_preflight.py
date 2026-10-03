"""Provider-free compatibility preflight for cloned persistent state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from server.db import AppDatabase
from server.persistence.initializer import initialize_market_metadata_database
from server.runtime_paths import resolve_data_dir


def _require_sqlite_integrity(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("state_preflight_database_missing")
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA quick_check").fetchall()
    if result != [("ok",)]:
        raise RuntimeError("state_preflight_integrity_failed")


def preflight_persistent_state() -> None:
    """Initialize or migrate the two local SQLite stores used at startup.

    Release tooling must point ``KARKINOS_DATA_DIR`` at a disposable clone
    before invoking this function.  No application, scheduler, provider, HTTP,
    or network runtime is constructed here.
    """

    data_dir = Path(resolve_data_dir())
    AppDatabase(data_dir / "app.db").init_sync()
    initialize_market_metadata_database(data_dir / "app.db")
    _require_sqlite_integrity(data_dir / "app.db")
    _require_sqlite_integrity(data_dir / "meta.db")
