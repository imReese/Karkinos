"""Runtime construction for safe read-only broker connectors."""

from __future__ import annotations

from typing import Any

from account_truth.broker_connector import LocalJsonReadOnlyBrokerConnector

_LOCAL_EXPORT_CONNECTOR_TYPES = {"local_export_readonly"}


def build_broker_connectors(
    configured_connectors: list[Any] | tuple[Any, ...],
) -> list[Any]:
    """Turn supported local configs into runtime read-only connectors."""
    connectors: list[Any] = []
    for connector in configured_connectors or []:
        if callable(getattr(connector, "read_account_snapshot", None)):
            connectors.append(connector)
            continue
        connector_type = str(getattr(connector, "connector_type", "") or "").strip()
        if (
            bool(getattr(connector, "enabled", False))
            and connector_type in _LOCAL_EXPORT_CONNECTOR_TYPES
        ):
            connectors.append(
                LocalJsonReadOnlyBrokerConnector(
                    connector_id=str(getattr(connector, "connector_id", "") or ""),
                    snapshot_path=str(getattr(connector, "client_path", "") or ""),
                    account_alias=str(getattr(connector, "account_alias", "") or ""),
                )
            )
            continue
        connectors.append(connector)
    return connectors
