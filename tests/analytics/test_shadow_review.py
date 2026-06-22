"""Shadow review comparison evidence tests."""

from __future__ import annotations

from decimal import Decimal

from analytics.shadow_review import (
    SHADOW_REVIEW_SCHEMA_VERSION,
    PaperOutcomeEvidence,
    RealAccountMovementEvidence,
    StrategyCandidateEvidence,
    build_shadow_review_report,
)


def test_shadow_review_keeps_unlinked_real_movement_unattributed() -> None:
    report = build_shadow_review_report(
        candidates=[
            StrategyCandidateEvidence(
                candidate_id="candidate-001",
                strategy_id="dual_ma",
                symbol="TEST-STOCK",
                action="buy",
                quantity=Decimal("100"),
                reference_price=Decimal("10.00"),
                signal_id="signal-001",
                risk_decision_id="risk-001",
            )
        ],
        paper_outcomes=[
            PaperOutcomeEvidence(
                candidate_id="candidate-001",
                order_id="paper-order-001",
                strategy_id="dual_ma",
                symbol="TEST-STOCK",
                side="buy",
                status="filled",
                filled_quantity=Decimal("100"),
                average_fill_price=Decimal("10.01"),
                commission=Decimal("5.00"),
                slippage=Decimal("1.00"),
                fill_id="paper-fill-001",
            )
        ],
        real_movements=[
            RealAccountMovementEvidence(
                movement_id="ledger-fill-001",
                symbol="TEST-STOCK",
                quantity_delta=Decimal("100"),
                cash_delta=Decimal("-1006.00"),
                source="manual_ledger",
                source_ref="ledger-entry-001",
            )
        ],
    )

    assert report.schema_version == SHADOW_REVIEW_SCHEMA_VERSION
    assert report.does_not_mutate_account_facts is True
    assert report.supported_match_count == 0
    assert report.unsupported_real_movement_count == 1

    candidate_item = report.item_by_key("candidate:candidate-001")
    unsupported_item = report.item_by_key("real:ledger-fill-001")

    assert candidate_item.review_status == "paper_only"
    assert candidate_item.attributed_to_strategy is False
    assert candidate_item.attributed_strategy_id is None
    assert unsupported_item.review_status == "unsupported_real_movement"
    assert unsupported_item.attributed_to_strategy is False
    assert unsupported_item.attributed_strategy_id is None
    assert unsupported_item.suggested_action == "review_account_movement"
    assert "missing_explicit_strategy_link" in unsupported_item.limitations


def test_shadow_review_matches_strategy_only_when_explicit_refs_align() -> None:
    report = build_shadow_review_report(
        candidates=[
            StrategyCandidateEvidence(
                candidate_id="candidate-001",
                strategy_id="dual_ma",
                symbol="TEST-STOCK",
                action="buy",
                quantity=Decimal("100"),
                reference_price=Decimal("10.00"),
            )
        ],
        paper_outcomes=[
            PaperOutcomeEvidence(
                candidate_id="candidate-001",
                order_id="paper-order-001",
                strategy_id="dual_ma",
                symbol="TEST-STOCK",
                side="buy",
                status="filled",
                filled_quantity=Decimal("100"),
                average_fill_price=Decimal("10.01"),
                commission=Decimal("5.00"),
                slippage=Decimal("1.00"),
            )
        ],
        real_movements=[
            RealAccountMovementEvidence(
                movement_id="ledger-fill-001",
                symbol="TEST-STOCK",
                quantity_delta=Decimal("100"),
                cash_delta=Decimal("-1006.00"),
                source="broker_evidence",
                source_ref="broker-row-001",
                linked_candidate_id="candidate-001",
                linked_order_id="paper-order-001",
                linked_strategy_id="dual_ma",
            )
        ],
    )

    matched_item = report.item_by_key("candidate:candidate-001")
    payload = report.to_json_dict()

    assert report.supported_match_count == 1
    assert report.unsupported_real_movement_count == 0
    assert matched_item.review_status == "matched"
    assert matched_item.attributed_to_strategy is True
    assert matched_item.attributed_strategy_id == "dual_ma"
    assert matched_item.quantity_difference == Decimal("0")
    assert matched_item.cash_difference == Decimal("0.00")
    assert matched_item.suggested_action == "no_action_needed"
    assert payload["items"][0]["cash_difference"] == "0.00"
    assert payload["items"][0]["evidence_refs"] == {
        "candidate_id": "candidate-001",
        "paper_order_id": "paper-order-001",
        "real_movement_id": "ledger-fill-001",
        "strategy_id": "dual_ma",
    }
