"""Out-of-sample validation evidence for backtest results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from backtest.result import BacktestResult
from core.events import FillEvent


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
        return {
            "strategy_id": self.strategy_id,
            "benchmark_role": self.benchmark_role,
            "validation_mode": self.validation_mode,
            "min_train_points": self.min_train_points,
            "test_window_points": self.test_window_points,
            "step_points": self.step_points,
            "fold_count": self.fold_count,
            "folds": [fold.to_json_dict() for fold in self.folds],
            "aggregate": aggregate,
            "validation_status": self.validation_status,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
        }


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
