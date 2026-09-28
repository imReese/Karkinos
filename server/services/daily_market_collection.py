"""Automatically capture one daily-bar source and persist its quality evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import (
    DailyBarProviderUnavailableError,
    DailyBarRequest,
)
from data.market.ingestion import DailyBarIngestionNoData, ingest_daily_bars
from data.market.quality import RESEARCH_STRICT_DAILY
from data.market.quality_evidence import publish_market_quality_evidence
from data.source_policy import MarketDataUseCase, resolve_market_source_policy
from data.source_routing import provider_registry_for_config
from data.storage.objects import ContentAddressedObjectStore

DAILY_MARKET_COLLECTION_JOB = "market_daily_collection"
DAILY_MARKET_COLLECTION_JOB_SCHEMA_VERSION = "karkinos.market_daily_collection_job.v1"
_NORMALIZER_VERSION = "karkinos.market.normalize.v1"


@dataclass(frozen=True, slots=True)
class DailyMarketCollectionJobRequest:
    trade_date: date
    instrument: InstrumentKey
    source_policy_id: str
    calendar_evidence_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": DAILY_MARKET_COLLECTION_JOB_SCHEMA_VERSION,
            "trade_date": self.trade_date.isoformat(),
            "instrument": {
                "symbol": self.instrument.symbol,
                "instrument_type": self.instrument.instrument_type.value,
            },
            "source_policy_id": self.source_policy_id,
            "calendar_evidence_refs": list(self.calendar_evidence_refs),
        }

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> DailyMarketCollectionJobRequest:
        if (
            not isinstance(payload, Mapping)
            or set(payload)
            != {
                "schema_version",
                "trade_date",
                "instrument",
                "source_policy_id",
                "calendar_evidence_refs",
            }
            or payload.get("schema_version")
            != DAILY_MARKET_COLLECTION_JOB_SCHEMA_VERSION
        ):
            raise ValueError("daily_market_collection_payload_invalid")
        raw = payload["instrument"]
        raw_refs = payload["calendar_evidence_refs"]
        if (
            not isinstance(payload["trade_date"], str)
            or not isinstance(raw, Mapping)
            or set(raw) != {"symbol", "instrument_type"}
            or not isinstance(payload["source_policy_id"], str)
            or not isinstance(raw_refs, list)
        ):
            raise ValueError("daily_market_collection_payload_invalid")
        try:
            trade_date = date.fromisoformat(payload["trade_date"])
            instrument = InstrumentKey(
                raw["symbol"], InstrumentType(raw["instrument_type"])
            )
            policy_id = str(payload["source_policy_id"]).strip()
            refs = tuple(raw_refs)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("daily_market_collection_payload_invalid") from exc
        if (
            instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}
            or not policy_id
            or not refs
            or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
            or len(set(refs)) != len(refs)
        ):
            raise ValueError("daily_market_collection_payload_invalid")
        resolve_market_source_policy(policy_id)
        return cls(trade_date, instrument, policy_id, refs)


class DailyMarketCollectionService:
    """Collection stops at quality; it grants no Dataset or research eligibility."""

    def __init__(self, root: str | Path, config: object) -> None:
        self.root = Path(root).resolve()
        self._config = config

    def run(
        self,
        payload: Mapping[str, Any],
        *,
        checked_at: datetime | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> str:
        request = DailyMarketCollectionJobRequest.from_payload(payload)
        checked_at = checked_at or datetime.now(timezone.utc)
        if (
            not isinstance(checked_at, datetime)
            or checked_at.tzinfo is None
            or checked_at.utcoffset() is None
        ):
            raise ValueError("daily_market_collection_checked_at_naive")
        policy = resolve_market_source_policy(request.source_policy_id)
        route = policy.route(MarketDataUseCase.DAILY_BARS)
        if route.price_basis not in {None, "unadjusted"}:
            raise ValueError("daily_market_collection_price_basis_unsupported")
        providers = provider_registry_for_config(
            self._config, include_tdx=False
        ).daily_bar_providers(route.candidates)
        daily_request = DailyBarRequest(
            (request.instrument,), request.trade_date, request.trade_date
        )
        store = ContentAddressedObjectStore(self.root / "objects")
        for name, provider in providers:
            descriptor = provider.descriptor
            if not descriptor.supports_daily_bars(
                request.instrument.instrument_type, price_basis="unadjusted"
            ):
                continue
            try:
                result = ingest_daily_bars(
                    provider,
                    store,
                    request=daily_request,
                    quality_policy=RESEARCH_STRICT_DAILY,
                    normalizer_version=_NORMALIZER_VERSION,
                    checked_at=checked_at,
                )
            except (DailyBarProviderUnavailableError, DailyBarIngestionNoData):
                continue
            if (
                result.capture.provider != name
                or result.capture.adapter_version != descriptor.adapter_version
            ):
                raise ValueError("daily_market_collection_provider_identity_mismatch")
            if before_publish is not None:
                before_publish()
            quality = publish_market_quality_evidence(store, result.quality)
            return f"quality:{quality.quality_id}"
        raise RuntimeError("daily_market_collection_sources_unavailable")
