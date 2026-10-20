"""Short-lived, source-rechecked Account Truth evidence for session start."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION = "karkinos.session_start_account_truth.v1"
SESSION_START_ACCOUNT_TRUTH_STATUS_SCHEMA_VERSION = (
    "karkinos.session_start_account_truth_status.v1"
)
SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE = "controlled_session.account_truth_recorded"
SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE = "session_start_account_truth"
SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE = "session_start_account_truth"
SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT = (
    "record_non_authorizing_session_start_account_truth"
)
SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS = 120

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SAFE_RESOLUTION_BLOCKERS = frozenset(
    {
        "account_truth_fingerprint_invalid",
        "account_truth_recorded_at_invalid",
        "account_truth_record_expired",
        "account_truth_source_changed",
        "account_truth_currently_blocked",
        "account_truth_record_not_found",
    }
)


class SessionStartAccountTruthRejected(ValueError):
    """Raised after a rejected Account Truth recording attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class SessionStartAccountTruthService:
    """Persist current Account Truth evidence without issuing session authority."""

    def __init__(
        self,
        *,
        db: Any,
        account_truth_provider: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._account_truth_provider = account_truth_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_START_ACCOUNT_TRUTH_STATUS_SCHEMA_VERSION,
            "contract_status": "short_lived_non_authorizing_account_truth",
            "source_max_age_seconds": SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
            "record_max_age_seconds": SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
            "account_truth_provider_configured": callable(self._account_truth_provider),
            "runtime_session_authority": "disabled",
            "capital_authority_change_enabled": False,
            "broker_submission_enabled": False,
            "acknowledgement": SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
            "safety": _safety_flags(),
        }

    def preview(
        self,
        *,
        evidence_connector_id: str,
        account_alias: str,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        connector_id = str(evidence_connector_id or "").strip()
        raw_account_alias = str(account_alias or "")
        normalized_account_alias = raw_account_alias.strip()
        blockers: list[str] = []
        if not _ID_PATTERN.fullmatch(connector_id):
            blockers.append("evidence_connector_id_invalid")
        if (
            not normalized_account_alias
            or len(normalized_account_alias) > 128
            or raw_account_alias != normalized_account_alias
            or any(ord(character) < 32 for character in normalized_account_alias)
        ):
            blockers.append("account_alias_invalid")

        raw: dict[str, Any] = {}
        if not callable(self._account_truth_provider):
            blockers.append("account_truth_provider_unavailable")
        else:
            try:
                source = self._account_truth_provider() or {}
            except Exception:
                source = {}
                blockers.append("account_truth_provider_failed")
            raw = source if isinstance(source, dict) else {}
        sanitized = _sanitize_source(raw)
        if sanitized["status"] != "clear":
            blockers.append("account_truth_status_not_clear")
        if sanitized["gate_status"] != "pass":
            blockers.append("account_truth_gate_not_pass")
        if sanitized["data_freshness_status"] != "fresh":
            blockers.append("account_truth_data_not_fresh")
        if sanitized["reconciliation_status"] not in {"clear", "pass"}:
            blockers.append("account_truth_reconciliation_not_clear")
        if sanitized["unresolved_mismatch_count"] != 0:
            blockers.append("account_truth_unresolved_mismatches")
        if not sanitized["import_run_id"]:
            blockers.append("account_truth_import_run_missing")
        if not _FINGERPRINT_PATTERN.fullmatch(sanitized["source_fingerprint"]):
            blockers.append("account_truth_source_fingerprint_invalid")
        captured_at = _parse_aware_timestamp(sanitized["captured_at"])
        age_seconds: int | None = None
        freshness = "missing"
        if captured_at is None:
            blockers.append("account_truth_source_timestamp_invalid")
        else:
            age = (now - captured_at).total_seconds()
            age_seconds = int(max(0, age))
            if age < -30:
                freshness = "future"
                blockers.append("account_truth_source_timestamp_in_future")
            elif age > SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS:
                freshness = "stale"
                blockers.append("account_truth_source_stale_for_session_start")
            else:
                freshness = "fresh"
        if sanitized["does_not_mutate_production_ledger"] is not True:
            blockers.append("account_truth_ledger_boundary_invalid")
        if sanitized["does_not_issue_execution_authority"] is not True:
            blockers.append("account_truth_authority_boundary_invalid")
        if sanitized["broker_submission_enabled"] is not False:
            blockers.append("account_truth_submission_boundary_invalid")
        unique_blockers = list(dict.fromkeys(blockers))
        source_core = {
            "schema_version": SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION,
            "evidence_connector_id": connector_id,
            "account_alias": normalized_account_alias,
            "source": sanitized,
            "source_freshness_status": freshness,
            "blockers": unique_blockers,
        }
        return {
            **source_core,
            "account_truth_fingerprint": _fingerprint(source_core),
            "generated_at": now.isoformat(),
            "current_source_age_seconds": age_seconds,
            "max_age_seconds": SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
            "review_status": "ready_to_record" if not unique_blockers else "blocked",
            "review_ready": not unique_blockers,
            "runtime_session_authority": "disabled",
            "capital_authority_change_enabled": False,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }

    def record(
        self,
        *,
        evidence_connector_id: str,
        account_alias: str,
        account_truth_fingerprint: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview(
            evidence_connector_id=evidence_connector_id,
            account_alias=account_alias,
        )
        rejection_reasons: list[str] = []
        if account_truth_fingerprint != preview["account_truth_fingerprint"]:
            rejection_reasons.append("account_truth_fingerprint_mismatch")
        if acknowledgement != SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if preview["blockers"]:
            rejection_reasons.append("session_start_account_truth_blocked")
        status = "rejected" if rejection_reasons else "recorded_clear"
        evidence = self._record_attempt(
            preview=preview,
            submitted_account_truth_fingerprint=account_truth_fingerprint,
            acknowledgement=acknowledgement,
            status=status,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            raise SessionStartAccountTruthRejected(
                "session-start Account Truth rejected: " + ", ".join(rejection_reasons),
                evidence=evidence,
            )
        return evidence

    def resolve(self, account_truth_fingerprint: str) -> dict[str, Any]:
        normalized = str(account_truth_fingerprint or "").strip()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            return _blocked_resolution(
                normalized, ["account_truth_fingerprint_invalid"]
            )
        for item in self.list_records(limit=500):
            if (
                item.get("status") == "recorded_clear"
                and item.get("account_truth_fingerprint") == normalized
            ):
                recorded_at = _parse_aware_timestamp(item.get("recorded_at"))
                now = _aware_utc(self._clock())
                if recorded_at is None:
                    return _blocked_resolution(
                        normalized,
                        ["account_truth_recorded_at_invalid"],
                    )
                if (now - recorded_at).total_seconds() > (
                    SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS
                ):
                    return _blocked_resolution(
                        normalized,
                        ["account_truth_record_expired"],
                    )
                current = self.preview(
                    evidence_connector_id=str(item.get("evidence_connector_id") or ""),
                    account_alias=str(item.get("account_alias") or ""),
                )
                if current["account_truth_fingerprint"] != normalized:
                    return _blocked_resolution(
                        normalized,
                        ["account_truth_source_changed"],
                    )
                if current["blockers"]:
                    return _blocked_resolution(
                        normalized,
                        ["account_truth_currently_blocked"],
                    )
                return {
                    "schema_version": SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION,
                    "status": "clear",
                    "record_id": str(item.get("record_id") or ""),
                    "account_truth_fingerprint": normalized,
                    "evidence_connector_id": str(
                        item.get("evidence_connector_id") or ""
                    ),
                    "account_alias": str(item.get("account_alias") or ""),
                    "source_fingerprint": str(item.get("source_fingerprint") or ""),
                    "import_run_id": str(item.get("import_run_id") or ""),
                    "source_captured_at": str(item.get("source_captured_at") or ""),
                    "recorded_at": item.get("recorded_at"),
                    "blockers": [],
                    "runtime_session_authority": "disabled",
                    "capital_authority_change_enabled": False,
                    "broker_submission_enabled": False,
                    "authorizes_execution": False,
                    "safety": _safety_flags(),
                }
        return _blocked_resolution(normalized, ["account_truth_record_not_found"])

    def list_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE,
            entity_type=SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE,
            source=SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def _record_attempt(
        self,
        *,
        preview: dict[str, Any],
        submitted_account_truth_fingerprint: str,
        acknowledgement: str,
        status: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        identity = {
            "account_truth_fingerprint": preview["account_truth_fingerprint"],
            "submitted_account_truth_fingerprint": (
                submitted_account_truth_fingerprint
            ),
            "evidence_connector_id": preview["evidence_connector_id"],
            "account_alias": preview["account_alias"],
            "source_fingerprint": preview["source"]["source_fingerprint"],
            "import_run_id": preview["source"]["import_run_id"],
            "source_captured_at": preview["source"]["captured_at"],
            "acknowledgement": acknowledgement,
            "status": status,
            "rejection_reasons": list(rejection_reasons),
        }
        record_id = _fingerprint(identity)
        payload = {
            "schema_version": SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION,
            "record_id": record_id,
            **identity,
            "source": preview["source"],
            "source_freshness_status": preview["source_freshness_status"],
            "review_blockers": list(preview["blockers"]),
            "runtime_session_authority": "disabled",
            "capital_authority_change_enabled": False,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE,
            entity_type=SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE,
            entity_id=record_id,
            source=SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        now = _aware_utc(self._clock())
        self._db.append_event_sync(
            event_type=SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE,
            entity_id=record_id,
            source=SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE,
            source_ref=preview["source"]["import_run_id"],
            payload=payload,
        )
        rows = self._db.list_events_sync(
            event_type=SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE,
            entity_type=SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE,
            entity_id=record_id,
            source=SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            raise RuntimeError("session-start Account Truth evidence was not recorded")
        return _event_response(rows[0], reused=False)


def resolve_session_start_account_truth_binding(
    provider: Callable[[str], dict[str, Any]] | None,
    *,
    fingerprint: str,
    expected_evidence_connector_id: str,
    expected_account_alias: str,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve one exact current Account Truth record for a session envelope."""

    normalized = str(fingerprint or "").strip()
    if not _FINGERPRINT_PATTERN.fullmatch(normalized):
        blocker = "session_start_account_truth_fingerprint_invalid"
        return _blocked_binding(normalized, blocker), [blocker]
    if not callable(provider):
        blocker = "session_start_account_truth_provider_unavailable"
        return _blocked_binding(normalized, blocker), [blocker]
    try:
        raw = provider(normalized) or {}
    except Exception:
        blocker = "session_start_account_truth_provider_failed"
        return _blocked_binding(normalized, blocker), [blocker]
    raw = raw if isinstance(raw, dict) else {}
    checks = (
        (raw.get("status") == "clear", "session_start_account_truth_not_clear"),
        (
            str(raw.get("account_truth_fingerprint") or "") == normalized,
            "session_start_account_truth_fingerprint_mismatch",
        ),
        (
            str(raw.get("evidence_connector_id") or "")
            == str(expected_evidence_connector_id or ""),
            "session_start_account_truth_connector_mismatch",
        ),
        (
            str(raw.get("account_alias") or "") == str(expected_account_alias or ""),
            "session_start_account_truth_account_mismatch",
        ),
        (
            _FINGERPRINT_PATTERN.fullmatch(str(raw.get("source_fingerprint") or ""))
            is not None,
            "session_start_account_truth_source_fingerprint_invalid",
        ),
        (
            bool(str(raw.get("import_run_id") or "")),
            "session_start_account_truth_import_run_missing",
        ),
        (
            raw.get("runtime_session_authority") == "disabled",
            "session_start_account_truth_authority_not_disabled",
        ),
        (
            raw.get("capital_authority_change_enabled") is False,
            "session_start_account_truth_capital_change_not_disabled",
        ),
        (
            raw.get("broker_submission_enabled") is False,
            "session_start_account_truth_submission_not_disabled",
        ),
        (
            raw.get("authorizes_execution") is False,
            "session_start_account_truth_unexpected_authority",
        ),
    )
    blockers = [reason for passed, reason in checks if not passed]
    provider_blockers = raw.get("blockers")
    if raw.get("status") != "clear" and isinstance(provider_blockers, list):
        blockers.extend(
            f"session_start_account_truth:{str(item)}"
            for item in provider_blockers
            if str(item) in _SAFE_RESOLUTION_BLOCKERS
        )
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": "karkinos.session_start_account_truth_binding.v1",
        "status": "pass" if not unique_blockers else "blocked",
        "record_id": str(raw.get("record_id") or ""),
        "account_truth_fingerprint": normalized,
        "evidence_connector_id": str(raw.get("evidence_connector_id") or ""),
        "account_alias": str(raw.get("account_alias") or ""),
        "source_fingerprint": str(raw.get("source_fingerprint") or ""),
        "import_run_id": str(raw.get("import_run_id") or ""),
        "source_captured_at": str(raw.get("source_captured_at") or ""),
        "recorded_at": str(raw.get("recorded_at") or ""),
        "blockers": unique_blockers,
        "runtime_session_authority": "disabled",
        "capital_authority_change_enabled": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }, unique_blockers


def _blocked_binding(fingerprint: str, blocker: str) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.session_start_account_truth_binding.v1",
        "status": "blocked",
        "record_id": "",
        "account_truth_fingerprint": fingerprint,
        "evidence_connector_id": "",
        "account_alias": "",
        "source_fingerprint": "",
        "import_run_id": "",
        "source_captured_at": "",
        "recorded_at": "",
        "blockers": [blocker],
        "runtime_session_authority": "disabled",
        "capital_authority_change_enabled": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }


def _sanitize_source(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(raw.get("status") or ""),
        "source_fingerprint": str(raw.get("source_fingerprint") or ""),
        "import_run_id": str(raw.get("import_run_id") or ""),
        "captured_at": str(raw.get("captured_at") or ""),
        "data_freshness_status": str(raw.get("data_freshness_status") or ""),
        "reconciliation_status": str(raw.get("reconciliation_status") or ""),
        "gate_status": str(raw.get("gate_status") or ""),
        "score": _safe_int(raw.get("score")),
        "cash_status": str(raw.get("cash_status") or ""),
        "position_status": str(raw.get("position_status") or ""),
        "fee_status": str(raw.get("fee_status") or ""),
        "cost_basis_status": str(raw.get("cost_basis_status") or ""),
        "unresolved_mismatch_count": _safe_int(raw.get("unresolved_mismatch_count")),
        "resolved_review_count": _safe_int(raw.get("resolved_review_count")),
        "does_not_mutate_production_ledger": (
            raw.get("does_not_mutate_production_ledger") is True
        ),
        "does_not_issue_execution_authority": (
            raw.get("does_not_issue_execution_authority") is True
        ),
        "broker_submission_enabled": raw.get("broker_submission_enabled") is True,
    }


def _blocked_resolution(fingerprint: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION,
        "status": "blocked",
        "record_id": "",
        "account_truth_fingerprint": fingerprint,
        "evidence_connector_id": "",
        "account_alias": "",
        "source_fingerprint": "",
        "import_run_id": "",
        "source_captured_at": "",
        "recorded_at": "",
        "blockers": list(dict.fromkeys(blockers)),
        "runtime_session_authority": "disabled",
        "capital_authority_change_enabled": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "safety": _safety_flags(),
    }


def _safe_int(value: Any) -> int | None:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return None


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        **payload,
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "reused": reused,
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_issue_or_enable_runtime_session": True,
        "does_not_issue_or_change_capital_authority": True,
        "does_not_mutate_account_truth": True,
        "does_not_mutate_oms_or_production_ledger": True,
        "does_not_contact_broker": True,
        "does_not_submit_or_cancel_orders": True,
    }


def _parse_aware_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
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
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
