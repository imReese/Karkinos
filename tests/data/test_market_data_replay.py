"""Frozen market-data dataset replay tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.types import AssetClass, BarFrequency, Symbol
from data.market_data import (
    MarketDataEventKind,
    MarketDataRecord,
    MarketDataRecordMetadata,
    MarketDataStatus,
)
from data.market_data_replay import (
    MarketDataReplayUse,
    freeze_market_data_dataset,
)


def test_freezing_market_data_records_is_deterministic_and_replay_safe() -> None:
    frozen_at = datetime(2026, 6, 18, 16, 0, tzinfo=UTC)
    records = [
        _record(
            kind=MarketDataEventKind.SNAPSHOT,
            symbol="600519",
            timestamp=datetime(2026, 6, 18, 15, 0, tzinfo=UTC),
            source="provider_b",
            close=Decimal("10.30"),
        ),
        _record(
            kind=MarketDataEventKind.DAILY_BAR,
            symbol="600519",
            timestamp=datetime(2026, 6, 18, 9, 30, tzinfo=UTC),
            source="provider_a",
            close=Decimal("10.00"),
        ),
    ]

    first = freeze_market_data_dataset(records, frozen_at=frozen_at)
    second = freeze_market_data_dataset(list(reversed(records)), frozen_at=frozen_at)

    assert first.dataset_id == second.dataset_id
    assert first.record_count == 2
    assert first.schema_version == "karkinos.market_data_dataset.v1"
    assert first.allowed_uses == (
        MarketDataReplayUse.BACKTEST,
        MarketDataReplayUse.STRATEGY_RUNTIME_DRY_RUN,
        MarketDataReplayUse.PAPER_SHADOW_REVIEW,
        MarketDataReplayUse.AUDIT_REPLAY,
    )
    assert first.trading_behavior_changed is False
    assert first.broker_order_submission_enabled is False
    assert first.manual_confirmation_required_unchanged is True

    replayed = first.replay(MarketDataReplayUse.BACKTEST)
    assert [record.kind for record in replayed] == [
        MarketDataEventKind.DAILY_BAR,
        MarketDataEventKind.SNAPSHOT,
    ]
    assert [record.metadata.source for record in replayed] == [
        "provider_a",
        "provider_b",
    ]


def test_frozen_market_data_dataset_payload_is_stable_and_rejects_unallowed_use() -> (
    None
):
    frozen_at = datetime(2026, 6, 18, 16, 0, tzinfo=UTC)
    dataset = freeze_market_data_dataset(
        [_record(kind=MarketDataEventKind.DAILY_BAR, symbol="019999")],
        frozen_at=frozen_at,
        allowed_uses=(MarketDataReplayUse.AUDIT_REPLAY,),
    )

    payload = dataset.to_payload()
    assert payload["dataset_id"].startswith("sha256:")
    assert payload["record_count"] == 1
    assert payload["allowed_uses"] == ["audit_replay"]
    assert payload["records"][0]["values"] == {"close": "10.00"}
    assert payload["safety"] == {
        "trading_behavior_changed": False,
        "broker_order_submission_enabled": False,
        "manual_confirmation_required_unchanged": True,
    }

    with pytest.raises(ValueError, match="not allowed for frozen dataset"):
        dataset.replay(MarketDataReplayUse.BACKTEST)


def test_strategy_runtime_dry_run_replay_evidence_keeps_estimates_unconfirmed() -> None:
    frozen_at = datetime(2026, 6, 18, 16, 0, tzinfo=UTC)
    dataset = freeze_market_data_dataset(
        [
            _record(
                kind=MarketDataEventKind.DAILY_BAR,
                symbol="600519",
                status=MarketDataStatus.CONFIRMED,
            ),
            _record(
                kind=MarketDataEventKind.SNAPSHOT,
                symbol="019999",
                status=MarketDataStatus.ESTIMATED,
            ),
        ],
        frozen_at=frozen_at,
    )

    evidence = dataset.replay_evidence(
        MarketDataReplayUse.STRATEGY_RUNTIME_DRY_RUN
    ).to_payload()

    assert evidence["use"] == "strategy_runtime_dry_run"
    assert evidence["record_count"] == 2
    assert evidence["status_counts"] == {"confirmed": 1, "estimated": 1}
    assert evidence["unconfirmed_statuses"] == ["estimated"]
    assert evidence["can_present_as_confirmed_returns"] is False
    assert evidence["required_action"] == (
        "refresh_or_replay_confirmed_market_data_before_claiming_confirmed_returns"
    )
    assert evidence["safety"] == {
        "trading_behavior_changed": False,
        "broker_order_submission_enabled": False,
        "manual_confirmation_required_unchanged": True,
    }


def _record(
    *,
    kind: MarketDataEventKind,
    symbol: str,
    timestamp: datetime | None = None,
    source: str = "fixture_provider",
    close: Decimal = Decimal("10.00"),
    status: MarketDataStatus = MarketDataStatus.CONFIRMED,
) -> MarketDataRecord:
    observed_at = timestamp or datetime(2026, 6, 18, 15, 0, tzinfo=UTC)
    return MarketDataRecord(
        kind=kind,
        symbol=Symbol(symbol),
        asset_class=AssetClass.FUND if symbol.startswith("0") else AssetClass.STOCK,
        timestamp=observed_at,
        values={"close": close},
        frequency=BarFrequency.DAILY,
        metadata=MarketDataRecordMetadata(
            source=source,
            status=status,
            observed_at=observed_at,
            source_symbol=f"{symbol}.TEST",
            trading_session="2026-06-18",
            adjustment_mode="qfq",
            freshness={"age_seconds": 0},
        ),
    )
