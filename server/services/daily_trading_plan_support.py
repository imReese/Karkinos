"""Pure normalization and evidence helpers for daily trading plans."""

from __future__ import annotations

from typing import Any

_ORDERABLE_ACTIONS = {"buy", "sell", "rebalance"}
_BLOCKER_CATEGORY_ORDER = {
    "account_truth": 0,
    "market_data": 1,
    "portfolio": 2,
    "risk": 3,
    "evidence_not_ready": 4,
    "other": 9,
}


def blocker_summary(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for blocker_value in blockers:
        category = blocker_category(blocker_value)
        bucket = grouped.setdefault(
            category,
            {
                "category": category,
                "target": blocker_value.get("target") or "decision",
                "count": 0,
                "reasons": [],
                "sample_symbols": [],
            },
        )
        bucket["count"] += 1
        for reason in blocker_reasons(blocker_value):
            if reason and reason not in bucket["reasons"]:
                bucket["reasons"].append(reason)
        symbol = blocker_value.get("symbol")
        if (
            symbol
            and symbol not in bucket["sample_symbols"]
            and len(bucket["sample_symbols"]) < 5
        ):
            bucket["sample_symbols"].append(symbol)
    return sorted(
        grouped.values(),
        key=lambda item: _BLOCKER_CATEGORY_ORDER.get(str(item["category"]), 99),
    )


def account_truth_snapshot(
    account_truth: dict[str, Any],
    gate_status: str,
) -> dict[str, Any]:
    has_evidence_value = account_truth.get("has_evidence")
    snapshot = {
        "gate_status": gate_status,
        "has_evidence": (
            bool(account_truth)
            if has_evidence_value is None
            else bool(has_evidence_value)
        ),
        "blocking_reasons": [
            str(reason) for reason in account_truth.get("blocking_reasons") or []
        ],
    }
    for key in (
        "status",
        "source_type",
        "score",
        "cash_status",
        "position_status",
        "data_freshness_status",
        "unresolved_mismatch_count",
        "required_actions",
        "limitations",
    ):
        if key in account_truth:
            snapshot[key] = account_truth[key]
    return snapshot


def blocker_category(blocker_value: dict[str, Any]) -> str:
    target = str(blocker_value.get("target") or "").strip().lower()
    reason = str(blocker_value.get("reason") or "").strip().lower()
    if target == "account-truth" or reason == "account_truth_blocked":
        return "account_truth"
    if target == "market" or reason == "market_data_unavailable":
        return "market_data"
    if target == "portfolio" or reason in {
        "insufficient_cash",
        "cash_buffer_breached",
        "concentration_limit_breached",
    }:
        return "portfolio"
    if reason == "awaiting_risk_gate" or target == "decision":
        return "evidence_not_ready"
    if target == "risk":
        return "risk"
    return "other"


def side(candidate: dict[str, Any]) -> str | None:
    action = status(candidate.get("action") or candidate.get("direction"), "")
    if action == "buy":
        return "buy"
    if action == "sell":
        return "sell"
    if action == "rebalance":
        return "buy" if float_value(candidate.get("target_weight"), 0.0) > 0 else "sell"
    if action in _ORDERABLE_ACTIONS:
        return action
    return None


def blocker(
    candidate: dict[str, Any],
    reason: str,
    target: str,
) -> dict[str, Any]:
    return {
        "action_id": candidate.get("action_id"),
        "symbol": candidate.get("symbol"),
        "reason": reason,
        "reasons": candidate_blocking_reasons(candidate, fallback=reason),
        "target": target,
        "risk_gate_status": candidate.get("risk_gate_status"),
        "manual_confirmation_status": candidate.get("manual_confirmation_status"),
    }


def blocker_reasons(blocker_value: dict[str, Any]) -> list[str]:
    reasons = blocker_value.get("reasons")
    if isinstance(reasons, list):
        values = [str(reason) for reason in reasons if reason]
        if values:
            return values
    reason = blocker_value.get("reason")
    return [str(reason)] if reason else []


def candidate_blocking_reasons(
    candidate: dict[str, Any],
    *,
    fallback: str,
) -> list[str]:
    risk_reasons = candidate.get("risk_gate_reasons")
    if fallback == "risk_gate_blocked" and isinstance(risk_reasons, list):
        values = [str(reason) for reason in risk_reasons if reason]
        if values:
            return values
    return [fallback]


def evidence_refs(candidate: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    action_id = candidate.get("action_id")
    if action_id is not None:
        refs.append(f"decision_action:{action_id}")
    evidence = mapping(candidate.get("evidence"))
    signal = mapping(evidence.get("signal"))
    signal_id = signal.get("signal_id") or signal.get("id")
    if signal_id is not None:
        refs.append(f"signal:{signal_id}")
    strategy = mapping(evidence.get("strategy"))
    strategy_id = strategy.get("strategy_id")
    if strategy_id is not None:
        refs.append(f"strategy:{strategy_id}")
    order_generation_gate = mapping(strategy.get("order_generation_gate"))
    promotion = mapping(order_generation_gate.get("promotion"))
    advancement_fingerprint = promotion.get("strategy_advancement_gate_fingerprint")
    if advancement_fingerprint:
        refs.append(f"strategy_advancement:{advancement_fingerprint}")
    fee_schedule_binding = mapping(promotion.get("fee_schedule_binding"))
    fee_review_fingerprint = fee_schedule_binding.get("fee_schedule_review_fingerprint")
    if fee_review_fingerprint:
        refs.append(f"reviewed_fee_schedule:{fee_review_fingerprint}")
    risk_gate = mapping(evidence.get("risk_gate"))
    risk_decision_id = risk_gate.get("decision_id")
    if risk_decision_id is not None:
        refs.append(f"risk:{risk_decision_id}")
    account_truth = mapping(evidence.get("account_truth"))
    import_run_id = account_truth.get("import_run_id")
    if import_run_id is not None:
        refs.append(f"account_truth:{import_run_id}")
    return refs


def candidate_status(
    candidate: dict[str, Any],
    *names: str,
    nested: tuple[str, ...] = (),
) -> str:
    for name in names:
        value = candidate.get(name)
        if value is not None:
            return status(value, "unknown")
    evidence = mapping(candidate.get("evidence"))
    for nested_name in nested:
        source = mapping(candidate.get(nested_name)) or mapping(
            evidence.get(nested_name)
        )
        for name in names:
            value = source.get(name)
            if value is not None:
                return status(value, "unknown")
    return "unknown"


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def status(value: Any, default: str = "unknown") -> str:
    text = str(value if value is not None else default).strip().lower()
    return text or default


def float_value(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def first_float(*values: Any, fallback: float) -> float:
    for value in values:
        if value is None:
            continue
        return float_value(value, fallback)
    return fallback


def bounded_ratio(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
