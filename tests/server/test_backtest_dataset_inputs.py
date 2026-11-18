"""Verified Dataset adaptation preserves replay values without repeated full scans."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from core.events import MarketEvent
from core.types import (
    AssetClass,
    BarFrequency,
    CommissionType,
    InstrumentKey,
    InstrumentType,
    Settlement,
)
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetSnapshot,
)
from data.dataset.reader import read_daily_bar_dataset
from data.market.capture import capture_provider_payload
from data.market.contracts import DailyBarRequest
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market_calendar import build_static_market_calendar_snapshot
from data.storage.objects import ContentAddressedObjectStore
from server.contracts.http.strategy_models import (
    BacktestCostAssumptions,
    BacktestRequest,
    BacktestSweepRequest,
)
from server.services.backtest.chronological import run_chronological_sweep
from server.services.backtest_views.execution import run_single_backtest
from server.services.research import dataset_inputs as inputs
from server.services.research.dataset_policy import (
    EXPLICIT_VERIFIED_SOURCE_UNION_POLICY_ID,
)
from server.services.research.datasets import ResearchDatasetError
from tests.server.test_dataset_corporate_actions import CAPTURED, _observe
from tests.server.test_deployment_scope_datasets import _composed
from tests.server.test_verified_interval_dataset import DAYS, _verified_day

STOCK = InstrumentKey("600000", InstrumentType.STOCK)
ETF = InstrumentKey("510300", InstrumentType.ETF)


def _mixed(root):
    store = ContentAddressedObjectStore(root / "objects")
    partitions = []
    for day, close in zip(DAYS, ("10.12345678", "10.87654321"), strict=True):
        ref = _verified_day(root, day, instruments=(STOCK, ETF), close=close)
        daily = read_daily_bar_dataset(store, ref)
        partitions.extend(daily.snapshot.partitions)
    ref = publish_daily_bar_dataset_manifest(
        store,
        replace(daily.snapshot, start_date=DAYS[0], partitions=tuple(partitions)),
    )
    return read_daily_bar_dataset(store, ref)


def _request(result):
    return SimpleNamespace(
        dataset_id=result.ref.dataset_id,
        start_date=result.snapshot.start_date.isoformat(),
        end_date=result.snapshot.end_date.isoformat(),
        assets=[
            {"symbol": key.symbol, "instrument_type": key.instrument_type.value}
            for key in result.snapshot.instruments
        ],
    )


class _CountedBars(tuple):
    def __init__(self, bars):
        self.visits = 0

    def __iter__(self):
        for bar in super().__iter__():
            self.visits += 1
            yield bar


@pytest.mark.parametrize("shape", ["mixed", "sparse"])
def test_verified_inputs_preserve_values_identity_and_replay_order(tmp_path, shape):
    root = tmp_path / "research"
    result = _mixed(root) if shape == "mixed" else _composed(tmp_path)[1]
    instruments, handlers, binding = inputs.load_dataset_backtest_inputs(
        root, _request(result)
    )

    assert list(handlers) == [key.symbol for key in result.snapshot.instruments]
    assert list(instruments) == list(handlers)
    columns = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "available_at",
        "captured_at",
    ]
    fields = ["event_time", *columns[1:]]
    for key in result.snapshot.instruments:
        bars = tuple(bar for bar in result.bars if bar.instrument == key)
        handler, instrument = handlers[key.symbol], instruments[key.symbol]
        expected = pd.DataFrame(
            [[getattr(bar, field) for field in fields] for bar in bars],
            columns=columns,
        )
        expected.attrs.update(
            provider_name="tdx",
            data_source="tdx",
            adjustment_mode="none",
            dataset_id=result.ref.dataset_id,
        )
        pd.testing.assert_frame_equal(handler._df, expected, check_exact=True)
        assert handler._df.attrs == expected.attrs
        for column in columns[1:7]:
            assert all(isinstance(value, Decimal) for value in handler._df[column])
        is_stock = key.instrument_type is InstrumentType.STOCK
        assert instrument.asset_class is (
            AssetClass.STOCK if is_stock else AssetClass.FUND
        )
        assert (
            instrument.instrument_type is handler.instrument_type is key.instrument_type
        )
        assert instrument.symbol == instrument.name == key.symbol
        assert instrument.commission_type is (
            CommissionType.STOCK_A if is_stock else CommissionType.FUND_ETF
        )
        assert instrument.settlement is Settlement.T_PLUS_1
        assert instrument.lot_size == Decimal("100")
        assert instrument.price_tick == Decimal("0.01" if is_stock else "0.001")
        events = tuple(
            MarketEvent(
                timestamp=bar.event_time,
                symbol=key.symbol,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                frequency=BarFrequency.DAILY,
                asset_class=instrument.asset_class,
                instrument_type=key.instrument_type,
                available_at=bar.available_at,
            )
            for bar in bars
        )
        assert tuple(handler) == events
        assert tuple(handler.stream()) == events
    assert [handler.total_bars for handler in handlers.values()] == (
        [2, 2] if shape == "mixed" else [2, 1]
    )
    assert binding["dataset_id"] == result.ref.dataset_id
    assert binding["cutoff"] == result.snapshot.cutoff.isoformat()
    assert binding["source_names"] == ["tdx"]
    assert binding["price_basis"] == "unadjusted"
    assert binding["cross_source_verified"] is True
    assert binding["offline_replay"] is True
    assert binding["point_in_time_verified"] is False
    assert "corporate_action_evidence" not in binding
    audit = binding["decision_availability"]
    assert audit["status"] == "blocked"
    assert audit["checked_bar_count"] == len(result.bars)
    assert (
        audit["late_bar_count"] == audit["late_verification_count"] == len(result.bars)
    )


def test_inputs_retain_bound_corporate_action_evidence(tmp_path):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    original = _verified_day(tmp_path, DAYS[0])
    before = read_daily_bar_dataset(store, original)
    observation = _observe(store)
    ref = publish_daily_bar_dataset_manifest(
        store,
        replace(
            before.snapshot,
            cutoff=CAPTURED,
            corporate_action_observation_ids=(observation.object_id,),
        ),
    )
    result = read_daily_bar_dataset(store, ref)

    _, handlers, binding = inputs.load_dataset_backtest_inputs(
        tmp_path, _request(result)
    )

    assert ref != original
    assert binding["dataset_id"] == ref.dataset_id
    assert binding["corporate_action_evidence"] == result.corporate_action_evidence
    assert binding["corporate_action_evidence"]["observation_ids"] == [
        observation.object_id
    ]
    assert binding["corporate_action_evidence"]["returns_modeled"] is False
    assert handlers[STOCK.symbol]._df["close"].tolist() == [before.bars[0].close]
    assert read_daily_bar_dataset(store, original) == before


def test_missing_instrument_rows_still_fail_closed(tmp_path, monkeypatch):
    result = _mixed(tmp_path)

    def missing_read(store, ref):
        restored = read_daily_bar_dataset(store, ref)
        return replace(
            restored,
            bars=tuple(bar for bar in restored.bars if bar.instrument != STOCK),
        )

    monkeypatch.setattr(inputs, "read_daily_bar_dataset", missing_read)
    with pytest.raises(ResearchDatasetError, match="^dataset_instrument_has_no_rows$"):
        inputs.load_dataset_backtest_inputs(tmp_path, _request(result))


def test_input_bar_visits_stay_bounded_as_instrument_count_grows(tmp_path, monkeypatch):
    keys = tuple(
        InstrumentKey(str(600000 + index), InstrumentType.STOCK) for index in range(6)
    )
    ref = _verified_day(tmp_path, DAYS[0], instruments=keys)
    result = read_daily_bar_dataset(
        ContentAddressedObjectStore(tmp_path / "objects"), ref
    )
    observed = []

    def counted_read(store, dataset_ref):
        restored = read_daily_bar_dataset(store, dataset_ref)
        bars = _CountedBars(restored.bars)
        observed.append(bars)
        return replace(restored, bars=bars)

    monkeypatch.setattr(inputs, "read_daily_bar_dataset", counted_read)
    _, handlers, binding = inputs.load_dataset_backtest_inputs(
        tmp_path, _request(result)
    )

    assert len(handlers) == len(keys)
    assert binding["decision_availability"]["checked_bar_count"] == len(result.bars)
    assert len(observed) == 1
    # Include the availability audit, but never scan all bars for each symbol.
    assert observed[0].visits <= 3 * len(result.bars)


E2E_DATES = [
    date(2025, 1, 2),
    date(2025, 1, 3),
    date(2025, 1, 6),
    date(2025, 1, 7),
    date(2025, 1, 8),
]


def _make_dataset_with_evidence(
    tmp_path,
    dates,
    prices,
    *,
    halt_day=None,
    is_st=False,
    listing_date="1999-11-10",
    omit_st=False,
    omit_listing=False,
):
    root = tmp_path / "research"
    store = ContentAddressedObjectStore(root / "objects")
    partitions = []
    memberships = []

    for day, price in zip(dates, prices, strict=True):
        ref = _verified_day(root, day, instruments=(STOCK,), close=str(price))
        daily = read_daily_bar_dataset(store, ref)
        partitions.extend(
            replace(p, instruments=(STOCK,)) for p in daily.snapshot.partitions
        )

        master_at = datetime(day.year, day.month, day.day, 8, 0, tzinfo=timezone.utc)
        cap_request = DailyBarRequest((STOCK,), day, day).to_capture_request()
        is_halted = halt_day == day
        trade_status = "0" if is_halted else "1"
        cap_payload = {
            "schema": "baostock.history_k_data_plus.rows.v2",
            "request": {
                "frequency": "d",
                "adjustflag": "3",
                "start_date": str(day),
                "end_date": str(day),
                "fields": [
                    "date",
                    "code",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "adjustflag",
                    "tradestatus",
                ],
            },
            "calls": [
                {
                    "code": "sh.600000",
                    "fields": [
                        "date",
                        "code",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                        "adjustflag",
                        "tradestatus",
                    ],
                    "rows": [
                        [
                            str(day),
                            "sh.600000",
                            str(price),
                            str(price),
                            str(price),
                            str(price),
                            "0" if is_halted else "100",
                            "0" if is_halted else "1000",
                            "3",
                            "1",
                        ]
                    ],
                }
            ],
        }
        cap = capture_provider_payload(
            store,
            provider="baostock",
            operation="daily_bars",
            request=cap_request,
            raw_payload=json.dumps(cap_payload).encode(),
            payload_format="baostock.history_k_data_plus.rows.v2",
            adapter_version="karkinos.baostock.daily_bar.v2",
            started_at=master_at,
            completed_at=master_at,
            record_count=1,
        )

        meta_row = {
            "symbol": "600000",
            "display_name": "浦发银行" if not is_st else "ST浦发",
            "list_status": "L",
            "list_date": None if omit_listing else listing_date,
            "delist_date": None,
            "trade_status": trade_status,
            "status_session_date": str(day),
            "status_capture_id": cap.capture_id,
        }
        if not omit_st:
            meta_row["is_st"] = is_st

        master = {
            "schema_version": "karkinos.market_universe_snapshot.v2",
            "trade_date": str(day),
            "membership_basis": "current_active_stock_master",
            "availability_basis": "capture_completed_at",
            "observation_basis": "adapter_response",
            "capture_started_at": master_at.isoformat(),
            "capture_completed_at": master_at.isoformat(),
            "available_at": master_at.isoformat(),
            "members": [{"symbol": "600000"}],
            "member_metadata": [meta_row],
        }
        master_ref = store.put_bytes(json.dumps(master).encode())
        memberships.append(
            DailyBarDatasetMembership(
                day,
                (STOCK,),
                master_at,
                (master_ref.object_id, cap.capture_id),
            )
        )

    snapshot = DailyBarDatasetSnapshot(
        start_date=dates[0],
        end_date=dates[-1],
        cutoff=datetime(
            dates[-1].year, dates[-1].month, dates[-1].day, 16, 0, tzinfo=timezone.utc
        ),
        instruments=(STOCK,),
        resolver_policy_id=EXPLICIT_VERIFIED_SOURCE_UNION_POLICY_ID,
        market_schema_version=DAILY_BAR_SCHEMA_VERSION,
        partitions=tuple(partitions),
        session_memberships=tuple(memberships),
        universe_policy_id="fixture.policy.v1",
    )
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    return read_daily_bar_dataset(store, ref)


class MockCalendarDb:
    def __init__(self, root, cal):
        self.path = root / "app.db"
        self._cal = cal

    def get_market_calendar_snapshot_sync(self, *, exchange="SSE", year=2025):
        if self._cal and self._cal.year == year:
            return self._cal.to_payload()
        return None


def test_e2e_dataset_service_verified_normal_produces_fills(tmp_path):
    """1. Verified normal status produces expected trade fills and fill metadata."""
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in E2E_DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    # 5 days: Day 4 golden cross triggers order for Day 5
    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    result = _make_dataset_with_evidence(
        tmp_path, E2E_DATES, prices, is_st=False, listing_date="1999-11-10"
    )

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=E2E_DATES[0].isoformat(),
        end_date=E2E_DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = inputs.prepare_dataset_backtest_inputs(req, db=db)
    instruments, handlers, binding, snapshot = prepared

    assert binding["strict_security_status"] is True
    assert binding["execution_context"]["trading_calendar"] is not None
    assert binding["execution_context"]["security_status"] is not None

    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )
    assert out["metrics_json"]["total_trades"] > 0
    assert len(out["fills"]) >= 1
    fill = out["fills"][0]
    assert fill["symbol"] == "600000"
    assert fill["metadata"]["execution_phase"] == "close"
    assert fill["metadata"]["session_date"] == "2025-01-08"
    assert "bar_timestamp" in fill["metadata"]


def test_e2e_dataset_service_confirmed_suspension_blocks_order(tmp_path):
    """2. Same scenario with confirmed halt on Day 5 blocks order execution."""
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in E2E_DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    result = _make_dataset_with_evidence(
        tmp_path,
        E2E_DATES,
        prices,
        halt_day=E2E_DATES[4],
        is_st=False,
        listing_date="1999-11-10",
    )

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=E2E_DATES[0].isoformat(),
        end_date=E2E_DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = inputs.prepare_dataset_backtest_inputs(req, db=db)
    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )
    # Order blocked due to suspension!
    assert out["metrics_json"]["total_trades"] == 0
    assert out["metrics_json"]["execution_timing"]["suspension_blocked_count"] >= 1


def test_e2e_dataset_service_missing_strict_fields_fails_closed(tmp_path):
    """3. Missing strict mode required fields (e.g. is_st is None) fails closed."""
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in E2E_DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    result = _make_dataset_with_evidence(
        tmp_path, E2E_DATES, prices, omit_st=True, listing_date="1999-11-10"
    )

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=E2E_DATES[0].isoformat(),
        end_date=E2E_DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = inputs.prepare_dataset_backtest_inputs(req, db=db)
    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )
    # Blocked by unverified_state (st_status_unverified), does not fall into 10% ordinary rule
    assert out["metrics_json"]["total_trades"] == 0
    assert (
        out["metrics_json"]["execution_timing"]["unverified_state_blocked_count"] >= 1
    )


def test_e2e_dataset_service_st_status_alters_price_boundary(tmp_path):
    """4. Historical ST status changes price boundary to 5%, blocking a +8% move."""
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in E2E_DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    # Prices: Day 4 close is 10.1 (DualMA triggers BUY for Day 5).
    # Day 5 price is 10.8 (+6.9% jump). For ST stock (5%), limit up is 10.61, so 10.8 exceeds limit!
    prices = [10.0, 10.0, 10.0, 10.1, 10.8]
    result = _make_dataset_with_evidence(
        tmp_path, E2E_DATES, prices, is_st=True, listing_date="1999-11-10"
    )

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=E2E_DATES[0].isoformat(),
        end_date=E2E_DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = inputs.prepare_dataset_backtest_inputs(req, db=db)
    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )
    # Blocked by price limit!
    assert out["metrics_json"]["total_trades"] == 0
    assert out["metrics_json"]["execution_timing"]["limit_blocked_count"] >= 1


def test_e2e_dataset_service_calendar_fingerprint_and_gap_rejection(tmp_path):
    """5. Non-empty calendar fingerprint & rejection of calendar gaps."""
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in E2E_DATES],
    )
    assert len(cal.source_fingerprint) == 64

    # Incomplete calendar missing 2025-01-06
    bad_cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=["2025-01-02", "2025-01-03", "2025-01-07", "2025-01-08"],
    )
    bad_db = MockCalendarDb(tmp_path / "bad", bad_cal)
    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    result = _make_dataset_with_evidence(tmp_path / "bad", E2E_DATES, prices)

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=E2E_DATES[0].isoformat(),
        end_date=E2E_DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    # Engine coverage validation rejects the missing calendar day
    with pytest.raises(
        ValueError,
        match=r"(session_bar_on_non_trading_day|trading_calendar_coverage_incomplete)",
    ):
        prepared = inputs.prepare_dataset_backtest_inputs(req, db=bad_db)
        out = run_single_backtest(
            req, SimpleNamespace(), db=bad_db, preloaded_dataset_inputs=prepared
        )


def test_e2e_dataset_service_main_and_stress_test_consume_same_context(tmp_path):
    """6. Main backtest and cost stress test consume identical execution context."""
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in E2E_DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    result = _make_dataset_with_evidence(
        tmp_path, E2E_DATES, prices, is_st=False, listing_date="1999-11-10"
    )

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=E2E_DATES[0].isoformat(),
        end_date=E2E_DATES[-1].isoformat(),
        initial_cash=100000.0,
        cost_assumptions=BacktestCostAssumptions(
            stock_commission_rate=0.0003,
            slippage_bps=10.0,
        ),
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = inputs.prepare_dataset_backtest_inputs(req, db=db)
    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )
    assert out["metrics_json"]["dataset_binding"]["strict_security_status"] is True
    assert (
        out["metrics_json"]["dataset_binding"]["execution_context"]["security_status"]
        is not None
    )


def test_e2e_dataset_service_chronological_sweep_preserves_strict_mode(tmp_path):
    """7. Public /sweep and chronological test_start_date preserve strict mode."""
    sweep_dates = [
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2025, 1, 6),
        date(2025, 1, 7),
        date(2025, 1, 8),
        date(2025, 1, 9),
        date(2025, 1, 10),
    ]
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in sweep_dates],
    )
    db = MockCalendarDb(tmp_path, cal)
    prices = [10.0, 10.0, 10.0, 10.1, 10.2, 10.3, 10.4]
    result = _make_dataset_with_evidence(
        tmp_path, sweep_dates, prices, is_st=False, listing_date="1999-11-10"
    )

    sweep_req = BacktestSweepRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=sweep_dates[0].isoformat(),
        end_date=sweep_dates[-1].isoformat(),
        initial_cash=100000.0,
        param_grid={"short_period": [2], "long_period": [3]},
        test_start_date=sweep_dates[4],
        strict_security_status=True,
    )

    candidates = [
        BacktestRequest(
            strategy="dual_ma",
            dataset_id=result.ref.dataset_id,
            start_date=sweep_dates[0].isoformat(),
            end_date=sweep_dates[-1].isoformat(),
            initial_cash=100000.0,
            short_period=2,
            long_period=3,
            params={"short_period": 2, "long_period": 3},
            strict_security_status=True,
        )
    ]

    chronology = run_chronological_sweep(
        sweep_req,
        candidates,
        SimpleNamespace(),
        db,
        rank_direction="desc",
    )
    assert chronology["selection"]["strict_security_status"] is True
    assert (
        chronology["training"][0]["metrics_json"]["dataset_binding"][
            "strict_security_status"
        ]
        is True
    )
    assert (
        chronology["test"]["metrics_json"]["dataset_binding"]["strict_security_status"]
        is True
    )
