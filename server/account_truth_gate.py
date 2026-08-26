"""Shared Account Truth gate construction for routes and review surfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
)
from account_truth.manual_review import ManualReviewRepository
from account_truth.reconciliation import (
    ReconciliationReport,
    build_reconciliation_report,
)
from account_truth.score import AccountTruthScore, build_account_truth_score
from server.account_truth_gate_support import (
    ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
    ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS,
)
from server.account_truth_gate_support import (
    account_truth_item_key as _account_truth_item_key,
)
from server.account_truth_gate_support import (
    account_truth_snapshot_capture as _account_truth_snapshot_capture,
)
from server.account_truth_gate_support import aware_utc as _aware_utc
from server.account_truth_gate_support import (
    broker_events_for_import_run,
)
from server.account_truth_gate_support import db_path_for_state as _db_path_for_state
from server.account_truth_gate_support import fingerprint_json as _fingerprint_json
from server.account_truth_gate_support import (
    freshness_with_ledger_coverage as _freshness_with_ledger_coverage,
)
from server.account_truth_gate_support import (
    karkinos_account_facts as _karkinos_account_facts,
)
from server.account_truth_gate_support import (
    latest_reconcilable_import_run as _latest_reconcilable_import_run,
)
from server.account_truth_gate_support import (
    ledger_coverage_for_import as _ledger_coverage_for_import,
)
from server.account_truth_gate_support import (
    ledger_fact_from_entry as _ledger_fact_from_entry,
)
from server.account_truth_gate_support import (
    missing_account_truth_promotion_evidence as _missing_account_truth_promotion_evidence,
)
from server.account_truth_gate_support import (
    parse_aware_timestamp as _parse_aware_timestamp,
)
from server.account_truth_gate_support import (
    parse_fact_timestamp as _parse_fact_timestamp,
)
from server.account_truth_gate_support import same_shanghai_date as _same_shanghai_date
from server.services.citic_source_follow_up import build_citic_source_follow_up


def missing_account_truth_score_payload() -> dict[str, object]:
    """Return the shared fail-closed projection when no score is available."""
    return {
        "schema_version": "karkinos.account_truth.score.v1",
        "status": "missing",
        "import_run_id": None,
        "score": None,
        "gate_status": "blocked",
        "cash_status": "missing",
        "position_status": "missing",
        "fee_status": "missing",
        "cost_basis_status": "missing",
        "data_freshness_status": "missing",
        "unresolved_mismatch_count": None,
        "resolved_review_count": 0,
        "required_actions": ["import_and_reconcile_broker_evidence"],
        "blocking_reasons": ["account_truth_score_unavailable"],
        "limitations": [
            "Account Truth review requires staged broker evidence before trusted use."
        ],
    }


def build_latest_account_truth_score_payload(
    state: Any,
    *,
    data_freshness_status: str = "fresh",
) -> dict[str, object]:
    """Build the latest Account Truth score from staged broker evidence."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        return {}

    repository = BrokerEvidenceRepository(db_path)
    import_run = _latest_reconcilable_import_run(repository)
    if import_run is None:
        return {}

    ledger_coverage = _ledger_coverage_for_import(state, import_run)
    effective_freshness = _freshness_with_ledger_coverage(
        data_freshness_status,
        ledger_coverage,
    )
    score = build_account_truth_score_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
        data_freshness_status=effective_freshness,
    )
    payload = {
        **score.to_json_dict(),
        "status": "available",
        "import_run_id": import_run.import_run_id,
        "source_type": import_run.source_type,
        "source_name": import_run.source_name,
        "created_at": import_run.created_at,
        "ledger_coverage": ledger_coverage,
    }
    if ledger_coverage["status"] == "stale":
        payload["gate_status"] = "blocked"
        payload["blocking_reasons"] = list(
            dict.fromkeys(
                [
                    *list(payload.get("blocking_reasons") or []),
                    "account_truth_evidence_predates_latest_ledger",
                ]
            )
        )
        payload["required_actions"] = list(
            dict.fromkeys(
                [
                    *list(payload.get("required_actions") or []),
                    "reimport_broker_statement_after_latest_ledger_fact",
                ]
            )
        )
        payload["limitations"] = list(
            dict.fromkeys(
                [
                    *list(payload.get("limitations") or []),
                    "The latest broker evidence does not cover the latest local ledger fact.",
                ]
            )
        )
    return payload


def build_latest_account_truth_promotion_evidence(
    state: Any,
    *,
    clock: Callable[[], datetime] | None = None,
    max_age_seconds: int = ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS,
) -> dict[str, object]:
    """Build sanitized, source-sensitive Account Truth promotion evidence."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        return _missing_account_truth_promotion_evidence(
            ["account_truth_database_unavailable"]
        )
    repository = BrokerEvidenceRepository(db_path)
    import_run = _latest_reconcilable_import_run(repository)
    if import_run is None:
        return _missing_account_truth_promotion_evidence(
            ["account_truth_import_run_missing"]
        )

    now = _aware_utc((clock or (lambda: datetime.now(timezone.utc)))())
    imported_at = _parse_aware_timestamp(import_run.created_at)
    events = broker_events_for_import_run(repository, import_run)
    snapshot_capture = _account_truth_snapshot_capture(events)
    captured_at = _parse_aware_timestamp(snapshot_capture.get("captured_at"))
    effective_max_age = max(60, min(int(max_age_seconds), 604800))
    blockers: list[str] = list(snapshot_capture["blockers"])
    citic_source_follow_up = _citic_source_follow_up_for_promotion(db_path)
    if citic_source_follow_up["count_complete"] is not True:
        blockers.append(str(citic_source_follow_up["status"]))
    elif int(citic_source_follow_up["pending_source_count"]) > 0:
        blockers.append("citic_source_follow_up_required")
    blockers.extend(str(item) for item in citic_source_follow_up["blockers"])
    age_seconds: int | None = None
    freshness_status = "missing"
    if imported_at is None:
        blockers.append("account_truth_import_timestamp_invalid")
    if captured_at is None:
        blockers.append("account_truth_snapshot_timestamp_invalid")
    else:
        age = (now - captured_at).total_seconds()
        age_seconds = int(max(0, age))
        if age < -300:
            blockers.append("account_truth_snapshot_timestamp_in_future")
        elif age > effective_max_age:
            blockers.append("account_truth_snapshot_stale")
            freshness_status = "stale"
        else:
            freshness_status = "fresh"
    if (
        imported_at is not None
        and captured_at is not None
        and captured_at > imported_at
    ):
        blockers.append("account_truth_snapshot_captured_after_import")

    ledger_coverage = _ledger_coverage_for_import(state, import_run)
    freshness_status = _freshness_with_ledger_coverage(
        freshness_status,
        ledger_coverage,
    )
    if ledger_coverage["status"] == "stale":
        blockers.append("account_truth_evidence_predates_latest_ledger")

    report = build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
    )
    review_decisions = ManualReviewRepository(db_path).list_decisions(
        import_run.import_run_id
    )
    score = build_account_truth_score(
        report=report,
        review_decisions=review_decisions,
        data_freshness_status=freshness_status,
    )
    if import_run.validation_status == "blocked":
        blockers.append("account_truth_import_validation_blocked")
    if report.status == "blocked":
        blockers.append("account_truth_reconciliation_blocked")
    if score.gate_status != "pass":
        blockers.append(f"account_truth_gate_not_pass:{score.gate_status}")
    if score.unresolved_mismatch_count:
        blockers.append("account_truth_unresolved_mismatches")

    review_by_item = {decision.item_key: decision for decision in review_decisions}
    report_items = sorted(
        (
            {
                "item_key": _account_truth_item_key(item.category, item.symbol),
                "category": item.category,
                "symbol": item.symbol,
                "status": item.status,
                "broker_value": item.broker_value,
                "karkinos_value": item.karkinos_value,
                "difference": item.difference,
                "detail_code": item.detail_code,
                "review_status": str(
                    getattr(
                        review_by_item.get(
                            _account_truth_item_key(item.category, item.symbol)
                        ),
                        "review_status",
                        "",
                    )
                    or ""
                ),
            }
            for item in report.items
        ),
        key=lambda item: (item["category"], item["symbol"], item["item_key"]),
    )
    source_core = {
        "schema_version": ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        "import_run": {
            "import_run_id": import_run.import_run_id,
            "schema_version": import_run.schema_version,
            "source_type": import_run.source_type,
            "file_fingerprint": import_run.file_fingerprint,
            "row_count": import_run.row_count,
            "valid_row_count": import_run.valid_row_count,
            "invalid_row_count": import_run.invalid_row_count,
            "row_duplicate_count": import_run.row_duplicate_count,
            "validation_status": import_run.validation_status,
            "created_at": import_run.created_at,
        },
        "reconciliation": {
            "schema_version": report.schema_version,
            "status": report.status,
            "unresolved_count": report.unresolved_count,
            "items": report_items,
        },
        "score": score.to_json_dict(),
        "freshness": {
            "status": freshness_status,
            "max_age_seconds": effective_max_age,
            "snapshot_capture": snapshot_capture,
            "ledger_coverage": ledger_coverage,
        },
        "citic_source_follow_up": citic_source_follow_up,
    }
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        "status": "clear" if not unique_blockers else "blocked",
        "source_fingerprint": _fingerprint_json(source_core),
        "import_run_id": import_run.import_run_id,
        "file_fingerprint": import_run.file_fingerprint,
        "source_type": import_run.source_type,
        "captured_at": (captured_at.isoformat() if captured_at is not None else ""),
        "imported_at": import_run.created_at,
        "snapshot_capture": snapshot_capture,
        "import_validation_status": import_run.validation_status,
        "import_valid_row_count": import_run.valid_row_count,
        "current_age_seconds": age_seconds,
        "max_age_seconds": effective_max_age,
        "data_freshness_status": freshness_status,
        "ledger_coverage": ledger_coverage,
        "reconciliation_status": report.status,
        "score": score.score,
        "gate_status": score.gate_status,
        "cash_status": score.cash_status,
        "position_status": score.position_status,
        "fee_status": score.fee_status,
        "cost_basis_status": score.cost_basis_status,
        "unresolved_mismatch_count": score.unresolved_mismatch_count,
        "resolved_review_count": score.resolved_review_count,
        "score_blocking_reasons": list(score.blocking_reasons),
        "score_required_actions": list(score.required_actions),
        "score_limitations": list(score.limitations),
        "reconciliation_items": report_items,
        "citic_source_follow_up": citic_source_follow_up,
        "blockers": unique_blockers,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
    }


def _citic_source_follow_up_for_promotion(db_path: Path) -> dict[str, object]:
    """Return only sanitized, fail-closed source-review gate fields."""

    try:
        projection = build_citic_source_follow_up(db_path)
    except Exception:
        return {
            "schema_version": "karkinos.account_truth.citic_source_follow_up.v1",
            "status": "citic_source_follow_up_projection_failed",
            "pending_source_count": 0,
            "scanned_source_count": 0,
            "count_complete": False,
            "intake_scan_truncated": False,
            "evidence_fingerprint": "",
            "blockers": ["citic_source_follow_up_projection_failed"],
            "query_window_batch_integrity_status": "not_available",
            "query_window_batch_assessment_fingerprint": "",
            "query_window_gap_calendar_day_count": 0,
            "query_window_overlap_calendar_day_count": 0,
            "query_window_integrity_clear": False,
            "source_scope_batch_integrity_status": "not_available",
            "source_scope_batch_assessment_fingerprint": "",
            "source_scope_integrity_clear": False,
            "source_scope_account_binding_consistent": False,
            "source_scope_declared_scope_consistent": False,
            "source_scope_complete_returned_results_attested": False,
        }
    return {
        "schema_version": str(projection.get("schema_version") or ""),
        "status": str(projection.get("status") or "unavailable"),
        "pending_source_count": max(
            0,
            int(projection.get("pending_source_count") or 0),
        ),
        "scanned_source_count": max(
            0,
            int(projection.get("scanned_source_count") or 0),
        ),
        "count_complete": projection.get("count_complete") is True,
        "intake_scan_truncated": projection.get("intake_scan_truncated") is True,
        "evidence_fingerprint": str(projection.get("evidence_fingerprint") or ""),
        "blockers": [str(item) for item in projection.get("blockers") or []],
        "query_window_batch_integrity_status": str(
            projection.get("query_window_batch_integrity_status") or "not_available"
        ),
        "query_window_batch_assessment_fingerprint": str(
            projection.get("query_window_batch_assessment_fingerprint") or ""
        ),
        "query_window_gap_calendar_day_count": max(
            0,
            int(projection.get("query_window_gap_calendar_day_count") or 0),
        ),
        "query_window_overlap_calendar_day_count": max(
            0,
            int(projection.get("query_window_overlap_calendar_day_count") or 0),
        ),
        "query_window_integrity_clear": (
            projection.get("query_window_integrity_clear") is True
        ),
        "source_scope_batch_integrity_status": str(
            projection.get("source_scope_batch_integrity_status") or "not_available"
        ),
        "source_scope_batch_assessment_fingerprint": str(
            projection.get("source_scope_batch_assessment_fingerprint") or ""
        ),
        "source_scope_integrity_clear": (
            projection.get("source_scope_integrity_clear") is True
        ),
        "source_scope_account_binding_consistent": (
            projection.get("source_scope_account_binding_consistent") is True
        ),
        "source_scope_declared_scope_consistent": (
            projection.get("source_scope_declared_scope_consistent") is True
        ),
        "source_scope_complete_returned_results_attested": (
            projection.get("source_scope_complete_returned_results_attested") is True
        ),
    }


def build_account_truth_score_for_import_run(
    state: Any,
    *,
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
    data_freshness_status: str = "fresh",
) -> AccountTruthScore:
    """Reconcile one import run and build its account-truth score."""

    report = build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
    )
    db_path = _db_path_for_state(state)
    review_decisions = (
        ManualReviewRepository(db_path).list_decisions(import_run.import_run_id)
        if db_path is not None
        else []
    )
    effective_freshness = _freshness_with_ledger_coverage(
        data_freshness_status,
        _ledger_coverage_for_import(state, import_run),
    )
    return build_account_truth_score(
        report=report,
        review_decisions=review_decisions,
        data_freshness_status=effective_freshness,
    )


def build_reconciliation_report_for_import_run(
    state: Any,
    *,
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
) -> ReconciliationReport:
    """Build a reconciliation report for one staged broker evidence run."""

    return build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=broker_events_for_import_run(repository, import_run),
        **_karkinos_account_facts(state),
    )
