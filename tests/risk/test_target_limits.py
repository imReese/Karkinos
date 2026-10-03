from decimal import Decimal, Inexact, localcontext

import pytest

from domain.research_targets import build_research_target_weights
from risk.target_limits import evaluate_target_limits


def test_risk_accepts_bounded_allocation_without_execution_authority() -> None:
    limits = {"max_symbol_weight": Decimal("0.6"), "max_gross_weight": Decimal("0.7")}
    targets = build_research_target_weights(
        {"600001": Decimal("1"), "600002": Decimal("0.3")}, **limits
    )
    before = dict(targets)

    result = evaluate_target_limits(
        targets, frozen_universe=["600001", "600002"], **limits
    )

    assert result["status"] == "allowed"
    assert result["reasons"] == []
    assert result["gross_weight"] == "0.69999999"
    assert result["authorizes_execution"] is False
    assert targets == before


def test_risk_reports_exact_over_limit_gross_without_clipping_targets() -> None:
    targets = {"600001": Decimal("0.600000001"), "600002": Decimal("0.4")}
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        result = evaluate_target_limits(
            targets,
            frozen_universe=["600001", "600002"],
            max_symbol_weight=Decimal("0.6"),
            max_gross_weight=Decimal("1"),
        )

    assert result["status"] == "blocked"
    assert result["reasons"] == [
        "target_symbol_limit_exceeded",
        "target_gross_limit_exceeded",
    ]
    assert result["gross_weight"] == "1.000000001"
    assert targets["600001"] == Decimal("0.600000001")


@pytest.mark.parametrize(
    "universe", [[], ["600001", "600001"], [""], [" 600001"], "600001"]
)
def test_invalid_frozen_universe_blocks_risk(universe) -> None:
    result = evaluate_target_limits(
        {"600001": Decimal("0")},
        frozen_universe=universe,
        max_symbol_weight=Decimal("1"),
        max_gross_weight=Decimal("1"),
    )

    assert result["status"] == "blocked"
    assert "target_frozen_universe_invalid" in result["reasons"]


def test_missing_zero_weight_symbol_still_changes_frozen_universe() -> None:
    result = evaluate_target_limits(
        {"600001": Decimal("0")},
        frozen_universe=["600001", "600002"],
        max_symbol_weight=Decimal("1"),
        max_gross_weight=Decimal("1"),
    )

    assert result["reasons"] == ["target_universe_mismatch"]


@pytest.mark.parametrize(
    "weight", [Decimal("-0.1"), Decimal("NaN"), Decimal("Infinity"), 0.5]
)
def test_risk_rejects_non_decimal_or_non_finite_or_short_weights(weight) -> None:
    result = evaluate_target_limits(
        {"600001": weight},
        frozen_universe=["600001"],
        max_symbol_weight=Decimal("1"),
        max_gross_weight=Decimal("1"),
    )

    assert result["status"] == "blocked"
    assert result["reasons"] == ["target_weight_invalid"]
    assert result["gross_weight"] is None


def test_invalid_limits_block_even_when_portfolio_is_empty() -> None:
    result = evaluate_target_limits(
        {"600001": Decimal("0")},
        frozen_universe=["600001"],
        max_symbol_weight=Decimal("NaN"),
        max_gross_weight=Decimal("1.01"),
    )

    assert result["reasons"] == [
        "target_max_symbol_weight_invalid",
        "target_max_gross_weight_invalid",
    ]
