"""Publish one verified daily market-data partition from versioned source policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.dataset.resolver import (
    DailyBarDatasetResolverPolicy,
    resolve_daily_bar_dataset,
)
from data.market.contracts import DailyBarRequest
from data.market.cross_source import (
    CrossSourceDailyBarResult,
    ingest_cross_source_daily_bars,
)
from data.market.quality import RESEARCH_STRICT_DAILY
from data.market.serving import MarketServingStore
from data.source_policy import resolve_market_source_policy
from data.source_routing import (
    provider_registry_for_config,
    resolve_daily_bar_verification_pair,
)
from data.storage.objects import ContentAddressedObjectStore

VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION = "karkinos.market_daily_verified_job.v1"
_NORMALIZER_VERSION = "karkinos.market.normalize.v1"
_RESOLVER_POLICY_PREFIX = "karkinos.dataset.pit.verified.daily.v1:"


class VerifiedDailyMarketDataError(RuntimeError):
    """Base failure for verified daily publication."""


class VerifiedDailyMarketDataRequestError(VerifiedDailyMarketDataError):
    """A durable job payload is not a valid market-data request."""


class VerifiedDailyMarketDataNotPublishable(VerifiedDailyMarketDataError):
    """Evidence was captured but does not authorize a verified dataset."""


@dataclass(frozen=True, slots=True)
class VerifiedDailyMarketPublication:
    dataset_ref: DatasetRef
    verification_id: str
    trade_date: date
    source_policy_id: str
    primary_provider: str
    comparison_provider: str

    @property
    def dataset_id(self) -> str:
        return self.dataset_ref.dataset_id

    @property
    def result_ref(self) -> str:
        return f"dataset:{self.dataset_id}"


@dataclass(frozen=True, slots=True)
class VerifiedDailyMarketJobRequest:
    trade_date: date
    instruments: tuple[InstrumentKey, ...]
    source_policy_id: str
    calendar_evidence_refs: tuple[str, ...]
    observation_round: str = "post_close.v1"

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> VerifiedDailyMarketJobRequest:
        if not isinstance(payload, Mapping):
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_payload_invalid"
            )
        if payload.get("schema_version") != VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION:
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_schema_unsupported"
            )
        try:
            trade_date = date.fromisoformat(str(payload["trade_date"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_trade_date_invalid"
            ) from exc

        raw_instruments = payload.get("instruments")
        if not isinstance(raw_instruments, list) or not raw_instruments:
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_instruments_invalid"
            )
        instruments: list[InstrumentKey] = []
        seen: set[InstrumentKey] = set()
        for raw in raw_instruments:
            if not isinstance(raw, Mapping):
                raise VerifiedDailyMarketDataRequestError(
                    "verified_daily_market_instrument_invalid"
                )
            try:
                instrument = InstrumentKey(
                    str(raw["symbol"]),
                    InstrumentType(str(raw["instrument_type"])),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise VerifiedDailyMarketDataRequestError(
                    "verified_daily_market_instrument_invalid"
                ) from exc
            if instrument.instrument_type not in {
                InstrumentType.STOCK,
                InstrumentType.ETF,
            }:
                raise VerifiedDailyMarketDataRequestError(
                    "verified_daily_market_instrument_type_unsupported"
                )
            if instrument in seen:
                raise VerifiedDailyMarketDataRequestError(
                    "verified_daily_market_instrument_duplicate"
                )
            seen.add(instrument)
            instruments.append(instrument)

        source_policy_id = str(payload.get("source_policy_id") or "").strip()
        if not source_policy_id:
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_source_policy_missing"
            )
        # Resolve now so an unknown policy fails before any provider I/O.
        resolve_market_source_policy(source_policy_id)

        raw_refs = payload.get("calendar_evidence_refs")
        if not isinstance(raw_refs, list) or not raw_refs:
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_calendar_evidence_missing"
            )
        refs = tuple(str(item).strip() for item in raw_refs)
        if any(not item for item in refs) or len(set(refs)) != len(refs):
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_calendar_evidence_invalid"
            )

        observation_round = str(
            payload.get("observation_round") or "post_close.v1"
        ).strip()
        if not observation_round:
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_observation_round_invalid"
            )

        return cls(
            trade_date=trade_date,
            instruments=tuple(
                sorted(
                    instruments,
                    key=lambda item: (
                        item.instrument_type.value,
                        item.symbol,
                    ),
                )
            ),
            source_policy_id=source_policy_id,
            calendar_evidence_refs=refs,
            observation_round=observation_round,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION,
            "trade_date": self.trade_date.isoformat(),
            "instruments": [
                {
                    "symbol": item.symbol,
                    "instrument_type": item.instrument_type.value,
                }
                for item in self.instruments
            ],
            "source_policy_id": self.source_policy_id,
            "calendar_evidence_refs": list(self.calendar_evidence_refs),
            "observation_round": self.observation_round,
        }


class VerifiedDailyMarketDataService:
    """Build verified evidence first, then publish only behind a fencing guard."""

    def __init__(self, root: str | Path, config: object) -> None:
        self.root = Path(root).resolve()
        self._config = config

    def run(
        self,
        payload: Mapping[str, Any],
        *,
        checked_at: datetime | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> VerifiedDailyMarketPublication:
        request = VerifiedDailyMarketJobRequest.from_payload(payload)
        checked_at = _utc_now(checked_at)

        daily_request = DailyBarRequest(
            request.instruments,
            request.trade_date,
            request.trade_date,
        )
        policy = resolve_market_source_policy(request.source_policy_id)
        registry = provider_registry_for_config(self._config, include_tdx=False)
        pair = resolve_daily_bar_verification_pair(
            policy,
            registry,
            daily_request,
        )

        store = ContentAddressedObjectStore(self.root / "objects")
        evidence = ingest_cross_source_daily_bars(
            pair.primary,
            pair.comparison,
            store,
            request=daily_request,
            quality_policy=RESEARCH_STRICT_DAILY,
            normalizer_version=_NORMALIZER_VERSION,
            reconciliation_policy=pair.reconciliation_policy,
            checked_at=checked_at,
        )
        if not evidence.eligible_for_verified_dataset:
            raise VerifiedDailyMarketDataNotPublishable(_not_publishable_code(evidence))
        assert evidence.verification is not None

        candidates = evidence.resolution_candidates()
        resolver_policy = DailyBarDatasetResolverPolicy(
            policy_id=_resolver_policy_id(policy.policy_id),
            provider_priority=(pair.primary_name, pair.comparison_name),
            required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
        )
        cutoff = max(
            evidence.primary.capture.completed_at,
            evidence.comparison.capture.completed_at,
            evidence.verification.checked_at,
        )
        snapshot = resolve_daily_bar_dataset(
            store,
            candidates=candidates,
            start_date=request.trade_date,
            end_date=request.trade_date,
            cutoff=cutoff,
            instruments=request.instruments,
            expected_partition_dates=(request.trade_date,),
            policy=resolver_policy,
        )
        if not snapshot.verification_bound:
            raise VerifiedDailyMarketDataNotPublishable(
                "verified_daily_market_dataset_not_verification_bound"
            )

        dataset_ref = publish_daily_bar_dataset_manifest(store, snapshot)
        # Re-read from immutable truth before making any mutable projection visible.
        replayed = read_daily_bar_dataset(store, dataset_ref)
        if replayed.snapshot != snapshot:
            raise VerifiedDailyMarketDataError(
                "verified_daily_market_dataset_replay_mismatch"
            )

        if before_publish is not None:
            before_publish()

        DatasetCatalog(self.root).register(
            store,
            dataset_ref,
            registered_at=checked_at,
        )
        selected = _selected_candidate(evidence, snapshot.partitions[0].provider)
        MarketServingStore(self.root).apply_daily_bar_revision(
            store,
            revision=selected.revision,
            materialization=selected.materialization,
        )

        return VerifiedDailyMarketPublication(
            dataset_ref=dataset_ref,
            verification_id=evidence.verification.verification_id,
            trade_date=request.trade_date,
            source_policy_id=policy.policy_id,
            primary_provider=pair.primary_name,
            comparison_provider=pair.comparison_name,
        )


def _selected_candidate(
    evidence: CrossSourceDailyBarResult,
    provider: str,
):
    if evidence.primary.revision.provider == provider:
        return evidence.primary
    if evidence.comparison.revision.provider == provider:
        return evidence.comparison
    raise VerifiedDailyMarketDataError(
        "verified_daily_market_selected_provider_missing"
    )


def _resolver_policy_id(source_policy_id: str) -> str:
    return _RESOLVER_POLICY_PREFIX + source_policy_id


def is_verified_daily_resolver_policy(policy_id: str) -> bool:
    return str(policy_id).startswith(_RESOLVER_POLICY_PREFIX)


def _not_publishable_code(result: CrossSourceDailyBarResult) -> str:
    if result.verification is None:
        return "verified_daily_market_quality_blocked"
    return "verified_daily_market_cross_source_conflict"


def _utc_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("verified_daily_market_checked_at_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("verified_daily_market_checked_at_must_be_timezone_aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION",
    "VerifiedDailyMarketDataError",
    "VerifiedDailyMarketDataNotPublishable",
    "VerifiedDailyMarketDataRequestError",
    "VerifiedDailyMarketDataService",
    "VerifiedDailyMarketJobRequest",
    "VerifiedDailyMarketPublication",
    "is_verified_daily_resolver_policy",
]
