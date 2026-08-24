"""Value normalization and immutable inputs for paper/shadow runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.types import AssetClass, OrderSide
from execution.paper_broker import PaperOrderContext
from server.services.paper_shadow_contracts import (
    PAPER_SHADOW_INPUT_SNAPSHOT_SCHEMA_VERSION,
)


def _current_account_facts(
    trading_plan: dict[str, Any],
    order_intents: list[dict[str, Any]],
) -> dict[str, Any]:
    constraint_statuses: list[Any] = []
    for intent in order_intents:
        checks = intent.get("constraint_checks")
        if not isinstance(checks, list):
            continue
        constraint_statuses.extend(
            check.get("status") for check in checks if isinstance(check, dict)
        )
    return {
        "available_cash": _float_or_none(trading_plan.get("available_cash")),
        "cash_status_counts": _value_counts(
            intent.get("cash_status") for intent in order_intents
        ),
        "constraint_status_counts": _value_counts(constraint_statuses),
        "position_effect_count": sum(
            1
            for intent in order_intents
            if isinstance(intent.get("position_effect"), dict)
        ),
    }


def _broker_account_truth_state(trading_plan: dict[str, Any]) -> dict[str, Any]:
    account_truth = _account_truth_snapshot(trading_plan)
    has_evidence = bool(account_truth.get("has_evidence", bool(account_truth)))
    return {
        "gate_status": str(account_truth.get("gate_status") or "not_attached"),
        "has_evidence": has_evidence,
        "blocking_reasons": [
            str(reason) for reason in account_truth.get("blocking_reasons") or []
        ],
    }


def _account_truth_snapshot(trading_plan: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        trading_plan.get("account_truth"),
        _dict(trading_plan.get("summary")).get("account_truth"),
        _dict(trading_plan.get("evidence")).get("account_truth"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _float_or_none(value: Any) -> float | None:
    decimal_value = _decimal(value)
    return float(decimal_value) if decimal_value is not None else None


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _decimal_or_zero(value: Any) -> Decimal:
    decimal_value = _decimal(value)
    return decimal_value if decimal_value is not None else Decimal("0")


def _dedupe_refs(refs: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        value = str(ref).strip()
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
    return values


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _outcome_for_intent(
    intent: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    symbol = str(intent.get("symbol") or "")
    action_id = str(intent.get("action_id") or "")
    return overrides.get(symbol) or overrides.get(action_id) or {}


def _normalized_outcome_overrides(
    overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            overrides,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    )


def _input_refs(
    *,
    trading_plan: dict[str, Any],
    plan_date: str,
    input_fingerprint: str,
) -> dict[str, str | None]:
    return {
        "source_decision": (
            str(trading_plan.get("source_decision"))
            if trading_plan.get("source_decision") is not None
            else None
        ),
        "trading_plan_ref": f"trading_plan:{plan_date}:{input_fingerprint[:12]}",
        "trading_plan_schema_version": (
            str(trading_plan.get("schema_version"))
            if trading_plan.get("schema_version") is not None
            else None
        ),
    }


def _input_snapshot(
    *,
    trading_plan: dict[str, Any],
    plan_date: str,
    input_fingerprint: str,
    input_refs: dict[str, Any],
    order_intents: list[dict[str, Any]],
    outcome_overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": PAPER_SHADOW_INPUT_SNAPSHOT_SCHEMA_VERSION,
        "plan_date": plan_date,
        "input_fingerprint": input_fingerprint,
        "input_refs": input_refs,
        "source_decision": trading_plan.get("source_decision"),
        "trading_plan_schema_version": trading_plan.get("schema_version"),
        "order_intent_count": len(order_intents),
        "order_intents": [
            _order_intent_snapshot(intent, _order_intent_ref(intent, index))
            for index, intent in enumerate(order_intents, start=1)
        ],
        "current_account_facts": _current_account_facts(trading_plan, order_intents),
        "broker_account_truth_state": _broker_account_truth_state(trading_plan),
        "outcome_overrides": outcome_overrides,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _input_fingerprint(payload: dict[str, Any]) -> str:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_order_intent_input(intent: dict[str, Any]) -> dict[str, Any]:
    """Remove workflow labels that change only after this simulation passes."""

    stable = dict(intent)
    stable.pop("manual_confirmation_status", None)
    stable.pop("submission_status", None)
    return stable


def _order_intents(trading_plan: dict[str, Any]) -> list[dict[str, Any]]:
    value = trading_plan.get("order_intents")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _plan_date(trading_plan: dict[str, Any], generated_at: str | None) -> str:
    value = trading_plan.get("plan_date") or trading_plan.get("decision_date")
    if value:
        return str(value)
    if generated_at:
        return str(generated_at)[:10]
    return datetime.now().date().isoformat()


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return datetime.now()


def _side(value: Any) -> OrderSide | None:
    try:
        return OrderSide(str(value).lower())
    except ValueError:
        return None


def _asset_class(value: Any) -> AssetClass:
    try:
        return AssetClass(str(value or "stock").lower())
    except ValueError:
        return AssetClass.STOCK


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _paper_order_context(intent: dict[str, Any]) -> PaperOrderContext:
    refs = [str(item) for item in intent.get("evidence_refs") or []]
    return PaperOrderContext(
        strategy_id=_first_ref(refs, "strategy:"),
        signal_id=_first_ref(refs, "signal:") or _order_intent_ref(intent, 0),
        risk_decision_id=_first_ref(refs, "risk:"),
        cost_model_id=str(intent.get("fee_rule_id") or "stock_a_commission_v1"),
    )


def _refs_with_prefix(refs: list[str], prefix: str) -> list[str]:
    return [item for item in refs if item.startswith(prefix)]


def _first_ref(refs: list[str], prefix: str) -> str | None:
    return next((item for item in refs if item.startswith(prefix)), None)


def _order_intent_ref(intent: dict[str, Any], index: int) -> str:
    action_id = intent.get("action_id")
    if action_id is not None and str(action_id):
        return f"action:{action_id}"
    return f"order_intent:{index}"


def _order_intent_snapshot(
    intent: dict[str, Any],
    intent_ref: str,
) -> dict[str, Any]:
    refs = [str(item) for item in intent.get("evidence_refs") or []]
    return {
        "action_ref": intent_ref,
        "symbol": intent.get("symbol"),
        "side": intent.get("side"),
        "estimated_quantity": intent.get("estimated_quantity"),
        "estimated_price": intent.get("estimated_price"),
        "strategy_refs": _refs_with_prefix(refs, "strategy:"),
        "strategy_advancement_refs": _refs_with_prefix(
            refs,
            "strategy_advancement:",
        ),
        "risk_refs": _refs_with_prefix(refs, "risk:"),
        "signal_refs": _refs_with_prefix(refs, "signal:"),
        "account_truth_refs": _refs_with_prefix(refs, "account_truth:"),
        "price_basis": str(intent.get("price_basis") or "estimated_price"),
        "estimated_gross_amount": intent.get("estimated_gross_amount"),
        "estimated_total_fee": intent.get("estimated_total_fee"),
        "fee_rule_id": intent.get("fee_rule_id"),
        "risk_gate_status": intent.get("risk_gate_status"),
        "manual_confirmation_status": intent.get("manual_confirmation_status"),
        "submission_status": intent.get("submission_status"),
    }


def _value_counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value is None or value == "":
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _fill_count_by_order(
    fill_summaries: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fill in fill_summaries:
        order_id = str(fill.get("order_id") or "")
        if not order_id:
            continue
        counts[order_id] = counts.get(order_id, 0) + 1
    return counts


current_account_facts = _current_account_facts
broker_account_truth_state = _broker_account_truth_state
account_truth_snapshot = _account_truth_snapshot
float_or_none = _float_or_none
string_or_none = _string_or_none
decimal_or_zero = _decimal_or_zero
dedupe_refs = _dedupe_refs
dict_value = _dict
outcome_for_intent = _outcome_for_intent
normalized_outcome_overrides = _normalized_outcome_overrides
input_refs = _input_refs
input_snapshot = _input_snapshot
input_fingerprint = _input_fingerprint
stable_order_intent_input = _stable_order_intent_input
order_intents = _order_intents
plan_date = _plan_date
timestamp = _timestamp
side = _side
asset_class = _asset_class
decimal_value = _decimal
paper_order_context = _paper_order_context
refs_with_prefix = _refs_with_prefix
first_ref = _first_ref
order_intent_ref = _order_intent_ref
order_intent_snapshot = _order_intent_snapshot
value_counts = _value_counts
fill_count_by_order = _fill_count_by_order
