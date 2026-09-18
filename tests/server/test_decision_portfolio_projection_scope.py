from __future__ import annotations

from types import SimpleNamespace

from server.services.decision_portfolio_projection import (
    decision_symbols,
    portfolio_state_summary,
)


def _position(quantity: float, market_value: float):
    return SimpleNamespace(
        quantity=quantity,
        market_value=market_value,
        valuation_available=True,
    )


def test_portfolio_state_summary_excludes_closed_zero_quantity_positions():
    portfolio = SimpleNamespace(
        cash=500.0,
        valuation_status="complete",
        positions={
            "600001": _position(100.0, 1000.0),
            "600002": _position(0.0, 0.0),
        },
    )
    context = {
        "portfolio": portfolio,
        "instruments": {
            "600001": SimpleNamespace(instrument_type=SimpleNamespace(value="stock")),
            "600002": SimpleNamespace(instrument_type=SimpleNamespace(value="stock")),
        },
        "valuation_snapshot": None,
        "authority": "legacy_runtime_fallback",
    }

    summary = portfolio_state_summary(
        SimpleNamespace(),
        portfolio_context=context,
    )

    assert summary["position_count"] == 1
    assert summary["symbols"] == ["600001"]
    assert summary["instrument_types"] == {"600001": "stock"}
    assert summary["total_market_value"] == 1000.0
    assert summary["total_equity"] == 1500.0


def test_decision_symbols_include_only_current_holdings_and_current_actions():
    state = SimpleNamespace(
        scheduler=SimpleNamespace(
            watchlist=[
                ("WATCH_ONLY", "stock"),
                ("600001", "stock"),
            ]
        ),
        config=SimpleNamespace(
            assets=[
                {"symbol": "CONFIG_ONLY", "asset_class": "stock"},
            ]
        ),
    )
    context = {
        "portfolio": SimpleNamespace(
            positions={
                "600001": _position(100.0, 1000.0),
                "600002": _position(0.0, 0.0),
            }
        ),
    }

    symbols = decision_symbols(
        state,
        [{"symbol": "ACTION_ONLY"}],
        portfolio_context=context,
    )

    assert symbols == ["ACTION_ONLY", "600001"]
