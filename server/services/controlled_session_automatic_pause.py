"""Durable automatic pause controller, closed until session issuance exists."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

CONTROLLED_SESSION_AUTOMATIC_PAUSE_SCHEMA_VERSION = (
    "karkinos.controlled_session_automatic_pause.v1"
)
CONTROLLED_SESSION_AUTOMATIC_PAUSE_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_session_automatic_pause_status.v1"
)
CONTROLLED_SESSION_PAUSE_REJECTION_EVENT_TYPE = (
    "controlled_session.automatic_pause_evaluation_rejected"
)
CONTROLLED_SESSION_PAUSE_ENTITY_TYPE = "controlled_session_automatic_pause"
CONTROLLED_SESSION_PAUSE_EVENT_SOURCE = "controlled_session_automatic_pause"

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ControlledSessionAutomaticPauseRejected(ValueError):
    """Raised after a pause evaluation cannot safely identify its session."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSessionAutomaticPauseService:
    """Evaluate hard gates and persist a one-way paused runtime state."""

    def __init__(
        self,
        *,
        db: Any,
        session_provider: Callable[[str], dict[str, Any]] | None = None,
        gate_provider: Callable[[str], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._session_provider = session_provider
        self._gate_provider = gate_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        providers_configured = callable(self._session_provider) and callable(
            self._gate_provider
        )
        return {
            "schema_version": CONTROLLED_SESSION_AUTOMATIC_PAUSE_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "automatic_pause_ready_internal_only"
                if providers_configured
                else "disabled_waiting_for_authenticated_session_issuance"
            ),
            "session_provider_configured": callable(self._session_provider),
            "gate_provider_configured": callable(self._gate_provider),
            "automatic_pause_enabled": providers_configured,
            "public_pause_endpoint_exposed": False,
            "automatic_resume_enabled": False,
            "public_resume_endpoint_exposed": False,
            "runtime_session_issuance_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }

    def preview(self, *, session_id: str) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized_session_id = str(session_id or "").strip()
        blockers: list[str] = []
        if not _ID_PATTERN.fullmatch(normalized_session_id):
            blockers.append("automatic_pause_session_id_invalid")

        session: dict[str, Any] = {}
        if not callable(self._session_provider):
            blockers.append("automatic_pause_session_provider_unavailable")
        elif _ID_PATTERN.fullmatch(normalized_session_id):
            try:
                raw_session = self._session_provider(normalized_session_id) or {}
            except Exception:
                raw_session = {}
                blockers.append("automatic_pause_session_provider_failed")
            session = _sanitize_session(
                raw_session if isinstance(raw_session, dict) else {}
            )
        session_status = session.get("status")
        if session_status not in {
            "current_enabled_bounded_session",
            "monitorable_bounded_session",
        }:
            blockers.append("automatic_pause_session_not_current_or_enabled")
        if session.get("session_id") != normalized_session_id:
            blockers.append("automatic_pause_session_identity_mismatch")
        if session_status == "current_enabled_bounded_session" and not session.get(
            "session_authority_verified"
        ):
            blockers.append("automatic_pause_session_authority_not_verified")
        if session_status == "monitorable_bounded_session" and not session.get(
            "monitoring_identity_verified"
        ):
            blockers.append("automatic_pause_monitoring_identity_not_verified")
        session_fingerprint = str(session.get("session_fingerprint") or "")
        reservation_id = str(session.get("reservation_id") or "")
        if not _FINGERPRINT_PATTERN.fullmatch(session_fingerprint):
            blockers.append("automatic_pause_session_fingerprint_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(reservation_id):
            blockers.append("automatic_pause_reservation_id_invalid")

        existing_state = (
            self._db.get_controlled_session_runtime_state_sync(normalized_session_id)
            if _ID_PATTERN.fullmatch(normalized_session_id)
            else None
        )
        if existing_state and existing_state.get("session_fingerprint") != (
            session_fingerprint
        ):
            blockers.append("automatic_pause_session_identity_conflict")
        gate_provider_failed = False
        raw_gates: dict[str, Any] = {}
        if not callable(self._gate_provider):
            gate_provider_failed = True
        elif _ID_PATTERN.fullmatch(normalized_session_id):
            try:
                provided = self._gate_provider(normalized_session_id) or {}
            except Exception:
                provided = {}
                gate_provider_failed = True
            raw_gates = provided if isinstance(provided, dict) else {}
        gates = _sanitize_gates(raw_gates)
        pause_reasons = _pause_reasons(
            gates,
            gate_provider_failed=gate_provider_failed,
        )
        gate_fingerprint = _fingerprint(gates)
        reason_fingerprint = _fingerprint(pause_reasons)
        pause_core = {
            "schema_version": CONTROLLED_SESSION_AUTOMATIC_PAUSE_SCHEMA_VERSION,
            "session_id": normalized_session_id,
            "session_fingerprint": session_fingerprint,
            "reservation_id": reservation_id,
            "gate_fingerprint": gate_fingerprint,
            "reason_fingerprint": reason_fingerprint,
            "reasons": pause_reasons,
        }
        unique_blockers = list(dict.fromkeys(blockers))
        already_paused = bool(
            existing_state and existing_state.get("status") == "paused"
        )
        return {
            **pause_core,
            "pause_event_id": _fingerprint(pause_core),
            "previewed_at": now.isoformat(),
            "status": (
                "blocked"
                if unique_blockers
                else (
                    "already_paused"
                    if already_paused
                    else "pause_required" if pause_reasons else "clear_no_pause"
                )
            ),
            "blockers": unique_blockers,
            "pause_required": bool(pause_reasons) and not already_paused,
            "already_paused": already_paused,
            "current_state": _public_state(existing_state or {}),
            "gate_snapshot": gates,
            "runtime_session_issued": False,
            "authorizes_broker_submission": False,
            "safety": _safety_flags(),
        }

    def evaluate(self, *, session_id: str) -> dict[str, Any]:
        preview = self.preview(session_id=session_id)
        if preview["blockers"]:
            evidence = self._record_rejection(preview)
            raise ControlledSessionAutomaticPauseRejected(
                "controlled session automatic pause evaluation rejected",
                evidence=evidence,
            )
        if preview["already_paused"]:
            state = (
                self._db.get_controlled_session_runtime_state_sync(
                    preview["session_id"]
                )
                or {}
            )
            event = (
                self._db.get_controlled_session_pause_event_sync(
                    str(state.get("pause_event_id") or "")
                )
                or {}
            )
            if not event:
                evidence = self._record_rejection(
                    {
                        **preview,
                        "blockers": ["automatic_pause_event_evidence_missing"],
                    }
                )
                raise ControlledSessionAutomaticPauseRejected(
                    "controlled session automatic pause evidence missing",
                    evidence=evidence,
                )
            return _pause_response(event, state=state, reused=True)
        if not preview["pause_required"]:
            return {
                **preview,
                "persisted": False,
                "reused": False,
                "pause_applied": False,
            }

        now = _aware_utc(self._clock())
        payload = {
            **{
                key: preview[key]
                for key in (
                    "schema_version",
                    "pause_event_id",
                    "session_id",
                    "session_fingerprint",
                    "reservation_id",
                    "gate_fingerprint",
                    "reason_fingerprint",
                    "reasons",
                    "gate_snapshot",
                )
            },
            "status": "paused",
            "pause_applied": True,
            "automatic_resume_enabled": False,
            "runtime_session_issued": False,
            "authorizes_broker_submission": False,
            "safety": _safety_flags(),
        }
        transaction = self._db.pause_controlled_session_sync(
            pause={
                **{
                    key: payload[key]
                    for key in (
                        "pause_event_id",
                        "session_id",
                        "session_fingerprint",
                        "reservation_id",
                        "gate_fingerprint",
                        "reason_fingerprint",
                        "reasons",
                        "gate_snapshot",
                    )
                },
                "paused_at_epoch_ms": int(now.timestamp() * 1000),
                "paused_at": now.isoformat(),
                "payload": payload,
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") != "paused":
            evidence = self._record_rejection(
                {
                    **preview,
                    "blockers": [
                        str(item) for item in transaction.get("blockers") or []
                    ],
                }
            )
            raise ControlledSessionAutomaticPauseRejected(
                "controlled session automatic pause transaction rejected",
                evidence=evidence,
            )
        return _pause_response(
            transaction.get("event") or {},
            state=transaction.get("state") or {},
            reused=bool(transaction.get("reused")),
        )

    def get_state(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not _ID_PATTERN.fullmatch(normalized):
            return _public_state({})
        return _public_state(
            self._db.get_controlled_session_runtime_state_sync(normalized) or {}
        )

    def list_pause_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_session_pause_events_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [_pause_response(row, state={}, reused=False) for row in rows]

    def _record_rejection(self, preview: dict[str, Any]) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_SESSION_AUTOMATIC_PAUSE_SCHEMA_VERSION,
            "status": "rejected",
            "session_id": str(preview.get("session_id") or ""),
            "session_fingerprint": str(preview.get("session_fingerprint") or ""),
            "pause_event_id": str(preview.get("pause_event_id") or ""),
            "blockers": [str(item) for item in preview.get("blockers") or []],
            "pause_applied": False,
            "automatic_resume_enabled": False,
            "runtime_session_issued": False,
            "authorizes_broker_submission": False,
            "safety": _safety_flags(),
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SESSION_PAUSE_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SESSION_PAUSE_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_SESSION_PAUSE_EVENT_SOURCE,
            source_ref=str(preview.get("pause_event_id") or ""),
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            "attempt_id": attempt_id,
            **payload,
        }


def _pause_reasons(
    gates: dict[str, Any],
    *,
    gate_provider_failed: bool,
) -> list[str]:
    reasons: list[str] = []
    if gate_provider_failed:
        reasons.append("gate_provider_unavailable")
    if not _FINGERPRINT_PATTERN.fullmatch(str(gates.get("source_fingerprint") or "")):
        reasons.append("gate_source_fingerprint_invalid")
    if gates.get("account_truth_status") not in {"pass", "clear"}:
        reasons.append("account_truth_not_clear")
    if gates.get("risk_gate_status") not in {"pass", "passed"}:
        reasons.append("risk_gate_not_clear")
    if gates.get("reconciliation_status") not in {"clear", "manually_accepted"}:
        reasons.append("reconciliation_not_clear")
    if gates.get("paper_shadow_status") not in {
        "within_expectations",
        "manually_accepted",
    }:
        reasons.append("paper_shadow_divergence_not_clear")
    if gates.get("gateway_health_status") != "healthy":
        reasons.append("gateway_health_degraded")
    if gates.get("market_data_status") not in {"confirmed", "current", "live"}:
        reasons.append("market_data_not_current")
    if gates.get("budget_status") not in {
        "current_reserved",
        "current_reserved_non_executing",
    }:
        reasons.append("budget_not_current")
    if gates.get("rate_limit_status") != "clear":
        reasons.append("rate_limit_not_clear")
    if gates.get("kill_switch_enabled") is not False:
        reasons.append("kill_switch_enabled")
    for field, reason in (
        ("budget_exhausted", "budget_exhausted"),
        ("daily_loss_limit_reached", "daily_loss_limit_reached"),
        ("drawdown_limit_reached", "drawdown_limit_reached"),
        ("rejection_spike", "rejection_spike"),
        ("unexpected_account_change", "unexpected_account_change"),
    ):
        value = gates.get(field)
        if value is True:
            reasons.append(reason)
        elif value is not False:
            reasons.append(f"{field}_fact_invalid")
    consecutive_errors = gates.get("consecutive_errors")
    max_consecutive_errors = gates.get("max_consecutive_errors")
    if (
        not isinstance(consecutive_errors, int)
        or not isinstance(max_consecutive_errors, int)
        or consecutive_errors < 0
        or max_consecutive_errors <= 0
    ):
        reasons.append("consecutive_error_facts_invalid")
    elif consecutive_errors >= max_consecutive_errors:
        reasons.append("consecutive_error_limit_reached")
    return list(dict.fromkeys(reasons))


def _sanitize_session(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(value.get("status") or ""),
        "session_id": str(value.get("session_id") or ""),
        "session_fingerprint": str(value.get("session_fingerprint") or ""),
        "reservation_id": str(value.get("reservation_id") or ""),
        "session_authority_verified": value.get("session_authority_verified") is True,
        "monitoring_identity_verified": value.get("monitoring_identity_verified")
        is True,
    }


def _sanitize_gates(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_fingerprint": str(value.get("source_fingerprint") or ""),
        "account_truth_status": str(value.get("account_truth_status") or "").lower(),
        "risk_gate_status": str(value.get("risk_gate_status") or "").lower(),
        "reconciliation_status": str(value.get("reconciliation_status") or "").lower(),
        "paper_shadow_status": str(value.get("paper_shadow_status") or "").lower(),
        "gateway_health_status": str(value.get("gateway_health_status") or "").lower(),
        "market_data_status": str(value.get("market_data_status") or "").lower(),
        "budget_status": str(value.get("budget_status") or "").lower(),
        "rate_limit_status": str(value.get("rate_limit_status") or "").lower(),
        "kill_switch_enabled": value.get("kill_switch_enabled"),
        "budget_exhausted": value.get("budget_exhausted"),
        "daily_loss_limit_reached": value.get("daily_loss_limit_reached"),
        "drawdown_limit_reached": value.get("drawdown_limit_reached"),
        "rejection_spike": value.get("rejection_spike"),
        "unexpected_account_change": value.get("unexpected_account_change"),
        "consecutive_errors": value.get("consecutive_errors"),
        "max_consecutive_errors": value.get("max_consecutive_errors"),
    }


def _public_state(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": str(row.get("session_id") or ""),
        "session_fingerprint": str(row.get("session_fingerprint") or ""),
        "reservation_id": str(row.get("reservation_id") or ""),
        "status": str(row.get("status") or "not_found"),
        "pause_event_id": str(row.get("pause_event_id") or ""),
        "reason_fingerprint": str(row.get("reason_fingerprint") or ""),
        "reasons": _json_list(row.get("reasons_json")),
        "paused_at": str(row.get("paused_at") or ""),
        "automatic_resume_enabled": False,
        "authorizes_broker_submission": False,
    }


def _pause_response(
    row: dict[str, Any],
    *,
    state: dict[str, Any],
    reused: bool,
) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "persisted": True,
        "reused": reused,
        "paused_at": str(row.get("paused_at") or ""),
        "current_state": _public_state(state),
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_issue_enable_resume_renew_or_expand_session": True,
        "does_not_contact_broker": True,
        "does_not_submit_or_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_grant_or_scale_capital_authority": True,
    }
