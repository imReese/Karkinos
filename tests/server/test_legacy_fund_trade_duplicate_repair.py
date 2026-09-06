from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from server import legacy_fund_trade_duplicate_repair_cli as repair_cli
from server.ledger.models import LedgerEntry
from server.persistence.financial_facts_ledger import insert_ledger_entry_on_connection
from server.persistence.initializer import initialize_database
from server.projections.legacy_fund_trade_duplicate_correction import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    LegacyFundTradeDuplicateCorrectionError,
    legacy_fund_trade_duplicate_group_fingerprint,
    resolve_legacy_fund_trade_duplicate_exclusions,
)
from server.projections.service import build_portfolio_projection
from server.services.legacy_fund_trade_duplicate_repair import (
    LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION,
    LegacyFundTradeDuplicateRepairBlocked,
    LegacyFundTradeDuplicateRepairCommand,
    LegacyFundTradeDuplicateRepairService,
)

pytestmark = pytest.mark.unit

NOW = "2026-08-30T20:00:00+08:00"


def _fixture_database(
    path: Path,
    *,
    group_sizes: tuple[int, ...] = (5, 2, 2),
    asset_class: str = "fund",
    direction: str = "buy",
    live_offset_shape: bool = False,
    high_precision: bool = False,
) -> None:
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        for group_index, pair_count in enumerate(group_sizes, start=1):
            symbol = f"FIXTURE-{group_index}"
            for pair_index in range(1, pair_count + 1):
                timestamp = f"2026-04-{group_index * 7 + pair_index:02d}T13:22:58+08:00"
                created_at = timestamp
                quantity = (
                    float(pair_index) + 0.12345678901234567
                    if high_precision
                    else float(pair_index * 10)
                )
                price = (
                    float(group_index) + 0.9876543210987654
                    if high_precision
                    else float(group_index + 1)
                )
                commission = 0.0 if high_precision else float(group_index) / 10
                gross = quantity * price
                net = (
                    -(gross + commission) if direction == "buy" else gross - commission
                )
                note = "migration fixture"
                trade_id = int(
                    conn.execute(
                        """
                        INSERT INTO trades (
                            timestamp, symbol, direction, quantity, price,
                            commission, asset_class, note, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            timestamp,
                            symbol,
                            direction,
                            quantity,
                            price,
                            commission,
                            asset_class,
                            note,
                            created_at,
                        ),
                    ).lastrowid
                )
                insert_ledger_entry_on_connection(
                    conn,
                    entry_type=f"trade_{direction}",
                    timestamp=timestamp,
                    amount=gross,
                    symbol=symbol,
                    direction=direction,
                    quantity=quantity,
                    price=price,
                    commission=commission,
                    gross_amount=gross,
                    net_cash_impact=net,
                    fee_breakdown_json=json.dumps(
                        {
                            "commission": str(commission),
                            "subscription_fee": "0",
                        },
                        sort_keys=True,
                    ),
                    fee_rule_id="legacy_manual_input",
                    fee_rule_version="legacy_manual_input",
                    asset_class=asset_class,
                    note=note,
                    source="manual",
                    source_ref=None,
                    created_at=created_at,
                )
                canonical_id = insert_ledger_entry_on_connection(
                    conn,
                    entry_type=f"trade_{direction}",
                    timestamp=timestamp,
                    amount=gross,
                    symbol=symbol,
                    direction=direction,
                    quantity=quantity,
                    price=price,
                    commission=commission,
                    gross_amount=gross,
                    net_cash_impact=net,
                    fee_rule_id="legacy_manual_trade",
                    fee_rule_version="legacy_manual_trade",
                    cost_basis_method="moving_average_buy_cost",
                    asset_class=asset_class,
                    note=note,
                    source="portfolio_trade",
                    source_ref=f"trade:{trade_id}",
                    created_at=created_at,
                )
                if live_offset_shape:
                    conn.execute(
                        "UPDATE ledger_entries SET timestamp = ? WHERE id = ?",
                        (timestamp, canonical_id),
                    )
        conn.commit()


def _counts(path: Path) -> tuple[int, int, int]:
    with sqlite3.connect(path) as conn:
        return tuple(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("ledger_entries", "event_log", "trades")
        )


def _rows(path: Path) -> list[dict[str, object]]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM ledger_entries ORDER BY timestamp, id"
            ).fetchall()
        ]


def _writer(calls: list[list[dict[str, object]]]):
    def write(conn: sqlite3.Connection, **kwargs) -> dict[str, object]:
        candidates = [dict(row) for row in kwargs["candidate_ledger_rows"]]
        calls.append(candidates)
        assert conn.in_transaction
        return {"snapshot_id": "fixture-valuation", "status": "complete"}

    return write


def _command(preview: dict[str, object], *, command_id: str = "repair-1"):
    return LegacyFundTradeDuplicateRepairCommand(
        command_id=command_id,
        operator_id="fixture-owner",
        preview_fingerprint=str(preview["preview_fingerprint"]),
        confirmation=LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION,
    )


def test_correction_read_evidence_validates_references_and_page_identity(
    tmp_path, monkeypatch
):
    from server.projections.ledger_correction_read import correction_read_evidence

    path = tmp_path / "read-evidence.db"
    _fixture_database(path, group_sizes=(1,))
    service = LegacyFundTradeDuplicateRepairService(
        path, now=lambda: NOW, valuation_transaction_writer=_writer([])
    )
    service.apply(_command(service.preview()))
    rows = _rows(path)
    entry = next(
        LedgerEntry.from_row(r)
        for r in rows
        if r["entry_type"] == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
    )
    before = _counts(path)
    evidence = correction_read_evidence([entry], rows)[entry.id]
    assert evidence["status"] == "verified"
    assert {r["role"] for r in evidence["related_entries"]} == {"original", "retained"}
    assert _counts(path) == before
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import server.dependencies
    from server.db import AppDatabase
    from server.routes.ledger import create_router

    db = AppDatabase(path)
    monkeypatch.setattr(
        server.dependencies, "get_app_state", lambda: SimpleNamespace(db=db)
    )
    app = FastAPI()
    app.include_router(create_router())
    response = TestClient(app).get("/api/ledger/entries?limit=1")
    assert response.status_code == 200
    item = response.json()[0]
    assert item["id"] == entry.id
    assert item["correction_evidence"] == evidence
    assert item["correction_evidence"]["entry_fingerprint"] == item["entry_fingerprint"]
    assert _counts(path) == before
    assert _rows(path) == rows
    for mutation in ("missing", "schema", "payload", "page"):
        changed = json.loads(json.dumps(rows))
        if mutation == "missing":
            changed = [r for r in changed if r["id"] != 1]
        else:
            row = next(r for r in changed if r["id"] == entry.id)
            payload = json.loads(row["correction_payload_json"])
            if mutation == "schema":
                payload["schema_version"] = "unknown"
            elif mutation == "payload":
                payload["position_after"]["quantity"] = "999"
            else:
                row["note"] = "changed after page read"
            row["correction_payload_json"] = json.dumps(payload)
        result = correction_read_evidence([entry], changed)[entry.id]
        assert result["status"] == "unverified"
        assert result["blockers"]
        assert result["related_entries"] == []


def test_daily_history_characterizes_tail_correction_without_restating_facts(tmp_path):
    from server.projections.portfolio_views.historical_ledger_series import (
        build_daily_equity_series_from_ledger_history,
    )
    from server.projections.portfolio_views.historical_series import (
        historical_performance_from_series,
    )

    path = tmp_path / "history.db"
    _fixture_database(path, group_sizes=(1,))
    with sqlite3.connect(path) as conn:
        for kind, timestamp, amount in [
            ("cash_deposit", "2026-04-07T09:00:00+08:00", 100),
            ("cash_interest", "2026-04-10T09:00:00+08:00", 0),
        ]:
            insert_ledger_entry_on_connection(
                conn,
                entry_type=kind,
                timestamp=timestamp,
                amount=amount,
                asset_class="cash",
                source="manual",
                created_at=timestamp,
            )
    service = LegacyFundTradeDuplicateRepairService(
        path, now=lambda: NOW, valuation_transaction_writer=_writer([])
    )
    service.apply(_command(service.preview()))
    with sqlite3.connect(path) as conn:
        insert_ledger_entry_on_connection(
            conn,
            entry_type="cash_deposit",
            timestamp="2026-04-13T09:00:00+08:00",
            amount=10,
            asset_class="cash",
            source="manual",
            created_at=NOW,
        )
        insert_ledger_entry_on_connection(
            conn,
            entry_type="trade_buy",
            timestamp="2026-04-14T09:00:00+08:00",
            amount=3,
            quantity=1,
            price=3,
            direction="buy",
            symbol="FIXTURE-1",
            asset_class="fund",
            commission=0,
            source="manual",
            created_at=NOW,
        )
    rows = _rows(path)
    correction = next(
        r
        for r in rows
        if r["entry_type"] == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
    )
    assert correction["created_at"] == NOW
    assert correction["timestamp"] == "2026-04-10T01:00:01+00:00"
    original_ids = set(
        json.loads(correction["correction_payload_json"])["original_ledger_entry_ids"]
    )
    # Test-only restatement is a counterfactual, never a production write policy.
    restated = [
        r for r in rows if r["id"] not in original_ids and r["id"] != correction["id"]
    ]
    before = json.dumps(rows, sort_keys=True)

    def history(facts):
        prices = [
            {
                "timestamp": f"2026-04-{day:02d}T15:00:00+08:00",
                "price": price,
                "asset_class": "fund",
                "instrument_type": "open_end_fund",
            }
            for day, price in [(8, 2), (9, 3), (10, 3), (13, 3), (14, 3)]
        ]
        state = SimpleNamespace(
            db=SimpleNamespace(
                get_all_ledger_entries_sync=lambda: facts,
                get_ledger_entries_sync=lambda **_: facts,
                get_historical_price_matrix_sync=lambda **_: {"FIXTURE-1": prices},
            ),
            scheduler=None,
        )
        points = build_daily_equity_series_from_ledger_history(
            state,
            selected_range="all",
            current_point=None,
            now=datetime.fromisoformat("2026-04-14T16:00:00+08:00"),
        )
        return points, historical_performance_from_series(
            state, points, valuation_snapshot_id=None
        )

    actual, adjusted = history(rows)
    reference, _ = history(restated)
    assert [p.total for p in actual] == pytest.approx(
        [100, 99.8, 119.8, 109.9, 119.9, 119.9]
    )
    assert [p.total for p in reference] == pytest.approx(
        [100, 99.9, 109.9, 109.9, 119.9, 119.9]
    )
    assert actual[-1].total == reference[-1].total
    # A valid correction and matching final balance do not prove historical returns.
    assert actual[3].total < actual[2].total
    assert adjusted.equity_curve == []
    assert adjusted.blockers == ["historical_correction_performance_unverified"]
    assert resolve_legacy_fund_trade_duplicate_exclusions(rows).valid
    assert json.dumps(_rows(path), sort_keys=True) == before


@pytest.mark.parametrize("price_gap", [False, True])
def test_correction_performance_is_blocked_in_bound_snapshot_http_reads(
    tmp_path, monkeypatch, price_gap
):
    import socket

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.config import ServerConfig
    from server.db import AppDatabase
    from server.dependencies import AppState, AppStateContextMiddleware
    from server.routes import portfolio

    path = tmp_path / "bound-history.db"
    _fixture_database(path, group_sizes=(1,))
    db = AppDatabase(path)
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-04-07T09:00:00+08:00",
        amount=100,
        asset_class="cash",
    )
    db.insert_ledger_entry_sync(
        entry_type="cash_interest",
        timestamp="2026-04-10T09:00:00+08:00",
        amount=0.1,
        asset_class="cash",
    )
    service = LegacyFundTradeDuplicateRepairService(
        path, now=lambda: NOW, valuation_transaction_writer=_writer([])
    )
    service.apply(_command(service.preview()))
    for day, price in [(8, 2), (9, 3), (10, 3)]:
        if price_gap and day == 9:
            continue
        db.save_quote_snapshot_sync(
            symbol="FIXTURE-1",
            asset_class="fund",
            price=price,
            volume=None,
            timestamp=f"2026-04-{day:02d}T15:00:00+08:00",
            nav_date=f"2026-04-{day:02d}",
            quote_status="confirmed",
            quote_source="synthetic_history",
            provider_name="fixture",
        )
    now = datetime.fromisoformat("2026-04-10T16:00:00+08:00")
    valuation = db.publish_current_valuation_snapshot_sync(now=now)
    assert valuation["status"] == "complete"
    assert resolve_legacy_fund_trade_duplicate_exclusions(_rows(path)).valid
    state = AppState()
    state.db = db
    state.config = ServerConfig(assets=[{"symbol": "FIXTURE-1", "asset_class": "fund"}])
    monkeypatch.setattr(portfolio, "get_shanghai_now", lambda: now)
    reads = []
    original_read = db.get_all_ledger_entries_sync

    def read_ledger():
        reads.append(1)
        return original_read()

    def fail(*args, **kwargs):
        raise AssertionError("unbound ledger read or provider connection")

    monkeypatch.setattr(db, "get_all_ledger_entries_sync", read_ledger)
    monkeypatch.setattr(db, "get_ledger_entries_sync", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(portfolio.create_router())
    # Finish setup WAL publication before measuring read-only requests.
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = path.read_bytes()
    with TestClient(app) as client:
        series_response = client.get("/api/portfolio/equity-curve/series?range=all")
        overview_response = client.get("/api/portfolio/overview")
        risk_response = client.get("/api/portfolio/risk-workspace")
    for response in (series_response, overview_response, risk_response):
        assert response.status_code == 200, response.text
    series = series_response.json()
    assert any(point["total"] is None for point in series) == price_gap
    assert series[-1]["valuation_snapshot_id"] == valuation["snapshot_id"]
    overview = overview_response.json()
    risk = risk_response.json()
    expected = ["historical_correction_performance_unverified"]
    if price_gap:
        expected.insert(0, "drawdown_history_unavailable")
    assert overview["valuation_snapshot_id"] == valuation["snapshot_id"]
    assert overview["ledger_cutoff_id"] == valuation["ledger_cutoff_id"]
    assert overview["current_drawdown"] is None
    assert overview["drawdown_peak_equity"] is None
    assert overview["drawdown_blockers"] == expected
    assert overview["total_equity"] == pytest.approx(110)
    assert risk["status"] == "partial"
    assert risk["blockers"] == expected
    assert risk["drawdown"] is None
    assert risk["drawdown_series"] == []
    assert risk["exposure_buckets"]
    assert risk["concentration"][0]["market_value"] == 30
    assert len(reads) == 1
    assert path.read_bytes() == before


def test_preview_is_zero_write_private_and_finds_generic_live_shape(tmp_path) -> None:
    path = tmp_path / "repair-preview.db"
    _fixture_database(path)
    before = _counts(path)

    report = LegacyFundTradeDuplicateRepairService(path).preview()

    assert report["status"] == "ready"
    assert report["pair_count"] == 9
    assert report["affected_fund_count"] == 3
    assert report["group_pair_counts"] == [5, 2, 2]
    assert report["database_writes_performed"] is False
    assert report["provider_contact_performed"] is False
    assert _counts(path) == before
    encoded = json.dumps(report)
    assert "FIXTURE-" not in encoded
    assert "fixture-owner" not in encoded


def test_apply_appends_one_correction_per_fund_and_is_exactly_idempotent(
    tmp_path,
) -> None:
    path = tmp_path / "repair-apply.db"
    _fixture_database(path)
    calls: list[list[dict[str, object]]] = []
    service = LegacyFundTradeDuplicateRepairService(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_writer(calls),
    )
    preview = service.preview()
    originals_before = [
        row for row in _rows(path) if row["source"] in {"manual", "portfolio_trade"}
    ]

    result = service.apply(_command(preview))

    assert result.status == "applied"
    assert result.correction_count == 3
    assert result.pair_count == 9
    assert len(calls) == 1 and len(calls[0]) == 3
    rows = _rows(path)
    assert [
        row for row in rows if row["source"] in {"manual", "portfolio_trade"}
    ] == originals_before
    corrections = [
        row
        for row in rows
        if row["source"] == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
    ]
    assert len(corrections) == 3
    assert {row["entry_type"] for row in corrections} == {
        LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
    }
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(rows)
    assert resolution.valid
    assert len(resolution.excluded_manual_entry_ids) == 9

    counts_after = _counts(path)
    replay = service.apply(_command(preview))
    assert replay.status == "already_applied"
    assert replay.replayed is True
    assert _counts(path) == counts_after
    with pytest.raises(
        LegacyFundTradeDuplicateRepairBlocked,
        match="existing_correction",
    ):
        service.apply(_command(preview, command_id="another-command"))
    assert _counts(path) == counts_after


@pytest.mark.parametrize("group_sizes", ((1, 1), (5, 2, 2)))
def test_apply_orders_live_shaped_plus08_rows_by_instant(
    tmp_path,
    group_sizes: tuple[int, ...],
) -> None:
    path = tmp_path / "repair-live-offset.db"
    _fixture_database(
        path,
        group_sizes=group_sizes,
        live_offset_shape=True,
        high_precision=True,
    )
    service = LegacyFundTradeDuplicateRepairService(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_writer([]),
    )
    preview = service.preview()

    assert preview["status"] == "ready"
    result = service.apply(_command(preview))
    assert result.status == "applied"
    rows = _rows(path)
    assert resolve_legacy_fund_trade_duplicate_exclusions(rows).valid
    payloads = [
        json.loads(str(row["correction_payload_json"]))
        for row in sorted(rows, key=lambda item: int(item["id"]))
        if row["source"] == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
    ]
    assert all(
        payload["cash_allocation"] == "ordered_batch_absolute_cash_state_v1"
        for payload in payloads
    )
    assert all(
        left["cash_after"] == right["cash_before"]
        for left, right in zip(payloads, payloads[1:], strict=False)
    )


def test_default_writer_publishes_valuation_in_same_database(tmp_path) -> None:
    path = tmp_path / "repair-default-writer.db"
    _fixture_database(path, group_sizes=(1,), live_offset_shape=True)
    service = LegacyFundTradeDuplicateRepairService(path, now=lambda: NOW)
    preview = service.preview()

    result = service.apply(_command(preview))

    assert result.status == "applied"
    assert result.valuation_snapshot_id
    with sqlite3.connect(path) as conn:
        persisted = conn.execute(
            "SELECT status FROM valuation_snapshots WHERE snapshot_id = ?",
            (result.valuation_snapshot_id,),
        ).fetchone()
    assert persisted is not None


def test_apply_requires_exact_confirmation_and_current_preview(tmp_path) -> None:
    path = tmp_path / "repair-confirmation.db"
    _fixture_database(path)
    service = LegacyFundTradeDuplicateRepairService(
        path,
        valuation_transaction_writer=_writer([]),
    )
    preview = service.preview()
    before = _counts(path)
    bad = LegacyFundTradeDuplicateRepairCommand(
        command_id="repair-1",
        operator_id="fixture-owner",
        preview_fingerprint=str(preview["preview_fingerprint"]),
        confirmation="yes",
    )
    with pytest.raises(ValueError, match="exact repair confirmation"):
        service.apply(bad)
    assert _counts(path) == before

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE ledger_entries SET amount = amount + 0.000000001 "
            "WHERE source = 'manual' AND id = ("
            "SELECT min(id) FROM ledger_entries WHERE source = 'manual')"
        )
        conn.commit()
    with pytest.raises(
        LegacyFundTradeDuplicateRepairBlocked,
        match="economic_pair_drifted",
    ):
        service.apply(_command(preview))


def test_stock_pairs_and_ambiguous_pairs_fail_closed(tmp_path) -> None:
    stock_path = tmp_path / "stock.db"
    _fixture_database(stock_path, group_sizes=(1,), asset_class="stock")
    stock = LegacyFundTradeDuplicateRepairService(stock_path).preview()
    assert stock["status"] == "blocked"
    assert "legacy_fund_trade_duplicate_stock_pair_detected" in stock["blockers"]

    ambiguous_path = tmp_path / "ambiguous.db"
    _fixture_database(ambiguous_path, group_sizes=(1,))
    with sqlite3.connect(ambiguous_path) as conn:
        row = conn.execute(
            "SELECT * FROM ledger_entries WHERE source = 'manual' LIMIT 1"
        ).fetchone()
        columns = [
            item[1] for item in conn.execute("PRAGMA table_info(ledger_entries)")
        ]
        values = dict(zip(columns, row, strict=True))
        values.pop("id")
        names = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO ledger_entries ({names}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        conn.commit()
    ambiguous = LegacyFundTradeDuplicateRepairService(ambiguous_path).preview()
    assert ambiguous["status"] == "blocked"
    assert "legacy_fund_trade_duplicate_pair_ambiguous" in ambiguous["blockers"]


def test_group_fingerprint_rejects_canonical_id_reuse(tmp_path) -> None:
    path = tmp_path / "canonical-reuse.db"
    _fixture_database(path, group_sizes=(2,))
    rows = _rows(path)
    manual_ids = [int(row["id"]) for row in rows if row["source"] == "manual"]
    canonical_id = next(
        int(row["id"]) for row in rows if row["source"] == "portfolio_trade"
    )

    with pytest.raises(
        LegacyFundTradeDuplicateCorrectionError,
        match="canonical_scope_overlapped",
    ):
        legacy_fund_trade_duplicate_group_fingerprint(
            ledger_rows=rows,
            pair_entry_ids=(
                (manual_ids[0], canonical_id),
                (manual_ids[1], canonical_id),
            ),
        )


def test_failure_after_first_append_rolls_back_entire_batch(tmp_path) -> None:
    path = tmp_path / "repair-rollback.db"
    _fixture_database(path)
    before = _counts(path)
    calls: list[list[dict[str, object]]] = []

    def fail(stage: str) -> None:
        if stage == "after_correction_entry_1":
            raise RuntimeError("injected")

    service = LegacyFundTradeDuplicateRepairService(
        path,
        valuation_transaction_writer=_writer(calls),
        failure_injector=fail,
    )
    preview = service.preview()
    with pytest.raises(RuntimeError, match="injected"):
        service.apply(_command(preview))
    assert _counts(path) == before
    assert calls == []


def test_resolver_uses_repair_cutoff_and_rejects_pre_cutoff_tampering(
    tmp_path,
) -> None:
    path = tmp_path / "repair-cutoff.db"
    _fixture_database(path, group_sizes=(2,))
    service = LegacyFundTradeDuplicateRepairService(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_writer([]),
    )
    preview = service.preview()
    service.apply(_command(preview))

    # A normal later fact is outside the repair-time cutoff and must not revoke
    # the already-validated historical repair.
    with sqlite3.connect(path) as conn:
        insert_ledger_entry_on_connection(
            conn,
            entry_type="cash_deposit",
            timestamp="2026-09-01T09:00:00+08:00",
            amount=100.0,
            asset_class="cash",
            source="manual",
            source_ref="later-cash",
            created_at="2026-09-01T09:00:00+08:00",
        )
        insert_ledger_entry_on_connection(
            conn,
            entry_type="trade_buy",
            timestamp="2026-09-02T09:00:00+08:00",
            amount=3.0,
            symbol="LATER-STOCK",
            direction="buy",
            quantity=1.0,
            price=3.0,
            commission=0.0,
            gross_amount=3.0,
            net_cash_impact=-3.0,
            asset_class="stock",
            source="manual",
            source_ref="later-stock",
            created_at="2026-09-02T09:00:00+08:00",
        )
        insert_ledger_entry_on_connection(
            conn,
            entry_type="trade_buy",
            timestamp="2026-09-03T09:00:00+08:00",
            amount=4.0,
            symbol="FIXTURE-1",
            direction="buy",
            quantity=1.0,
            price=4.0,
            commission=0.0,
            gross_amount=4.0,
            net_cash_impact=-4.0,
            asset_class="fund",
            source="manual",
            source_ref="later-fund",
            created_at="2026-09-03T09:00:00+08:00",
        )
        conn.commit()
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(_rows(path))
    assert resolution.valid
    assert len(resolution.excluded_manual_entry_ids) == 2
    build_portfolio_projection([LedgerEntry.from_row(row) for row in _rows(path)])

    # A post-cutoff row backfilled before the correction remains outside the
    # historical fingerprint, but protected projection replay rejects its
    # changed position-before state.
    with sqlite3.connect(path) as conn:
        insert_ledger_entry_on_connection(
            conn,
            entry_type="trade_buy",
            timestamp="2026-04-08T06:00:00+00:00",
            amount=1.0,
            symbol="FIXTURE-1",
            direction="buy",
            quantity=1.0,
            price=1.0,
            commission=0.0,
            gross_amount=1.0,
            net_cash_impact=-1.0,
            asset_class="fund",
            source="manual",
            source_ref="backfilled-fund",
            created_at="2026-09-04T09:00:00+08:00",
        )
        conn.commit()
    assert resolve_legacy_fund_trade_duplicate_exclusions(_rows(path)).valid
    with pytest.raises(ValueError, match="position evidence drifted"):
        build_portfolio_projection([LedgerEntry.from_row(row) for row in _rows(path)])

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE ledger_entries SET note = 'tampered' "
            "WHERE id = (SELECT min(id) FROM ledger_entries)"
        )
        conn.commit()
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(_rows(path))
    assert not resolution.valid
    assert not resolution.excluded_manual_entry_ids


def test_resolver_rejects_tampered_fingerprint_and_returns_no_exclusions(
    tmp_path,
) -> None:
    path = tmp_path / "repair-tamper.db"
    _fixture_database(path, group_sizes=(1,))
    service = LegacyFundTradeDuplicateRepairService(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_writer([]),
    )
    preview = service.preview()
    service.apply(_command(preview))
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT id, correction_payload_json FROM ledger_entries WHERE source = ?",
            (LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,),
        ).fetchone()
        payload = json.loads(row[1])
        payload["repair_fingerprint"] = "a" * 64
        conn.execute(
            "UPDATE ledger_entries SET correction_payload_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True), row[0]),
        )
        conn.commit()
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(_rows(path))
    assert not resolution.valid
    assert not resolution.excluded_manual_entry_ids


def test_cli_defaults_to_read_only_preview(tmp_path) -> None:
    path = tmp_path / "repair-cli.db"
    _fixture_database(path, group_sizes=(2,))
    before = _counts(path)
    output = io.StringIO()

    code = repair_cli.main(
        ["--database", str(path)],
        stdout=output,
    )

    report = json.loads(output.getvalue())
    assert code == 0
    assert report["status"] == "ready"
    assert report["database_writes_performed"] is False
    assert _counts(path) == before
