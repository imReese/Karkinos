"""Typed state shared by controlled-session repository capabilities."""

from server.persistence.connection import SQLiteRepository


class ControlledSessionRepositoryAccess(SQLiteRepository):
    """Repository path and clock shared by controlled-session capabilities."""
