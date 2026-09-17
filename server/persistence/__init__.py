"""Persistence infrastructure shared by application repositories."""

from server.persistence.database_format import DATABASE_FORMAT_VERSION
from server.persistence.migrations import (
    CURRENT_MIGRATION_HEAD,
    CURRENT_SCHEMA_VERSION,
    apply_schema_migrations,
    assert_schema_compatible,
)

__all__ = [
    "DATABASE_FORMAT_VERSION",
    "CURRENT_MIGRATION_HEAD",
    "CURRENT_SCHEMA_VERSION",
    "apply_schema_migrations",
    "assert_schema_compatible",
]
