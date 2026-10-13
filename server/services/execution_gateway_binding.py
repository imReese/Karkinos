"""Sanitized execution-gateway identity binding without runtime authority.

Backward-compatible facade for server.services.controlled_execution.gateway.
"""

from __future__ import annotations

from server.services.controlled_execution.gateway import (
    build_execution_gateway_binding,
)

__all__ = ["build_execution_gateway_binding"]
