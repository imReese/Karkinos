"""Strategy signal preview adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.events import MarketEvent
from core.types import BarFrequency, Symbol


def _bar(day: int, close: str) -> MarketEvent:
    price = Decimal(close)
    return MarketEvent(
        timestamp=datetime(2026, 6, day, 15, 0, tzinfo=UTC),
        symbol=Symbol("600000"),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1000"),
        frequency=BarFrequency.DAILY,
    )


def test_strategy_signal_preview_converts_legacy_signal_into_candidate_action() -> (
    None
):
    from analytics.strategy_signal_preview import build_strategy_signal_preview

    preview = build_strategy_signal_preview(
        strategy_id="dual_ma",
        symbol="600000",
        params={"short_period": 2, "long_period": 3},
        bars=(
            _bar(1, "3"),
            _bar(2, "2"),
            _bar(3, "1"),
            _bar(4, "4"),
        ),
        dataset_snapshot={
            "schema_version": "karkinos.dataset_snapshot.v1",
            "snapshot_id": "snapshot-signal-preview-001",
            "data_quality": {"status": "pass"},
        },
    )

    assert preview["schema_version"] == "karkinos.strategy_signal_preview.v1"
    assert preview["strategy_id"] == "dual_ma"
    assert preview["symbol"] == "600000"
    assert preview["dataset_snapshot_id"] == "snapshot-signal-preview-001"
    assert preview["record_count"] == 1
    assert preview["does_not_enable_execution"] is True

    record = preview["outputs"][0]
    assert record["schema_version"] == "karkinos.strategy_runtime_output.v1"
    assert record["record_kind"] == "candidate_action"
    assert record["output_type"] == "buy_candidate"
    assert record["action"] == "buy"
    assert record["symbol"] == "600000"
    assert record["target_weight"] == "1.0"
    assert record["price"] == "4.0"
    assert record["requires_risk_gate"] is True
    assert record["requires_account_truth_gate"] is True
    assert record["requires_paper_shadow_review"] is True
    assert record["requires_manual_review"] is True
    assert record["does_not_enable_execution"] is True
    assert record["evidence"]["bar_count"] == 4
    assert record["evidence"]["dataset_snapshot_id"] == "snapshot-signal-preview-001"
    assert record["evidence"]["data_quality_status"] == "pass"


def test_strategy_signal_preview_returns_no_action_when_strategy_emits_no_signal() -> (
    None
):
    from analytics.strategy_signal_preview import build_strategy_signal_preview

    preview = build_strategy_signal_preview(
        strategy_id="dual_ma",
        symbol="600000",
        params={"short_period": 2, "long_period": 3},
        bars=(
            _bar(1, "3"),
            _bar(2, "2"),
        ),
        dataset_snapshot={
            "schema_version": "karkinos.dataset_snapshot.v1",
            "snapshot_id": "snapshot-signal-preview-002",
            "data_quality": {"status": "degraded"},
        },
    )

    assert preview["record_count"] == 1
    record = preview["outputs"][0]
    assert record["record_kind"] == "explanation"
    assert record["output_type"] == "no_action"
    assert record["action"] == "no_action"
    assert record["requires_risk_gate"] is False
    assert record["requires_account_truth_gate"] is False
    assert record["requires_paper_shadow_review"] is False
    assert record["requires_manual_review"] is False
    assert record["evidence"]["data_quality_status"] == "degraded"
