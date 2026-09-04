"""Portfolio ledger replay preserves explicit instrument identity."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.types import CommissionType, InstrumentType, Settlement, Symbol
from server.projections.valuation_snapshot import build_current_valuation_snapshot
from server.services.portfolio_ledger import rebuild_portfolio_from_entries


def _legacy_etf_rows() -> list[dict[str, object]]:
    return [
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-09-01T09:00:00+08:00",
            "amount": 10_000.0,
            "asset_class": "cash",
        },
        {
            "id": 2,
            "entry_type": "trade_buy",
            "timestamp": "2026-09-01T10:00:00+08:00",
            "symbol": "510300",
            "direction": "buy",
            "quantity": 100.0,
            "price": 4.0,
            "asset_class": "fund",
        },
    ]


def test_explicit_etf_identity_survives_legacy_fund_ledger_roundtrip() -> None:
    rebuilt = rebuild_portfolio_from_entries(
        SimpleNamespace(
            assets=[{"symbol": "510300", "asset_class": "etf"}],
        ),
        _legacy_etf_rows(),
        latest_quotes={
            "510300": {
                "symbol": "510300",
                "asset_class": "etf",
                "price": 4.1,
            }
        },
    )

    instrument = rebuilt.instruments[Symbol("510300")]
    assert instrument.instrument_type is InstrumentType.ETF
    assert instrument.commission_type is CommissionType.FUND_ETF
    assert instrument.settlement is Settlement.T_PLUS_1
    assert instrument.lot_size == Decimal("100")
    assert rebuilt.portfolio.positions[Symbol("510300")].market_value == Decimal(
        "410.0"
    )


def test_quote_identity_does_not_retype_legacy_fund_without_config() -> None:
    rebuilt = rebuild_portfolio_from_entries(
        SimpleNamespace(assets=[]),
        _legacy_etf_rows(),
        latest_quotes={
            "510300": {
                "symbol": "510300",
                "instrument_type": "etf",
                "asset_class": "fund",
                "price": 4.1,
            }
        },
    )

    assert (
        rebuilt.instruments[Symbol("510300")].instrument_type
        is InstrumentType.OPEN_END_FUND
    )
    position = rebuilt.portfolio.positions[Symbol("510300")]
    assert position.valuation_available is False
    assert position.market_value == Decimal("0")


def test_conflicting_explicit_fund_instrument_identities_fail_closed() -> None:
    rows = _legacy_etf_rows()
    rows[-1] = {**rows[-1], "asset_class": "open_end_fund"}

    with pytest.raises(
        ValueError,
        match="instrument identity conflicts for 510300: etf,open_end_fund",
    ):
        rebuild_portfolio_from_entries(
            SimpleNamespace(
                assets=[{"symbol": "510300", "instrument_type": "etf"}],
            ),
            rows,
            latest_quotes={"510300": {"price": 4.1}},
        )


def test_valuation_scope_does_not_promote_legacy_fund_from_quote() -> None:
    class EtfValuationDb:
        def get_ledger_entries_sync(self, limit=500, offset=0):
            return _legacy_etf_rows()[offset : offset + limit]

        def list_quote_selection_candidates_sync(self):
            return [
                {
                    "id": 1,
                    "symbol": "510300",
                    "asset_type": "etf",
                    "price": 4.1,
                    "quote_timestamp": "2026-09-01T15:00:00+08:00",
                    "quote_status": "confirmed",
                    "quote_source": "persisted_etf_quote",
                }
            ]

        def get_latest_market_bar_before_date_sync(
            self,
            symbol,
            trade_date,
            *,
            instrument_type,
        ):
            assert symbol == "510300"
            assert trade_date == "2026-09-01"
            assert instrument_type == "open_end_fund"
            return {
                "close": 4.0,
                "trade_date": "2026-08-31",
                "source": "persisted_etf_close",
            }

    snapshot = build_current_valuation_snapshot(EtfValuationDb())

    assert snapshot["status"] == "missing"
    assert snapshot["quotes"][0]["symbol"] == "510300"
    assert snapshot["quotes"][0]["asset_type"] == "fund"
    assert snapshot["quotes"][0]["quote_status"] == "missing"
    assert snapshot["valuation_lanes"][1]["asset_class"] == "fund"
    assert snapshot["valuation_lanes"][1]["status"] == "missing"


def test_valuation_scope_ignores_unrelated_quote_namespaces() -> None:
    class ConflictingValuationDb:
        def get_ledger_entries_sync(self, limit=500, offset=0):
            return _legacy_etf_rows()[offset : offset + limit]

        def list_quote_selection_candidates_sync(self):
            return [
                {
                    "id": 1,
                    "symbol": "510300",
                    "asset_type": "etf",
                    "price": 4.1,
                    "quote_timestamp": "2026-09-01T15:00:00+08:00",
                    "quote_status": "confirmed",
                },
                {
                    "id": 2,
                    "symbol": "510300",
                    "asset_type": "open_end_fund",
                    "price": 1.2,
                    "quote_timestamp": "2026-09-01T15:00:00+08:00",
                    "quote_status": "confirmed",
                },
            ]

    snapshot = build_current_valuation_snapshot(ConflictingValuationDb())

    assert snapshot["status"] == "degraded"
    assert len(snapshot["quotes"]) == 1
    assert snapshot["quotes"][0]["id"] == 2
    assert snapshot["quotes"][0]["asset_type"] == "fund"
    assert snapshot["quotes"][0]["observation_instrument_type"] == "open_end_fund"
