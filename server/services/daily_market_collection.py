"""Automatically capture one daily-bar source and persist its quality evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.market.capture import ProviderCaptureError, read_provider_capture
from data.market.contracts import (
    DailyBarProviderUnavailableError,
    DailyBarRequest,
)
from data.market.ingestion import (
    DailyBarIngestionCapturedFailure,
    DailyBarIngestionNoData,
    ingest_daily_bars,
)
from data.market.quality import RESEARCH_STRICT_DAILY, MarketDataQualityReport
from data.market.quality_evidence import (
    MarketQualityEvidenceError,
    publish_market_quality_evidence,
    read_market_quality_evidence,
)
from data.market.revision import (
    MarketRevisionError,
    MarketRevisionRef,
    read_market_revision,
    read_market_revision_materialization,
)
from data.source_policy import MarketDataUseCase, resolve_market_source_policy
from data.source_routing import provider_registry_for_config
from data.storage.objects import ContentAddressedObjectStore, ObjectStoreError
from server.persistence.jobs import SQLiteJobStore

DAILY_MARKET_COLLECTION_JOB = "market_daily_collection"
DAILY_MARKET_COLLECTION_JOB_SCHEMA_VERSION = "karkinos.market_daily_collection_job.v1"
_NORMALIZER_VERSION = "karkinos.market.normalize.v1"


class DailyMarketCollectionFailure(RuntimeError):
    """A collection attempt failed after optionally persisting Capture evidence."""

    def __init__(self, code: str, *, capture_id: str | None = None) -> None:
        self.failure_evidence_ref = f"capture:{capture_id}" if capture_id else None
        super().__init__(code)


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
        if checked_at is not None and (
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
        last_capture_id: str | None = None
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
            except DailyBarProviderUnavailableError:
                continue
            except DailyBarIngestionNoData as exc:
                last_capture_id = exc.capture.capture_id
                continue
            except DailyBarIngestionCapturedFailure as exc:
                raise DailyMarketCollectionFailure(
                    "daily_market_collection_ingestion_failed_after_capture",
                    capture_id=exc.capture.capture_id,
                ) from exc
            if (
                result.capture.provider != name
                or result.capture.adapter_version != descriptor.adapter_version
            ):
                raise DailyMarketCollectionFailure(
                    "daily_market_collection_provider_identity_mismatch",
                    capture_id=result.capture.capture_id,
                )
            if result.revision.partition_date != request.trade_date:
                raise DailyMarketCollectionFailure(
                    "daily_market_collection_partition_date_mismatch",
                    capture_id=result.capture.capture_id,
                )
            if before_publish is not None:
                before_publish()
            quality = publish_market_quality_evidence(store, result.quality)
            return f"quality:{quality.quality_id}"
        raise DailyMarketCollectionFailure(
            "daily_market_collection_sources_unavailable",
            capture_id=last_capture_id,
        )


def list_daily_market_collection_quality(
    db_path: str | Path, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Read recent automatic collection jobs and their immutable quality evidence."""
    rows = SQLiteJobStore(db_path).list_recent(DAILY_MARKET_COLLECTION_JOB, limit=limit)
    objects = ContentAddressedObjectStore(
        Path(db_path).resolve().parent / "research" / "objects"
    )
    return [_collection_quality_row(row, objects) for row in rows]


def _collection_quality_row(
    row: Mapping[str, Any], objects: ContentAddressedObjectStore
) -> dict[str, Any]:
    try:
        request = DailyMarketCollectionJobRequest.from_payload(
            json.loads(row["payload_json"])
        )
    except (KeyError, TypeError, ValueError):
        request = None

    result: dict[str, Any] = {
        "job_id": row["job_id"],
        "trade_date": request.trade_date.isoformat() if request else None,
        "instrument": (
            {
                "symbol": request.instrument.symbol,
                "instrument_type": request.instrument.instrument_type.value,
            }
            if request
            else None
        ),
        "source_policy_id": request.source_policy_id if request else None,
        "job_status": row["status"],
        "attempt": row["attempt"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "error": row["error"],
        "result_ref": row["result_ref"],
        "failure_evidence_ref": row["failure_evidence_ref"],
        "quality_read_status": "not_recorded",
        "quality_attribution_status": "not_checked",
        "quality": None,
    }
    if row["status"] != "succeeded":
        return result

    result["quality_read_status"] = "unreadable"
    try:
        result_ref = row["result_ref"]
        if not isinstance(result_ref, str) or not result_ref.startswith(
            "quality:sha256:"
        ):
            raise ValueError("daily_market_collection_quality_ref_invalid")
        evidence = read_market_quality_evidence(
            objects, objects.resolve_ref(result_ref.removeprefix("quality:"))
        )
    except (
        ValueError,
        OSError,
        ObjectStoreError,
        MarketQualityEvidenceError,
    ):
        return result
    result["quality_read_status"] = "available"
    result["quality"] = _collection_quality_report(evidence.report, evidence.quality_id)
    if request is None:
        result["quality_attribution_status"] = "unreadable"
        return result
    try:
        provider = _collection_quality_provider(
            objects, request=request, report=evidence.report
        )
    except ValueError:
        result["quality_attribution_status"] = "mismatch"
        return result
    except (
        OSError,
        ObjectStoreError,
        MarketRevisionError,
        ProviderCaptureError,
    ):
        result["quality_attribution_status"] = "unreadable"
        return result
    result["quality_attribution_status"] = "verified"
    result["quality"]["provider"] = provider
    return result


def _collection_quality_provider(
    objects: ContentAddressedObjectStore,
    *,
    request: DailyMarketCollectionJobRequest,
    report: MarketDataQualityReport,
) -> str:
    revision = read_market_revision(
        objects, MarketRevisionRef(objects.resolve_ref(report.revision_id))
    )
    materialization = read_market_revision_materialization(
        objects, objects.resolve_ref(report.materialization_id)
    )
    capture = read_provider_capture(objects, materialization.capture_ref)
    expected_request = DailyBarRequest(
        (request.instrument,), request.trade_date, request.trade_date
    ).to_capture_request()
    route = resolve_market_source_policy(request.source_policy_id).route(
        MarketDataUseCase.DAILY_BARS
    )
    if (
        materialization.revision_ref.revision_id != revision.ref.revision_id
        or revision.partition_date != request.trade_date
        or capture.provider != revision.provider
        or revision.provider not in route.candidates
        or revision.provider == "tdx"
        or capture.operation != "daily_bars"
        or json.loads(capture.request_json) != expected_request
        or report.policy_id != RESEARCH_STRICT_DAILY.policy_id
        or report.expected_instrument_count != 1
    ):
        raise ValueError("daily_market_collection_quality_lineage_mismatch")
    return revision.provider


def _collection_quality_report(
    report: MarketDataQualityReport, quality_id: str
) -> dict[str, Any]:
    return {
        "quality_id": quality_id,
        "status": report.status.value,
        "policy_id": report.policy_id,
        "checked_at": report.checked_at.isoformat(),
        "provider": None,
        "revision_id": report.revision_id,
        "materialization_id": report.materialization_id,
        "observed_instrument_count": report.observed_instrument_count,
        "expected_instrument_count": report.expected_instrument_count,
        "diagnostics": [
            {
                "kind": item.kind.value,
                "severity": item.severity.value,
                "instrument": (
                    {
                        "symbol": item.instrument.symbol,
                        "instrument_type": item.instrument.instrument_type.value,
                    }
                    if item.instrument
                    else None
                ),
                "details": dict(item.details),
            }
            for item in report.diagnostics
        ],
    }
