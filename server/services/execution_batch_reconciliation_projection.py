"""Read-only evidence projection for exact execution batches."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from server.services.execution_batch_reconciliation_values import (
    BATCH_ID_PATTERN,
    EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
    MAX_BATCH_ORDER_COUNT,
    TERMINAL_OMS_STATUSES,
    aware_utc,
    decimal_string,
    decimal_value,
    derive_effective_terminal_status,
    fill_contract,
    is_real_fill,
    json_object,
    order_contract,
    order_strategy_id,
    reconciliation_item_contract,
    reconciliation_run_summary,
    safety_flags,
    stable_fingerprint,
    transition_contract,
    valid_plan_paper_actual_comparison,
)


def build_execution_batch_reconciliation_preview(
    *,
    db: Any,
    clock: Callable[[], datetime],
    batch_id: str,
    order_ids: list[str] | tuple[str, ...],
    reconciliation_run_id: str,
) -> dict[str, Any]:
    normalized_batch_id = str(batch_id or "").strip()
    requested_order_ids = [str(item or "").strip() for item in order_ids]
    normalized_order_ids = sorted({item for item in requested_order_ids if item})
    normalized_run_id = str(reconciliation_run_id or "").strip()
    blockers: list[str] = []
    if not BATCH_ID_PATTERN.fullmatch(normalized_batch_id):
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
        db.get_execution_reconciliation_run_sync(normalized_run_id)
        if normalized_run_id
        else None
    )
    items = (
        db.list_execution_reconciliation_items_sync(normalized_run_id)
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
        order = db.get_oms_order_sync(order_id)
        if order is None:
            blockers.append(f"batch_oms_order_not_found:{order_id}")
            continue
        order = dict(order)
        transitions = db.list_oms_transitions_sync(order_id)
        fills = db.list_fills_sync(order_id=order_id, limit=1000)
        item_rows = items_by_order.get(order_id, [])
        if len(item_rows) != 1:
            blockers.append(f"batch_reconciliation_item_count_invalid:{order_id}")
            item = {}
        else:
            item = item_rows[0]
        order_payload = json_object(order.get("payload_json"))
        item_payload = json_object(item.get("payload_json"))
        plan_paper_actual = json_object(
            item_payload.get("plan_paper_actual_comparison")
        )
        strategy_id = order_strategy_id(db, order_payload)
        current_plan_paper_actual: dict[str, Any] = {}
        plan_paper_actual_current = False
        if strategy_id.startswith("ai_formula_shadow:"):
            from server.services.execution_reconciliation import (
                build_current_plan_paper_actual_comparison,
            )

            if not valid_plan_paper_actual_comparison(
                plan_paper_actual,
                expected_order_id=order_id,
                expected_strategy_id=strategy_id,
            ):
                blockers.append(
                    f"batch_ai_shadow_plan_paper_actual_not_clear:{order_id}"
                )
            current_plan_paper_actual = build_current_plan_paper_actual_comparison(
                db, order
            )
            if not valid_plan_paper_actual_comparison(
                current_plan_paper_actual,
                expected_order_id=order_id,
                expected_strategy_id=strategy_id,
            ):
                blockers.append(
                    f"batch_ai_shadow_plan_paper_actual_current_not_clear:{order_id}"
                )
            plan_paper_actual_current = bool(
                plan_paper_actual.get("evidence_fingerprint")
                and plan_paper_actual.get("evidence_fingerprint")
                == current_plan_paper_actual.get("evidence_fingerprint")
            )
            if not plan_paper_actual_current:
                blockers.append(
                    f"batch_ai_shadow_plan_paper_actual_source_changed:{order_id}"
                )
        current_status = str(order.get("status") or "").strip().lower()
        effective_terminal_status = derive_effective_terminal_status(
            current_status,
            transitions,
        )
        execution_mode = str(order_payload.get("execution_mode") or "").lower()
        if execution_mode == "paper_shadow":
            blockers.append(f"batch_paper_shadow_order_not_allowed:{order_id}")
        if effective_terminal_status not in TERMINAL_OMS_STATUSES:
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
            if not is_real_fill(fill):
                continue
            metadata = json_object(fill.get("metadata_json"))
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
                blockers.append(f"batch_real_fill_reconciliation_mismatch:{order_id}")
            quantity = abs(decimal_value(fill.get("fill_quantity")) or Decimal("0"))
            if quantity <= 0:
                blockers.append(f"batch_real_fill_quantity_invalid:{order_id}")
            real_fill_quantity += quantity
            real_fills.append(
                {
                    "fill_id": str(fill.get("fill_id") or ""),
                    "fill_fingerprint": stable_fingerprint(fill_contract(fill)),
                    "provider_name": str(fill.get("provider_name") or ""),
                    "broker_order_id": str(fill.get("broker_order_id") or ""),
                    "account_truth_import_run_id": str(
                        metadata.get("account_truth_import_run_id") or ""
                    ),
                    "execution_reconciliation_run_id": str(
                        metadata.get("execution_reconciliation_run_id") or ""
                    ),
                    "fill_quantity": decimal_string(quantity),
                }
            )
        order_quantity = abs(decimal_value(order.get("quantity")) or Decimal("0"))
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
                "fingerprint": stable_fingerprint(transition_contract(transition)),
            }
            for transition in transitions
        ]
        order_facts.append(
            {
                "order_id": order_id,
                "order_fingerprint": stable_fingerprint(order_contract(order)),
                "current_oms_status": current_status,
                "effective_terminal_status": effective_terminal_status,
                "execution_mode": execution_mode,
                "strategy_id": strategy_id,
                "order_quantity": decimal_string(order_quantity),
                "real_fill_quantity": decimal_string(real_fill_quantity),
                "transitions": transition_facts,
                "real_fills": real_fills,
                "reconciliation_item": {
                    "item_id": int(item.get("id") or 0),
                    "item_status": str(item.get("item_status") or ""),
                    "suggested_action": str(item.get("suggested_action") or ""),
                    "fingerprint": (
                        stable_fingerprint(reconciliation_item_contract(item))
                        if item
                        else ""
                    ),
                },
                "plan_paper_actual_comparison": {
                    "required": strategy_id.startswith("ai_formula_shadow:"),
                    "status": str(plan_paper_actual.get("status") or "missing"),
                    "evidence_fingerprint": str(
                        plan_paper_actual.get("evidence_fingerprint") or ""
                    ),
                    "current_status": str(
                        current_plan_paper_actual.get("status") or "not_required"
                    ),
                    "current_evidence_fingerprint": str(
                        current_plan_paper_actual.get("evidence_fingerprint") or ""
                    ),
                    "current_source_match": plan_paper_actual_current,
                },
            }
        )
        source_refs.extend(
            [
                f"oms_order:{order_id}",
                *(f"oms_transition:{row['transition_id']}" for row in transition_facts),
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
        "reconciliation_run": reconciliation_run_summary(run),
        "orders": order_facts,
        "source_refs": list(dict.fromkeys(ref for ref in source_refs if ref)),
        "blockers": list(dict.fromkeys(blockers)),
        "status": "clear" if not blockers else "blocked",
        "batch_reconciliation_clear": not blockers,
        "manual_mismatch_acceptance_applied": False,
        "authorizes_next_batch": False,
        "safety": safety_flags(),
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
        "batch_reconciliation_fingerprint": stable_fingerprint(core),
        "generated_at": aware_utc(clock()).isoformat(),
        "persisted": False,
        "reused": False,
    }
