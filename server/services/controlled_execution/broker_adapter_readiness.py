"""Persisted-only operator projection for broker adapter evidence readiness.

Backward-compatible facade for server.services.controlled_execution.broker.
"""

from __future__ import annotations

from server.services.controlled_execution.broker import (
    BROKER_ADAPTER_READINESS_SCHEMA_VERSION,
    BrokerAdapterReadinessService,
    build_broker_adapter_readiness,
)

__all__ = [
    "BROKER_ADAPTER_READINESS_SCHEMA_VERSION",
    "BrokerAdapterReadinessService",
    "build_broker_adapter_readiness",
]
