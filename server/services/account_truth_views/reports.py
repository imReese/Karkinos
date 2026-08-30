"""Canonical account_truth reports projections."""

from __future__ import annotations

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from account_truth.broker_statement import (
    BrokerEvidenceEvent,
    BrokerStatementValidationError,
)
from account_truth.manual_review import (
    ManualReviewDecision,
)
from account_truth.reconciliation import (
    ReconciliationItem,
    ReconciliationReport,
)
from account_truth.score import reconciliation_item_fingerprint
from server.account_truth_gate import (
    broker_events_for_import_run,
)
from server.services.account_truth_views.repositories import (
    manual_review_repository_for_state,
)


def preview_error_response(
    error: BrokerStatementValidationError,
) -> dict[str, object]:
    return {
        "row_number": error.row_number,
        "code": error.code,
        "message": error.message,
    }


def preview_event_response(event: BrokerEvidenceEvent) -> dict[str, object]:
    return {
        "row_number": event.row_number,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "settled_at": event.settled_at,
        "symbol": event.symbol,
        "instrument_name": event.instrument_name,
        "asset_class": event.asset_class,
        "currency": event.currency,
        "quantity": str(event.quantity),
        "price": str(event.price),
        "gross_amount": str(event.gross_amount),
        "fee": str(event.fee),
        "tax": str(event.tax),
        "net_amount": str(event.net_amount),
        "cash_balance": (
            str(event.cash_balance) if event.cash_balance is not None else None
        ),
        "position_quantity": (
            str(event.position_quantity)
            if event.position_quantity is not None
            else None
        ),
        "cost_basis": str(event.cost_basis) if event.cost_basis is not None else None,
        "is_duplicate": event.is_duplicate,
    }


def report_summary_response(
    import_run: BrokerImportRun,
    report: ReconciliationReport,
) -> dict[str, object]:
    return {
        "import_run_id": report.import_run_id,
        "schema_version": report.schema_version,
        "status": report.status,
        "row_count": import_run.row_count,
        "validation_status": import_run.validation_status,
        "source_type": import_run.source_type,
        "source_name": import_run.source_name,
        "created_at": import_run.created_at,
        "unresolved_count": report.unresolved_count,
        "cash_difference": str(report.cash_difference),
        "fee_difference": str(report.fee_difference),
        "tax_difference": str(report.tax_difference),
        "suggested_review_actions": list(report.suggested_review_actions),
        "asset_reconciliation": {
            lane: dict(summary) for lane, summary in report.asset_reconciliation.items()
        },
        "limitations": list(import_run.limitations),
    }


def report_detail_response(
    import_run: BrokerImportRun,
    report: ReconciliationReport,
    repository: BrokerEvidenceRepository,
    state,
) -> dict[str, object]:
    events = broker_events_for_import_run(repository, import_run)
    review_decisions = manual_review_repository_for_state(state).list_decisions(
        import_run.import_run_id
    )
    review_by_item = {decision.item_key: decision for decision in review_decisions}
    return {
        **report_summary_response(import_run, report),
        "items": [
            item_response(item, events, review_by_item.get(item_key(item)))
            for item in report.items
        ],
    }


def item_response(
    item: ReconciliationItem,
    events: list[StoredBrokerEvidenceEvent],
    latest_review: ManualReviewDecision | None = None,
) -> dict[str, object]:
    return {
        "item_key": item_key(item),
        "category": item.category,
        "status": item.status,
        "severity": item.status,
        "symbol": item.symbol,
        "asset_class": item.asset_class,
        "display_name": display_name_for_item(item, events),
        "broker_value": item.broker_value,
        "karkinos_value": item.karkinos_value,
        "difference": item.difference,
        "suggested_review_action": item.suggested_review_action,
        "detail_code": item.detail_code,
        "detail": item.detail,
        "detail_context": dict(item.detail_context),
        "evidence_references": evidence_references(item, events),
        "evidence_fingerprint": reconciliation_item_fingerprint(item),
        "latest_review": (
            {
                **decision_response(latest_review),
                "is_current": latest_review.evidence_fingerprint
                == reconciliation_item_fingerprint(item),
            }
            if latest_review is not None
            else None
        ),
        "manual_review_does_not_override_mismatch": True,
    }


def display_name_for_item(
    item: ReconciliationItem,
    events: list[StoredBrokerEvidenceEvent],
) -> str | None:
    if not item.symbol:
        return None
    for event in events:
        if event.symbol == item.symbol and event.instrument_name.strip():
            return event.instrument_name
    return None


def evidence_references(
    item: ReconciliationItem,
    events: list[StoredBrokerEvidenceEvent],
) -> list[str]:
    if item.category == "position" and item.symbol:
        return [
            f"broker_event:{event.import_run_id}:{event.symbol}:{event.event_type}"
            for event in events
            if event.symbol == item.symbol and event.event_type == "position_snapshot"
        ]
    if item.category == "cash":
        return [
            f"broker_event:{event.import_run_id}:cash:{event.event_type}"
            for event in events
            if event.event_type == "cash_snapshot"
        ]
    if item.category in {
        "trade_gross_amount",
        "net_cash_impact",
        "fee",
        "tax",
        "transfer_fee",
        "cost_basis",
    }:
        event_types = (
            {"trade_buy", "trade_sell"}
            if item.category
            in {"trade_gross_amount", "net_cash_impact", "transfer_fee"}
            else {item.category, "position_snapshot", "trade_buy", "trade_sell"}
        )
        return [
            f"broker_event:{event.import_run_id}:{event.symbol or item.category}:{event.event_type}"
            for event in events
            if event.event_type in event_types
            and (not item.symbol or event.symbol == item.symbol)
        ]
    return []


def item_key(item: ReconciliationItem) -> str:
    if item.symbol:
        return f"{item.category}:{item.symbol}"
    return item.category


def decision_response(decision: ManualReviewDecision) -> dict[str, object]:
    return {
        "id": decision.id,
        "import_run_id": decision.import_run_id,
        "item_key": decision.item_key,
        "category": decision.category,
        "symbol": decision.symbol,
        "review_status": decision.review_status,
        "note": decision.note,
        "reviewer": decision.reviewer,
        "evidence_fingerprint": decision.evidence_fingerprint,
        "schema_version": decision.schema_version,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
        "does_not_mutate_production_ledger": True,
    }


__all__ = (
    "decision_response",
    "display_name_for_item",
    "evidence_references",
    "item_key",
    "item_response",
    "preview_error_response",
    "preview_event_response",
    "report_detail_response",
    "report_summary_response",
)
