from __future__ import annotations

from types import SimpleNamespace

from server.services.portfolio_allocation import allocate_action_tasks


def test_portfolio_allocation_caps_targets_uses_deltas_and_shares_cash() -> None:
    actions = [
        _action(3, "600001", "buy", 1.0, "stock"),
        _action(2, "600002", "buy", 1.0, "stock"),
        _action(1, "FUND01", "sell", 0.0, "fund"),
    ]
    portfolio = SimpleNamespace(
        cash=7000.0,
        total_equity=20000.0,
        positions={
            "600001": SimpleNamespace(
                quantity=100.0,
                available_qty=100.0,
                market_value=3000.0,
            ),
            "600002": SimpleNamespace(
                quantity=100.0,
                available_qty=100.0,
                market_value=1000.0,
            ),
            "FUND01": SimpleNamespace(
                quantity=500.0,
                available_qty=500.0,
                market_value=1000.0,
            ),
        },
    )
    quotes = {
        "600001": {"price": 30.0},
        "600002": {"price": 10.0},
        "FUND01": {"price": 2.0},
    }

    allocated = allocate_action_tasks(
        actions,
        portfolio=portfolio,
        quotes=quotes,
        config=SimpleNamespace(
            min_cash_buffer_ratio=0.03,
            max_single_symbol_weight=0.35,
        ),
    )

    first, second, sell = allocated
    assert first["raw_target_weight"] == 1.0
    assert first["target_weight"] == 0.3
    assert first["allocation_quantity"] == 100.0
    assert first["allocation_status"] == "allocated_concentration_capped"
    assert second["raw_target_weight"] == 1.0
    assert second["target_weight"] == 0.2
    assert second["allocation_quantity"] == 300.0
    assert second["allocation_status"] == "allocated_cash_bounded"
    assert sell["target_weight"] == 0.0
    assert sell["allocation_quantity"] == 500.0
    assert (
        sell["allocation_evidence"]["sell_proceeds_netted_into_buy_capacity"] is False
    )
    assert (
        sum(
            item["allocation_quantity"] * item["allocation_price"]
            for item in allocated
            if item["direction"] == "buy"
        )
        == 6000.0
    )
    assert allocated == allocate_action_tasks(
        actions,
        portfolio=portfolio,
        quotes=quotes,
        config=SimpleNamespace(
            min_cash_buffer_ratio=0.03,
            max_single_symbol_weight=0.35,
        ),
    )


def test_portfolio_allocation_does_not_rebuy_existing_target_quantity() -> None:
    allocated = allocate_action_tasks(
        [_action(1, "600001", "buy", 0.2, "stock")],
        portfolio=SimpleNamespace(
            cash=30000.0,
            total_equity=50000.0,
            positions={
                "600001": SimpleNamespace(
                    quantity=200.0,
                    available_qty=200.0,
                    market_value=2000.0,
                )
            },
        ),
        quotes={"600001": {"price": 10.0}},
    )[0]

    assert allocated["allocation_quantity"] == 800.0
    assert allocated["target_weight"] == 0.2


def _action(
    action_id: int,
    symbol: str,
    direction: str,
    target_weight: float,
    asset_class: str,
) -> dict[str, object]:
    return {
        "id": action_id,
        "symbol": symbol,
        "direction": direction,
        "target_weight": target_weight,
        "asset_class": asset_class,
        "strategy_id": "dual_ma",
    }
