from __future__ import annotations

import asyncio
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from server.projections.models import ProjectedPosition
from server.services.position_presence import (
    POSITION_QUANTITY_ZERO_TOLERANCE,
    classify_position_presence,
    is_economically_zero_quantity,
)


def _endpoint(router, path: str):
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path
    )


def _ledger_rows() -> list[dict]:
    return [
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-07-01T09:00:00+08:00",
            "amount": 10_000.0,
            "note": "fixture capital",
            "source": "fixture",
        },
        {
            "id": 2,
            "entry_type": "trade_buy",
            "timestamp": "2026-07-02T10:00:00+08:00",
            "symbol": "600066",
            "direction": "buy",
            "quantity": 200.0,
            "price": 10.0,
            "commission": 2.0,
            "asset_class": "stock",
            "note": "buy yutong",
            "source": "fixture",
        },
        {
            "id": 3,
            "entry_type": "trade_sell",
            "timestamp": "2026-07-03T10:00:00+08:00",
            "symbol": "600066",
            "direction": "sell",
            "quantity": 100.0,
            "price": 12.0,
            "commission": 1.0,
            "asset_class": "stock",
            "note": "first yutong exit",
            "source": "fixture",
        },
        {
            "id": 4,
            "entry_type": "trade_sell",
            "timestamp": "2026-07-04T10:00:00+08:00",
            "symbol": "600066",
            "direction": "sell",
            "quantity": 100.0,
            "price": 11.0,
            "commission": 1.0,
            "asset_class": "stock",
            "note": "final yutong exit",
            "source": "fixture",
        },
        {
            "id": 5,
            "entry_type": "trade_buy",
            "timestamp": "2026-07-05T10:00:00+08:00",
            "symbol": "000001",
            "direction": "buy",
            "quantity": 10.0,
            "price": 5.0,
            "commission": 0.0,
            "asset_class": "stock",
            "note": "open fixture position",
            "source": "fixture",
        },
    ]


class PersistedLedgerDb:
    def __init__(self) -> None:
        self.rows = _ledger_rows()

    def get_ledger_entries_sync(self, limit=500, offset=0):
        return deepcopy(self.rows[offset : offset + limit])

    def get_cash_flows_sync(self, limit=1000, offset=0):
        return []

    def get_trades_sync(self, limit=1000, offset=0):
        return []

    def list_latest_quotes_sync(self):
        return [
            {
                "id": 1,
                "symbol": "000001",
                "asset_type": "stock",
                "price": 6.0,
                "previous_close": 5.5,
                "previous_close_date": "2026-07-10",
                "quote_timestamp": "2026-07-10T15:00:00+08:00",
                "quote_source": "persisted_fixture",
                "quote_status": "confirmed",
                "display_name": "平安银行",
            }
        ]

    def get_instrument_metadata_sync(self, symbol, asset_type=None):
        names = {"600066": "宇通客车", "000001": "平安银行"}
        return {
            "symbol": symbol,
            "asset_type": asset_type or "stock",
            "display_name": names[str(symbol)],
        }

    async def get_total_deposits(self):
        return 10_000.0

    async def get_action_tasks(self, statuses, limit):
        return []


def test_quantity_precision_filters_only_economic_zero() -> None:
    assert is_economically_zero_quantity(POSITION_QUANTITY_ZERO_TOLERANCE)
    assert is_economically_zero_quantity(Decimal("-0.00000001"))
    assert not is_economically_zero_quantity(Decimal("0.000001"))
    assert not is_economically_zero_quantity(Decimal("100"))
    assert not is_economically_zero_quantity(Decimal("-100"))

    positive = ProjectedPosition(symbol="LONG", quantity=Decimal("100"))
    negative = ProjectedPosition(symbol="SHORT", quantity=Decimal("-100"))
    residual = ProjectedPosition(symbol="RESIDUAL", quantity=Decimal("0.00000001"))
    assert classify_position_presence(positive)[0] == "current"
    assert classify_position_presence(negative)[0] == "current"
    assert classify_position_presence(residual)[0] == "closed"


def test_zero_quantity_with_inconsistent_evidence_requires_review(
    monkeypatch,
) -> None:
    from server.routes import portfolio as portfolio_routes

    position = ProjectedPosition(
        symbol="REVIEW",
        quantity=Decimal("0"),
        available_qty=Decimal("1"),
        market_value=Decimal("0"),
        unrealized_pnl=Decimal("0"),
    )

    class EmptyDb:
        def get_ledger_entries_sync(self, limit=500, offset=0):
            return []

        def get_cash_flows_sync(self, limit=1000, offset=0):
            return []

        def get_trades_sync(self, limit=1000, offset=0):
            return []

        def list_latest_quotes_sync(self):
            return []

        async def get_total_deposits(self):
            return 0.0

    state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0, assets=[]),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=0, positions={"REVIEW": position}),
            instruments={},
            watchlist=[],
            latest_quotes={},
        ),
        db=EmptyDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: state)

    snapshot = asyncio.run(
        _endpoint(portfolio_routes.create_router(), "/api/portfolio")()
    )

    assert snapshot.positions == []
    assert snapshot.closed_positions == []
    assert len(snapshot.position_review_items) == 1
    assert snapshot.position_review_items[0].position.symbol == "REVIEW"
    assert snapshot.position_review_items[0].reason_codes == [
        "available_quantity_nonzero"
    ]


def test_closed_ledger_position_is_historical_but_not_current_across_consumers(
    monkeypatch,
) -> None:
    from server.routes import ledger as ledger_routes
    from server.routes import portfolio as portfolio_routes

    db = PersistedLedgerDb()
    original_rows = deepcopy(db.rows)
    state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0, assets=[], live_poll_interval=60),
        scheduler=None,
        db=db,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: state)

    portfolio_router = portfolio_routes.create_router()
    snapshot = asyncio.run(_endpoint(portfolio_router, "/api/portfolio")())
    positions = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/positions")())
    allocation = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/allocation")())
    overview = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/overview")())
    cockpit = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/cockpit")())
    history = asyncio.run(
        _endpoint(ledger_routes.create_router(), "/api/ledger/entries")(
            limit=50, offset=0
        )
    )

    assert [position.symbol for position in snapshot.positions] == ["000001"]
    assert [position.symbol for position in positions] == ["000001"]
    assert [position.symbol for position in snapshot.closed_positions] == ["600066"]
    assert snapshot.position_review_items == []

    allocation_symbols = {
        item.symbol for item in allocation if item.asset_class != "cash"
    }
    grouped_symbols = {
        item.symbol
        for group in snapshot.allocation_grouped
        for item in group.items
        if item.asset_class != "cash"
    }
    assert allocation_symbols == {"000001"}
    assert grouped_symbols == {"000001"}

    assert overview.positions_count == len(positions) == len(cockpit.positions) == 1
    assert snapshot.realized_pnl_total == pytest.approx(296.0)
    assert overview.realized_pnl == pytest.approx(snapshot.realized_pnl_total)

    sell_history = [
        entry
        for entry in history
        if entry.symbol == "600066" and entry.entry_type == "trade_sell"
    ]
    assert len(sell_history) == 2
    assert sum(entry.commission for entry in sell_history) == pytest.approx(2.0)
    assert db.rows == original_rows

    assert snapshot.valuation_snapshot_id is not None
    assert snapshot.ledger_cutoff_id == 5
    assert overview.valuation_snapshot_id == snapshot.valuation_snapshot_id
    assert overview.ledger_cutoff_id == snapshot.ledger_cutoff_id
    assert cockpit.summary.valuation_snapshot_id == snapshot.valuation_snapshot_id
    assert cockpit.summary.ledger_cutoff_id == snapshot.ledger_cutoff_id
