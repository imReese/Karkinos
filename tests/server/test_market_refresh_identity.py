from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.types import AssetClass, Symbol
from domain.instrument import make_etf
from server.db import AppDatabase
from server.scheduler_loop import runtime_quotes_from_persisted
from server.services import market_refresh
from server.services.market_views.health_inputs import (
    extract_runtime_portfolio,
    find_asset_config,
    ledger_position_assets,
    merged_watchlist_assets,
)

pytestmark = pytest.mark.unit

_SYNTHETIC_ETF_SYMBOL = "019999"


def _config(instrument_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        assets=[{"symbol": _SYNTHETIC_ETF_SYMBOL, "instrument_type": instrument_type}],
        data_source="akshare",
        tushare_token="",
        live_poll_interval=60,
    )


def test_etf_cache_lookup_never_accepts_legacy_fund_observation() -> None:
    class FakeDb:
        @staticmethod
        def get_latest_quotes_sync():
            return [
                {
                    "symbol": _SYNTHETIC_ETF_SYMBOL,
                    "asset_type": "fund",
                    "price": 1.23,
                    "timestamp": "2026-09-04T10:00:00+08:00",
                }
            ]

    state = SimpleNamespace(
        config=_config("etf"),
        scheduler=SimpleNamespace(instruments={}),
        db=FakeDb(),
    )

    assert (
        market_refresh.latest_persistent_real_quote(
            state,
            _SYNTHETIC_ETF_SYMBOL,
            AssetClass.FUND,
        )
        is None
    )


def test_manual_etf_refresh_persists_and_publishes_canonical_identity(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    runtime_quotes: dict[str, dict] = {}
    scheduler = SimpleNamespace(
        instruments={
            Symbol(_SYNTHETIC_ETF_SYMBOL): make_etf(
                _SYNTHETIC_ETF_SYMBOL,
                "synthetic ETF",
            )
        },
        publish_runtime_quote=lambda symbol, quote: runtime_quotes.__setitem__(
            symbol,
            dict(quote),
        ),
    )
    state = SimpleNamespace(
        config=_config("etf"),
        scheduler=scheduler,
        db=db,
    )
    monkeypatch.setattr(market_refresh, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(
        market_refresh,
        "load_latest_snapshot_from_provider",
        lambda state, symbol, asset_class: {
            "symbol": symbol,
            "asset_class": "fund",
            "price": 2.5,
            "volume": 100.0,
            "timestamp": "2026-09-04T10:00:00+08:00",
            "quote_source": "fixture",
            "provider_name": "fixture",
            "provider_status": "live",
        },
    )
    monkeypatch.setattr(
        market_refresh,
        "resolve_quote_status",
        lambda state, quote, now=None: "live",
    )

    result = asyncio.run(
        market_refresh.refresh_one_quote(
            state,
            _SYNTHETIC_ETF_SYMBOL,
            AssetClass.FUND,
        )
    )

    assert result.status == "refreshed"
    assert db.get_latest_quote_sync(_SYNTHETIC_ETF_SYMBOL, "etf") is not None
    assert db.get_latest_quote_sync(_SYNTHETIC_ETF_SYMBOL, "open_end_fund") is None
    assert runtime_quotes[_SYNTHETIC_ETF_SYMBOL]["asset_class"] == "fund"
    assert runtime_quotes[_SYNTHETIC_ETF_SYMBOL]["instrument_type"] == "etf"


def test_committed_etf_publication_queries_exact_identity() -> None:
    requested: list[tuple[str, str]] = []
    runtime_quotes: dict[str, dict] = {}

    class FakeDb:
        @staticmethod
        def get_latest_quote_sync(symbol: str, asset_type: str):
            requested.append((symbol, asset_type))
            return {
                "symbol": symbol,
                "asset_type": asset_type,
                "price": 2.5,
                "volume": 100.0,
                "quote_timestamp": "2026-09-04T10:00:00+08:00",
                "fetch_run_id": "run-1",
            }

    state = SimpleNamespace(
        config=_config("etf"),
        scheduler=SimpleNamespace(
            instruments={
                Symbol(_SYNTHETIC_ETF_SYMBOL): make_etf(
                    _SYNTHETIC_ETF_SYMBOL,
                    "synthetic ETF",
                )
            },
            publish_runtime_quote=lambda symbol, quote: runtime_quotes.__setitem__(
                symbol,
                dict(quote),
            ),
        ),
        db=FakeDb(),
    )

    market_refresh.publish_committed_runtime_quotes(
        state,
        [SimpleNamespace(symbol=_SYNTHETIC_ETF_SYMBOL, asset_class="fund")],
    )

    assert requested == [(_SYNTHETIC_ETF_SYMBOL, "etf")]
    assert runtime_quotes[_SYNTHETIC_ETF_SYMBOL]["instrument_type"] == "etf"
    assert runtime_quotes[_SYNTHETIC_ETF_SYMBOL]["asset_class"] == "fund"


def test_scheduler_restore_does_not_bind_legacy_fund_quote_to_etf() -> None:
    restored = runtime_quotes_from_persisted(
        [
            {
                "id": 1,
                "symbol": _SYNTHETIC_ETF_SYMBOL,
                "asset_type": "fund",
                "price": 1.2,
                "volume": None,
                "timestamp": "2026-09-04T10:00:00+08:00",
            }
        ],
        {
            Symbol(_SYNTHETIC_ETF_SYMBOL): make_etf(
                _SYNTHETIC_ETF_SYMBOL,
                "synthetic ETF",
            )
        },
    )

    assert restored == {}


def test_scheduler_restore_rejects_unbound_same_symbol_identity_conflict() -> None:
    with pytest.raises(
        RuntimeError,
        match=f"quote identity conflicts: {_SYNTHETIC_ETF_SYMBOL}",
    ):
        runtime_quotes_from_persisted(
            [
                {
                    "id": 1,
                    "symbol": _SYNTHETIC_ETF_SYMBOL,
                    "asset_type": "fund",
                    "price": 1.2,
                    "volume": None,
                    "timestamp": "2026-09-04T10:00:00+08:00",
                },
                {
                    "id": 2,
                    "symbol": _SYNTHETIC_ETF_SYMBOL,
                    "asset_type": "etf",
                    "price": 2.5,
                    "volume": None,
                    "timestamp": "2026-09-04T10:00:00+08:00",
                },
            ],
            {},
        )


def test_ledger_position_assets_aggregate_same_symbol_by_exact_identity() -> None:
    rows = [
        {
            "entry_type": "trade_buy",
            "symbol": "000777",
            "instrument_type": "stock",
            "quantity": 10,
        },
        {
            "entry_type": "trade_sell",
            "symbol": "000777",
            "instrument_type": "stock",
            "quantity": 10,
        },
        {
            "entry_type": "trade_buy",
            "symbol": "000777",
            "instrument_type": "etf",
            "quantity": 4,
        },
        {
            "entry_type": "trade_buy",
            "symbol": "000777",
            "asset_class": "fund",
            "quantity": 3,
        },
    ]

    class FakeDb:
        @staticmethod
        def get_ledger_entries_sync(limit=500, offset=0):
            return rows[offset : offset + limit]

    state = SimpleNamespace(
        config=SimpleNamespace(assets=[]),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            latest_quotes={},
            watchlist=[],
        ),
        db=FakeDb(),
    )

    assets = ledger_position_assets(state)

    assert [asset["instrument_type"] for asset in assets] == [
        "etf",
        "open_end_fund",
    ]
    assert assets[1]["identity_provenance"] == "legacy_fund_compatibility"


def test_merged_watchlist_keeps_same_symbol_namespaces_separate() -> None:
    configured_assets = [
        {"symbol": "000777", "instrument_type": "stock"},
        {"symbol": "000777", "instrument_type": "etf"},
        {"symbol": "000777", "asset_class": "fund"},
        {"symbol": "000777", "instrument_type": "etf"},
    ]

    class FakeDb:
        @staticmethod
        def list_watchlist_assets_sync():
            return []

        @staticmethod
        def get_ledger_entries_sync(limit=500, offset=0):
            return []

    state = SimpleNamespace(
        config=SimpleNamespace(assets=configured_assets),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            latest_quotes={},
            watchlist=[],
        ),
        db=FakeDb(),
    )

    assets = merged_watchlist_assets(state)

    assert [asset["instrument_type"] for asset in assets] == [
        "stock",
        "etf",
        "open_end_fund",
    ]


def test_merged_watchlist_does_not_take_runtime_identity_from_quote() -> None:
    class FakeDb:
        @staticmethod
        def list_watchlist_assets_sync():
            return []

        @staticmethod
        def get_ledger_entries_sync(limit=500, offset=0):
            return []

    state = SimpleNamespace(
        config=SimpleNamespace(assets=[]),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                positions={Symbol("000777"): SimpleNamespace(quantity=1)}
            ),
            instruments={},
            latest_quotes={
                "000777": {
                    "symbol": "000777",
                    "instrument_type": "etf",
                    "price": 1.0,
                }
            },
            watchlist=[],
        ),
        db=FakeDb(),
    )

    assert merged_watchlist_assets(state) == []


def test_runtime_quote_projection_fails_closed_on_same_symbol_namespaces() -> None:
    class FakeDb:
        @staticmethod
        def list_latest_quotes_sync():
            return [
                {
                    "symbol": "000001",
                    "asset_type": "stock",
                    "price": 12.5,
                },
                {
                    "symbol": "000001",
                    "asset_type": "index",
                    "price": 3500.0,
                },
            ]

        @staticmethod
        def get_latest_quotes_sync():
            return []

    state = SimpleNamespace(
        config=SimpleNamespace(assets=[]),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    _, _, _, quotes = extract_runtime_portfolio(state)

    assert quotes == {}


def test_asset_config_lookup_requires_exact_type_when_symbol_is_ambiguous() -> None:
    assets = [
        {"symbol": "000001", "instrument_type": "stock"},
        {"symbol": "000001", "instrument_type": "index"},
    ]

    assert find_asset_config(assets, "000001") is None
    assert find_asset_config(assets, "000001", instrument_type="stock") == assets[0]
    assert find_asset_config(assets, "000001", instrument_type="index") == assets[1]
