from decimal import Decimal, Inexact, localcontext

import pytest

from domain.research_targets import build_research_target_weights


def test_allocation_caps_each_symbol_before_proportional_gross_limit() -> None:
    desired = {"600002": Decimal("0.2"), "600001": Decimal("0.9")}

    result = build_research_target_weights(
        desired, max_symbol_weight=Decimal("0.6"), max_gross_weight=Decimal("0.4")
    )

    assert result == {"600001": Decimal("0.3"), "600002": Decimal("0.1")}
    assert desired == {"600002": Decimal("0.2"), "600001": Decimal("0.9")}


def test_rounding_never_exceeds_limits_and_ignores_callers_decimal_context() -> None:
    desired = {symbol: Decimal("1") for symbol in ("600001", "600002", "600003")}
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        result = build_research_target_weights(
            desired, max_symbol_weight=Decimal("0.5"), max_gross_weight=Decimal("1")
        )

    assert set(result.values()) == {Decimal("0.33333333")}
    assert sum(result.values()) == Decimal("0.99999999")


@pytest.mark.parametrize("limit_name", ["max_symbol_weight", "max_gross_weight"])
def test_zero_exposure_limit_preserves_every_symbol(limit_name: str) -> None:
    limits = {"max_symbol_weight": Decimal("1"), "max_gross_weight": Decimal("1")}
    limits[limit_name] = Decimal("0")

    assert build_research_target_weights(
        {"600001": Decimal("0.5"), "600002": Decimal("0")}, **limits
    ) == {"600001": Decimal("0"), "600002": Decimal("0")}


@pytest.mark.parametrize(
    "limit", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal("1.01"), 0.5]
)
def test_invalid_limit_cannot_silently_become_an_allocation(limit) -> None:
    with pytest.raises(ValueError, match="research_target_max_symbol_weight_invalid"):
        build_research_target_weights(
            {"600001": Decimal("1")},
            max_symbol_weight=limit,
            max_gross_weight=Decimal("1"),
        )


@pytest.mark.parametrize(
    ("desired", "error"),
    [
        ({}, "research_target_universe_empty"),
        ({" 600001": Decimal("1")}, "research_target_symbol_invalid"),
        ({"600001": Decimal("NaN")}, "research_target_weight_invalid"),
        ({"600001": Decimal("-0.1")}, "research_target_weight_invalid"),
        ({"600001": 0.1}, "research_target_weight_invalid"),
    ],
)
def test_invalid_forecast_weights_are_not_repaired_silently(desired, error) -> None:
    with pytest.raises(ValueError, match=error):
        build_research_target_weights(
            desired, max_symbol_weight=Decimal("1"), max_gross_weight=Decimal("1")
        )
