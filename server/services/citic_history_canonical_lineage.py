"""Read-only lineage assessment between CITIC history exports and Account Truth."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Hashable, Iterable, Sequence

from account_truth.broker_evidence import (
    BrokerEvidenceReadRejected,
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from account_truth.broker_statement import BrokerEvidenceEvent
from account_truth.citic_history_xls_directory import CiticHistoryXlsDirectoryScan
from server.account_truth_gate import build_latest_account_truth_score_payload

CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_history_canonical_lineage_assessment.v1"
)
_MATCH_CONTRACT_VERSION = "citic_history_financial_semantics.v1"
_CITIC_SUPPORTED_EVENT_TYPES = frozenset({"trade_buy", "trade_sell", "dividend"})


def build_citic_history_canonical_lineage_assessment(
    state: Any,
    *,
    scan: CiticHistoryXlsDirectoryScan,
) -> dict[str, object]:
    """Compare the explicit runtime scan with the selected canonical import."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        return project_citic_history_canonical_lineage_assessment(
            scan=scan,
            canonical_import=None,
            canonical_events=(),
            read_blocker="citic_canonical_lineage_database_unavailable",
        )
    try:
        score = build_latest_account_truth_score_payload(state)
        import_run_id = str(score.get("import_run_id") or "").strip()
        if not import_run_id:
            return project_citic_history_canonical_lineage_assessment(
                scan=scan,
                canonical_import=None,
                canonical_events=(),
            )
        repository = BrokerEvidenceRepository(db_path)
        import_run = repository.get_import_run(import_run_id)
        events = repository.list_events(import_run_id) if import_run is not None else []
    except (BrokerEvidenceReadRejected, OSError, ValueError):
        return project_citic_history_canonical_lineage_assessment(
            scan=scan,
            canonical_import=None,
            canonical_events=(),
            read_blocker="citic_canonical_lineage_canonical_evidence_unreadable",
        )
    return project_citic_history_canonical_lineage_assessment(
        scan=scan,
        canonical_import=import_run,
        canonical_events=events,
    )


def project_citic_history_canonical_lineage_assessment(
    *,
    scan: CiticHistoryXlsDirectoryScan,
    canonical_import: BrokerImportRun | None,
    canonical_events: Sequence[StoredBrokerEvidenceEvent],
    read_blocker: str | None = None,
) -> dict[str, object]:
    """Project only sanitized counts and fingerprints; never return event facts."""

    source_events = [
        event
        for preview in scan.previews
        for event in preview.events
        if event.event_type in _CITIC_SUPPORTED_EVENT_TYPES
    ]
    comparable_canonical_events = [
        event
        for event in canonical_events
        if event.event_type in _CITIC_SUPPORTED_EVENT_TYPES
        and not event.is_row_duplicate
    ]
    source_semantics = _safe_counter(source_events, _financial_semantic_key)
    canonical_semantics = _safe_counter(
        comparable_canonical_events,
        _financial_semantic_key,
    )
    source_broker_identities = _safe_counter(
        (event for event in source_events if event.broker_order_id),
        _broker_order_identity_key,
    )
    canonical_broker_identities = _safe_counter(
        (event for event in comparable_canonical_events if event.broker_order_id),
        _broker_order_identity_key,
    )
    source_event_identities = Counter(
        event.event_id for event in source_events if event.event_id
    )
    canonical_event_identities = Counter(
        event.event_id for event in comparable_canonical_events if event.event_id
    )
    matched_semantics = source_semantics & canonical_semantics
    source_unmatched_semantics = source_semantics - canonical_semantics
    canonical_unmatched_semantics = canonical_semantics - source_semantics

    source_count = len(source_events)
    canonical_count = len(comparable_canonical_events)
    semantic_match_count = sum(matched_semantics.values())
    broker_order_identity_match_count = _counter_overlap(
        source_broker_identities,
        canonical_broker_identities,
    )
    exact_event_identity_match_count = _counter_overlap(
        source_event_identities,
        canonical_event_identities,
    )
    source_with_broker_order_identity_count = sum(source_broker_identities.values())
    canonical_with_broker_order_identity_count = sum(
        canonical_broker_identities.values()
    )
    source_unmatched_count = max(0, source_count - semantic_match_count)
    canonical_unmatched_count = max(0, canonical_count - semantic_match_count)

    blockers: list[str] = ["citic_canonical_lineage_complete_account_coverage_unproven"]
    if read_blocker:
        blockers.append(read_blocker)
    if scan.state != "ready":
        blockers.append("citic_canonical_lineage_source_scan_not_ready")
    if not source_events:
        blockers.append("citic_canonical_lineage_source_events_missing")
    if canonical_import is None:
        blockers.append("citic_canonical_lineage_canonical_import_missing")
    if canonical_import is not None and not comparable_canonical_events:
        blockers.append("citic_canonical_lineage_canonical_events_missing")
    if source_unmatched_count:
        blockers.append("citic_canonical_lineage_source_events_unmatched")
    if canonical_unmatched_count:
        blockers.append("citic_canonical_lineage_canonical_events_outside_source_batch")
    if (
        source_with_broker_order_identity_count
        and broker_order_identity_match_count < source_with_broker_order_identity_count
    ):
        blockers.append("citic_canonical_lineage_broker_order_identity_not_preserved")
    if source_count and exact_event_identity_match_count < source_count:
        blockers.append("citic_canonical_lineage_event_identity_not_preserved")

    exact_event_lineage = bool(
        scan.state == "ready"
        and canonical_import is not None
        and source_count > 0
        and source_count == canonical_count == semantic_match_count
        and exact_event_identity_match_count == source_count
        and broker_order_identity_match_count == source_with_broker_order_identity_count
    )
    event_lineage_status = (
        "exact"
        if exact_event_lineage
        else (
            "partial"
            if source_count and canonical_import is not None and semantic_match_count
            else "not_available"
        )
    )
    core = {
        "schema_version": CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION,
        "status": "blocked",
        "event_lineage_status": event_lineage_status,
        "match_contract_version": _MATCH_CONTRACT_VERSION,
        "source_batch_fingerprint": scan.batch_assessment.batch_fingerprint,
        "canonical_import_reference": (
            f"account_truth_import:{canonical_import.import_run_id}"
            if canonical_import is not None
            else None
        ),
        "canonical_import_file_fingerprint": (
            canonical_import.file_fingerprint if canonical_import is not None else None
        ),
        "source_supported_event_count": source_count,
        "canonical_supported_event_count": canonical_count,
        "semantically_matched_event_count": semantic_match_count,
        "source_unmatched_event_count": source_unmatched_count,
        "canonical_unmatched_event_count": canonical_unmatched_count,
        "source_event_type_counts": _semantic_event_type_counts(source_semantics),
        "canonical_event_type_counts": _semantic_event_type_counts(canonical_semantics),
        "semantically_matched_event_type_counts": _semantic_event_type_counts(
            matched_semantics
        ),
        "source_unmatched_event_type_counts": _semantic_event_type_counts(
            source_unmatched_semantics
        ),
        "canonical_unmatched_event_type_counts": _semantic_event_type_counts(
            canonical_unmatched_semantics
        ),
        "source_events_with_broker_order_identity_count": (
            source_with_broker_order_identity_count
        ),
        "canonical_events_with_broker_order_identity_count": (
            canonical_with_broker_order_identity_count
        ),
        "broker_order_identity_matched_event_count": (
            broker_order_identity_match_count
        ),
        "exact_event_identity_matched_event_count": (exact_event_identity_match_count),
        "semantic_match_dimensions": [
            "event_type",
            "occurred_at",
            "settled_at",
            "symbol",
            "instrument_name",
            "asset_class",
            "currency",
            "quantity",
            "price",
            "gross_amount",
            "net_amount",
        ],
        "blockers": list(dict.fromkeys(blockers)),
        "required_evidence": [
            "preserve_source_event_and_broker_order_identity_in_canonical_import",
            "resolve_unmatched_source_and_canonical_events",
            "reviewed_query_window_for_each_source",
            "itemized_settlement_components_and_current_account_snapshots",
        ],
        "complete_account_coverage_proven": False,
        "events_included": False,
        "transaction_details_included": False,
        "private_fields_included": False,
        "source_names_included": False,
        "paths_included": False,
        "assessment_persisted": False,
        "database_writes_performed": False,
        "provider_contacted": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "limitations": [
            "This runtime comparison can identify matching persisted event semantics but cannot prove that the source batch is a complete account export.",
            "History-trade exports still lack itemized settlement components and current cash and position snapshots.",
            "A semantic match without preserved event and broker-order identity is not canonical source lineage.",
        ],
    }
    fingerprint_payload = {
        key: value
        for key, value in core.items()
        if key
        not in {
            "limitations",
            "assessment_persisted",
            "database_writes_performed",
            "provider_contacted",
            "eligible_for_account_truth",
            "eligible_for_reconciliation",
            "authorizes_execution",
            "changes_capital_authority",
        }
    }
    core["assessment_fingerprint"] = _fingerprint(fingerprint_payload)
    return core


def _financial_semantic_key(
    event: BrokerEvidenceEvent | StoredBrokerEvidenceEvent,
) -> tuple[Hashable, ...]:
    return (
        event.event_type,
        event.occurred_at,
        event.settled_at,
        event.symbol,
        event.instrument_name,
        event.asset_class,
        event.currency,
        _decimal(event.quantity),
        _decimal(event.price),
        _decimal(event.gross_amount),
        _decimal(event.net_amount),
    )


def _broker_order_identity_key(
    event: BrokerEvidenceEvent | StoredBrokerEvidenceEvent,
) -> tuple[Hashable, ...]:
    return (*_financial_semantic_key(event), event.broker_order_id)


def _safe_counter(
    events: Iterable[BrokerEvidenceEvent | StoredBrokerEvidenceEvent],
    key: Callable[[BrokerEvidenceEvent | StoredBrokerEvidenceEvent], Hashable],
) -> Counter[Hashable]:
    counter: Counter[Hashable] = Counter()
    for event in events:
        try:
            counter[key(event)] += 1
        except (InvalidOperation, TypeError, ValueError):
            counter[("invalid_event_semantics", event.event_id)] += 1
    return counter


def _counter_overlap(left: Counter[Hashable], right: Counter[Hashable]) -> int:
    return sum((left & right).values())


def _semantic_event_type_counts(
    semantics: Counter[Hashable],
) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    for semantic_key, count in semantics.items():
        event_type = (
            str(semantic_key[0])
            if isinstance(semantic_key, tuple)
            and semantic_key
            and semantic_key[0] in _CITIC_SUPPORTED_EVENT_TYPES
            else "invalid"
        )
        counts[event_type] += count
    return [
        {"event_type": event_type, "count": counts[event_type]}
        for event_type in sorted(counts)
    ]


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _db_path_for_state(state: Any) -> Path | None:
    db = getattr(state, "db", None)
    db_path = getattr(db, "_path", None)
    return Path(db_path) if db_path is not None else None


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
