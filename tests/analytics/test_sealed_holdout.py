from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from analytics.sealed_holdout import (
    SEALED_HOLDOUT_EVIDENCE_SCHEMA_VERSION,
    SealedHoldoutPartition,
    build_consumption_receipt,
    build_sealed_holdout_evaluation,
    is_partition_consumed,
    is_valid_sealed_holdout_evaluation,
    split_sealed_holdout,
)
from backtest.result import BacktestResult
from core.events import FillEvent
from core.types import OrderSide, Symbol


def _fill(timestamp: datetime, commission: str, slippage: str) -> FillEvent:
    return FillEvent(
        timestamp=timestamp,
        fill_id=f"FILL-{timestamp.day}",
        order_id=f"ORD-{timestamp.day}",
        symbol=Symbol("510300"),
        side=OrderSide.BUY,
        fill_price=Decimal("10"),
        fill_quantity=Decimal("100"),
        commission=Decimal(commission),
        slippage=Decimal(slippage),
    )


def _result() -> BacktestResult:
    return BacktestResult(
        equity_curve=[
            (datetime(2026, 1, 1), Decimal("100000")),
            (datetime(2026, 1, 5), Decimal("101000")),
            (datetime(2026, 1, 10), Decimal("100500")),
            (datetime(2026, 1, 15), Decimal("102000")),
            (datetime(2026, 1, 16), Decimal("103000")),  # research boundary
            (datetime(2026, 1, 17), Decimal("104000")),  # sealed starts
            (datetime(2026, 1, 18), Decimal("105000")),
            (datetime(2026, 1, 20), Decimal("106000")),
        ],
        positions={},
        initial_cash=Decimal("100000"),
        final_equity=Decimal("106000"),
        fills=[
            _fill(datetime(2026, 1, 6), "4", "1"),
            _fill(datetime(2026, 1, 18), "6", "2"),
        ],
    )


def _partition() -> SealedHoldoutPartition:
    return split_sealed_holdout(
        start_date="2026-01-01",
        end_date="2026-01-20",
        holdout_fraction=Decimal("0.2"),
    )


def test_split_sealed_holdout_is_deterministic_and_contiguous():
    partition = _partition()
    assert partition.research_start.isoformat() == "2026-01-01"
    assert partition.research_end.isoformat() == "2026-01-16"
    assert partition.sealed_start.isoformat() == "2026-01-17"
    assert partition.sealed_end.isoformat() == "2026-01-20"
    assert partition.partition_fingerprint.startswith("sha256:")
    assert partition.partition_fingerprint == _partition().partition_fingerprint


def test_split_sealed_holdout_rejects_bad_fraction_and_short_window():
    with pytest.raises(ValueError):
        split_sealed_holdout(
            start_date="2026-01-01",
            end_date="2026-01-20",
            holdout_fraction=Decimal("0.9"),
        )
    with pytest.raises(ValueError):
        split_sealed_holdout(
            start_date="2026-01-01",
            end_date="2026-01-01",
            holdout_fraction=Decimal("0.2"),
        )


def test_build_sealed_evaluation_measures_sealed_tail_once():
    evidence = build_sealed_holdout_evaluation(
        strategy_id="ai_formula_research",
        benchmark_role="formula_champion",
        research_family_id="family-1",
        formula_fingerprint="sha256:abcd",
        partition=_partition(),
        result=_result(),
        benchmark_return=Decimal("0.01"),
    )
    payload = evidence.to_json_dict()
    # sealed tail runs from 2026-01-17 boundary equity 103000 to final 106000
    assert payload["sealed_return"] == pytest.approx(
        float(Decimal("3000") / Decimal("103000"))
    )
    assert payload["sealed_cost"] == Decimal("8")
    assert payload["sealed_fill_count"] == 1
    assert payload["sealed_bar_count"] == 3
    assert payload["consumed_once"] is True
    assert payload["passed_benchmark"] is True
    assert payload["validation_status"] == "sealed_passed"
    assert is_valid_sealed_holdout_evaluation(payload) is True


def test_sealed_evaluation_rejects_reuse_after_consumption():
    partition = _partition()
    receipt = build_consumption_receipt(
        research_family_id="family-1",
        partition=partition,
        champion_formula_fingerprint="sha256:abcd",
        consumed_at="2026-01-21T00:00:00+00:00",
        evaluator_code_revision="rev-1",
    )
    assert is_partition_consumed(
        [receipt.to_json_dict()], partition.partition_fingerprint
    )
    with pytest.raises(ValueError):
        build_sealed_holdout_evaluation(
            strategy_id="ai_formula_research",
            benchmark_role="formula_champion",
            research_family_id="family-1",
            formula_fingerprint="sha256:abcd",
            partition=partition,
            result=_result(),
            prior_consumption_receipts=[receipt.to_json_dict()],
        )


def test_sealed_evaluation_requires_sealed_bars():
    result = BacktestResult(
        equity_curve=[
            (datetime(2026, 1, 1), Decimal("100000")),
            (datetime(2026, 1, 10), Decimal("101000")),
        ],
        positions={},
        initial_cash=Decimal("100000"),
        final_equity=Decimal("101000"),
        fills=[],
    )
    with pytest.raises(ValueError):
        build_sealed_holdout_evaluation(
            strategy_id="ai_formula_research",
            benchmark_role="formula_champion",
            research_family_id="family-1",
            formula_fingerprint="sha256:abcd",
            partition=_partition(),
            result=result,
        )


def test_validator_rejects_tampered_fingerprint_and_status():
    payload = build_sealed_holdout_evaluation(
        strategy_id="ai_formula_research",
        benchmark_role="formula_champion",
        research_family_id="family-1",
        formula_fingerprint="sha256:abcd",
        partition=_partition(),
        result=_result(),
    ).to_json_dict()
    assert is_valid_sealed_holdout_evaluation(payload) is True

    tampered = dict(payload)
    tampered["sealed_return"] = 0.5
    assert is_valid_sealed_holdout_evaluation(tampered) is False

    bad_fingerprint = dict(payload)
    bad_fingerprint["evidence_fingerprint"] = "f" * 64
    assert is_valid_sealed_holdout_evaluation(bad_fingerprint) is False
