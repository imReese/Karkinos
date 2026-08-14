"""Out-of-sample validation evidence for backtest results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from backtest.result import BacktestResult
from core.events import FillEvent

ROLLING_OOS_EVIDENCE_SCHEMA_VERSION = "karkinos.rolling_oos_validation.v1"


@dataclass(frozen=True)
class ValidationSegmentEvidence:
    """After-cost evidence for one validation segment."""

    start_timestamp: datetime
    end_timestamp: datetime
    initial_equity: Decimal
    final_equity: Decimal
    net_pnl: Decimal
    net_return: Decimal
    total_cost: Decimal
    gross_pnl_before_costs: Decimal
    gross_return_before_costs: Decimal
    fill_count: int

    def to_json_dict(self) -> dict:
        return {
            "start_timestamp": self.start_timestamp.isoformat(),
            "end_timestamp": self.end_timestamp.isoformat(),
            "initial_equity": float(self.initial_equity),
            "final_equity": float(self.final_equity),
            "net_pnl": float(self.net_pnl),
            "net_return": float(self.net_return),
            "total_cost": float(self.total_cost),
            "gross_pnl_before_costs": float(self.gross_pnl_before_costs),
            "gross_return_before_costs": float(self.gross_return_before_costs),
            "fill_count": self.fill_count,
        }


@dataclass(frozen=True)
class OutOfSampleValidationEvidence:
    """Audit-friendly evidence for strategy out-of-sample validation."""

    strategy_id: str
    benchmark_role: str
    split_timestamp: datetime
    in_sample: ValidationSegmentEvidence
    out_of_sample: ValidationSegmentEvidence
    benchmark_return: Decimal | None
    excess_return: Decimal | None
    passed_benchmark: bool | None
    validation_status: str
    assumptions: list[str]
    limitations: list[str]

    def to_json_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "benchmark_role": self.benchmark_role,
            "split_timestamp": self.split_timestamp.isoformat(),
            "in_sample": self.in_sample.to_json_dict(),
            "out_of_sample": self.out_of_sample.to_json_dict(),
            "benchmark_return": (
                float(self.benchmark_return)
                if self.benchmark_return is not None
                else None
            ),
            "excess_return": (
                float(self.excess_return) if self.excess_return is not None else None
            ),
            "passed_benchmark": self.passed_benchmark,
            "validation_status": self.validation_status,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class RollingValidationFoldEvidence:
    """One rolling out-of-sample fold from a completed deterministic run."""

    fold_index: int
    split_timestamp: datetime
    train_segment: ValidationSegmentEvidence
    out_of_sample: ValidationSegmentEvidence
    benchmark_return: Decimal | None
    excess_return: Decimal | None
    passed_benchmark: bool | None

    def to_json_dict(self) -> dict:
        return {
            "fold_index": self.fold_index,
            "split_timestamp": self.split_timestamp.isoformat(),
            "train_segment": self.train_segment.to_json_dict(),
            "out_of_sample": self.out_of_sample.to_json_dict(),
            "benchmark_return": (
                float(self.benchmark_return)
                if self.benchmark_return is not None
                else None
            ),
            "excess_return": (
                float(self.excess_return) if self.excess_return is not None else None
            ),
            "passed_benchmark": self.passed_benchmark,
        }


@dataclass(frozen=True)
class RollingOutOfSampleValidationEvidence:
    """Audit-friendly rolling OOS evidence across multiple validation folds."""

    strategy_id: str
    benchmark_role: str
    validation_mode: str
    min_train_points: int
    test_window_points: int
    step_points: int
    equity_point_count: int
    folds: list[RollingValidationFoldEvidence]
    mean_out_of_sample_return: Decimal
    worst_out_of_sample_return: Decimal
    pass_rate: Decimal | None
    total_oos_cost: Decimal
    validation_status: str
    assumptions: list[str]
    limitations: list[str]

    @property
    def fold_count(self) -> int:
        return len(self.folds)

    def to_json_dict(self) -> dict:
        aggregate = {
            "mean_out_of_sample_return": float(self.mean_out_of_sample_return),
            "worst_out_of_sample_return": float(self.worst_out_of_sample_return),
            "pass_rate": float(self.pass_rate) if self.pass_rate is not None else None,
            "total_oos_cost": float(self.total_oos_cost),
        }
        core = {
            "schema_version": ROLLING_OOS_EVIDENCE_SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "benchmark_role": self.benchmark_role,
            "validation_mode": self.validation_mode,
            "min_train_points": self.min_train_points,
            "test_window_points": self.test_window_points,
            "step_points": self.step_points,
            "equity_point_count": self.equity_point_count,
            "fold_count": self.fold_count,
            "folds": [fold.to_json_dict() for fold in self.folds],
            "aggregate": aggregate,
            "validation_status": self.validation_status,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "persisted_backtest_result_only": True,
            "human_review_required": True,
            "authorizes_execution": False,
            "does_not_change_capital_authority": True,
        }
        return {**core, "evidence_fingerprint": _fingerprint(core)}


def is_valid_rolling_out_of_sample_validation_evidence(
    value: Any,
    *,
    minimum_fold_count: int = 2,
) -> bool:
    """Validate and replay fold arithmetic for persisted rolling OOS evidence."""

    if not isinstance(value, Mapping) or minimum_fold_count < 1:
        return False
    payload = dict(value)
    fingerprint = str(payload.pop("evidence_fingerprint", ""))
    expected_keys = {
        "schema_version",
        "strategy_id",
        "benchmark_role",
        "validation_mode",
        "min_train_points",
        "test_window_points",
        "step_points",
        "equity_point_count",
        "fold_count",
        "folds",
        "aggregate",
        "validation_status",
        "assumptions",
        "limitations",
        "persisted_backtest_result_only",
        "human_review_required",
        "authorizes_execution",
        "does_not_change_capital_authority",
    }
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != ROLLING_OOS_EVIDENCE_SCHEMA_VERSION
        or payload.get("validation_mode") != "rolling"
        or not str(payload.get("strategy_id") or "").strip()
        or not str(payload.get("benchmark_role") or "").strip()
        or not _positive_integer(payload.get("min_train_points"))
        or not _positive_integer(payload.get("test_window_points"))
        or not _positive_integer(payload.get("step_points"))
        or not _positive_integer(payload.get("equity_point_count"))
        or payload.get("persisted_backtest_result_only") is not True
        or payload.get("human_review_required") is not True
        or payload.get("authorizes_execution") is not False
        or payload.get("does_not_change_capital_authority") is not True
        or not _nonempty_string_list(payload.get("assumptions"))
        or not _nonempty_string_list(payload.get("limitations"))
        or len(fingerprint) != 64
        or fingerprint != _fingerprint(payload)
    ):
        return False

    raw_folds = payload.get("folds")
    fold_count = _integer(payload.get("fold_count"))
    min_train_points = _integer(payload.get("min_train_points"))
    test_window_points = _integer(payload.get("test_window_points"))
    step_points = _integer(payload.get("step_points"))
    equity_point_count = _integer(payload.get("equity_point_count"))
    expected_fold_count = (
        ((equity_point_count - test_window_points - min_train_points) // step_points)
        + 1
        if min_train_points is not None
        and test_window_points is not None
        and step_points is not None
        and equity_point_count is not None
        and equity_point_count >= min_train_points + test_window_points
        else 0
    )
    if (
        not isinstance(raw_folds, list)
        or fold_count is None
        or fold_count < minimum_fold_count
        or fold_count != expected_fold_count
        or len(raw_folds) != fold_count
    ):
        return False

    oos_returns: list[Decimal] = []
    oos_costs: list[Decimal] = []
    benchmark_returns: list[Decimal | None] = []
    passed_benchmarks: list[bool | None] = []
    split_timestamps: list[datetime] = []
    train_start_timestamp: datetime | None = None
    train_initial_equity: Decimal | None = None
    prior_train_end: datetime | None = None
    prior_oos_end: datetime | None = None
    for expected_index, raw_fold in enumerate(raw_folds, start=1):
        if not isinstance(raw_fold, Mapping) or set(raw_fold) != {
            "fold_index",
            "split_timestamp",
            "train_segment",
            "out_of_sample",
            "benchmark_return",
            "excess_return",
            "passed_benchmark",
        }:
            return False
        if _integer(raw_fold.get("fold_index")) != expected_index:
            return False
        split_timestamp = _timestamp(raw_fold.get("split_timestamp"))
        train = _validated_segment(raw_fold.get("train_segment"))
        out_of_sample = _validated_segment(raw_fold.get("out_of_sample"))
        if split_timestamp is None or train is None or out_of_sample is None:
            return False
        if (
            train["end_timestamp"] >= out_of_sample["start_timestamp"]
            or split_timestamp != out_of_sample["start_timestamp"]
            or not _close_decimal(
                train["final_equity"], out_of_sample["initial_equity"]
            )
        ):
            return False
        if train_start_timestamp is None:
            train_start_timestamp = train["start_timestamp"]
            train_initial_equity = train["initial_equity"]
        elif (
            train["start_timestamp"] != train_start_timestamp
            or train_initial_equity is None
            or not _close_decimal(train["initial_equity"], train_initial_equity)
            or prior_train_end is None
            or train["end_timestamp"] <= prior_train_end
            or prior_oos_end is None
            or out_of_sample["end_timestamp"] <= prior_oos_end
        ):
            return False
        prior_train_end = train["end_timestamp"]
        prior_oos_end = out_of_sample["end_timestamp"]
        split_timestamps.append(split_timestamp)

        raw_benchmark_return = raw_fold.get("benchmark_return")
        raw_excess_return = raw_fold.get("excess_return")
        benchmark_return = _optional_decimal(raw_benchmark_return)
        excess_return = _optional_decimal(raw_excess_return)
        passed_benchmark = raw_fold.get("passed_benchmark")
        if (
            raw_benchmark_return is not None
            and benchmark_return is None
            or raw_excess_return is not None
            and excess_return is None
        ):
            return False
        if benchmark_return is None:
            if excess_return is not None or passed_benchmark is not None:
                return False
        else:
            expected_excess = out_of_sample["net_return"] - benchmark_return
            expected_passed = out_of_sample["net_return"] > benchmark_return
            if (
                excess_return is None
                or not _close_decimal(excess_return, expected_excess)
                or passed_benchmark is not expected_passed
            ):
                return False
        oos_returns.append(out_of_sample["net_return"])
        oos_costs.append(out_of_sample["total_cost"])
        benchmark_returns.append(benchmark_return)
        passed_benchmarks.append(passed_benchmark)

    if any(
        right <= left for left, right in zip(split_timestamps, split_timestamps[1:])
    ):
        return False
    benchmark_modes = {item is None for item in passed_benchmarks}
    if len(benchmark_modes) != 1:
        return False
    if benchmark_returns[0] is not None and any(
        item is None or not _close_decimal(item, benchmark_returns[0])
        for item in benchmark_returns[1:]
    ):
        return False

    aggregate = payload.get("aggregate")
    if not isinstance(aggregate, Mapping) or set(aggregate) != {
        "mean_out_of_sample_return",
        "worst_out_of_sample_return",
        "pass_rate",
        "total_oos_cost",
    }:
        return False
    mean_return = _decimal(aggregate.get("mean_out_of_sample_return"))
    worst_return = _decimal(aggregate.get("worst_out_of_sample_return"))
    total_cost = _decimal(aggregate.get("total_oos_cost"))
    raw_pass_rate = aggregate.get("pass_rate")
    pass_rate = _optional_decimal(raw_pass_rate)
    if raw_pass_rate is not None and pass_rate is None:
        return False
    expected_mean = sum(oos_returns, Decimal("0")) / Decimal(len(oos_returns))
    expected_worst = min(oos_returns)
    expected_cost = sum(oos_costs, Decimal("0"))
    if (
        mean_return is None
        or worst_return is None
        or total_cost is None
        or not _close_decimal(mean_return, expected_mean)
        or not _close_decimal(worst_return, expected_worst)
        or not _close_decimal(total_cost, expected_cost)
    ):
        return False
    expected_pass_rate = (
        None
        if passed_benchmarks[0] is None
        else Decimal(sum(item is True for item in passed_benchmarks))
        / Decimal(len(passed_benchmarks))
    )
    if expected_pass_rate is None:
        if pass_rate is not None:
            return False
    elif pass_rate is None or not _close_decimal(pass_rate, expected_pass_rate):
        return False
    return payload.get("validation_status") == _rolling_validation_status(
        expected_pass_rate
    )


def build_out_of_sample_validation(
    *,
    strategy_id: str,
    benchmark_role: str,
    result: BacktestResult,
    split_timestamp: datetime,
    benchmark_return: Decimal | None = None,
    assumptions: list[str] | None = None,
    limitations: list[str] | None = None,
) -> OutOfSampleValidationEvidence:
    """Split a completed backtest into in-sample and out-of-sample evidence."""
    if len(result.equity_curve) < 2:
        raise ValueError("out-of-sample validation requires at least two equity points")

    before_split = [
        (ts, equity) for ts, equity in result.equity_curve if ts < split_timestamp
    ]
    after_split = [
        (ts, equity) for ts, equity in result.equity_curve if ts >= split_timestamp
    ]
    if not before_split or not after_split:
        raise ValueError(
            "out-of-sample validation requires at least one in-sample and one out-of-sample equity point"
        )

    boundary_timestamp, boundary_equity = before_split[-1]
    in_sample = _build_segment_evidence(
        start_timestamp=result.equity_curve[0][0],
        end_timestamp=boundary_timestamp,
        initial_equity=result.equity_curve[0][1],
        final_equity=boundary_equity,
        fills=[fill for fill in result.fills if fill.timestamp < split_timestamp],
    )
    out_of_sample = _build_segment_evidence(
        start_timestamp=after_split[0][0],
        end_timestamp=result.equity_curve[-1][0],
        initial_equity=boundary_equity,
        final_equity=result.equity_curve[-1][1],
        fills=[fill for fill in result.fills if fill.timestamp >= split_timestamp],
    )
    excess_return = (
        out_of_sample.net_return - benchmark_return
        if benchmark_return is not None
        else None
    )
    passed_benchmark = (
        out_of_sample.net_return > benchmark_return
        if benchmark_return is not None
        else None
    )
    validation_status = (
        "benchmark_passed"
        if passed_benchmark is True
        else (
            "benchmark_failed"
            if passed_benchmark is False
            else "benchmark_not_supplied"
        )
    )

    return OutOfSampleValidationEvidence(
        strategy_id=strategy_id,
        benchmark_role=benchmark_role,
        split_timestamp=split_timestamp,
        in_sample=in_sample,
        out_of_sample=out_of_sample,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        passed_benchmark=passed_benchmark,
        validation_status=validation_status,
        assumptions=assumptions
        or [
            "Out-of-sample validation is computed from a completed deterministic backtest result.",
            "Segment gross values are reconstructed by adding recorded commissions and slippage back to net PnL.",
        ],
        limitations=limitations
        or [
            "Validation evidence is not investment advice or a profitability guarantee.",
            "Benchmark and liquidity assumptions must be reviewed before strategy promotion.",
        ],
    )


def build_rolling_out_of_sample_validation(
    *,
    strategy_id: str,
    benchmark_role: str,
    result: BacktestResult,
    min_train_points: int,
    test_window_points: int,
    step_points: int = 1,
    benchmark_return: Decimal | None = None,
    assumptions: list[str] | None = None,
    limitations: list[str] | None = None,
) -> RollingOutOfSampleValidationEvidence:
    """Build rolling OOS folds from a completed deterministic backtest result."""
    equity_curve = list(result.equity_curve)
    if min_train_points < 1:
        raise ValueError("rolling OOS validation requires min_train_points >= 1")
    if test_window_points < 1:
        raise ValueError("rolling OOS validation requires test_window_points >= 1")
    if step_points < 1:
        raise ValueError("rolling OOS validation requires step_points >= 1")
    required_points = min_train_points + test_window_points
    if len(equity_curve) < required_points:
        raise ValueError(
            "rolling OOS validation requires enough equity points for at least one fold"
        )

    folds: list[RollingValidationFoldEvidence] = []
    last_start_index = len(equity_curve) - test_window_points
    for split_index in range(min_train_points, last_start_index + 1, step_points):
        train_points = equity_curve[:split_index]
        test_points = equity_curve[split_index : split_index + test_window_points]
        train_start_timestamp, train_start_equity = train_points[0]
        train_end_timestamp, train_end_equity = train_points[-1]
        test_start_timestamp = test_points[0][0]
        test_end_timestamp, test_end_equity = test_points[-1]
        train_segment = _build_segment_evidence(
            start_timestamp=train_start_timestamp,
            end_timestamp=train_end_timestamp,
            initial_equity=train_start_equity,
            final_equity=train_end_equity,
            fills=[
                fill
                for fill in result.fills
                if train_start_timestamp <= fill.timestamp <= train_end_timestamp
            ],
        )
        out_of_sample = _build_segment_evidence(
            start_timestamp=test_start_timestamp,
            end_timestamp=test_end_timestamp,
            initial_equity=train_end_equity,
            final_equity=test_end_equity,
            fills=[
                fill
                for fill in result.fills
                if test_start_timestamp <= fill.timestamp <= test_end_timestamp
            ],
        )
        excess_return = (
            out_of_sample.net_return - benchmark_return
            if benchmark_return is not None
            else None
        )
        passed_benchmark = (
            out_of_sample.net_return > benchmark_return
            if benchmark_return is not None
            else None
        )
        folds.append(
            RollingValidationFoldEvidence(
                fold_index=len(folds) + 1,
                split_timestamp=test_start_timestamp,
                train_segment=train_segment,
                out_of_sample=out_of_sample,
                benchmark_return=benchmark_return,
                excess_return=excess_return,
                passed_benchmark=passed_benchmark,
            )
        )

    oos_returns = [fold.out_of_sample.net_return for fold in folds]
    passed = [fold.passed_benchmark for fold in folds]
    pass_count = sum(1 for item in passed if item is True)
    pass_rate = (
        Decimal(pass_count) / Decimal(len(folds))
        if benchmark_return is not None
        else None
    )
    validation_status = _rolling_validation_status(pass_rate)
    return RollingOutOfSampleValidationEvidence(
        strategy_id=strategy_id,
        benchmark_role=benchmark_role,
        validation_mode="rolling",
        min_train_points=min_train_points,
        test_window_points=test_window_points,
        step_points=step_points,
        equity_point_count=len(equity_curve),
        folds=folds,
        mean_out_of_sample_return=sum(oos_returns, Decimal("0"))
        / Decimal(len(oos_returns)),
        worst_out_of_sample_return=min(oos_returns),
        pass_rate=pass_rate,
        total_oos_cost=sum(
            (fold.out_of_sample.total_cost for fold in folds), Decimal("0")
        ),
        validation_status=validation_status,
        assumptions=assumptions
        or [
            "Rolling OOS validation is computed from a completed deterministic backtest result.",
            "Each fold advances over the same frozen equity curve and cost evidence.",
        ],
        limitations=limitations
        or [
            "Validation evidence is not investment advice or a profitability guarantee.",
            "Rolling OOS evidence does not refit parameters per fold; use it as robustness evidence before promotion review.",
        ],
    )


def _build_segment_evidence(
    *,
    start_timestamp: datetime,
    end_timestamp: datetime,
    initial_equity: Decimal,
    final_equity: Decimal,
    fills: list[FillEvent],
) -> ValidationSegmentEvidence:
    total_cost = sum((fill.commission + fill.slippage for fill in fills), Decimal("0"))
    net_pnl = final_equity - initial_equity
    gross_pnl_before_costs = net_pnl + total_cost
    if initial_equity == Decimal("0"):
        net_return = Decimal("0")
        gross_return_before_costs = Decimal("0")
    else:
        net_return = net_pnl / initial_equity
        gross_return_before_costs = gross_pnl_before_costs / initial_equity

    return ValidationSegmentEvidence(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        initial_equity=initial_equity,
        final_equity=final_equity,
        net_pnl=net_pnl,
        net_return=net_return,
        total_cost=total_cost,
        gross_pnl_before_costs=gross_pnl_before_costs,
        gross_return_before_costs=gross_return_before_costs,
        fill_count=len(fills),
    )


def _rolling_validation_status(pass_rate: Decimal | None) -> str:
    if pass_rate is None:
        return "benchmark_not_supplied"
    return "benchmark_passed" if pass_rate >= Decimal("0.5") else "benchmark_failed"


def _validated_segment(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != {
        "start_timestamp",
        "end_timestamp",
        "initial_equity",
        "final_equity",
        "net_pnl",
        "net_return",
        "total_cost",
        "gross_pnl_before_costs",
        "gross_return_before_costs",
        "fill_count",
    }:
        return None
    start_timestamp = _timestamp(value.get("start_timestamp"))
    end_timestamp = _timestamp(value.get("end_timestamp"))
    initial_equity = _decimal(value.get("initial_equity"))
    final_equity = _decimal(value.get("final_equity"))
    net_pnl = _decimal(value.get("net_pnl"))
    net_return = _decimal(value.get("net_return"))
    total_cost = _decimal(value.get("total_cost"))
    gross_pnl = _decimal(value.get("gross_pnl_before_costs"))
    gross_return = _decimal(value.get("gross_return_before_costs"))
    fill_count = _integer(value.get("fill_count"))
    if (
        start_timestamp is None
        or end_timestamp is None
        or start_timestamp > end_timestamp
        or initial_equity is None
        or initial_equity <= 0
        or final_equity is None
        or final_equity < 0
        or net_pnl is None
        or net_return is None
        or total_cost is None
        or total_cost < 0
        or gross_pnl is None
        or gross_return is None
        or fill_count is None
        or fill_count < 0
    ):
        return None
    if not all(
        (
            _close_decimal(left, right)
            for left, right in (
                (final_equity - initial_equity, net_pnl),
                (net_pnl / initial_equity, net_return),
                (net_pnl + total_cost, gross_pnl),
                (gross_pnl / initial_equity, gross_return),
            )
        )
    ):
        return None
    return {
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "net_pnl": net_pnl,
        "net_return": net_return,
        "total_cost": total_cost,
        "gross_pnl_before_costs": gross_pnl,
        "gross_return_before_costs": gross_return,
        "fill_count": fill_count,
    }


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return normalized if normalized.isoformat() == value else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _positive_integer(value: Any) -> bool:
    normalized = _integer(value)
    return normalized is not None and normalized > 0


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
