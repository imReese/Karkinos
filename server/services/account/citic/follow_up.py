"""Read-only Operations projection for reviewed incomplete CITIC sources.

Backward-compatible facade for server.services.controlled_execution.citic.follow_up.
"""

from __future__ import annotations

from server.services.controlled_execution.citic.follow_up import (
    CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION,
    build_citic_source_follow_up,
)

__all__ = [
    "CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION",
    "build_citic_source_follow_up",
]
