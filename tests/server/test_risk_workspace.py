"""Risk ratios distinguish measured exposure from inapplicable empty equity."""

import pytest

from server.models import AllocationItem, EquityPoint, PortfolioSnapshot
from server.services.risk.risk_workspace import build_risk_workspace


def _snapshot(*, total_equity=1000.0, weights=()):
    return PortfolioSnapshot(
        cash=total_equity * (1 - sum(weights)),
        total_equity=total_equity,
        positions=[],
        allocation=[
            AllocationItem(
                symbol=f"SAMPLE-{index}",
                name=f"Sample {index}",
                weight=weight,
                value=total_equity * weight,
                asset_class="stock",
            )
            for index, weight in enumerate(weights)
        ],
        valuation_status="complete",
    )


@pytest.mark.parametrize(
    ("weights", "expected_level"),
    [((), "low"), ((0.1, 0.1, 0.1), "low"), ((0.2, 0.2, 0.15), "high")],
)
def test_top_three_concentration_respects_its_risk_boundary(weights, expected_level):
    result = build_risk_workspace(_snapshot(weights=weights), [])
    metric = next(item for item in result.metrics if item.key == "top3_weight")
    assert metric.value == pytest.approx(sum(weights))
    assert metric.level == expected_level


@pytest.mark.parametrize("total_equity", [0.0, -100.0])
def test_ratios_without_positive_equity_are_not_zero_or_warnings(total_equity):
    result = build_risk_workspace(_snapshot(total_equity=total_equity), [])
    assert {item.key for item in result.metrics} == {
        "gross_exposure",
        "cash_ratio",
        "largest_weight",
        "top3_weight",
    }
    for metric in result.metrics:
        assert metric.value is None
        assert metric.display_value == "--"
        assert metric.level == "not_applicable"
    assert result.exposure_buckets == []
    assert result.drawdown is None
    assert result.blockers == ["drawdown_history_unavailable"]
    assert all(item["value"] is None for item in result.model_dump()["metrics"])


@pytest.mark.parametrize(
    ("latest", "expected_level"), [(100.0, "low"), (90.0, "low"), (85.0, "high")]
)
def test_max_drawdown_zero_and_below_threshold_do_not_warn(latest, expected_level):
    result = build_risk_workspace(
        _snapshot(),
        [
            EquityPoint(timestamp="2026-10-14T15:00:00+08:00", equity=100.0),
            EquityPoint(timestamp="2026-10-15T15:00:00+08:00", equity=latest),
        ],
    )
    metric = next(item for item in result.metrics if item.key == "max_drawdown")
    assert metric.level == expected_level
    assert metric.value == pytest.approx((100.0 - latest) / 100.0)
