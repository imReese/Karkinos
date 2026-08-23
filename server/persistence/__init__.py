"""Persistence infrastructure shared by application repositories."""

from server.persistence.migrations import (
    CURRENT_SCHEMA_VERSION,
    apply_schema_migrations,
    assert_schema_compatible,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "apply_schema_migrations",
    "assert_schema_compatible",
]
