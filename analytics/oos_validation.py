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
