"""Cross-source daily-bar ingestion and immutable verification orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from data.dataset.resolver import DailyBarResolutionCandidate
from data.market.contracts import (
    DailyBarProvider,
    DailyBarProviderUnavailableError,
    DailyBarRequest,
)
from data.market.ingestion import (
    DailyBarIngestionNoData,
    DailyBarIngestionResult,
    ingest_daily_bars,
)
from data.market.quality import (
    DailyBarQualityPolicy,
    MarketQualityStatus,
)
from data.market.quality_evidence import (
    MarketQualityEvidence,
    publish_market_quality_evidence,
)
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    DailyBarReconciliationPolicy,
    reconcile_daily_bar_revisions,
)
from data.market.verification_evidence import (
    MarketVerificationEvidence,
    MarketVerificationStatus,
    publish_market_verification_evidence,
)
from data.storage.objects import ContentAddressedObjectStore


class CrossSourceDailyBarError(RuntimeError):
    """Base error for cross-source canonical daily-bar ingestion."""


class CrossSourceDailyBarConfigurationError(CrossSourceDailyBarError):
    """Provider roles or reviewed capabilities cannot support verification."""


class CrossSourceDailyBarIntegrityError(CrossSourceDailyBarError):
    """A provider violated its declared canonical adapter identity."""


class CrossSourceDailyBarUnavailableError(CrossSourceDailyBarError):
    """One source could not produce a usable observation in this attempt."""

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = str(provider).strip()
        self.reason = str(reason).strip()
        super().__init__(
            f"cross_source_daily_bar_unavailable:{self.provider}:{self.reason}"
        )


@dataclass(frozen=True, slots=True)
class CrossSourceDailyBarResult:
    """Durable evidence produced by one two-source daily-bar observation."""

    primary: DailyBarIngestionResult
    comparison: DailyBarIngestionResult
    primary_quality: MarketQualityEvidence
    comparison_quality: MarketQualityEvidence
    verification: MarketVerificationEvidence | None

    @property
    def verification_status(self) -> str:
        if self.verification is None:
            return "quality_blocked"
        return self.verification.status.value

    @property
    def eligible_for_verified_dataset(self) -> bool:
        return (
            self.verification is not None
            and self.verification.status is MarketVerificationStatus.MATCHED
        )

    def resolution_candidates(self) -> tuple[DailyBarResolutionCandidate, ...]:
        """Return candidates only when the cross-source evidence fully matches."""
        if not self.eligible_for_verified_dataset:
            return ()
        assert self.verification is not None
        return (
            DailyBarResolutionCandidate(
                revision=self.primary.revision,
                materialization=self.primary.materialization,
                quality=self.primary.quality,
                verification=self.verification,
            ),
            DailyBarResolutionCandidate(
                revision=self.comparison.revision,
                materialization=self.comparison.materialization,
                quality=self.comparison.quality,
                verification=self.verification,
            ),
        )


def ingest_cross_source_daily_bars(
    primary_provider: DailyBarProvider,
    comparison_provider: DailyBarProvider,
    store: ContentAddressedObjectStore,
    *,
    request: DailyBarRequest,
    quality_policy: DailyBarQualityPolicy,
    normalizer_version: str,
    reconciliation_policy: DailyBarReconciliationPolicy = STRICT_DAILY_RECONCILIATION,
    checked_at: datetime | None = None,
) -> CrossSourceDailyBarResult:
    """Capture, normalize, quality-check, reconcile, and persist two sources."""
    if not isinstance(store, ContentAddressedObjectStore):
        raise TypeError("cross_source_daily_bar_store_invalid")
    if not isinstance(request, DailyBarRequest):
        raise TypeError("cross_source_daily_bar_request_invalid")
    if not isinstance(quality_policy, DailyBarQualityPolicy):
        raise TypeError("cross_source_daily_bar_quality_policy_invalid")
    if not isinstance(reconciliation_policy, DailyBarReconciliationPolicy):
        raise TypeError("cross_source_daily_bar_reconciliation_policy_invalid")

    primary_descriptor = primary_provider.descriptor
    comparison_descriptor = comparison_provider.descriptor
    _validate_provider_roles(
        request,
        primary_descriptor=primary_descriptor,
        comparison_descriptor=comparison_descriptor,
    )

    checked_at = _checked_at(checked_at)

    primary = _ingest_provider(
        primary_provider,
        store,
        request=request,
        quality_policy=quality_policy,
        normalizer_version=normalizer_version,
        checked_at=checked_at,
    )
    _validate_ingestion_identity(primary, primary_descriptor)

    comparison = _ingest_provider(
        comparison_provider,
        store,
        request=request,
        quality_policy=quality_policy,
        normalizer_version=normalizer_version,
        checked_at=checked_at,
    )
    _validate_ingestion_identity(comparison, comparison_descriptor)

    primary_quality = publish_market_quality_evidence(store, primary.quality)
    comparison_quality = publish_market_quality_evidence(store, comparison.quality)

    if (
        primary.quality.status is not MarketQualityStatus.PASS
        or comparison.quality.status is not MarketQualityStatus.PASS
    ):
        return CrossSourceDailyBarResult(
            primary=primary,
            comparison=comparison,
            primary_quality=primary_quality,
            comparison_quality=comparison_quality,
            verification=None,
        )

    report = reconcile_daily_bar_revisions(
        store,
        primary_revision=primary.revision,
        primary_materialization=primary.materialization,
        comparison_revision=comparison.revision,
        comparison_materialization=comparison.materialization,
        policy=reconciliation_policy,
    )
    verification = publish_market_verification_evidence(
        store,
        report=report,
        primary_quality=primary_quality,
        comparison_quality=comparison_quality,
        primary_descriptor=primary_descriptor,
        comparison_descriptor=comparison_descriptor,
        policy=reconciliation_policy,
        checked_at=checked_at,
    )
    return CrossSourceDailyBarResult(
        primary=primary,
        comparison=comparison,
        primary_quality=primary_quality,
        comparison_quality=comparison_quality,
        verification=verification,
    )


def _ingest_provider(
    provider: DailyBarProvider,
    store: ContentAddressedObjectStore,
    *,
    request: DailyBarRequest,
    quality_policy: DailyBarQualityPolicy,
    normalizer_version: str,
    checked_at: datetime,
) -> DailyBarIngestionResult:
    try:
        return ingest_daily_bars(
            provider,
            store,
            request=request,
            quality_policy=quality_policy,
            normalizer_version=normalizer_version,
            checked_at=checked_at,
        )
    except DailyBarIngestionNoData as exc:
        raise CrossSourceDailyBarUnavailableError(
            provider.descriptor.provider,
            "no_data",
        ) from exc
    except DailyBarProviderUnavailableError as exc:
        raise CrossSourceDailyBarUnavailableError(
            provider.descriptor.provider,
            "provider_unavailable",
        ) from exc


def _validate_provider_roles(
    request: DailyBarRequest,
    *,
    primary_descriptor,
    comparison_descriptor,
) -> None:
    if primary_descriptor.provider == comparison_descriptor.provider:
        raise CrossSourceDailyBarConfigurationError(
            "cross_source_daily_bar_provider_roles_must_differ"
        )
    if primary_descriptor.upstream_group == comparison_descriptor.upstream_group:
        raise CrossSourceDailyBarConfigurationError(
            "cross_source_daily_bar_upstream_groups_must_differ"
        )
    for descriptor in (primary_descriptor, comparison_descriptor):
        for instrument in request.instruments:
            if not descriptor.supports_daily_bars(
                instrument.instrument_type,
                price_basis="unadjusted",
            ):
                raise CrossSourceDailyBarConfigurationError(
                    "cross_source_daily_bar_capability_unsupported:"
                    f"{descriptor.provider}:{instrument.instrument_type.value}"
                )


def _validate_ingestion_identity(result, descriptor) -> None:
    if result.capture.provider != descriptor.provider:
        raise CrossSourceDailyBarIntegrityError(
            "cross_source_daily_bar_provider_identity_mismatch"
        )
    if result.capture.adapter_version != descriptor.adapter_version:
        raise CrossSourceDailyBarIntegrityError(
            "cross_source_daily_bar_adapter_version_mismatch"
        )


def _checked_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("cross_source_daily_bar_checked_at_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cross_source_daily_bar_checked_at_must_be_timezone_aware")
    return value.astimezone(timezone.utc)
