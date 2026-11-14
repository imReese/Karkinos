"""Server-side broker gateway boundary for OMS orders."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from account_truth.broker_evidence import BrokerEvidenceRepository
from server.contracts.broker_gateway import (
    BROKER_GATEWAY_SCHEMA_VERSION,
    CONTROLLED_BRIDGE_POLICY_SCHEMA_VERSION,
    MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCOPE,
)
from server.contracts.broker_gateway import (
    BrokerGatewayPersistencePort as _BrokerGatewayPersistencePort,
)
from server.services.controlled_execution.broker_gateway_gates import (
    BrokerGatewayGateMixin as _BrokerGatewayGateMixin,
)
from server.services.controlled_execution.broker_gateway_queries import (
    BrokerGatewayQueryMixin as _BrokerGatewayQueryMixin,
)
from server.services.controlled_execution.broker_gateway_values import (
    CONTROLLED_BRIDGE_REQUIRED_GATES as _CONTROLLED_BRIDGE_REQUIRED_GATES,
)
from server.services.controlled_execution.broker_lifecycle_evidence_view import (
    BrokerLifecycleEvidenceViewService,
)
from server.services.controlled_execution.oms import OmsService
from server.services.manual_trading import ManualTradingService
from server.services.risk.trading_controls import (
    resolve_kill_switch_evidence,
)


class BrokerGatewayService(
    _BrokerGatewayQueryMixin,
    _BrokerGatewayGateMixin,
):
    """Expose safe broker gateway capabilities and manual-ticket execution."""

    def __init__(
        self,
        *,
        db: Any,
        broker_connectors: list[Any] | None = None,
        controlled_bridge_policy: Any | None = None,
        trading_controls: Any | None = None,
        current_per_order_confirmation_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
    ) -> None:
        self._db: _BrokerGatewayPersistencePort = db
        self._oms = OmsService(db=db)
        self._broker_connectors = broker_connectors or []
        self._controlled_bridge_policy = controlled_bridge_policy
        self._trading_controls = trading_controls
        self._current_per_order_confirmation_provider = (
            current_per_order_confirmation_provider
        )
        self._manual_trading = ManualTradingService(
            db=db,
            oms=self._oms,
            controlled_bridge_policy=controlled_bridge_policy,
            trading_controls=trading_controls,
            current_per_order_confirmation_provider=(
                current_per_order_confirmation_provider
            ),
        )

    def preview_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        return self._manual_trading.preview_manual_ticket(order_id, actor=actor)

    def export_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        return self._manual_trading.export_manual_ticket(order_id, actor=actor)

    def dry_run_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        return self._manual_trading.dry_run_manual_ticket(order_id, actor=actor)

    def create_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        return self._manual_trading.create_manual_ticket(order_id, actor=actor)

    def preview_manual_execution_record(
        self,
        order_id: str,
        *,
        fill_price: Any,
        quantity: Any,
        fee: Any = None,
        tax: Any = None,
        transfer_fee: Any = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        return self._manual_trading.preview_manual_execution_record(
            order_id,
            fill_price=fill_price,
            quantity=quantity,
            fee=fee,
            tax=tax,
            transfer_fee=transfer_fee,
            actor=actor,
        )

    def record_manual_execution_evidence(
        self,
        order_id: str,
        *,
        fill_price: Any,
        quantity: Any,
        preview_fingerprint: str,
        fee: Any = None,
        tax: Any = None,
        transfer_fee: Any = None,
        actor: str | None = None,
        operator_note: str | None = None,
    ) -> dict[str, Any]:
        return self._manual_trading.record_manual_execution_evidence(
            order_id,
            fill_price=fill_price,
            quantity=quantity,
            preview_fingerprint=preview_fingerprint,
            fee=fee,
            tax=tax,
            transfer_fee=transfer_fee,
            actor=actor,
            operator_note=operator_note,
        )

    def submit_live_disabled(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order = self._require_order(order_id)
        self._db.record_broker_gateway_event_sync(
            gateway_id="live_disabled",
            event_type="live_submission_rejected",
            order_id=order_id,
            status="rejected",
            actor=actor,
            payload={
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "order_status": order["status"],
                "submitted_to_broker": False,
            },
        )
        raise ValueError("live broker submission is disabled")

    def cancel_live_disabled(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order = self._require_order(order_id)
        self._db.record_broker_gateway_event_sync(
            gateway_id="live_disabled",
            event_type="live_cancel_rejected",
            order_id=order_id,
            status="rejected",
            actor=actor,
            payload={
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "order_status": order["status"],
                "submitted_to_broker": False,
                "cancelled_at_broker": False,
            },
        )
        raise ValueError("live broker cancellation is disabled")

    def get_status(self) -> dict[str, Any]:
        kill_switch = self._kill_switch_snapshot()
        return {
            "schema_version": "karkinos.broker_gateway_status.v1",
            "broker_submission_enabled": False,
            "kill_switch_status": kill_switch["status"],
            "kill_switch_enabled": kill_switch["enabled"],
            "kill_switch_reason": kill_switch["reason"],
            "kill_switch_updated_at": kill_switch["updated_at"],
            "kill_switch_evidence_available": kill_switch["evidence_available"],
            "kill_switch_blockers": list(kill_switch["blockers"]),
            "controlled_bridge_policy": self._controlled_bridge_policy_snapshot(),
            "gateways": self.list_gateways(kill_switch=kill_switch),
        }

    def list_gateways(
        self,
        *,
        kill_switch: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if kill_switch is None:
            kill_switch = self._kill_switch_snapshot()
        manual_ticket_blocked = kill_switch["status"] != "pass"
        manual_ticket_status = "available"
        if kill_switch["status"] == "blocked":
            manual_ticket_status = "blocked_by_kill_switch"
        elif kill_switch["status"] == "unavailable":
            manual_ticket_status = "blocked_by_trading_controls_unavailable"
        return [
            {
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "gateway_id": "manual_ticket",
                "display_name": "Manual broker ticket",
                "status": manual_ticket_status,
                "is_live": False,
                "can_read_account_facts": False,
                "can_preview_orders": not manual_ticket_blocked,
                "can_export_tickets": not manual_ticket_blocked,
                "can_dry_run_orders": not manual_ticket_blocked,
                "can_submit_orders": False,
                "can_cancel_orders": False,
                "can_query_orders": True,
                "can_query_fills": True,
                "can_query_positions": False,
                "can_query_cash": False,
                "requires_human_broker_entry": True,
                "blockers": (
                    ["kill_switch"]
                    if kill_switch["status"] == "blocked"
                    else list(kill_switch["blockers"])
                ),
                "blocked_reason": (
                    kill_switch["reason"]
                    if kill_switch["status"] == "blocked"
                    else (
                        "Trading control state is unavailable; manual tickets fail closed."
                        if kill_switch["status"] == "unavailable"
                        else ""
                    )
                ),
                "limitations": [
                    "Creates copyable manual broker tickets only.",
                    "Does not call a broker API or mutate ledger entries.",
                    "Queries local OMS, gateway audit, and staged broker evidence only.",
                ],
            },
            {
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "gateway_id": "staged_broker_evidence",
                "display_name": "Staged broker evidence",
                "status": "available",
                "is_live": False,
                "can_read_account_facts": True,
                "can_preview_orders": False,
                "can_export_tickets": False,
                "can_dry_run_orders": False,
                "can_submit_orders": False,
                "can_cancel_orders": False,
                "can_query_orders": True,
                "can_query_fills": True,
                "can_query_positions": True,
                "can_query_cash": True,
                "requires_human_broker_entry": False,
                "limitations": [
                    "Reads staged broker evidence already imported into Karkinos.",
                    "Does not call a broker API, store credentials, or mutate OMS.",
                    "Broker order submission remains disabled.",
                ],
            },
            {
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "gateway_id": "live_disabled",
                "display_name": "Live broker gateway",
                "status": "disabled",
                "is_live": True,
                "can_read_account_facts": False,
                "can_preview_orders": False,
                "can_export_tickets": False,
                "can_dry_run_orders": False,
                "can_submit_orders": False,
                "can_cancel_orders": False,
                "can_query_orders": False,
                "can_query_fills": False,
                "can_query_positions": False,
                "can_query_cash": False,
                "requires_human_broker_entry": False,
                "controlled_bridge_policy_status": (
                    self._controlled_bridge_policy_snapshot()["status"]
                ),
                "limitations": [
                    "Live broker submission is disabled until explicit gated enablement.",
                ],
            },
        ]

    def _kill_switch_snapshot(self) -> dict[str, Any]:
        return resolve_kill_switch_evidence(self._trading_controls)

    def _build_lifecycle_evidence_view(self) -> BrokerLifecycleEvidenceViewService:
        return BrokerLifecycleEvidenceViewService(
            db=self._db,
            broker_connectors=self._broker_connectors,
        )

    def _broker_evidence_repository(self) -> BrokerEvidenceRepository | None:
        db_path = getattr(self._db, "_path", None)
        if db_path is None:
            return None
        return BrokerEvidenceRepository(Path(db_path))
