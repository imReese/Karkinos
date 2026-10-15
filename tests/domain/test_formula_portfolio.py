from decimal import Decimal

from domain.research_targets import allocate_formula_targets


def decide(**changes):
    values = dict(
        entries=["b", "a", "c", "d", "e"],
        exits=[],
        position_values={},
        prices={s: Decimal("10") for s in "abcde"},
        liquidity={s: Decimal(ord(s)) for s in "abcde"},
        lot_sizes={s: Decimal("100") for s in "abcde"},
        cash=Decimal("100000"),
        equity=Decimal("100000"),
        buy_cost=lambda symbol, price, quantity: price * quantity + Decimal("5"),
    )
    return allocate_formula_targets(**(values | changes))


def test_complete_session_ranking_reserves_all_costs_and_is_order_independent():
    first = decide()
    assert first == decide(entries=list(reversed("abcde")))
    assert first["selected_entries"] == ["e", "d", "c", "b"]
    assert sum(first["target_weights"].values()) < Decimal("0.97")


def test_unfilled_exit_keeps_position_slot_and_does_not_finance_entries():
    result = decide(
        position_values={s: Decimal("20000") for s in "abc"},
        exits=["a"],
        cash=Decimal("5000"),
    )
    assert result["exit_symbols"] == ["a"]
    assert result["selected_entries"] == ["e"]
    assert result["target_weights"]["a"] == 0
    assert result["target_weights"]["e"] == Decimal("0.01")


def test_full_book_cannot_add_four_more_positions():
    result = decide(position_values={s: Decimal("20000") for s in "abcd"})
    assert result["selected_entries"] == []
    assert result["rejected_entries"]["e"] == "position_limit"


def test_held_weight_describes_actual_exposure_without_implying_a_cap_trim():
    result = decide(entries=[], position_values={"a": Decimal("29000")})
    assert result["target_weights"] == {"a": Decimal("0.29")}
    assert result["selected_entries"] == result["exit_symbols"] == []


def test_fee_minimum_blocks_a_lot_that_only_appears_affordable():
    result = decide(cash=Decimal("4000"))
    assert result["selected_entries"] == []


def test_unquoted_fee_size_is_reduced_without_treating_missing_quote_as_free():
    result = decide(
        buy_cost=lambda symbol, price, quantity: (
            None
            if quantity * price > Decimal("12000")
            else quantity * price + Decimal("5")
        )
    )
    assert result["selected_entries"] == ["e", "d", "c", "b"]
    assert all(
        weight <= Decimal("0.12") for weight in result["target_weights"].values()
    )
