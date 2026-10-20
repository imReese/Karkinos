from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import AssetClass, InstrumentType
from domain.instrument import make_etf, make_open_end_fund, make_stock
from server.db import AppDatabase
from server.routes.market import create_router
from server.services.market.asset_metadata import resolve_asset_metadata


def _state(db=None):
    return SimpleNamespace(
        db=db,
        config=SimpleNamespace(assets=[], initial_cash=0.0, data_source="akshare"),
        scheduler=SimpleNamespace(
            latest_quotes={}, watchlist=[], portfolio=None, instruments={}
        ),
    )


@pytest.mark.parametrize("kind", ["fund", "etf"])
def test_persisted_fund_holding_does_not_borrow_stock_metadata(
    tmp_path, monkeypatch, kind
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_instrument_metadata_sync(
        symbol="000001", asset_type="stock", display_name="Synthetic stock"
    )
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit", timestamp="2026-10-16T09:00:00+08:00", amount=1000
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-10-16T09:05:00+08:00",
        symbol="000001",
        asset_class=kind,
        direction="buy",
        quantity=100,
        price=1.25,
        gross_amount=125,
        net_cash_impact=-125,
    )
    ledger_before = db.get_ledger_entries_sync()
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: _state(db))
    app = FastAPI()
    app.include_router(create_router())

    with TestClient(app) as client:
        response = client.get("/api/market/watchlist")

    assert response.status_code == 200
    holding = next(row for row in response.json() if row["symbol"] == "000001")
    assert holding["asset_class"] == "fund"
    assert holding["instrument_type"] == ("open_end_fund" if kind == "fund" else "etf")
    assert holding["name"] == "000001"
    assert holding["is_holding"] is True
    assert holding["quantity"] == 100
    assert db.get_ledger_entries_sync() == ledger_before


@pytest.mark.parametrize("source", ["config", "watchlist", "quote", "instrument"])
def test_fund_metadata_rejects_conflicting_source_type(source):
    row = {"symbol": "000001", "asset_class": "stock", "display_name": "Stock"}
    state, quote = _state(), None
    if source == "config":
        state.config.assets = [row]
    elif source == "watchlist":
        state.db = SimpleNamespace(list_watchlist_assets_sync=lambda: [row])
    elif source == "quote":
        quote = row
    else:
        state.scheduler.instruments = {"000001": make_stock("000001", "Stock")}

    metadata = resolve_asset_metadata(
        state, "000001", asset_class="fund", quote=quote, fallback_name="Fund fallback"
    )

    assert metadata.asset_class == "fund"
    assert metadata.display_name == "Fund fallback"
    assert metadata.source == "fallback"


@pytest.mark.parametrize("factory", [make_etf, make_open_end_fund])
def test_exact_fund_type_selects_its_metadata_and_keeps_fund_group(tmp_path, factory):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    for kind in ("etf", "open_end_fund"):
        db.upsert_instrument_metadata_sync(
            symbol="019999", asset_type=kind, display_name=f"Synthetic {kind}"
        )
    instrument = factory("019999", "Instrument fallback")
    assert instrument.asset_class is AssetClass.FUND

    metadata = resolve_asset_metadata(
        _state(db),
        "019999",
        asset_class=instrument.asset_class,
        instrument_type=instrument.instrument_type,
    )

    assert metadata.display_name == f"Synthetic {instrument.instrument_type.value}"
    assert metadata.asset_class == "fund"
    assert metadata.source == "db"


def test_broad_fund_group_does_not_choose_between_two_instrument_types(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    for kind in ("etf", "open_end_fund"):
        db.upsert_instrument_metadata_sync(
            symbol="019999", asset_type=kind, display_name=f"Synthetic {kind}"
        )

    metadata = resolve_asset_metadata(
        _state(db), "019999", asset_class=AssetClass.FUND, fallback_name="Fund fallback"
    )

    assert metadata.display_name == "Fund fallback"
    assert metadata.asset_class == "fund"
    assert metadata.source == "fallback"


@pytest.mark.parametrize("source", ["config", "watchlist", "quote", "instrument"])
def test_exact_fund_type_does_not_borrow_other_fund_type(source):
    row = {
        "symbol": "019999",
        "asset_class": "fund",
        "instrument_type": "open_end_fund",
        "display_name": "Open-end fund",
    }
    state, quote = _state(), None
    if source == "config":
        state.config.assets = [row]
    elif source == "watchlist":
        state.db = SimpleNamespace(list_watchlist_assets_sync=lambda: [row])
    elif source == "quote":
        quote = row
    else:
        state.scheduler.instruments = {
            "019999": make_open_end_fund("019999", "Open-end fund")
        }

    metadata = resolve_asset_metadata(
        state,
        "019999",
        asset_class=AssetClass.FUND,
        instrument_type=InstrumentType.ETF,
        quote=quote,
        fallback_name="ETF fallback",
    )

    assert metadata.display_name == "ETF fallback"
    assert metadata.asset_class == "fund"
    assert metadata.source == "fallback"


@pytest.mark.parametrize("source", ["config", "watchlist", "quote", "instrument"])
@pytest.mark.parametrize("kind", [InstrumentType.ETF, InstrumentType.OPEN_END_FUND])
def test_fund_group_preserves_names_for_matching_exact_types(source, kind):
    rows = [
        {
            "symbol": "019999",
            "asset_class": "fund",
            "instrument_type": value.value,
            "display_name": f"Synthetic {value.value}",
        }
        for value in (InstrumentType.ETF, InstrumentType.OPEN_END_FUND)
    ]
    state, quote = _state(), None
    if source == "config":
        state.config.assets = rows
    elif source == "watchlist":
        state.db = SimpleNamespace(list_watchlist_assets_sync=lambda: rows)
    elif source == "quote":
        quote = next(row for row in rows if row["instrument_type"] == kind.value)
    else:
        factory = make_etf if kind is InstrumentType.ETF else make_open_end_fund
        state.scheduler.instruments = {
            "019999": factory("019999", f"Synthetic {kind.value}")
        }

    metadata = resolve_asset_metadata(
        state,
        "019999",
        asset_class=AssetClass.FUND,
        instrument_type=kind,
        quote=quote,
    )

    assert metadata.display_name == f"Synthetic {kind.value}"
    assert metadata.asset_class == "fund"


@pytest.mark.parametrize("kind", ["etf", "open_end_fund", "fund"])
def test_unique_fund_metadata_preserves_broad_group_and_legacy_alias(tmp_path, kind):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_instrument_metadata_sync(
        symbol="019999", asset_type=kind, display_name="Synthetic fund"
    )

    for requested_type in (None, InstrumentType.from_persisted(kind)):
        metadata = resolve_asset_metadata(
            _state(db),
            "019999",
            asset_class=AssetClass.FUND,
            instrument_type=requested_type,
        )
        assert metadata.display_name == "Synthetic fund"
        assert metadata.asset_class == "fund"


@pytest.mark.parametrize("kind", [InstrumentType.ETF, InstrumentType.OPEN_END_FUND])
def test_legacy_config_label_does_not_override_declared_fund_identity(kind):
    state = _state()
    state.config.assets = [
        {"symbol": "019999", "asset_class": "fund", "display_name": "Generic fund"},
        {
            "symbol": "019999",
            "instrument_type": "open_end_fund",
            "display_name": "Open-end fund",
        },
    ]

    metadata = resolve_asset_metadata(
        state,
        "019999",
        asset_class=AssetClass.FUND,
        instrument_type=kind,
        fallback_name="ETF fallback",
    )

    assert metadata.display_name == (
        "ETF fallback" if kind is InstrumentType.ETF else "Open-end fund"
    )
    assert metadata.asset_class == "fund"


@pytest.mark.parametrize("raw_class", ["fund", " FUND ", "Fund"])
def test_broad_quote_class_spelling_does_not_supply_exact_identity(raw_class):
    metadata = resolve_asset_metadata(
        _state(),
        "019999",
        asset_class=AssetClass.FUND,
        instrument_type=InstrumentType.OPEN_END_FUND,
        quote={"asset_class": raw_class, "display_name": "Broad label"},
        fallback_name="Bound fallback",
    )

    assert metadata.display_name == "Bound fallback"
    assert metadata.source == "fallback"


def test_legacy_config_name_cannot_hide_a_conflicting_declared_group():
    state = _state()
    state.config.instruments = [
        {"symbol": "000001", "asset_class": "fund", "display_name": "Declared fund"}
    ]
    state.config.assets = {"000001": "Generic fund name"}

    metadata = resolve_asset_metadata(
        state,
        "000001",
        asset_class="stock",
        instrument_type=InstrumentType.STOCK,
        fallback_name="Stock fallback",
    )

    assert metadata.display_name == "Stock fallback"
    assert metadata.asset_class == "stock"
    assert metadata.source == "fallback"
