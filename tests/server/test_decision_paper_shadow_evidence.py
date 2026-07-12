from __future__ import annotations

import json

from server.routes.decision import _paper_shadow_evidence


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
