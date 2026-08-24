"""Frozen SQLite v1 schema initialization composition."""

from __future__ import annotations

import sqlite3

from server.persistence.schema_v1_compatibility import (
    ensure_v1_compatibility_schema,
)
from server.persistence.schema_v1_controlled_execution import (
    CONTROLLED_SUBMISSION_LEDGER_CORRECTION_TABLE_SQL,
    CONTROLLED_SUBMISSION_LEDGER_POSTING_TABLE_SQL,
    ensure_controlled_submission_clearance_terminal_schema,
)
from server.persistence.schema_v1_financial_fragments import (
    V1_FINANCIAL_SCHEMA_SQL,
)
from server.persistence.schema_v1_operational_fragments import (
    V1_OPERATIONAL_SCHEMA_SQL,
)
from server.persistence.schema_v1_reference_fragments import (
    V1_REFERENCE_SCHEMA_SQL,
)

__all__ = ["initialize_v1_baseline_schema"]

_V1_BASELINE_SCHEMA_SQL = "".join(
    (
        V1_REFERENCE_SCHEMA_SQL,
        V1_OPERATIONAL_SCHEMA_SQL,
        V1_FINANCIAL_SCHEMA_SQL,
    )
)


def initialize_v1_baseline_schema(conn: sqlite3.Connection) -> None:
    """Create the frozen v1 baseline used by legacy upgrades and verification."""

    conn.executescript(_V1_BASELINE_SCHEMA_SQL)
    ensure_controlled_submission_clearance_terminal_schema(conn)
    conn.executescript(CONTROLLED_SUBMISSION_LEDGER_POSTING_TABLE_SQL)
    conn.executescript(CONTROLLED_SUBMISSION_LEDGER_CORRECTION_TABLE_SQL)
    ensure_v1_compatibility_schema(conn)
