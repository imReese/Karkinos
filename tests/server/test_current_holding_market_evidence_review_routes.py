from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.models import PortfolioSnapshot, PositionResponse
from server.routes import portfolio as portfolio_routes


def test_current_holding_market_review_route_uses_canonical_snapshot_only(
    monkeypatch,
) -> None:
    snapshot = PortfolioSnapshot(
        cash=1000,
        total_equity=2100,
        positions=[
            PositionResponse(
                symbol="FUND-A",
                name="Fixture Fund",
                asset_class="fund",
                quantity=1000,
                available_qty=1000,
                frozen_qty=0,
                avg_cost=1,
                latest_price=1.1,
                market_value=1100,
                unrealized_pnl=100,
                realized_pnl=0,
                commission_paid=0,
                quote_timestamp="2026-07-17T15:00:00+08:00",
                quote_status="confirmed_nav_missing",
                quote_source="eastmoney_fund_estimate",
            )
        ],
        allocation=[],
        valuation_snapshot_id="valuation-route-fixture",
        valuation_as_of="2026-07-17T15:00:00+08:00",
        valuation_trade_date="2026-07-17",
        valuation_policy="karkinos.persisted_valuation.v4",
        valuation_status="degraded",
        ledger_cutoff_id=9,
        ledger_fingerprint="ledger-route-fixture",
        quote_set_fingerprint="quote-route-fixture",
    )
    calls: list[object] = []
    state = SimpleNamespace(
        db=object(),
        scheduler=SimpleNamespace(
            data_provider=SimpleNamespace(
                get_quote=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("GET must not contact a provider")
                )
            )
        ),
    )

    async def build_snapshot(received_state) -> PortfolioSnapshot:
        calls.append(received_state)
        return snapshot

    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    monkeypatch.setattr(
        "server.routes.portfolio.build_portfolio_snapshot", build_snapshot
    )
    router = portfolio_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/market-evidence-review"
    )

    payload = asyncio.run(route.endpoint()).model_dump(mode="json")

    assert calls == [state]
    assert payload["status"] == "review_required"
    assert payload["review_required_count"] == 1
    assert payload["items"][0]["symbol"] == "FUND-A"
    assert payload["valuation_snapshot_id"] == "valuation-route-fixture"
    assert payload["ledger_cutoff_id"] == 9
    assert payload["provider_contact_performed"] is False
    assert payload["database_writes_performed"] is False
    assert payload["authorizes_execution"] is False
