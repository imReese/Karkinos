"""Verify memoization and timeout fast-fail for promoted strategy universe scan."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from server.ai_runtime.contracts import content_fingerprint
from server.services.market.market_universe_truth import MarketUniversePolicy
from server.services.strategy_scan.universe.evaluation import (
    cash_buffer_ratio,
    market_evaluation_cache_key,
    portfolio_scan_binding,
    promoted_scan_evaluation_policy_fingerprint,
)
from server.services.strategy_scan.universe.service import (
    PromotedStrategyUniverseScanService,
)
from server.services.strategy_scan.universe.validation import (
    current_scan_input_blockers,
)


def _mock_market(
    *,
    snapshot_id: str = "snap:one",
    receipt_fingerprints: list[str] | None = None,
    held_symbols: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "history_start": "2026-01-01",
        "snapshot": {"snapshot_id": snapshot_id},
        "receipts": [
            {"receipt_fingerprint": fp}
            for fp in (receipt_fingerprints or ["receipt:one"])
        ],
        "trading_dates": ["2026-09-22", "2026-09-23"],
        "frames": {},
        "held_symbols": held_symbols or [],
        "formula_dataset_bindings": {},
    }


def _mock_promoted(
    *,
    strategy_id: str = "strategy:one",
    artifact_fp: str = "art:one",
) -> list[dict[str, Any]]:
    return [
        {
            "strategy_id": strategy_id,
            "strategy_artifact_fingerprint": artifact_fp,
            "order_generation_gate_fingerprint": "gate:one",
            "qualification_fingerprint": "qual:one",
            "history_start": "2026-01-01",
            "strategy": {
                "formula_ast": {},
                "selected_universe": ["600869"],
            },
        }
    ]


def test_market_evaluation_cache_key_identifies_matching_inputs() -> None:
    promoted = _mock_promoted()
    key1 = market_evaluation_cache_key(
        market_date="2026-09-23",
        snapshot_id="snap:one",
        receipt_fingerprints=["receipt:one", "receipt:two"],
        trading_dates=["2026-09-22", "2026-09-23"],
        start_date="2026-01-01",
        total_equity=100000.0,
        held_symbols=["600869"],
        policy_fingerprint="pol:one",
        promoted_strategies=promoted,
        formula_bindings={"strategy:one": {"dataset_id": "ds:one"}},
    )
    key2 = market_evaluation_cache_key(
        market_date="2026-09-23",
        snapshot_id="snap:one",
        receipt_fingerprints=["receipt:two", "receipt:one"],
        trading_dates=["2026-09-22", "2026-09-23"],
        start_date="2026-01-01",
        total_equity=100000.0,
        held_symbols=["600869"],
        policy_fingerprint="pol:one",
        promoted_strategies=promoted,
        formula_bindings={"strategy:one": {"dataset_id": "ds:one"}},
    )
    assert key1 == key2


def test_market_evaluation_cache_key_changes_on_input_mutation() -> None:
    promoted = _mock_promoted()
    base_kwargs: dict[str, Any] = {
        "market_date": "2026-09-23",
        "snapshot_id": "snap:one",
        "receipt_fingerprints": ["receipt:one"],
        "trading_dates": ["2026-09-22", "2026-09-23"],
        "start_date": "2026-01-01",
        "total_equity": 100000.0,
        "held_symbols": ["600869"],
        "policy_fingerprint": "pol:one",
        "promoted_strategies": promoted,
    }
    base_key = market_evaluation_cache_key(**base_kwargs)

    # Different snapshot
    diff_snap = market_evaluation_cache_key(
        **{**base_kwargs, "snapshot_id": "snap:two"}
    )
    assert diff_snap != base_key

    # Different receipts
    diff_rcpt = market_evaluation_cache_key(
        **{**base_kwargs, "receipt_fingerprints": ["receipt:two"]}
    )
    assert diff_rcpt != base_key

    # Different strategy artifact fingerprint
    diff_promoted = market_evaluation_cache_key(
        **{**base_kwargs, "promoted_strategies": _mock_promoted(artifact_fp="art:two")}
    )
    assert diff_promoted != base_key

    # Different held symbols
    diff_held = market_evaluation_cache_key(
        **{**base_kwargs, "held_symbols": ["600869", "000001"]}
    )
    assert diff_held != base_key

    # Intermediate trading date mutation (same len, first, last)
    diff_dates = market_evaluation_cache_key(
        **{
            **base_kwargs,
            "trading_dates": ["2026-09-22", "2026-09-24", "2026-09-23"],
        }
    )
    assert diff_dates != base_key

    # Sub-cent equity precision difference
    diff_eq1 = market_evaluation_cache_key(**{**base_kwargs, "total_equity": 4040.001})
    diff_eq2 = market_evaluation_cache_key(**{**base_kwargs, "total_equity": 4039.999})
    assert diff_eq1 != diff_eq2


def test_market_evaluation_cache_key_trading_dates_counterexample(monkeypatch) -> None:
    scanner = PromotedStrategyUniverseScanService(
        db=MagicMock(), config=None, data_store=MagicMock()
    )
    promoted = _mock_promoted()

    eval_calls: list[list[str]] = []

    def mock_evaluate(
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        eval_calls.append(list(kwargs["trading_dates"]))
        if "2026-01-07" in kwargs["trading_dates"]:
            return {}, [], ["full_market_daily_receipt_coverage_incomplete"]
        return (
            {"strategy:one": {"evidence_fingerprint": "ev:A"}},
            [{"symbol": "600869", "direction": "buy"}],
            [],
        )

    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.evaluate_promoted_strategy_market",
        mock_evaluate,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.load_exact_formula_market_inputs",
        lambda *a, **k: ({}, {}, {}, []),
    )

    market_A = _mock_market()
    market_A["trading_dates"] = ["2026-01-05", "2026-01-06", "2026-01-08", "2026-01-09"]
    market_A["history_start"] = "2026-01-01"

    # Cold call A
    truths_A, signals_A, blockers_A = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-01-09",
        market=market_A,
        total_equity=100000.0,
        decision_at=datetime(2026, 1, 9, 9, 36, tzinfo=timezone.utc),
    )
    assert len(eval_calls) == 1
    assert len(signals_A) == 1
    assert blockers_A == []

    # Call B on same scanner instance: intermediate date differs (01-07 vs 01-06)
    # Must NOT hit A's cache!
    market_B = _mock_market()
    market_B["trading_dates"] = ["2026-01-05", "2026-01-07", "2026-01-08", "2026-01-09"]
    market_B["history_start"] = "2026-01-01"

    truths_B, signals_B, blockers_B = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-01-09",
        market=market_B,
        total_equity=100000.0,
        decision_at=datetime(2026, 1, 9, 9, 36, tzinfo=timezone.utc),
    )
    assert len(eval_calls) == 2
    assert len(signals_B) == 0
    assert "full_market_daily_receipt_coverage_incomplete" in blockers_B

    # Fresh cold scanner on B must produce exact same result
    scanner_fresh = PromotedStrategyUniverseScanService(
        db=MagicMock(), config=None, data_store=MagicMock()
    )
    truths_B_cold, signals_B_cold, blockers_B_cold = (
        scanner_fresh._evaluate_promoted_strategies(
            promoted=promoted,
            market_date="2026-01-09",
            market=market_B,
            total_equity=100000.0,
            decision_at=datetime(2026, 1, 9, 9, 36, tzinfo=timezone.utc),
        )
    )
    assert len(eval_calls) == 3
    assert truths_B == truths_B_cold
    assert signals_B == signals_B_cold
    assert blockers_B == blockers_B_cold


def test_market_evaluation_cache_key_equity_precision_counterexample(
    monkeypatch,
) -> None:
    scanner = PromotedStrategyUniverseScanService(
        db=MagicMock(), config=None, data_store=MagicMock()
    )
    promoted = _mock_promoted()

    eval_calls: list[float] = []

    def mock_evaluate(
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        eq = float(kwargs["total_equity"])
        eval_calls.append(eq)
        if eq >= 4040.0:
            return (
                {"strategy:one": {"evidence_fingerprint": "ev:eligible"}},
                [{"symbol": "600869", "direction": "buy"}],
                [],
            )
        return (
            {"strategy:one": {"evidence_fingerprint": "ev:ineligible"}},
            [],
            ["insufficient_per_name_budget_for_one_lot"],
        )

    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.evaluate_promoted_strategy_market",
        mock_evaluate,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.load_exact_formula_market_inputs",
        lambda *a, **k: ({}, {}, {}, []),
    )

    market = _mock_market()

    # 1. Cold call with 4040.001
    truths_1, signals_1, blockers_1 = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=4040.001,
        decision_at=datetime(2026, 9, 23, 9, 36, tzinfo=timezone.utc),
    )
    assert len(eval_calls) == 1
    assert len(signals_1) == 1
    assert blockers_1 == []

    # 2. Call with 4039.999 on same scanner instance: must NOT hit cache!
    truths_2, signals_2, blockers_2 = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=4039.999,
        decision_at=datetime(2026, 9, 23, 9, 36, tzinfo=timezone.utc),
    )
    assert len(eval_calls) == 2
    assert len(signals_2) == 0
    assert "insufficient_per_name_budget_for_one_lot" in blockers_2

    # 3. Fresh cold scanner on 4039.999 must produce identical results
    scanner_fresh = PromotedStrategyUniverseScanService(
        db=MagicMock(), config=None, data_store=MagicMock()
    )
    truths_cold, signals_cold, blockers_cold = (
        scanner_fresh._evaluate_promoted_strategies(
            promoted=promoted,
            market_date="2026-09-23",
            market=market,
            total_equity=4039.999,
            decision_at=datetime(2026, 9, 23, 9, 36, tzinfo=timezone.utc),
        )
    )
    assert len(eval_calls) == 3
    assert truths_2 == truths_cold
    assert signals_2 == signals_cold
    assert blockers_2 == blockers_cold

    # 4. Same input 4040.001 hits cache and does not evaluate
    truths_hit, signals_hit, blockers_hit = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=4040.001,
        decision_at=datetime(2026, 9, 23, 9, 36, tzinfo=timezone.utc),
    )
    assert len(eval_calls) == 3
    assert truths_hit == truths_1
    assert signals_hit == signals_1


def test_service_reuses_cached_pure_evaluation_across_calls(monkeypatch) -> None:
    eval_mock = MagicMock(
        return_value=(
            {"strategy:one": {"evidence_fingerprint": "ev:one"}},
            [{"symbol": "600869", "direction": "buy", "strategy_id": "strategy:one"}],
            [],
        )
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.evaluate_promoted_strategy_market",
        eval_mock,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.load_exact_formula_market_inputs",
        lambda _db, _promoted, market_date, decision_at: ({}, {}, {}, []),
    )

    scanner = PromotedStrategyUniverseScanService(
        db=MagicMock(),
        config=None,
        data_store=MagicMock(),
    )
    market = _mock_market()
    promoted = _mock_promoted()

    # First call: computes and caches
    truths1, signals1, blockers1 = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 9, 36, tzinfo=timezone.utc),
    )
    assert eval_mock.call_count == 1
    assert "strategy:one" in truths1

    # Second call with identical inputs: reuses cache without calling evaluate_promoted_strategy_market
    truths2, signals2, blockers2 = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 9, 37, tzinfo=timezone.utc),
    )
    assert eval_mock.call_count == 1
    assert truths1 == truths2
    assert signals1 == signals2

    # Third call with changed snapshot: cache miss, calls evaluate_promoted_strategy_market again
    market_changed = _mock_market(snapshot_id="snap:two")
    truths3, signals3, blockers3 = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market_changed,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 9, 38, tzinfo=timezone.utc),
    )
    assert eval_mock.call_count == 2


def test_service_evaluation_without_init_handles_uninitialized_cache_and_mock_policy(
    monkeypatch,
) -> None:
    eval_mock = MagicMock(
        return_value=(
            {"strategy:one": {"evidence_fingerprint": "ev:one"}},
            [{"symbol": "600869", "direction": "buy", "strategy_id": "strategy:one"}],
            [],
        )
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.evaluate_promoted_strategy_market",
        eval_mock,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.load_exact_formula_market_inputs",
        lambda _db, _promoted, market_date, decision_at: ({}, {}, {}, []),
    )

    scanner = object.__new__(PromotedStrategyUniverseScanService)
    scanner._db = object()
    scanner._policy = object()
    market = _mock_market()
    promoted = _mock_promoted()

    truths, signals, blockers = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 9, 36, tzinfo=timezone.utc),
    )
    assert eval_mock.call_count == 1
    assert "strategy:one" in truths
    assert len(signals) == 1
    assert getattr(scanner, "_evaluation_cache", None) is not None

    # Subsequent call reuses cache even on raw object instance
    truths2, signals2, _ = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 9, 46, tzinfo=timezone.utc),
    )
    assert eval_mock.call_count == 1
    assert truths2 == truths
    assert signals2 == signals


def test_evaluation_cache_reused_in_subsequent_phases(
    monkeypatch,
) -> None:
    eval_mock = MagicMock(
        return_value=(
            {"strategy:one": {"evidence_fingerprint": "ev:one"}},
            [{"symbol": "600869", "direction": "buy", "strategy_id": "strategy:one"}],
            [],
        )
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.evaluate_promoted_strategy_market",
        eval_mock,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.service.load_exact_formula_market_inputs",
        lambda _db, _promoted, market_date, decision_at: ({}, {}, {}, []),
    )

    scanner = PromotedStrategyUniverseScanService(
        db=MagicMock(),
        config=None,
        data_store=MagicMock(),
    )
    market = _mock_market()
    promoted = _mock_promoted()

    # Initial run during prepare phase
    scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 9, 36, tzinfo=timezone.utc),
    )
    assert eval_mock.call_count == 1

    # Second run during final scan / outside window: reuses cache without re-evaluating
    truths, signals, blockers = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc),
    )
    assert eval_mock.call_count == 1
    assert "strategy:one" in truths
    assert len(signals) == 1


def test_validation_reuses_evaluation_cache_without_recomputing(monkeypatch) -> None:
    eval_mock = MagicMock(
        return_value=(
            {"strategy:one": {"evidence_fingerprint": "ev:one"}},
            [],
            [],
        )
    )
    policy = MarketUniversePolicy()
    promoted = _mock_promoted()
    market_date = "2026-09-23"
    decision_date = "2026-09-24"
    snapshot = {"snapshot_id": "snap:one", "members": [{"symbol": "600869"}]}
    receipts = [{"trade_date": market_date, "receipt_fingerprint": "receipt:one"}]
    trading_dates = ["2026-09-22", market_date]
    safety_gate = {
        "status": "clear",
        "kill_switch_enabled": False,
        "broker_submission_enabled": False,
        "manual_confirmation_required": True,
        "default_execution_mode": "manual_confirmation",
    }
    safety_fp = "sha256:" + content_fingerprint(safety_gate)
    policy_fp = promoted_scan_evaluation_policy_fingerprint(policy)

    portfolio = {
        "total_equity": 100000.0,
        "stock_equity": 0.0,
        "cash": 100000.0,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_snapshot_id": "val:one",
        "valuation_status": "complete",
        "symbols": [],
        "stock_symbols": [],
        "instrument_types": {},
        "board_buy_permissions": {},
        "stock_position_market_values": {},
    }
    p_binding = portfolio_scan_binding(
        portfolio, held_symbols=[], reserve_ratio=cash_buffer_ratio(None)
    )
    signal_fp = "sha256:" + content_fingerprint(
        {
            "decision_date": decision_date,
            "market_date": market_date,
            "raw_signals": [],
            "account_blocked_buys": [],
            "signals": [],
        }
    )

    scan = {
        "scan_id": "scan:test:one",
        "decision_date": decision_date,
        "market_date": market_date,
        "market_universe_snapshot_id": "snap:one",
        "receipt_fingerprints": ["receipt:one"],
        "safety_gate_fingerprint": safety_fp,
        "evaluation_policy_fingerprint": policy_fp,
        "portfolio_binding": p_binding,
        "strategy_bindings": [
            {
                "strategy_id": "strategy:one",
                "strategy_artifact_fingerprint": "art:one",
                "order_generation_gate_fingerprint": "gate:one",
                "qualification_fingerprint": "qual:one",
                "universe_truth_fingerprint": "ev:one",
            }
        ],
        "selected_signals": [],
        "signal_selection_fingerprint": signal_fp,
    }

    data_store = MagicMock()
    data_store.get_market_universe_snapshot.return_value = snapshot
    data_store.load_market_bar_windows.return_value = {"600869": pd.DataFrame()}

    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.evaluate_promoted_strategy_market",
        eval_mock,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.load_exact_formula_market_inputs",
        lambda *a, **k: ({}, {}, {}, []),
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.prior_verified_trading_date",
        lambda *a, **k: market_date,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.require_complete_market_universe_snapshot",
        lambda *a, **k: snapshot,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.resolve_daily_bar_receipt_provider",
        lambda *a, **k: "test",
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.resolve_daily_bar_receipts",
        lambda *a, **k: receipts,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.verified_trading_dates",
        lambda *a, **k: trading_dates,
    )

    # 1. Cold call without cache: must call real evaluate_promoted_strategy_market
    eval_mock.reset_mock()
    blockers_cold = current_scan_input_blockers(
        db=MagicMock(),
        config=None,
        data_store=data_store,
        policy=policy,
        scan=scan,
        portfolio_summary={"total_equity": 100000.0, "valuation_status": "complete"},
        portfolio_reader=lambda p: (portfolio, []),
        promoted_reader=lambda d: (promoted, []),
        safety_reader=lambda: safety_gate,
        current_time=datetime(2026, 9, 24, 9, 36, tzinfo=timezone.utc),
        evaluation_cache={},
    )
    assert eval_mock.call_count == 1
    assert blockers_cold == []

    # 2. Warm call with cache: reuses cache and skips evaluate_promoted_strategy_market
    cache_key = market_evaluation_cache_key(
        market_date=market_date,
        snapshot_id="snap:one",
        receipt_fingerprints=["receipt:one"],
        trading_dates=trading_dates,
        start_date="2026-01-01",
        total_equity=100000.0,
        held_symbols=[],
        policy_fingerprint=policy_fp,
        promoted_strategies=promoted,
        formula_bindings={},
    )
    cache = {
        cache_key: (
            {"strategy:one": {"evidence_fingerprint": "ev:one"}},
            [],
            [],
            {},
        )
    }
    eval_mock.reset_mock()
    blockers_warm = current_scan_input_blockers(
        db=MagicMock(),
        config=None,
        data_store=data_store,
        policy=policy,
        scan=scan,
        portfolio_summary={"total_equity": 100000.0, "valuation_status": "complete"},
        portfolio_reader=lambda p: (portfolio, []),
        promoted_reader=lambda d: (promoted, []),
        safety_reader=lambda: safety_gate,
        current_time=datetime(2026, 9, 24, 9, 36, tzinfo=timezone.utc),
        evaluation_cache=cache,
    )
    assert eval_mock.call_count == 0
    assert blockers_warm == []

    # 3. Changed identity (e.g. Snapshot ID changed): detects change and blocks
    scan_changed = dict(scan, market_universe_snapshot_id="snap:two")
    eval_mock.reset_mock()
    blockers_changed = current_scan_input_blockers(
        db=MagicMock(),
        config=None,
        data_store=data_store,
        policy=policy,
        scan=scan_changed,
        portfolio_summary={"total_equity": 100000.0, "valuation_status": "complete"},
        portfolio_reader=lambda p: (portfolio, []),
        promoted_reader=lambda d: (promoted, []),
        safety_reader=lambda: safety_gate,
        current_time=datetime(2026, 9, 24, 9, 36, tzinfo=timezone.utc),
        evaluation_cache=cache,
    )
    assert eval_mock.call_count == 0
    assert "promoted_strategy_scan_market_universe_changed" in blockers_changed
