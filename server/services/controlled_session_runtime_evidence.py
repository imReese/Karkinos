"""Provider resolution and rejection evidence for runtime-session authority."""

from __future__ import annotations

from typing import Any, Callable

from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_ENTITY_TYPE,
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_EVENT_SOURCE,
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE,
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
)
from server.services.controlled_session_runtime_values import aware_utc as _aware_utc
from server.services.controlled_session_runtime_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_session_runtime_values import (
    safety_flags as _safety_flags,
)


class RuntimeAuthorityEvidenceMixin:
    def _resolve_provider(
        self,
        provider: Callable[[str], dict[str, Any]] | None,
        identifier: str,
        *,
        unavailable: str,
        failed: str,
        blockers: list[str],
    ) -> dict[str, Any]:
        if not callable(provider):
            blockers.append(unavailable)
            return {}
        try:
            value = provider(identifier) or {}
        except Exception:
            blockers.append(failed)
            return {}
        return value if isinstance(value, dict) else {}

    def _record_rejection(
        self,
        *,
        action: str,
        artifact: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
            "status": "rejected",
            "action": action,
            "session_id": str(artifact.get("session_id") or ""),
            "reservation_id": str(artifact.get("reservation_id") or ""),
            "expected_fingerprint": str(
                artifact.get("issuance_fingerprint")
                or artifact.get("revocation_fingerprint")
                or artifact.get("replacement_fingerprint")
                or ""
            ),
            "submitted_fingerprint": str(submitted_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in artifact.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "runtime_session_issued": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SESSION_RUNTIME_AUTHORITY_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_SESSION_RUNTIME_AUTHORITY_EVENT_SOURCE,
            source_ref=payload["expected_fingerprint"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            **payload,
        }
