import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from server.db import AppDatabase
from server.services.decision_candidate_market_evidence import (
    bind_candidate_market_evidence,
    candidate_market_evidence,
)


def _save_quote(
    db: AppDatabase,
    *,
    symbol: str,
    asset_type: str,
    price: float,
) -> None:
    db.upsert_latest_quote_sync(
        symbol=symbol,
        asset_type=asset_type,
        price=price,
        quote_timestamp="2026-07-02T09:30:00+08:00",
        quote_source="deterministic_fixture",
        quote_status="confirmed",
    )


def test_candidate_market_evidence_selects_exact_persisted_identity(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _save_quote(db, symbol="same-code", asset_type="stock", price=10.0)
    _save_quote(db, symbol="same-code", asset_type="fund", price=2.0)

    evidence = candidate_market_evidence(
        db,
        [{"id": 1, "symbol": "same-code", "asset_class": "stock"}],
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert evidence["source_status"] == "persisted_current_quotes"
    assert evidence["quotes"]["same-code"]["price"] == 10.0
    assert evidence["bindings"][0]["instrument_type"] == "stock"
    assert evidence["fingerprint"].startswith("sha256:")
    assert evidence["persisted_facts_only"] is True
    assert evidence["provider_contact_performed"] is False


def test_candidate_market_evidence_rejects_missing_instrument_type(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    evidence = candidate_market_evidence(
        db,
        [{"id": 7, "symbol": "600000"}],
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert evidence["invalid_task_ids"] == [7]
    assert evidence["quotes"] == {}


def test_candidate_market_evidence_rejects_same_symbol_across_types(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _save_quote(db, symbol="same-code", asset_type="stock", price=10.0)
    _save_quote(db, symbol="same-code", asset_type="fund", price=2.0)

    evidence = candidate_market_evidence(
        db,
        [
            {"id": 1, "symbol": "same-code", "asset_class": "stock"},
            {"id": 2, "symbol": "same-code", "asset_class": "fund"},
        ],
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert evidence["ambiguous_symbols"] == ["same-code"]
    assert evidence["quotes"] == {}
    assert {row["instrument_type"] for row in evidence["bindings"]} == {
        "open_end_fund",
        "stock",
    }


def test_candidate_market_evidence_freezes_stale_quote_status(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="600000",
        asset_type="stock",
        price=10.0,
        quote_timestamp="2026-07-01T15:00:00+08:00",
        quote_source="deterministic_fixture",
        quote_status="live",
    )

    evidence = candidate_market_evidence(
        db,
        [{"id": 1, "symbol": "600000", "asset_class": "stock"}],
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    quote = evidence["quotes"]["600000"]
    assert quote["observed_quote_status"] == "live"
    assert quote["quote_status"] == "stale"
    assert quote["stale_reason"] == "candidate_quote_outside_freshness_window"


@pytest.mark.parametrize("price", [-1.0, 0.0, float("inf")])
def test_candidate_market_evidence_rejects_non_positive_or_non_finite_price(
    tmp_path,
    price: float,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _save_quote(db, symbol="600000", asset_type="stock", price=price)

    evidence = candidate_market_evidence(
        db,
        [{"id": 1, "symbol": "600000", "asset_class": "stock"}],
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    quote = evidence["quotes"]["600000"]
    assert quote["quote_status"] == "error"
    assert quote["stale_reason"] == "candidate_quote_price_not_positive_finite"


def test_candidate_fingerprint_changes_when_persisted_provenance_changes(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="600000",
        asset_type="stock",
        price=10.0,
        quote_timestamp="2026-07-02T09:30:00+08:00",
        quote_source="deterministic_fixture",
        quote_status="confirmed",
        fetch_run_id="run-a",
    )
    now = datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai"))
    tasks = [{"id": 1, "symbol": "600000", "asset_class": "stock"}]
    first = candidate_market_evidence(db, tasks, now=now)

    db.upsert_latest_quote_sync(
        symbol="600000",
        asset_type="stock",
        price=10.0,
        quote_timestamp="2026-07-02T09:30:00+08:00",
        quote_source="deterministic_fixture",
        quote_status="confirmed",
        fetch_run_id="run-b",
    )
    second = candidate_market_evidence(db, tasks, now=now)

    assert first["bindings"][0]["quote_id"] == second["bindings"][0]["quote_id"]
    assert first["fingerprint"] != second["fingerprint"]
    assert (
        first["bindings"][0]["persisted_row_fingerprint"]
        != second["bindings"][0]["persisted_row_fingerprint"]
    )


def test_unrelated_malformed_quote_does_not_block_candidate(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _save_quote(db, symbol="600000", asset_type="stock", price=10.0)
    _save_quote(db, symbol="unrelated", asset_type="stock", price=20.0)
    with sqlite3.connect(db.path) as connection:
        connection.execute(
            "UPDATE latest_quotes SET quote_timestamp = ? WHERE symbol = ?",
            ("not-a-timestamp", "unrelated"),
        )

    evidence = candidate_market_evidence(
        db,
        [{"id": 1, "symbol": "600000", "asset_class": "stock"}],
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert evidence["source_status"] == "persisted_current_quotes"
    assert evidence["quotes"]["600000"]["price"] == 10.0


def test_binding_rejects_candidate_that_collides_with_account_instrument_type(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _save_quote(db, symbol="same-code", asset_type="fund", price=2.0)
    evidence = candidate_market_evidence(
        db,
        [{"id": 1, "symbol": "same-code", "asset_class": "fund"}],
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    account_quote = {
        "symbol": "same-code",
        "instrument_type": "stock",
        "asset_class": "stock",
        "price": 10.0,
        "quote_status": "confirmed",
    }

    context = bind_candidate_market_evidence(
        {
            "authority": "persisted_valuation_snapshot",
            "quotes": {"same-code": account_quote},
        },
        evidence,
    )

    assert context["quotes"] == {"same-code": account_quote}
    assert context["candidate_quotes"] == {}
    assert context["candidate_market_evidence"]["ambiguous_symbols"] == ["same-code"]
