"""Verify memoization and timeout fast-fail for promoted strategy universe scan."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from server.services.market.market_universe_truth import MarketUniversePolicy
from server.services.strategy_scan.universe.evaluation import (
    market_evaluation_cache_key,
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


def test_outside_window_without_cache_fast_fails_without_expensive_evaluation(
    monkeypatch,
) -> None:
    eval_mock = MagicMock()
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

    # When outside_window=True and no cache exists: fast-fail, no expensive call
    truths, signals, blockers = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc),
        outside_window=True,
    )
    assert eval_mock.call_count == 0
    assert truths == {}
    assert signals == []


def test_outside_window_with_existing_cache_reuses_cached_evaluation(
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

    # Initial run within window populates cache
    scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 9, 36, tzinfo=timezone.utc),
        outside_window=False,
    )
    assert eval_mock.call_count == 1

    # Second call outside window: reuses cache without calling evaluate_promoted_strategy_market again
    truths, signals, blockers = scanner._evaluate_promoted_strategies(
        promoted=promoted,
        market_date="2026-09-23",
        market=market,
        total_equity=100000.0,
        decision_at=datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc),
        outside_window=True,
    )
    assert eval_mock.call_count == 1
    assert "strategy:one" in truths
    assert len(signals) == 1


def test_validation_reuses_evaluation_cache_without_recomputing(monkeypatch) -> None:
    eval_mock = MagicMock()
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.evaluate_promoted_strategy_market",
        eval_mock,
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.load_exact_formula_market_inputs",
        lambda _db, _promoted, market_date, decision_at, saved_bindings: (
            {},
            {},
            {},
            [],
        ),
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.prior_verified_trading_date",
        lambda _db, _date: "2026-09-23",
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.require_complete_market_universe_snapshot",
        lambda _store, trade_date: {"snapshot_id": "snap:one", "symbols": ["600869"]},
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.resolve_daily_bar_receipt_provider",
        lambda config: "test",
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.resolve_daily_bar_receipts",
        lambda data_store, start_date, end_date, config, snapshot: [
            {"receipt_fingerprint": "receipt:one"}
        ],
    )
    monkeypatch.setattr(
        "server.services.strategy_scan.universe.validation.verified_trading_dates",
        lambda _db, start_date, end_date: ["2026-09-22", "2026-09-23"],
    )

    policy = MarketUniversePolicy()
    promoted = _mock_promoted()
    cache_key = market_evaluation_cache_key(
        market_date="2026-09-23",
        snapshot_id="snap:one",
        receipt_fingerprints=["receipt:one"],
        trading_dates=["2026-09-22", "2026-09-23"],
        start_date="2026-01-01",
        total_equity=100000.0,
        held_symbols=[],
        policy_fingerprint=promoted_scan_evaluation_policy_fingerprint(policy),
        promoted_strategies=promoted,
        formula_bindings={},
    )
    evaluation_cache = {
        cache_key: (
            {"strategy:one": {"evidence_fingerprint": "ev:one"}},
            [],
            [],
            {},
        )
    }

    scan = {
        "decision_date": "2026-09-24",
        "market_date": "2026-09-23",
        "strategy_bindings": [
            {
                "strategy_id": "strategy:one",
                "universe_truth_fingerprint": "ev:one",
            }
        ],
        "selected_signals": [],
        "signal_selection_fingerprint": "sha256:test",
    }

    blockers = current_scan_input_blockers(
        db=MagicMock(),
        config=None,
        data_store=MagicMock(),
        policy=policy,
        scan=scan,
        portfolio_summary={"total_equity": 100000.0, "valuation_status": "complete"},
        portfolio_reader=lambda p: (
            {
                "total_equity": 100000.0,
                "stock_symbols": [],
                "valuation_snapshot_id": "val:one",
                "valuation_status": "complete",
            },
            [],
        ),
        promoted_reader=lambda d: (promoted, []),
        safety_reader=lambda: {"status": "clear"},
        current_time=datetime(2026, 9, 24, 9, 36, tzinfo=timezone.utc),
        evaluation_cache=evaluation_cache,
    )

    # evaluate_promoted_strategy_market was NEVER called because cache hit!
    assert eval_mock.call_count == 0
