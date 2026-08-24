from __future__ import annotations

import json

from server.services.decision_application import (
    paper_shadow_allows_manual_ticket as _paper_shadow_allows_manual_ticket,
)
from server.services.decision_application import (
    paper_shadow_evidence as _paper_shadow_evidence,
)


def test_decision_attaches_matching_persisted_paper_shadow_evidence() -> None:
    class FakeDb:
        def latest_paper_shadow_run_sync(self, plan_date: str):
            assert plan_date == "2026-07-10"
            return {
                "run_id": "shadow:2026-07-10:fixture",
                "input_fingerprint": "fixture-fingerprint",
                "divergence_status": "within_expectations",
                "review_status": None,
                "payload_json": json.dumps(
                    {
                        "orders": [
                            {
                                "order_id": "SHADOW-FIXTURE-1",
                                "divergence_status": "within_expectations",
                                "order_intent": {"action_ref": "action:7"},
                            }
                        ]
                    }
                ),
            }

    evidence = _paper_shadow_evidence(
        {"id": 7, "timestamp": "2026-07-10T14:57:03+08:00"},
        "ready_for_manual_confirmation",
        db=FakeDb(),
    )

    assert evidence["status"] == "pass"
    assert evidence["has_evidence"] is True
    assert evidence["execution_mode"] == "paper_shadow"
    assert evidence["run_id"] == "shadow:2026-07-10:fixture"
    assert evidence["order_id"] == "SHADOW-FIXTURE-1"
    assert evidence["blocking_reasons"] == []
    assert evidence["required_actions"] == []
    assert _paper_shadow_allows_manual_ticket(evidence) is True


def test_decision_does_not_attach_unmatched_paper_shadow_run() -> None:
    class FakeDb:
        def latest_paper_shadow_run_sync(self, plan_date: str):
            return {
                "run_id": "shadow:2026-07-10:other",
                "divergence_status": "within_expectations",
                "payload_json": json.dumps(
                    {
                        "orders": [
                            {
                                "order_id": "SHADOW-OTHER",
                                "divergence_status": "within_expectations",
                                "order_intent": {"action_ref": "action:99"},
                            }
                        ]
                    }
                ),
            }

    evidence = _paper_shadow_evidence(
        {"id": 7, "timestamp": "2026-07-10T14:57:03+08:00"},
        "ready_for_manual_confirmation",
        db=FakeDb(),
    )

    assert evidence["status"] == "review_required"
    assert evidence["has_evidence"] is False
    assert evidence["order_id"] is None
    assert _paper_shadow_allows_manual_ticket(evidence) is False


def test_manual_ticket_rejects_label_only_shadow_pass_without_exact_run_binding() -> (
    None
):
    evidence = _paper_shadow_evidence(
        {
            "id": 7,
            "timestamp": "2026-07-10T14:57:03+08:00",
            "paper_shadow_status": "pass",
            "paper_shadow_order_id": "unbound-order",
        },
        "ready_for_manual_confirmation",
        db=object(),
    )

    assert evidence["status"] == "pass"
    assert evidence["has_evidence"] is True
    assert evidence["run_id"] is None
    assert evidence["input_fingerprint"] is None
    assert _paper_shadow_allows_manual_ticket(evidence) is False
