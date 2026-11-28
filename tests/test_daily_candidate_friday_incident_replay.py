"""Isolated replay and acceptance suite for the 2026-11-27 decision incident."""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from core.event_bus import EventBus
from data.providers.tdx import TdxRuntimeSettings
from data.store import DataStore
from notification.notifier import build_notifier
from server.ai_runtime.contracts import content_fingerprint
from server.app import create_app
from server.bootstrap import load_runtime_config
from server.bridge import EventBusBridge
from server.config import ServerConfig
from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.dependencies import AppState
from server.persistence.valuation_publication_recovery import (
    UNPUBLISHED_RECOVERY_CONFIRMATION,
    discard_proven_unpublished_quote_refreshes,
    unresolved_publications,
)
from server.persistence.valuation_recovery_preview import (
    preview_unpublished_quote_recovery,
)
from server.services.automation.automation_control import AutomationControlService
from server.services.decision.daily_decision_background_schedule import (
    project_daily_candidate_background_schedule,
)
from server.services.decision.daily_decision_evidence_automation import (
    build_daily_decision_evidence_automation_service,
)
from server.services.decision.daily_decision_evidence_orchestration import (
    run_claimed_background_attempt,
)
from server.services.decision.decision_application import (
    run_batch_pre_trade_risk_for_state,
)
from server.services.decision.operations_projection import (
    current_decision_and_trading_plan,
)
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    normalize_a_share_members,
)
from server.services.market.quotes import (
    build_quote_ingestion_command,
    persist_quote_ingestion,
)
from server.services.research.datasets import ResearchDatasetService
from server.services.risk.trading_controls import TradingControlState
from server.services.strategy_scan.promoted_strategy_universe_scan import (
    PromotedStrategyUniverseScanService,
)
from server.ws.hub import ConnectionHub

_SH = ZoneInfo("Asia/Shanghai")
_DECISION_DATE = "2026-11-27"
_MARKET_DATE = "2026-11-26"
_NEXT_DATE = "2026-11-30"
_PRE_WINDOW_RECOVERY_SH = datetime(2026, 11, 27, 9, 25, 0, tzinfo=_SH)
_IN_WINDOW_SH = datetime(2026, 11, 27, 9, 37, 0, tzinfo=_SH)
_RECOVERY_SH = datetime(2026, 11, 27, 12, 1, 57, tzinfo=_SH)
_POST_WINDOW_SH = datetime(2026, 11, 27, 19, 30, 0, tzinfo=_SH)
_MONDAY_IN_WINDOW_SH = datetime(2026, 11, 30, 9, 37, 0, tzinfo=_SH)
_INCIDENT_RUN_ID = (
    "fund_nav_sync:2026-11-26T09:30:16.870019:60fd45a0b9884a35aef2036c19d8a59a"
)
_STRATEGY_ID = "ai_formula_shadow:friday-replay-winner"


def _seed_calendar(db: AppDatabase) -> list[str]:
    history_dates = [
        value.date().isoformat()
        for value in pd.bdate_range(end=_MARKET_DATE, periods=75)
    ]
    trading_dates = set(history_dates) | {_DECISION_DATE, _NEXT_DATE}
    calendar_days: list[dict[str, Any]] = []
    current = date(2026, 1, 1)
    while current.year == 2026:
        day_str = current.isoformat()
        is_trading = day_str in trading_dates
        calendar_days.append(
            {
                "date": day_str,
                "is_trading_day": is_trading,
                "day_type": "trading" if is_trading else "closed",
                "reason_code": "trading_day" if is_trading else "closed",
            }
        )
        current += timedelta(days=1)
    source_fp = "c" * 64
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "fixture",
            "schema_version": "karkinos.market_calendar.v1",
            "status": "available",
            "trading_day_count": len(trading_dates),
            "closed_day_count": len(calendar_days) - len(trading_dates),
            "source_fingerprint": source_fp,
            "days": calendar_days,
            "limitations": [],
        }
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=source_fp,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="d" * 64,
        verified_by="friday-replay-test",
    )
    return history_dates


def _freeze_market(store: DataStore, market_dates: list[str]) -> list[str]:
    symbols = [f"{600000 + index:06d}" for index in range(1, 51)]
    store.save_market_universe_snapshot(
        trade_date=_MARKET_DATE,
        provider_name="fixture",
        members=normalize_a_share_members(symbols),
        capture_started_at=datetime(2026, 11, 26, 15, 59, tzinfo=_SH),
        capture_completed_at=datetime(2026, 11, 26, 16, 0, tzinfo=_SH),
        source_metadata=[
            {"symbol": sym, "display_name": f"样本股票{sym}"} for sym in symbols
        ],
    )
    for market_date in market_dates:
        closes = [10.0 if sym == "600001" else 20.0 for sym in symbols]
        store.ingest_market_daily_batch(
            trade_date=market_date,
            provider_name="fixture",
            bars=pd.DataFrame(
                {
                    "symbol": symbols,
                    "timestamp": [pd.Timestamp(market_date)] * len(symbols),
                    "open": closes,
                    "high": [price + 0.2 for price in closes],
                    "low": [price - 0.2 for price in closes],
                    "close": closes,
                    "volume": [1_000_000 + idx for idx in range(len(symbols))],
                    "amount": [10_000_000 + idx * 1_000 for idx in range(len(symbols))],
                }
            ),
        )
    return symbols


def _formula(*, produces_signals: bool) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.ai.formula_ast.v1",
        "entry": {
            "op": "gt" if produces_signals else "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 0},
        },
        "exit": {
            "op": "lt" if produces_signals else "gt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 11 if produces_signals else 1_000},
        },
        "position_size": {
            "op": "max_weight",
            "input": {"op": "equal_weight"},
            "value": 0.1,
        },
    }


def _seed_reconciled_statement(
    db: AppDatabase,
    *,
    cash_balance: float,
    stock_qty: float,
    stock_px: float,
    fund_qty: float,
    fund_px: float,
    snapshot_date: str = _DECISION_DATE,
) -> str:
    stock_gross = stock_qty * stock_px
    fund_gross = fund_qty * fund_px
    deposit = cash_balance + stock_gross + fund_gross
    cash_after_stock = deposit - stock_gross
    rows = [
        "event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method",
        f"dep-1,transfer_in,2026-11-20T08:30:00+08:00,2026-11-20,,,,CNY,0,0,{deposit:.2f},0.00,0.00,{deposit:.2f},{deposit:.2f},,,deposit,0.00,",
        f"buy-stock,trade_buy,2026-11-20T10:00:00+08:00,2026-11-20,600001,样本股票600001,stock,CNY,{stock_qty:g},{stock_px:.2f},{stock_gross:.2f},0.00,0.00,-{stock_gross:.2f},{cash_after_stock:.2f},{stock_qty:g},{stock_px:.2f},buy,0.00,moving_average_buy_cost",
        f"buy-fund,trade_buy,2026-11-20T10:05:00+08:00,2026-11-20,018125,样本基金018125,fund,CNY,{fund_qty:g},{fund_px:.4f},{fund_gross:.2f},0.00,0.00,-{fund_gross:.2f},{cash_balance:.2f},{fund_qty:g},{fund_px:.4f},buy,0.00,moving_average_buy_cost",
        f"cash-snap-{snapshot_date},cash_snapshot,{snapshot_date}T08:45:00+08:00,{snapshot_date},,,,CNY,0,0,0.00,0.00,0.00,0.00,{cash_balance:.2f},,,cash,0.00,",
        f"pos-600001-{snapshot_date},position_snapshot,{snapshot_date}T08:45:00+08:00,{snapshot_date},600001,样本股票600001,stock,CNY,0,0,0.00,0.00,0.00,0.00,{cash_balance:.2f},{stock_qty:g},{stock_px:.2f},pos,0.00,moving_average_buy_cost",
        f"pos-018125-{snapshot_date},position_snapshot,{snapshot_date}T08:45:00+08:00,{snapshot_date},018125,样本基金018125,fund,CNY,0,0,0.00,0.00,0.00,0.00,{cash_balance:.2f},{fund_qty:g},{fund_px:.4f},pos,0.00,moving_average_buy_cost",
    ]
    imported = BrokerEvidenceRepository(db._path).save_preview(
        parse_broker_statement_csv("\n".join(rows) + "\n"),
        source_name=f"friday-replay-broker-{snapshot_date}.csv",
    )
    return imported.import_run_id


def _ingest_morning_stock_poll(
    db: AppDatabase,
    *,
    symbols: list[str],
    quote_timestamp: str,
    captured_at: str,
    run_id: str,
    price_fn: Callable[[str], float] | None = None,
) -> None:
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at=captured_at,
        trigger="scheduler_poll",
        provider="tencent",
        asset_type="stock",
        symbol_count=len(symbols),
        status="running",
        metadata={
            "requested_symbols": symbols,
            "instrument_types": ["stock"] * len(symbols),
        },
    )
    for sym in symbols:
        price = (
            price_fn(sym)
            if price_fn is not None
            else (10.0 if sym == "600001" else 20.0)
        )
        db.persist_quote_ingestion_sync(
            QuoteIngestionCommand(
                symbol=sym,
                asset_type="stock",
                price=price,
                volume=0.0,
                quote_timestamp=quote_timestamp,
                captured_at=captured_at,
                quote_source="tencent_realtime_quote",
                provider_name="tencent",
                provider_status="live",
                quote_status="live",
                captured_reason="scheduler_poll",
                fetch_run_id=run_id,
            )
        )
    db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at=captured_at,
        status="success",
        success_count=len(symbols),
        failure_count=0,
        metadata={
            "requested_symbols": symbols,
            "instrument_types": ["stock"] * len(symbols),
        },
    )


def _build_strategy_gate(strategy_fp: str) -> dict[str, Any]:
    constraints = {
        "schema_version": "karkinos.ai.strategy_operating_constraints.v1",
        "candidate_id": "friday-replay-winner",
        "strategy_artifact_fingerprint": strategy_fp,
        "source_backup_artifact_fingerprint": "2" * 64,
        "economic_hypothesis": "Replay hypothesis.",
        "risk_impact": "Loss remains possible under reviewed limits.",
        "failure_conditions": ["Excess return turns non-positive."],
        "limitations": ["Historical replay only."],
        "anti_lookahead_assumptions": ["Closed persisted market bars only."],
        "automatic_enforcement_enabled": False,
        "human_review_required": True,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    constraints["evidence_fingerprint"] = content_fingerprint(constraints)
    binding = {
        "schema_version": "karkinos.ai.daily_strategy_promotion_binding.v2",
        "run_id": "ai-shadow-research:2026-10-13:replay",
        "market_date": "2026-10-13",
        "winner_candidate_id": "friday-replay-winner",
        "selection_id": "selection-replay",
        "selection_fingerprint": "1" * 64,
        "backup_id": "backup-replay",
        "backup_artifact_fingerprint": "2" * 64,
        "operating_constraints": constraints,
        "contains_private_account_identifiers": False,
        "contains_broker_export_rows": False,
        "does_not_change_capital_authority": True,
        "authority_effect": "research_only",
    }
    return {
        "schema_version": "karkinos.strategy_order_generation_gate.v1",
        "status": "pass",
        "as_of_date": _MARKET_DATE,
        "strategy_id": _STRATEGY_ID,
        "blockers": [],
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "paper_shadow_evaluation_only": True,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
        "promotion": {
            "status": "pass",
            "stage": "paper_shadow",
            "gate_status": "paper_shadow_enabled",
            "live_like_enabled": False,
            "human_reviewer": "owner",
            "human_review_note_recorded": True,
            "comparison_fingerprint": "e" * 64,
            "human_approval_id": "approval-replay",
            "dataset_replay_fingerprint": "0" * 64,
            "daily_strategy_artifact_binding": binding,
            "strategy_advancement_gate_fingerprint": "a" * 64,
            "fee_schedule_binding": {
                "fee_schedule_review_fingerprint": "b" * 64,
            },
            "dataset_replay": {
                "status": "pass",
                "blockers": [],
                "evidence_fingerprint": "f" * 64,
                "persisted_market_bars_only": True,
                "provider_contacted": False,
                "baseline_manifest_matches_candidate": True,
                "baseline_snapshot_id": "dataset-replay",
                "candidate_snapshot_id": "dataset-replay",
            },
            "comparison_context": {
                "baseline_snapshot_id": "sha256:" + "3" * 64,
                "candidate_snapshot_id": "sha256:" + "3" * 64,
                "comparison_fingerprint": "4" * 64,
            },
        },
    }


def _patch_persistence_modules(
    monkeypatch: pytest.MonkeyPatch, target_sh: datetime
) -> None:
    import server.db as db_mod
    import server.persistence.connection as conn_mod
    import server.persistence.event_log as ev_log_mod

    fixed_dt = _fixed_datetime_type(lambda fixed=target_sh: fixed)
    for module in (db_mod, conn_mod, ev_log_mod):
        monkeypatch.setattr(module, "datetime", fixed_dt)


def _stage_unpublished_fund_estimate_incident(
    db: AppDatabase,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    run_now = datetime(2026, 11, 26, 9, 30, 16, 870019, tzinfo=_SH)
    started_at = run_now.isoformat()
    finished_at = (run_now + timedelta(seconds=2)).isoformat()
    with monkeypatch.context() as scoped:
        _patch_persistence_modules(scoped, run_now)
        db.create_quote_fetch_run(
            run_id=_INCIDENT_RUN_ID,
            started_at=started_at,
            trigger="fund_nav_sync",
            provider="akshare",
            asset_type="open_end_fund",
            symbol_count=1,
            status="running",
            metadata={
                "requested_symbols": ["018125"],
                "instrument_types": ["open_end_fund"],
            },
        )
        db.persist_quote_ingestion_sync(
            QuoteIngestionCommand(
                symbol="018125",
                asset_type="open_end_fund",
                price=1.8123,
                previous_close=1.8028,
                volume=0.0,
                quote_timestamp="2026-11-25T15:00:00+08:00",
                captured_at=started_at,
                quote_source="sina_fund_estimate",
                provider_name="sina",
                provider_status="live",
                quote_status="live",
                captured_reason="fund_nav_sync",
                nav_date="2026-11-25",
                fetch_run_id=_INCIDENT_RUN_ID,
            )
        )
        finished = db.finish_quote_fetch_run(
            run_id=_INCIDENT_RUN_ID,
            finished_at=finished_at,
            status="success",
            success_count=1,
            failure_count=0,
            metadata={
                "requested_symbols": ["018125"],
                "instrument_types": ["open_end_fund"],
            },
        )
    assert finished is not None and finished["status"] == "failed"
    with sqlite3.connect(db.path) as conn:
        failures = unresolved_publications(conn)
    assert len(failures) == 1
    return str(failures[0]["incident_ref"])


def _fixed_datetime_type(clock: Callable[[], datetime]) -> type[datetime]:
    class FixedDT(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            target_sh = clock()
            if tz is timezone.utc:
                return target_sh.astimezone(timezone.utc)
            if tz is None:
                return target_sh.replace(tzinfo=None)
            return target_sh.astimezone(tz)

    return FixedDT


def _patch_clocks(
    monkeypatch: pytest.MonkeyPatch, target_sh: datetime | Callable[[], datetime]
) -> None:
    clock: Callable[[], datetime] = (
        target_sh if callable(target_sh) else (lambda fixed=target_sh: fixed)
    )
    import account_truth.broker_evidence as broker_ev_mod
    import server.account_truth_gate as account_truth_gate
    import server.account_truth_gate_support as account_truth_gate_support
    import server.db as db_mod
    import server.persistence.automation_runs as aut_runs_mod
    import server.persistence.connection as conn_mod
    import server.persistence.event_log as ev_log_mod
    import server.projections.system_readiness as readiness_mod
    import server.routes.decision as decision_route_mod
    import server.services.account.session_truth as session_truth_mod
    import server.services.decision.daily_decision_background_schedule as bg_sched_mod
    import server.services.decision.daily_decision_evidence_automation as ev_auto_mod
    import server.services.decision.daily_decision_evidence_collection as col_mod
    import server.services.decision.daily_decision_evidence_cycle as cyc_mod
    import server.services.decision.daily_decision_evidence_orchestration as orch_mod
    import server.services.decision.daily_decision_evidence_values as ev_val_mod
    import server.services.decision.daily_decision_report as rep_mod
    import server.services.decision.decision_portfolio_projection as port_proj_mod
    import server.services.decision.decision_projection as dec_proj_mod
    import server.services.decision.forward_paper_review as fpr_mod
    import server.services.decision.operations_today as ops_today_mod
    import server.services.decision.recommendation_publication as rec_pub_mod
    import server.services.market.hours as hours_mod
    import server.services.strategy_scan.daily_candidate_quote_freeze as freeze_mod
    import server.services.strategy_scan.outcomes as outcomes_mod
    import server.services.strategy_scan.promoted_strategy_universe_scan as scan_pub_mod
    import server.services.strategy_scan.universe.service as scan_svc_mod
    import server.services.strategy_scan.universe.validation as scan_val_mod

    fixed_dt = _fixed_datetime_type(clock)

    class FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return clock().date()

    for module in (
        broker_ev_mod,
        db_mod,
        conn_mod,
        aut_runs_mod,
        ev_log_mod,
        hours_mod,
        readiness_mod,
        decision_route_mod,
        session_truth_mod,
        bg_sched_mod,
        ev_auto_mod,
        col_mod,
        cyc_mod,
        orch_mod,
        ev_val_mod,
        dec_proj_mod,
        rep_mod,
        fpr_mod,
        ops_today_mod,
        rec_pub_mod,
        outcomes_mod,
        scan_val_mod,
        account_truth_gate,
        account_truth_gate_support,
    ):
        monkeypatch.setattr(module, "datetime", fixed_dt)
    monkeypatch.setattr(port_proj_mod, "date", FixedDate)

    orig_freeze = freeze_mod.DailyCandidateQuoteFreezeService

    class ClockedFreezeService(orig_freeze):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("clock", clock)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        freeze_mod, "DailyCandidateQuoteFreezeService", ClockedFreezeService
    )
    # Keep scanner defaults explicit if anything rebuilds it dynamically
    orig_scan = scan_svc_mod.PromotedStrategyUniverseScanService

    class ClockedScanService(orig_scan):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("clock", clock)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        scan_svc_mod, "PromotedStrategyUniverseScanService", ClockedScanService
    )
    monkeypatch.setattr(
        scan_pub_mod, "PromotedStrategyUniverseScanService", ClockedScanService
    )


def _setup_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    produces_signals: bool,
    target_now: datetime,
    quote_timestamp: str,
    with_unresolved_incident: bool,
    formula_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clock_holder = [target_now]

    def current_clock() -> datetime:
        return clock_holder[0]

    def set_clock(new_now: datetime) -> datetime:
        if new_now < clock_holder[0]:
            raise AssertionError(
                f"chronological clock cannot move backwards: {new_now} < {clock_holder[0]}"
            )
        clock_holder[0] = new_now
        return new_now

    ws = tmp_path.resolve() / "ws"
    data_dir = ws / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KARKINOS_WORKSPACE", str(ws))
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("KARKINOS_HOME", raising=False)

    cfg = load_runtime_config(
        ServerConfig,
        market_calendar_auto_sync=False,
        data_source="fixture",
    )
    app = create_app(runtime_config=cfg)
    state: AppState = app.state.app_state
    db = AppDatabase(data_dir / "app.db")
    db.init_sync()

    market_dates = _seed_calendar(db)
    cfg.start_date = market_dates[0]
    store = DataStore(data_dir / "market")
    symbols = _freeze_market(store, market_dates)

    # Ledger holdings matching reconciled broker statement (cash=190_000, 600001*500, 018125*1000)
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-11-20T08:30:00+08:00",
        amount=196_753.30,
        asset_class="cash",
        source_ref="deposit-initial",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-11-20T10:00:00+08:00",
        amount=5_000.0,
        symbol="600001",
        direction="buy",
        quantity=500.0,
        price=10.0,
        fee_breakdown_json=json.dumps({"commission": 0.0, "total_fee": 0.0}),
        asset_class="stock",
        source_ref="seed-600001",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-11-20T10:05:00+08:00",
        amount=1_753.30,
        symbol="018125",
        direction="buy",
        quantity=1_000.0,
        price=1.7533,
        fee_breakdown_json=json.dumps({"commission": 0.0, "total_fee": 0.0}),
        asset_class="open_end_fund",
        source_ref="seed-018125",
    )
    import_run_id = _seed_reconciled_statement(
        db,
        cash_balance=190_000.0,
        stock_qty=500.0,
        stock_px=10.0,
        fund_qty=1_000.0,
        fund_px=1.7533,
    )

    # 1) 2026-11-25 confirmed NAV published before the 2026-11-26 09:30 estimate incident
    if with_unresolved_incident:
        prior_nav_run = "fund_nav_sync:seed-official-2026-11-25"
        with monkeypatch.context() as scoped:
            _patch_persistence_modules(
                scoped, datetime(2026, 11, 25, 21, 30, 0, tzinfo=_SH)
            )
            db.create_quote_fetch_run(
                run_id=prior_nav_run,
                started_at="2026-11-25T21:30:00+08:00",
                trigger="fund_nav_sync",
                provider="akshare",
                asset_type="open_end_fund",
                symbol_count=1,
                status="running",
                metadata={
                    "requested_symbols": ["018125"],
                    "instrument_types": ["open_end_fund"],
                },
            )
            db.persist_quote_ingestion_sync(
                QuoteIngestionCommand(
                    symbol="018125",
                    asset_type="open_end_fund",
                    price=1.8028,
                    volume=0.0,
                    quote_timestamp="2026-11-25T15:00:00+08:00",
                    captured_at="2026-11-25T21:30:00+08:00",
                    quote_source="eastmoney_fund_page",
                    provider_name="akshare",
                    provider_status="live",
                    quote_status="confirmed",
                    captured_reason="fund_nav_sync",
                    nav_date="2026-11-25",
                    fetch_run_id=prior_nav_run,
                )
            )
            db.finish_quote_fetch_run(
                run_id=prior_nav_run,
                finished_at="2026-11-25T21:30:01+08:00",
                status="success",
                success_count=1,
                failure_count=0,
                metadata={
                    "requested_symbols": ["018125"],
                    "instrument_types": ["open_end_fund"],
                },
            )
        incident_ref = _stage_unpublished_fund_estimate_incident(
            db, monkeypatch=monkeypatch
        )
    else:
        incident_ref = None

    _patch_clocks(monkeypatch, current_clock)

    # 2) Confirmed official NAV for 018125 on 2026-11-26 and live stock quotes
    official_nav_run = "fund_nav_sync:seed-official-2026-11-26"
    db.create_quote_fetch_run(
        run_id=official_nav_run,
        started_at="2026-11-26T21:30:00+08:00",
        trigger="fund_nav_sync",
        provider="akshare",
        asset_type="open_end_fund",
        symbol_count=1,
        status="running",
        metadata={
            "requested_symbols": ["018125"],
            "instrument_types": ["open_end_fund"],
        },
    )
    db.persist_quote_ingestion_sync(
        QuoteIngestionCommand(
            symbol="018125",
            asset_type="open_end_fund",
            price=1.7533,
            volume=0.0,
            quote_timestamp="2026-11-26T15:00:00+08:00",
            captured_at="2026-11-26T21:30:00+08:00",
            quote_source="eastmoney_fund_page",
            provider_name="akshare",
            provider_status="live",
            quote_status="confirmed",
            captured_reason="fund_nav_sync",
            nav_date=_MARKET_DATE,
            fetch_run_id=official_nav_run,
        )
    )
    db.finish_quote_fetch_run(
        run_id=official_nav_run,
        finished_at="2026-11-26T21:30:01+08:00",
        status="success",
        success_count=1,
        failure_count=0,
        metadata={
            "requested_symbols": ["018125"],
            "instrument_types": ["open_end_fund"],
        },
    )
    stock_poll_run = "scheduler_poll:seed"
    db.create_quote_fetch_run(
        run_id=stock_poll_run,
        started_at=quote_timestamp,
        trigger="scheduler_poll",
        provider="tencent",
        asset_type="stock",
        symbol_count=len(symbols[:40]),
        status="running",
        metadata={
            "requested_symbols": symbols[:40],
            "instrument_types": ["stock"] * len(symbols[:40]),
        },
    )
    for sym in symbols[:40]:
        db.persist_quote_ingestion_sync(
            QuoteIngestionCommand(
                symbol=sym,
                asset_type="stock",
                price=10.0 if sym == "600001" else 20.0,
                volume=0.0,
                quote_timestamp=quote_timestamp,
                captured_at=quote_timestamp,
                quote_source="tencent_realtime_quote",
                provider_name="tencent",
                provider_status="live",
                quote_status="live",
                captured_reason="scheduler_poll",
                fetch_run_id=stock_poll_run,
            )
        )
    db.finish_quote_fetch_run(
        run_id=stock_poll_run,
        finished_at=quote_timestamp,
        status="success",
        success_count=len(symbols[:40]),
        failure_count=0,
        metadata={
            "requested_symbols": symbols[:40],
            "instrument_types": ["stock"] * len(symbols[:40]),
        },
    )

    valuation = db.publish_current_valuation_snapshot_sync(now=target_now)
    assert valuation["status"] == "complete"

    db.upsert_strategy_promotion_state_sync(
        strategy_id=_STRATEGY_ID,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={},
    )
    strategy = {
        "formula_ast": (
            copy.deepcopy(formula_override)
            if formula_override is not None
            else _formula(produces_signals=produces_signals)
        ),
        "formula_fingerprint": "sha256:friday-replay",
        "selected_universe": symbols[:40],
    }
    strategy_fp = content_fingerprint(strategy)
    base_gate = _build_strategy_gate(strategy_fp)

    def gate_resolver(_db: Any, requested_strategy_id: str, *, as_of_date: str):
        gate = copy.deepcopy(base_gate)
        gate["strategy_id"] = requested_strategy_id
        gate["as_of_date"] = as_of_date
        return gate, []

    def strategy_loader(*, candidate_id: str, run_id: str) -> dict[str, Any]:
        return {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "strategy_artifact_fingerprint": strategy_fp,
            "strategy": strategy,
        }

    for target_path in (
        "server.services.research.strategy_promotion_pipeline.resolve_strategy_order_generation_gate",
        "server.services.decision.decision_application.resolve_strategy_order_generation_gate",
    ):
        monkeypatch.setattr(target_path, gate_resolver)

    controls = TradingControlState(db=db)
    automation_controls = AutomationControlService(db=db, trading_controls=controls)
    scanner = PromotedStrategyUniverseScanService(
        db=db,
        config=cfg,
        data_store=store,
        policy=MarketUniversePolicy(minimum_master_member_count=40),
        strategy_gate_resolver=gate_resolver,
        strategy_loader=strategy_loader,
        safety_gate_reader=automation_controls.get_status,
        clock=current_clock,
    )

    state.config = cfg
    state.db = db
    state.hub = ConnectionHub()
    state.bridge = EventBusBridge(EventBus(), asyncio.new_event_loop())
    state.notifier = build_notifier(cfg.notification)
    state.trading_controls = controls
    state.research_datasets = ResearchDatasetService(
        data_dir / "research", TdxRuntimeSettings()
    )
    state.data_store = store  # type: ignore[attr-defined]
    state.scanner = scanner  # type: ignore[attr-defined]

    quote_price_overrides: dict[str, float] = {}

    async def offline_quote_refresher(
        state_arg: AppState,
        symbol: str,
        asset_class: Any,
        *,
        fetch_run_id: str | None = None,
    ) -> dict[str, Any]:
        now_dt = current_clock()
        active_quote_ts = (
            quote_timestamp
            if now_dt == target_now
            else f"{now_dt.date().isoformat()}T09:35:45+08:00"
        )
        price = quote_price_overrides.get(symbol, 10.0 if symbol == "600001" else 20.0)
        ac_val = (
            asset_class.value if hasattr(asset_class, "value") else str(asset_class)
        )
        cmd = build_quote_ingestion_command(
            symbol=symbol,
            asset_type=ac_val,
            snapshot={
                "price": price,
                "previous_close": price,
                "timestamp": active_quote_ts,
                "volume": 0.0,
            },
            quote_source="tencent_realtime_quote",
            provider_name="tencent",
            provider_status="live",
            quote_status="live",
            captured_reason="daily_candidate_signal_quote_freeze",
            fetch_run_id=fetch_run_id,
            captured_at=now_dt.isoformat(),
        )
        persist_quote_ingestion(state_arg.db, command=cmd)
        return {
            "symbol": symbol,
            "status": "refreshed",
            "quote_timestamp": active_quote_ts,
            "fetch_run_id": fetch_run_id,
        }

    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=current_decision_and_trading_plan,
        risk_runner=run_batch_pre_trade_risk_for_state,
        quote_refresher=offline_quote_refresher,
    )

    return {
        "app": app,
        "state": state,
        "db": db,
        "store": store,
        "symbols": symbols,
        "service": service,
        "import_run_id": import_run_id,
        "incident_ref": incident_ref,
        "valuation": valuation,
        "set_clock": set_clock,
        "current_clock": current_clock,
        "quote_price_overrides": quote_price_overrides,
    }


async def _run_http(app: Any, coro_fn: Callable[[httpx.AsyncClient], Any]) -> Any:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await coro_fn(client)


def test_friday_pre_recovery_blocks_candidate_publication_and_decision_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 1: Unresolved prior fund-NAV publication incident blocks 09:37 candidates."""
    env = _setup_environment(
        tmp_path,
        monkeypatch,
        produces_signals=True,
        target_now=_IN_WINDOW_SH,
        quote_timestamp=f"{_DECISION_DATE}T09:35:45+08:00",
        with_unresolved_incident=True,
    )
    db: AppDatabase = env["db"]
    schedule = project_daily_candidate_background_schedule(db=db, now=_IN_WINDOW_SH)
    assert schedule["status"] == "due" and schedule["due"] is True

    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=env["service"],
            schedule=schedule,
            clock=lambda: _IN_WINDOW_SH,
        )
    )

    attempt = db.get_automation_run_sync(
        f"automation:daily-candidate-background-attempt:{_DECISION_DATE}"
    )
    assert attempt is not None and attempt["status"] == "completed"
    att_payload = json.loads(attempt["payload_json"])
    assert att_payload["decision_outcome"] == "no_action"
    assert att_payload["result_status"] == "blocked_by_data_quality"
    assert att_payload["broker_submission_enabled"] is False

    ev_run = db.get_automation_run_sync(att_payload["result_run_id"])
    assert ev_run is not None and ev_run["status"] == "blocked_by_data_quality"
    ev_payload = json.loads(ev_run["payload_json"])
    assert ev_payload["risk"]["blockers"] == [
        {"code": "valuation_publication_recovery_required"}
    ]
    assert ev_payload["manual_ticket_candidate_count"] == 0

    async def verify_routes(client: httpx.AsyncClient) -> None:
        today = (await client.get("/api/decision/today")).json()
        assert today["candidates"] == []
        strategy_task = next(
            task
            for task in today["summary"]["workflow_tasks"]
            if task["id"] == "strategy_evidence"
        )
        assert strategy_task["status"] == "blocked"
        assert (
            "daily_cycle_not_evidence_clear:blocked_by_data_quality"
            in strategy_task["blocking_reasons"]
        )
        report = (
            await client.get(f"/api/decision/daily-reports/{_DECISION_DATE}")
        ).json()
        assert report["status"] == "blocked"
        assert (
            report["attempts"][0]["scan_run_id"]
            == att_payload["promoted_strategy_scan_run_id"]
        )

    asyncio.run(_run_http(env["app"], verify_routes))


def test_friday_post_recovery_in_window_replays_to_manual_tickets_and_decision_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 2: Pre-window recovery receipt unblocks in-window E2E path chronologically."""
    env = _setup_environment(
        tmp_path,
        monkeypatch,
        produces_signals=True,
        target_now=_PRE_WINDOW_RECOVERY_SH,
        quote_timestamp=f"{_MARKET_DATE}T15:00:00+08:00",
        with_unresolved_incident=True,
    )
    db: AppDatabase = env["db"]
    set_clock = env["set_clock"]
    incident_ref = str(env["incident_ref"])

    preview = preview_unpublished_quote_recovery(db.path, incident_refs=[incident_ref])
    assert preview["status"] == "ready"
    receipt = discard_proven_unpublished_quote_refreshes(
        db.path,
        incident_refs=[incident_ref],
        expected_proof_fingerprint=str(preview["proof_fingerprint"]),
        actor="operator_cli_recovery",
        confirmation=UNPUBLISHED_RECOVERY_CONFIRMATION,
        now=_PRE_WINDOW_RECOVERY_SH,
    )
    assert receipt["resolved_count"] == 1
    assert receipt["changes_financial_facts"] is False
    assert receipt["authorizes_execution"] is False

    # Advance chronologically to 09:36 stock poll + 09:37 decision window
    pre_open_sh = datetime(2026, 11, 27, 9, 36, 0, tzinfo=_SH)
    set_clock(pre_open_sh)
    _ingest_morning_stock_poll(
        db,
        symbols=env["symbols"][:40],
        quote_timestamp=f"{_DECISION_DATE}T09:35:45+08:00",
        captured_at=pre_open_sh.isoformat(),
        run_id="scheduler_poll:fri-open-case2",
    )
    val_after = db.publish_current_valuation_snapshot_sync(now=pre_open_sh)
    assert val_after["status"] == "complete"

    set_clock(_IN_WINDOW_SH)
    schedule = project_daily_candidate_background_schedule(db=db, now=_IN_WINDOW_SH)
    assert schedule["status"] == "due" and schedule["due"] is True

    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=env["service"],
            schedule=schedule,
            clock=env["current_clock"],
        )
    )

    attempt = db.get_automation_run_sync(
        f"automation:daily-candidate-background-attempt:{_DECISION_DATE}"
    )
    assert attempt is not None
    assert datetime.fromisoformat(
        str(receipt["completed_at"])
    ) < datetime.fromisoformat(str(attempt["started_at"]))
    att_payload = json.loads(attempt["payload_json"])
    scan_run_id = str(att_payload["promoted_strategy_scan_run_id"])
    ev_run_id = str(att_payload["result_run_id"])
    assert att_payload["decision_outcome"] == "manual_order_ticket_candidate"
    assert att_payload["result_status"] == "paper_shadow_completed"
    assert att_payload["broker_submission_enabled"] is False

    ev_run = db.get_automation_run_sync(ev_run_id)
    assert ev_run is not None
    ev_payload = json.loads(ev_run["payload_json"])
    assert ev_payload["risk"]["passed_count"] > 0
    assert ev_payload["risk"]["blocked_count"] == 0
    assert ev_payload["production_gate"]["status"] == "pass"
    assert ev_payload["paper_shadow"]["status"] == "within_expectations"
    ticket_candidates = ev_payload["manual_order_ticket_candidates"]
    assert ticket_candidates

    async def verify_end_to_end(client: httpx.AsyncClient) -> None:
        today_resp = await client.get("/api/decision/today")
        plan_resp = await client.get("/api/decision/trading-plan")
        intraday_resp = await client.get("/api/decision/intraday")
        quality_resp = await client.get("/api/decision/quality")
        ops_resp = await client.get("/api/operations/today")
        report_resp = await client.get(f"/api/decision/daily-reports/{_DECISION_DATE}")
        reports_list_resp = await client.get(
            "/api/decision/daily-reports?limit=20&offset=0"
        )

        for resp in (
            today_resp,
            plan_resp,
            intraday_resp,
            quality_resp,
            ops_resp,
            report_resp,
            reports_list_resp,
        ):
            assert resp.status_code == 200

        today = today_resp.json()
        plan = plan_resp.json()
        ops = ops_resp.json()
        report = report_resp.json()

        assert len(today["candidates"]) == len(ticket_candidates)
        assert plan["plan_date"] == _DECISION_DATE
        assert report["status"] == "formal_candidate"
        assert report["daily_evidence_runs"][0]["run_id"] == ev_run_id
        assert report["daily_evidence_runs"][0]["scan_run_id"] == scan_run_id
        assert ops["broker_adapter_readiness"]["broker_submission_enabled"] is False

        by_action = {int(item["action_id"]): item for item in ticket_candidates}
        confirmed_action_ids: list[int] = []
        for cand in today["candidates"]:
            aid = int(cand["action_id"])
            spec = by_action[aid]
            mo = await client.post(
                f"/api/trading/actions/{aid}/manual-order",
                json={
                    "quantity": float(spec["quantity"]),
                    "order_type": str(spec["order_type"]),
                    "price": float(spec["limit_price"]),
                    "note": "isolated replay acceptance",
                },
            )
            assert mo.status_code == 200, mo.text
            order_id = str(mo.json()["order_id"])
            assert mo.json()["status"] == "pending_confirm"
            assert mo.json().get("broker_submission_enabled", False) is False

            confirm = await client.post(
                f"/api/trading/orders/{order_id}/confirm", json={}
            )
            assert confirm.status_code == 200, confirm.text
            assert confirm.json()["status"] == "confirmed"
            confirmed_action_ids.append(aid)

        confirmed_orders = (
            await client.get("/api/trading/orders?status=confirmed")
        ).json()
        assert len(confirmed_orders) == len(confirmed_action_ids)
        oms_orders = db.list_oms_orders_sync()
        assert len(oms_orders) == len(confirmed_action_ids)
        for order in oms_orders:
            payload = json.loads(str(order.get("payload_json") or "{}"))
            assert str(order.get("order_id") or "").startswith("SHADOW-2026-11-27-")
            assert order.get("source") == "paper_shadow_daily"
            assert payload.get("execution_mode") == "paper_shadow"
            assert payload.get("does_not_submit_broker_order") is True
            assert order.get("broker_submission_enabled") in (False, 0, None)
            assert not payload.get("broker_submission_enabled")

        report_after = (
            await client.get(f"/api/decision/daily-reports/{_DECISION_DATE}")
        ).json()
        assert report_after["status"] == "formal_candidate"
        assert sorted(
            report_after["daily_evidence_runs"][0]["ticket_action_ids"]
        ) == sorted(confirmed_action_ids)

    asyncio.run(_run_http(env["app"], verify_end_to_end))


def test_friday_post_window_preserves_original_attempt_and_blocks_late_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 3: Post-recovery evening preserves morning attempt and fails closed outside window."""
    env = _setup_environment(
        tmp_path,
        monkeypatch,
        produces_signals=True,
        target_now=_POST_WINDOW_SH,
        quote_timestamp=f"{_DECISION_DATE}T15:00:00+08:00",
        with_unresolved_incident=True,
    )
    db: AppDatabase = env["db"]
    incident_ref = str(env["incident_ref"])

    preview = preview_unpublished_quote_recovery(db.path, incident_refs=[incident_ref])
    discard_proven_unpublished_quote_refreshes(
        db.path,
        incident_refs=[incident_ref],
        expected_proof_fingerprint=str(preview["proof_fingerprint"]),
        actor="operator_cli_recovery",
        confirmation=UNPUBLISHED_RECOVERY_CONFIRMATION,
        now=_RECOVERY_SH,
    )

    # Seed the morning attempt + daily evidence index to verify preservation.
    db.upsert_automation_run_sync(
        {
            "run_id": f"automation:promoted-strategy-universe-scan:{_DECISION_DATE}:ced7d77bf27a0bfd",
            "run_type": "promoted_strategy_universe_scan",
            "run_date": _DECISION_DATE,
            "status": "completed",
            "execution_mode": "paper_shadow",
            "started_at": f"{_DECISION_DATE}T01:35:51+00:00",
            "finished_at": f"{_DECISION_DATE}T01:36:29+00:00",
            "source_ref": "sha256:ced7d77bf27a0bfd",
            "payload": {"decision_date": _DECISION_DATE, "market_date": _MARKET_DATE},
        }
    )
    db.upsert_automation_run_sync(
        {
            "run_id": f"automation:daily-decision-evidence:{_DECISION_DATE}:7e4c4342ae2e",
            "run_type": "daily_decision_evidence",
            "run_date": _DECISION_DATE,
            "status": "blocked_by_data_quality",
            "execution_mode": "paper_shadow",
            "started_at": f"{_DECISION_DATE}T01:35:09+00:00",
            "finished_at": f"{_DECISION_DATE}T01:37:05+00:00",
            "source_ref": None,
            "payload": {
                "schema_version": "karkinos.daily_decision_evidence_automation.v3",
                "promoted_strategy_scan_run_id": (
                    f"automation:promoted-strategy-universe-scan:{_DECISION_DATE}:ced7d77bf27a0bfd"
                ),
                "decision_outcome": "no_action",
                "no_action_reasons": [
                    "daily_cycle_not_evidence_clear:blocked_by_data_quality"
                ],
                "production_gate": {"status": "blocked"},
                "broker_submission_enabled": False,
            },
        }
    )
    db.upsert_automation_run_sync(
        {
            "run_id": f"automation:daily-candidate-background-attempt:{_DECISION_DATE}",
            "run_type": "daily_candidate_background_attempt",
            "run_date": _DECISION_DATE,
            "status": "completed",
            "execution_mode": "paper_shadow",
            "started_at": f"{_DECISION_DATE}T01:35:09+00:00",
            "finished_at": f"{_DECISION_DATE}T01:37:05+00:00",
            "source_ref": f"automation:daily-decision-evidence:{_DECISION_DATE}:7e4c4342ae2e",
            "payload": {
                "decision_outcome": "no_action",
                "result_status": "blocked_by_data_quality",
                "result_run_id": f"automation:daily-decision-evidence:{_DECISION_DATE}:7e4c4342ae2e",
                "result_plan_date": _DECISION_DATE,
                "promoted_strategy_scan_run_id": (
                    f"automation:promoted-strategy-universe-scan:{_DECISION_DATE}:ced7d77bf27a0bfd"
                ),
                "no_action_reasons": [
                    "daily_cycle_not_evidence_clear:blocked_by_data_quality"
                ],
                "attempt_count": 1,
            },
        }
    )

    schedule = project_daily_candidate_background_schedule(db=db, now=_POST_WINDOW_SH)
    assert schedule["status"] == "already_attempted"
    assert schedule["due"] is False
    assert (
        schedule["existing_run_id"]
        == f"automation:daily-candidate-background-attempt:{_DECISION_DATE}"
    )
    assert schedule["next_reviewed_window"]["market_date"] == _NEXT_DATE

    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=env["service"],
            schedule=schedule,
            clock=lambda: _POST_WINDOW_SH,
        )
    )
    attempts = db.list_automation_runs_sync(
        run_type="daily_candidate_background_attempt",
        run_date=_DECISION_DATE,
        limit=10,
    )
    assert len(attempts) == 1

    # Direct post-window evaluation clears risk/shadow after recovery, but still blocks publication
    late_eval = asyncio.run(env["service"].run_once(expected_plan_date=_DECISION_DATE))
    assert late_eval["decision_outcome"] == "no_action"
    assert late_eval["risk"]["blocked_count"] == 0
    assert late_eval["production_gate"]["status"] == "blocked"
    assert late_eval["manual_ticket_candidate_count"] == 0
    assert late_eval["broker_submission_enabled"] is False
    assert late_eval["no_action_reasons"][0] == (
        "promoted_strategy_universe_scan:strategy_scan_outside_reviewed_decision_window"
    )
    assert (
        "decision_generated_outside_reviewed_window" in late_eval["no_action_reasons"]
    )
    assert "market_quote_too_old_for_decision" in late_eval["no_action_reasons"]


def test_friday_replay_valid_zero_signal_session_publishes_clean_no_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 4: Valid zero-signal run completes cleanly with completed_no_signal across routes."""
    env = _setup_environment(
        tmp_path,
        monkeypatch,
        produces_signals=False,
        target_now=_IN_WINDOW_SH,
        quote_timestamp=f"{_DECISION_DATE}T09:35:45+08:00",
        with_unresolved_incident=False,
    )
    db: AppDatabase = env["db"]
    schedule = project_daily_candidate_background_schedule(db=db, now=_IN_WINDOW_SH)
    assert schedule["status"] == "due" and schedule["due"] is True

    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=env["service"],
            schedule=schedule,
            clock=lambda: _IN_WINDOW_SH,
        )
    )

    attempt = db.get_automation_run_sync(
        f"automation:daily-candidate-background-attempt:{_DECISION_DATE}"
    )
    assert attempt is not None and attempt["status"] == "completed"
    att_payload = json.loads(attempt["payload_json"])
    assert att_payload["decision_outcome"] == "no_action"
    scan_run = db.get_automation_run_sync(att_payload["promoted_strategy_scan_run_id"])
    assert scan_run is not None and scan_run["status"] == "completed_no_signal"
    scan_payload = json.loads(scan_run["payload_json"])
    assert scan_payload["normal_no_signal"] is True
    assert scan_payload["raw_signal_count"] == 0

    async def verify_zero_signal_routes(client: httpx.AsyncClient) -> None:
        today = (await client.get("/api/decision/today")).json()
        plan = (await client.get("/api/decision/trading-plan")).json()
        report = (
            await client.get(f"/api/decision/daily-reports/{_DECISION_DATE}")
        ).json()
        ops = (await client.get("/api/operations/today")).json()

        assert today["candidates"] == []
        strategy_task = next(
            task
            for task in today["summary"]["workflow_tasks"]
            if task["id"] == "strategy_evidence"
        )
        assert strategy_task["status"] == "pass"
        assert plan["order_intents"] == []
        assert report["status"] == "completed_no_signal"
        assert ops["broker_adapter_readiness"]["broker_submission_enabled"] is False

    asyncio.run(_run_http(env["app"], verify_zero_signal_routes))


def _advance_to_monday_window(
    env: dict[str, Any],
    *,
    friday_close_fn: Callable[[str], float],
) -> None:
    """Seed post-Friday-close and pre-Monday-open facts strictly chronologically."""
    db: AppDatabase = env["db"]
    store: DataStore = env["store"]
    symbols: list[str] = env["symbols"]
    set_clock = env["set_clock"]

    fri_post_close = datetime(2026, 11, 27, 16, 0, 0, tzinfo=_SH)
    set_clock(fri_post_close)
    store.save_market_universe_snapshot(
        trade_date=_DECISION_DATE,
        provider_name="fixture",
        members=normalize_a_share_members(symbols),
        capture_started_at=datetime(2026, 11, 27, 15, 59, tzinfo=_SH),
        capture_completed_at=fri_post_close,
        source_metadata=[
            {"symbol": sym, "display_name": f"样本股票{sym}"} for sym in symbols
        ],
    )
    closes = [friday_close_fn(sym) for sym in symbols]
    store.ingest_market_daily_batch(
        trade_date=_DECISION_DATE,
        provider_name="fixture",
        bars=pd.DataFrame(
            {
                "symbol": symbols,
                "timestamp": [pd.Timestamp(_DECISION_DATE)] * len(symbols),
                "open": closes,
                "high": [price + 0.2 for price in closes],
                "low": [price - 0.2 for price in closes],
                "close": closes,
                "volume": [1_000_000 + idx for idx in range(len(symbols))],
                "amount": [10_000_000 + idx * 1_000 for idx in range(len(symbols))],
            }
        ),
    )

    fri_nav_sh = datetime(2026, 11, 27, 21, 30, 0, tzinfo=_SH)
    set_clock(fri_nav_sh)
    fri_nav_run = "fund_nav_sync:seed-official-2026-11-27"
    db.create_quote_fetch_run(
        run_id=fri_nav_run,
        started_at=fri_nav_sh.isoformat(),
        trigger="fund_nav_sync",
        provider="akshare",
        asset_type="open_end_fund",
        symbol_count=1,
        status="running",
        metadata={
            "requested_symbols": ["018125"],
            "instrument_types": ["open_end_fund"],
        },
    )
    db.persist_quote_ingestion_sync(
        QuoteIngestionCommand(
            symbol="018125",
            asset_type="open_end_fund",
            price=1.9526,
            volume=0.0,
            quote_timestamp="2026-11-27T15:00:00+08:00",
            captured_at=fri_nav_sh.isoformat(),
            quote_source="eastmoney_fund_page",
            provider_name="akshare",
            provider_status="live",
            quote_status="confirmed",
            captured_reason="fund_nav_sync",
            nav_date=_DECISION_DATE,
            fetch_run_id=fri_nav_run,
        )
    )
    db.finish_quote_fetch_run(
        run_id=fri_nav_run,
        finished_at="2026-11-27T21:30:01+08:00",
        status="success",
        success_count=1,
        failure_count=0,
        metadata={
            "requested_symbols": ["018125"],
            "instrument_types": ["open_end_fund"],
        },
    )

    mon_pre_open = datetime(2026, 11, 30, 8, 50, 0, tzinfo=_SH)
    set_clock(mon_pre_open)
    _seed_reconciled_statement(
        db,
        cash_balance=190_000.0,
        stock_qty=500.0,
        stock_px=10.0,
        fund_qty=1_000.0,
        fund_px=1.7533,
        snapshot_date=_NEXT_DATE,
    )

    mon_quote_sh = datetime(2026, 11, 30, 9, 36, 0, tzinfo=_SH)
    set_clock(mon_quote_sh)
    env["quote_price_overrides"].update(
        {sym: friday_close_fn(sym) for sym in symbols[:40]}
    )
    _ingest_morning_stock_poll(
        db,
        symbols=symbols[:40],
        quote_timestamp=f"{_NEXT_DATE}T09:35:45+08:00",
        captured_at=mon_quote_sh.isoformat(),
        run_id="scheduler_poll:seed-2026-11-30",
        price_fn=friday_close_fn,
    )
    mon_val = db.publish_current_valuation_snapshot_sync(now=mon_quote_sh)
    assert mon_val["status"] == "complete"

    set_clock(_MONDAY_IN_WINDOW_SH)


def _run_friday_blocked_and_midday_recovery(env: dict[str, Any]) -> dict[str, Any]:
    """Run Friday 09:37 blocked cycle followed by Friday 12:01 recovery receipt."""
    db: AppDatabase = env["db"]
    set_clock = env["set_clock"]
    incident_ref = str(env["incident_ref"])

    fri_schedule = project_daily_candidate_background_schedule(db=db, now=_IN_WINDOW_SH)
    assert fri_schedule["status"] == "due" and fri_schedule["due"] is True
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=env["service"],
            schedule=fri_schedule,
            clock=env["current_clock"],
        )
    )

    fri_attempt = db.get_automation_run_sync(
        f"automation:daily-candidate-background-attempt:{_DECISION_DATE}"
    )
    assert fri_attempt is not None and fri_attempt["status"] == "completed"
    fri_att_payload = json.loads(fri_attempt["payload_json"])
    assert fri_att_payload["decision_outcome"] == "no_action"
    assert fri_att_payload["result_status"] == "blocked_by_data_quality"
    assert fri_att_payload["broker_submission_enabled"] is False
    fri_scan = db.get_automation_run_sync(
        fri_att_payload["promoted_strategy_scan_run_id"]
    )
    assert fri_scan is not None
    fri_scan_payload = json.loads(fri_scan["payload_json"])
    assert fri_scan_payload["raw_signal_count"] > 0

    async def verify_fri_blocked(client: httpx.AsyncClient) -> dict[str, Any]:
        today = (await client.get("/api/decision/today")).json()
        report = (
            await client.get(f"/api/decision/daily-reports/{_DECISION_DATE}")
        ).json()
        assert today["candidates"] == []
        assert report["status"] == "blocked"
        assert (
            report["attempts"][0]["scan_run_id"]
            == fri_att_payload["promoted_strategy_scan_run_id"]
        )
        return report

    fri_report = asyncio.run(_run_http(env["app"], verify_fri_blocked))

    # Step 2: Friday 12:01:57 recovery receipt, no same-day backfill
    set_clock(_RECOVERY_SH)
    preview = preview_unpublished_quote_recovery(db.path, incident_refs=[incident_ref])
    assert preview["status"] == "ready"
    receipt = discard_proven_unpublished_quote_refreshes(
        db.path,
        incident_refs=[incident_ref],
        expected_proof_fingerprint=str(preview["proof_fingerprint"]),
        actor="operator_cli_recovery",
        confirmation=UNPUBLISHED_RECOVERY_CONFIRMATION,
        now=_RECOVERY_SH,
    )
    assert receipt["resolved_count"] == 1
    with sqlite3.connect(db.path) as conn:
        assert unresolved_publications(conn) == []

    midday_schedule = project_daily_candidate_background_schedule(
        db=db, now=_RECOVERY_SH
    )
    assert midday_schedule["status"] == "already_attempted"
    assert midday_schedule["due"] is False
    assert midday_schedule["next_reviewed_window"]["market_date"] == _NEXT_DATE
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=env["service"],
            schedule=midday_schedule,
            clock=env["current_clock"],
        )
    )
    fri_attempts = db.list_automation_runs_sync(
        run_type="daily_candidate_background_attempt",
        run_date=_DECISION_DATE,
        limit=10,
    )
    assert len(fri_attempts) == 1

    async def verify_no_same_day_backfill(client: httpx.AsyncClient) -> None:
        today = (await client.get("/api/decision/today")).json()
        report = (
            await client.get(f"/api/decision/daily-reports/{_DECISION_DATE}")
        ).json()
        assert today["candidates"] == []
        assert report["status"] == "blocked"
        assert report["daily_evidence_runs"] == fri_report["daily_evidence_runs"]

    asyncio.run(_run_http(env["app"], verify_no_same_day_backfill))

    return {
        "fri_attempt": fri_attempt,
        "fri_att_payload": fri_att_payload,
        "fri_report": fri_report,
        "receipt": receipt,
    }


def test_friday_incident_chronological_recovery_and_monday_candidate_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 5: Single-DB Asia/Shanghai chronological flow (Fri blocked -> 12:01 recovery -> Mon tickets)."""
    env = _setup_environment(
        tmp_path,
        monkeypatch,
        produces_signals=True,
        target_now=_IN_WINDOW_SH,
        quote_timestamp=f"{_DECISION_DATE}T09:35:45+08:00",
        with_unresolved_incident=True,
    )
    db: AppDatabase = env["db"]

    fri = _run_friday_blocked_and_midday_recovery(env)

    _advance_to_monday_window(
        env,
        friday_close_fn=lambda sym: 10.0 if sym == "600001" else 20.0,
    )

    mon_schedule = project_daily_candidate_background_schedule(
        db=db, now=_MONDAY_IN_WINDOW_SH
    )
    assert mon_schedule["status"] == "due" and mon_schedule["due"] is True
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=env["service"],
            schedule=mon_schedule,
            clock=env["current_clock"],
        )
    )

    mon_attempt = db.get_automation_run_sync(
        f"automation:daily-candidate-background-attempt:{_NEXT_DATE}"
    )
    assert mon_attempt is not None and mon_attempt["status"] == "completed"
    mon_att_payload = json.loads(mon_attempt["payload_json"])
    assert mon_att_payload["decision_outcome"] == "manual_order_ticket_candidate"
    assert mon_att_payload["result_status"] == "paper_shadow_completed"
    assert mon_att_payload["broker_submission_enabled"] is False

    # Verify monotonic Asia/Shanghai chronological timestamps across all three stages.
    fri_started = datetime.fromisoformat(str(fri["fri_attempt"]["started_at"]))
    recovered_at = datetime.fromisoformat(str(fri["receipt"]["completed_at"]))
    mon_started = datetime.fromisoformat(str(mon_attempt["started_at"]))
    assert fri_started < recovered_at < mon_started

    mon_ev_id = str(mon_att_payload["result_run_id"])
    mon_ev_run = db.get_automation_run_sync(mon_ev_id)
    assert mon_ev_run is not None
    mon_ev_payload = json.loads(mon_ev_run["payload_json"])
    ticket_candidates = mon_ev_payload["manual_order_ticket_candidates"]
    assert ticket_candidates

    async def verify_monday_end_to_end(client: httpx.AsyncClient) -> None:
        today_resp = await client.get("/api/decision/today")
        plan_resp = await client.get("/api/decision/trading-plan")
        mon_report_resp = await client.get(f"/api/decision/daily-reports/{_NEXT_DATE}")
        fri_report_resp = await client.get(
            f"/api/decision/daily-reports/{_DECISION_DATE}"
        )
        for resp in (today_resp, plan_resp, mon_report_resp, fri_report_resp):
            assert resp.status_code == 200, resp.text
        today = today_resp.json()
        plan = plan_resp.json()
        mon_report = mon_report_resp.json()
        fri_report = fri_report_resp.json()

        assert today["decision_date"] == _NEXT_DATE
        assert plan["plan_date"] == _NEXT_DATE
        assert len(today["candidates"]) == len(ticket_candidates)
        assert mon_report["status"] == "formal_candidate"
        assert fri_report["status"] == "blocked"

        by_action = {int(item["action_id"]): item for item in ticket_candidates}
        confirmed_ids: list[int] = []
        for cand in today["candidates"]:
            aid = int(cand["action_id"])
            spec = by_action[aid]
            mo = await client.post(
                f"/api/trading/actions/{aid}/manual-order",
                json={
                    "quantity": float(spec["quantity"]),
                    "order_type": str(spec["order_type"]),
                    "price": float(spec["limit_price"]),
                    "note": "monday chronological acceptance",
                },
            )
            assert mo.status_code == 200, mo.text
            order_id = str(mo.json()["order_id"])
            assert mo.json().get("broker_submission_enabled", False) is False

            confirm = await client.post(
                f"/api/trading/orders/{order_id}/confirm", json={}
            )
            assert confirm.status_code == 200, confirm.text
            assert confirm.json()["status"] == "confirmed"
            confirmed_ids.append(aid)

        oms_orders = db.list_oms_orders_sync()
        assert len(oms_orders) == len(confirmed_ids)
        for order in oms_orders:
            assert str(order.get("order_id") or "").startswith("SHADOW-2026-11-30-")
            assert order.get("broker_submission_enabled") in (False, 0, None)

        mon_report_after = (
            await client.get(f"/api/decision/daily-reports/{_NEXT_DATE}")
        ).json()
        assert sorted(
            mon_report_after["daily_evidence_runs"][0]["ticket_action_ids"]
        ) == sorted(confirmed_ids)

    asyncio.run(_run_http(env["app"], verify_monday_end_to_end))


def test_friday_incident_chronological_recovery_and_monday_clean_no_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 6: Single-DB chronological flow distinguishes Fri data block from Mon clean no_action."""
    # Entry holds only for closes < 25; Fri pre-open bars close at 10/20 (signals!),
    # then Friday close moves all symbols to 30 so Monday cleanly yields 0 signals.
    threshold_formula = {
        "schema_version": "karkinos.ai.formula_ast.v1",
        "entry": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 25},
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 5},
        },
        "position_size": {
            "op": "max_weight",
            "input": {"op": "equal_weight"},
            "value": 0.1,
        },
    }
    env = _setup_environment(
        tmp_path,
        monkeypatch,
        produces_signals=True,
        target_now=_IN_WINDOW_SH,
        quote_timestamp=f"{_DECISION_DATE}T09:35:45+08:00",
        with_unresolved_incident=True,
        formula_override=threshold_formula,
    )
    db: AppDatabase = env["db"]

    fri = _run_friday_blocked_and_midday_recovery(env)

    _advance_to_monday_window(
        env,
        friday_close_fn=lambda _sym: 30.0,
    )

    mon_schedule = project_daily_candidate_background_schedule(
        db=db, now=_MONDAY_IN_WINDOW_SH
    )
    assert mon_schedule["status"] == "due" and mon_schedule["due"] is True
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=env["service"],
            schedule=mon_schedule,
            clock=env["current_clock"],
        )
    )

    mon_attempt = db.get_automation_run_sync(
        f"automation:daily-candidate-background-attempt:{_NEXT_DATE}"
    )
    assert mon_attempt is not None and mon_attempt["status"] == "completed"
    mon_att_payload = json.loads(mon_attempt["payload_json"])
    assert mon_att_payload["decision_outcome"] == "no_action"

    fri_started = datetime.fromisoformat(str(fri["fri_attempt"]["started_at"]))
    recovered_at = datetime.fromisoformat(str(fri["receipt"]["completed_at"]))
    mon_started = datetime.fromisoformat(str(mon_attempt["started_at"]))
    assert fri_started < recovered_at < mon_started

    mon_scan = db.get_automation_run_sync(
        mon_att_payload["promoted_strategy_scan_run_id"]
    )
    assert mon_scan is not None and mon_scan["status"] == "completed_no_signal"
    mon_scan_payload = json.loads(mon_scan["payload_json"])
    assert mon_scan_payload["normal_no_signal"] is True
    assert mon_scan_payload["raw_signal_count"] == 0

    async def verify_distinction(client: httpx.AsyncClient) -> None:
        today = (await client.get("/api/decision/today")).json()
        fri_report = (
            await client.get(f"/api/decision/daily-reports/{_DECISION_DATE}")
        ).json()
        mon_report = (
            await client.get(f"/api/decision/daily-reports/{_NEXT_DATE}")
        ).json()
        reports_list = (
            await client.get("/api/decision/daily-reports?limit=20&offset=0")
        ).json()

        assert today["candidates"] == []
        strategy_task = next(
            task
            for task in today["summary"]["workflow_tasks"]
            if task["id"] == "strategy_evidence"
        )
        assert strategy_task["status"] == "pass"

        assert fri_report["status"] == "blocked"
        assert any(
            "blocked_by_data_quality" in str(reason)
            for reason in fri_report.get("reason_codes") or []
        )

        assert mon_report["status"] == "completed_no_signal"
        assert mon_report.get("reason_codes") == [
            "full_market_scan_completed_without_strategy_signal"
        ]
        assert not any(
            "blocked_by_data_quality" in str(reason)
            for reason in mon_report.get("reason_codes") or []
        )
        by_date = {item["report_date"]: item for item in reports_list["reports"]}
        assert by_date[_DECISION_DATE]["status"] == "blocked"
        assert by_date[_NEXT_DATE]["status"] == "completed_no_signal"

    asyncio.run(_run_http(env["app"], verify_distinction))
