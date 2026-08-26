"""Frozen sealed-time holdout evidence for AI strategy research.

A sealed holdout is the tail of the operator-frozen backtest window that the
model must never see while proposing or iterating on hypotheses.  It is
evaluated exactly once against the frozen champion, and its consumption is
recorded so the same partition cannot be reused for further selection.

This module is a deterministic, provider-free analytics primitive.  It does not
contact a model, mutate strategy/order authority, or grant trading permission.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from backtest.result import BacktestResult
from core.events import FillEvent

SEALED_HOLDOUT_EVIDENCE_SCHEMA_VERSION = "karkinos.sealed_holdout_validation.v1"
SEALED_PARTITION_CONTRACT = "karkinos.sealed_partition.v1"
SEALED_CONSUMPTION_RECEIPT_CONTRACT = "karkinos.sealed_partition_consumption.v1"

_DEFAULT_HOLDOUT_FRACTION = Decimal("0.20")
_MIN_HOLDOUT_FRACTION = Decimal("0.05")
_MAX_HOLDOUT_FRACTION = Decimal("0.50")
_MIN_PARTITION_DAYS = 2


@dataclass(frozen=True)
class SealedHoldoutPartition:
    """A frozen split of the operator window into research and sealed tails."""

    research_start: date
    research_end: date
    sealed_start: date
    sealed_end: date
    holdout_fraction: Decimal

    def __post_init__(self) -> None:
        if not (
            self.research_start
            <= self.research_end
            < self.sealed_start
            <= self.sealed_end
        ):
            raise ValueError("sealed_partition_order_invalid")
        if (self.sealed_start - self.research_end) != timedelta(days=1):
            raise ValueError("sealed_partition_not_contiguous")
        if not (
            _MIN_HOLDOUT_FRACTION <= self.holdout_fraction <= _MAX_HOLDOUT_FRACTION
        ):
            raise ValueError("sealed_partition_fraction_out_of_bounds")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SEALED_PARTITION_CONTRACT,
            "research_start": self.research_start.isoformat(),
            "research_end": self.research_end.isoformat(),
            "sealed_start": self.sealed_start.isoformat(),
            "sealed_end": self.sealed_end.isoformat(),
            "holdout_fraction": float(self.holdout_fraction),
        }

    @property
    def partition_fingerprint(self) -> str:
        return "sha256:" + _fingerprint(self.to_json_dict())

    @property
    def sealed_days(self) -> int:
        return (self.sealed_end - self.sealed_start).days + 1


def split_sealed_holdout(
    *,
    start_date: str,
    end_date: str,
    holdout_fraction: Decimal | float = _DEFAULT_HOLDOUT_FRACTION,
) -> SealedHoldoutPartition:
    """Split a frozen window into a research tail and a sealed holdout tail."""

    start = _date(start_date, "start_date")
    end = _date(end_date, "end_date")
    if end - start < timedelta(days=_MIN_PARTITION_DAYS - 1):
        raise ValueError("sealed_partition_window_too_short")
    fraction = Decimal(str(holdout_fraction))
    if not fraction.is_finite() or not (
        _MIN_HOLDOUT_FRACTION <= fraction <= _MAX_HOLDOUT_FRACTION
    ):
        raise ValueError("sealed_holdout_fraction_out_of_bounds")
    total_days = (end - start).days + 1
    sealed_days = max(1, int(round(total_days * float(fraction))))
    research_end = end - timedelta(days=sealed_days)
    if research_end < start:
        raise ValueError("sealed_holdout_leaves_no_research_window")
    sealed_start = research_end + timedelta(days=1)
    return SealedHoldoutPartition(
        research_start=start,
        research_end=research_end,
        sealed_start=sealed_start,
        sealed_end=end,
        holdout_fraction=fraction,
    )


def sealed_return_from_result(
    result: BacktestResult,
    partition: SealedHoldoutPartition,
) -> Decimal:
    """Extract the sealed-tail net return from a full-window backtest result."""

    sealed_start = datetime.combine(partition.sealed_start, datetime.min.time())
    boundary = [equity for ts, equity in result.equity_curve if ts < sealed_start]
    sealed = [equity for ts, equity in result.equity_curve if ts >= sealed_start]
    if not boundary or not sealed:
        raise ValueError("sealed_evaluation_insufficient_sealed_bars")
    initial_equity = boundary[-1]
    final_equity = sealed[-1]
    if initial_equity == Decimal("0"):
        return Decimal("0")
    return (final_equity - initial_equity) / initial_equity


def build_sealed_partition(
    *,
    research_start: str,
    research_end: str,
    sealed_end: str,
) -> SealedHoldoutPartition:
    """Build a sealed partition from an explicit research window and holdout end.

    The sealed tail is the future window ``[research_end + 1 day, sealed_end]``;
    the research window is ``[research_start, research_end]``.  The holdout
    fraction is derived from the explicit dates and must still satisfy the
    partition's meaningful-holdout bounds.
    """

    rs = _date(research_start, "research_start")
    re_ = _date(research_end, "research_end")
    se = _date(sealed_end, "sealed_end")
    if re_ >= se:
        raise ValueError("sealed_end_must_follow_research_end")
    sealed_start = re_ + timedelta(days=1)
    total_days = (se - rs).days + 1
    sealed_days = (se - sealed_start).days + 1
    fraction = Decimal(sealed_days) / Decimal(total_days)
    return SealedHoldoutPartition(
        research_start=rs,
        research_end=re_,
        sealed_start=sealed_start,
        sealed_end=se,
        holdout_fraction=fraction,
    )


@dataclass(frozen=True)
class SealedPartitionConsumptionReceipt:
    """A durable, one-time record that a sealed partition was consumed."""

    research_family_id: str
    partition_fingerprint: str
    champion_formula_fingerprint: str
    consumed_at: str
    evaluator_code_revision: str

    def __post_init__(self) -> None:
        if not all(
            str(getattr(self, field)).strip()
            for field in (
                "research_family_id",
                "partition_fingerprint",
                "champion_formula_fingerprint",
                "consumed_at",
                "evaluator_code_revision",
            )
        ):
            raise ValueError("sealed_consumption_receipt_missing_field")
        if not self.partition_fingerprint.startswith("sha256:"):
            raise ValueError("sealed_partition_fingerprint_invalid")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SEALED_CONSUMPTION_RECEIPT_CONTRACT,
            "research_family_id": self.research_family_id,
            "partition_fingerprint": self.partition_fingerprint,
            "champion_formula_fingerprint": self.champion_formula_fingerprint,
            "consumed_at": self.consumed_at,
            "evaluator_code_revision": self.evaluator_code_revision,
        }

    @property
    def receipt_fingerprint(self) -> str:
        return "sha256:" + _fingerprint(self.to_json_dict())


def build_consumption_receipt(
    *,
    research_family_id: str,
    partition: SealedHoldoutPartition,
    champion_formula_fingerprint: str,
    consumed_at: str,
    evaluator_code_revision: str,
) -> SealedPartitionConsumptionReceipt:
    """Create a one-time consumption receipt for a sealed partition."""

    return SealedPartitionConsumptionReceipt(
        research_family_id=research_family_id,
        partition_fingerprint=partition.partition_fingerprint,
        champion_formula_fingerprint=champion_formula_fingerprint,
        consumed_at=consumed_at,
        evaluator_code_revision=evaluator_code_revision,
    )


def is_partition_consumed(
    prior_receipts: Any,
    partition_fingerprint: str,
) -> bool:
    """Return whether any prior receipt already consumed this partition."""

    if not isinstance(prior_receipts, (list, tuple)):
        return False
    for receipt in prior_receipts:
        if not isinstance(receipt, Mapping):
            continue
        if receipt.get("partition_fingerprint") == partition_fingerprint:
            return True
        if receipt.get("partition_fingerprint") is None:
            payload = _validated_receipt(receipt)
            if (
                payload is not None
                and payload.get("partition_fingerprint") == partition_fingerprint
            ):
                return True
    return False


@dataclass(frozen=True)
class SealedHoldoutEvaluationEvidence:
    """After-cost performance of the frozen champion on the sealed tail."""

    strategy_id: str
    benchmark_role: str
    research_family_id: str
    formula_fingerprint: str
    partition: SealedHoldoutPartition
    sealed_return: Decimal
    benchmark_return: Decimal | None
    excess_return: Decimal | None
    passed_benchmark: bool | None
    sealed_cost: Decimal
    sealed_fill_count: int
    sealed_bar_count: int
    validation_status: str
    assumptions: list[str]
    limitations: list[str]

    def to_json_dict(self) -> dict[str, Any]:
        core = {
            "schema_version": SEALED_HOLDOUT_EVIDENCE_SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "benchmark_role": self.benchmark_role,
            "research_family_id": self.research_family_id,
            "formula_fingerprint": self.formula_fingerprint,
            "partition": self.partition.to_json_dict(),
            "partition_fingerprint": self.partition.partition_fingerprint,
            "sealed_return": float(self.sealed_return),
            "benchmark_return": (
                float(self.benchmark_return)
                if self.benchmark_return is not None
                else None
            ),
            "excess_return": (
                float(self.excess_return) if self.excess_return is not None else None
            ),
            "passed_benchmark": self.passed_benchmark,
            "sealed_cost": float(self.sealed_cost),
            "sealed_fill_count": self.sealed_fill_count,
            "sealed_bar_count": self.sealed_bar_count,
            "consumed_once": True,
            "validation_status": self.validation_status,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "persisted_backtest_result_only": True,
            "human_review_required": True,
            "authorizes_execution": False,
            "does_not_change_capital_authority": True,
        }
        return {**core, "evidence_fingerprint": _fingerprint(core)}


def build_sealed_holdout_evaluation(
    *,
    strategy_id: str,
    benchmark_role: str,
    research_family_id: str,
    formula_fingerprint: str,
    partition: SealedHoldoutPartition,
    result: BacktestResult,
    benchmark_return: Decimal | None = None,
    prior_consumption_receipts: Any = (),
    assumptions: list[str] | None = None,
    limitations: list[str] | None = None,
) -> SealedHoldoutEvaluationEvidence:
    """Measure the frozen champion on the sealed tail, exactly once."""

    if is_partition_consumed(
        prior_consumption_receipts, partition.partition_fingerprint
    ):
        raise ValueError("sealed_partition_already_consumed")
    if not str(strategy_id).strip() or not str(benchmark_role).strip():
        raise ValueError("sealed_evaluation_identity_missing")
    if not str(research_family_id).strip():
        raise ValueError("sealed_evaluation_research_family_missing")
    if not str(formula_fingerprint).startswith("sha256:"):
        raise ValueError("sealed_evaluation_formula_fingerprint_invalid")

    sealed_start = datetime.combine(partition.sealed_start, datetime.min.time())
    sealed_points = [
        (ts, equity) for ts, equity in result.equity_curve if ts >= sealed_start
    ]
    boundary_points = [
        (ts, equity) for ts, equity in result.equity_curve if ts < sealed_start
    ]
    if not boundary_points or len(sealed_points) < 1:
        raise ValueError("sealed_evaluation_insufficient_sealed_bars")
    boundary_equity = boundary_points[-1][1]
    sealed_initial_equity = boundary_equity
    sealed_final_equity = sealed_points[-1][1]
    sealed_fills = [fill for fill in result.fills if fill.timestamp >= sealed_start]
    sealed_cost = sum(
        (fill.commission + fill.slippage for fill in sealed_fills), Decimal("0")
    )
    if sealed_initial_equity == Decimal("0"):
        sealed_return = Decimal("0")
    else:
        sealed_return = (
            sealed_final_equity - sealed_initial_equity
        ) / sealed_initial_equity
    excess_return = (
        sealed_return - benchmark_return if benchmark_return is not None else None
    )
    passed_benchmark = (
        sealed_return > benchmark_return if benchmark_return is not None else None
    )
    validation_status = (
        "sealed_passed"
        if passed_benchmark is True
        else (
            "sealed_failed" if passed_benchmark is False else "benchmark_not_supplied"
        )
    )
    return SealedHoldoutEvaluationEvidence(
        strategy_id=strategy_id,
        benchmark_role=benchmark_role,
        research_family_id=research_family_id,
        formula_fingerprint=formula_fingerprint,
        partition=partition,
        sealed_return=sealed_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        passed_benchmark=passed_benchmark,
        sealed_cost=sealed_cost,
        sealed_fill_count=len(sealed_fills),
        sealed_bar_count=len(sealed_points),
        validation_status=validation_status,
        assumptions=assumptions
        or [
            "Sealed holdout evaluation is computed from a completed deterministic backtest result.",
            "The sealed tail is never exposed to the model before the champion is frozen.",
        ],
        limitations=limitations
        or [
            "Sealed holdout evidence is not investment advice or a profitability guarantee.",
            "A sealed tail measures temporal generalization, not cross-sectional or live-trading generalization.",
        ],
    )


def is_valid_sealed_holdout_evaluation(value: Any) -> bool:
    """Replay and validate a persisted sealed-holdout evaluation."""

    if not isinstance(value, Mapping):
        return False
    payload = dict(value)
    fingerprint = str(payload.pop("evidence_fingerprint", ""))
    if len(fingerprint) != 64 or fingerprint != _fingerprint(payload):
        return False
    if payload.get("schema_version") != SEALED_HOLDOUT_EVIDENCE_SCHEMA_VERSION:
        return False
    if not str(payload.get("strategy_id") or "").strip():
        return False
    if not str(payload.get("benchmark_role") or "").strip():
        return False
    if not str(payload.get("research_family_id") or "").strip():
        return False
    if not str(payload.get("formula_fingerprint") or "").startswith("sha256:"):
        return False
    if payload.get("consumed_once") is not True:
        return False
    if payload.get("persisted_backtest_result_only") is not True:
        return False
    if payload.get("human_review_required") is not True:
        return False
    if payload.get("authorizes_execution") is not False:
        return False
    if payload.get("does_not_change_capital_authority") is not True:
        return False
    partition = _validated_partition(payload.get("partition"))
    if partition is None:
        return False
    if payload.get("partition_fingerprint") != partition.partition_fingerprint:
        return False
    sealed_return = _decimal(payload.get("sealed_return"))
    benchmark_return = _optional_decimal(payload.get("benchmark_return"))
    excess_return = _optional_decimal(payload.get("excess_return"))
    passed_benchmark = payload.get("passed_benchmark")
    sealed_cost = _decimal(payload.get("sealed_cost"))
    sealed_fill_count = _integer(payload.get("sealed_fill_count"))
    sealed_bar_count = _integer(payload.get("sealed_bar_count"))
    if (
        sealed_return is None
        or sealed_cost is None
        or sealed_cost < 0
        or sealed_fill_count is None
        or sealed_fill_count < 0
        or sealed_bar_count is None
        or sealed_bar_count < 1
    ):
        return False
    if benchmark_return is None:
        if excess_return is not None or passed_benchmark is not None:
            return False
    else:
        expected_excess = sealed_return - benchmark_return
        expected_passed = sealed_return > benchmark_return
        if (
            excess_return is None
            or not _close_decimal(excess_return, expected_excess)
            or passed_benchmark is not expected_passed
        ):
            return False
    expected_status = (
        "sealed_passed"
        if passed_benchmark is True
        else (
            "sealed_failed" if passed_benchmark is False else "benchmark_not_supplied"
        )
    )
    if payload.get("validation_status") != expected_status:
        return False
    if not _nonempty_string_list(payload.get("assumptions")):
        return False
    if not _nonempty_string_list(payload.get("limitations")):
        return False
    return True


def _validated_partition(value: Any) -> SealedHoldoutPartition | None:
    if not isinstance(value, Mapping):
        return None
    try:
        partition = SealedHoldoutPartition(
            research_start=_date(value.get("research_start"), "research_start"),
            research_end=_date(value.get("research_end"), "research_end"),
            sealed_start=_date(value.get("sealed_start"), "sealed_start"),
            sealed_end=_date(value.get("sealed_end"), "sealed_end"),
            holdout_fraction=_decimal(value.get("holdout_fraction")),
        )
    except (ValueError, InvalidOperation, TypeError):
        return None
    if partition.holdout_fraction is None:
        return None
    if value.get("schema_version") != SEALED_PARTITION_CONTRACT:
        return None
    if float(partition.holdout_fraction) != value.get("holdout_fraction"):
        return None
    return partition


def _validated_receipt(value: Mapping[str, Any]) -> dict[str, Any] | None:
    if value.get("schema_version") != SEALED_CONSUMPTION_RECEIPT_CONTRACT:
        return None
    return dict(value)


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field}_invalid") from exc


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else _decimal(value)


def _close_decimal(left: Decimal, right: Decimal) -> bool:
    tolerance = max(
        Decimal("1e-9"),
        max(abs(left), abs(right)) * Decimal("1e-9"),
    )
    return abs(left - right) <= tolerance


def _nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "SEALED_HOLDOUT_EVIDENCE_SCHEMA_VERSION",
    "SealedHoldoutPartition",
    "SealedPartitionConsumptionReceipt",
    "SealedHoldoutEvaluationEvidence",
    "split_sealed_holdout",
    "build_sealed_partition",
    "sealed_return_from_result",
    "build_consumption_receipt",
    "is_partition_consumed",
    "build_sealed_holdout_evaluation",
    "is_valid_sealed_holdout_evaluation",
]
