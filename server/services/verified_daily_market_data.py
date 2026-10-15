"""Publish verified daily partitions from a versioned source policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
from data.dataset.reader import read_daily_bar_dataset
from data.dataset.resolver import (
    DailyBarDatasetResolverPolicy,
    resolve_daily_bar_dataset,
)
from data.market.contracts import (
    MAX_DAILY_BAR_JOB_INSTRUMENTS,
    MAX_DAILY_BAR_RANGE_JOB_INSTRUMENTS,
    DailyBarRequest,
    MarketDataProviderDescriptor,
)
from data.market.cross_source import (
    CrossSourceDailyBarResult,
    CrossSourceDailyBarUnavailableError,
    ingest_cross_source_daily_bars,
    ingest_cross_source_daily_bars_range,
)
from data.market.quality import RESEARCH_STRICT_DAILY
from data.market.serving import MarketServingStore
from data.source_policy import resolve_market_source_policy
from data.source_routing import (
    provider_registry_for_config,
    resolve_daily_bar_verification_pairs,
)
from data.storage.objects import ContentAddressedObjectStore

VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION = "karkinos.market_daily_verified_job.v1"
VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION = "karkinos.market_daily_verified_job.v2"
VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT = "market.daily.source_resolution"
_NORMALIZER_VERSION = "karkinos.market.normalize.v1"
_RESOLVER_POLICY_PREFIX = "karkinos.dataset.pit.verified.daily.v1:"


class VerifiedDailyMarketDataError(RuntimeError):
    """Base failure for verified daily publication."""


class VerifiedDailyMarketDataRequestError(VerifiedDailyMarketDataError):
    """A durable job payload is not a valid market-data request."""


@dataclass(frozen=True, slots=True)
class VerifiedDailySourceResolution:
    """Operational trace of source selection; never part of Dataset identity."""

    source_policy_id: str
    outcome: str
    attempted_pairs: tuple[tuple[str, str], ...]
    unavailable_providers: tuple[str, ...] = ()
    selected_pair: tuple[str, str] | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": "karkinos.market_daily_source_resolution.v1",
            "source_policy_id": self.source_policy_id,
            "outcome": self.outcome,
            "attempted_pairs": [
                {"primary": primary, "comparison": comparison}
                for primary, comparison in self.attempted_pairs
            ],
            "unavailable_providers": list(self.unavailable_providers),
            "selected_pair": (
                None
                if self.selected_pair is None
                else {
                    "primary": self.selected_pair[0],
                    "comparison": self.selected_pair[1],
                }
            ),
        }


class VerifiedDailyMarketDataNotPublishable(VerifiedDailyMarketDataError):
    """Evidence was captured but does not authorize a verified dataset."""

    def __init__(
        self,
        code: str,
        *,
        source_resolution: VerifiedDailySourceResolution | None = None,
    ) -> None:
        self.source_resolution = source_resolution
        super().__init__(code)


class VerifiedDailyMarketDataUnavailable(VerifiedDailyMarketDataError):
    """Every eligible independent source pair was unavailable for this attempt."""

    def __init__(
        self,
        code: str,
        *,
        source_resolution: VerifiedDailySourceResolution | None = None,
    ) -> None:
        self.source_resolution = source_resolution
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class VerifiedDailyMarketPublication:
    dataset_ref: DatasetRef
    verification_id: str
    trade_date: date
    source_policy_id: str
    primary_provider: str
    comparison_provider: str
    source_resolution: VerifiedDailySourceResolution

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
    range_start_date: date | None = None
    range_end_date: date | None = None
    session_memberships: tuple[
        tuple[date, tuple[InstrumentKey, ...], tuple[str, ...]], ...
    ] = ()

    @property
    def is_range(self) -> bool:
        return self.range_start_date is not None

    def expected_sessions(self) -> tuple[date, ...]:
        return (
            tuple(item[0] for item in self.session_memberships)
            if self.is_range
            else (self.trade_date,)
        )

    def instruments_for_session(self, day: date) -> tuple[InstrumentKey, ...]:
        if not self.is_range:
            return self.instruments if day == self.trade_date else ()
        return next(
            (item[1] for item in self.session_memberships if item[0] == day), ()
        )

    def calendar_refs_for_session(self, day: date) -> tuple[str, ...]:
        if not self.is_range:
            return self.calendar_evidence_refs if day == self.trade_date else ()
        return next(
            (item[2] for item in self.session_memberships if item[0] == day), ()
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> VerifiedDailyMarketJobRequest:
        if not isinstance(payload, Mapping):
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_payload_invalid"
            )
        version = payload.get("schema_version")
        if version not in (
            VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION,
            VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION,
        ):
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
        maximum_instruments = (
            MAX_DAILY_BAR_RANGE_JOB_INSTRUMENTS
            if version == VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION
            else MAX_DAILY_BAR_JOB_INSTRUMENTS
        )
        if len(raw_instruments) > maximum_instruments:
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_job_batch_exceeded"
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

        range_fields: dict[str, Any] = {}
        if version == VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION:
            range_fields = _read_range_fields(
                payload, tuple(instruments), refs, trade_date
            )
        elif any(
            key in payload
            for key in ("range_start_date", "range_end_date", "session_memberships")
        ):
            raise VerifiedDailyMarketDataRequestError(
                "verified_daily_market_range_schema_required"
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
            **range_fields,
        )

    def to_payload(self) -> dict[str, Any]:
        payload = {
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
        if self.is_range:
            assert self.range_start_date is not None and self.range_end_date is not None
            payload.update(
                schema_version=VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION,
                range_start_date=self.range_start_date.isoformat(),
                range_end_date=self.range_end_date.isoformat(),
                session_memberships=[
                    {
                        "trade_date": day.isoformat(),
                        "instruments": [
                            {
                                "symbol": key.symbol,
                                "instrument_type": key.instrument_type.value,
                            }
                            for key in instruments
                        ],
                        "calendar_evidence_refs": list(refs),
                    }
                    for day, instruments, refs in self.session_memberships
                ],
            )
        return payload


def _read_range_fields(
    payload: Mapping[str, Any],
    instruments: tuple[InstrumentKey, ...],
    refs: tuple[str, ...],
    trade_date: date,
) -> dict[str, Any]:
    try:
        start = date.fromisoformat(payload["range_start_date"])
        end = date.fromisoformat(payload["range_end_date"])
        rows = payload["session_memberships"]
        if (
            not start <= end == trade_date
            or (end - start).days >= 3653
            or not isinstance(rows, list)
            or not 1 <= len(rows) <= 2000
        ):
            raise ValueError()
        memberships = []
        seen = set()
        observed: set[InstrumentKey] = set()
        for row in rows:
            day = date.fromisoformat(row["trade_date"])
            raw = row["instruments"]
            evidence = row["calendar_evidence_refs"]
            if (
                day in seen
                or not start <= day <= end
                or not isinstance(raw, list)
                or not isinstance(evidence, list)
                or not evidence
                or any(not isinstance(ref, str) or not ref.strip() for ref in evidence)
            ):
                raise ValueError()
            members = tuple(
                InstrumentKey(
                    str(item["symbol"]), InstrumentType(str(item["instrument_type"]))
                )
                for item in raw
            )
            if (
                len(set(members)) != len(members)
                or not set(members) <= set(instruments)
                or len(set(evidence)) != len(evidence)
                or not set(evidence) <= set(refs)
            ):
                raise ValueError()
            seen.add(day)
            observed.update(members)
            memberships.append(
                (
                    day,
                    tuple(sorted(members, key=lambda key: key.storage_tuple())),
                    tuple(evidence),
                )
            )
        memberships.sort(key=lambda item: item[0])
        if (
            memberships[0][0] != start
            or memberships[-1][0] != end
            or observed != set(instruments)
            or {ref for _, _, evidence in memberships for ref in evidence} != set(refs)
        ):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise VerifiedDailyMarketDataRequestError(
            "verified_daily_market_range_payload_invalid"
        ) from exc
    return {
        "range_start_date": start,
        "range_end_date": end,
        "session_memberships": tuple(memberships),
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
        before_provider_fetch: Callable[[MarketDataProviderDescriptor], None]
        | None = None,
        publication_guard: Callable[[Callable[[], None]], None] | None = None,
    ) -> VerifiedDailyMarketPublication:
        request = VerifiedDailyMarketJobRequest.from_payload(payload)
        checked_at = _utc_now(checked_at) if checked_at is not None else None
        if request.is_range:
            return self._run_range(
                request,
                checked_at=checked_at,
                before_publish=before_publish,
                before_provider_fetch=before_provider_fetch,
                publication_guard=publication_guard,
            )

        daily_request = DailyBarRequest(
            request.instruments,
            request.trade_date,
            request.trade_date,
        )
        policy = resolve_market_source_policy(request.source_policy_id)
        registry = provider_registry_for_config(self._config, include_tdx=False)
        pairs = resolve_daily_bar_verification_pairs(
            policy,
            registry,
            daily_request,
        )

        store = ContentAddressedObjectStore(self.root / "objects")
        evidence: CrossSourceDailyBarResult | None = None
        selected_pair = None
        unavailable_providers: set[str] = set()
        attempted_pairs: list[tuple[str, str]] = []
        for pair in pairs:
            if {
                pair.primary_name,
                pair.comparison_name,
            } & unavailable_providers:
                continue
            attempted_pairs.append((pair.primary_name, pair.comparison_name))
            try:
                candidate_evidence = ingest_cross_source_daily_bars(
                    pair.primary,
                    pair.comparison,
                    store,
                    request=daily_request,
                    quality_policy=RESEARCH_STRICT_DAILY,
                    normalizer_version=_NORMALIZER_VERSION,
                    reconciliation_policy=pair.reconciliation_policy,
                    checked_at=checked_at,
                    before_fetch=before_provider_fetch,
                )
            except CrossSourceDailyBarUnavailableError as exc:
                unavailable_providers.add(exc.provider)
                continue

            if not candidate_evidence.eligible_for_verified_dataset:
                outcome = (
                    "quality_blocked"
                    if candidate_evidence.verification is None
                    else "conflict"
                )
                raise VerifiedDailyMarketDataNotPublishable(
                    _not_publishable_code(candidate_evidence),
                    source_resolution=VerifiedDailySourceResolution(
                        source_policy_id=policy.policy_id,
                        outcome=outcome,
                        attempted_pairs=tuple(attempted_pairs),
                        unavailable_providers=tuple(sorted(unavailable_providers)),
                        selected_pair=(pair.primary_name, pair.comparison_name),
                    ),
                )
            evidence = candidate_evidence
            selected_pair = pair
            break

        if evidence is None or selected_pair is None:
            unavailable = ",".join(sorted(unavailable_providers)) or "unknown"
            raise VerifiedDailyMarketDataUnavailable(
                f"verified_daily_market_sources_unavailable:{unavailable}",
                source_resolution=VerifiedDailySourceResolution(
                    source_policy_id=policy.policy_id,
                    outcome="unavailable",
                    attempted_pairs=tuple(attempted_pairs),
                    unavailable_providers=tuple(sorted(unavailable_providers)),
                ),
            )
        assert evidence.verification is not None
        pair = selected_pair
        verified_at = evidence.verification.checked_at

        candidates = evidence.resolution_candidates()
        resolver_policy = DailyBarDatasetResolverPolicy(
            policy_id=verified_daily_resolver_policy_id(policy.policy_id),
            provider_priority=(pair.primary_name, pair.comparison_name),
            required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
        )
        cutoff = max(
            evidence.primary.capture.completed_at,
            evidence.comparison.capture.completed_at,
            verified_at,
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

        def publish() -> None:
            DatasetCatalog(self.root).register(
                store, dataset_ref, registered_at=verified_at
            )
            selected = _selected_candidate(evidence, snapshot.partitions[0].provider)
            MarketServingStore(self.root).apply_daily_bar_revision(
                store,
                revision=selected.revision,
                materialization=selected.materialization,
            )

        if publication_guard is None:
            publish()
        else:
            publication_guard(publish)

        return VerifiedDailyMarketPublication(
            dataset_ref=dataset_ref,
            verification_id=evidence.verification.verification_id,
            trade_date=request.trade_date,
            source_policy_id=policy.policy_id,
            primary_provider=pair.primary_name,
            comparison_provider=pair.comparison_name,
            source_resolution=VerifiedDailySourceResolution(
                source_policy_id=policy.policy_id,
                outcome="matched",
                attempted_pairs=tuple(attempted_pairs),
                unavailable_providers=tuple(sorted(unavailable_providers)),
                selected_pair=(pair.primary_name, pair.comparison_name),
            ),
        )

    def _run_range(
        self,
        request: VerifiedDailyMarketJobRequest,
        *,
        checked_at: datetime | None,
        before_publish: Callable[[], None] | None,
        before_provider_fetch: Callable[[MarketDataProviderDescriptor], None] | None,
        publication_guard: Callable[[Callable[[], None]], None] | None,
    ) -> VerifiedDailyMarketPublication:
        """Capture a historical range once per source; retain daily verification.

        Memberships are an explicit transport projection, with no historical
        availability claim. Each materialization retains the real range capture.
        """
        assert (
            request.range_start_date is not None and request.range_end_date is not None
        )
        daily_request = DailyBarRequest(
            request.instruments, request.range_start_date, request.range_end_date
        )
        expected = {
            day: members for day, members, _ in request.session_memberships if members
        }
        policy = resolve_market_source_policy(request.source_policy_id)
        pairs = resolve_daily_bar_verification_pairs(
            policy,
            provider_registry_for_config(self._config, include_tdx=False),
            daily_request,
        )
        store = ContentAddressedObjectStore(self.root / "objects")
        unavailable: set[str] = set()
        attempted: list[tuple[str, str]] = []
        evidence_rows: tuple[CrossSourceDailyBarResult, ...] = ()
        selected_pair = None
        for pair in pairs:
            if {pair.primary_name, pair.comparison_name} & unavailable:
                continue
            attempted.append((pair.primary_name, pair.comparison_name))
            try:
                rows = ingest_cross_source_daily_bars_range(
                    pair.primary,
                    pair.comparison,
                    store,
                    request=daily_request,
                    expected_sessions=expected,
                    quality_policy=RESEARCH_STRICT_DAILY,
                    normalizer_version=_NORMALIZER_VERSION,
                    reconciliation_policy=pair.reconciliation_policy,
                    checked_at=checked_at,
                    before_fetch=before_provider_fetch,
                )
            except CrossSourceDailyBarUnavailableError as exc:
                unavailable.add(exc.provider)
                continue
            for row in rows:
                if not row.eligible_for_verified_dataset:
                    raise VerifiedDailyMarketDataNotPublishable(
                        _not_publishable_code(row),
                        source_resolution=VerifiedDailySourceResolution(
                            policy.policy_id,
                            "quality_blocked"
                            if row.verification is None
                            else "conflict",
                            tuple(attempted),
                            tuple(sorted(unavailable)),
                            (pair.primary_name, pair.comparison_name),
                        ),
                    )
            evidence_rows, selected_pair = rows, pair
            break
        if not evidence_rows or selected_pair is None:
            raise VerifiedDailyMarketDataUnavailable(
                "verified_daily_market_sources_unavailable:"
                + (",".join(sorted(unavailable)) or "unknown"),
                source_resolution=VerifiedDailySourceResolution(
                    policy.policy_id,
                    "unavailable",
                    tuple(attempted),
                    tuple(sorted(unavailable)),
                ),
            )
        if len(evidence_rows) != len(expected):
            raise VerifiedDailyMarketDataError(
                "verified_daily_market_range_coverage_mismatch"
            )
        pair = selected_pair
        resolver_policy = DailyBarDatasetResolverPolicy(
            policy_id=verified_daily_resolver_policy_id(policy.policy_id),
            provider_priority=(pair.primary_name, pair.comparison_name),
            required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
        )
        snapshots = []
        for (day, members), evidence in zip(
            expected.items(), evidence_rows, strict=True
        ):
            assert evidence.verification is not None
            cutoff = max(
                evidence.primary.capture.completed_at,
                evidence.comparison.capture.completed_at,
                evidence.verification.checked_at,
            )
            snapshot = resolve_daily_bar_dataset(
                store,
                candidates=evidence.resolution_candidates(),
                start_date=day,
                end_date=day,
                cutoff=cutoff,
                instruments=members,
                expected_partition_dates=(day,),
                policy=resolver_policy,
            )
            if not snapshot.verification_bound:
                raise VerifiedDailyMarketDataNotPublishable(
                    "verified_daily_market_dataset_not_verification_bound"
                )
            snapshots.append(snapshot)
        snapshot = DailyBarDatasetSnapshot(
            start_date=snapshots[0].start_date,
            end_date=snapshots[-1].end_date,
            cutoff=max(item.cutoff for item in snapshots),
            instruments=request.instruments,
            resolver_policy_id=resolver_policy.policy_id,
            market_schema_version=snapshots[0].market_schema_version,
            partitions=tuple(
                replace(item.partitions[0], instruments=item.instruments)
                for item in snapshots
            ),
            session_memberships=tuple(
                DailyBarDatasetMembership(
                    item.start_date, item.instruments, item.cutoff
                )
                for item in snapshots
            ),
            universe_policy_id="karkinos.dataset.verified_range_projection.v1",
        )
        ref = publish_daily_bar_dataset_manifest(store, snapshot)
        if read_daily_bar_dataset(store, ref).snapshot != snapshot:
            raise VerifiedDailyMarketDataError(
                "verified_daily_market_dataset_replay_mismatch"
            )
        if before_publish is not None:
            before_publish()

        def publish() -> None:
            DatasetCatalog(self.root).register(
                store, ref, registered_at=snapshot.cutoff
            )
            serving = MarketServingStore(self.root)
            for daily, evidence in zip(snapshots, evidence_rows, strict=True):
                selected = _selected_candidate(evidence, daily.partitions[0].provider)
                serving.apply_daily_bar_revision(
                    store,
                    revision=selected.revision,
                    materialization=selected.materialization,
                )

        if publication_guard is None:
            publish()
        else:
            publication_guard(publish)
        assert evidence_rows[-1].verification is not None
        return VerifiedDailyMarketPublication(
            dataset_ref=ref,
            verification_id=evidence_rows[-1].verification.verification_id,
            trade_date=request.trade_date,
            source_policy_id=policy.policy_id,
            primary_provider=pair.primary_name,
            comparison_provider=pair.comparison_name,
            source_resolution=VerifiedDailySourceResolution(
                policy.policy_id,
                "matched",
                tuple(attempted),
                tuple(sorted(unavailable)),
                (pair.primary_name, pair.comparison_name),
            ),
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


def verified_daily_resolver_policy_id(source_policy_id: str) -> str:
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
    "VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION",
    "VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT",
    "VerifiedDailyMarketDataError",
    "VerifiedDailyMarketDataNotPublishable",
    "VerifiedDailyMarketDataRequestError",
    "VerifiedDailyMarketDataUnavailable",
    "VerifiedDailyMarketDataService",
    "VerifiedDailyMarketJobRequest",
    "VerifiedDailyMarketPublication",
    "VerifiedDailySourceResolution",
    "is_verified_daily_resolver_policy",
    "verified_daily_resolver_policy_id",
]
