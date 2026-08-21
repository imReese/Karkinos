"""Stable lineage for trusted local statement facts and derived daily snapshots.

The lineage deliberately excludes only snapshots produced by Karkinos' bounded
daily no-activity roll-forward.  Every persisted non-generated row remains in
the fingerprint, so a new transaction, correction, duplicate, or other source
fact invalidates inherited reviews.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from account_truth.broker_statement_roll_forward import (
    DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX,
    DAILY_SNAPSHOT_ROLL_FORWARD_NOTE,
)

ACCOUNT_TRUTH_SOURCE_FACT_LINEAGE_SCHEMA_VERSION = (
    "karkinos.account_truth.source_fact_lineage.v1"
)

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_CASH_EVENT_ID = re.compile(
    rf"^{re.escape(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX)}"
    r"(?P<date>[0-9]{8})-cash-(?P<tag>[0-9a-f]{12})$"
)
_POSITION_EVENT_ID = re.compile(
    rf"^{re.escape(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX)}"
    r"(?P<date>[0-9]{8})-position-(?P<symbol>[0-9a-f]{12})-"
    r"(?P<tag>[0-9a-f]{12})$"
)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_ZERO_FIELDS = (
    "quantity",
    "gross_amount",
    "fee",
    "tax",
    "net_amount",
    "transfer_fee",
)


def project_account_truth_source_fact_lineage(
    *,
    import_run: Any,
    events: Sequence[Any],
) -> dict[str, object]:
    """Return a privacy-minimized, fail-closed source-fact lineage projection."""

    blockers: list[str] = []
    expected_count = _nonnegative_int(getattr(import_run, "valid_row_count", None))
    if expected_count is None or expected_count != len(events):
        blockers.append("account_truth_source_fact_lineage_event_count_mismatch")

    base_events: list[Any] = []
    derived_events: list[Any] = []
    event_ids: set[str] = set()
    row_numbers: set[int] = set()
    for event in events:
        event_id = str(getattr(event, "event_id", "")).strip()
        row_number = _positive_int(getattr(event, "row_number", None))
        row_fingerprint = str(getattr(event, "row_fingerprint", "")).strip()
        if not event_id or event_id in event_ids:
            blockers.append("account_truth_source_fact_lineage_event_identity_invalid")
        else:
            event_ids.add(event_id)
        if row_number is None or row_number in row_numbers:
            blockers.append("account_truth_source_fact_lineage_row_identity_invalid")
        else:
            row_numbers.add(row_number)
        if not _SHA256_HEX.fullmatch(row_fingerprint):
            blockers.append("account_truth_source_fact_lineage_row_fingerprint_invalid")
        if event_id.startswith(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX):
            derived_events.append(event)
        else:
            base_events.append(event)

    if not base_events:
        blockers.append("account_truth_source_fact_lineage_base_events_missing")
    if any(bool(getattr(event, "is_row_duplicate", False)) for event in derived_events):
        blockers.append("account_truth_source_fact_lineage_derived_duplicate")

    derived = _validate_derived_snapshots(
        derived_events,
        base_events=base_events,
    )
    blockers.extend(str(item) for item in derived["blockers"])

    source_type = str(getattr(import_run, "source_type", "")).strip()
    base_row_fingerprints = sorted(
        str(getattr(event, "row_fingerprint", "")).strip() for event in base_events
    )
    lineage_core = {
        "schema_version": ACCOUNT_TRUTH_SOURCE_FACT_LINEAGE_SCHEMA_VERSION,
        "source_type": source_type,
        "base_event_count": len(base_events),
        "base_row_fingerprints": base_row_fingerprints,
    }
    source_fact_fingerprint = _fingerprint(lineage_core)
    unique_blockers = list(dict.fromkeys(blockers))
    projection_core = {
        "schema_version": ACCOUNT_TRUTH_SOURCE_FACT_LINEAGE_SCHEMA_VERSION,
        "status": "pass" if not unique_blockers else "blocked",
        "source_fact_fingerprint": source_fact_fingerprint,
        "base_event_count": len(base_events),
        "derived_snapshot_count": len(derived_events),
        "derived_cash_snapshot_count": derived["cash_count"],
        "derived_position_snapshot_count": derived["position_count"],
        "derived_snapshot_date": derived["snapshot_date"],
        "derived_source_tag": derived["source_tag"],
        "blockers": unique_blockers,
        "contains_private_financial_values": False,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    return {**projection_core, "evidence_fingerprint": _fingerprint(projection_core)}


def source_fact_lineages_match(
    current: dict[str, object],
    reviewed: dict[str, object],
    *,
    require_current_derived_snapshot: bool = True,
) -> bool:
    """Accept only exact stable lineage with a valid current derived snapshot."""

    return bool(
        current.get("status") == "pass"
        and reviewed.get("status") == "pass"
        and current.get("source_fact_fingerprint")
        == reviewed.get("source_fact_fingerprint")
        and current.get("base_event_count") == reviewed.get("base_event_count")
        and (
            not require_current_derived_snapshot
            or int(current.get("derived_snapshot_count") or 0) > 0
        )
    )


def source_fact_lineage_history_is_continuous(
    *,
    repository: Any,
    current_import: Any,
    reviewed_import: Any,
    limit: int = 1000,
) -> bool:
    """Reject old-lineage resurrection after any intervening import drift."""

    if limit < 1 or limit > 1000:
        return False
    imports = list(repository.list_import_runs(limit=limit))
    import_ids = [str(getattr(item, "import_run_id", "")) for item in imports]
    try:
        current_index = import_ids.index(str(current_import.import_run_id))
        reviewed_index = import_ids.index(str(reviewed_import.import_run_id))
    except ValueError:
        return False
    if current_index > reviewed_index:
        return False

    reviewed_lineage = _lineage_for_repository_import(repository, reviewed_import)
    current_lineage = _lineage_for_repository_import(repository, current_import)
    if not source_fact_lineages_match(
        current_lineage,
        reviewed_lineage,
        require_current_derived_snapshot=(
            current_import.import_run_id != reviewed_import.import_run_id
        ),
    ):
        return False
    expected_fingerprint = reviewed_lineage.get("source_fact_fingerprint")
    for import_run in imports[current_index : reviewed_index + 1]:
        lineage = _lineage_for_repository_import(repository, import_run)
        if (
            lineage.get("status") != "pass"
            or lineage.get("source_fact_fingerprint") != expected_fingerprint
        ):
            return False
    return True


def account_truth_scope_review_binding_fingerprint(
    review: Any,
    *,
    source_fact_fingerprint: str,
) -> str:
    """Bind one human scope decision to stable source facts, not daily snapshots."""

    core = {
        "schema_version": "karkinos.account_truth.evidence_scope_review_binding.v1",
        "review_id": str(getattr(review, "review_id", "")),
        "review_fingerprint": str(getattr(review, "review_fingerprint", "")),
        "source_fact_fingerprint": source_fact_fingerprint,
        "provider": str(getattr(review, "provider", "")),
        "account_reference_hash": str(getattr(review, "account_reference_hash", "")),
        "coverage_start_date": str(getattr(review, "coverage_start_date", "")),
        "coverage_end_date": str(getattr(review, "coverage_end_date", "")),
        "asset_classes": list(getattr(review, "asset_classes", []) or []),
        "full_account_scope_attested": (
            getattr(review, "full_account_scope_attested", None) is True
        ),
        "decision": str(getattr(review, "decision", "")),
    }
    return _fingerprint(core)


def _lineage_for_repository_import(
    repository: Any,
    import_run: Any,
) -> dict[str, object]:
    events = repository.list_events(
        import_run.duplicate_of_import_run_id or import_run.import_run_id
    )
    return project_account_truth_source_fact_lineage(
        import_run=import_run,
        events=events,
    )


def _validate_derived_snapshots(
    events: Sequence[Any],
    *,
    base_events: Sequence[Any],
) -> dict[str, object]:
    if not events:
        return {
            "cash_count": 0,
            "position_count": 0,
            "snapshot_date": None,
            "source_tag": None,
            "blockers": [],
        }

    blockers: list[str] = []
    dates: set[str] = set()
    tags: set[str] = set()
    cash_count = 0
    position_count = 0
    position_symbols: set[str] = set()
    latest_base_by_symbol = {
        str(getattr(event, "symbol", "")).strip(): event
        for event in sorted(
            base_events,
            key=lambda item: (
                str(getattr(item, "occurred_at", "")),
                int(getattr(item, "row_number", 0) or 0),
            ),
        )
        if str(getattr(event, "symbol", "")).strip()
    }
    for event in events:
        event_id = str(getattr(event, "event_id", "")).strip()
        event_type = str(getattr(event, "event_type", "")).strip()
        note = str(getattr(event, "note", ""))
        if note != DAILY_SNAPSHOT_ROLL_FORWARD_NOTE:
            blockers.append("account_truth_source_fact_lineage_derived_note_invalid")
        if any(not _is_zero(getattr(event, field, None)) for field in _ZERO_FIELDS):
            blockers.append("account_truth_source_fact_lineage_derived_amount_invalid")

        match = _CASH_EVENT_ID.fullmatch(event_id)
        if match is not None and event_type == "cash_snapshot":
            cash_count += 1
            if getattr(event, "cash_balance", None) is None:
                blockers.append(
                    "account_truth_source_fact_lineage_derived_cash_invalid"
                )
        else:
            match = _POSITION_EVENT_ID.fullmatch(event_id)
            if match is None or event_type != "position_snapshot":
                blockers.append(
                    "account_truth_source_fact_lineage_derived_identity_invalid"
                )
                continue
            position_count += 1
            symbol = str(getattr(event, "symbol", "")).strip()
            base_position = latest_base_by_symbol.get(symbol)
            if (
                not symbol
                or symbol in position_symbols
                or hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:12]
                != match.group("symbol")
                or getattr(event, "position_quantity", None) is None
                or getattr(event, "cost_basis", None) is None
                or base_position is None
                or any(
                    str(getattr(event, field, ""))
                    != str(getattr(base_position, field, ""))
                    for field in (
                        "instrument_name",
                        "asset_class",
                        "currency",
                        "price",
                        "position_quantity",
                        "cost_basis",
                        "cost_basis_method",
                    )
                )
            ):
                blockers.append(
                    "account_truth_source_fact_lineage_derived_position_invalid"
                )
            position_symbols.add(symbol)

        assert match is not None
        raw_date = match.group("date")
        tags.add(match.group("tag"))
        try:
            parsed_occurred_at = datetime.fromisoformat(
                str(getattr(event, "occurred_at", ""))
            )
        except (TypeError, ValueError):
            blockers.append("account_truth_source_fact_lineage_derived_time_invalid")
            continue
        if parsed_occurred_at.tzinfo is None or parsed_occurred_at.utcoffset() is None:
            blockers.append("account_truth_source_fact_lineage_derived_time_invalid")
            continue
        occurred_at = parsed_occurred_at.astimezone(_SHANGHAI_TZ)
        if (
            occurred_at.strftime("%Y%m%d") != raw_date
            or occurred_at.timetz().replace(tzinfo=None) != time(8, 45)
            or str(getattr(event, "settled_at", "")) != occurred_at.date().isoformat()
        ):
            blockers.append("account_truth_source_fact_lineage_derived_time_invalid")
        dates.add(occurred_at.date().isoformat())

    if cash_count != 1:
        blockers.append("account_truth_source_fact_lineage_derived_cash_count_invalid")
    if position_count < 1:
        blockers.append(
            "account_truth_source_fact_lineage_derived_position_count_invalid"
        )
    if position_symbols != set(latest_base_by_symbol):
        blockers.append(
            "account_truth_source_fact_lineage_derived_position_set_invalid"
        )
    if len(dates) != 1 or len(tags) != 1:
        blockers.append("account_truth_source_fact_lineage_derived_batch_invalid")
    return {
        "cash_count": cash_count,
        "position_count": position_count,
        "snapshot_date": next(iter(dates)) if len(dates) == 1 else None,
        "source_tag": next(iter(tags)) if len(tags) == 1 else None,
        "blockers": list(dict.fromkeys(blockers)),
    }


def _is_zero(value: object) -> bool:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return parsed.is_finite() and parsed == 0


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _nonnegative_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
