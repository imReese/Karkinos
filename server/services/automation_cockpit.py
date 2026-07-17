"""Read-only automation cockpit summary."""

from __future__ import annotations

from typing import Any, Callable

from server.services.automation_alerts import AutomationAlertService
from server.services.automation_control import AutomationControlService
from server.services.broker_gateway import BrokerGatewayService
from server.services.controlled_execution_operator_view import (
    ControlledExecutionOperatorViewService,
)
from server.services.strategy_promotion_pipeline import StrategyPromotionPipeline

AUTOMATION_COCKPIT_SCHEMA_VERSION = "karkinos.automation_cockpit.v2"
AUTOMATION_CURRENT_PER_ORDER_REVIEWS_SCHEMA_VERSION = (
    "karkinos.automation_current_per_order_reviews.v1"
)
CURRENT_PER_ORDER_CANDIDATES_SOURCE_SCHEMA_VERSION = (
    "karkinos.current_per_order_confirmation_candidates.v1"
)


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
            "current_per_order_reviews": _current_per_order_review_summary(
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


def _current_per_order_review_summary(
    reader: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    boundary = {
        "reads_persisted_facts_only": True,
        "provider_contact_performed": False,
        "runtime_connector_query_performed": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk": True,
        "does_not_mutate_kill_switch": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
        "broker_cancel_enabled": False,
        "authorizes_execution": False,
    }
    base = {
        "schema_version": AUTOMATION_CURRENT_PER_ORDER_REVIEWS_SCHEMA_VERSION,
        "source_schema_version": "",
        "status": "unavailable",
        "candidate_count": 0,
        "review_ready_count": 0,
        "blocked_review_count": 0,
        "source_truncated": False,
        "next_operator_action": "review_current_per_order_source_unavailable",
        "primary_candidate": None,
        "candidates": [],
        "source_blockers": ["current_per_order_dossier_source_unavailable"],
        **boundary,
    }
    if reader is None:
        return base
    try:
        source = reader()
    except Exception:
        return {
            **base,
            "status": "blocked_source",
            "source_blockers": ["current_per_order_dossier_source_failed"],
        }
    if not isinstance(source, dict):
        return {
            **base,
            "status": "blocked_source",
            "source_blockers": ["current_per_order_dossier_source_invalid"],
        }

    source_blockers: list[str] = []
    source_schema_version = str(source.get("schema_version") or "")
    if source_schema_version != CURRENT_PER_ORDER_CANDIDATES_SOURCE_SCHEMA_VERSION:
        source_blockers.append("current_per_order_source_schema_invalid")
    candidates = [
        dict(item) for item in source.get("candidates") or [] if isinstance(item, dict)
    ]
    declared_count = _safe_non_negative_int(source.get("candidate_count"))
    if declared_count is None or declared_count != len(candidates):
        source_blockers.append("current_per_order_candidate_count_mismatch")
    source_truncated = source.get("truncated") is True
    if source_truncated:
        source_blockers.append("current_per_order_candidate_source_truncated")
    expected_boundary = {
        "reads_persisted_facts_only": True,
        "provider_contact_performed": False,
        "runtime_connector_query_performed": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk": True,
        "does_not_mutate_kill_switch": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
        "broker_cancel_enabled": False,
        "authorizes_execution": False,
    }
    if any(source.get(key) is not value for key, value in expected_boundary.items()):
        source_blockers.append("current_per_order_source_boundary_invalid")
    if any(item.get("authorizes_execution") is not False for item in candidates):
        source_blockers.append("current_per_order_candidate_authority_invalid")

    ready = [item for item in candidates if item.get("review_ready") is True]
    blocked = [item for item in candidates if item.get("review_ready") is not True]
    if source_blockers:
        status = "blocked_source"
        next_action = "review_current_per_order_source_blockers"
        primary = None
    elif ready:
        status = "review_ready"
        next_action = "open_trading_current_per_order_review"
        primary = ready[0]
    elif blocked:
        status = "blocked_review"
        next_action = "resolve_current_per_order_evidence_blockers"
        primary = blocked[0]
    else:
        status = "no_current_candidates"
        next_action = "none_default_disabled"
        primary = None
    return {
        **base,
        "source_schema_version": source_schema_version,
        "status": status,
        "candidate_count": len(candidates),
        "review_ready_count": len(ready),
        "blocked_review_count": len(blocked),
        "source_truncated": source_truncated,
        "next_operator_action": next_action,
        "primary_candidate": primary,
        "candidates": candidates,
        "source_blockers": list(dict.fromkeys(source_blockers)),
    }


def _safe_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


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
