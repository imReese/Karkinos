from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from server.db import AppDatabase
from server.services.decision.decision_action_application import (
    allocate_decision_actions,
)
from server.services.decision.decision_candidate_market_evidence import (
    bind_candidate_market_evidence,
    candidate_market_evidence,
)
from server.services.portfolio.allocation import allocate_action_tasks


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


@pytest.mark.parametrize("quote_price", [0.0, float("nan"), float("inf")])
def test_persisted_allocation_never_falls_back_to_action_price(quote_price) -> None:
    action = _action(1, "600001", "buy", 0.2, "stock")
    action["price"] = 10.0

    allocated = allocate_action_tasks(
        [action],
        portfolio=SimpleNamespace(
            cash=30000.0,
            total_equity=50000.0,
            positions={},
        ),
        quotes={"600001": {"price": quote_price}},
        require_persisted_quote_price=True,
    )[0]

    assert allocated["allocation_price"] is None
    assert allocated["allocation_quantity"] == 0.0
    assert allocated["allocation_status"] == "missing_price_or_equity"


@pytest.mark.parametrize("action_price", [float("nan"), float("inf")])
def test_allocation_rejects_non_finite_action_price_without_quote(action_price) -> None:
    action = _action(1, "600001", "buy", 0.2, "stock")
    action["price"] = action_price

    allocated = allocate_action_tasks(
        [action],
        portfolio=SimpleNamespace(
            cash=30_000.0,
            total_equity=50_000.0,
            positions={},
        ),
        quotes={},
    )[0]

    assert allocated["allocation_price"] is None
    assert allocated["allocation_quantity"] == 0.0
    assert allocated["allocation_status"] == "missing_price_or_equity"


@pytest.mark.parametrize("persisted_price", [None, 0.0, -1.0, float("inf"), 20.0])
def test_decision_allocation_consumes_bound_persisted_candidate_price(
    tmp_path, persisted_price
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    action = _action(1, "600001", "buy", 0.2, "stock")
    action["price"] = 10.0
    if persisted_price is not None:
        db.upsert_latest_quote_sync(
            symbol="600001",
            asset_type="stock",
            price=persisted_price,
            quote_timestamp="2026-07-02T09:30:00+08:00",
            quote_source="deterministic_fixture",
            quote_status="confirmed",
        )
    evidence = candidate_market_evidence(
        db,
        [action],
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    context = bind_candidate_market_evidence(
        {
            "authority": "persisted_valuation_snapshot",
            "portfolio": SimpleNamespace(
                cash=30_000.0,
                total_equity=50_000.0,
                positions={},
            ),
            # Account quotes must not replace a missing or invalid candidate.
            "quotes": {
                "600001": {
                    "symbol": "600001",
                    "instrument_type": "stock",
                    "price": 5.0,
                }
            },
        },
        evidence,
    )

    allocated = allocate_decision_actions(
        SimpleNamespace(config=None), context, [action]
    )

    assert len(allocated) == 1
    result = allocated[0]
    if persisted_price == 20.0:
        assert result["allocation_price"] == 20.0
        assert result["allocation_quantity"] == 500.0
        assert result["allocation_status"] == "allocated"
    else:
        assert result["allocation_price"] is None
        assert result["allocation_quantity"] == 0.0
        assert result["allocation_status"] == "missing_price_or_equity"
    assert "allocation_quantity" not in action
    assert action["price"] == 10.0
    assert db.get_ledger_entries_sync(limit=10) == []


@pytest.mark.parametrize("candidate_map_present", [False, True])
def test_persisted_decision_allocation_does_not_use_account_quotes_without_candidates(
    candidate_map_present,
) -> None:
    action = _action(1, "600001", "buy", 0.2, "stock")
    action["price"] = 10.0
    context = {
        "authority": "persisted_valuation_snapshot",
        "portfolio": SimpleNamespace(
            cash=30_000.0, total_equity=50_000.0, positions={}
        ),
        "quotes": {"600001": {"price": 5.0}},
    }
    if candidate_map_present:
        context["candidate_quotes"] = {}

    allocated = allocate_decision_actions(
        SimpleNamespace(config=None), context, [action]
    )

    assert allocated[0]["allocation_price"] is None
    assert allocated[0]["allocation_quantity"] == 0.0
    assert allocated[0]["allocation_status"] == "missing_price_or_equity"


@pytest.mark.parametrize("account_price", [None, 5.0])
def test_legacy_decision_allocation_preserves_account_and_action_price_fallback(
    account_price,
) -> None:
    action = _action(1, "600001", "buy", 0.2, "stock")
    action["price"] = 10.0
    context = {
        "authority": "legacy_runtime_fallback",
        "portfolio": SimpleNamespace(
            cash=30_000.0, total_equity=50_000.0, positions={}
        ),
        "candidate_quotes": {},
        "quotes": (
            {"600001": {"price": account_price}} if account_price is not None else {}
        ),
    }

    allocated = allocate_decision_actions(
        SimpleNamespace(config=None), context, [action]
    )

    assert allocated[0]["allocation_price"] == (account_price or 10.0)
    assert allocated[0]["allocation_quantity"] == (
        2000.0 if account_price is not None else 1000.0
    )
    assert allocated[0]["allocation_status"] == "allocated"


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
