"""Cross-source daily-bar ingestion and immutable verification orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone

from core.types import InstrumentKey
from data.dataset.resolver import DailyBarResolutionCandidate
from data.market.contracts import (
    DailyBarProvider,
    DailyBarProviderUnavailableError,
    DailyBarRequest,
    MarketDataProviderDescriptor,
)
from data.market.ingestion import (
    DailyBarIngestionNoData,
    DailyBarIngestionResult,
    ingest_daily_bars,
    ingest_daily_bars_range,
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
    before_fetch: Callable[[MarketDataProviderDescriptor], None] | None = None,
    ingestion_cache: dict[tuple[object, ...], DailyBarIngestionResult] | None = None,
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

    # Without an explicit replay clock, each source is quality-checked after
    # its own capture. Cross-source verification is dated only after both
    # provider calls have completed.
    quality_checked_at = _checked_at(checked_at) if checked_at is not None else None

    primary = _ingest_provider(
        primary_provider,
        store,
        request=request,
        quality_policy=quality_policy,
        normalizer_version=normalizer_version,
        checked_at=quality_checked_at,
        before_fetch=before_fetch,
        ingestion_cache=ingestion_cache,
    )
    _validate_ingestion_identity(primary, primary_descriptor)
    primary_quality = publish_market_quality_evidence(store, primary.quality)

    comparison = _ingest_provider(
        comparison_provider,
        store,
        request=request,
        quality_policy=quality_policy,
        normalizer_version=normalizer_version,
        checked_at=quality_checked_at,
        before_fetch=before_fetch,
        ingestion_cache=ingestion_cache,
    )
    _validate_ingestion_identity(comparison, comparison_descriptor)
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
    verification_checked_at = _checked_at(checked_at)
    if verification_checked_at < max(
        primary.capture.completed_at, comparison.capture.completed_at
    ):
        raise ValueError("cross_source_daily_bar_checked_at_before_capture")
    verification = publish_market_verification_evidence(
        store,
        report=report,
        primary_quality=primary_quality,
        comparison_quality=comparison_quality,
        primary_descriptor=primary_descriptor,
        comparison_descriptor=comparison_descriptor,
        policy=reconciliation_policy,
        checked_at=verification_checked_at,
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
    checked_at: datetime | None,
    before_fetch: Callable[[MarketDataProviderDescriptor], None] | None,
    ingestion_cache: dict[tuple[object, ...], DailyBarIngestionResult] | None,
) -> DailyBarIngestionResult:
    key = (
        store.root,
        provider.descriptor,
        request,
        quality_policy,
        normalizer_version,
        checked_at,
    )
    if ingestion_cache is not None and key in ingestion_cache:
        result = ingestion_cache[key]
        _validate_ingestion_identity(result, provider.descriptor)
        return result
    try:
        result = ingest_daily_bars(
            provider,
            store,
            request=request,
            quality_policy=quality_policy,
            normalizer_version=normalizer_version,
            checked_at=checked_at,
            before_fetch=before_fetch,
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
    _validate_ingestion_identity(result, provider.descriptor)
    if ingestion_cache is not None:
        ingestion_cache[key] = result
    return result


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


def ingest_cross_source_daily_bars_range(
    primary_provider: DailyBarProvider,
    comparison_provider: DailyBarProvider,
    store: ContentAddressedObjectStore,
    *,
    request: DailyBarRequest,
    expected_sessions: Mapping[date, tuple[InstrumentKey, ...]],
    quality_policy: DailyBarQualityPolicy,
    normalizer_version: str,
    reconciliation_policy: DailyBarReconciliationPolicy = STRICT_DAILY_RECONCILIATION,
    checked_at: datetime | None = None,
    before_fetch: Callable[[MarketDataProviderDescriptor], None] | None = None,
    ingestion_cache: dict[tuple[object, ...], tuple[DailyBarIngestionResult, ...]]
    | None = None,
) -> tuple[CrossSourceDailyBarResult, ...]:
    """One real range capture per independent source, existing verification/day.

    Expected members are explicit per-date projections, never a returned-source
    intersection. Extras within the original request remain captured and are
    outside the projection; missing expected members retain strict quality gates.
    """
    if not isinstance(quality_policy, DailyBarQualityPolicy) or not isinstance(
        reconciliation_policy, DailyBarReconciliationPolicy
    ):
        raise TypeError("cross_source_daily_bar_range_policy_invalid")
    _validate_provider_roles(
        request,
        primary_descriptor=primary_provider.descriptor,
        comparison_descriptor=comparison_provider.descriptor,
    )
    quality_checked_at = _checked_at(checked_at) if checked_at is not None else None
    sources = []
    for provider in (primary_provider, comparison_provider):
        key = (
            store.root,
            provider.descriptor,
            request,
            quality_policy,
            normalizer_version,
            quality_checked_at,
            tuple(sorted(expected_sessions.items())),
        )
        try:
            if ingestion_cache is not None and key in ingestion_cache:
                source = ingestion_cache[key]
            else:
                source = ingest_daily_bars_range(
                    provider,
                    store,
                    request=request,
                    expected_sessions=expected_sessions,
                    quality_policy=quality_policy,
                    normalizer_version=normalizer_version,
                    checked_at=quality_checked_at,
                    before_fetch=before_fetch,
                )
        except DailyBarIngestionNoData as exc:
            raise CrossSourceDailyBarUnavailableError(
                provider.descriptor.provider, "no_data"
            ) from exc
        except DailyBarProviderUnavailableError as exc:
            raise CrossSourceDailyBarUnavailableError(
                provider.descriptor.provider, "provider_unavailable"
            ) from exc
        for item in source:
            _validate_ingestion_identity(item, provider.descriptor)
        if ingestion_cache is not None:
            ingestion_cache[key] = source
        sources.append(source)
    results = []
    for primary, comparison in zip(*sources, strict=True):
        if primary.revision.partition_date != comparison.revision.partition_date:
            raise CrossSourceDailyBarIntegrityError(
                "cross_source_daily_bar_range_partition_mismatch"
            )
        primary_quality = publish_market_quality_evidence(store, primary.quality)
        comparison_quality = publish_market_quality_evidence(store, comparison.quality)
        verification = None
        if (
            primary.quality.status is MarketQualityStatus.PASS
            and comparison.quality.status is MarketQualityStatus.PASS
        ):
            report = reconcile_daily_bar_revisions(
                store,
                primary_revision=primary.revision,
                primary_materialization=primary.materialization,
                comparison_revision=comparison.revision,
                comparison_materialization=comparison.materialization,
                policy=reconciliation_policy,
            )
            verification_checked_at = _checked_at(checked_at)
            if verification_checked_at < max(
                primary.capture.completed_at, comparison.capture.completed_at
            ):
                raise ValueError("cross_source_daily_bar_checked_at_before_capture")
            verification = publish_market_verification_evidence(
                store,
                report=report,
                primary_quality=primary_quality,
                comparison_quality=comparison_quality,
                primary_descriptor=primary_provider.descriptor,
                comparison_descriptor=comparison_provider.descriptor,
                policy=reconciliation_policy,
                checked_at=verification_checked_at,
            )
        results.append(
            CrossSourceDailyBarResult(
                primary, comparison, primary_quality, comparison_quality, verification
            )
        )
    return tuple(results)


def reverify_captured_daily_bar_evidence(
    store: ContentAddressedObjectStore,
    *,
    verification_ids: tuple[str, ...],
    request: DailyBarRequest,
    expected_sessions: Mapping[date, tuple[InstrumentKey, ...]],
    primary_descriptor: MarketDataProviderDescriptor,
    comparison_descriptor: MarketDataProviderDescriptor,
    reconciliation_policy: DailyBarReconciliationPolicy,
    checked_at: datetime,
) -> tuple[CrossSourceDailyBarResult, ...]:
    """Reprocess actual immutable captures without claiming a fresh fetch.

    Original source bytes, capture identities and availability times stay exact.
    Only the newly evaluated verification has today's decision time/policy.
    """
    import json
    from dataclasses import replace

    from data.market.capture import read_provider_capture
    from data.market.quality import RESEARCH_STRICT_DAILY
    from data.market.quality_evidence import read_market_quality_evidence
    from data.market.reconciliation import (
        reconcile_daily_bar_revisions_with_bars,
        reconcile_daily_bars,
    )
    from data.market.revision import (
        read_market_revision,
        read_market_revision_materialization,
    )
    from data.market.verification_evidence import read_market_verification_evidence

    _validate_provider_roles(
        request,
        primary_descriptor=primary_descriptor,
        comparison_descriptor=comparison_descriptor,
    )
    now = _checked_at(checked_at)
    if not verification_ids or len(set(verification_ids)) != len(verification_ids):
        raise ValueError("captured_reverification_evidence_invalid")
    results = {}
    for identity in verification_ids:
        original = read_market_verification_evidence(store, store.resolve_ref(identity))
        if original.policy != STRICT_DAILY_RECONCILIATION or original.checked_at > now:
            raise ValueError("captured_reverification_original_policy_or_time_invalid")
        sides, qualities, descriptors = [], [], []
        for prefix, descriptor in (
            ("primary", primary_descriptor),
            ("comparison", comparison_descriptor),
        ):
            quality = read_market_quality_evidence(
                store, store.resolve_ref(getattr(original, prefix + "_quality_id"))
            )
            materialization = read_market_revision_materialization(
                store,
                store.resolve_ref(getattr(original, prefix + "_materialization_id")),
            )
            revision = read_market_revision(store, materialization.revision_ref)
            capture = read_provider_capture(store, materialization.capture_ref)
            adapter = getattr(original, prefix + "_adapter_version")
            reviewed = {
                "baostock": {
                    "karkinos.baostock.daily_bar.v1",
                    "karkinos.baostock.daily_bar.v2",
                },
                "tushare": {
                    "karkinos.tushare.daily_bar.v1",
                    "karkinos.tushare.daily_bar.v2",
                },
            }
            if (
                capture.provider != descriptor.provider
                or adapter not in reviewed.get(descriptor.provider, set())
                or getattr(original, prefix + "_upstream_group")
                != descriptor.upstream_group
                or capture.adapter_version != adapter
                or capture.completed_at > now
                or json.loads(capture.request_json) != request.to_capture_request()
                or quality.report.status is not MarketQualityStatus.PASS
                or quality.report.policy_id != RESEARCH_STRICT_DAILY.policy_id
                or quality.report.revision_id != revision.ref.revision_id
                or quality.report.materialization_id
                != materialization.materialization_id
            ):
                raise ValueError("captured_reverification_source_mismatch")
            sides.append(
                DailyBarIngestionResult(
                    capture, revision, materialization, quality.report
                )
            )
            qualities.append(quality)
            descriptors.append(replace(descriptor, adapter_version=adapter))
        primary, comparison = sides
        report, primary_bars, comparison_bars = reconcile_daily_bar_revisions_with_bars(
            store,
            primary_revision=primary.revision,
            primary_materialization=primary.materialization,
            comparison_revision=comparison.revision,
            comparison_materialization=comparison.materialization,
            policy=reconciliation_policy,
        )
        replayed_original = reconcile_daily_bars(
            primary_bars,
            comparison_bars,
            primary_revision_id=primary.revision.ref.revision_id,
            comparison_revision_id=comparison.revision.ref.revision_id,
            primary_provider=primary.revision.provider,
            comparison_provider=comparison.revision.provider,
            policy=original.policy,
        )
        day = primary.revision.partition_date
        if (
            replayed_original != original.report
            or day in results
            or day not in expected_sessions
            or {bar.instrument for bar in primary_bars} != set(expected_sessions[day])
            or {bar.instrument for bar in comparison_bars}
            != set(expected_sessions[day])
        ):
            raise ValueError("captured_reverification_partition_mismatch")
        verification = publish_market_verification_evidence(
            store,
            report=report,
            primary_quality=qualities[0],
            comparison_quality=qualities[1],
            primary_descriptor=descriptors[0],
            comparison_descriptor=descriptors[1],
            policy=reconciliation_policy,
            checked_at=now,
        )
        results[day] = CrossSourceDailyBarResult(
            primary, comparison, qualities[0], qualities[1], verification
        )
    if set(results) != set(expected_sessions):
        raise ValueError("captured_reverification_session_coverage_mismatch")
    return tuple(results[day] for day in sorted(results))
