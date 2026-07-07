"""Read-only automation cockpit summary."""

from __future__ import annotations

from typing import Any

from server.services.automation_alerts import AutomationAlertService
from server.services.automation_control import AutomationControlService
from server.services.broker_gateway import BrokerGatewayService
from server.services.strategy_promotion_pipeline import StrategyPromotionPipeline

AUTOMATION_COCKPIT_SCHEMA_VERSION = "karkinos.automation_cockpit.v1"


class AutomationCockpitService:
    """Aggregate controlled automation status for a single UI surface."""

    def __init__(
        self,
        *,
        db: Any,
        trading_controls: Any | None,
        broker_connectors: list[Any] | None = None,
    ) -> None:
        self._db = db
        self._trading_controls = trading_controls
        self._broker_connectors = broker_connectors or []

    def summary(self) -> dict[str, Any]:
        automation_status = AutomationControlService(
            db=self._db,
            trading_controls=self._trading_controls,
        ).get_status()
        broker_gateway = BrokerGatewayService(
            db=self._db,
            broker_connectors=self._broker_connectors,
        )
        gateways = broker_gateway.list_gateways()
        runtime_connector_snapshots = _runtime_connector_snapshots(broker_gateway)
        open_alerts = AutomationAlertService(
            db=self._db,
            trading_controls=self._trading_controls,
        ).list_alerts(status="open")
        recent_runs = self._db.list_automation_runs_sync(limit=20)
        promotion_states = StrategyPromotionPipeline(db=self._db).list_states()
        reconciliation_items = self._db.list_execution_reconciliation_open_items_sync(
            limit=50
        )
        return {
            "schema_version": AUTOMATION_COCKPIT_SCHEMA_VERSION,
            "broker_submission_enabled": False,
            "automation_status": automation_status,
            "gateways": gateways,
            "runtime_connector_snapshots": runtime_connector_snapshots,
            "open_alert_count": len(open_alerts),
            "open_alerts": open_alerts,
            "recent_runs": recent_runs,
            "promotion_states": promotion_states,
            "execution_reconciliation_open_items": reconciliation_items,
            "limitations": [
                "Cockpit summary is read-only and does not submit broker orders.",
            ],
        }


def _runtime_connector_snapshots(
    broker_gateway: BrokerGatewayService,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for connector_health in broker_gateway.list_connector_health():
        if (
            connector_health.get("capability_scope")
            != "runtime_readonly_connector_snapshot"
        ):
            continue
        connector_id = str(connector_health.get("connector_id") or "").strip()
        if not connector_id:
            continue
        try:
            snapshots.append(broker_gateway.query_connector_snapshot(connector_id))
        except Exception as exc:  # pragma: no cover - defensive cockpit boundary
            snapshots.append(
                {
                    "schema_version": "karkinos.broker_gateway.v1",
                    "gateway_id": "read_only_connector",
                    "status": "snapshot_unavailable",
                    "query_scope": "runtime_readonly_connector_snapshot",
                    "connector_id": connector_id,
                    "connector_health": connector_health,
                    "submitted_to_broker": False,
                    "can_submit_orders": False,
                    "stores_credentials": False,
                    "does_not_mutate_oms": True,
                    "does_not_mutate_production_ledger": True,
                    "last_error": str(exc),
                    "limitations": [
                        "Runtime connector snapshot query failed; review connector health manually.",
                        "No broker order was submitted or cancelled.",
                    ],
                }
            )
    return snapshots
