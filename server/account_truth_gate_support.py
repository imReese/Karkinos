"""Pure value, snapshot, and ledger helpers for the Account Truth gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from server.account_truth_gate_values import (
    breakdown_decimal,
    broker_events_for_import_run,
    db_path_for_state,
    decimal_or_zero,
    ledger_fact_from_entry,
    ledger_fee_component,
    ledger_net_cash_impact,
    ledger_tax_component,
    ledger_transfer_fee_component,
    optional_decimal,
    parse_aware_timestamp,
    parse_fact_timestamp,
    same_shanghai_date,
)

ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION = (
    "karkinos.account_truth.promotion_evidence.v1"
)
ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS = 86400
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def missing_account_truth_promotion_evidence(
    blockers: list[str],
) -> dict[str, object]:
    return {
        "schema_version": ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        "status": "blocked",
        "source_fingerprint": "",
        "import_run_id": "",
        "file_fingerprint": "",
        "source_type": "",
        "captured_at": "",
        "imported_at": "",
        "snapshot_capture": {
            "status": "missing",
            "captured_at": "",
            "latest_cash_snapshot_at": "",
            "latest_position_snapshot_at": "",
            "latest_non_snapshot_event_at": "",
            "blockers": ["account_truth_snapshot_evidence_missing"],
        },
        "current_age_seconds": None,
        "max_age_seconds": ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS,
        "data_freshness_status": "missing",
        "reconciliation_status": "missing",
        "score": 0,
        "gate_status": "blocked",
        "cash_status": "missing",
        "position_status": "missing",
        "fee_status": "missing",
        "cost_basis_status": "missing",
        "unresolved_mismatch_count": 0,
        "resolved_review_count": 0,
        "blockers": list(dict.fromkeys(blockers)),
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
    }


def account_truth_item_key(category: str, symbol: str) -> str:
    return f"{category}:{symbol}" if symbol else category


def account_truth_snapshot_capture(
    events: list[StoredBrokerEvidenceEvent],
) -> dict[str, object]:
    """Resolve the effective Account Truth capture from persisted snapshots."""

    unique_events = [event for event in events if not event.is_row_duplicate]
    cash_timestamps = [
        parsed
        for event in unique_events
        if event.event_type == "cash_snapshot"
        and (parsed := parse_aware_timestamp(event.occurred_at)) is not None
    ]
    position_timestamps = [
        parsed
        for event in unique_events
        if event.event_type == "position_snapshot"
        and (parsed := parse_aware_timestamp(event.occurred_at)) is not None
    ]
    non_snapshot_timestamps = [
        parsed
        for event in unique_events
        if event.event_type not in {"cash_snapshot", "position_snapshot"}
        and (parsed := parse_aware_timestamp(event.occurred_at)) is not None
    ]
    latest_cash = max(cash_timestamps, default=None)
    latest_position = max(position_timestamps, default=None)
    latest_non_snapshot = max(non_snapshot_timestamps, default=None)
    blockers: list[str] = []
    if latest_cash is None:
        blockers.append("account_truth_cash_snapshot_missing")
    if latest_position is None:
        blockers.append("account_truth_position_snapshot_missing")

    captured_at = (
        min(latest_cash, latest_position)
        if latest_cash is not None and latest_position is not None
        else None
    )
    if (
        latest_cash is not None
        and latest_position is not None
        and latest_cash.astimezone(_SHANGHAI_TZ).date()
        != latest_position.astimezone(_SHANGHAI_TZ).date()
    ):
        blockers.append("account_truth_snapshot_dates_mismatch")
    if (
        captured_at is not None
        and latest_non_snapshot is not None
        and latest_non_snapshot > captured_at
    ):
        blockers.append("account_truth_snapshot_predates_latest_event")

    return {
        "status": "clear" if not blockers else "blocked",
        "captured_at": captured_at.isoformat() if captured_at is not None else "",
        "latest_cash_snapshot_at": (
            latest_cash.isoformat() if latest_cash is not None else ""
        ),
        "latest_position_snapshot_at": (
            latest_position.isoformat() if latest_position is not None else ""
        ),
        "latest_non_snapshot_event_at": (
            latest_non_snapshot.isoformat() if latest_non_snapshot is not None else ""
        ),
        "blockers": blockers,
    }


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def fingerprint_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def latest_reconcilable_import_run(
    repository: BrokerEvidenceRepository,
) -> BrokerImportRun | None:
    for import_run in repository.list_import_runs(limit=100):
        if import_run.valid_row_count <= 0:
            continue
        if import_run.validation_status == "blocked":
            continue
        return import_run
    return None


# Compatibility shims for callers that imported the pre-split support module.
# Ledger support depends on the lower-level values module, so this lazy edge is
# one-way and keeps importing the pure gate helpers lightweight.
def load_canonical_ledger_rows(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from server.account_truth_ledger_support import (
        load_canonical_ledger_rows as implementation,
    )

    return implementation(*args, **kwargs)


def legacy_fund_duplicate_roll_forward_guardrail(*args: Any, **kwargs: Any) -> Any:
    from server.account_truth_ledger_support import (
        legacy_fund_duplicate_roll_forward_guardrail as implementation,
    )

    return implementation(*args, **kwargs)


def karkinos_account_facts(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from server.account_truth_ledger_support import (
        karkinos_account_facts as implementation,
    )

    return implementation(*args, **kwargs)


def latest_quotes_by_symbol(*args: Any, **kwargs: Any) -> dict[str, dict[str, object]]:
    from server.account_truth_ledger_support import (
        latest_quotes_by_symbol as implementation,
    )

    return implementation(*args, **kwargs)


def ledger_coverage_for_import(*args: Any, **kwargs: Any) -> dict[str, object]:
    from server.account_truth_ledger_support import (
        ledger_coverage_for_import as implementation,
    )

    return implementation(*args, **kwargs)


def broker_evidence_covered_ledger_entry_ids(*args: Any, **kwargs: Any) -> set[int]:
    from server.account_truth_ledger_support import (
        broker_evidence_covered_ledger_entry_ids as implementation,
    )

    return implementation(*args, **kwargs)


def posting_covered_ledger_entry_ids(*args: Any, **kwargs: Any) -> set[int]:
    from server.account_truth_ledger_support import (
        posting_covered_ledger_entry_ids as implementation,
    )

    return implementation(*args, **kwargs)


def freshness_with_ledger_coverage(*args: Any, **kwargs: Any) -> str:
    from server.account_truth_ledger_support import (
        freshness_with_ledger_coverage as implementation,
    )

    return implementation(*args, **kwargs)


__all__ = [
    "ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION",
    "ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS",
    "account_truth_item_key",
    "account_truth_snapshot_capture",
    "aware_utc",
    "breakdown_decimal",
    "broker_events_for_import_run",
    "broker_evidence_covered_ledger_entry_ids",
    "db_path_for_state",
    "decimal_or_zero",
    "fingerprint_json",
    "freshness_with_ledger_coverage",
    "karkinos_account_facts",
    "latest_quotes_by_symbol",
    "latest_reconcilable_import_run",
    "ledger_coverage_for_import",
    "ledger_fact_from_entry",
    "ledger_fee_component",
    "ledger_net_cash_impact",
    "ledger_tax_component",
    "ledger_transfer_fee_component",
    "legacy_fund_duplicate_roll_forward_guardrail",
    "load_canonical_ledger_rows",
    "missing_account_truth_promotion_evidence",
    "optional_decimal",
    "parse_aware_timestamp",
    "parse_fact_timestamp",
    "posting_covered_ledger_entry_ids",
    "same_shanghai_date",
]
