from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from server.contracts.http.ledger_models import (
    CashFlowCreate,
    ManualTradeCreate,
    PortfolioCorrectionRequest,
)
from server.db import AppDatabase

pytestmark = pytest.mark.unit


def _route(router, path: str, method: str = "POST"):
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def _state(database: AppDatabase):
    return SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=0.0,
            assets=[],
            account_commission_rate=0.0,
            account_min_commission=0.0,
        ),
        db=database,
        scheduler=SimpleNamespace(is_running=False),
    )


def test_portfolio_trade_routes_replay_exact_command_and_use_post_correction(
    monkeypatch,
    tmp_path,
) -> None:
    from server.routes import portfolio as portfolio_routes

    database = AppDatabase(tmp_path / "trade-routes.db")
    database.init_sync()
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: _state(database))
    router = portfolio_routes.create_router()
    create_route = _route(router, "/api/portfolio/trade")
    correction_route = _route(
        router,
        "/api/portfolio/trade/{trade_id}/corrections",
    )
    body = ManualTradeCreate(
        command_id="route-trade-command-1",
        operator_id="human-operator",
        timestamp="2026-08-26T10:00:00+08:00",
        symbol="600000.SH",
        direction="buy",
        quantity=10,
        price=10,
        commission=1,
        asset_class="stock",
        note="route trade",
    )

    first = asyncio.run(create_route.endpoint(body))
    replay = asyncio.run(create_route.endpoint(body))
    assert first.id == replay.id
    assert first.replayed is False
    assert replay.replayed is True
    assert len(database.get_ledger_entries_sync(limit=100)) == 1

    with pytest.raises(HTTPException) as conflict:
        asyncio.run(create_route.endpoint(body.model_copy(update={"note": "drift"})))
    assert conflict.value.status_code == 409

    correction = PortfolioCorrectionRequest(
        command_id="route-trade-correction-1",
        operator_id="human-operator",
    )
    corrected = asyncio.run(correction_route.endpoint(first.id, correction))
    corrected_replay = asyncio.run(correction_route.endpoint(first.id, correction))
    assert corrected.corrected is True
    assert corrected.replayed is False
    assert corrected_replay.replayed is True
    assert corrected_replay.correction_ledger_entry_id == (
        corrected.correction_ledger_entry_id
    )
    assert not any(
        route.path == "/api/portfolio/trade/{trade_id}" and "DELETE" in route.methods
        for route in router.routes
        if isinstance(route, APIRoute)
    )


def test_portfolio_cash_flow_routes_replay_exact_command_and_never_delete(
    monkeypatch,
    tmp_path,
) -> None:
    from server.routes import portfolio as portfolio_routes

    database = AppDatabase(tmp_path / "cash-flow-routes.db")
    database.init_sync()
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: _state(database))
    router = portfolio_routes.create_router()
    create_route = _route(router, "/api/portfolio/cash-flow")
    correction_route = _route(
        router,
        "/api/portfolio/cash-flow/{flow_id}/corrections",
    )
    body = CashFlowCreate(
        command_id="route-cash-command-1",
        operator_id="human-operator",
        timestamp="2026-08-26T10:00:00+08:00",
        amount=100,
        flow_type="deposit",
        note="route deposit",
    )

    first = asyncio.run(create_route.endpoint(body))
    replay = asyncio.run(create_route.endpoint(body))
    assert first.id == replay.id
    assert first.replayed is False
    assert replay.replayed is True
    assert len(database.get_ledger_entries_sync(limit=100)) == 1

    with pytest.raises(HTTPException) as conflict:
        asyncio.run(create_route.endpoint(body.model_copy(update={"amount": 101})))
    assert conflict.value.status_code == 409

    correction = PortfolioCorrectionRequest(
        command_id="route-cash-correction-1",
        operator_id="human-operator",
    )
    corrected = asyncio.run(correction_route.endpoint(first.id, correction))
    corrected_replay = asyncio.run(correction_route.endpoint(first.id, correction))
    assert corrected.corrected is True
    assert corrected.replayed is False
    assert corrected_replay.replayed is True
    assert corrected_replay.correction_ledger_entry_id == (
        corrected.correction_ledger_entry_id
    )
    assert not any(
        route.path == "/api/portfolio/cash-flow/{flow_id}" and "DELETE" in route.methods
        for route in router.routes
        if isinstance(route, APIRoute)
    )


@pytest.mark.parametrize(
    "amount",
    [0.0, -1.0, float("nan"), float("inf"), float("-inf")],
)
def test_portfolio_cash_flow_http_contract_rejects_invalid_amounts(
    amount: float,
) -> None:
    with pytest.raises(ValidationError):
        CashFlowCreate(
            command_id="route-cash-invalid",
            operator_id="human-operator",
            amount=amount,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", float("nan")),
        ("quantity", float("inf")),
        ("price", float("-inf")),
        ("amount", float("inf")),
        ("commission", float("nan")),
    ],
)
def test_portfolio_trade_http_contract_rejects_non_finite_values(
    field: str,
    value: float,
) -> None:
    payload = {
        "command_id": "route-trade-invalid",
        "operator_id": "human-operator",
        "symbol": "600000.SH",
        "direction": "buy",
        field: value,
    }
    with pytest.raises(ValidationError):
        ManualTradeCreate(**payload)
