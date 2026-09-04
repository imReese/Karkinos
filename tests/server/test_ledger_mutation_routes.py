"""HTTP contracts for explicit, replay-safe ledger mutations."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from server.contracts.ledger_mutations import ledger_entry_state_fingerprint
from server.db import AppDatabase
from server.routes import ledger as ledger_routes


def _seed_position(
    database: AppDatabase,
    *,
    symbol: str,
    quantity: float,
    asset_class: str = "stock",
) -> None:
    database.insert_ledger_entry_sync(
        entry_type="manual_adjustment",
        timestamp="2026-01-01T09:00:00+08:00",
        symbol=symbol,
        quantity=quantity,
        price=1.0,
        asset_class=asset_class,
        source="internal_fixture",
        source_ref=f"opening-position-{symbol}",
    )


@pytest.mark.parametrize(
    ("model", "payload"),
    (
        (
            ledger_routes.LedgerTradeCreate,
            {
                "operator_id": "local-owner",
                "request_id": "invalid-trade",
                "symbol": "600519",
                "direction": "buy",
                "quantity": -1,
                "unit_price": 100,
            },
        ),
        (
            ledger_routes.LedgerCashFlowCreate,
            {
                "operator_id": "local-owner",
                "request_id": "invalid-cash",
                "amount": 0,
            },
        ),
        (
            ledger_routes.LedgerDividendCreate,
            {
                "operator_id": "local-owner",
                "request_id": "invalid-dividend",
                "symbol": "600519",
                "amount": float("inf"),
            },
        ),
        (
            ledger_routes.LedgerAdjustmentCreate,
            {
                "operator_id": "local-owner",
                "request_id": "invalid-adjustment",
                "amount": float("nan"),
            },
        ),
        (
            ledger_routes.LedgerTradeSettlementCreate,
            {
                "operator_id": "local-owner",
                "request_id": "invalid-settlement",
                "expected_entry_fingerprint": "a" * 64,
                "commission": float("inf"),
                "net_cash_impact": 1,
                "source_ref": "broker-fill-1",
            },
        ),
    ),
)
def test_http_ledger_models_reject_invalid_money(model, payload) -> None:
    with pytest.raises(ValidationError):
        model(**payload)


@pytest.mark.parametrize(
    ("path", "model", "payload", "entry_type"),
    (
        (
            "/api/ledger/trades",
            ledger_routes.LedgerTradeCreate,
            {
                "symbol": "600519",
                "direction": "buy",
                "quantity": 10,
                "unit_price": 100,
                "fee": 5,
                "source_ref": "route-trade-1",
            },
            "trade_buy",
        ),
        (
            "/api/ledger/cash-flows",
            ledger_routes.LedgerCashFlowCreate,
            {
                "amount": 1000,
                "flow_type": "deposit",
                "source_ref": "route-cash-1",
            },
            "cash_deposit",
        ),
        (
            "/api/ledger/dividends",
            ledger_routes.LedgerDividendCreate,
            {
                "symbol": "600519",
                "amount": 88,
                "source_ref": "route-dividend-1",
            },
            "dividend",
        ),
        (
            "/api/ledger/adjustments",
            ledger_routes.LedgerAdjustmentCreate,
            {
                "symbol": "600519",
                "quantity": 1,
                "source_ref": "route-adjustment-1",
            },
            "manual_adjustment",
        ),
    ),
)
def test_append_routes_replay_and_reject_changed_payload(
    tmp_path,
    monkeypatch,
    path,
    model,
    payload,
    entry_type,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(db=database, config=None),
    )
    endpoint = _endpoint(path)
    request_payload = {
        "operator_id": "local-owner",
        "request_id": f"request-{entry_type}",
        "occurred_at": "2026-08-26T10:00:00+08:00",
        **payload,
    }

    first = asyncio.run(endpoint(model(**request_payload)))
    replay = asyncio.run(endpoint(model(**request_payload)))

    assert first.entry_type == entry_type
    assert replay.id == first.id
    assert replay.replayed is True
    listed = asyncio.run(_endpoint("/api/ledger/entries")())
    assert listed[0].entry_fingerprint == first.entry_fingerprint

    changed = model(**{**request_payload, "note": "changed immutable payload"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(endpoint(changed))
    assert error.value.status_code == 409


def test_settlement_route_replays_and_maps_request_conflict(
    tmp_path, monkeypatch
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    _seed_position(database, symbol="600519", quantity=100)
    entry_id = database.insert_ledger_entry_sync(
        entry_type="trade_sell",
        timestamp="2026-08-26T10:00:00+08:00",
        amount=1000.0,
        symbol="600519",
        direction="sell",
        quantity=100,
        price=10,
        commission=5,
        gross_amount=1000,
        net_cash_impact=995,
        source_ref="settlement-route-trade-1",
    )
    entry = database.get_ledger_entry_sync(entry_id)
    assert entry is not None
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(db=database),
    )
    endpoint = _endpoint("/api/ledger/trades/{entry_id}/settlement")
    payload = {
        "operator_id": "local-owner",
        "request_id": "settlement-route-request-1",
        "expected_entry_fingerprint": ledger_entry_state_fingerprint(entry),
        "settled_at": "2026-08-27T16:00:00+08:00",
        "commission": 5,
        "stamp_tax": 1.5,
        "net_cash_impact": 993.5,
        "source_ref": "settlement-evidence-route-1",
    }

    first = asyncio.run(
        endpoint(entry_id, ledger_routes.LedgerTradeSettlementCreate(**payload))
    )
    replay = asyncio.run(
        endpoint(entry_id, ledger_routes.LedgerTradeSettlementCreate(**payload))
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.entry_fingerprint == first.entry_fingerprint

    changed = ledger_routes.LedgerTradeSettlementCreate(
        **{**payload, "note": "changed immutable payload"}
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(endpoint(entry_id, changed))
    assert error.value.status_code == 409


def _endpoint(path: str):
    router = ledger_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path
    )
