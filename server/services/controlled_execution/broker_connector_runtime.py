"""Runtime construction for safe read-only broker connectors.

Backward-compatible facade for server.services.controlled_execution.broker.
"""

from __future__ import annotations

from server.services.controlled_execution.broker import build_broker_connectors

__all__ = ["build_broker_connectors"]
