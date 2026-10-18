from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import BarFrequency, InstrumentType, Symbol
from data.store import DataStore
from server.db import AppDatabase
from server.routes.market import create_router

pytestmark = pytest.mark.unit

_CASES = [
    ("000001", "index", "stock"),
    ("019999", "etf", "open_end_fund"),
    ("019999", "open_end_fund", "etf"),
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "market-data"
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(root))
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    state = SimpleNamespace(
        db=db,
        scheduler=None,
        config=SimpleNamespace(assets=[], initial_cash=0, data_source="akshare"),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    monkeypatch.setattr("data.manager.build_sources_for_config", lambda config: {})

    def reject_metadata_provider(*args, **kwargs):
        raise AssertionError("cached exact metadata must not require a provider")

    monkeypatch.setattr(
        "server.services.market_views.backfill._metadata_sources",
        reject_metadata_provider,
    )
    app = FastAPI()
    app.include_router(create_router())
    with TestClient(app) as client:
        yield SimpleNamespace(db=db, store=DataStore(root), client=client)


def _cache_identity(workspace, symbol, kind, price):
    workspace.db.upsert_instrument_metadata_sync(
        symbol=symbol,
        asset_type="fund" if kind == "open_end_fund" else kind,
        display_name=f"synthetic {kind}",
        provider_name="synthetic",
    )
    workspace.store.save_bars(
        Symbol(symbol),
        BarFrequency.DAILY,
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-05-27", "2026-05-28"]),
                "open": [price, price],
                "high": [price, price],
                "low": [price, price],
                "close": [price, price],
                "volume": [100.0, 120.0],
            }
        ),
        instrument_type=InstrumentType.from_persisted(kind),
    )


def _backfill(workspace, request):
    metadata = workspace.client.post(
        "/api/market/instrument-metadata/backfill", json=request
    )
    bars = workspace.client.post(
        "/api/market/bars/backfill",
        json={**request, "start": "2026-05-27", "end": "2026-05-28"},
    )
    return metadata, bars


@pytest.mark.parametrize("symbol, watched_kind, held_kind", _CASES)
@pytest.mark.parametrize("selection", ["held", "watched", "symbol", "all"])
def test_backfill_preserves_known_identities_through_both_http_commands(
    workspace, symbol, watched_kind, held_kind, selection
):
    db = workspace.db
    db.upsert_watchlist_asset_sync(
        symbol=symbol, asset_class=watched_kind, instrument_type=watched_kind
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-05-26T10:00:00+08:00",
        symbol=symbol,
        direction="buy",
        quantity=100,
        price=10,
        asset_class=held_kind,
    )
    _cache_identity(workspace, symbol, watched_kind, 20.0)
    _cache_identity(workspace, symbol, held_kind, 12.5)
    ledger_before = db.get_ledger_entries_sync()
    request = {} if selection == "all" else {"symbols": [symbol]}
    expected_kinds = [watched_kind, held_kind]
    if selection in {"held", "watched"}:
        kind = held_kind if selection == "held" else watched_kind
        request["instrument_type"] = kind
        expected_kinds = [kind]

    metadata, bars = _backfill(workspace, request)

    assert metadata.status_code == 200, metadata.text
    assert bars.status_code == 200, bars.text
    expected_classes = [
        "fund" if kind == "open_end_fund" else kind for kind in expected_kinds
    ]
    metadata_result = metadata.json()
    assert metadata_result["requested_count"] == len(expected_kinds)
    assert metadata_result["skipped_count"] == len(expected_kinds)
    assert metadata_result["updated_count"] == metadata_result["failed_count"] == 0
    assert [
        (item["symbol"], item["asset_class"], item["display_name"])
        for item in metadata_result["items"]
    ] == [
        (symbol, asset_class, f"synthetic {kind}")
        for asset_class, kind in zip(expected_classes, expected_kinds, strict=True)
    ]
    bars_result = bars.json()
    assert bars_result["requested_count"] == len(expected_kinds)
    assert bars_result["cached_count"] == len(expected_kinds)
    assert bars_result["updated_count"] == bars_result["failed_count"] == 0
    assert [
        (item["symbol"], item["asset_class"], item["row_count"])
        for item in bars_result["items"]
    ] == [(symbol, asset_class, 2) for asset_class in expected_classes]
    assert db.get_ledger_entries_sync() == ledger_before


@pytest.mark.parametrize("symbol, known_kind, conflicting_kind", _CASES)
def test_backfill_rejects_retyping_a_single_known_identity(
    workspace, symbol, known_kind, conflicting_kind
):
    workspace.db.upsert_watchlist_asset_sync(
        symbol=symbol, asset_class=known_kind, instrument_type=known_kind
    )
    # A cached fact alone does not replace the configured/watchlist identity.
    _cache_identity(workspace, symbol, conflicting_kind, 12.5)

    responses = _backfill(
        workspace, {"symbols": [symbol], "instrument_type": conflicting_kind}
    )

    for response in responses:
        assert response.status_code == 422
        assert response.json()["detail"] == (
            "requested instrument_type conflicts with persisted identity"
        )


@pytest.mark.parametrize("explicit", [False, True])
def test_backfill_unknown_symbol_still_requires_explicit_type(workspace, explicit):
    _cache_identity(workspace, "600001", "stock", 12.5)
    request = {"symbols": ["600001"]}
    if explicit:
        request["instrument_type"] = "stock"

    responses = _backfill(workspace, request)

    for response in responses:
        if explicit:
            assert response.status_code == 200, response.text
            assert response.json()["requested_count"] == 1
        else:
            assert response.status_code == 422
            assert response.json()["detail"] == (
                "instrument_type is required for unknown symbols"
            )


@pytest.mark.parametrize(
    "kind, conflicting_class", [("etf", "fund"), ("open_end_fund", "etf")]
)
def test_bar_backfill_keeps_explicit_asset_class_conflict_rejection(
    workspace, kind, conflicting_class
):
    workspace.db.upsert_watchlist_asset_sync(
        symbol="019999", asset_class=kind, instrument_type=kind
    )
    response = workspace.client.post(
        "/api/market/bars/backfill",
        json={
            "symbols": ["019999"],
            "instrument_type": kind,
            "asset_class": conflicting_class,
            "start": "2026-05-27",
            "end": "2026-05-28",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "asset_class conflicts with instrument_type"


def test_bar_backfill_does_not_infer_unknown_identity_from_asset_class(workspace):
    response = workspace.client.post(
        "/api/market/bars/backfill",
        json={
            "symbols": ["600001"],
            "asset_class": "stock",
            "start": "2026-05-27",
            "end": "2026-05-28",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "instrument_type is required for unknown symbols"
    )
