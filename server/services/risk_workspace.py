from __future__ import annotations

from dataclasses import dataclass

from server.models import (
    EquityPoint,
    PortfolioSnapshot,
    RiskConcentrationItem,
    RiskDrawdownPoint,
    RiskDrawdownSummary,
    RiskExposureBucket,
    RiskMetricItem,
    RiskWorkspaceResponse,
)


@dataclass
class _BucketState:
    label: str
    value: float = 0.0
    positions_count: int = 0
    symbols: list[str] | None = None

    def __post_init__(self) -> None:
        if self.symbols is None:
            self.symbols = []


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_currency(value: float) -> str:
    return f"¥{value:,.2f}"


def _build_drawdown_summary(
    equity_curve: list[EquityPoint],
) -> tuple[RiskDrawdownSummary, list[RiskDrawdownPoint]]:
    if not equity_curve:
        empty = RiskDrawdownSummary(
            current_drawdown=0.0,
            max_drawdown=0.0,
            latest_equity=0.0,
            peak_equity=0.0,
        )
        return empty, []

    peak_equity = 0.0
    peak_timestamp: str | None = None
    max_drawdown = 0.0
    trough_timestamp: str | None = None
    series: list[RiskDrawdownPoint] = []

    for point in equity_curve:
        if point.equity >= peak_equity:
            peak_equity = point.equity
            peak_timestamp = point.timestamp

        drawdown = 0.0 if peak_equity <= 0 else (peak_equity - point.equity) / peak_equity
        if drawdown >= max_drawdown:
            max_drawdown = drawdown
            trough_timestamp = point.timestamp

        series.append(
            RiskDrawdownPoint(
                timestamp=point.timestamp,
                equity=point.equity,
                peak_equity=peak_equity,
                drawdown=drawdown,
            )
        )

    latest_equity = equity_curve[-1].equity
    current_drawdown = 0.0 if peak_equity <= 0 else (peak_equity - latest_equity) / peak_equity
    return (
        RiskDrawdownSummary(
            current_drawdown=current_drawdown,
            max_drawdown=max_drawdown,
            latest_equity=latest_equity,
            peak_equity=peak_equity,
            peak_timestamp=peak_timestamp,
            trough_timestamp=trough_timestamp,
        ),
        series,
    )


def build_risk_workspace(
    snapshot: PortfolioSnapshot,
    equity_curve: list[EquityPoint],
) -> RiskWorkspaceResponse:
    drawdown_summary, drawdown_series = _build_drawdown_summary(equity_curve)

    total_equity = snapshot.total_equity or 0.0
    gross_exposure = 0.0 if total_equity <= 0 else (total_equity - snapshot.cash) / total_equity
    cash_ratio = 0.0 if total_equity <= 0 else snapshot.cash / total_equity
    largest_weight = max(
        (item.weight for item in snapshot.allocation if item.asset_class != "cash"),
        default=0.0,
    )
    top3_weight = sum(
        sorted(
            (item.weight for item in snapshot.allocation if item.asset_class != "cash"),
            reverse=True,
        )[:3]
    )

    metrics = [
        RiskMetricItem(
            key="current_drawdown",
            label="Current drawdown",
            value=drawdown_summary.current_drawdown,
            display_value=_format_percent(drawdown_summary.current_drawdown),
            level="high" if drawdown_summary.current_drawdown >= 0.1 else "low",
            detail="Distance between current equity and the latest portfolio peak.",
        ),
        RiskMetricItem(
            key="max_drawdown",
            label="Max drawdown",
            value=drawdown_summary.max_drawdown,
            display_value=_format_percent(drawdown_summary.max_drawdown),
            level="high" if drawdown_summary.max_drawdown >= 0.15 else "medium",
            detail="Largest observed peak-to-trough loss across the equity curve.",
        ),
        RiskMetricItem(
            key="gross_exposure",
            label="Gross exposure",
            value=gross_exposure,
            display_value=_format_percent(gross_exposure),
            level="high" if gross_exposure >= 0.85 else "low",
            detail="Capital currently deployed in non-cash positions.",
        ),
        RiskMetricItem(
            key="cash_ratio",
            label="Cash ratio",
            value=cash_ratio,
            display_value=_format_percent(cash_ratio),
            level="medium" if cash_ratio <= 0.15 else "low",
            detail="Immediate liquidity buffer for rebalance or defense.",
        ),
        RiskMetricItem(
            key="largest_weight",
            label="Largest position",
            value=largest_weight,
            display_value=_format_percent(largest_weight),
            level="high" if largest_weight >= 0.2 else "low",
            detail="Single-name concentration of the biggest live holding.",
        ),
        RiskMetricItem(
            key="top3_weight",
            label="Top 3 concentration",
            value=top3_weight,
            display_value=_format_percent(top3_weight),
            level="high" if top3_weight >= 0.55 else "medium",
            detail="Aggregate concentration across the three largest holdings.",
        ),
    ]

    bucket_map = {
        "heavy": _BucketState("Heavy conviction"),
        "core": _BucketState("Core"),
        "starter": _BucketState("Starter"),
        "small": _BucketState("Small / tracking"),
    }

    concentration: list[RiskConcentrationItem] = []
    for position in snapshot.positions:
        allocation_item = next(
            (item for item in snapshot.allocation if item.symbol == position.symbol),
            None,
        )
        weight = allocation_item.weight if allocation_item else 0.0
        asset_class = allocation_item.asset_class if allocation_item else "stock"
        concentration.append(
            RiskConcentrationItem(
                symbol=position.symbol,
                asset_class=asset_class,
                market_value=position.market_value,
                weight=weight,
                unrealized_pnl=position.unrealized_pnl,
                avg_cost=position.avg_cost,
                quantity=position.quantity,
            )
        )

        if weight >= 0.2:
            bucket = bucket_map["heavy"]
        elif weight >= 0.1:
            bucket = bucket_map["core"]
        elif weight >= 0.05:
            bucket = bucket_map["starter"]
        else:
            bucket = bucket_map["small"]

        bucket.value += position.market_value
        bucket.positions_count += 1
        bucket.symbols.append(position.symbol)

    concentration.sort(key=lambda item: item.weight, reverse=True)

    exposure_buckets = [
        RiskExposureBucket(
            bucket=key,
            label=value.label,
            value=value.value,
            weight=0.0 if total_equity <= 0 else value.value / total_equity,
            positions_count=value.positions_count,
            symbols=value.symbols or [],
        )
        for key, value in bucket_map.items()
        if value.positions_count > 0
    ]

    if not exposure_buckets:
        exposure_buckets.append(
            RiskExposureBucket(
                bucket="cash",
                label="Cash reserve",
                value=snapshot.cash,
                weight=cash_ratio,
                positions_count=0,
                symbols=[],
            )
        )

    return RiskWorkspaceResponse(
        metrics=metrics,
        drawdown=drawdown_summary,
        drawdown_series=drawdown_series,
        exposure_buckets=exposure_buckets,
        concentration=concentration[:8],
    )
