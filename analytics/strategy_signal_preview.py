"""Research-only strategy signal preview adapter.

This module bridges the legacy registry/backtest Strategy API, which emits
SignalEvent target weights, into the newer strategy-runtime audit-record shape.
It does not persist signals, create action tasks, create paper orders, mutate
ledger entries, or submit broker orders.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Iterable

import strategy.builtins  # noqa: F401
from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import Symbol
from strategy.registry import StrategyRegistry

_SCHEMA_VERSION = "karkinos.strategy_signal_preview.v1"
_OUTPUT_SCHEMA_VERSION = "karkinos.strategy_runtime_output.v1"
_LIMITATIONS = [
    "Strategy signal preview is research evidence only.",
    "Candidate actions require data, account-truth, risk, paper/shadow, and manual-review gates before any live-like workflow.",
    "This preview does not persist signals, create orders, mutate ledger entries, or submit broker orders.",
]


def build_strategy_signal_preview(
    *,
    strategy_id: str,
    symbol: str,
    params: dict[str, Any] | None,
    bars: Iterable[MarketEvent],
    dataset_snapshot: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run a registered strategy over supplied bars and return audit records."""
    bar_events = tuple(bars)
    normalized_params = dict(params or {})
    snapshot = dict(dataset_snapshot or {})
    snapshot_id = _dataset_snapshot_id(snapshot)
    preview_run_id = run_id or _preview_run_id(
        strategy_id=strategy_id,
        symbol=symbol,
        params=normalized_params,
        bars=bar_events,
        dataset_snapshot_id=snapshot_id,
    )

    event_bus = EventBus()
    signals: list[SignalEvent] = []
    event_bus.subscribe(SignalEvent, signals.append)

    strategy = StrategyRegistry.create(strategy_id, event_bus, **normalized_params)
    strategy.on_init([Symbol(symbol)])
    for bar in bar_events:
        strategy.on_data(bar)
        event_bus.drain()

    outputs = (
        [
            _signal_to_audit_record(
                signal=signal,
                run_id=preview_run_id,
                sequence=index,
                bar_count=len(bar_events),
                dataset_snapshot=snapshot,
            )
            for index, signal in enumerate(signals, start=1)
        ]
        or [
            _no_action_record(
                strategy_id=strategy_id,
                symbol=symbol,
                run_id=preview_run_id,
                bars=bar_events,
                dataset_snapshot=snapshot,
            )
        ]
    )

    return {
        "schema_version": _SCHEMA_VERSION,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "params": normalized_params,
        "run_id": preview_run_id,
        "dataset_snapshot_id": snapshot_id,
        "record_count": len(outputs),
        "outputs": outputs,
        "limitations": list(_LIMITATIONS),
        "does_not_enable_execution": True,
    }


def _signal_to_audit_record(
    *,
    signal: SignalEvent,
    run_id: str,
    sequence: int,
    bar_count: int,
    dataset_snapshot: dict[str, Any],
) -> dict[str, Any]:
    output_type, action = _candidate_type_for_target(signal.target_weight)
    return {
        "schema_version": _OUTPUT_SCHEMA_VERSION,
        "output_id": f"{run_id}:{sequence:04d}:{output_type}",
        "strategy_id": signal.strategy_id,
        "run_id": run_id,
        "hook": "on_bar",
        "output_type": output_type,
        "record_kind": "candidate_action",
        "action": action,
        "reason": _candidate_reason(action=action, target_weight=signal.target_weight),
        "source_event_id": f"{signal.symbol}:{signal.timestamp.isoformat()}",
        "symbol": str(signal.symbol),
        "confidence": None,
        "target_weight": _decimal_text(signal.target_weight),
        "quantity": None,
        "price": _decimal_text(signal.price),
        "evidence": _record_evidence(
            bar_count=bar_count,
            signal=signal,
            dataset_snapshot=dataset_snapshot,
        ),
        "review_gates": _candidate_review_gates(dataset_snapshot),
        "requires_risk_gate": True,
        "requires_account_truth_gate": True,
        "requires_paper_shadow_review": True,
        "requires_manual_review": True,
        "does_not_enable_execution": True,
    }


def _no_action_record(
    *,
    strategy_id: str,
    symbol: str,
    run_id: str,
    bars: tuple[MarketEvent, ...],
    dataset_snapshot: dict[str, Any],
) -> dict[str, Any]:
    source_event_id = (
        f"{bars[-1].symbol}:{bars[-1].timestamp.isoformat()}" if bars else None
    )
    return {
        "schema_version": _OUTPUT_SCHEMA_VERSION,
        "output_id": f"{run_id}:0001:no_action",
        "strategy_id": strategy_id,
        "run_id": run_id,
        "hook": "after_market_close",
        "output_type": "no_action",
        "record_kind": "explanation",
        "action": "no_action",
        "reason": "Strategy emitted no candidate action for the supplied bars.",
        "source_event_id": source_event_id,
        "symbol": symbol,
        "confidence": None,
        "target_weight": None,
        "quantity": None,
        "price": None,
        "evidence": _record_evidence(
            bar_count=len(bars),
            signal=None,
            dataset_snapshot=dataset_snapshot,
        ),
        "review_gates": _no_action_review_gates(dataset_snapshot),
        "requires_risk_gate": False,
        "requires_account_truth_gate": False,
        "requires_paper_shadow_review": False,
        "requires_manual_review": False,
        "does_not_enable_execution": True,
    }


def _candidate_type_for_target(target_weight: Decimal) -> tuple[str, str]:
    if target_weight <= Decimal("0"):
        return "sell_candidate", "sell"
    if target_weight >= Decimal("1"):
        return "buy_candidate", "buy"
    return "rebalance_candidate", "rebalance"


def _candidate_reason(*, action: str, target_weight: Decimal) -> str:
    if action == "buy":
        return "Strategy emitted a buy candidate from the supplied market bars."
    if action == "sell":
        return "Strategy emitted a sell candidate from the supplied market bars."
    return (
        "Strategy emitted a rebalance candidate toward target weight "
        f"{_decimal_text(target_weight)} from the supplied market bars."
    )


def _record_evidence(
    *,
    bar_count: int,
    signal: SignalEvent | None,
    dataset_snapshot: dict[str, Any],
) -> dict[str, Any]:
    status = _data_quality_status(dataset_snapshot)
    evidence: dict[str, Any] = {
        "bar_count": bar_count,
        "dataset_snapshot_id": _dataset_snapshot_id(dataset_snapshot),
        "data_quality_status": status,
        "research_only": True,
        "does_not_enable_execution": True,
    }
    if signal is not None:
        evidence.update(
            {
                "signal_timestamp": signal.timestamp.isoformat(),
                "target_weight": _decimal_text(signal.target_weight),
                "reference_price": _decimal_text(signal.price),
            }
        )
    return evidence


def _candidate_review_gates(dataset_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _data_review_gate(dataset_snapshot),
        {
            "key": "account_truth",
            "status": "not_evaluated",
            "severity": "warning",
            "summary": (
                "Account-truth evidence must be checked before this candidate "
                "can enter any live-like workflow."
            ),
            "required_action": "review_account_truth_evidence",
            "evidence_ref": None,
        },
        {
            "key": "risk",
            "status": "not_evaluated",
            "severity": "warning",
            "summary": (
                "Pre-trade risk requires a sized order intent and current "
                "account context."
            ),
            "required_action": "size_order_and_run_pre_trade_risk_gate",
            "evidence_ref": None,
        },
        {
            "key": "paper_shadow",
            "status": "waiting",
            "severity": "warning",
            "summary": (
                "Paper/shadow preview waits for data, account-truth, and risk "
                "gates."
            ),
            "required_action": "run_paper_shadow_preview_after_gates",
            "evidence_ref": None,
        },
        {
            "key": "manual_review",
            "status": "required",
            "severity": "warning",
            "summary": "Manual review is required before any live-like workflow.",
            "required_action": "manual_confirm_or_reject_candidate",
            "evidence_ref": None,
        },
    ]


def _no_action_review_gates(dataset_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _data_review_gate(dataset_snapshot),
        {
            "key": "account_truth",
            "status": "not_required",
            "severity": "info",
            "summary": (
                "No candidate action was emitted, so account-truth gate is not "
                "required."
            ),
            "required_action": None,
            "evidence_ref": None,
        },
        {
            "key": "risk",
            "status": "not_required",
            "severity": "info",
            "summary": (
                "No candidate action was emitted, so pre-trade risk gate is not "
                "required."
            ),
            "required_action": None,
            "evidence_ref": None,
        },
        {
            "key": "paper_shadow",
            "status": "not_required",
            "severity": "info",
            "summary": (
                "No candidate action was emitted, so paper/shadow preview is not "
                "required."
            ),
            "required_action": None,
            "evidence_ref": None,
        },
        {
            "key": "manual_review",
            "status": "not_required",
            "severity": "info",
            "summary": "No candidate action was emitted, so manual review is not required.",
            "required_action": None,
            "evidence_ref": None,
        },
    ]


def _data_review_gate(dataset_snapshot: dict[str, Any]) -> dict[str, Any]:
    status = _data_quality_status(dataset_snapshot)
    snapshot_id = _dataset_snapshot_id(dataset_snapshot)
    normalized = status.lower()
    if normalized in {"pass", "ok", "complete", "confirmed", "live"}:
        return {
            "key": "data",
            "status": status,
            "severity": "info",
            "summary": "Dataset snapshot is available for the preview bars.",
            "required_action": None,
            "evidence_ref": snapshot_id,
        }
    if normalized in {"blocked", "missing", "unavailable"}:
        return {
            "key": "data",
            "status": status,
            "severity": "critical",
            "summary": "Dataset snapshot is unavailable for the preview bars.",
            "required_action": "repair_dataset_snapshot",
            "evidence_ref": snapshot_id,
        }
    return {
        "key": "data",
        "status": status,
        "severity": "warning",
        "summary": f"Dataset snapshot is {status} for the preview bars.",
        "required_action": "review_dataset_quality",
        "evidence_ref": snapshot_id,
    }


def _dataset_snapshot_id(dataset_snapshot: dict[str, Any]) -> str | None:
    snapshot_id = dataset_snapshot.get("snapshot_id")
    return str(snapshot_id) if snapshot_id else None


def _data_quality_status(dataset_snapshot: dict[str, Any]) -> str:
    data_quality = dataset_snapshot.get("data_quality")
    if isinstance(data_quality, dict) and data_quality.get("status"):
        return str(data_quality["status"])
    if dataset_snapshot.get("status"):
        return str(dataset_snapshot["status"])
    return "unknown"


def _preview_run_id(
    *,
    strategy_id: str,
    symbol: str,
    params: dict[str, Any],
    bars: tuple[MarketEvent, ...],
    dataset_snapshot_id: str | None,
) -> str:
    payload = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "params": params,
        "dataset_snapshot_id": dataset_snapshot_id,
        "bars": [
            {
                "timestamp": bar.timestamp.isoformat(),
                "symbol": str(bar.symbol),
                "close": _decimal_text(bar.close),
                "frequency": bar.frequency.value,
            }
            for bar in bars
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:12]
    return f"signal-preview:{strategy_id}:{symbol}:{digest}"


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
