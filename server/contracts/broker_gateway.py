"""Stable contracts for the broker-neutral gateway application boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

BROKER_GATEWAY_SCHEMA_VERSION = "karkinos.broker_gateway.v1"
CONTROLLED_BRIDGE_POLICY_SCHEMA_VERSION = "karkinos.controlled_broker_bridge_policy.v1"
MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCOPE = (
    "order_id, execution_preview, ledger_entry_draft, "
    "position_cost_preview, controlled_bridge_policy, "
    "current_per_order_confirmation"
)


class BrokerGatewayPersistencePort(Protocol):
    """Minimal canonical persistence surface consumed by gateway workflows."""

    _path: Path | str

    def get_oms_order_sync(self, order_id: str) -> dict[str, Any] | None: ...

    def record_broker_gateway_event_sync(
        self,
        *,
        gateway_id: str,
        event_type: str,
        order_id: str | None = None,
        status: str = "recorded",
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def list_broker_gateway_events_sync(
        self,
        *,
        order_id: str | None = None,
        gateway_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...
