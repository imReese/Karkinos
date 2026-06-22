"""Frozen market-data dataset replay contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Sequence

from data.market_data import MarketDataRecord, MarketDataStatus


class MarketDataReplayUse(Enum):
    """Allowed deterministic replay consumers for frozen market data."""

    BACKTEST = "backtest"
    STRATEGY_RUNTIME_DRY_RUN = "strategy_runtime_dry_run"
    PAPER_SHADOW_REVIEW = "paper_shadow_review"
    AUDIT_REPLAY = "audit_replay"

    @property
    def label_zh(self) -> str:
        return {
            MarketDataReplayUse.BACKTEST: "回测",
            MarketDataReplayUse.STRATEGY_RUNTIME_DRY_RUN: "策略运行时干跑",
            MarketDataReplayUse.PAPER_SHADOW_REVIEW: "paper/shadow 复核",
            MarketDataReplayUse.AUDIT_REPLAY: "审计回放",
        }[self]


DEFAULT_REPLAY_USES = (
    MarketDataReplayUse.BACKTEST,
    MarketDataReplayUse.STRATEGY_RUNTIME_DRY_RUN,
    MarketDataReplayUse.PAPER_SHADOW_REVIEW,
    MarketDataReplayUse.AUDIT_REPLAY,
)


@dataclass(frozen=True)
class MarketDataReplayEvidence:
    """Status evidence for a frozen replay consumer."""

    use: MarketDataReplayUse
    record_count: int
    status_counts: dict[str, int]
    unconfirmed_statuses: tuple[str, ...]
    trading_behavior_changed: bool = False
    broker_order_submission_enabled: bool = False
    manual_confirmation_required_unchanged: bool = True

    @property
    def can_present_as_confirmed_returns(self) -> bool:
        return not self.unconfirmed_statuses

    @property
    def required_action(self) -> str:
        if self.can_present_as_confirmed_returns:
            return "none"
        return (
            "refresh_or_replay_confirmed_market_data_before_claiming_confirmed_returns"
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "use": self.use.value,
            "use_label_zh": self.use.label_zh,
            "record_count": self.record_count,
            "status_counts": dict(self.status_counts),
            "unconfirmed_statuses": list(self.unconfirmed_statuses),
            "can_present_as_confirmed_returns": (self.can_present_as_confirmed_returns),
            "required_action": self.required_action,
            "safety": {
                "trading_behavior_changed": self.trading_behavior_changed,
                "broker_order_submission_enabled": (
                    self.broker_order_submission_enabled
                ),
                "manual_confirmation_required_unchanged": (
                    self.manual_confirmation_required_unchanged
                ),
            },
        }


@dataclass(frozen=True)
class FrozenMarketDataDataset:
    """Deterministic frozen market-data records and replay safety metadata."""

    dataset_id: str
    frozen_at: datetime
    records: tuple[MarketDataRecord, ...]
    allowed_uses: tuple[MarketDataReplayUse, ...] = DEFAULT_REPLAY_USES
    schema_version: str = "karkinos.market_data_dataset.v1"
    trading_behavior_changed: bool = False
    broker_order_submission_enabled: bool = False
    manual_confirmation_required_unchanged: bool = True

    @property
    def record_count(self) -> int:
        return len(self.records)

    def replay(self, use: MarketDataReplayUse) -> tuple[MarketDataRecord, ...]:
        """Replay frozen records in canonical order for an allowed consumer."""
        if use not in self.allowed_uses:
            raise ValueError(f"{use.value} is not allowed for frozen dataset")
        return self.records

    def replay_evidence(self, use: MarketDataReplayUse) -> MarketDataReplayEvidence:
        """Build deterministic status evidence for a replay consumer."""
        records = self.replay(use)
        status_counts: dict[str, int] = {}
        for record in records:
            status = record.metadata.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        unconfirmed_statuses = tuple(
            status
            for status in sorted(status_counts)
            if status != MarketDataStatus.CONFIRMED.value
        )
        return MarketDataReplayEvidence(
            use=use,
            record_count=len(records),
            status_counts=status_counts,
            unconfirmed_statuses=unconfirmed_statuses,
            trading_behavior_changed=self.trading_behavior_changed,
            broker_order_submission_enabled=self.broker_order_submission_enabled,
            manual_confirmation_required_unchanged=(
                self.manual_confirmation_required_unchanged
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "frozen_at": self.frozen_at.isoformat(),
            "record_count": self.record_count,
            "allowed_uses": [use.value for use in self.allowed_uses],
            "allowed_use_labels_zh": [use.label_zh for use in self.allowed_uses],
            "replay_evidence": [
                self.replay_evidence(use).to_payload() for use in self.allowed_uses
            ],
            "records": [_record_payload(record) for record in self.records],
            "safety": {
                "trading_behavior_changed": self.trading_behavior_changed,
                "broker_order_submission_enabled": (
                    self.broker_order_submission_enabled
                ),
                "manual_confirmation_required_unchanged": (
                    self.manual_confirmation_required_unchanged
                ),
            },
        }


def freeze_market_data_dataset(
    records: Sequence[MarketDataRecord],
    *,
    frozen_at: datetime,
    allowed_uses: Sequence[MarketDataReplayUse] = DEFAULT_REPLAY_USES,
) -> FrozenMarketDataDataset:
    """Freeze market data records into a deterministic replay dataset."""
    canonical_records = tuple(sorted(records, key=_record_sort_key))
    allowed = tuple(allowed_uses)
    identity_payload = {
        "schema_version": "karkinos.market_data_dataset.v1",
        "frozen_at": frozen_at.isoformat(),
        "record_count": len(canonical_records),
        "allowed_uses": [use.value for use in allowed],
        "records": [_record_payload(record) for record in canonical_records],
        "safety": {
            "trading_behavior_changed": False,
            "broker_order_submission_enabled": False,
            "manual_confirmation_required_unchanged": True,
        },
    }
    dataset_id = _stable_id(identity_payload)
    return FrozenMarketDataDataset(
        dataset_id=dataset_id,
        frozen_at=frozen_at,
        records=canonical_records,
        allowed_uses=allowed,
    )


def _stable_id(payload: dict[str, Any]) -> str:
    frozen = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(frozen.encode("utf-8")).hexdigest()


def _record_sort_key(record: MarketDataRecord) -> tuple[str, str, str, str, str]:
    source = record.metadata.source
    frequency = record.frequency.value if record.frequency is not None else ""
    return (
        record.timestamp.isoformat(),
        str(record.symbol),
        record.kind.value,
        frequency,
        source,
    )


def _record_payload(record: MarketDataRecord) -> dict[str, Any]:
    payload = record.to_payload()
    return _jsonable(payload)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
