"""Atomic runtime order-rate admission, closed until session issuance exists."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

CONTROLLED_SESSION_RATE_ADMISSION_SCHEMA_VERSION = (
    "karkinos.controlled_session_rate_admission.v1"
)
CONTROLLED_SESSION_RATE_LIMITER_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_session_rate_limiter_status.v1"
)
CONTROLLED_SESSION_RATE_REJECTION_EVENT_TYPE = (
    "controlled_session.runtime_rate_admission_rejected"
)
CONTROLLED_SESSION_RATE_ADMISSION_ENTITY_TYPE = "controlled_session_rate_admission"
CONTROLLED_SESSION_RATE_ADMISSION_EVENT_SOURCE = (
    "controlled_session_runtime_rate_limiter"
)
CONTROLLED_SESSION_RATE_WINDOW_SECONDS = 60
CONTROLLED_SESSION_MAX_RATE_PER_MINUTE = 600

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ControlledSessionRateAdmissionRejected(ValueError):
    """Raised after a rejected runtime rate-admission attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSessionRuntimeRateLimiterService:
    """Admit an order atomically without issuing a session or touching OMS/broker."""

    def __init__(
        self,
        *,
        db: Any,
        session_provider: Callable[[str], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._session_provider = session_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        provider_configured = callable(self._session_provider)
        return {
            "schema_version": CONTROLLED_SESSION_RATE_LIMITER_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "runtime_admission_ready_internal_only"
                if provider_configured
                else "disabled_waiting_for_authenticated_session_issuance"
            ),
            "session_provider_configured": provider_configured,
            "runtime_admission_enabled": provider_configured,
            "public_admission_endpoint_exposed": False,
            "window_seconds": CONTROLLED_SESSION_RATE_WINDOW_SECONDS,
            "maximum_supported_rate_per_minute": (
                CONTROLLED_SESSION_MAX_RATE_PER_MINUTE
            ),
            "runtime_session_issuance_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }

    def preview(
        self,
        *,
        session_id: str,
        order_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized_session_id = str(session_id or "").strip()
        normalized_order_id = str(order_id or "").strip()
        normalized_request_id = str(request_id or "").strip().lower()
        blockers: list[str] = []
        if not _ID_PATTERN.fullmatch(normalized_session_id):
            blockers.append("runtime_session_id_invalid")
        if not _ID_PATTERN.fullmatch(normalized_order_id):
            blockers.append("runtime_order_id_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_request_id):
            blockers.append("runtime_rate_request_id_invalid")
        pause_event_id = ""
        state_getter = getattr(
            self._db,
            "get_controlled_session_runtime_state_sync",
            None,
        )
        if callable(state_getter) and _ID_PATTERN.fullmatch(normalized_session_id):
            pause_state = state_getter(normalized_session_id) or {}
            if pause_state.get("status") == "paused":
                blockers.append("runtime_session_paused")
                pause_event_id = str(pause_state.get("pause_event_id") or "")

        session: dict[str, Any] = {}
        if not callable(self._session_provider):
            blockers.append("authenticated_runtime_session_provider_unavailable")
        elif _ID_PATTERN.fullmatch(normalized_session_id):
            try:
                raw = self._session_provider(normalized_session_id) or {}
            except Exception:
                raw = {}
                blockers.append("authenticated_runtime_session_provider_failed")
            session = _sanitize_session(raw if isinstance(raw, dict) else {})
        if session.get("status") != "current_enabled_bounded_session":
            blockers.append("runtime_session_not_current_or_enabled")
        if session.get("session_id") != normalized_session_id:
            blockers.append("runtime_session_identity_mismatch")
        if not session.get("session_authority_verified"):
            blockers.append("runtime_session_authority_not_verified")
        if not session.get("budget_reservation_verified"):
            blockers.append("runtime_session_budget_reservation_not_verified")
        if not session.get("upstream_gates_clear"):
            blockers.append("runtime_session_upstream_gates_not_clear")
        if not session.get("kill_switch_clear"):
            blockers.append("runtime_session_kill_switch_not_clear")
        if not session.get("runtime_rate_limiter_enabled"):
            blockers.append("runtime_rate_limiter_not_enabled_by_session")
        session_order_ids = [str(item) for item in session.get("order_ids") or []]
        if (
            not session_order_ids
            or len(session_order_ids) != len(set(session_order_ids))
            or any(not _ID_PATTERN.fullmatch(item) for item in session_order_ids)
        ):
            blockers.append("runtime_session_order_scope_invalid")
        if normalized_order_id not in set(session_order_ids):
            blockers.append("runtime_order_not_in_session_scope")
        session_fingerprint = str(session.get("session_fingerprint") or "")
        reservation_id = str(session.get("reservation_id") or "")
        if not _FINGERPRINT_PATTERN.fullmatch(session_fingerprint):
            blockers.append("runtime_session_fingerprint_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(reservation_id):
            blockers.append("runtime_session_reservation_id_invalid")
        authorization_id = str(session.get("authorization_id") or "")
        account_alias = str(session.get("account_alias") or "")
        strategy_id = str(session.get("strategy_id") or "")
        if not _ID_PATTERN.fullmatch(authorization_id):
            blockers.append("runtime_session_authorization_id_invalid")
        if (
            not account_alias
            or len(account_alias) > 128
            or any(ord(character) < 32 for character in account_alias)
        ):
            blockers.append("runtime_session_account_alias_invalid")
        if not _ID_PATTERN.fullmatch(strategy_id):
            blockers.append("runtime_session_strategy_id_invalid")

        start_at = _parse_timestamp(session.get("effective_at"))
        expires_at = _parse_timestamp(session.get("expires_at"))
        if start_at is None or expires_at is None or start_at >= expires_at:
            blockers.append("runtime_session_window_invalid")
        elif now < start_at:
            blockers.append("runtime_session_not_yet_effective")
        elif now >= expires_at:
            blockers.append("runtime_session_expired")
        try:
            max_rate = int(session.get("max_order_rate_per_minute") or 0)
        except (TypeError, ValueError):
            max_rate = 0
        if max_rate <= 0 or max_rate > CONTROLLED_SESSION_MAX_RATE_PER_MINUTE:
            blockers.append("runtime_session_rate_limit_invalid")

        admission_core = {
            "schema_version": CONTROLLED_SESSION_RATE_ADMISSION_SCHEMA_VERSION,
            "session_id": normalized_session_id,
            "session_fingerprint": session_fingerprint,
            "reservation_id": reservation_id,
            "authorization_id": authorization_id,
            "account_alias": account_alias,
            "strategy_id": strategy_id,
            "order_id": normalized_order_id,
            "request_id": normalized_request_id,
            "max_order_rate_per_minute": max_rate,
            "effective_at": start_at.isoformat() if start_at else "",
            "expires_at": expires_at.isoformat() if expires_at else "",
            "window_seconds": CONTROLLED_SESSION_RATE_WINDOW_SECONDS,
        }
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **admission_core,
            "admission_id": _fingerprint(admission_core),
            "previewed_at": now.isoformat(),
            "status": (
                "ready_for_atomic_admission" if not unique_blockers else "blocked"
            ),
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "pause_event_id": pause_event_id,
            "runtime_admission_granted": False,
            "authorizes_broker_submission": False,
            "safety": _safety_flags(),
        }

    def admit(
        self,
        *,
        session_id: str,
        order_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        preview = self.preview(
            session_id=session_id,
            order_id=order_id,
            request_id=request_id,
        )
        if preview["blockers"]:
            evidence = self._record_rejection(
                preview=preview,
                transaction_blockers=[],
            )
            raise ControlledSessionRateAdmissionRejected(
                "controlled session runtime rate admission rejected",
                evidence=evidence,
            )
        now = _aware_utc(self._clock())
        payload = {
            **{
                key: preview[key]
                for key in (
                    "schema_version",
                    "admission_id",
                    "session_id",
                    "session_fingerprint",
                    "reservation_id",
                    "authorization_id",
                    "account_alias",
                    "strategy_id",
                    "order_id",
                    "request_id",
                    "max_order_rate_per_minute",
                    "effective_at",
                    "expires_at",
                    "window_seconds",
                )
            },
            "status": "admitted",
            "runtime_admission_granted": True,
            "runtime_session_issued": False,
            "authorizes_broker_submission": False,
            "safety": _safety_flags(),
        }
        transaction = self._db.admit_controlled_session_order_sync(
            admission={
                **{
                    key: payload[key]
                    for key in (
                        "admission_id",
                        "session_id",
                        "session_fingerprint",
                        "reservation_id",
                        "authorization_id",
                        "account_alias",
                        "strategy_id",
                        "order_id",
                        "request_id",
                        "max_order_rate_per_minute",
                    )
                },
                "admitted_at_epoch_ms": int(now.timestamp() * 1000),
                "admitted_at": now.isoformat(),
                "payload": payload,
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") != "admitted":
            evidence = self._record_rejection(
                preview=preview,
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
                transaction=transaction,
            )
            raise ControlledSessionRateAdmissionRejected(
                "controlled session runtime rate admission rejected atomically",
                evidence=evidence,
            )
        return _admission_response(
            transaction.get("admission") or {},
            reused=bool(transaction.get("reused")),
            admitted_before=int(transaction.get("admitted_before") or 0),
            admitted_after=int(transaction.get("admitted_after") or 0),
            effective_rate=int(transaction.get("effective_rate") or 0),
        )

    def list_admissions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_session_rate_admissions_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [_admission_response(row, reused=False) for row in rows]

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        transaction_blockers: list[str],
        transaction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_SESSION_RATE_ADMISSION_SCHEMA_VERSION,
            "status": "rejected",
            "admission_id": str(preview.get("admission_id") or ""),
            "session_id": str(preview.get("session_id") or ""),
            "order_id": str(preview.get("order_id") or ""),
            "request_id": str(preview.get("request_id") or ""),
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "admitted_before": int((transaction or {}).get("admitted_before") or 0),
            "admitted_after": int((transaction or {}).get("admitted_after") or 0),
            "pause_event_id": str(
                (transaction or {}).get("pause_event_id")
                or preview.get("pause_event_id")
                or ""
            ),
            "runtime_admission_granted": False,
            "runtime_session_issued": False,
            "authorizes_broker_submission": False,
            "safety": _safety_flags(),
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SESSION_RATE_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SESSION_RATE_ADMISSION_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_SESSION_RATE_ADMISSION_EVENT_SOURCE,
            source_ref=str(preview.get("admission_id") or ""),
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            "attempt_id": attempt_id,
            **payload,
        }


def _sanitize_session(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(value.get("status") or ""),
        "session_id": str(value.get("session_id") or ""),
        "session_fingerprint": str(value.get("session_fingerprint") or ""),
        "reservation_id": str(value.get("reservation_id") or ""),
        "authorization_id": str(value.get("authorization_id") or ""),
        "account_alias": str(value.get("account_alias") or ""),
        "strategy_id": str(value.get("strategy_id") or ""),
        "order_ids": [str(item) for item in value.get("order_ids") or []],
        "effective_at": str(value.get("effective_at") or ""),
        "expires_at": str(value.get("expires_at") or ""),
        "max_order_rate_per_minute": value.get("max_order_rate_per_minute"),
        "session_authority_verified": value.get("session_authority_verified") is True,
        "budget_reservation_verified": value.get("budget_reservation_verified") is True,
        "upstream_gates_clear": value.get("upstream_gates_clear") is True,
        "kill_switch_clear": value.get("kill_switch_clear") is True,
        "runtime_rate_limiter_enabled": value.get("runtime_rate_limiter_enabled")
        is True,
    }


def _admission_response(
    row: dict[str, Any],
    *,
    reused: bool,
    admitted_before: int = 0,
    admitted_after: int = 0,
    effective_rate: int = 0,
) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "persisted": True,
        "reused": reused,
        "admitted_at": str(row.get("admitted_at") or ""),
        "created_at": str(row.get("created_at") or ""),
        "admitted_before": admitted_before,
        "admitted_after": admitted_after,
        "effective_rate": effective_rate,
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


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


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_issue_enable_resume_or_expand_session": True,
        "does_not_contact_broker": True,
        "does_not_submit_or_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_grant_or_scale_capital_authority": True,
    }
