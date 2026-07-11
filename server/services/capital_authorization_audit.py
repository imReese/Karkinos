"""Append-only audit service for non-submitting capital-authority evaluations."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from server.services.capital_authorization import (
    CAPITAL_AUTHORIZATION_MODES,
    CapitalAuthorizationContext,
    CapitalAuthorizationDecision,
    CapitalAuthorizationPolicy,
    evaluate_capital_authorization,
)

CAPITAL_AUTHORIZATION_AUDIT_SCHEMA_VERSION = "karkinos.capital_authorization_audit.v1"
CAPITAL_AUTHORIZATION_STATUS_SCHEMA_VERSION = "karkinos.capital_authorization_status.v1"
CAPITAL_AUTHORIZATION_EVENT_TYPE = "capital_authorization.evaluated"
CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE = "capital_authorization_evaluation"
CAPITAL_AUTHORIZATION_EVENT_SOURCE = "capital_authorization"


class CapitalAuthorizationAuditService:
    """Preview and persist evaluation evidence without granting authority."""

    def __init__(
        self,
        *,
        db: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def preview(
        self,
        *,
        policy: CapitalAuthorizationPolicy,
        context: CapitalAuthorizationContext,
    ) -> dict[str, Any]:
        decision = evaluate_capital_authorization(policy, context)
        return {
            **decision.to_dict(),
            "persisted": False,
            "reused": False,
            "does_not_enable_execution": True,
            "runtime_authority_status": "disabled",
            "operator_identity_verified": False,
        }

    def record_evaluation(
        self,
        *,
        policy: CapitalAuthorizationPolicy,
        context: CapitalAuthorizationContext,
    ) -> dict[str, Any]:
        decision = evaluate_capital_authorization(policy, context)
        existing = self._db.list_events_sync(
            event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE,
            entity_type=CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
            entity_id=decision.input_fingerprint,
            source=CAPITAL_AUTHORIZATION_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return self._event_response(existing[0], reused=True)

        recorded_at = self._clock()
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        payload = self._audit_payload(
            policy=policy,
            context=context,
            decision=decision,
        )
        self._db.append_event_sync(
            event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE,
            timestamp=recorded_at.isoformat(),
            entity_type=CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
            entity_id=decision.input_fingerprint,
            source=CAPITAL_AUTHORIZATION_EVENT_SOURCE,
            source_ref=policy.authorization_id or decision.input_fingerprint,
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE,
            entity_type=CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
            entity_id=decision.input_fingerprint,
            source=CAPITAL_AUTHORIZATION_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("capital authorization evaluation was not recorded")
        return self._event_response(saved[0], reused=False)

    def list_evaluations(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE,
            entity_type=CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
            source=CAPITAL_AUTHORIZATION_EVENT_SOURCE,
            limit=max(1, min(int(limit), 100)),
        )
        return [self._event_response(row, reused=False) for row in rows]

    def get_status(self) -> dict[str, Any]:
        latest = self.list_evaluations(limit=1)
        return {
            "schema_version": CAPITAL_AUTHORIZATION_STATUS_SCHEMA_VERSION,
            "runtime_authority_status": "disabled",
            "execution_authority_enabled": False,
            "broker_submission_enabled": False,
            "automatic_resume_enabled": False,
            "automatic_scale_up_enabled": False,
            "supported_evaluation_modes": list(CAPITAL_AUTHORIZATION_MODES),
            "authorization_source": "append_only_operator_workflow_not_config",
            "config_can_grant_execution_authority": False,
            "operator_identity_verified": False,
            "latest_evaluation": latest[0] if latest else None,
            "next_action": "review_evaluation_evidence",
            "limitations": [
                "evaluation_evidence_does_not_enable_execution",
                "no_authorization_issue_or_revoke_endpoint",
                "operator_identity_is_unverified_input",
                "no_broker_submit_or_cancel_endpoint",
                "no_oms_or_production_ledger_mutation",
            ],
        }

    def _audit_payload(
        self,
        *,
        policy: CapitalAuthorizationPolicy,
        context: CapitalAuthorizationContext,
        decision: CapitalAuthorizationDecision,
    ) -> dict[str, Any]:
        return {
            "schema_version": CAPITAL_AUTHORIZATION_AUDIT_SCHEMA_VERSION,
            "policy": _json_safe(policy),
            "context": _json_safe(context),
            "decision": decision.to_dict(),
            "does_not_enable_execution": True,
            "runtime_authority_status": "disabled",
            "broker_submission_enabled": False,
            "automatic_resume_enabled": False,
            "automatic_scale_up_enabled": False,
            "operator_identity_verified": False,
        }

    def _event_response(
        self,
        row: dict[str, Any],
        *,
        reused: bool,
    ) -> dict[str, Any]:
        payload = _json_object(row.get("payload_json"))
        return {
            "evaluation_id": int(row["id"]),
            "recorded_at": row["timestamp"],
            "created_at": row["created_at"],
            "input_fingerprint": row["entity_id"],
            "authorization_id": row.get("source_ref") or "",
            "persisted": True,
            "reused": reused,
            **payload,
        }


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
