"""Contracts and schema constants for paper shadow execution.

Canonical module in server.services.paper_shadow.
"""

from __future__ import annotations

from server.services.paper_shadow.paper_shadow_contracts import (
    PAPER_SHADOW_EXECUTION_MODE,
    PAPER_SHADOW_INPUT_SNAPSHOT_SCHEMA_VERSION,
    PAPER_SHADOW_RUN_SCHEMA_VERSION,
    PAPER_SHADOW_SOURCE,
)

__all__ = [
    "PAPER_SHADOW_EXECUTION_MODE",
    "PAPER_SHADOW_INPUT_SNAPSHOT_SCHEMA_VERSION",
    "PAPER_SHADOW_RUN_SCHEMA_VERSION",
    "PAPER_SHADOW_SOURCE",
]
