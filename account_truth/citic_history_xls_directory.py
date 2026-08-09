"""Explicit, privacy-minimized scans of a configured CITIC export directory.

The directory is a user-owned local evidence source. Scans are explicit and
read-only: they parse stable direct-child ``.xls`` files in memory, suppress
local names and paths, and never persist broker events or account facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_history_xls import (
    parse_citic_history_xls,
    recognized_non_financial_activity_count,
)
from account_truth.citic_source_intake import (
    citic_preview_is_recordable_for_follow_up,
    citic_source_preview_fingerprint,
)

CITIC_HISTORY_XLS_DIRECTORY_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_history_xls_directory.v1"
)
CITIC_HISTORY_XLS_BATCH_ASSESSMENT_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_history_xls_batch_assessment.v1"
)
_LOCAL_NAME_MONTH_TOKEN = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)")

CiticHistoryXlsDirectoryState = Literal[
    "disabled",
    "empty",
    "ready",
    "partial",
    "blocked",
]
CiticHistoryXlsBatchIntegrityStatus = Literal[
    "not_available",
    "clear",
    "blocked",
]


class CiticHistoryXlsDirectoryRejected(ValueError):
    """Fail-closed rejection without exposing a private local path or name."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CiticHistoryXlsBatchAssessment:
    """Privacy-minimized integrity facts for one in-memory preview set."""

    schema_version: str
    status: Literal["blocked"]
    integrity_status: CiticHistoryXlsBatchIntegrityStatus
    source_count: int
    structurally_recordable_source_count: int
    source_with_financial_events_count: int
    source_without_financial_events_count: int
    observed_event_count: int
    unique_event_count: int
    within_file_duplicate_row_count: int
    cross_file_duplicate_event_count: int
    conflicting_event_identity_count: int
    invalid_row_count: int
    invalid_event_time_count: int
    recognized_non_financial_activity_count: int
    observed_event_months: tuple[str, ...]
    observed_event_month_counts: tuple[tuple[str, int], ...]
    batch_fingerprint: str
    blockers: tuple[str, ...]
    required_evidence: tuple[str, ...]
    limitations: tuple[str, ...]
    query_windows_reviewed: bool = False
    complete_coverage_proven: bool = False
    settlement_components_complete: bool = False
    current_account_snapshots_present: bool = False
    account_scope_bound: bool = False
    events_included: bool = False
    private_fields_included: bool = False
    source_names_included: bool = False
    paths_included: bool = False
    evidence_persisted: bool = False
    eligible_for_account_truth: bool = False
    eligible_for_reconciliation: bool = False
    does_not_mutate_production_ledger: bool = True
    does_not_contact_provider: bool = True
    does_not_enable_broker_submission: bool = True
    does_not_change_capital_authority: bool = True


@dataclass(frozen=True)
class CiticHistoryXlsDirectoryScan:
    schema_version: str
    enabled: bool
    state: CiticHistoryXlsDirectoryState
    candidate_file_count: int
    preview_count: int
    duplicate_file_count: int
    unreadable_file_count: int
    recognized_event_count: int
    valid_row_count: int
    invalid_row_count: int
    scan_fingerprint: str
    error_codes: tuple[str, ...]
    previews: tuple[BrokerStatementPreview, ...]
    batch_assessment: CiticHistoryXlsBatchAssessment
    local_name_month_hints: tuple[tuple[str, str], ...]
    configured_path_included: bool = False
    source_names_included: bool = False
    scan_persisted: bool = False
    events_persisted: bool = False
    eligible_for_account_truth: bool = False
    eligible_for_reconciliation: bool = False
    does_not_mutate_production_ledger: bool = True
    does_not_contact_provider: bool = True
    does_not_enable_broker_submission: bool = True
    does_not_change_capital_authority: bool = True


def build_citic_history_xls_batch_assessment(
    previews: tuple[BrokerStatementPreview, ...],
) -> CiticHistoryXlsBatchAssessment:
    """Assess cross-file integrity without exposing or persisting row facts."""

    row_fingerprint_sources: dict[str, set[int]] = defaultdict(set)
    event_id_row_fingerprints: dict[str, set[str]] = defaultdict(set)
    observed_month_counts: dict[str, int] = defaultdict(int)
    invalid_event_time_count = 0
    for source_index, preview in enumerate(previews):
        for event in preview.events:
            row_fingerprint_sources[event.row_fingerprint].add(source_index)
            event_id_row_fingerprints[event.event_id].add(event.row_fingerprint)
            month = _event_month(event.occurred_at)
            if month is None:
                invalid_event_time_count += 1
            else:
                observed_month_counts[month] += 1

    observed_event_count = sum(len(preview.events) for preview in previews)
    within_file_duplicate_row_count = sum(
        preview.duplicate_row_count for preview in previews
    )
    cross_file_duplicate_event_count = sum(
        max(0, len(source_indexes) - 1)
        for source_indexes in row_fingerprint_sources.values()
    )
    conflicting_event_identity_count = sum(
        len(row_fingerprints) > 1
        for row_fingerprints in event_id_row_fingerprints.values()
    )
    structurally_recordable_source_count = sum(
        citic_preview_is_recordable_for_follow_up(preview) for preview in previews
    )
    invalid_row_count = sum(preview.invalid_row_count for preview in previews)
    source_with_financial_events_count = sum(
        bool(preview.events) for preview in previews
    )
    non_financial_activity_count = sum(
        recognized_non_financial_activity_count(preview) for preview in previews
    )

    integrity_blockers: list[str] = []
    if not previews:
        integrity_blockers.append("citic_history_xls_batch_sources_missing")
    if structurally_recordable_source_count != len(previews):
        integrity_blockers.append(
            "citic_history_xls_batch_source_structure_not_recordable"
        )
    if invalid_row_count:
        integrity_blockers.append("citic_history_xls_batch_invalid_rows_present")
    if invalid_event_time_count:
        integrity_blockers.append("citic_history_xls_batch_event_time_invalid")
    if within_file_duplicate_row_count:
        integrity_blockers.append("citic_history_xls_batch_duplicate_rows_present")
    if cross_file_duplicate_event_count:
        integrity_blockers.append("citic_history_xls_batch_cross_file_duplicate_events")
    if conflicting_event_identity_count:
        integrity_blockers.append("citic_history_xls_batch_conflicting_event_identity")

    integrity_status: CiticHistoryXlsBatchIntegrityStatus
    if not previews:
        integrity_status = "not_available"
    elif integrity_blockers:
        integrity_status = "blocked"
    else:
        integrity_status = "clear"
    blockers = [
        *integrity_blockers,
        "citic_history_xls_batch_query_windows_unreviewed",
        "citic_history_xls_batch_settlement_components_missing",
        "citic_history_xls_batch_current_account_snapshots_missing",
        "citic_history_xls_batch_account_scope_unbound",
    ]
    observed_event_month_counts = tuple(sorted(observed_month_counts.items()))
    fingerprint_payload = {
        "schema_version": CITIC_HISTORY_XLS_BATCH_ASSESSMENT_SCHEMA_VERSION,
        "sources": sorted(
            (
                {
                    "file_fingerprint": preview.file_fingerprint,
                    "source_preview_fingerprint": (
                        citic_source_preview_fingerprint(preview)
                    ),
                }
                for preview in previews
            ),
            key=lambda source: (
                source["file_fingerprint"],
                source["source_preview_fingerprint"],
            ),
        ),
        "integrity_status": integrity_status,
        "source_count": len(previews),
        "structurally_recordable_source_count": (structurally_recordable_source_count),
        "observed_event_count": observed_event_count,
        "unique_event_count": len(row_fingerprint_sources),
        "within_file_duplicate_row_count": within_file_duplicate_row_count,
        "cross_file_duplicate_event_count": cross_file_duplicate_event_count,
        "conflicting_event_identity_count": conflicting_event_identity_count,
        "invalid_row_count": invalid_row_count,
        "invalid_event_time_count": invalid_event_time_count,
        "observed_event_month_counts": observed_event_month_counts,
        "blockers": blockers,
    }
    batch_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return CiticHistoryXlsBatchAssessment(
        schema_version=CITIC_HISTORY_XLS_BATCH_ASSESSMENT_SCHEMA_VERSION,
        status="blocked",
        integrity_status=integrity_status,
        source_count=len(previews),
        structurally_recordable_source_count=structurally_recordable_source_count,
        source_with_financial_events_count=source_with_financial_events_count,
        source_without_financial_events_count=(
            len(previews) - source_with_financial_events_count
        ),
        observed_event_count=observed_event_count,
        unique_event_count=len(row_fingerprint_sources),
        within_file_duplicate_row_count=within_file_duplicate_row_count,
        cross_file_duplicate_event_count=cross_file_duplicate_event_count,
        conflicting_event_identity_count=conflicting_event_identity_count,
        invalid_row_count=invalid_row_count,
        invalid_event_time_count=invalid_event_time_count,
        recognized_non_financial_activity_count=non_financial_activity_count,
        observed_event_months=tuple(month for month, _ in observed_event_month_counts),
        observed_event_month_counts=observed_event_month_counts,
        batch_fingerprint=batch_fingerprint,
        blockers=tuple(dict.fromkeys(blockers)),
        required_evidence=(
            "reviewed_query_window_for_each_source",
            "itemized_settlement_or_cash_flow",
            "current_cash_and_position_snapshot",
            "reviewed_account_alias_binding",
        ),
        limitations=(
            "Observed event months prove only where recognized rows occurred; they do not prove the exported query windows or complete month coverage.",
            "A source with no recognized financial event may still be a valid no-activity export, but only an explicit reviewed query window can establish that scope.",
            "History-trade XLS does not contain itemized settlement components or current cash and position snapshots.",
        ),
    )


def _event_month(value: str) -> str | None:
    try:
        occurred_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        return None
    return occurred_at.strftime("%Y-%m")


def scan_citic_history_xls_directory(
    *,
    path: str | Path,
    enabled: bool,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> CiticHistoryXlsDirectoryScan:
    """Read stable direct-child XLS files under explicit bounded limits."""

    if not enabled:
        return _scan_result(
            enabled=False,
            state="disabled",
            candidate_file_count=0,
            duplicate_file_count=0,
            unreadable_file_count=0,
            error_codes=("citic_history_xls_directory_disabled",),
            previews=(),
        )

    directory = Path(path)
    try:
        if not directory.is_dir():
            return _blocked_scan("citic_history_xls_directory_unavailable")
        children = tuple(directory.iterdir())
    except OSError:
        return _blocked_scan("citic_history_xls_directory_unavailable")

    candidates = tuple(child for child in children if child.suffix.lower() == ".xls")
    if len(candidates) > max_files:
        return _blocked_scan(
            "citic_history_xls_directory_file_limit_exceeded",
            candidate_file_count=len(candidates),
        )
    if not candidates:
        return _scan_result(
            enabled=True,
            state="empty",
            candidate_file_count=0,
            duplicate_file_count=0,
            unreadable_file_count=0,
            error_codes=(),
            previews=(),
        )

    metadata: list[tuple[Path, int, int]] = []
    metadata_error_codes: list[str] = []
    total_bytes = 0
    for candidate in candidates:
        try:
            if candidate.is_symlink() or not candidate.is_file():
                metadata_error_codes.append("citic_history_xls_directory_unsafe_file")
                continue
            stat = candidate.stat()
        except OSError:
            metadata_error_codes.append("citic_history_xls_directory_stat_failed")
            continue
        if stat.st_size > max_file_bytes:
            metadata_error_codes.append("citic_history_xls_directory_file_too_large")
            continue
        total_bytes += stat.st_size
        metadata.append((candidate, stat.st_mtime_ns, stat.st_size))

    if total_bytes > max_total_bytes:
        return _blocked_scan(
            "citic_history_xls_directory_total_size_exceeded",
            candidate_file_count=len(candidates),
        )

    parsed_previews: list[tuple[BrokerStatementPreview, str | None]] = []
    read_error_codes = list(metadata_error_codes)
    for candidate, expected_mtime_ns, expected_size in metadata:
        try:
            content = candidate.read_bytes()
            after = candidate.stat()
        except OSError:
            read_error_codes.append("citic_history_xls_directory_read_failed")
            continue
        if (
            after.st_mtime_ns != expected_mtime_ns
            or after.st_size != expected_size
            or len(content) != expected_size
        ):
            read_error_codes.append("citic_history_xls_directory_file_changed")
            continue
        try:
            parsed_previews.append(
                (
                    parse_citic_history_xls(content),
                    _local_name_month_hint(candidate.name),
                )
            )
        except Exception:
            read_error_codes.append("citic_history_xls_directory_parse_failed")

    previews_by_fingerprint: dict[str, BrokerStatementPreview] = {}
    month_hint_by_fingerprint: dict[str, str | None] = {}
    duplicate_file_count = 0
    for preview, month_hint in parsed_previews:
        if preview.file_fingerprint in previews_by_fingerprint:
            duplicate_file_count += 1
            if month_hint_by_fingerprint[preview.file_fingerprint] != month_hint:
                month_hint_by_fingerprint[preview.file_fingerprint] = None
            continue
        previews_by_fingerprint[preview.file_fingerprint] = preview
        month_hint_by_fingerprint[preview.file_fingerprint] = month_hint
    previews = tuple(
        previews_by_fingerprint[fingerprint]
        for fingerprint in sorted(previews_by_fingerprint)
    )
    local_name_month_hints = tuple(
        (fingerprint, month_hint)
        for fingerprint in sorted(previews_by_fingerprint)
        if (month_hint := month_hint_by_fingerprint[fingerprint]) is not None
    )
    unreadable_file_count = len(read_error_codes)
    if previews and unreadable_file_count:
        state: CiticHistoryXlsDirectoryState = "partial"
    elif previews:
        state = "ready"
    else:
        state = "blocked"
    return _scan_result(
        enabled=True,
        state=state,
        candidate_file_count=len(candidates),
        duplicate_file_count=duplicate_file_count,
        unreadable_file_count=unreadable_file_count,
        error_codes=tuple(sorted(set(read_error_codes))),
        previews=previews,
        local_name_month_hints=local_name_month_hints,
    )


def find_citic_history_xls_directory_preview(
    *,
    expected_file_fingerprint: str,
    path: str | Path,
    enabled: bool,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> BrokerStatementPreview:
    """Re-scan and resolve one exact file fingerprint for human review."""

    scan = scan_citic_history_xls_directory(
        path=path,
        enabled=enabled,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )
    if scan.state in {"disabled", "blocked"}:
        code = (
            scan.error_codes[0]
            if scan.error_codes
            else "citic_history_xls_directory_blocked"
        )
        raise CiticHistoryXlsDirectoryRejected(code)
    for preview in scan.previews:
        if preview.file_fingerprint == expected_file_fingerprint:
            return preview
    raise CiticHistoryXlsDirectoryRejected(
        "citic_history_xls_directory_fingerprint_not_found"
    )


def _blocked_scan(
    code: str,
    *,
    candidate_file_count: int = 0,
) -> CiticHistoryXlsDirectoryScan:
    return _scan_result(
        enabled=True,
        state="blocked",
        candidate_file_count=candidate_file_count,
        duplicate_file_count=0,
        unreadable_file_count=candidate_file_count,
        error_codes=(code,),
        previews=(),
    )


def _scan_result(
    *,
    enabled: bool,
    state: CiticHistoryXlsDirectoryState,
    candidate_file_count: int,
    duplicate_file_count: int,
    unreadable_file_count: int,
    error_codes: tuple[str, ...],
    previews: tuple[BrokerStatementPreview, ...],
    local_name_month_hints: tuple[tuple[str, str], ...] = (),
) -> CiticHistoryXlsDirectoryScan:
    batch_assessment = build_citic_history_xls_batch_assessment(previews)
    fingerprint_payload = {
        "schema_version": CITIC_HISTORY_XLS_DIRECTORY_SCHEMA_VERSION,
        "enabled": enabled,
        "state": state,
        "candidate_file_count": candidate_file_count,
        "duplicate_file_count": duplicate_file_count,
        "unreadable_file_count": unreadable_file_count,
        "error_codes": list(error_codes),
        "batch_assessment": {
            "batch_fingerprint": batch_assessment.batch_fingerprint,
            "integrity_status": batch_assessment.integrity_status,
        },
        "previews": [
            {
                "file_fingerprint": preview.file_fingerprint,
                "source_preview_fingerprint": citic_source_preview_fingerprint(preview),
            }
            for preview in previews
        ],
    }
    scan_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return CiticHistoryXlsDirectoryScan(
        schema_version=CITIC_HISTORY_XLS_DIRECTORY_SCHEMA_VERSION,
        enabled=enabled,
        state=state,
        candidate_file_count=candidate_file_count,
        preview_count=len(previews),
        duplicate_file_count=duplicate_file_count,
        unreadable_file_count=unreadable_file_count,
        recognized_event_count=sum(len(preview.events) for preview in previews),
        valid_row_count=sum(preview.valid_row_count for preview in previews),
        invalid_row_count=sum(preview.invalid_row_count for preview in previews),
        scan_fingerprint=scan_fingerprint,
        error_codes=error_codes,
        previews=previews,
        batch_assessment=batch_assessment,
        local_name_month_hints=local_name_month_hints,
    )


def _local_name_month_hint(source_name: str) -> str | None:
    """Return one sanitized month token without treating it as evidence."""

    matches = _LOCAL_NAME_MONTH_TOKEN.findall(Path(source_name).stem)
    if len(matches) != 1:
        return None
    year, month = matches[0]
    return f"{year}-{month}"
