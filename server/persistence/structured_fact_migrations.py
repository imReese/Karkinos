"""Frozen v19 migration for durable structured-fact JSON contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_JSON_COLUMNS: dict[str, tuple[str, ...]] = {
    "event_log": ("payload_json",),
    "ledger_mutation_claims": ("request_json", "result_json"),
    "portfolio_mutation_claims": ("request_json", "result_json"),
    "order_state_command_claims": ("result_json",),
    "quote_ingestion_items": ("payload_json",),
}


def _json_guard(table: str, columns: tuple[str, ...]) -> str:
    invalid = " OR ".join(
        f"(NEW.{column} IS NOT NULL AND json_valid(NEW.{column}) = 0)"
        for column in columns
    )
    return f"""
    CREATE TRIGGER guard_{table}_structured_json_insert
    BEFORE INSERT ON {table}
    WHEN {invalid}
    BEGIN
        SELECT RAISE(ABORT, '{table} structured JSON required');
    END
    """


_TRIGGER_NAMES = tuple(
    f"guard_{table}_structured_json_insert" for table in _JSON_COLUMNS
)
V19_SCHEMA_OBJECTS = tuple(("trigger", name) for name in _TRIGGER_NAMES)

V19_STRUCTURED_FACT_STATEMENTS = tuple(
    _json_guard(table, columns) for table, columns in _JSON_COLUMNS.items()
)


def build_structured_fact_migration(migration_factory: Callable[..., Any]) -> Any:
    return migration_factory(
        version=19,
        name="enforce_structured_fact_json",
        statements=V19_STRUCTURED_FACT_STATEMENTS,
    )


__all__ = [
    "V19_SCHEMA_OBJECTS",
    "V19_STRUCTURED_FACT_STATEMENTS",
    "build_structured_fact_migration",
]
