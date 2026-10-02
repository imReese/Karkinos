"""Integer share awards and preservation of the research book's existing cost."""

from decimal import Decimal

import pytest

from domain.portfolio_accounting import (
    average_cost_after_share_distribution,
    share_distribution_quantity,
)

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]


def test_integer_award_does_not_round_fractional_entitlement() -> None:
    assert share_distribution_quantity(
        eligible_quantity=Decimal("100"), shares_per_share=Decimal("0.3")
    ) == Decimal("30")
    with pytest.raises(ValueError, match="fractional_unsupported"):
        share_distribution_quantity(
            eligible_quantity=Decimal("101"), shares_per_share=Decimal("0.3")
        )


@pytest.mark.parametrize(
    ("quantity", "rate"),
    [
        ("-1", "1"),
        ("NaN", "1"),
        ("Infinity", "1"),
        ("1", "-1"),
        ("1", "sNaN"),
        ("1", "Infinity"),
        ("1", "1E1000000"),
        ("1E-999999", "1E-999999"),
        ("0.5", "2"),
    ],
)
def test_invalid_share_terms_cannot_become_integer_awards(quantity, rate) -> None:
    with pytest.raises(ValueError, match="portfolio_share_distribution_"):
        share_distribution_quantity(
            eligible_quantity=Decimal(quantity), shares_per_share=Decimal(rate)
        )


def test_repeating_average_cost_preserves_existing_total_cost() -> None:
    average = average_cost_after_share_distribution(
        current_quantity=Decimal("2"),
        current_average_cost=Decimal("10.01"),
        distribution_quantity=Decimal("15"),
    )
    assert average * Decimal("17") == Decimal("20.02")


def test_award_to_empty_position_adds_no_invented_cost() -> None:
    assert average_cost_after_share_distribution(
        current_quantity=Decimal("0"),
        current_average_cost=Decimal("0"),
        distribution_quantity=Decimal("30"),
    ) == Decimal("0")


def test_cost_overflow_is_a_public_value_error() -> None:
    with pytest.raises(ValueError, match="portfolio_share_distribution_cost_invalid"):
        average_cost_after_share_distribution(
            current_quantity=Decimal("10"),
            current_average_cost=Decimal("1E999999"),
            distribution_quantity=Decimal("1"),
        )
