"""Deterministic next-session Formula signals for normalized research only."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from server.ai_runtime.formula_dsl import evaluate_formula
from server.contracts.content_identity import content_fingerprint

NORMALIZED_RESEARCH_OPERATION_PREVIEW_SCHEMA = (
    "karkinos.ai.normalized_formula_operation_preview.v1"
)
NORMALIZED_RESEARCH_OPERATION_RECOMMENDATION_SCHEMA = (
    "karkinos.ai.normalized_research_operation_recommendation.v1"
)

_PREVIEW_FIELDS = (
    "schema_version",
    "status",
    "dataset_snapshot_id",
    "formula_fingerprint",
    "research_window_end_date",
    "signal_observed_at",
    "execution_timing",
    "allocation_slots",
    "canonical_target_weight",
    "entry_condition_count",
    "exit_condition_count",
    "selected_buy_candidate_count",
    "omitted_buy_candidate_count",
    "operations",
    "blockers",
    "deterministic",
    "persisted_frozen_bars_only",
    "provider_selects_operations",
    "account_qualification_status",
    "account_positions_evaluated",
    "research_only",
    "executable",
    "authorizes_order_creation",
    "authorizes_execution",
    "authority_effect",
    "evidence_fingerprint",
)
_OPERATION_FIELDS = (
    "symbol",
    "signal_date",
    "signal_type",
    "operation",
    "target_weight",
    "account_position_status",
    "next_session_only",
    "research_only",
    "executable",
)
_RECOMMENDATION_FIELDS = {
    "schema_version",
    "status",
    "research_winner_candidate_id",
    "run_id",
    "market_date",
    "source_preview_fingerprint",
    "dataset_snapshot_id",
    "formula_fingerprint",
    "research_window_end_date",
    "signal_observed_at",
    "execution_timing",
    "allocation_slots",
    "canonical_target_weight",
    "operations",
    "blockers",
    "account_qualification_status",
    "account_positions_evaluated",
    "research_only",
    "executable",
    "authorizes_order_creation",
    "authorizes_execution",
    "authority_effect",
    "evidence_fingerprint",
}


def build_normalized_research_operation_preview(
    *,
    formula_ast: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    dataset_snapshot_id: str,
    formula_fingerprint: str,
    research_window_end_date: str,
    allocation_slots: int,
) -> dict[str, Any]:
    """Evaluate the Formula on each exact final frozen bar.

    This projection intentionally knows nothing about holdings or capital. An
    exit condition is therefore represented as ``exit_if_held_candidate`` and
    can never be interpreted as an immediately sellable account position.
    """

    slots = max(1, int(allocation_slots))
    target_weight = 1.0 / slots
    blockers: list[str] = []
    entry_symbols: list[tuple[str, str]] = []
    exit_symbols: list[tuple[str, str]] = []
    observed_at: set[str] = set()

    for symbol, raw_frame in sorted(frames.items()):
        if not isinstance(raw_frame, pd.DataFrame) or raw_frame.empty:
            blockers.append(f"frozen_bar_missing:{symbol}")
            continue
        frame = raw_frame.copy()
        if "timestamp" not in frame.columns:
            blockers.append(f"frozen_bar_timestamp_missing:{symbol}")
            continue
        try:
            timestamp = pd.Timestamp(frame.iloc[-1]["timestamp"])
            if timestamp.date().isoformat() != research_window_end_date:
                blockers.append(f"frozen_bar_end_date_mismatch:{symbol}")
                continue
            entry, exit_signal, _ = evaluate_formula(
                formula_ast,
                frame,
                universe_size=len(frames),
            )
        except Exception:
            blockers.append(f"formula_final_bar_evaluation_failed:{symbol}")
            continue
        timestamp_text = timestamp.isoformat()
        observed_at.add(timestamp_text)
        if bool(exit_signal.iloc[-1]):
            exit_symbols.append((symbol, timestamp_text))
        elif bool(entry.iloc[-1]):
            entry_symbols.append((symbol, timestamp_text))

    if len(observed_at) > 1:
        blockers.append("frozen_bar_timestamp_mismatch")

    operations: list[dict[str, Any]] = []
    if not blockers:
        operations.extend(
            _operation(
                symbol=symbol,
                signal_date=research_window_end_date,
                signal_type="exit",
                operation="exit_if_held_candidate",
                target_weight=0.0,
            )
            for symbol, _ in exit_symbols
        )
        operations.extend(
            _operation(
                symbol=symbol,
                signal_date=research_window_end_date,
                signal_type="entry",
                operation="buy_candidate",
                target_weight=target_weight,
            )
            for symbol, _ in entry_symbols[:slots]
        )

    status = (
        "unavailable"
        if blockers
        else ("available" if operations else "no_formula_condition")
    )
    core = {
        "schema_version": NORMALIZED_RESEARCH_OPERATION_PREVIEW_SCHEMA,
        "status": status,
        "dataset_snapshot_id": dataset_snapshot_id,
        "formula_fingerprint": formula_fingerprint,
        "research_window_end_date": research_window_end_date,
        "signal_observed_at": (
            next(iter(observed_at)) if len(observed_at) == 1 else None
        ),
        "execution_timing": "next_verified_market_session",
        "allocation_slots": slots,
        "canonical_target_weight": target_weight,
        "entry_condition_count": len(entry_symbols),
        "exit_condition_count": len(exit_symbols),
        "selected_buy_candidate_count": (
            min(len(entry_symbols), slots) if not blockers else 0
        ),
        "omitted_buy_candidate_count": (
            max(0, len(entry_symbols) - slots) if not blockers else 0
        ),
        "operations": operations,
        "blockers": sorted(set(blockers)),
        "deterministic": True,
        "persisted_frozen_bars_only": True,
        "provider_selects_operations": False,
        "account_qualification_status": "not_evaluated",
        "account_positions_evaluated": False,
        "research_only": True,
        "executable": False,
        "authorizes_order_creation": False,
        "authorizes_execution": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def project_normalized_research_operation_preview(value: Any) -> dict[str, Any] | None:
    """Validate and copy only the canonical preview allowlist."""

    if not isinstance(value, Mapping):
        return None
    projected = {key: value.get(key) for key in _PREVIEW_FIELDS}
    operations = value.get("operations")
    if not isinstance(operations, list):
        return None
    projected["operations"] = [
        {key: operation.get(key) for key in _OPERATION_FIELDS}
        for operation in operations
        if isinstance(operation, Mapping)
    ]
    if len(projected["operations"]) != len(operations):
        return None
    if set(value) != set(_PREVIEW_FIELDS) or not _valid_preview(projected):
        return None
    return projected


def bind_research_winner_operation_preview(
    *,
    preview: Any,
    candidate_id: str,
    run_id: str,
    market_date: str,
) -> dict[str, Any]:
    """Bind one validated preview to the deterministic research winner."""

    projected = project_normalized_research_operation_preview(preview)
    if projected is None:
        return unavailable_research_operation_recommendation(
            reason="winner_operation_preview_invalid_or_missing",
            candidate_id=candidate_id,
            run_id=run_id,
            market_date=market_date,
        )
    core = {
        "schema_version": NORMALIZED_RESEARCH_OPERATION_RECOMMENDATION_SCHEMA,
        "status": projected["status"],
        "research_winner_candidate_id": candidate_id,
        "run_id": run_id,
        "market_date": market_date,
        "source_preview_fingerprint": projected["evidence_fingerprint"],
        "dataset_snapshot_id": projected["dataset_snapshot_id"],
        "formula_fingerprint": projected["formula_fingerprint"],
        "research_window_end_date": projected["research_window_end_date"],
        "signal_observed_at": projected["signal_observed_at"],
        "execution_timing": projected["execution_timing"],
        "allocation_slots": projected["allocation_slots"],
        "canonical_target_weight": projected["canonical_target_weight"],
        "operations": projected["operations"],
        "blockers": projected["blockers"],
        "account_qualification_status": "not_evaluated",
        "account_positions_evaluated": False,
        "research_only": True,
        "executable": False,
        "authorizes_order_creation": False,
        "authorizes_execution": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def unavailable_research_operation_recommendation(
    *,
    reason: str,
    candidate_id: str | None = None,
    run_id: str | None = None,
    market_date: str | None = None,
) -> dict[str, Any]:
    """Return one explicit, non-authorizing fail-closed read artifact."""

    core = {
        "schema_version": NORMALIZED_RESEARCH_OPERATION_RECOMMENDATION_SCHEMA,
        "status": "unavailable",
        "research_winner_candidate_id": candidate_id,
        "run_id": run_id,
        "market_date": market_date,
        "source_preview_fingerprint": None,
        "dataset_snapshot_id": None,
        "formula_fingerprint": None,
        "research_window_end_date": None,
        "signal_observed_at": None,
        "execution_timing": "next_verified_market_session",
        "allocation_slots": None,
        "canonical_target_weight": None,
        "operations": [],
        "blockers": [reason],
        "account_qualification_status": "not_evaluated",
        "account_positions_evaluated": False,
        "research_only": True,
        "executable": False,
        "authorizes_order_creation": False,
        "authorizes_execution": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def is_valid_research_operation_recommendation(value: Any) -> bool:
    """Validate the winner-bound artifact before any public projection."""

    if not isinstance(value, Mapping):
        return False
    if set(value) != _RECOMMENDATION_FIELDS:
        return False
    payload = dict(value)
    fingerprint = payload.pop("evidence_fingerprint", None)
    operations = payload.get("operations")
    if not isinstance(operations, list) or any(
        not isinstance(item, Mapping) or set(item) != set(_OPERATION_FIELDS)
        for item in operations
    ):
        return False
    status = payload.get("status")
    blockers = payload.get("blockers")
    source_preview_fingerprint = payload.get("source_preview_fingerprint")
    if not isinstance(blockers, list) or any(
        not isinstance(item, str) or not item for item in blockers
    ):
        return False
    if not _valid_operation_list(
        operations,
        allocation_slots=payload.get("allocation_slots"),
        canonical_target_weight=payload.get("canonical_target_weight"),
        signal_date=payload.get("research_window_end_date"),
    ):
        return False
    return (
        payload.get("schema_version")
        == NORMALIZED_RESEARCH_OPERATION_RECOMMENDATION_SCHEMA
        and status in {"available", "no_formula_condition", "unavailable"}
        and (status == "available") == bool(operations)
        and (status == "unavailable") == bool(blockers)
        and (
            (
                _valid_fingerprint(source_preview_fingerprint)
                and _valid_fingerprint(payload.get("dataset_snapshot_id"))
                and _valid_fingerprint(payload.get("formula_fingerprint"))
            )
            or (
                status == "unavailable"
                and source_preview_fingerprint is None
                and payload.get("dataset_snapshot_id") is None
                and payload.get("formula_fingerprint") is None
                and payload.get("research_window_end_date") is None
                and payload.get("signal_observed_at") is None
                and payload.get("allocation_slots") is None
                and payload.get("canonical_target_weight") is None
            )
        )
        and payload.get("execution_timing") == "next_verified_market_session"
        and payload.get("account_qualification_status") == "not_evaluated"
        and payload.get("account_positions_evaluated") is False
        and payload.get("research_only") is True
        and payload.get("executable") is False
        and payload.get("authorizes_order_creation") is False
        and payload.get("authorizes_execution") is False
        and payload.get("authority_effect") == "none"
        and isinstance(fingerprint, str)
        and fingerprint == content_fingerprint(payload)
    )


def _operation(
    *,
    symbol: str,
    signal_date: str,
    signal_type: str,
    operation: str,
    target_weight: float,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "signal_date": signal_date,
        "signal_type": signal_type,
        "operation": operation,
        "target_weight": target_weight,
        "account_position_status": "not_evaluated",
        "next_session_only": True,
        "research_only": True,
        "executable": False,
    }


def _valid_preview(value: Mapping[str, Any]) -> bool:
    payload = dict(value)
    fingerprint = payload.pop("evidence_fingerprint", None)
    operations = payload.get("operations")
    status = payload.get("status")
    blockers = payload.get("blockers")
    if not isinstance(operations, list) or any(
        not isinstance(item, Mapping) or set(item) != set(_OPERATION_FIELDS)
        for item in operations
    ):
        return False
    if not isinstance(blockers, list) or any(
        not isinstance(item, str) or not item for item in blockers
    ):
        return False
    buy_operations = [
        item for item in operations if item.get("operation") == "buy_candidate"
    ]
    operation_order = [
        (
            0 if item.get("operation") == "exit_if_held_candidate" else 1,
            item.get("symbol"),
        )
        for item in operations
    ]
    return (
        payload.get("schema_version") == NORMALIZED_RESEARCH_OPERATION_PREVIEW_SCHEMA
        and status in {"available", "no_formula_condition", "unavailable"}
        and (status == "available") == bool(operations)
        and (status == "unavailable") == bool(blockers)
        and _valid_fingerprint(payload.get("dataset_snapshot_id"))
        and _valid_fingerprint(payload.get("formula_fingerprint"))
        and len(buy_operations) <= int(payload.get("allocation_slots") or 0)
        and operation_order == sorted(operation_order)
        and _valid_operation_list(
            operations,
            allocation_slots=payload.get("allocation_slots"),
            canonical_target_weight=payload.get("canonical_target_weight"),
            signal_date=payload.get("research_window_end_date"),
        )
        and payload.get("execution_timing") == "next_verified_market_session"
        and payload.get("deterministic") is True
        and payload.get("persisted_frozen_bars_only") is True
        and payload.get("provider_selects_operations") is False
        and payload.get("account_qualification_status") == "not_evaluated"
        and payload.get("account_positions_evaluated") is False
        and payload.get("research_only") is True
        and payload.get("executable") is False
        and payload.get("authorizes_order_creation") is False
        and payload.get("authorizes_execution") is False
        and payload.get("authority_effect") == "none"
        and isinstance(fingerprint, str)
        and fingerprint == content_fingerprint(payload)
    )


def _valid_operation_list(
    operations: list[Any],
    *,
    allocation_slots: Any,
    canonical_target_weight: Any,
    signal_date: Any,
) -> bool:
    try:
        slots = int(allocation_slots)
        target_weight = float(canonical_target_weight)
    except (TypeError, ValueError):
        return (
            not operations
            and allocation_slots is None
            and canonical_target_weight is None
        )
    if slots < 1 or target_weight != 1.0 / slots or not str(signal_date or ""):
        return False
    buy_count = 0
    order_keys: list[tuple[int, str]] = []
    for item in operations:
        if not isinstance(item, Mapping) or set(item) != set(_OPERATION_FIELDS):
            return False
        operation = item.get("operation")
        symbol = str(item.get("symbol") or "")
        try:
            item_weight = float(item.get("target_weight"))
        except (TypeError, ValueError):
            return False
        if operation == "buy_candidate":
            buy_count += 1
            semantic_valid = (
                item.get("signal_type") == "entry" and item_weight == target_weight
            )
            priority = 1
        elif operation == "exit_if_held_candidate":
            semantic_valid = item.get("signal_type") == "exit" and item_weight == 0.0
            priority = 0
        else:
            return False
        if (
            not symbol
            or not semantic_valid
            or item.get("signal_date") != signal_date
            or item.get("account_position_status") != "not_evaluated"
            or item.get("next_session_only") is not True
            or item.get("research_only") is not True
            or item.get("executable") is not False
        ):
            return False
        order_keys.append((priority, symbol))
    return buy_count <= slots and order_keys == sorted(order_keys)


def _valid_fingerprint(value: Any) -> bool:
    text = str(value or "").removeprefix("sha256:")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


__all__ = [
    "NORMALIZED_RESEARCH_OPERATION_PREVIEW_SCHEMA",
    "NORMALIZED_RESEARCH_OPERATION_RECOMMENDATION_SCHEMA",
    "bind_research_winner_operation_preview",
    "build_normalized_research_operation_preview",
    "is_valid_research_operation_recommendation",
    "project_normalized_research_operation_preview",
    "unavailable_research_operation_recommendation",
]
