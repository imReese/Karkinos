"""Read-only exchange candidates over exact historical targets and source bytes."""

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from core.types import InstrumentKey
from server.persistence.database_normalization import stable_json_fingerprint
from server.projections.portfolio_read_snapshot import (
    PortfolioReadSnapshot,
    PortfolioReadSnapshotIdentity,
)
from server.projections.portfolio_views.historical_coverage import (
    HistoricalCoverageEvidence,
    build_historical_coverage,
)


class InstrumentExchangeEvidenceRejected(ValueError):
    """The expected coverage or metadata input no longer matches."""


@dataclass(frozen=True)
class InstrumentExchangeTarget:
    instrument_key: InstrumentKey
    valuation_dates: tuple[str, ...]
    current_exchanges: tuple[str | None, ...]
    metadata_content_fingerprint: str


@dataclass(frozen=True)
class InstrumentExchangeTargets:
    identity: PortfolioReadSnapshotIdentity
    evaluated_at: datetime
    coverage_evidence_fingerprint: str
    metadata_content_fingerprint: str
    targets: tuple[InstrumentExchangeTarget, ...]


@dataclass(frozen=True)
class ExchangeSourceReference:
    content_ref: str
    source_locator: str
    content_sha256: str
    record_locators: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExchangeSourceRecord:
    source: ExchangeSourceReference
    record_locator: str
    record_id: str
    instrument_key: InstrumentKey
    exchange: str
    valid_from: str
    valid_to: str


@dataclass(frozen=True)
class ExchangeSourceReview:
    source: ExchangeSourceReference
    records: tuple[ExchangeSourceRecord, ...]
    content_blockers: tuple[str, ...]
    authenticity_status: str = field(default="unverified", init=False)


@dataclass(frozen=True)
class InstrumentExchangePreviewItem:
    target: InstrumentExchangeTarget
    candidate_exchange: str | None
    record_matched_dates: tuple[str, ...]
    record_unmatched_dates: tuple[str, ...]
    source_records: tuple[ExchangeSourceRecord, ...]
    blockers: tuple[str, ...]
    status: str = field(default="blocked", init=False)
    support_scope: str = field(default="record_content_only", init=False)
    human_verification_status: str = field(default="not_performed", init=False)
    verified_supported_dates: tuple[str, ...] = field(default=(), init=False)


@dataclass(frozen=True)
class InstrumentExchangePreview:
    expected_targets: InstrumentExchangeTargets
    items: tuple[InstrumentExchangePreviewItem, ...]
    source_blockers: tuple[str, ...]
    source_reviews: tuple[ExchangeSourceReview, ...]
    rule_version: str = field(default="instrument-exchange-preview-v1", init=False)
    database_writes_performed: bool = field(default=False, init=False)
    provider_contacted: bool = field(default=False, init=False)
    authorizes_metadata_publication: bool = field(default=False, init=False)


def build_instrument_exchange_targets(
    snapshot: PortfolioReadSnapshot, evidence: HistoricalCoverageEvidence
) -> InstrumentExchangeTargets:
    """Select dates from the canonical coverage result, never from a watchlist."""
    report = build_historical_coverage(snapshot, evidence)
    dates = defaultdict(set)
    for item in report.items:
        if (
            item.requirement_reason == "instrument_exchange_unavailable"
            and item.instrument_type in {"stock", "etf"}
        ):
            dates[InstrumentKey.from_values(item.symbol, item.instrument_type)].add(
                item.valuation_date
            )
    targets = []
    for key in sorted(dates, key=lambda key: key.storage_tuple()):
        metadata = [
            row
            for row in evidence.metadata
            if InstrumentKey.from_values(row["symbol"], row["asset_type"]) == key
        ]
        exchanges = {
            str(row["exchange"]) if row.get("exchange") else None for row in metadata
        }
        targets.append(
            InstrumentExchangeTarget(
                key,
                tuple(sorted(dates[key])),
                tuple(sorted(exchanges, key=lambda value: value or "")),
                stable_json_fingerprint(metadata),
            )
        )
    return InstrumentExchangeTargets(
        snapshot.identity,
        datetime.fromisoformat(report.evaluated_at),
        report.evidence_fingerprint,
        stable_json_fingerprint(evidence.metadata),
        tuple(targets),
    )


def preview_instrument_exchange_evidence(
    expected_targets: InstrumentExchangeTargets,
    *,
    current_targets: InstrumentExchangeTargets,
    sources: tuple[ExchangeSourceReference, ...],
    source_contents: Mapping[str, bytes],
) -> InstrumentExchangePreview:
    """Compare source records; content matching never establishes authenticity."""
    if current_targets != expected_targets:
        raise InstrumentExchangeEvidenceRejected("coverage or metadata inputs changed")
    if len({source.content_ref for source in sources}) != len(sources):
        raise InstrumentExchangeEvidenceRejected("duplicate source content reference")
    records, source_blockers, source_reviews = [], set(), []
    for source in sorted(
        sources, key=lambda source: (source.source_locator, source.content_ref)
    ):
        parsed, blockers = _source_records(source, source_contents)
        records.extend(parsed)
        source_blockers.update(blockers)
        source_reviews.append(ExchangeSourceReview(source, parsed, blockers))
    items = []
    for target in expected_targets.targets:
        observed = tuple(
            record
            for record in records
            if record.instrument_key == target.instrument_key
        )
        matched = tuple(
            record
            for record in observed
            if not record.source.record_locators
            or record.record_locator in record.source.record_locators
        )
        blockers = {
            *source_blockers,
            "source_authenticity_unverified",
            "historical_applicability_unverified",
            "human_review_required",
        }
        if not matched:
            blockers.add("typed_source_record_missing")
        supported, unsupported, exchanges = [], [], set()
        for day in target.valuation_dates:
            observed_exchanges = {
                record.exchange
                for record in observed
                if record.valid_from <= day <= record.valid_to
            }
            if len(observed_exchanges) > 1:
                unsupported.append(day)
                blockers.add("source_record_conflict")
                continue
            candidates = {
                record.exchange
                for record in matched
                if record.valid_from <= day <= record.valid_to
            }
            if len(candidates) == 1:
                supported.append(day)
                exchanges.update(candidates)
            else:
                unsupported.append(day)
                if len(candidates) > 1:
                    blockers.add("source_record_conflict")
        if unsupported:
            blockers.add("source_date_coverage_incomplete")
        if len(exchanges) > 1:
            blockers.add("candidate_exchange_varies_by_date")
        items.append(
            InstrumentExchangePreviewItem(
                target,
                next(iter(exchanges)) if len(exchanges) == 1 else None,
                tuple(supported),
                tuple(unsupported),
                observed,
                tuple(sorted(blockers)),
            )
        )
    return InstrumentExchangePreview(
        expected_targets,
        tuple(items),
        tuple(sorted(source_blockers)),
        tuple(source_reviews),
    )


def _source_records(
    source: ExchangeSourceReference, contents: Mapping[str, bytes]
) -> tuple[tuple[ExchangeSourceRecord, ...], tuple[str, ...]]:
    if (
        any(
            not isinstance(value, str) or not value.strip()
            for value in (
                source.content_ref,
                source.source_locator,
                source.content_sha256,
            )
        )
        or len(source.content_sha256) != 64
    ):
        return (), ("source_reference_invalid",)
    content = contents.get(source.content_ref)
    if not isinstance(content, bytes):
        return (), ("source_content_unavailable",)
    if hashlib.sha256(content).hexdigest() != source.content_sha256:
        return (), ("source_content_digest_mismatch",)
    try:
        payload = json.loads(content)
        if (
            set(payload) != {"schema_version", "records"}
            or payload["schema_version"] != "karkinos.instrument-exchange-source.v1"
            or not isinstance(payload["records"], list)
        ):
            raise ValueError("invalid source envelope")
        records, identifiers = [], set()
        for index, row in enumerate(payload["records"]):
            if set(row) != {
                "record_id",
                "symbol",
                "instrument_type",
                "exchange",
                "valid_from",
                "valid_to",
            }:
                raise ValueError("invalid source record")
            if any(
                not isinstance(value, str) or not value.strip()
                for value in row.values()
            ):
                raise ValueError("invalid source record value")
            if row["record_id"] in identifiers:
                raise ValueError("invalid record identity")
            if row["instrument_type"] not in {"stock", "etf"} or row[
                "exchange"
            ] not in {"SSE", "SZSE", "BSE"}:
                raise ValueError("unsupported source identity")
            first, last = date.fromisoformat(row["valid_from"]), date.fromisoformat(
                row["valid_to"]
            )
            if first > last:
                raise ValueError("invalid source interval")
            identifiers.add(row["record_id"])
            records.append(
                ExchangeSourceRecord(
                    source,
                    f"/records/{index}",
                    row["record_id"],
                    InstrumentKey.from_values(row["symbol"], row["instrument_type"]),
                    row["exchange"],
                    first.isoformat(),
                    last.isoformat(),
                )
            )
        if source.record_locators:
            wanted = set(source.record_locators)
            if len(wanted) != len(source.record_locators) or not wanted.issubset(
                {record.record_locator for record in records}
            ):
                return tuple(records), ("source_record_locator_unavailable",)
        return tuple(records), ()
    except (TypeError, ValueError, KeyError, UnicodeDecodeError):
        return (), ("source_schema_invalid",)
