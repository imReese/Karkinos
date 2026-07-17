"""Resolve the current persisted evidence for one non-submitting order dossier."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from server.services.capital_authorization_audit import (
    CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
    CAPITAL_AUTHORIZATION_EVENT_SOURCE,
    CAPITAL_AUTHORIZATION_EVENT_TYPE,
)
from server.services.execution_gateway_verification import (
    EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
    EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
    EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
    EXECUTION_GATEWAY_VERIFICATION_MAX_AGE_SECONDS,
)
from server.services.per_order_confirmation import build_order_fingerprint

CURRENT_PER_ORDER_DOSSIER_SCHEMA_VERSION = (
    "karkinos.current_per_order_confirmation_dossier.v1"
)
CURRENT_PER_ORDER_CANDIDATES_SCHEMA_VERSION = (
    "karkinos.current_per_order_confirmation_candidates.v1"
)
CURRENT_PER_ORDER_EVIDENCE_RESOLUTION_SCHEMA_VERSION = (
    "karkinos.current_per_order_evidence_resolution.v1"
)
CURRENT_PER_ORDER_MAX_CAPITAL_EVALUATION_SCAN = 500
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_BATCH_REFERENCE_PREFIX = "execution_batch_reconciliation:"
_GATEWAY_REFERENCE_PREFIX = "execution_gateway_verification:"


class CurrentPerOrderDossierService:
    """Resolve exact persisted evidence without accepting operator fingerprints."""

    def __init__(self, *, db: Any, dossier_service: Any) -> None:
        self._db = db
        self._dossier_service = dossier_service

    def list_candidates(self, *, limit: int = 20) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 100))
        orders = self._db.list_oms_orders_sync(
            status="manually_confirmed",
            limit=bounded_limit + 1,
        )
        truncated = len(orders) > bounded_limit
        candidates: list[dict[str, Any]] = []
        for order in orders[:bounded_limit]:
            dossier = self.preview_current(str(order.get("order_id") or ""))
            resolution = _mapping(dossier.get("evidence_resolution"))
            confirmation = _mapping(dossier.get("confirmation"))
            candidates.append(
                {
                    "order_id": str(order.get("order_id") or ""),
                    "symbol": str(order.get("symbol") or ""),
                    "side": str(order.get("side") or ""),
                    "asset_class": str(order.get("asset_class") or ""),
                    "quantity": _number_text(order.get("quantity")),
                    "order_type": str(order.get("order_type") or ""),
                    "limit_price": (
                        _number_text(order.get("limit_price"))
                        if order.get("limit_price") is not None
                        else None
                    ),
                    "oms_status": str(order.get("status") or ""),
                    "updated_at": str(order.get("updated_at") or ""),
                    "order_fingerprint": str(dossier.get("order_fingerprint") or ""),
                    "dossier_fingerprint": str(
                        dossier.get("dossier_fingerprint") or ""
                    ),
                    "review_status": str(dossier.get("review_status") or ""),
                    "review_ready": bool(dossier.get("review_ready")),
                    "review_blockers": [
                        str(item) for item in dossier.get("review_blockers") or []
                    ],
                    "evidence_resolution_status": str(
                        resolution.get("status") or "blocked"
                    ),
                    "confirmation_status": str(confirmation.get("status") or "missing"),
                    "authorizes_execution": False,
                }
            )
        return {
            "schema_version": CURRENT_PER_ORDER_CANDIDATES_SCHEMA_VERSION,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "truncated": truncated,
            "selection_contract": "canonical_manually_confirmed_oms_orders_only",
            **_read_boundary(),
        }

    def preview_current(self, order_id: str) -> dict[str, Any]:
        order = self._require_order(order_id)
        resolution = self._resolve_current_evidence(order)
        dossier = self._dossier_service.preview_dossier(
            order_id,
            capital_evaluation_input_fingerprint=str(
                resolution.get("capital_evaluation_input_fingerprint") or ""
            ),
            prior_batch_reconciliation_fingerprint=str(
                resolution.get("prior_batch_reconciliation_fingerprint") or ""
            ),
            execution_gateway_verification_fingerprint=str(
                resolution.get("execution_gateway_verification_fingerprint") or ""
            ),
        )
        resolution_blockers = [str(item) for item in resolution.get("blockers") or []]
        review_blockers = list(
            dict.fromkeys(
                [
                    *resolution_blockers,
                    *[str(item) for item in dossier.get("review_blockers") or []],
                ]
            )
        )
        required_operator_approval = (
            {
                "action": "attest_per_order_dossier",
                "artifact_type": "per_order_dossier",
                "artifact_fingerprint": str(dossier.get("dossier_fingerprint") or ""),
            }
            if not review_blockers
            else None
        )
        return {
            **dossier,
            "schema_version": CURRENT_PER_ORDER_DOSSIER_SCHEMA_VERSION,
            "underlying_dossier_schema_version": str(
                dossier.get("schema_version") or ""
            ),
            "evidence_resolution": resolution,
            "review_blockers": review_blockers,
            "review_status": (
                "review_ready_non_submitting"
                if not review_blockers
                else "blocked_review"
            ),
            "review_ready": not review_blockers,
            "required_operator_approval": required_operator_approval,
            "current_evidence_resolved": not resolution_blockers,
            "submission_status": "blocked",
            "authorizes_execution": False,
            **_read_boundary(),
        }

    def record_current_confirmation(
        self,
        order_id: str,
        *,
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        current = self.preview_current(order_id)
        resolution = _mapping(current.get("evidence_resolution"))
        return self._dossier_service.record_confirmation(
            order_id,
            capital_evaluation_input_fingerprint=str(
                resolution.get("capital_evaluation_input_fingerprint") or ""
            ),
            prior_batch_reconciliation_fingerprint=str(
                resolution.get("prior_batch_reconciliation_fingerprint") or ""
            ),
            execution_gateway_verification_fingerprint=str(
                resolution.get("execution_gateway_verification_fingerprint") or ""
            ),
            dossier_fingerprint=dossier_fingerprint,
            operator_label=operator_label,
            operator_approval_id=operator_approval_id,
            acknowledgement=acknowledgement,
        )

    def _require_order(self, order_id: str) -> dict[str, Any]:
        order = self._db.get_oms_order_sync(order_id)
        if order is None:
            raise KeyError(f"OMS order not found: {order_id}")
        return dict(order)

    def _resolve_current_evidence(self, order: dict[str, Any]) -> dict[str, Any]:
        order_fingerprint = build_order_fingerprint(order)
        rows = self._db.list_events_sync(
            event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE,
            entity_type=CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
            source=CAPITAL_AUTHORIZATION_EVENT_SOURCE,
            limit=CURRENT_PER_ORDER_MAX_CAPITAL_EVALUATION_SCAN + 1,
        )
        scan_truncated = len(rows) > CURRENT_PER_ORDER_MAX_CAPITAL_EVALUATION_SCAN
        selected: tuple[dict[str, Any], dict[str, Any]] | None = None
        for row in rows[:CURRENT_PER_ORDER_MAX_CAPITAL_EVALUATION_SCAN]:
            payload = _json_object(row.get("payload_json"))
            context = _mapping(payload.get("context"))
            if order_fingerprint in {
                str(context.get("order_fingerprint") or ""),
                str(context.get("manual_confirmation_fingerprint") or ""),
            }:
                selected = (row, payload)
                break

        blockers: list[str] = []
        if selected is None:
            blockers.append("current_capital_evaluation_not_found")
            if scan_truncated:
                blockers.append("current_capital_evaluation_scan_truncated")
            return _resolution_response(
                order_fingerprint=order_fingerprint,
                status="missing",
                blockers=blockers,
                scan_truncated=scan_truncated,
            )

        row, payload = selected
        context = _mapping(payload.get("context"))
        decision = _mapping(payload.get("decision"))
        input_fingerprint = str(row.get("entity_id") or "")
        if not _FINGERPRINT_PATTERN.fullmatch(input_fingerprint):
            blockers.append("current_capital_evaluation_input_fingerprint_invalid")
        if str(decision.get("input_fingerprint") or "") != input_fingerprint:
            blockers.append("current_capital_evaluation_decision_fingerprint_mismatch")

        references = [
            *[str(item) for item in context.get("evidence_refs") or []],
            *[str(item) for item in decision.get("evidence_refs") or []],
        ]
        batch_fingerprint, batch_blockers = _resolve_reference(
            references,
            prefix=_BATCH_REFERENCE_PREFIX,
            blocker_stem="current_prior_batch_reconciliation_ref",
        )
        gateway_fingerprint, gateway_blockers = _resolve_reference(
            references,
            prefix=_GATEWAY_REFERENCE_PREFIX,
            blocker_stem="current_execution_gateway_verification_ref",
        )
        blockers.extend(batch_blockers)
        blockers.extend(gateway_blockers)
        unique_blockers = list(dict.fromkeys(blockers))
        return _resolution_response(
            order_fingerprint=order_fingerprint,
            status="resolved" if not unique_blockers else "blocked",
            blockers=unique_blockers,
            scan_truncated=scan_truncated,
            selected_event_id=int(row.get("id") or 0),
            selected_recorded_at=str(row.get("timestamp") or ""),
            capital_evaluation_input_fingerprint=input_fingerprint,
            prior_batch_reconciliation_fingerprint=batch_fingerprint,
            execution_gateway_verification_fingerprint=gateway_fingerprint,
        )


def resolve_persisted_execution_gateway_verification(
    db: Any,
    verification_fingerprint: str,
    *,
    clock: Any | None = None,
) -> dict[str, Any]:
    """Resolve one recorded verification without calling a runtime gateway."""

    normalized = str(verification_fingerprint or "").strip()
    if not _FINGERPRINT_PATTERN.fullmatch(normalized):
        return _blocked_gateway_verification(
            normalized,
            ["verification_fingerprint_invalid"],
        )
    rows = db.list_events_sync(
        event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
        entity_type=EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
        source=EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
        limit=500,
    )
    selected: tuple[dict[str, Any], dict[str, Any]] | None = None
    for row in rows:
        payload = _json_object(row.get("payload_json"))
        if str(payload.get("verification_fingerprint") or "") == normalized:
            selected = (row, payload)
            break
    if selected is None:
        return _blocked_gateway_verification(normalized, ["verification_not_found"])

    row, payload = selected
    blockers: list[str] = []
    if payload.get("status") != "recorded_non_submitting_runtime_verification":
        blockers.append("verification_not_clear")
    if payload.get("runtime_gateway_verified") is not True:
        blockers.append("verification_runtime_gate_not_verified")
    if (
        str(payload.get("runtime_verification_status") or "")
        != "verified_non_submitting_dry_run"
    ):
        blockers.append("verification_runtime_status_invalid")
    if payload.get("runtime_execution_authority") != "disabled":
        blockers.append("verification_authority_boundary_invalid")
    if payload.get("broker_submission_enabled") is not False:
        blockers.append("verification_submission_boundary_invalid")
    if payload.get("authorizes_execution") is not False:
        blockers.append("verification_unexpected_authority")

    recorded_at = _parse_timestamp(row.get("timestamp"))
    current_time = _aware_utc((clock or (lambda: datetime.now(timezone.utc)))())
    if recorded_at is None:
        blockers.append("verification_recorded_at_invalid")
    else:
        age_seconds = (current_time - recorded_at).total_seconds()
        if age_seconds < -30:
            blockers.append("verification_recorded_at_in_future")
        elif age_seconds > EXECUTION_GATEWAY_VERIFICATION_MAX_AGE_SECONDS:
            blockers.append("verification_expired")
    if blockers:
        return _blocked_gateway_verification(normalized, blockers)

    order_contract = _mapping(payload.get("order_contract"))
    return {
        "status": "clear",
        "verification_id": str(payload.get("verification_id") or ""),
        "verification_fingerprint": normalized,
        "gateway_id": str(payload.get("gateway_id") or ""),
        "evidence_connector_id": str(payload.get("evidence_connector_id") or ""),
        "account_alias": str(payload.get("account_alias") or ""),
        "order_id": str(payload.get("order_id") or ""),
        "order_fingerprint": str(payload.get("order_fingerprint") or ""),
        "order_contract": dict(order_contract),
        "recorded_at": recorded_at.isoformat(),
        "runtime_gateway_verified": True,
        "runtime_verification_status": "verified_non_submitting_dry_run",
        "blockers": [],
        "runtime_execution_authority": "disabled",
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "persisted_evidence_only": True,
        "provider_contact_performed": False,
        "runtime_gateway_call_performed": False,
    }


def _resolve_reference(
    references: list[str],
    *,
    prefix: str,
    blocker_stem: str,
) -> tuple[str, list[str]]:
    matched = [item[len(prefix) :] for item in references if item.startswith(prefix)]
    valid = sorted(
        {item for item in matched if _FINGERPRINT_PATTERN.fullmatch(item) is not None}
    )
    blockers: list[str] = []
    if any(_FINGERPRINT_PATTERN.fullmatch(item) is None for item in matched):
        blockers.append(f"{blocker_stem}_invalid")
    if not valid:
        blockers.append(f"{blocker_stem}_missing")
        return "", blockers
    if len(valid) != 1:
        blockers.append(f"{blocker_stem}_ambiguous")
        return "", blockers
    return valid[0], blockers


def _resolution_response(
    *,
    order_fingerprint: str,
    status: str,
    blockers: list[str],
    scan_truncated: bool,
    selected_event_id: int | None = None,
    selected_recorded_at: str = "",
    capital_evaluation_input_fingerprint: str = "",
    prior_batch_reconciliation_fingerprint: str = "",
    execution_gateway_verification_fingerprint: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": CURRENT_PER_ORDER_EVIDENCE_RESOLUTION_SCHEMA_VERSION,
        "status": status,
        "order_fingerprint": order_fingerprint,
        "selected_capital_evaluation_event_id": selected_event_id,
        "selected_capital_evaluation_recorded_at": selected_recorded_at,
        "capital_evaluation_input_fingerprint": (capital_evaluation_input_fingerprint),
        "prior_batch_reconciliation_fingerprint": (
            prior_batch_reconciliation_fingerprint
        ),
        "execution_gateway_verification_fingerprint": (
            execution_gateway_verification_fingerprint
        ),
        "blockers": list(dict.fromkeys(blockers)),
        "scan_limit": CURRENT_PER_ORDER_MAX_CAPITAL_EVALUATION_SCAN,
        "scan_truncated": scan_truncated,
        **_read_boundary(),
    }


def _read_boundary() -> dict[str, Any]:
    return {
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


def _blocked_gateway_verification(
    fingerprint: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "verification_id": "",
        "verification_fingerprint": fingerprint,
        "gateway_id": "",
        "evidence_connector_id": "",
        "account_alias": "",
        "order_id": "",
        "order_fingerprint": "",
        "order_contract": {},
        "recorded_at": "",
        "runtime_gateway_verified": False,
        "runtime_verification_status": "blocked",
        "blockers": list(dict.fromkeys(blockers)),
        "runtime_execution_authority": "disabled",
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "persisted_evidence_only": True,
        "provider_contact_performed": False,
        "runtime_gateway_call_performed": False,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _number_text(value: Any) -> str:
    if value is None:
        return ""
    return format(value, "g") if isinstance(value, float) else str(value)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
