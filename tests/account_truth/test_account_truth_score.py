from __future__ import annotations

from decimal import Decimal

from account_truth.manual_review import ManualReviewDecision
from account_truth.reconciliation import ReconciliationItem, ReconciliationReport
from account_truth.score import build_account_truth_score


def test_account_truth_score_passes_for_fresh_fully_reconciled_report() -> None:
    score = build_account_truth_score(
        report=_report(status="pass", items=[_item("cash", "pass")]),
        review_decisions=[],
        data_freshness_status="fresh",
    )

    assert score.schema_version == "karkinos.account_truth.score.v1"
    assert score.score == 100
    assert score.gate_status == "pass"
    assert score.cash_status == "pass"
    assert score.position_status == "pass"
    assert score.fee_status == "pass"
    assert score.cost_basis_status == "pass"
    assert score.data_freshness_status == "fresh"
    assert score.unresolved_mismatch_count == 0
    assert score.limitations == []
    assert score.to_json_dict()["score"] == 100


def test_account_truth_score_degrades_for_warning_and_stale_data() -> None:
    score = build_account_truth_score(
        report=_report(
            status="warning",
            items=[
                _item("cash", "warning", action="provide_cash_snapshot"),
                _item("position", "pass", symbol="SYN001"),
            ],
        ),
        review_decisions=[],
        data_freshness_status="stale",
    )

    assert score.score == 65
    assert score.gate_status == "degraded"
    assert score.cash_status == "warning"
    assert score.position_status == "pass"
    assert score.data_freshness_status == "stale"
    assert score.unresolved_mismatch_count == 1
    assert score.limitations == [
        "Account truth is degraded by stale account or market evidence.",
        "Unresolved reconciliation items require review before trusted use.",
    ]


def test_account_truth_score_blocks_for_unresolved_mismatches() -> None:
    score = build_account_truth_score(
        report=_report(
            status="mismatch",
            items=[
                _item("cash", "mismatch", action="review_cash_difference"),
                _item(
                    "position",
                    "mismatch",
                    symbol="SYN001",
                    action="review_position_difference",
                ),
                _item("fee", "mismatch", action="review_fee_difference"),
                _item(
                    "cost_basis",
                    "mismatch",
                    symbol="SYN001",
                    action="review_cost_basis_difference",
                ),
            ],
        ),
        review_decisions=[
            _decision("import_synthetic", "cash", "accepted"),
            _decision("import_synthetic", "position:SYN001", "needs_investigation"),
            _decision("import_synthetic", "fee", "known_difference"),
            _decision("import_synthetic", "cost_basis:SYN001", "ledger_candidate"),
        ],
        data_freshness_status="fresh",
    )

    assert score.score == 40
    assert score.gate_status == "blocked"
    assert score.unresolved_mismatch_count == 2
    assert score.resolved_review_count == 2
    assert score.blocking_reasons == [
        "unresolved_position_difference",
        "unresolved_cost_basis_difference",
    ]
    assert "review_position_difference" in score.required_actions
    assert "review_cost_basis_difference" in score.required_actions


def test_account_truth_score_blocks_when_report_is_blocked() -> None:
    score = build_account_truth_score(
        report=_report(
            status="blocked",
            items=[_item("import", "blocked", action="import_broker_evidence")],
        ),
        review_decisions=[],
        data_freshness_status="missing",
    )

    assert score.score == 0
    assert score.gate_status == "blocked"
    assert score.unresolved_mismatch_count == 1
    assert score.blocking_reasons == [
        "blocked_reconciliation_report",
        "missing_account_or_market_evidence",
        "unresolved_import_difference",
    ]


def _report(
    *,
    status: str,
    items: list[ReconciliationItem],
) -> ReconciliationReport:
    return ReconciliationReport(
        schema_version="karkinos.account_truth.reconciliation.v1",
        import_run_id="import_synthetic",
        status=status,  # type: ignore[arg-type]
        cash_difference=Decimal("0"),
        fee_difference=Decimal("0"),
        tax_difference=Decimal("0"),
        unresolved_count=sum(1 for item in items if item.status != "pass"),
        suggested_review_actions=[
            item.suggested_review_action
            for item in items
            if item.suggested_review_action
        ],
        items=items,
    )


def _item(
    category: str,
    status: str,
    *,
    symbol: str = "",
    action: str = "",
) -> ReconciliationItem:
    return ReconciliationItem(
        category=category,
        status=status,  # type: ignore[arg-type]
        broker_value="0",
        karkinos_value="0",
        difference="0",
        suggested_review_action=action,
        symbol=symbol,
        detail="synthetic item",
    )


def _decision(
    import_run_id: str,
    item_key: str,
    review_status: str,
) -> ManualReviewDecision:
    return ManualReviewDecision(
        id=1,
        import_run_id=import_run_id,
        item_key=item_key,
        category=item_key.split(":", 1)[0],
        symbol=item_key.split(":", 1)[1] if ":" in item_key else "",
        review_status=review_status,  # type: ignore[arg-type]
        note="synthetic review",
        reviewer="local",
        schema_version="karkinos.account_truth.manual_review.v1",
        created_at="2026-06-17T00:00:00+00:00",
        updated_at="2026-06-17T00:00:00+00:00",
    )
