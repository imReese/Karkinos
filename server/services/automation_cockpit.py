"""Read-only automation cockpit summary."""

from __future__ import annotations

from typing import Any, Callable

from server.services.automation_alerts import AutomationAlertService
from server.services.automation_control import AutomationControlService
from server.services.broker_gateway import BrokerGatewayService
from server.services.controlled_execution_operator_view import (
    ControlledExecutionOperatorViewService,
)
from server.services.current_per_order_review_projection import (
    build_current_per_order_review_summary,
)
from server.services.strategy_promotion_pipeline import StrategyPromotionPipeline

AUTOMATION_COCKPIT_SCHEMA_VERSION = "karkinos.automation_cockpit.v2"


class AutomationCockpitService:
    """Aggregate controlled automation status for a single UI surface."""

    def __init__(
        self,
        *,
        db: Any,
        trading_controls: Any | None,
        broker_connectors: list[Any] | None = None,
        account_truth_evidence_reader: Callable[[], dict[str, Any]] | None = None,
        current_per_order_dossier_reader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._db = db
        self._trading_controls = trading_controls
        self._broker_connectors = broker_connectors or []
        self._account_truth_evidence_reader = account_truth_evidence_reader
        self._current_per_order_dossier_reader = current_per_order_dossier_reader

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
        connector_registrations = _registered_connector_contracts(
            self._broker_connectors
        )
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
            "connector_registrations": connector_registrations,
            "controlled_execution": ControlledExecutionOperatorViewService(
                db=self._db,
                account_truth_evidence_reader=self._account_truth_evidence_reader,
            ).summary(),
            "current_per_order_reviews": build_current_per_order_review_summary(
                self._current_per_order_dossier_reader
            ),
            "open_alert_count": len(open_alerts),
            "open_alerts": open_alerts,
            "recent_runs": recent_runs,
            "promotion_states": promotion_states,
            "execution_reconciliation_open_items": reconciliation_items,
            "limitations": [
                "Cockpit summary is read-only and does not submit broker orders.",
                "Cockpit GET reads persisted facts only and never queries a provider connector.",
                "Provider snapshots enter through an explicitly started ingestion boundary.",
                "Current per-order review is non-submitting and projects only persisted evidence.",
            ],
        }


def _registered_connector_contracts(
    connectors: list[Any],
) -> list[dict[str, Any]]:
    """Describe explicit registrations without calling an adapter method."""
    return [
        {
            "connector_id": str(
                getattr(connector, "connector_id", "") or connector.__class__.__name__
            ),
            "connector_type": str(
                getattr(connector, "connector_type", "") or "edge_adapter"
            ),
            "registration_status": "registered_unqueried",
            "provider_contact_performed": False,
            "explicit_ingestion_required": True,
            "can_submit_orders": False,
            "can_cancel_orders": False,
        }
        for connector in connectors
    ]
