"""Reproduction and regression tests for P0-4B remediation issues (A1-A3, B1-B6, Task C)."""

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType, Symbol
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetSnapshot,
)
from data.dataset.reader import read_daily_bar_dataset
from data.market.capture import capture_provider_payload
from data.market.contracts import DailyBarRequest
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market_calendar import (
    build_static_market_calendar_snapshot,
    market_calendar_day_from_payload,
)
from data.storage.objects import ContentAddressedObjectStore
from server.contracts.http.strategy_models import (
    BacktestRequest,
    BacktestSweepRequest,
)
from server.routes import backtest as backtest_routes
from server.services.backtest_views.execution import (
    read_backtest_report_file,
    run_single_backtest,
    write_backtest_report_file,
)
from server.services.research import dataset_inputs
from server.services.research.dataset_inputs import (
    ResearchDatasetError,
    compute_execution_context_id,
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
# Task A: Status date & unknown value semantics (A1-A3)
# ---------------------------------------------------------------------------


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


def test_a_future_master_does_not_override_active_session_status_or_supply_st(
    tmp_path,
):
    """Task A: Future master (2025-02-10) with omitted status_session_date must not supply ST or override verified active session (2025-01-08)."""
    from tests.server.test_backtest_dataset_inputs import (
        MockCalendarDb,
        _verified_day,
    )

    day5 = DATES[-1]
    cal = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2025,
        provider="test",
        open_dates=[d.isoformat() for d in DATES],
    )

    for is_st_val, trade_status_val in [(False, "1"), (True, "1"), (False, "0")]:
        sub_root = tmp_path / f"st_{is_st_val}_ts_{trade_status_val}"
        root = sub_root / "research"
        store = ContentAddressedObjectStore(root / "objects")
        partitions = []
        memberships = []

        day_prices = ["10.0", "10.0", "10.0", "10.8"]
        for day, p_close in zip(DATES[:-1], day_prices):
            ref = _verified_day(root, day, instruments=(STOCK,), close=p_close)
            daily = read_daily_bar_dataset(store, ref)
            partitions.extend(
                replace(p, instruments=(STOCK,)) for p in daily.snapshot.partitions
            )
            master_at = datetime(
                day.year, day.month, day.day, 8, 0, tzinfo=timezone.utc
            )
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

        ref5 = _verified_day(root, day5, instruments=(STOCK,), close="10.8")
        daily5 = read_daily_bar_dataset(store, ref5)
        partitions.extend(
            replace(p, instruments=(STOCK,)) for p in daily5.snapshot.partitions
        )

        master_at5 = datetime(
            day5.year, day5.month, day5.day, 8, 0, tzinfo=timezone.utc
        )
        cap_request = DailyBarRequest((STOCK,), day5, day5).to_capture_request()
        cap_payload = {
            "schema": "baostock.history_k_data_plus.rows.v2",
            "request": {
                "frequency": "d",
                "adjustflag": "3",
                "start_date": str(day5),
                "end_date": str(day5),
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
                            str(day5),
                            "sh.600000",
                            "10.8",
                            "10.8",
                            "10.8",
                            "10.8",
                            "100",
                            "1000",
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
            started_at=master_at5,
            completed_at=master_at5,
            record_count=1,
        )

        future_meta_row = {
            "symbol": "600000",
            "display_name": "浦发银行",
            "list_status": "L",
            "list_date": "1999-11-10",
            "trade_status": trade_status_val,
            "is_st": is_st_val,
        }
        future_master = {
            "schema_version": "karkinos.market_universe_snapshot.v2",
            "trade_date": "2025-02-10",
            "membership_basis": "current_active_stock_master",
            "availability_basis": "capture_completed_at",
            "observation_basis": "adapter_response",
            "capture_started_at": master_at5.isoformat(),
            "capture_completed_at": master_at5.isoformat(),
            "available_at": master_at5.isoformat(),
            "members": [{"symbol": "600000"}],
            "member_metadata": [future_meta_row],
        }
        fut_ref = store.put_bytes(json.dumps(future_master).encode())
        memberships.append(
            DailyBarDatasetMembership(
                day5, (STOCK,), master_at5, (fut_ref.object_id, cap.capture_id)
            )
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
        dataset_ref = publish_daily_bar_dataset_manifest(store, snapshot)
        db = MockCalendarDb(sub_root, cal)

        req_strict = BacktestRequest(
            strategy="dual_ma",
            dataset_id=dataset_ref.dataset_id,
            start_date=DATES[0].isoformat(),
            end_date=DATES[-1].isoformat(),
            initial_cash=100000.0,
            params={"short_period": 2, "long_period": 3},
            strict_security_status=True,
        )
        prepared_strict = prepare_dataset_backtest_inputs(req_strict, db=db)
        sec_status = prepared_strict[2]["execution_context"]["security_status"]
        day5_str = day5.isoformat()
        assert sec_status[day5_str]["600000"]["trade_status"] == "1"
        assert sec_status[day5_str]["600000"]["is_suspended"] is False
        assert sec_status[day5_str]["600000"]["is_st"] is None

        out_strict = run_single_backtest(
            req_strict,
            SimpleNamespace(),
            db=db,
            preloaded_dataset_inputs=prepared_strict,
        )
        assert (
            out_strict["metrics_json"]["execution_timing"][
                "unverified_state_blocked_count"
            ]
            >= 1
        )
        assert len(out_strict["fills"]) == 0

        req_exp = BacktestRequest(
            strategy="dual_ma",
            dataset_id=dataset_ref.dataset_id,
            start_date=DATES[0].isoformat(),
            end_date=DATES[-1].isoformat(),
            initial_cash=100000.0,
            params={"short_period": 2, "long_period": 3},
            strict_security_status=False,
        )
        prepared_exp = prepare_dataset_backtest_inputs(req_exp, db=db)
        out_exp = run_single_backtest(
            req_exp,
            SimpleNamespace(),
            db=db,
            preloaded_dataset_inputs=prepared_exp,
        )
        assert len(out_exp["fills"]) >= 1
        fill = out_exp["fills"][0]
        # Price is 10.8 + 5 bps slippage = 10.8054. Exceeds 5% ST limit (10.5), verifying 10% limit applies
        assert abs(fill["fill_price"] - 10.8054) < 1e-4
        assert fill["fill_price"] > 10.5


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


# ---------------------------------------------------------------------------
# Task B: Calendar core contracts & fixed execution identity (B1-B6)
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
        strategy="dual_ma",
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
    setattr(db, "_cal", cal2)

    def fail_if_db_called(*args, **kwargs):
        raise RuntimeError("latest_db_must_not_be_queried_during_pinned_replay")

    db.get_market_calendar_snapshot_sync = fail_if_db_called

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


def test_b5_execution_context_failure_modes_and_scope_rejection(tmp_path, monkeypatch):
    """B5: Exhaustive coverage of execution context failure modes and scope rejection."""
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
    dataset1 = _make_dataset_with_evidence(tmp_path, DATES, prices)

    # 1. Non-existent ID fails closed
    fake_ctx_id = (
        "ctx-sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    req_fake = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset1.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        execution_context_id=fake_ctx_id,
    )
    with pytest.raises(ResearchDatasetError, match="execution_context_not_found"):
        prepare_dataset_backtest_inputs(req_fake, db=db)

    # Prepare a valid context
    req_valid = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset1.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        strict_security_status=False,
    )
    _, _, binding_valid, _ = prepare_dataset_backtest_inputs(req_valid, db=db)
    valid_ctx_id = binding_valid["execution_context_id"]
    assert valid_ctx_id is not None

    # 2. Corrupted stored object (non-JSON object in store)
    store = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    corrupted_ref = store.put_bytes(b"invalid_corrupted_json{{{")
    with pytest.raises(ResearchDatasetError, match="execution_context_corrupted"):
        prepare_dataset_backtest_inputs(
            req_valid.model_copy(
                update={"execution_context_id": f"ctx-{corrupted_ref.object_id}"}
            ),
            db=db,
        )

    # 3. Content hash mismatch: valid JSON object with non-canonical formatting
    non_canonical_ref = store.put_bytes(b'{\n  "dataset_id": "test"\n}')
    with pytest.raises(
        ResearchDatasetError, match="execution_context_content_hash_mismatch"
    ):
        prepare_dataset_backtest_inputs(
            req_valid.model_copy(
                update={"execution_context_id": f"ctx-{non_canonical_ref.object_id}"}
            ),
            db=db,
        )

    # 4. Strict mode conflict: exploratory context (False) vs explicit request (True)
    req_conflict = req_valid.model_copy(
        update={
            "execution_context_id": valid_ctx_id,
            "strict_security_status": True,
        }
    )
    with pytest.raises(
        ResearchDatasetError, match="execution_context_strict_mode_conflict"
    ):
        prepare_dataset_backtest_inputs(req_conflict, db=db)

    # 5. Dataset incompatibility: context from Dataset 1 cannot apply to Dataset 2
    dataset2 = _make_dataset_with_evidence(
        tmp_path / "d2", DATES, [11.0, 11.0, 11.0, 11.5, 11.5]
    )
    req_d2 = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset2.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        execution_context_id=valid_ctx_id,
    )
    canonical_dict = {
        k: v
        for k, v in binding_valid["execution_context"].items()
        if k not in ("execution_context_id", "content_hash")
    }
    store2 = ContentAddressedObjectStore(tmp_path / "d2" / "research" / "objects")
    store2.put_bytes(
        json.dumps(canonical_dict, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    with pytest.raises(
        ResearchDatasetError, match="execution_context_dataset_incompatible"
    ):
        prepare_dataset_backtest_inputs(req_d2, db=MockCalendarDb(tmp_path / "d2", cal))

    # 6. First-time store write failure fails immediately without claiming pinned context
    def fail_put_bytes(*args, **kwargs):
        raise IOError("simulated_disk_full")

    monkeypatch.setattr(ContentAddressedObjectStore, "put_bytes", fail_put_bytes)
    req_new = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset1.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
    )
    with pytest.raises(
        ResearchDatasetError, match="execution_context_persistence_failed"
    ):
        prepare_dataset_backtest_inputs(req_new, db=db)


def test_b_sweep_and_chronological_pass_through_execution_context_and_strict_mode(
    tmp_path, monkeypatch
):
    """Task B-c: Public /sweep endpoint carries execution_context_id and strict_security_status to all candidates and chronological runs."""
    import asyncio

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

    req_init = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        strict_security_status=True,
    )
    _, _, binding_init, _ = prepare_dataset_backtest_inputs(req_init, db=db)
    ctx_id = binding_init["execution_context_id"]
    assert ctx_id is not None

    router = backtest_routes.create_router()
    endpoint = next(
        r.endpoint
        for r in router.routes
        if getattr(r, "path", None) == "/api/backtest/sweep"
    )

    saved_configs = []

    class FakeDb:
        def __init__(self, cal_db):
            self.path = cal_db.path
            self._cal = cal_db._cal
            self.get_market_calendar_snapshot_sync = (
                cal_db.get_market_calendar_snapshot_sync
            )

        async def save_backtest_result(self, **kwargs):
            saved_configs.append(json.loads(kwargs["config_json"]))
            return 900 + len(saved_configs)

    fake_state = SimpleNamespace(
        config=SimpleNamespace(assets=[]),
        db=FakeDb(db),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)

    # 1. Standard sweep: candidates inherit execution_context_id and strict_security_status
    sweep_req = BacktestSweepRequest(
        strategy="dual_ma",
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        param_grid={"short_period": [2], "long_period": [3, 4]},
        execution_context_id=ctx_id,
        strict_security_status=True,
    )
    resp = asyncio.run(endpoint(sweep_req))
    assert resp.tested_count == 2
    assert len(saved_configs) == 2
    for cfg in saved_configs:
        assert cfg["execution_context_id"] == ctx_id
        assert cfg["strict_security_status"] is True

    # 2. Chronological sweep with test_start_date
    saved_configs.clear()
    chrono_sweep_req = BacktestSweepRequest(
        strategy="dual_ma",
        dataset_id=dataset_res.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        test_start_date=DATES[3],
        param_grid={"short_period": [1], "long_period": [2]},
        execution_context_id=ctx_id,
        strict_security_status=True,
    )
    resp_chrono = asyncio.run(endpoint(chrono_sweep_req))
    assert resp_chrono.chronological_validation is not None
    assert resp_chrono.chronological_validation["execution_context_id"] == ctx_id
    assert resp_chrono.chronological_validation["strict_security_status"] is True
    assert len(saved_configs) >= 1
    for cfg in saved_configs:
        assert cfg["execution_context_id"] == ctx_id
        assert cfg["strict_security_status"] is True


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
        strategy="dual_ma",
        dataset_id="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        start_date="2025-01-02",
        end_date="2025-01-08",
    )
    with pytest.raises(TypeError, match="internal_bug_type_error"):
        prepare_dataset_backtest_inputs(req, db=db)
    assert calls == [db]


# ---------------------------------------------------------------------------
# Task C: Execution audit metadata and report file persistence
# ---------------------------------------------------------------------------


def test_c_service_output_and_report_metadata_audit_consistency(tmp_path, monkeypatch):
    """Task C: run_single_backtest output and write_backtest_report_file retain fill_execution_audits."""
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


def test_r1_legacy_context_lacking_dataset_id_rejected(tmp_path):
    """R1: Legacy execution context lacking dataset_id must be rejected without fallback to DB."""
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

    # 1. Dataset A
    dataset_a = _make_dataset_with_evidence(tmp_path, DATES, prices)
    req_a = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset_a.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        strict_security_status=False,
    )
    _, _, binding_a, _ = prepare_dataset_backtest_inputs(req_a, db=db)
    valid_ctx_id = binding_a["execution_context_id"]

    # 2. Construct legacy c12 production context (strip dataset_id)
    legacy_ctx = dict(binding_a["execution_context"])
    legacy_ctx.pop("dataset_id", None)
    legacy_ctx.pop("execution_context_id", None)
    legacy_ctx.pop("content_hash", None)
    legacy_id, _ = compute_execution_context_id(legacy_ctx)
    store = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    store.put_bytes(
        json.dumps(legacy_ctx, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )

    # Mock DB calendar getter to ensure no fallback query
    def fail_if_db_called(*args, **kwargs):
        raise RuntimeError("latest_db_must_not_be_queried_during_pinned_replay")

    db.get_market_calendar_snapshot_sync = fail_if_db_called

    # 3. Dataset B tries to use legacy context (cross-dataset reuse of legacy context)
    dataset_b = _make_dataset_with_evidence(
        tmp_path / "d_b", DATES, [11.0, 11.0, 11.0, 11.5, 11.5]
    )
    req_b = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset_b.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        execution_context_id=legacy_id,
    )
    store_b = ContentAddressedObjectStore(tmp_path / "d_b" / "research" / "objects")
    store_b.put_bytes(
        json.dumps(legacy_ctx, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )

    with pytest.raises(
        ResearchDatasetError, match="execution_context_dataset_unverified"
    ):
        prepare_dataset_backtest_inputs(req_b, db=MockCalendarDb(tmp_path / "d_b", cal))

    # 4. Dataset A itself trying to use legacy context is also rejected (unverified domain)
    req_a_legacy = req_a.model_copy(update={"execution_context_id": legacy_id})
    with pytest.raises(
        ResearchDatasetError, match="execution_context_dataset_unverified"
    ):
        prepare_dataset_backtest_inputs(req_a_legacy, db=db)

    # 5. Positive control: modern context with dataset_id replays successfully on same dataset
    req_a_valid = req_a.model_copy(update={"execution_context_id": valid_ctx_id})
    _, _, binding_replay, _ = prepare_dataset_backtest_inputs(req_a_valid, db=db)
    assert binding_replay["execution_context_id"] == valid_ctx_id

    # 6. Negative control: modern context with dataset_id rejected on different dataset
    req_b_cross = req_b.model_copy(update={"execution_context_id": valid_ctx_id})
    canonical_dict = {
        k: v
        for k, v in binding_a["execution_context"].items()
        if k not in ("execution_context_id", "content_hash")
    }
    store_b.put_bytes(
        json.dumps(canonical_dict, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    with pytest.raises(
        ResearchDatasetError, match="execution_context_dataset_incompatible"
    ):
        prepare_dataset_backtest_inputs(
            req_b_cross, db=MockCalendarDb(tmp_path / "d_b", cal)
        )


def test_r2_invalid_payload_rejected_without_fallback(tmp_path):
    """R2: Pinned execution context with invalid payload (e.g. b'null') rejected without falling into initial generation."""
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
    dataset = _make_dataset_with_evidence(tmp_path, DATES, prices)
    store = ContentAddressedObjectStore(tmp_path / "research" / "objects")

    # Mock DB calendar getter to ensure no fallback query
    def fail_if_db_called(*args, **kwargs):
        raise RuntimeError("latest_db_must_not_be_queried_on_pinned_payload_error")

    db.get_market_calendar_snapshot_sync = fail_if_db_called

    # 1. Real null object in store
    null_ref = store.put_bytes(b"null")
    req_null = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        execution_context_id=f"ctx-{null_ref.object_id}",
    )
    with pytest.raises(ResearchDatasetError, match="execution_context_invalid_payload"):
        prepare_dataset_backtest_inputs(req_null, db=db)

    # 2. Real array object in store
    array_ref = store.put_bytes(b'["not", "a", "dict"]')
    req_array = req_null.model_copy(
        update={"execution_context_id": f"ctx-{array_ref.object_id}"}
    )
    with pytest.raises(ResearchDatasetError, match="execution_context_invalid_payload"):
        prepare_dataset_backtest_inputs(req_array, db=db)

    # 3. Positive control: when execution_context_id is None, initial generation succeeds
    db.get_market_calendar_snapshot_sync = MockCalendarDb(
        tmp_path, cal
    ).get_market_calendar_snapshot_sync
    req_gen = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        execution_context_id=None,
    )
    _, _, binding_gen, _ = prepare_dataset_backtest_inputs(req_gen, db=db)
    assert binding_gen["execution_context_id"] is not None


def test_r3_preloaded_inputs_must_respect_requested_context_identity(
    tmp_path, monkeypatch
):
    """R3: run_single_backtest preloaded inputs must reject mismatched context identity before engine run."""
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
    dataset = _make_dataset_with_evidence(tmp_path, DATES, prices)
    store = ContentAddressedObjectStore(tmp_path / "research" / "objects")

    # Prepare inputs for context A
    req_a = BacktestRequest(
        strategy="dual_ma",
        dataset_id=dataset.ref.dataset_id,
        start_date=DATES[0].isoformat(),
        end_date=DATES[-1].isoformat(),
        initial_cash=100000.0,
        params={"short_period": 2, "long_period": 3},
        strict_security_status=False,
    )
    prepared_a = prepare_dataset_backtest_inputs(req_a, db=db)
    ctx_a_id = prepared_a[2]["execution_context_id"]

    # Create another valid context B for the same dataset
    ctx_b_payload = dict(prepared_a[2]["execution_context"])
    ctx_b_payload["trading_calendar"] = {
        **ctx_b_payload["trading_calendar"],
        "provider": "context_b_provider",
    }
    ctx_b_payload.pop("execution_context_id", None)
    ctx_b_payload.pop("content_hash", None)
    ctx_b_id, ctx_b_hash = compute_execution_context_id(ctx_b_payload)
    canonical_b = {
        k: v
        for k, v in ctx_b_payload.items()
        if k not in ("execution_context_id", "content_hash")
    }
    store.put_bytes(
        json.dumps(canonical_b, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )

    # Mock BacktestEngine.run to prove rejection happens BEFORE engine run
    def fail_if_engine_run(*args, **kwargs):
        raise RuntimeError("engine_must_not_run_when_context_mismatched")

    from backtest.engine import BacktestEngine

    monkeypatch.setattr(BacktestEngine, "run", fail_if_engine_run)

    # 1. Request B + prepared A: mismatch rejected before engine execution
    req_b = req_a.model_copy(update={"execution_context_id": ctx_b_id})
    with pytest.raises(
        ResearchDatasetError, match="preloaded_execution_context_mismatch"
    ):
        run_single_backtest(
            req_b,
            SimpleNamespace(),
            db=db,
            preloaded_dataset_inputs=prepared_a,
        )

    # Restore engine run
    monkeypatch.undo()

    # 2. Positive case: matching ID (ctx- prefixed) succeeds
    req_match = req_a.model_copy(update={"execution_context_id": ctx_a_id})
    out_match = run_single_backtest(
        req_match,
        SimpleNamespace(),
        db=db,
        preloaded_dataset_inputs=prepared_a,
    )
    assert (
        out_match["metrics_json"]["dataset_binding"]["execution_context_id"] == ctx_a_id
    )

    # 3. Positive case: matching ID (raw content hash without ctx-) succeeds
    raw_hash = ctx_a_id.removeprefix("ctx-")
    req_raw = req_a.model_copy(update={"execution_context_id": raw_hash})
    out_raw = run_single_backtest(
        req_raw,
        SimpleNamespace(),
        db=db,
        preloaded_dataset_inputs=prepared_a,
    )
    assert (
        out_raw["metrics_json"]["dataset_binding"]["execution_context_id"] == ctx_a_id
    )

    # 4. Positive case: omitted ID (None) inherits prepared context identity
    req_none = req_a.model_copy(update={"execution_context_id": None})
    out_none = run_single_backtest(
        req_none,
        SimpleNamespace(),
        db=db,
        preloaded_dataset_inputs=prepared_a,
    )
    assert (
        out_none["metrics_json"]["dataset_binding"]["execution_context_id"] == ctx_a_id
    )
