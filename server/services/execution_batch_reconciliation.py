"""Append-only, exact-order batch reconciliation evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION = (
    "karkinos.execution_batch_reconciliation.v1"
)
EXECUTION_BATCH_RECONCILIATION_STATUS_SCHEMA_VERSION = (
    "karkinos.execution_batch_reconciliation_status.v1"
)
EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE = (
    "execution_reconciliation.batch_evidence_recorded"
)
EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE = "execution_batch_reconciliation"
EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE = "execution_batch_reconciliation"
EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT = (
    "record_exact_batch_reconciliation_without_authority_change"
)

MAX_BATCH_ORDER_COUNT = 100
_BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TERMINAL_OMS_STATUSES = frozenset({"filled", "rejected", "cancelled", "expired"})
_REAL_EXECUTION_MODES = frozenset({"manual", "controlled_live", "live"})


class ExecutionBatchReconciliationRejected(ValueError):
    """Raised after an invalid record attempt is persisted."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ExecutionBatchReconciliationService:
    """Bind an exact prior order batch to immutable reconciliation evidence."""

    def __init__(
        self,
        *,
        db: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": EXECUTION_BATCH_RECONCILIATION_STATUS_SCHEMA_VERSION,
            "contract_status": "read_only_append_only_exact_batch_evidence",
            "maximum_batch_order_count": MAX_BATCH_ORDER_COUNT,
            "acknowledgement": EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
            "manual_mismatch_acceptance_enabled": False,
            "operator_identity_verified": False,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
            "limitations": [
                "Only persisted no-action reconciliation items can produce a clear batch fact.",
                "Manual acceptance of a mismatch is intentionally not implemented.",
                "A clear batch fact can satisfy one prior-batch evidence gate but cannot authorize the next batch.",
            ],
        }

    def preview(
        self,
        *,
        batch_id: str,
        order_ids: list[str] | tuple[str, ...],
        reconciliation_run_id: str,
    ) -> dict[str, Any]:
        normalized_batch_id = str(batch_id or "").strip()
        requested_order_ids = [str(item or "").strip() for item in order_ids]
        normalized_order_ids = sorted({item for item in requested_order_ids if item})
        normalized_run_id = str(reconciliation_run_id or "").strip()
        blockers: list[str] = []
        if not _BATCH_ID_PATTERN.fullmatch(normalized_batch_id):
            blockers.append("batch_id_invalid")
        if not normalized_order_ids:
            blockers.append("batch_order_set_empty")
        if len(normalized_order_ids) > MAX_BATCH_ORDER_COUNT:
            blockers.append("batch_order_count_exceeded")
        if len(requested_order_ids) != len(normalized_order_ids):
            blockers.append("batch_order_ids_invalid_or_duplicate")
        if not normalized_run_id:
            blockers.append("reconciliation_run_id_missing")

        run = (
            self._db.get_execution_reconciliation_run_sync(normalized_run_id)
            if normalized_run_id
            else None
        )
        items = (
            self._db.list_execution_reconciliation_items_sync(normalized_run_id)
            if run is not None
            else []
        )
        if run is None:
            blockers.append("reconciliation_run_not_found")
        items_by_order: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            items_by_order.setdefault(str(item.get("order_id") or ""), []).append(item)

        order_facts: list[dict[str, Any]] = []
        source_refs: list[str] = []
        for order_id in normalized_order_ids:
            order = self._db.get_oms_order_sync(order_id)
            if order is None:
                blockers.append(f"batch_oms_order_not_found:{order_id}")
                continue
            order = dict(order)
            transitions = self._db.list_oms_transitions_sync(order_id)
            fills = self._db.list_fills_sync(order_id=order_id, limit=1000)
            item_rows = items_by_order.get(order_id, [])
            if len(item_rows) != 1:
                blockers.append(f"batch_reconciliation_item_count_invalid:{order_id}")
                item = {}
            else:
                item = item_rows[0]
            item_payload = _json_object(item.get("payload_json"))
            current_status = str(order.get("status") or "").strip().lower()
            effective_terminal_status = _effective_terminal_status(
                current_status,
                transitions,
            )
            order_payload = _json_object(order.get("payload_json"))
            execution_mode = str(order_payload.get("execution_mode") or "").lower()
            if execution_mode == "paper_shadow":
                blockers.append(f"batch_paper_shadow_order_not_allowed:{order_id}")
            if effective_terminal_status not in _TERMINAL_OMS_STATUSES:
                blockers.append(f"batch_oms_order_not_terminal:{order_id}")
            if str(item.get("suggested_action") or "") != "no_action":
                blockers.append(f"batch_reconciliation_item_not_clear:{order_id}")
            item_oms_status = str(item_payload.get("oms_status") or "").lower()
            if not item_oms_status:
                blockers.append(f"batch_reconciliation_oms_status_missing:{order_id}")
            elif item_oms_status != current_status:
                blockers.append(f"batch_reconciliation_oms_status_changed:{order_id}")

            real_fills: list[dict[str, Any]] = []
            real_fill_quantity = Decimal("0")
            for fill in fills:
                if not _is_real_fill(fill):
                    continue
                metadata = _json_object(fill.get("metadata_json"))
                required_linkage = (
                    fill.get("provider_name"),
                    fill.get("broker_order_id"),
                    metadata.get("account_truth_import_run_id"),
                    metadata.get("execution_reconciliation_run_id"),
                )
                if not all(str(value or "").strip() for value in required_linkage):
                    blockers.append(f"batch_real_fill_linkage_incomplete:{order_id}")
                if (
                    str(metadata.get("execution_reconciliation_run_id") or "")
                    != normalized_run_id
                ):
                    blockers.append(
                        f"batch_real_fill_reconciliation_mismatch:{order_id}"
                    )
                quantity = abs(_decimal(fill.get("fill_quantity")) or Decimal("0"))
                if quantity <= 0:
                    blockers.append(f"batch_real_fill_quantity_invalid:{order_id}")
                real_fill_quantity += quantity
                real_fills.append(
                    {
                        "fill_id": str(fill.get("fill_id") or ""),
                        "fill_fingerprint": _fingerprint(_fill_contract(fill)),
                        "provider_name": str(fill.get("provider_name") or ""),
                        "broker_order_id": str(fill.get("broker_order_id") or ""),
                        "account_truth_import_run_id": str(
                            metadata.get("account_truth_import_run_id") or ""
                        ),
                        "execution_reconciliation_run_id": str(
                            metadata.get("execution_reconciliation_run_id") or ""
                        ),
                        "fill_quantity": _decimal_string(quantity),
                    }
                )
            order_quantity = abs(_decimal(order.get("quantity")) or Decimal("0"))
            if effective_terminal_status == "filled":
                if not real_fills:
                    blockers.append(f"batch_filled_order_real_fill_missing:{order_id}")
                if order_quantity <= 0 or real_fill_quantity != order_quantity:
                    blockers.append(f"batch_filled_quantity_mismatch:{order_id}")
            elif order_quantity > 0 and real_fill_quantity > order_quantity:
                blockers.append(f"batch_fill_quantity_exceeds_order:{order_id}")

            transition_facts = [
                {
                    "transition_id": int(transition.get("id") or 0),
                    "from_status": str(transition.get("from_status") or ""),
                    "to_status": str(transition.get("to_status") or ""),
                    "transitioned_at": str(transition.get("transitioned_at") or ""),
                    "fingerprint": _fingerprint(_transition_contract(transition)),
                }
                for transition in transitions
            ]
            order_facts.append(
                {
                    "order_id": order_id,
                    "order_fingerprint": _fingerprint(_order_contract(order)),
                    "current_oms_status": current_status,
                    "effective_terminal_status": effective_terminal_status,
                    "execution_mode": execution_mode,
                    "order_quantity": _decimal_string(order_quantity),
                    "real_fill_quantity": _decimal_string(real_fill_quantity),
                    "transitions": transition_facts,
                    "real_fills": real_fills,
                    "reconciliation_item": {
                        "item_id": int(item.get("id") or 0),
                        "item_status": str(item.get("item_status") or ""),
                        "suggested_action": str(item.get("suggested_action") or ""),
                        "fingerprint": (
                            _fingerprint(_reconciliation_item_contract(item))
                            if item
                            else ""
                        ),
                    },
                }
            )
            source_refs.extend(
                [
                    f"oms_order:{order_id}",
                    *(
                        f"oms_transition:{row['transition_id']}"
                        for row in transition_facts
                    ),
                    *(f"fill:{row['fill_id']}" for row in real_fills),
                    (
                        f"execution_reconciliation_item:{item.get('id')}"
                        if item.get("id") is not None
                        else ""
                    ),
                ]
            )

        core = {
            "schema_version": EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
            "batch_id": normalized_batch_id,
            "order_ids": normalized_order_ids,
            "order_count": len(normalized_order_ids),
            "reconciliation_run_id": normalized_run_id,
            "reconciliation_run": _reconciliation_run_summary(run),
            "orders": order_facts,
            "source_refs": list(dict.fromkeys(ref for ref in source_refs if ref)),
            "blockers": list(dict.fromkeys(blockers)),
            "status": "clear" if not blockers else "blocked",
            "batch_reconciliation_clear": not blockers,
            "manual_mismatch_acceptance_applied": False,
            "authorizes_next_batch": False,
            "safety": _safety_flags(),
            "assumptions": [
                "The caller identifies the exact prior order batch and persisted reconciliation run.",
                "Only one persisted reconciliation item per batch order is accepted.",
                "Real fills must link provider, broker order, Account Truth import, and the same reconciliation run.",
            ],
            "limitations": [
                "A reconciliation run may contain unrelated orders; only the exact selected batch is evaluated.",
                "Authenticated operator identity and manually accepted mismatch policy remain unimplemented.",
            ],
        }
        return {
            **core,
            "batch_reconciliation_fingerprint": _fingerprint(core),
            "generated_at": _aware_utc(self._clock()).isoformat(),
            "persisted": False,
            "reused": False,
        }

    def record(
        self,
        *,
        batch_id: str,
        order_ids: list[str] | tuple[str, ...],
        reconciliation_run_id: str,
        batch_reconciliation_fingerprint: str,
        operator_label: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview(
            batch_id=batch_id,
            order_ids=order_ids,
            reconciliation_run_id=reconciliation_run_id,
        )
        rejection_reasons: list[str] = []
        if not str(operator_label or "").strip():
            rejection_reasons.append("operator_label_missing")
        if acknowledgement != EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if (
            batch_reconciliation_fingerprint
            != preview["batch_reconciliation_fingerprint"]
        ):
            rejection_reasons.append("batch_reconciliation_fingerprint_mismatch")
        if rejection_reasons:
            evidence = self._record_rejected_attempt(
                preview=preview,
                submitted_fingerprint=batch_reconciliation_fingerprint,
                operator_label=str(operator_label or "").strip(),
                acknowledgement=acknowledgement,
                rejection_reasons=rejection_reasons,
            )
            raise ExecutionBatchReconciliationRejected(
                "execution batch reconciliation rejected: "
                + ", ".join(rejection_reasons),
                evidence=evidence,
            )

        fingerprint = str(preview["batch_reconciliation_fingerprint"])
        existing = self._db.list_events_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            entity_id=fingerprint,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        record_status = (
            "recorded_clear" if preview["status"] == "clear" else "recorded_blocked"
        )
        payload = {
            key: value
            for key, value in preview.items()
            if key not in {"generated_at", "persisted", "reused"}
        }
        payload.update(
            {
                "record_status": record_status,
                "operator_label": str(operator_label or "").strip(),
                "operator_identity_verified": False,
                "acknowledgement": acknowledgement,
                "rejection_reasons": [],
            }
        )
        self._db.append_event_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            timestamp=_aware_utc(self._clock()).isoformat(),
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            entity_id=fingerprint,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            source_ref=str(preview.get("reconciliation_run_id") or ""),
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            entity_id=fingerprint,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("execution batch reconciliation was not recorded")
        return _event_response(saved[0], reused=False)

    def resolve_recorded(self, fingerprint: str) -> dict[str, Any]:
        normalized = str(fingerprint or "").strip().lower()
        blockers: list[str] = []
        if not re.fullmatch(r"[a-f0-9]{64}", normalized):
            blockers.append("prior_batch_reconciliation_fingerprint_invalid")
        rows = (
            self._db.list_events_sync(
                event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
                entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
                entity_id=normalized,
                source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
                limit=1,
            )
            if not blockers
            else []
        )
        if not rows:
            blockers.append("prior_batch_reconciliation_not_found")
            return _resolution_summary(normalized, {}, blockers)
        recorded = _event_response(rows[0], reused=False)
        if recorded.get("schema_version") != (
            EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION
        ):
            blockers.append("prior_batch_reconciliation_schema_invalid")
        if recorded.get("record_status") != "recorded_clear":
            blockers.append("prior_batch_reconciliation_record_not_clear")
        if recorded.get("status") != "clear" or not recorded.get(
            "batch_reconciliation_clear"
        ):
            blockers.append("prior_batch_reconciliation_not_clear")
        current = self.preview(
            batch_id=str(recorded.get("batch_id") or ""),
            order_ids=[str(item) for item in recorded.get("order_ids") or []],
            reconciliation_run_id=str(recorded.get("reconciliation_run_id") or ""),
        )
        if current["batch_reconciliation_fingerprint"] != normalized:
            blockers.append("prior_batch_reconciliation_source_changed")
        return _resolution_summary(normalized, recorded, blockers)

    def list_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def _record_rejected_attempt(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_label: str,
        acknowledgement: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        attempt_id = _fingerprint(
            {
                "batch_reconciliation_fingerprint": preview.get(
                    "batch_reconciliation_fingerprint"
                ),
                "submitted_fingerprint": submitted_fingerprint,
                "operator_label": operator_label,
                "acknowledgement": acknowledgement,
                "rejection_reasons": rejection_reasons,
            }
        )
        payload = {
            "schema_version": EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
            "record_status": "rejected",
            "attempt_id": attempt_id,
            "batch_id": preview.get("batch_id"),
            "order_ids": preview.get("order_ids"),
            "reconciliation_run_id": preview.get("reconciliation_run_id"),
            "batch_reconciliation_fingerprint": preview.get(
                "batch_reconciliation_fingerprint"
            ),
            "submitted_fingerprint": submitted_fingerprint,
            "operator_label": operator_label,
            "operator_identity_verified": False,
            "acknowledgement": acknowledgement,
            "rejection_reasons": rejection_reasons,
            "batch_reconciliation_clear": False,
            "authorizes_next_batch": False,
            "safety": _safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            entity_id=attempt_id,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            limit=1,
        )
        if not existing:
            self._db.append_event_sync(
                event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
                timestamp=_aware_utc(self._clock()).isoformat(),
                entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
                entity_id=attempt_id,
                source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
                source_ref=str(preview.get("reconciliation_run_id") or ""),
                payload=payload,
            )
            existing = self._db.list_events_sync(
                event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
                entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
                entity_id=attempt_id,
                source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
                limit=1,
            )
        if not existing:
            raise RuntimeError("rejected batch reconciliation was not audited")
        return _event_response(existing[0], reused=False)


def resolve_prior_batch_reconciliation(
    *,
    db: Any,
    fingerprint: str,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve one exact batch fact for proposal consumers."""
    result = ExecutionBatchReconciliationService(db=db).resolve_recorded(fingerprint)
    return result, [str(item) for item in result.get("blockers") or []]


def _resolution_summary(
    fingerprint: str,
    recorded: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "pass" if not blockers else "blocked",
        "batch_reconciliation_fingerprint": fingerprint,
        "batch_id": str(recorded.get("batch_id") or ""),
        "order_ids": [str(item) for item in recorded.get("order_ids") or []],
        "order_count": int(recorded.get("order_count") or 0),
        "reconciliation_run_id": str(recorded.get("reconciliation_run_id") or ""),
        "record_status": str(recorded.get("record_status") or "missing"),
        "source_recorded_at": str(recorded.get("recorded_at") or ""),
        "source_refs": [str(item) for item in recorded.get("source_refs") or []],
        "blockers": list(dict.fromkeys(blockers)),
        "evidence_ref": (
            f"execution_batch_reconciliation:{fingerprint}" if fingerprint else ""
        ),
        "authorizes_next_batch": False,
        "does_not_submit_broker_order": True,
    }


def _effective_terminal_status(
    current_status: str,
    transitions: list[dict[str, Any]],
) -> str:
    if current_status in _TERMINAL_OMS_STATUSES:
        return current_status
    if current_status == "reconciled":
        for transition in reversed(transitions):
            status = str(transition.get("to_status") or "").strip().lower()
            if status in _TERMINAL_OMS_STATUSES:
                return status
    return current_status


def _is_real_fill(fill: dict[str, Any]) -> bool:
    mode = str(fill.get("execution_mode") or "").strip().lower()
    source = str(fill.get("source") or "").strip().lower()
    return mode in _REAL_EXECUTION_MODES and not any(
        marker in source for marker in ("paper", "shadow", "simulat")
    )


def _order_contract(order: dict[str, Any]) -> dict[str, Any]:
    return {
        key: order.get(key)
        for key in (
            "order_id",
            "intent_key",
            "symbol",
            "side",
            "asset_class",
            "quantity",
            "order_type",
            "limit_price",
            "status",
            "broker_submission_enabled",
            "source",
            "source_ref",
            "payload_json",
            "created_at",
            "updated_at",
        )
    }


def _transition_contract(transition: dict[str, Any]) -> dict[str, Any]:
    return {
        key: transition.get(key)
        for key in (
            "id",
            "order_id",
            "from_status",
            "to_status",
            "reason",
            "actor",
            "payload_json",
            "transitioned_at",
            "created_at",
        )
    }


def _fill_contract(fill: dict[str, Any]) -> dict[str, Any]:
    return {
        key: fill.get(key)
        for key in (
            "fill_id",
            "order_id",
            "timestamp",
            "symbol",
            "side",
            "fill_price",
            "fill_quantity",
            "commission",
            "slippage",
            "asset_class",
            "execution_mode",
            "provider_name",
            "broker_order_id",
            "source",
            "source_ref",
            "metadata_json",
        )
    }


def _reconciliation_item_contract(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "run_id",
            "order_id",
            "item_status",
            "suggested_action",
            "gateway_event_count",
            "broker_event_count",
            "detail",
            "payload_json",
            "created_at",
        )
    }


def _reconciliation_run_summary(run: dict[str, Any] | None) -> dict[str, Any]:
    if run is None:
        return {
            "status": "missing",
            "run_id": "",
            "run_date": "",
            "item_count": None,
            "open_item_count": None,
            "source_fingerprint": "",
        }
    contract = {
        key: run.get(key)
        for key in (
            "run_id",
            "run_date",
            "status",
            "item_count",
            "open_item_count",
            "payload_json",
            "created_at",
            "updated_at",
        )
    }
    return {
        "status": str(run.get("status") or ""),
        "run_id": str(run.get("run_id") or ""),
        "run_date": str(run.get("run_date") or ""),
        "item_count": int(run.get("item_count") or 0),
        "open_item_count": int(run.get("open_item_count") or 0),
        "source_fingerprint": _fingerprint(contract),
    }


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_string(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **_json_object(row.get("payload_json")),
    }


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


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_issue_or_expand_authority": True,
        "does_not_enable_or_resume_execution": True,
        "does_not_reserve_or_consume_budget": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
    }
