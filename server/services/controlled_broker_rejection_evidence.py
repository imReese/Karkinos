"""Read-only evidence package for one rejected controlled submission."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from server.services.per_order_confirmation import build_order_fingerprint

CONTROLLED_BROKER_REJECTION_EVIDENCE_SCHEMA_VERSION = (
    "karkinos.controlled_broker_rejection_evidence.v1"
)
CONTROLLED_BROKER_REJECTION_EXPORT_SCHEMA_VERSION = (
    "karkinos.controlled_broker_rejection_evidence_export.v1"
)
CONTROLLED_BROKER_REJECTION_EXPORT_ACKNOWLEDGEMENT = (
    "export_exact_rejection_evidence_without_retry_or_authority_change"
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REASON_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,255}$")
_REASON_CODE_PATTERN = re.compile(r"^controlled_broker_[a-z0-9_]{1,220}$")
_DEFINITIVE_GATEWAY_REJECTION_STATUSES = frozenset({"rejected", "not_found"})
_LOCAL_REJECTION_STATUSES = frozenset({"rejected_before_gateway_call"})
_REVIEWABLE_RESULT_STATUSES = (
    _DEFINITIVE_GATEWAY_REJECTION_STATUSES | _LOCAL_REJECTION_STATUSES
)


class ControlledBrokerRejectionEvidenceRejected(ValueError):
    """Raised when an export no longer matches the reviewed rejection facts."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledBrokerRejectionEvidenceService:
    """Explain one persisted rejection without contacting or retrying a broker."""

    def __init__(
        self,
        *,
        db: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def preview(self, *, submit_intent_id: str) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized_intent_id = str(submit_intent_id or "").strip().lower()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_intent_id):
            blockers.append("controlled_broker_rejection_submit_intent_id_invalid")

        intent = (
            self._db.get_controlled_broker_submit_intent_sync(normalized_intent_id)
            if _FINGERPRINT_PATTERN.fullmatch(normalized_intent_id)
            else None
        )
        if intent is None:
            blockers.append("controlled_broker_rejection_submit_intent_not_found")
            intent = {}
        elif str(intent.get("status") or "") != "rejected":
            blockers.append("controlled_broker_rejection_evidence_not_required")

        order_id = str(intent.get("order_id") or "")
        if order_id and not _ID_PATTERN.fullmatch(order_id):
            blockers.append("controlled_broker_rejection_order_id_invalid")
        order = self._db.get_oms_order_sync(order_id) if order_id else None
        if order is None:
            blockers.append("controlled_broker_rejection_oms_order_not_found")
            order = {}
        elif str(order.get("status") or "") != "rejected":
            blockers.append("controlled_broker_rejection_oms_status_mismatch")
        if order and str(intent.get("order_fingerprint") or "") != (
            build_order_fingerprint(order)
        ):
            blockers.append("controlled_broker_rejection_order_contract_changed")

        payload = _json_object(intent.get("payload_json"))
        result = _sanitize_persisted_result(_json_object(intent.get("result_json")))
        submit_fingerprint = str(intent.get("submit_fingerprint") or "")
        if not _FINGERPRINT_PATTERN.fullmatch(submit_fingerprint):
            blockers.append("controlled_broker_rejection_submit_fingerprint_invalid")
        identity = {
            "gateway_id": str(intent.get("gateway_id") or ""),
            "account_alias": str(
                intent.get("account_alias") or payload.get("account_alias") or ""
            ),
            "client_order_id": str(intent.get("client_order_id") or ""),
            "operator_id": str(intent.get("operator_id") or ""),
        }
        for key, value in identity.items():
            if not _ID_PATTERN.fullmatch(value):
                blockers.append(f"controlled_broker_rejection_{key}_invalid")

        intent_broker_order_id = str(intent.get("broker_order_id") or "")
        result_broker_order_id = str(result.get("broker_order_id") or "")
        if intent_broker_order_id or result_broker_order_id:
            blockers.append("controlled_broker_rejection_broker_order_id_present")

        result_status = str(result.get("status") or "")
        result_submitted = result.get("submitted")
        result_definitive = result.get("definitive") is True
        result_client_order_id = str(result.get("client_order_id") or "")
        result_order_fingerprint = str(result.get("order_fingerprint") or "")
        if result_status in _LOCAL_REJECTION_STATUSES:
            rejection_classification = "local_pre_gateway_rejection"
            if result_submitted is not False:
                blockers.append("controlled_broker_rejection_local_result_ambiguous")
        elif result_status in _DEFINITIVE_GATEWAY_REJECTION_STATUSES:
            rejection_classification = "definitive_gateway_rejection"
            if result_submitted is not False or not result_definitive:
                blockers.append("controlled_broker_rejection_gateway_result_ambiguous")
            if result_client_order_id != identity["client_order_id"]:
                blockers.append("controlled_broker_rejection_client_order_id_mismatch")
            if result_order_fingerprint and result_order_fingerprint != str(
                intent.get("order_fingerprint") or ""
            ):
                blockers.append(
                    "controlled_broker_rejection_order_fingerprint_mismatch"
                )
        else:
            rejection_classification = "unclassified_rejection"
            blockers.append("controlled_broker_rejection_result_not_definitive")

        order_quantity = _decimal_string(order.get("quantity"))
        order_contract = {
            "symbol": str(order.get("symbol") or ""),
            "side": str(order.get("side") or "").lower(),
            "asset_class": str(order.get("asset_class") or ""),
            "quantity": order_quantity,
            "order_type": str(order.get("order_type") or ""),
            "limit_price": _optional_decimal_string(order.get("limit_price")),
        }
        if not order_contract["symbol"] or not order_contract["side"]:
            blockers.append("controlled_broker_rejection_order_contract_incomplete")
        if _decimal(order_quantity) <= 0:
            blockers.append("controlled_broker_rejection_order_quantity_invalid")

        evidence_as_of = str(intent.get("updated_at") or "")
        if _parse_timestamp(evidence_as_of) is None:
            blockers.append("controlled_broker_rejection_evidence_as_of_missing")
        evidence_core = {
            "schema_version": CONTROLLED_BROKER_REJECTION_EVIDENCE_SCHEMA_VERSION,
            "submit_intent_id": normalized_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "order_id": order_id,
            "order_fingerprint": str(intent.get("order_fingerprint") or ""),
            "identity": identity,
            "order": order_contract,
            "rejection_evidence": {
                "classification": rejection_classification,
                "intent_status": str(intent.get("status") or "not_found"),
                "broker_status": str(intent.get("broker_status") or ""),
                "result_status": result_status,
                "submitted": result_submitted,
                "definitive": result_definitive,
                "error_type": str(result.get("error_type") or ""),
                "reason_codes": list(result.get("reason_codes") or []),
                "result_fingerprint": _fingerprint(result),
                "prepared_at": str(intent.get("prepared_at") or ""),
                "evidence_as_of": evidence_as_of,
            },
            "retry_policy": {
                "same_intent_retry_allowed": False,
                "same_client_order_id_retry_allowed": False,
                "automatic_retry_allowed": False,
                "new_order_requires_new_decision_and_all_gates": True,
            },
        }
        review_fingerprint = _fingerprint(evidence_core)
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **evidence_core,
            "review_fingerprint": review_fingerprint,
            "fingerprint_scope": (
                "submit intent, canonical OMS order contract, sanitized persisted "
                "rejection result, and exact gateway/client/operator identities"
            ),
            "generated_at": now.isoformat(),
            "status": "ready_for_human_review" if not unique_blockers else "blocked",
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "required_acknowledgement": (
                CONTROLLED_BROKER_REJECTION_EXPORT_ACKNOWLEDGEMENT
            ),
            "human_steps": [
                "Review whether the rejection occurred before the gateway call or is a definitive gateway response.",
                "Do not retry the persisted submit intent or reuse its client order id.",
                "If the investment decision remains valid, start a new Decision, risk, Account Truth, manual confirmation, and authority review.",
                "Keep this artifact with the incident or post-decision review evidence.",
            ],
            "assumptions": [
                "The persisted controlled submit intent and OMS order are the canonical local submission facts.",
                "Only the allowlisted sanitized gateway-result fields are reviewable here.",
                "A rejection artifact does not prove a later order is safe or authorized.",
            ],
            "risk_impact": (
                "Read-only evidence packaging only. The same intent remains terminal and "
                "cannot be retried by this boundary."
            ),
            "safety": _safety_flags(),
            "limitations": [
                "This report does not contact a provider or broker and cannot add missing provider reason text.",
                "It does not create, submit, retry, cancel, reconcile, clear, post, or correct an order.",
                "It does not change OMS, ledger, Account Truth, risk, kill switch, capital, or execution authority.",
            ],
        }

    def export(
        self,
        *,
        submit_intent_id: str,
        review_fingerprint: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview(submit_intent_id=submit_intent_id)
        blockers: list[str] = []
        if acknowledgement != CONTROLLED_BROKER_REJECTION_EXPORT_ACKNOWLEDGEMENT:
            blockers.append("controlled_broker_rejection_acknowledgement_mismatch")
        if str(review_fingerprint or "") != str(
            preview.get("review_fingerprint") or ""
        ):
            blockers.append("controlled_broker_rejection_fingerprint_mismatch")
        blockers.extend(str(item) for item in preview.get("blockers") or [])
        if blockers:
            evidence = {
                **preview,
                "status": "rejected",
                "ready": False,
                "blockers": list(dict.fromkeys(blockers)),
                "export_performed": False,
                "safety": _safety_flags(),
            }
            raise ControlledBrokerRejectionEvidenceRejected(
                "controlled broker rejection evidence export rejected",
                evidence=evidence,
            )

        artifact = {
            key: value
            for key, value in preview.items()
            if key not in {"generated_at", "status", "ready", "blockers"}
        }
        artifact.update(
            {
                "schema_version": CONTROLLED_BROKER_REJECTION_EXPORT_SCHEMA_VERSION,
                "export_fingerprint": _fingerprint(
                    {
                        "domain": CONTROLLED_BROKER_REJECTION_EXPORT_SCHEMA_VERSION,
                        "review_fingerprint": preview["review_fingerprint"],
                        "acknowledgement": acknowledgement,
                    }
                ),
                "evidence_as_of": preview["rejection_evidence"]["evidence_as_of"],
                "operator_acknowledgement": acknowledgement,
                "rejection_review_recorded": False,
                "retry_performed": False,
            }
        )
        content = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True)
        return {
            "schema_version": CONTROLLED_BROKER_REJECTION_EXPORT_SCHEMA_VERSION,
            "status": "export_ready",
            "review_fingerprint": preview["review_fingerprint"],
            "export_fingerprint": artifact["export_fingerprint"],
            "filename": (
                f"karkinos-rejection-{preview['order_id']}-"
                f"{preview['review_fingerprint'][:12]}.json"
            ),
            "content_type": "application/json",
            "content": content,
            "artifact": artifact,
            "export_performed": True,
            "safety": _safety_flags(),
        }


def _sanitize_persisted_result(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "").lower()
    client_order_id = str(raw.get("client_order_id") or "")
    order_fingerprint = str(raw.get("order_fingerprint") or "")
    broker_order_id = str(raw.get("broker_order_id") or "")
    error_type = str(raw.get("error_type") or "")
    raw_reasons = raw.get("blockers") or raw.get("reason_codes") or []
    reason_codes = (
        [str(item) for item in raw_reasons if _REASON_CODE_PATTERN.fullmatch(str(item))]
        if isinstance(raw_reasons, list)
        else []
    )
    return {
        "status": status if status in _REVIEWABLE_RESULT_STATUSES else "unknown",
        "client_order_id": (
            client_order_id if _ID_PATTERN.fullmatch(client_order_id) else ""
        ),
        "order_fingerprint": (
            order_fingerprint
            if _FINGERPRINT_PATTERN.fullmatch(order_fingerprint)
            else ""
        ),
        "broker_order_id": (
            broker_order_id if _ID_PATTERN.fullmatch(broker_order_id) else ""
        ),
        "submitted": (
            raw.get("submitted") if raw.get("submitted") in {True, False} else None
        ),
        "definitive": raw.get("definitive") is True,
        "error_type": (error_type if _REASON_PATTERN.fullmatch(error_type) else ""),
        "reason_codes": list(dict.fromkeys(reason_codes)),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "reads_persisted_facts_only": True,
        "provider_contact_performed": False,
        "broker_query_performed": False,
        "broker_submission_performed": False,
        "broker_retry_performed": False,
        "broker_cancel_performed": False,
        "oms_mutated": False,
        "production_ledger_mutated": False,
        "account_truth_mutated": False,
        "risk_state_mutated": False,
        "kill_switch_mutated": False,
        "capital_authority_changed": False,
        "authorizes_submission": False,
        "authorizes_retry": False,
        "authorizes_cancellation": False,
        "releases_submission_interlock": False,
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")


def _decimal_string(value: Any) -> str:
    normalized = _decimal(value).normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _optional_decimal_string(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return _decimal_string(value)


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
