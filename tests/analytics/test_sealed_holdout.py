from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

import pytest

from analytics.sealed_holdout import (
    SEALED_HOLDOUT_EVIDENCE_SCHEMA_VERSION,
    SealedHoldoutPartition,
    build_consumption_receipt,
    build_sealed_holdout_evaluation,
    build_sealed_partition,
    is_partition_consumed,
    is_valid_sealed_holdout_evaluation,
    sealed_return_from_result,
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


def test_sealed_return_from_result_extracts_tail():
    result = _result()
    partition = _partition()
    # sealed tail runs from 2026-01-17 boundary equity 103000 to final 106000
    assert sealed_return_from_result(result, partition) == pytest.approx(
        Decimal("3000") / Decimal("103000")
    )


def test_build_sealed_partition_from_explicit_end():
    partition = build_sealed_partition(
        research_start="2026-01-01",
        research_end="2026-01-16",
        sealed_end="2026-01-20",
    )
    assert partition.research_start.isoformat() == "2026-01-01"
    assert partition.research_end.isoformat() == "2026-01-16"
    assert partition.sealed_start.isoformat() == "2026-01-17"
    assert partition.sealed_end.isoformat() == "2026-01-20"
    assert (
        partition.partition_fingerprint
        == build_sealed_partition(
            research_start="2026-01-01",
            research_end="2026-01-16",
            sealed_end="2026-01-20",
        ).partition_fingerprint
    )

    with pytest.raises(ValueError):
        build_sealed_partition(
            research_start="2026-01-01",
            research_end="2026-01-20",
            sealed_end="2026-01-20",
        )


def test_default_partition_preserves_original_serialized_identity():
    partition = build_sealed_partition(
        research_start="2026-01-01",
        research_end="2026-01-16",
        sealed_end="2026-01-20",
    )
    original = (
        '{"holdout_fraction":0.2,"research_end":"2026-01-16",'
        '"research_start":"2026-01-01",'
        '"schema_version":"karkinos.sealed_partition.v1",'
        '"sealed_end":"2026-01-20","sealed_start":"2026-01-17"}'
    )
    assert (
        json.dumps(partition.to_json_dict(), sort_keys=True, separators=(",", ":"))
        == original
    )
    assert partition.partition_fingerprint == (
        "sha256:" + hashlib.sha256(original.encode()).hexdigest()
    )


def test_prospective_partition_gap_does_not_become_research_or_test_days():
    partition = build_sealed_partition(
        research_start="2026-01-01",
        research_end="2026-01-16",
        sealed_end="2026-02-04",
        prospective_start="2026-02-01",
    )
    assert partition.research_end.isoformat() == "2026-01-16"
    assert partition.sealed_days == 4
    assert partition.holdout_fraction == Decimal("0.2")  # 4 / (16 + 4)
    assert partition.to_json_dict() == {
        "schema_version": "karkinos.sealed_partition.v2",
        "research_start": "2026-01-01",
        "research_end": "2026-01-16",
        "sealed_start": "2026-02-01",
        "sealed_end": "2026-02-04",
        "holdout_fraction": 0.2,
        "prospective_start": "2026-02-01",
    }
    result = BacktestResult(
        equity_curve=[
            (datetime(2026, 2, day), Decimal(value))
            for day, value in ((1, "100000"), (2, "101000"), (4, "102000"))
        ],
        positions={},
        initial_cash=Decimal("100000"),
        final_equity=Decimal("102000"),
        fills=[_fill(datetime(2026, 2, 2), "6", "2")],
        execution_timing={
            "evaluation_start": "2026-02-01",
            "warmup_basis": "strategy_history_only_fresh_book",
            "warmup_final_bar_targets": True,
        },
    )
    payload = build_sealed_holdout_evaluation(
        strategy_id="ai_formula_research",
        benchmark_role="formula_champion",
        research_family_id="family-1",
        formula_fingerprint="sha256:abcd",
        partition=partition,
        result=result,
        benchmark_return=Decimal("0.01"),
    ).to_json_dict()
    assert payload["sealed_bar_count"] == 3
    assert payload["sealed_return"] == pytest.approx(0.02)
    assert sealed_return_from_result(result, partition) == Decimal("0.02")
    assert is_valid_sealed_holdout_evaluation(payload)


@pytest.mark.parametrize(
    "start", ["2026-01-15", "2026-01-16", "2026-02-05", "20260201", ""]
)
def test_prospective_partition_rejects_invalid_or_noncanonical_start(start):
    with pytest.raises(ValueError):
        build_sealed_partition(
            research_start="2026-01-01",
            research_end="2026-01-16",
            sealed_end="2026-02-04",
            prospective_start=start,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "karkinos.sealed_partition.v1"},
        {"prospective_start": None},
        {"prospective_start": "2026-02-02"},
        {"holdout_fraction": 0.4},
    ],
)
def test_prospective_partition_parser_rejects_ignored_or_conflicting_binding(change):
    partition = build_sealed_partition(
        research_start="2026-01-01",
        research_end="2026-01-16",
        sealed_end="2026-02-04",
        prospective_start="2026-02-01",
    )
    from analytics.sealed_holdout import _validated_partition

    assert _validated_partition(partition.to_json_dict()) == partition
    assert _validated_partition({**partition.to_json_dict(), **change}) is None


@pytest.mark.parametrize("measure", ["return", "evaluation"])
def test_prospective_measurement_rejects_inherited_gap_equity(measure):
    partition = build_sealed_partition(
        research_start="2026-01-01",
        research_end="2026-01-16",
        sealed_end="2026-02-04",
        prospective_start="2026-02-01",
    )
    # This full-window book accumulated equity and a fill in the gap. It is
    # valid legacy evidence, but cannot supply a fresh prospective experiment.
    result = BacktestResult(
        equity_curve=[
            (datetime(2026, 1, 16), Decimal("100000")),
            (datetime(2026, 1, 31), Decimal("120000")),
            (datetime(2026, 2, 1), Decimal("121000")),
            (datetime(2026, 2, 4), Decimal("125000")),
        ],
        positions={},
        initial_cash=Decimal("100000"),
        final_equity=Decimal("125000"),
        fills=[_fill(datetime(2026, 1, 25), "6", "2")],
    )
    with pytest.raises(ValueError, match="sealed_prospective_fresh_book_required"):
        if measure == "return":
            sealed_return_from_result(result, partition)
        else:
            build_sealed_holdout_evaluation(
                strategy_id="ai_formula_research",
                benchmark_role="formula_champion",
                research_family_id="family-1",
                formula_fingerprint="sha256:abcd",
                partition=partition,
                result=result,
                benchmark_return=Decimal("0.01"),
            )
