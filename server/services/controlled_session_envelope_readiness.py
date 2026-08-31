"""Soak, reconciliation, and kill-switch readiness evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS,
)
from server.services.controlled_session_envelope_values import (
    connector_id as _connector_id,
)
from server.services.controlled_session_envelope_values import (
    parse_timestamp as _parse_timestamp,
)


class ControlledSessionEnvelopeReadinessMixin:
    def _soak_summary(
        self,
        connector_id: str,
        *,
        now: datetime,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        status = self._build_soak_service(
            db=self._db,
            connectors=self._connectors,
            clock=self._clock,
        ).get_status()
        summary = next(
            (
                item
                for item in status.get("connectors") or []
                if str(item.get("connector_id") or "") == connector_id
            ),
            None,
        )
        connector = next(
            (item for item in self._connectors if _connector_id(item) == connector_id),
            None,
        )
        capabilities = getattr(connector, "capabilities", None)
        can_submit = bool(getattr(capabilities, "can_submit_orders", False))
        latest = (
            summary.get("latest_observation")
            if summary and isinstance(summary.get("latest_observation"), dict)
            else {}
        )
        captured_at = _parse_timestamp(latest.get("source_captured_at"))
        age_seconds: int | None = None
        freshness = "missing"
        if captured_at is not None:
            age = (now - captured_at).total_seconds()
            age_seconds = int(max(0, age))
            if age < -300:
                freshness = "future"
            elif age > CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS:
                freshness = "stale"
            else:
                freshness = "fresh"
        result = {
            "connector_id": connector_id,
            "configured": connector is not None,
            "latest_soak_status": (
                str(summary.get("latest_soak_status") or "not_observed")
                if summary
                else "not_observed"
            ),
            "healthy_trading_day_count": (
                int(summary.get("healthy_trading_day_count") or 0) if summary else 0
            ),
            "operational_soak_complete": bool(
                summary and summary.get("operational_soak_complete")
            ),
            "promotion_ready": bool(status.get("promotion_ready")),
            "account_truth_reconciliation_linked": bool(
                status.get("account_truth_reconciliation_linked")
            ),
            "owner_acceptance_recorded": bool(status.get("owner_acceptance_recorded")),
            "connector_can_submit": can_submit,
            "evidence_connector_can_submit": can_submit,
            "source_captured_at": captured_at.isoformat() if captured_at else "",
            "current_age_seconds": age_seconds,
            "max_age_seconds": CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS,
            "freshness_status": freshness,
            "broker_contacted": False,
        }
        review: list[str] = []
        if not connector_id:
            review.append("capital_connector_id_missing")
        if connector is None:
            review.append("connector_not_configured")
        if summary is None:
            review.append("connector_soak_evidence_missing")
        elif result["latest_soak_status"] != "healthy":
            review.append("connector_latest_soak_not_healthy")
        if freshness != "fresh":
            review.append("connector_soak_evidence_not_fresh")
        hard: list[str] = []
        if not result["operational_soak_complete"]:
            hard.append("broker_soak_operational_evidence_incomplete")
        if not result["account_truth_reconciliation_linked"]:
            hard.append("broker_soak_account_truth_reconciliation_not_linked")
        if not result["owner_acceptance_recorded"]:
            hard.append("broker_soak_owner_acceptance_missing")
        if not result["promotion_ready"]:
            hard.append("broker_soak_promotion_not_ready")
        if can_submit:
            hard.append("evidence_connector_exposes_submit_capability")
        return result, review, hard

    def _reconciliation_summary(
        self,
        fingerprint: str,
        *,
        expected_strategy_id: str,
    ) -> tuple[dict[str, Any], list[str]]:
        return self._resolve_prior_batch_reconciliation(
            db=self._db,
            fingerprint=fingerprint,
            expected_strategy_id=expected_strategy_id,
        )

    def _kill_switch_summary(self) -> tuple[dict[str, Any], list[str]]:
        getter = getattr(self._trading_controls, "snapshot", None)
        if not callable(getter):
            return {
                "status": "unavailable",
                "enabled": None,
                "reason": "",
            }, ["kill_switch_status_unavailable"]
        snapshot = getter()
        enabled = bool(getattr(snapshot, "kill_switch_enabled", False))
        return {
            "status": "blocked" if enabled else "pass",
            "enabled": enabled,
            "reason": str(getattr(snapshot, "reason", "") or ""),
            "evidence_ref": (
                "trading_controls:kill_switch_enabled"
                if enabled
                else "trading_controls:kill_switch_clear"
            ),
        }, (["kill_switch_enabled"] if enabled else [])
