"""Read-only display identities for verified research operation previews.

Backward-compatible facade for server.services.research.instruments.
"""

from __future__ import annotations

from server.services.research.instruments import (
    RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION,
    build_research_operation_instruments,
)

__all__ = (
    "RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION",
    "build_research_operation_instruments",
)
