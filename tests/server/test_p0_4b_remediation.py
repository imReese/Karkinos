"""Reproduction and regression tests for P0-4B remediation issues (A1-A3, B1-B6, Task C)."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.types import InstrumentKey, InstrumentType, Symbol
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetSnapshot,
)
from data.dataset.reader import read_daily_bar_dataset
from data.market.capture import capture_provider_payload
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market_calendar import (
    MarketCalendarDay,
    MarketCalendarSnapshot,
    build_static_market_calendar_snapshot,
    market_calendar_day_from_payload,
    market_calendar_snapshot_from_payload,
)
from data.storage.objects import ContentAddressedObjectStore
from server.contracts.http.strategy_models import BacktestRequest
from server.services.backtest.chronological import run_chronological_sweep
from server.services.backtest_views.execution import (
    run_single_backtest,
    write_backtest_report_file,
)
from server.services.research import dataset_inputs
from server.services.research.dataset_inputs import (
    ResearchDatasetError,
    prepare_dataset_backtest_inputs,
)
from server.services.research.dataset_policy import (
    EXPLICIT_VERIFIED_SOURCE_UNION_POLICY_ID,
)

STOCK = InstrumentKey(Symbol("600000"), InstrumentType.STOCK)
DATES = [
    date(2025, 1, 2),
    date(2025, 1, 3),
    date(2025, 1, 6),
    date(2025, 1, 7),
    date(2025, 1, 8),
]


# ---------------------------------------------------------------------------
# B1, B2, B3 reproduction tests
# ---------------------------------------------------------------------------


def test_b1_missing_is_trading_day_rejected():
    """B1: Missing is_trading_day must not default to open trading day."""
    with pytest.raises(ValueError, match="is_trading_day"):
        market_calendar_day_from_payload({"date": "2025-01-02"})


def test_b2_is_trading_day_null_rejected():
    """B2: is_trading_day=null must not be treated as known holiday."""
    with pytest.raises(ValueError, match="is_trading_day"):
        market_calendar_day_from_payload({"date": "2025-01-02", "is_trading_day": None})


def test_b3_is_trading_day_string_false_rejected():
    """B3: is_trading_day='false' must not be truthy open day."""
    with pytest.raises(ValueError, match="is_trading_day"):
        market_calendar_day_from_payload(
            {"date": "2025-01-02", "is_trading_day": "false"}
        )


# ---------------------------------------------------------------------------
# A2, A3 reproduction tests
# ---------------------------------------------------------------------------


def test_a2_is_st_null_remains_unknown_and_blocks_in_strict_mode(tmp_path):
    """A2: metadata.is_st=null must remain unknown, not bool(None)=False, blocking in strict mode."""
    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _make_dataset_with_evidence,
    )

    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)

    # Make dataset where is_st is None explicitly in metadata
    result = _make_dataset_with_evidence(
        tmp_path, DATES, prices, is_st=None, listing_date="1999-11-10"
    )

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = prepare_dataset_backtest_inputs(req, db=db)
    instruments, handlers, binding, snapshot = prepared

    # Binding's security status should preserve is_st as None for all days
    sec_status = binding["execution_context"]["security_status"]
    for day_str, syms in sec_status.items():
        assert syms["600000"]["is_st"] is None, (
            f"Expected None for day {day_str}, got {syms['600000']['is_st']}"
        )

    # In strict mode, execution must fail-closed with unverified_state
    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )
    assert (
        out["metrics_json"]["execution_timing"]["unverified_state_blocked_count"] >= 1
    )
    assert len(out["fills"]) == 0


def test_b6_typeerror_in_load_inputs_not_swallowed(monkeypatch, tmp_path):
    """B6: Internal TypeError in load_dataset_backtest_inputs must NOT trigger retry without db."""
    from tests.server.test_backtest_dataset_inputs import MockCalendarDb

    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)

    calls = []

    def buggy_load(root, request, db=None):
        calls.append(db)
        if db is not None:
            raise TypeError("internal_bug_type_error")
        return ({}, {}, {"source_names": []})

    monkeypatch.setattr(dataset_inputs, "load_dataset_backtest_inputs", buggy_load)
    req = BacktestRequest(
        dataset_id="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        start_date="2025-01-02",
        end_date="2025-01-08",
    )
    with pytest.raises(TypeError, match="internal_bug_type_error"):
        prepare_dataset_backtest_inputs(req, db=db)
    assert calls == [db]


def test_b4_fixed_execution_identity_replays_original_calendar_not_db_latest(tmp_path):
    """B4: Replaying with execution_context_id loads pinned context without querying DB latest calendar."""
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _make_dataset_with_evidence,
    )

    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    cal1 = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="original_provider",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal1)
    dataset_res = _make_dataset_with_evidence(tmp_path, DATES, prices)

    req1 = BacktestRequest(
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
    )
    _, _, binding1, _ = prepare_dataset_backtest_inputs(req1, db=db)
    ctx_id = binding1["execution_context_id"]
    assert ctx_id is not None
    assert (
        binding1["execution_context"]["trading_calendar"]["provider"]
        == "original_provider"
    )

    # Now change DB to return a radically altered calendar
    cal2 = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="altered_db_provider",
        open_dates=[DATES[0].isoformat()],
    )
    db._calendar = cal2

    # Replay with execution_context_id pinned
    req2 = req1.model_copy(update={"execution_context_id": ctx_id})
    _, _, binding2, _ = prepare_dataset_backtest_inputs(req2, db=db)

    # Must retain original_provider calendar from pinned object, NOT altered_db_provider
    assert binding2["execution_context_id"] == ctx_id
    assert (
        binding2["execution_context"]["trading_calendar"]["provider"]
        == "original_provider"
    )
    assert len(binding2["execution_context"]["trading_calendar"]["days"]) == len(
        binding1["execution_context"]["trading_calendar"]["days"]
    )


def test_b5_content_changed_with_old_execution_identity_detected(tmp_path):
    """B5: Mismatch between requested execution_context_id and actual context content fails closed."""
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _make_dataset_with_evidence,
    )

    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    dataset_res = _make_dataset_with_evidence(tmp_path, DATES, prices)

    # Fake context id passed
    fake_ctx_id = (
        "ctx-sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    req = BacktestRequest(
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        execution_context_id=fake_ctx_id,
    )
    with pytest.raises(
        ResearchDatasetError, match="execution_context_content_hash_mismatch"
    ):
        prepare_dataset_backtest_inputs(req, db=db)


# ---------------------------------------------------------------------------
# Task C: Execution audit metadata and report file persistence
# ---------------------------------------------------------------------------


def test_c_service_output_and_report_metadata_audit_consistency(tmp_path, monkeypatch):
    """Task C: run_single_backtest output and write_backtest_report_file retain fill_execution_audits."""
    from server.services.backtest_views.execution import (
        read_backtest_report_file,
        write_backtest_report_file,
    )
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _make_dataset_with_evidence,
    )

    monkeypatch.setenv("KARKINOS_BACKTEST_REPORT_DIR", str(tmp_path / "reports"))

    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    dataset_res = _make_dataset_with_evidence(tmp_path, DATES, prices)

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = prepare_dataset_backtest_inputs(req, db=db)
    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )

    # 1. Check fills DTO contract remains backwards compatible
    assert len(out["fills"]) >= 1
    dto_fill = out["fills"][0]
    assert "metadata" not in dto_fill
    assert "fill_id" in dto_fill
    assert "order_id" in dto_fill

    # 2. Check service outputs include fill_execution_audits
    audits = out["fill_execution_audits"]
    assert len(audits) >= 1
    assert audits == out["metrics_json"]["fill_execution_audits"]
    assert audits == out["evidence_json"]["fill_execution_audits"]

    first_audit = audits[0]
    assert first_audit["fill_id"] == dto_fill["fill_id"]
    assert first_audit["order_id"] == dto_fill["order_id"]
    assert first_audit["symbol"] == "600000"
    assert first_audit["execution_phase"] == "close"
    assert first_audit["session_date"] == "2025-01-08"
    assert first_audit["execution_model"] == "next_bar_close"
    assert first_audit["bar_timestamp"] is not None

    # 3. Check write_backtest_report_file and read_backtest_report_file
    report_path = write_backtest_report_file(
        result_id=101, request=req, bt_result=out, metrics_json=out["metrics_json"]
    )
    assert report_path.exists()
    report_data = read_backtest_report_file(101)
    assert "fill_execution_audits" in report_data
    assert report_data["fill_execution_audits"] == audits


def test_c_legacy_report_file_compatibility(tmp_path, monkeypatch):
    """Task C: Reading older report files without fill_execution_audits field defaults safely to empty list."""
    from server.services.backtest_views.execution import read_backtest_report_file

    rep_dir = tmp_path / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KARKINOS_BACKTEST_REPORT_DIR", str(rep_dir))

    legacy_payload = {
        "schema_version": "karkinos.backtest_report.v1",
        "id": 9999,
        "generated_at": "2025-01-01T00:00:00Z",
        "config": {},
        "metrics": {},
        "equity_curve": [],
        "metrics_json": {},
        "cost_summary": {},
        "evidence": {},
        "fills": [],
    }
    legacy_file = rep_dir / "backtest-result-9999.json"
    legacy_file.write_text(json.dumps(legacy_payload), encoding="utf-8")

    data = read_backtest_report_file(9999)
    assert data["id"] == 9999
    assert data["fill_execution_audits"] == []


def test_a3_is_st_string_zero_parsed_as_false_not_true(tmp_path):
    """A3: metadata.is_st='0' must be parsed as False, not bool('0')=True."""
    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _make_dataset_with_evidence,
    )

    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)

    # Pass is_st="0"
    result = _make_dataset_with_evidence(
        tmp_path, DATES, prices, is_st="0", listing_date="1999-11-10"
    )

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=result.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = prepare_dataset_backtest_inputs(req, db=db)
    instruments, handlers, binding, snapshot = prepared

    sec_status = binding["execution_context"]["security_status"]
    for day_str, syms in sec_status.items():
        assert syms["600000"]["is_st"] is False, (
            f"Expected False for day {day_str}, got {syms['600000']['is_st']}"
        )


def test_a1_master_future_date_does_not_supply_normal_status_when_hist_status_empty(
    tmp_path,
):
    """A1: Master from 2025-02-10 must not supply trade_status='1' for 2025-01-08 when hist_status is empty."""
    from tests.server.test_backtest_dataset_inputs import MockCalendarDb, _verified_day

    root = tmp_path / "research"
    store = ContentAddressedObjectStore(root / "objects")
    partitions = []
    memberships = []

    # 1. First 4 days have verified daily bars (day 3 price jumps to 10.8 to trigger signal)
    day_prices = ["10.0", "10.0", "10.0", "10.8"]
    for day, p_close in zip(DATES[:-1], day_prices):
        ref = _verified_day(root, day, instruments=(STOCK,), close=p_close)
        daily = read_daily_bar_dataset(store, ref)
        partitions.extend(
            replace(p, instruments=(STOCK,)) for p in daily.snapshot.partitions
        )
        master_at = datetime(day.year, day.month, day.day, 8, 0, tzinfo=timezone.utc)
        meta_row = {
            "symbol": "600000",
            "display_name": "浦发银行",
            "list_status": "L",
            "list_date": "1999-11-10",
            "trade_status": "1",
            "status_session_date": str(day),
            "is_st": False,
        }
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
        m_ref = store.put_bytes(json.dumps(master).encode())
        memberships.append(
            DailyBarDatasetMembership(day, (STOCK,), master_at, (m_ref.object_id,))
        )

    # 2. Day 5 (2025-01-08) references a future master (2025-02-10) with NO hist_status capture
    day5 = DATES[-1]
    ref5 = _verified_day(root, day5, instruments=(STOCK,), close="10.8")
    daily5 = read_daily_bar_dataset(store, ref5)
    partitions.extend(
        replace(p, instruments=(STOCK,)) for p in daily5.snapshot.partitions
    )

    future_date = "2025-02-10"
    future_at = datetime(2025, 2, 10, 8, 0, tzinfo=timezone.utc)
    future_meta_row = {
        "symbol": "600000",
        "display_name": "浦发银行",
        "list_status": "L",
        "list_date": "1999-11-10",
        "trade_status": "1",
        "status_session_date": future_date,
        "is_st": False,
    }
    future_master = {
        "schema_version": "karkinos.market_universe_snapshot.v2",
        "trade_date": future_date,
        "membership_basis": "current_active_stock_master",
        "availability_basis": "capture_completed_at",
        "observation_basis": "adapter_response",
        "capture_started_at": future_at.isoformat(),
        "capture_completed_at": future_at.isoformat(),
        "available_at": future_at.isoformat(),
        "members": [{"symbol": "600000"}],
        "member_metadata": [future_meta_row],
    }
    fut_ref = store.put_bytes(json.dumps(future_master).encode())
    memberships.append(
        DailyBarDatasetMembership(day5, (STOCK,), future_at, (fut_ref.object_id,))
    )

    snapshot = DailyBarDatasetSnapshot(
        start_date=DATES[0],
        end_date=DATES[-1],
        cutoff=datetime(2025, 2, 10, 16, 0, tzinfo=timezone.utc),
        instruments=(STOCK,),
        resolver_policy_id=EXPLICIT_VERIFIED_SOURCE_UNION_POLICY_ID,
        market_schema_version=DAILY_BAR_SCHEMA_VERSION,
        partitions=tuple(partitions),
        session_memberships=tuple(memberships),
        universe_policy_id="fixture.policy.v1",
    )
    from data.dataset.manifest import publish_daily_bar_dataset_manifest

    dataset_ref = publish_daily_bar_dataset_manifest(store, snapshot)

    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset_ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = prepare_dataset_backtest_inputs(req, db=db)
    instruments, handlers, binding, snapshot = prepared

    # On day 5 (2025-01-08), trade_status must NOT be "1"! It must be None!
    sec_status = binding["execution_context"]["security_status"]
    day5_str = day5.isoformat()
    assert sec_status[day5_str]["600000"]["trade_status"] is None, (
        f"Expected trade_status to be None for {day5_str}, got {sec_status[day5_str]['600000']['trade_status']}"
    )

    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )
    assert (
        out["metrics_json"]["execution_timing"]["unverified_state_blocked_count"] >= 1
    )
    assert len(out["fills"]) == 0


def test_b6_typeerror_in_load_inputs_not_swallowed(monkeypatch, tmp_path):
    """B6: Internal TypeError in load_dataset_backtest_inputs must NOT trigger retry without db."""
    from tests.server.test_backtest_dataset_inputs import MockCalendarDb

    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)

    calls = []

    def buggy_load(root, request, db=None):
        calls.append(db)
        if db is not None:
            raise TypeError("internal_bug_type_error")
        return ({}, {}, {"source_names": []})

    monkeypatch.setattr(dataset_inputs, "load_dataset_backtest_inputs", buggy_load)
    req = BacktestRequest(
        dataset_id="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        start_date="2025-01-02",
        end_date="2025-01-08",
    )
    with pytest.raises(TypeError, match="internal_bug_type_error"):
        prepare_dataset_backtest_inputs(req, db=db)
    assert calls == [db]


def test_b4_fixed_execution_identity_replays_original_calendar_not_db_latest(tmp_path):
    """B4: Replaying with execution_context_id loads pinned context without querying DB latest calendar."""
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _make_dataset_with_evidence,
    )

    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    cal1 = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="original_provider",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal1)
    dataset_res = _make_dataset_with_evidence(tmp_path, DATES, prices)

    req1 = BacktestRequest(
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
    )
    _, _, binding1, _ = prepare_dataset_backtest_inputs(req1, db=db)
    ctx_id = binding1["execution_context_id"]
    assert ctx_id is not None
    assert (
        binding1["execution_context"]["trading_calendar"]["provider"]
        == "original_provider"
    )

    # Now change DB to return a radically altered calendar
    cal2 = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="altered_db_provider",
        open_dates=[DATES[0].isoformat()],
    )
    db._calendar = cal2

    # Replay with execution_context_id pinned
    req2 = req1.model_copy(update={"execution_context_id": ctx_id})
    _, _, binding2, _ = prepare_dataset_backtest_inputs(req2, db=db)

    # Must retain original_provider calendar from pinned object, NOT altered_db_provider
    assert binding2["execution_context_id"] == ctx_id
    assert (
        binding2["execution_context"]["trading_calendar"]["provider"]
        == "original_provider"
    )
    assert len(binding2["execution_context"]["trading_calendar"]["days"]) == len(
        binding1["execution_context"]["trading_calendar"]["days"]
    )


def test_b5_content_changed_with_old_execution_identity_detected(tmp_path):
    """B5: Mismatch between requested execution_context_id and actual context content fails closed."""
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _make_dataset_with_evidence,
    )

    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    dataset_res = _make_dataset_with_evidence(tmp_path, DATES, prices)

    # Fake context id passed
    fake_ctx_id = (
        "ctx-sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    req = BacktestRequest(
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        execution_context_id=fake_ctx_id,
    )
    with pytest.raises(
        ResearchDatasetError, match="execution_context_content_hash_mismatch"
    ):
        prepare_dataset_backtest_inputs(req, db=db)


# ---------------------------------------------------------------------------
# Task C: Execution audit metadata and report file persistence
# ---------------------------------------------------------------------------


def test_c_service_output_and_report_metadata_audit_consistency(tmp_path, monkeypatch):
    """Task C: run_single_backtest output and write_backtest_report_file retain fill_execution_audits."""
    from server.services.backtest_views.execution import (
        read_backtest_report_file,
        write_backtest_report_file,
    )
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _make_dataset_with_evidence,
    )

    monkeypatch.setenv("KARKINOS_BACKTEST_REPORT_DIR", str(tmp_path / "reports"))

    prices = [10.0, 10.0, 10.0, 10.8, 10.8]
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )
    db = MockCalendarDb(tmp_path, cal)
    dataset_res = _make_dataset_with_evidence(tmp_path, DATES, prices)

    req = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=True,
    )
    prepared = prepare_dataset_backtest_inputs(req, db=db)
    out = run_single_backtest(
        req, SimpleNamespace(), db=db, preloaded_dataset_inputs=prepared
    )

    # 1. Check fills DTO contract remains backwards compatible
    assert len(out["fills"]) >= 1
    dto_fill = out["fills"][0]
    assert "metadata" not in dto_fill
    assert "fill_id" in dto_fill
    assert "order_id" in dto_fill

    # 2. Check service outputs include fill_execution_audits
    audits = out["fill_execution_audits"]
    assert len(audits) >= 1
    assert audits == out["metrics_json"]["fill_execution_audits"]
    assert audits == out["evidence_json"]["fill_execution_audits"]

    first_audit = audits[0]
    assert first_audit["fill_id"] == dto_fill["fill_id"]
    assert first_audit["order_id"] == dto_fill["order_id"]
    assert first_audit["symbol"] == "600000"
    assert first_audit["execution_phase"] == "close"
    assert first_audit["session_date"] == "2025-01-08"
    assert first_audit["execution_model"] == "next_bar_close"
    assert first_audit["bar_timestamp"] is not None

    # 3. Check write_backtest_report_file and read_backtest_report_file
    report_path = write_backtest_report_file(
        result_id=101, request=req, bt_result=out, metrics_json=out["metrics_json"]
    )
    assert report_path.exists()
    report_data = read_backtest_report_file(101)
    assert "fill_execution_audits" in report_data
    assert report_data["fill_execution_audits"] == audits


def test_c_legacy_report_file_compatibility(tmp_path, monkeypatch):
    """Task C: Reading older report files without fill_execution_audits field defaults safely to empty list."""
    from server.services.backtest_views.execution import read_backtest_report_file

    rep_dir = tmp_path / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KARKINOS_BACKTEST_REPORT_DIR", str(rep_dir))

    legacy_payload = {
        "schema_version": "karkinos.backtest_report.v1",
        "id": 9999,
        "generated_at": "2025-01-01T00:00:00Z",
        "config": {},
        "metrics": {},
        "equity_curve": [],
        "metrics_json": {},
        "cost_summary": {},
        "evidence": {},
        "fills": [],
    }
    legacy_file = rep_dir / "backtest-result-9999.json"
    legacy_file.write_text(json.dumps(legacy_payload), encoding="utf-8")

    data = read_backtest_report_file(9999)
    assert data["id"] == 9999
    assert data["fill_execution_audits"] == []
