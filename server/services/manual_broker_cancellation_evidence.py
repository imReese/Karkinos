"""Broker-neutral, non-authorizing manual cancellation ticket evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_order_lifecycle import (
    BrokerOrderLifecycleEvidenceRepository,
)
from server.services.per_order_confirmation import build_order_fingerprint

MANUAL_BROKER_CANCELLATION_TICKET_SCHEMA_VERSION = (
    "karkinos.manual_broker_cancellation_ticket.v1"
)
MANUAL_BROKER_CANCELLATION_EXPORT_SCHEMA_VERSION = (
    "karkinos.manual_broker_cancellation_ticket_export.v1"
)
MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT = (
    "prepare_manual_broker_cancellation_ticket_without_broker_contact"
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CANCELLABLE_LIFECYCLE_STATUSES = frozenset({"submitted", "open", "partially_filled"})


class ManualBrokerCancellationEvidenceRejected(ValueError):
    """Raised when an export cannot remain bound to the reviewed preview."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ManualBrokerCancellationEvidenceService:
    """Prepare a human cancellation package without contacting a broker."""

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
            blockers.append("manual_broker_cancel_submit_intent_id_invalid")

        intent = (
            self._db.get_controlled_broker_submit_intent_sync(normalized_intent_id)
            if _FINGERPRINT_PATTERN.fullmatch(normalized_intent_id)
            else None
        )
        if intent is None:
            blockers.append("manual_broker_cancel_submit_intent_not_found")
            intent = {}
        elif str(intent.get("status") or "") != "submitted":
            blockers.append("manual_broker_cancel_submit_intent_not_submitted")

        order_id = str(intent.get("order_id") or "")
        order = self._db.get_oms_order_sync(order_id) if order_id else None
        if order is None:
            blockers.append("manual_broker_cancel_oms_order_not_found")
            order = {}
        elif str(order.get("status") or "") != "submitted":
            blockers.append("manual_broker_cancel_oms_order_not_submitted")
        if order and str(intent.get("order_fingerprint") or "") != (
            build_order_fingerprint(order)
        ):
            blockers.append("manual_broker_cancel_order_contract_changed")

        payload = _json_object(intent.get("payload_json"))
        identity = {
            "gateway_id": str(intent.get("gateway_id") or ""),
            "account_alias": str(
                intent.get("account_alias") or payload.get("account_alias") or ""
            ),
            "broker_order_id": str(intent.get("broker_order_id") or ""),
            "client_order_id": str(intent.get("client_order_id") or ""),
        }
        for key, value in identity.items():
            if not _ID_PATTERN.fullmatch(value):
                blockers.append(f"manual_broker_cancel_{key}_invalid")

        lifecycle = self._resolve_lifecycle(identity)
        if str(lifecycle.get("status") or "") != "found":
            blockers.append("manual_broker_cancel_exact_lifecycle_evidence_unavailable")
            blockers.extend(str(item) for item in lifecycle.get("blockers") or [])
        collector = _mapping(lifecycle.get("collector_evidence"))
        if (
            bool(collector.get("required"))
            and str(collector.get("status") or "") != "healthy"
        ):
            blockers.append("manual_broker_cancel_lifecycle_collector_unhealthy")
            blockers.extend(str(item) for item in collector.get("blockers") or [])

        observation = _mapping(lifecycle.get("observation"))
        lifecycle_order = _mapping(lifecycle.get("order"))
        lifecycle_status = str(lifecycle_order.get("status") or "")
        if lifecycle_status and lifecycle_status not in (
            _CANCELLABLE_LIFECYCLE_STATUSES
        ):
            blockers.append("manual_broker_cancel_lifecycle_not_cancellable")
        if lifecycle_order:
            if str(lifecycle_order.get("symbol") or "") != str(
                order.get("symbol") or ""
            ):
                blockers.append("manual_broker_cancel_symbol_mismatch")
            if (
                str(lifecycle_order.get("side") or "")
                != str(order.get("side") or "").lower()
            ):
                blockers.append("manual_broker_cancel_side_mismatch")

        order_quantity = abs(_decimal(order.get("quantity")))
        lifecycle_quantity = abs(_decimal(lifecycle_order.get("order_quantity")))
        filled_quantity = abs(
            _decimal(lifecycle_order.get("cumulative_filled_quantity"))
        )
        cancelled_quantity = abs(_decimal(lifecycle_order.get("cancelled_quantity")))
        remaining_quantity = lifecycle_quantity - filled_quantity - cancelled_quantity
        if order_quantity <= 0 or lifecycle_quantity != order_quantity:
            blockers.append("manual_broker_cancel_quantity_mismatch")
        if remaining_quantity <= 0:
            blockers.append("manual_broker_cancel_no_remaining_quantity")

        provider = str(observation.get("provider") or "")
        if not provider:
            blockers.append("manual_broker_cancel_provider_identity_missing")
        if str(observation.get("validation_status") or "") != "pass":
            blockers.append("manual_broker_cancel_lifecycle_validation_not_pass")
        if not str(observation.get("observation_id") or ""):
            blockers.append("manual_broker_cancel_observation_identity_missing")
        if not str(observation.get("evidence_fingerprint") or ""):
            blockers.append("manual_broker_cancel_evidence_fingerprint_missing")

        ticket_core = {
            "schema_version": MANUAL_BROKER_CANCELLATION_TICKET_SCHEMA_VERSION,
            "submit_intent_id": normalized_intent_id,
            "submit_fingerprint": str(intent.get("submit_fingerprint") or ""),
            "order_id": order_id,
            "order_fingerprint": str(intent.get("order_fingerprint") or ""),
            "provider": provider,
            "identity": identity,
            "order": {
                "symbol": str(order.get("symbol") or ""),
                "side": str(order.get("side") or "").lower(),
                "asset_class": str(order.get("asset_class") or ""),
                "order_type": str(order.get("order_type") or ""),
                "limit_price": _optional_decimal_string(order.get("limit_price")),
                "order_quantity": _decimal_string(order_quantity),
                "lifecycle_status": lifecycle_status,
                "filled_quantity": _decimal_string(filled_quantity),
                "cancelled_quantity": _decimal_string(cancelled_quantity),
                "remaining_quantity": _decimal_string(remaining_quantity),
            },
            "lifecycle_evidence": {
                "observation_id": str(observation.get("observation_id") or ""),
                "evidence_fingerprint": str(
                    observation.get("evidence_fingerprint") or ""
                ),
                "source_sequence": int(observation.get("source_sequence") or 0),
                "captured_at": str(observation.get("captured_at") or ""),
                "source_name": str(observation.get("source_name") or ""),
                "collector_run_id": str(collector.get("matching_run_id") or ""),
                "collector_status": str(collector.get("status") or ""),
            },
        }
        ticket_fingerprint = _fingerprint(ticket_core)
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **ticket_core,
            "ticket_fingerprint": ticket_fingerprint,
            "fingerprint_scope": (
                "submit intent, OMS order contract, exact broker identities, and "
                "latest persisted lifecycle observation"
            ),
            "generated_at": now.isoformat(),
            "status": (
                "ready_for_manual_broker_action" if not unique_blockers else "blocked"
            ),
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "required_acknowledgement": (MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT),
            "human_steps": [
                "Open the separately reviewed broker interface; Karkinos will not open or call it.",
                "Find the exact order using both broker_order_id and client_order_id.",
                "Verify symbol, side, lifecycle status, and remaining quantity before requesting cancellation.",
                "After the broker responds, explicitly ingest a newer lifecycle observation and reconcile Account Truth.",
            ],
            "assumptions": [
                "The latest persisted exact-identity lifecycle observation is the evidence available at preview time.",
                "The human operator independently verifies the broker-side order before acting.",
                "A prepared or exported ticket is not proof that the broker accepted a cancellation.",
            ],
            "risk_impact": (
                "No execution authority changes. A stale preview can only be exported when its "
                "fingerprint still matches a fresh persisted-evidence preview."
            ),
            "safety": _safety_flags(),
            "limitations": [
                "This package is provider-neutral and does not register or call an edge adapter.",
                "It cannot submit or cancel an order and does not change OMS, ledger, risk, kill switch, or capital authority.",
                "Only newer persisted broker lifecycle and Account Truth evidence can prove a cancellation and clear downstream gates.",
            ],
        }

    def export(
        self,
        *,
        submit_intent_id: str,
        ticket_fingerprint: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview(submit_intent_id=submit_intent_id)
        blockers: list[str] = []
        if acknowledgement != MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT:
            blockers.append("manual_broker_cancel_acknowledgement_mismatch")
        if str(ticket_fingerprint or "") != str(
            preview.get("ticket_fingerprint") or ""
        ):
            blockers.append("manual_broker_cancel_ticket_fingerprint_mismatch")
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
            raise ManualBrokerCancellationEvidenceRejected(
                "manual broker cancellation ticket export rejected",
                evidence=evidence,
            )

        artifact = {
            key: value
            for key, value in preview.items()
            if key not in {"generated_at", "status", "ready", "blockers"}
        }
        artifact.update(
            {
                "schema_version": MANUAL_BROKER_CANCELLATION_EXPORT_SCHEMA_VERSION,
                "export_fingerprint": _fingerprint(
                    {
                        "domain": MANUAL_BROKER_CANCELLATION_EXPORT_SCHEMA_VERSION,
                        "ticket_fingerprint": preview["ticket_fingerprint"],
                        "acknowledgement": acknowledgement,
                    }
                ),
                "evidence_as_of": preview["lifecycle_evidence"]["captured_at"],
                "operator_acknowledgement": acknowledgement,
                "broker_cancel_performed": False,
                "cancellation_proven": False,
            }
        )
        content = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True)
        return {
            "schema_version": MANUAL_BROKER_CANCELLATION_EXPORT_SCHEMA_VERSION,
            "status": "export_ready",
            "ticket_fingerprint": preview["ticket_fingerprint"],
            "export_fingerprint": artifact["export_fingerprint"],
            "filename": (
                f"karkinos-manual-cancel-{preview['order_id']}-"
                f"{preview['ticket_fingerprint'][:12]}.json"
            ),
            "content_type": "application/json",
            "content": content,
            "artifact": artifact,
            "export_performed": True,
            "safety": _safety_flags(),
        }

    def _resolve_lifecycle(self, identity: dict[str, str]) -> dict[str, Any]:
        db_path = getattr(self._db, "_path", None)
        if db_path is None:
            return {
                "status": "not_configured",
                "identity": identity,
                "blockers": ["manual_broker_cancel_database_path_unavailable"],
            }
        return BrokerOrderLifecycleEvidenceRepository(
            Path(db_path),
            ensure_schema=False,
        ).resolve_order(**identity)


def _safety_flags() -> dict[str, bool]:
    return {
        "reads_persisted_facts_only": True,
        "provider_contact_performed": False,
        "broker_submission_performed": False,
        "broker_cancel_performed": False,
        "cancellation_proven": False,
        "oms_mutated": False,
        "production_ledger_mutated": False,
        "risk_state_mutated": False,
        "kill_switch_mutated": False,
        "capital_authority_changed": False,
        "authorizes_submission": False,
        "authorizes_cancellation": False,
        "releases_submission_interlock": False,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


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


def _decimal_string(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _optional_decimal_string(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return _decimal_string(_decimal(value))


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
