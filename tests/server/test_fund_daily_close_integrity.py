from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from domain.instrument import make_open_end_fund
from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.persistence.database_normalization import stable_json_fingerprint
from server.persistence.financial_facts_quote_ingestion_uow import (
    DailyCloseEvidenceConflict,
)
from server.persistence.valuation_publication_recovery import unresolved_publications
from server.services.market.fund_nav import refresh_fund_nav_quotes
from server.services.market.quotes import (
    build_quote_ingestion_command,
    persist_quote_ingestion,
)

SH_TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
def isolated_rotation_data(monkeypatch, tmp_path):
    from server.services.market.etf_rotation_automation import (
        EtfRotationAutomationService,
    )

    monkeypatch.setattr(
        EtfRotationAutomationService,
        "default_data_dir",
        tmp_path.resolve() / "rotation-data",
    )


def _db(tmp_path: Path, name: str = "app.db") -> AppDatabase:
    db = AppDatabase(tmp_path.resolve() / name)
    db.init_sync()
    return db


def _daily_closes(db: AppDatabase, symbol: str) -> list[tuple[str, str, float, str]]:
    with sqlite3.connect(db.path) as conn:
        rows = conn.execute(
            """
            SELECT instrument_type, trade_date, close_price, source
            FROM daily_close_snapshots_v2
            WHERE symbol = ?
            ORDER BY trade_date ASC, id ASC
            """,
            (symbol,),
        ).fetchall()
    return [(str(r[0]), str(r[1]), float(r[2]), str(r[3])) for r in rows]


def _run_scheduler_fund_poll(
    monkeypatch,
    db: AppDatabase,
    *,
    symbol: str,
    event_ts: datetime,
    price: float,
    snapshot: dict,
    now: datetime,
) -> dict:
    from server import scheduler as scheduler_module

    watchlist = [(Symbol(symbol), AssetClass.FUND)]
    instruments = {Symbol(symbol): make_open_end_fund(Symbol(symbol), name="测试基金")}
    event = replace(
        MarketEvent(
            timestamp=event_ts,
            symbol=Symbol(symbol),
            open=Decimal(str(price)),
            high=Decimal(str(price)),
            low=Decimal(str(price)),
            close=Decimal(str(price)),
            volume=Decimal("0"),
            frequency=BarFrequency.DAILY,
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.OPEN_END_FUND,
        )
    )

    class _FakeStrategy:
        def on_init(self, symbols) -> None:
            self.symbols = list(symbols)

        def on_data(self, _event) -> None:
            pass

    class _FakeBridge:
        def rebind(self, _bus) -> None:
            pass

    class _FakeLiveFeed:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def poll_all(self, current_watchlist):
            assert current_watchlist == watchlist
            return [event]

        def get_last_snapshot(self, req_symbol, asset_class=AssetClass.STOCK):
            return dict(snapshot)

        def close(self) -> None:
            pass

    runtime = SimpleNamespace(
        sources={"akshare": object(), "sina": object(), "tushare": object()},
        watchlist=watchlist,
        instruments=instruments,
        data_manager=SimpleNamespace(),
    )
    config = SimpleNamespace(
        data_source="akshare",
        live_poll_interval=60,
        initial_cash=Decimal("100000"),
        start_date="2026-01-01",
    )
    monkeypatch.setattr(scheduler_module, "create_runtime_context", lambda _c: runtime)
    monkeypatch.setattr(
        scheduler_module, "build_strategy", lambda _c, _b: _FakeStrategy()
    )
    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_warmup_strategy",
        lambda self, _dm, _st: None,
    )
    monkeypatch.setattr(scheduler_module, "scheduler_now", lambda: now)
    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_is_market_open",
        staticmethod(lambda: True),
    )
    monkeypatch.setattr(scheduler_module, "LiveDataFeed", _FakeLiveFeed)
    from server.scheduler import post_close as scheduler_post_close

    monkeypatch.setattr(
        scheduler_post_close,
        "refresh_fund_nav_quotes",
        lambda *_a, **_kw: SimpleNamespace(
            refreshed=[], skipped=[], failed={}, quotes={}
        ),
    )
    sched = scheduler_module.TradingScheduler(config, _FakeBridge(), db=db)
    sched.wait_for_scheduler_stop = lambda timeout=None: sched._running.clear()
    sched._running.set()
    sched._run_loop()
    return db.list_quote_fetch_runs(trigger="scheduler_poll")[0]


def test_build_quote_ingestion_command_blocks_estimate_prev_close_and_keeps_audit() -> (
    None
):
    cmd = build_quote_ingestion_command(
        symbol="012710",
        asset_type="open_end_fund",
        snapshot={
            "price": 1.79,
            "volume": None,
            "timestamp": "2026-11-27T10:30:00+08:00",
            "previous_close": 1.77,
            "previous_close_date": "2026-11-26",
            "source": "sina",
            "quote_source": "sina_fund_estimate",
        },
        quote_source="sina_fund_estimate",
        provider_name="sina",
        provider_status="live",
        quote_status="estimated",
        captured_reason="fund_nav_sync",
        fetch_run_id="run-audit-1",
        captured_at="2026-11-27T10:30:02+08:00",
        nav_date="2026-11-26",
    )
    assert cmd.price == 1.79
    assert cmd.previous_close == 1.77
    assert cmd.previous_close_date == "2026-11-26"
    assert cmd.quote_source == "sina_fund_estimate"
    assert cmd.daily_close_price is None
    assert cmd.daily_close_date is None
    assert cmd.daily_close_source is None


@pytest.mark.parametrize(
    "official_price", [1.8028, 1.77], ids=["diff-price", "same-price"]
)
@pytest.mark.parametrize(
    "order",
    ["estimate_then_official", "official_then_estimate"],
)
def test_fund_refresh_estimate_and_official_close_all_orders_and_prices(
    monkeypatch,
    tmp_path: Path,
    official_price: float,
    order: str,
) -> None:
    db = _db(tmp_path)
    symbol = "012710"
    watchlist = [(Symbol(symbol), InstrumentType.OPEN_END_FUND)]
    config = SimpleNamespace(data_source="akshare", tushare_token="")

    def run_estimate() -> None:
        class _EstimateSource:
            def fetch_latest(self, _sym, _ac):
                return {
                    "price": 1.79,
                    "volume": None,
                    "timestamp": "2026-11-27T10:30:00+08:00",
                    "previous_close": 1.77,
                    "previous_close_date": "2026-11-26",
                    "source": "sina",
                    "quote_source": "sina_fund_estimate",
                    "provider_name": "sina",
                    "quote_status": "estimated",
                    "nav_date": "2026-11-26",
                }

        monkeypatch.setattr(
            "server.services.market.fund_nav.build_sources",
            lambda **_kw: {"akshare": _EstimateSource()},
        )
        res = refresh_fund_nav_quotes(
            config,
            db,
            watchlist,
            {},
            now=datetime(2026, 11, 27, 10, 30, tzinfo=SH_TZ),
            ttl_seconds=0,
        )
        assert res.refreshed == [symbol]
        assert res.failed == {}

    def run_official() -> None:
        class _OfficialSource:
            def fetch_latest(self, _sym, _ac):
                return {
                    "price": official_price,
                    "volume": None,
                    "timestamp": "2026-11-26T15:00:00+08:00",
                    "nav_date": "2026-11-26",
                    "source": "akshare",
                    "quote_source": "eastmoney_fund_page",
                    "provider_name": "akshare",
                    "quote_status": "confirmed",
                }

            def fetch_confirmed_fund_nav(self, sym):
                return self.fetch_latest(sym, AssetClass.FUND)

        monkeypatch.setattr(
            "server.services.market.fund_nav.build_sources",
            lambda **_kw: {"akshare": _OfficialSource()},
        )
        res = refresh_fund_nav_quotes(
            config,
            db,
            watchlist,
            {},
            now=datetime(2026, 11, 27, 11, 0, tzinfo=SH_TZ)
            if order == "estimate_then_official"
            else datetime(2026, 11, 26, 20, 30, tzinfo=SH_TZ),
            ttl_seconds=0,
            confirmation_only=True,
            target_date="2026-11-26",
        )
        assert res.refreshed == [symbol]
        assert res.failed == {}

    if order == "estimate_then_official":
        run_estimate()
        assert _daily_closes(db, symbol) == []
        run_official()
    else:
        run_official()
        assert _daily_closes(db, symbol) == [
            ("open_end_fund", "2026-11-26", official_price, "eastmoney_fund_page")
        ]
        run_estimate()

    assert _daily_closes(db, symbol) == [
        ("open_end_fund", "2026-11-26", official_price, "eastmoney_fund_page")
    ]
    snaps = db.get_recent_quote_snapshots_sync(
        symbol, limit=10, instrument_type="open_end_fund"
    )
    assert len(snaps) == 2
    est_snap = next(s for s in snaps if s["quote_source"] == "sina_fund_estimate")
    assert est_snap["price"] == 1.79
    assert est_snap["quote_status"] == "estimated"
    assert est_snap["timestamp"] == "2026-11-27T10:30:00+08:00"
    with sqlite3.connect(db.path) as conn:
        conn.row_factory = sqlite3.Row
        item_row = conn.execute(
            "SELECT payload_json FROM quote_ingestion_items WHERE payload_json LIKE '%sina_fund_estimate%' LIMIT 1"
        ).fetchone()
    assert item_row is not None
    est_cmd = json.loads(item_row["payload_json"])
    assert est_cmd["previous_close"] == 1.77
    assert est_cmd["previous_close_date"] == "2026-11-26"


@pytest.mark.parametrize(
    "official_price", [1.8028, 1.77], ids=["diff-price", "same-price"]
)
@pytest.mark.parametrize(
    "order",
    ["estimate_then_official", "official_then_estimate"],
)
def test_scheduler_poll_estimate_never_writes_reported_or_afternoon_close(
    monkeypatch,
    tmp_path: Path,
    official_price: float,
    order: str,
) -> None:
    db = _db(tmp_path)
    symbol = "012710"

    def poll_post_close_estimate(day: str, prev_day: str) -> None:
        run = _run_scheduler_fund_poll(
            monkeypatch,
            db,
            symbol=symbol,
            event_ts=datetime.fromisoformat(f"{day}T15:02:00+08:00"),
            price=1.79,
            snapshot={
                "timestamp": f"{day}T15:02:00+08:00",
                "previous_close": 1.77,
                "previous_close_date": prev_day,
                "source": "sina",
                "quote_source": "sina_fund_estimate",
                "provider_name": "sina",
                "quote_status": "estimated",
                "nav_date": prev_day,
            },
            now=datetime.fromisoformat(f"{day}T15:02:05+08:00"),
        )
        assert run["status"] == "success"

    def poll_same_day_official() -> None:
        run = _run_scheduler_fund_poll(
            monkeypatch,
            db,
            symbol=symbol,
            event_ts=datetime.fromisoformat("2026-11-26T15:00:00+08:00"),
            price=official_price,
            snapshot={
                "timestamp": "2026-11-26T15:00:00+08:00",
                "nav_date": "2026-11-26",
                "source": "akshare",
                "quote_source": "eastmoney_fund_page",
                "provider_name": "akshare",
                "quote_status": "confirmed",
            },
            now=datetime.fromisoformat("2026-11-26T15:03:00+08:00"),
        )
        assert run["status"] == "success"

    if order == "estimate_then_official":
        poll_post_close_estimate("2026-11-26", "2026-11-25")
        assert _daily_closes(db, symbol) == []
        poll_same_day_official()
    else:
        poll_same_day_official()
        assert _daily_closes(db, symbol) == [
            ("open_end_fund", "2026-11-26", official_price, "eastmoney_fund_page")
        ]
        poll_post_close_estimate("2026-11-27", "2026-11-26")

    assert _daily_closes(db, symbol) == [
        ("open_end_fund", "2026-11-26", official_price, "eastmoney_fund_page")
    ]
    latest = db.get_latest_quote_sync(symbol, asset_type="open_end_fund")
    assert latest is not None
    if order == "official_then_estimate":
        assert latest["quote_source"] == "sina_fund_estimate"
        assert latest["previous_close"] == 1.77
        assert (
            json.loads(latest["metadata_json"])["previous_close_date"] == "2026-11-26"
        )


def test_two_official_sources_corroborate_same_price_and_reject_conflict(
    monkeypatch, tmp_path: Path
) -> None:
    db = _db(tmp_path)
    symbol = "018125"
    watchlist = [(Symbol(symbol), InstrumentType.OPEN_END_FUND)]
    config = SimpleNamespace(data_source="akshare", tushare_token="token")

    em_cmd = build_quote_ingestion_command(
        symbol=symbol,
        asset_type="open_end_fund",
        snapshot={
            "price": 1.8028,
            "volume": 0.0,
            "timestamp": "2026-11-26T15:00:00+08:00",
        },
        quote_source="eastmoney_fund_page",
        provider_name="akshare",
        provider_status="live",
        quote_status="confirmed",
        captured_reason="fund_nav_sync",
        fetch_run_id=None,
        captured_at="2026-11-26T20:00:00+08:00",
        nav_date="2026-11-26",
    )
    persist_quote_ingestion(db, em_cmd)
    assert _daily_closes(db, symbol) == [
        ("open_end_fund", "2026-11-26", 1.8028, "eastmoney_fund_page")
    ]

    # Second official source with SAME price (1.8028) corroborates cleanly.
    ts_same = build_quote_ingestion_command(
        symbol=symbol,
        asset_type="open_end_fund",
        snapshot={
            "price": 1.8028,
            "volume": 0.0,
            "timestamp": "2026-11-26T15:00:00+08:00",
        },
        quote_source="tushare_fund_nav",
        provider_name="tushare",
        provider_status="live",
        quote_status="confirmed",
        captured_reason="fund_nav_sync",
        fetch_run_id=None,
        captured_at="2026-11-26T20:05:00+08:00",
        nav_date="2026-11-26",
    )
    persist_quote_ingestion(db, ts_same)
    assert _daily_closes(db, symbol) == [
        ("open_end_fund", "2026-11-26", 1.8028, "eastmoney_fund_page")
    ]

    # Conflicting official source with DIFFERENT price (1.8150) fails closed.
    ts_conflict = build_quote_ingestion_command(
        symbol=symbol,
        asset_type="open_end_fund",
        snapshot={
            "price": 1.8150,
            "volume": 0.0,
            "timestamp": "2026-11-26T15:00:00+08:00",
        },
        quote_source="tushare_fund_nav",
        provider_name="tushare",
        provider_status="live",
        quote_status="confirmed",
        captured_reason="fund_nav_sync",
        fetch_run_id=None,
        captured_at="2026-11-26T20:10:00+08:00",
        nav_date="2026-11-26",
    )
    with pytest.raises((ValueError, DailyCloseEvidenceConflict)):
        persist_quote_ingestion(db, ts_conflict)

    class _ConflictingTushare:
        def fetch_latest(self, _sym, _ac):
            return {
                "price": 1.8150,
                "volume": 0.0,
                "timestamp": "2026-11-26T15:00:00+08:00",
                "nav_date": "2026-11-26",
                "source": "tushare",
                "quote_source": "tushare_fund_nav",
                "provider_name": "tushare",
                "quote_status": "confirmed",
            }

    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kw: {"tushare": _ConflictingTushare()},
    )
    conflict_run = refresh_fund_nav_quotes(
        config,
        db,
        watchlist,
        {},
        now=datetime(2026, 11, 26, 20, 15, tzinfo=SH_TZ),
        ttl_seconds=0,
    )
    assert conflict_run.refreshed == []
    assert "__publication__" in conflict_run.failed
    with sqlite3.connect(db.path) as conn:
        assert len(unresolved_publications(conn)) == 1
    assert _daily_closes(db, symbol) == [
        ("open_end_fund", "2026-11-26", 1.8028, "eastmoney_fund_page")
    ]


def _start_fund_run(db, run_id, symbols):
    scope = {
        "requested_symbols": symbols,
        "instrument_types": ["open_end_fund"] * len(symbols),
    }
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at="2026-11-26T18:00:00+08:00",
        trigger="fund_nav_sync",
        provider="akshare",
        asset_type="open_end_fund",
        symbol_count=len(symbols),
        status="running",
        metadata=scope,
    )
    return scope


def _finish_fund_run(db, run_id, scope):
    return db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-11-26T18:01:00+08:00",
        status="success",
        success_count=len(scope["requested_symbols"]),
        failure_count=0,
        metadata=scope,
    )


def _official_command(symbol, run_id=None):
    return QuoteIngestionCommand(
        symbol=symbol,
        asset_type="open_end_fund",
        price=1.8028,
        quote_timestamp="2026-11-25T15:00:00+08:00",
        captured_at="2026-11-26T18:00:00+08:00",
        quote_source="eastmoney_fund_page",
        provider_name="akshare",
        provider_status="live",
        quote_status="confirmed",
        nav_date="2026-11-25",
        fetch_run_id=run_id,
        daily_close_date="2026-11-25",
        daily_close_price=1.8028,
        daily_close_source="eastmoney_fund_page",
    )


def test_staged_estimate_keeps_raw_previous_close_and_cannot_publish_it(tmp_path):
    db = _db(tmp_path)
    run_id = "previous-version-scheduler"
    symbol = "012710"
    scope = _start_fund_run(db, run_id, [symbol])
    command = replace(
        _official_command(symbol, run_id),
        quote_source="sina_fund_estimate",
        quote_status="estimated",
        provider_name="sina",
        quote_timestamp="2026-11-26T10:30:00+08:00",
        price=1.8,
        previous_close=1.77,
        previous_close_date="2026-11-25",
        daily_close_source="reported_previous_close",
        daily_close_price=1.77,
    )
    db.persist_quote_ingestion_sync(command)
    assert _finish_fund_run(db, run_id, scope)["status"] == "success"
    assert _daily_closes(db, symbol) == []
    with sqlite3.connect(db.path) as conn:
        previous_close, source = conn.execute(
            "SELECT previous_close,quote_source FROM latest_quotes WHERE symbol=?",
            (symbol,),
        ).fetchone()
        assert (previous_close, source) == (1.77, "sina_fund_estimate")
        assert not unresolved_publications(conn)


def _seed_legacy_estimate_close(db, symbol, price=1.77):
    """Recreate the old writer's stored item with its original previous-close fields."""
    run_id = "legacy-estimate-" + symbol
    scope = _start_fund_run(db, run_id, [symbol])
    observation = replace(
        _official_command(symbol, run_id),
        price=1.8,
        quote_timestamp="2026-11-26T10:30:00+08:00",
        quote_source="sina_fund_estimate",
        quote_status="estimated",
        provider_name="sina",
        previous_close=price,
        previous_close_date="2026-11-25",
        daily_close_price=None,
        daily_close_date=None,
        daily_close_source=None,
    )
    db.persist_quote_ingestion_sync(observation)
    assert _finish_fund_run(db, run_id, scope)["status"] == "success"
    payload = replace(
        observation,
        daily_close_date=observation.previous_close_date,
        daily_close_price=price,
        daily_close_source="reported_previous_close",
    ).to_dict()
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            "UPDATE quote_ingestion_items SET payload_json=?,payload_fingerprint=? WHERE run_id=?",
            (json.dumps(payload), stable_json_fingerprint(payload), run_id),
        )
        conn.execute(
            """
            INSERT INTO daily_close_snapshots_v2
                (symbol,instrument_type,trade_date,close_price,source,captured_at,identity_provenance)
            SELECT symbol,instrument_type,?,?,?,created_at,identity_provenance
            FROM quote_snapshots WHERE fetch_run_id=?
        """,
            (observation.previous_close_date, price, "reported_previous_close", run_id),
        )


@pytest.mark.parametrize("price", [1.77, 1.8028])
def test_official_quote_resolves_proven_estimate_close_in_the_publication(
    tmp_path, price
):
    db = _db(tmp_path)
    symbols = ["012710", "018125"]
    _seed_legacy_estimate_close(db, symbols[0], price)
    run_id = "official-batch"
    scope = _start_fund_run(db, run_id, symbols)
    for symbol in symbols:
        db.persist_quote_ingestion_sync(_official_command(symbol, run_id))
    assert _finish_fund_run(db, run_id, scope)["status"] == "success"
    db.persist_quote_ingestion_sync(_official_command(symbols[0]))
    assert _daily_closes(db, symbols[1]) == [
        ("open_end_fund", "2026-11-25", 1.8028, "eastmoney_fund_page")
    ]
    expected_source = (
        "reported_previous_close" if price == 1.8028 else "eastmoney_fund_page"
    )
    assert _daily_closes(db, symbols[0]) == [
        ("open_end_fund", "2026-11-25", 1.8028, expected_source)
    ]
    with sqlite3.connect(db.path) as conn:
        repairs = conn.execute(
            "SELECT payload_json FROM event_log WHERE event_type='market.daily_close.legacy_reconciled'"
        ).fetchall()
        assert len(repairs) == (0 if price == 1.8028 else 1)
        if repairs:
            repair = json.loads(repairs[0][0])
            assert (repair["old_close_price"], repair["new_close_price"]) == (
                1.77,
                1.8028,
            )
            assert (repair["old_run_id"], repair["new_run_id"]) == (
                "legacy-estimate-012710",
                run_id,
            )
        assert not unresolved_publications(conn)


@pytest.mark.parametrize(
    "damage",
    [
        "ambiguous",
        "wrong_symbol",
        "wrong_date",
        "wrong_amount",
        "bad_fingerprint",
        "failed_run",
        "missing_item",
    ],
)
def test_untraceable_legacy_estimate_close_keeps_entire_batch_blocked(tmp_path, damage):
    db = _db(tmp_path)
    symbols = ["012710", "018125"]
    _seed_legacy_estimate_close(db, symbols[1])
    with sqlite3.connect(db.path) as conn:
        if damage == "ambiguous":
            conn.execute("""
                INSERT INTO quote_snapshots(symbol,asset_class,instrument_type,price,timestamp,created_at,quote_source)
                SELECT symbol,asset_class,instrument_type,price,timestamp,created_at,'another_source' FROM quote_snapshots
            """)
            conn.execute(
                "UPDATE quote_current_materialization_state SET snapshot_cutoff_id=(SELECT MAX(id) FROM quote_snapshots)"
            )
        elif damage == "failed_run":
            conn.execute("UPDATE quote_fetch_runs SET status='failed'")
        elif damage == "missing_item":
            conn.execute("DELETE FROM quote_ingestion_items")
        elif damage == "bad_fingerprint":
            conn.execute(
                "UPDATE quote_ingestion_items SET payload_fingerprint='broken'"
            )
        else:
            item = json.loads(
                conn.execute(
                    "SELECT payload_json FROM quote_ingestion_items"
                ).fetchone()[0]
            )
            k, v = {
                "wrong_symbol": ("symbol", "019999"),
                "wrong_date": ("previous_close_date", "2026-11-24"),
                "wrong_amount": ("daily_close_price", 2.1),
            }[damage]
            item[k] = v
            conn.execute(
                "UPDATE quote_ingestion_items SET payload_json=?,payload_fingerprint=?",
                (json.dumps(item), stable_json_fingerprint(item)),
            )
    run_id = "official-fails"
    scope = _start_fund_run(db, run_id, symbols)
    for symbol in symbols:
        db.persist_quote_ingestion_sync(_official_command(symbol, run_id))
    assert _finish_fund_run(db, run_id, scope)["status"] == "failed"
    assert _daily_closes(db, symbols[0]) == []
    assert _daily_closes(db, symbols[1]) == [
        ("open_end_fund", "2026-11-25", 1.77, "reported_previous_close")
    ]
    with sqlite3.connect(db.path) as conn:
        assert not conn.execute(
            "SELECT 1 FROM event_log WHERE event_type='market.daily_close.legacy_reconciled'"
        ).fetchone()
        assert len(unresolved_publications(conn)) == 1


def test_same_price_sync_provider_label_and_official_publisher_can_corroborate(
    tmp_path,
):
    db = _db(tmp_path)
    first = replace(_official_command("012710"), daily_close_source="akshare")
    db.persist_quote_ingestion_sync(first)
    second = replace(
        first,
        quote_source="tushare_fund_nav",
        provider_name="tushare",
        daily_close_source="tushare_fund_nav",
    )
    db.persist_quote_ingestion_sync(second)
    assert _daily_closes(db, "012710") == [
        ("open_end_fund", "2026-11-25", 1.8028, "akshare")
    ]
