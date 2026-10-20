"""Composition helpers for persisted, read-only AI context capture.

Backward-compatible facade for server.services.ai_shadow.context_capture.
"""

from __future__ import annotations

from server.services.ai_shadow.context_capture import (
    build_human_context_capture_service,
    database_path,
    utc_now,
)

__all__ = [
    "build_human_context_capture_service",
    "database_path",
    "utc_now",
]
