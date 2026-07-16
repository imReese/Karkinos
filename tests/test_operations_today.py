from __future__ import annotations

from server.models import DailyOperationsSummary
from server.services.operations_today import build_operations_today_summary


def _operations(manual_ready_count: int = 1) -> DailyOperationsSummary:
    return DailyOperationsSummary(
        candidate_pool_count=1,
        evidence_passed_count=1,
        risk_checked_count=1,
        risk_passed_count=1,
        risk_blocked_count=0,
        paper_shadow_review_count=1,
        manual_ready_count=manual_ready_count,
        pending_manual_order_count=0,
        execution_record_count=0,
        fill_record_count=0,
        ledger_review_count=0,
        execution_exception_count=0,
        default_execution_mode="manual_confirmation",
        broker_bridge_status="disabled",
        conclusion_status="pending_manual_confirmation",
        primary_target="trading",
        limitations=[],
    )


def _decision() -> dict:
    return {
        "decision_date": "2026-07-01",
        "generated_at": "2026-07-01T09:31:00+08:00",
        "summary": {
            "candidate_count": 1,
            "market_data": {
                "source_health": "live",
                "latest_quote_timestamp": "2026-07-01T09:30:00+08:00",
            },
            "account_truth": {"gate_status": "pass", "limitations": []},
        },
        "candidates": [],
    }


def _plan(order_intent_count: int = 1) -> dict:
    return {
        "plan_date": "2026-07-01",
        "generated_at": "2026-07-01T09:31:30+08:00",
        "conclusion_status": "manual_confirmation_ready",
        "candidate_pool_count": 1,
        "manual_ready_count": 1,
        "blocked_count": 0,
        "order_intent_count": order_intent_count,
        "limitations": [
            "Order intents are manual-confirmation previews, not broker submissions."
        ],
    }


def test_operations_today_requires_shadow_run_for_order_intents() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        generated_at="2026-07-01T09:32:00+08:00",
    )

    assert summary["conclusion_status"] == "manual_action_required"
    assert summary["primary_target"] == "paper-shadow"
    assert summary["daily_plan"]["order_intent_count"] == 1
    assert summary["paper_shadow"]["status"] == "not_run"
    assert summary["paper_shadow"]["next_manual_review_step"] == (
        "run_paper_shadow_daily"
    )
    assert summary["health"]["manual_action_required"] == 2


def test_operations_today_projects_the_canonical_daily_operations_summary() -> None:
    daily_operations = _operations(manual_ready_count=0).model_copy(
        update={
            "candidate_pool_count": 0,
            "conclusion_status": "no_manual_action",
            "primary_target": "decision",
        }
    )

    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan={
            **_plan(order_intent_count=0),
            "candidate_pool_count": 0,
            "manual_ready_count": 0,
            "conclusion_status": "no_manual_action",
        },
        daily_operations=daily_operations,
        order_facts=[],
        fill_facts=[],
        generated_at="2026-07-01T09:32:00+08:00",
    )

    assert summary["daily_operations"] == daily_operations.model_dump()


def test_operations_today_treats_no_manual_action_scheduler_as_skipped() -> None:
    no_action_operations = _operations(manual_ready_count=0).model_copy(
        update={
            "candidate_pool_count": 0,
            "evidence_passed_count": 0,
            "risk_checked_count": 0,
            "risk_passed_count": 0,
            "paper_shadow_review_count": 0,
            "conclusion_status": "no_manual_action",
            "primary_target": "decision",
        }
    )
    summary = build_operations_today_summary(
        decision_payload={
            **_decision(),
            "summary": {
                **_decision()["summary"],
                "candidate_count": 0,
            },
        },
        trading_plan={
            **_plan(order_intent_count=0),
            "candidate_pool_count": 0,
            "manual_ready_count": 0,
            "conclusion_status": "no_manual_action",
        },
        daily_operations=no_action_operations,
        order_facts=[],
        fill_facts=[],
        automation_runs=[],
        generated_at="2026-07-01T09:32:00+08:00",
    )

    subsystem = next(
        item for item in summary["subsystems"] if item["id"] == "scheduler"
    )

    assert summary["scheduler"]["status"] == "no_manual_action"
    assert subsystem["status"] == "skipped"
    assert subsystem["next_action"] == "none"
    assert summary["health"]["degraded"] == 0
    assert summary["conclusion_status"] == "healthy"


def test_operations_today_acceptance_audit_subsystem_uses_audit_export() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan={
            **_plan(order_intent_count=0),
            "manual_ready_count": 0,
            "conclusion_status": "no_manual_action",
        },
        daily_operations=_operations(manual_ready_count=0),
        order_facts=[],
        fill_facts=[],
        generated_at="2026-07-01T09:32:00+08:00",
        acceptance_audit_export={
            "generated_at": "2026-07-01T09:30:00Z",
            "selected_audit": "operations_runbook",
            "overall_is_complete": True,
            "audits": [
                {
                    "key": "operations_runbook",
                    "required_count": 19,
                    "completed_count": 19,
                    "is_complete": True,
                    "limitations": [
                        "Completion does not enable automatic real-money trading; manual confirmation remains the live-like default."
                    ],
                }
            ],
        },
    )

    audit = next(
        item for item in summary["subsystems"] if item["id"] == "acceptance_audit"
    )
    assert audit["status"] == "pass"
    assert audit["last_run_at"] == "2026-07-01T09:30:00Z"
    assert audit["next_action"] == "none"
    assert audit["detail_status"] == "operations_runbook:19/19"
    assert audit["limitations"] == [
        "Completion does not enable automatic real-money trading; manual confirmation remains the live-like default."
    ]


def test_operations_today_surfaces_broker_adapter_evidence_without_activation() -> None:
    readiness = {
        "schema_version": "karkinos.broker_adapter_readiness.v1",
        "status": "evidence_ready_not_activated",
        "subsystem_status": "skipped",
        "next_manual_action": (
            "obtain_explicit_owner_authorization_before_adapter_activation"
        ),
        "latest_release": {
            "collector_updated_at": None,
        },
        "limitations": ["Persisted evidence only; no provider contact."],
    }
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan={
            **_plan(order_intent_count=0),
            "manual_ready_count": 0,
            "conclusion_status": "no_manual_action",
        },
        daily_operations=_operations(manual_ready_count=0),
        order_facts=[],
        fill_facts=[],
        broker_adapter_readiness=readiness,
        generated_at="2026-07-01T09:32:00+08:00",
    )

    subsystem = next(
        item
        for item in summary["subsystems"]
        if item["id"] == "broker_adapter_evidence"
    )
    assert summary["broker_adapter_readiness"] == readiness
    assert subsystem == {
        "id": "broker_adapter_evidence",
        "status": "skipped",
        "tone": "neutral",
        "target": "account-truth",
        "last_run_at": None,
        "next_action": (
            "obtain_explicit_owner_authorization_before_adapter_activation"
        ),
        "limitations": ["Persisted evidence only; no provider contact."],
        "detail_status": "evidence_ready_not_activated",
    }


def test_operations_today_surfaces_manual_execution_reconciliation_review() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan={
            **_plan(order_intent_count=0),
            "manual_ready_count": 0,
            "conclusion_status": "no_manual_action",
        },
        daily_operations=_operations(manual_ready_count=0),
        order_facts=[],
        fill_facts=[],
        execution_reconciliation_open_items=[
            {
                "order_id": "MANUAL-001",
                "item_status": "manual_execution_recorded",
                "suggested_action": (
                    "review_manual_execution_and_import_broker_statement"
                ),
                "detail": (
                    "Manual execution evidence is recorded; import broker "
                    "statement before ledger update."
                ),
                "created_at": "2026-07-01T10:10:00+08:00",
                "payload_json": {
                    "manual_execution_evidence_summary": {
                        "preview_fingerprint": "preview:abc123",
                        "submitted_to_broker": False,
                        "does_not_mutate_oms": True,
                        "does_not_mutate_production_ledger": True,
                    }
                },
            }
        ],
        generated_at="2026-07-01T10:12:00+08:00",
    )

    reconciliation = summary["execution_reconciliation"]
    assert summary["conclusion_status"] == "manual_action_required"
    assert summary["primary_target"] == "decision"
    assert reconciliation["status"] == "manual_action_required"
    assert reconciliation["open_item_count"] == 1
    assert reconciliation["manual_execution_review_count"] == 1
    assert reconciliation["next_review_step"] == (
        "review_manual_execution_and_import_broker_statement"
    )
    assert reconciliation["first_open_item"] == {
        "order_id": "MANUAL-001",
        "item_status": "manual_execution_recorded",
        "suggested_action": "review_manual_execution_and_import_broker_statement",
        "detail": (
            "Manual execution evidence is recorded; import broker statement "
            "before ledger update."
        ),
        "manual_execution_evidence_summary": {
            "preview_fingerprint": "preview:abc123",
            "submitted_to_broker": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
        },
    }
    assert reconciliation["does_not_submit_broker_order"] is True
    assert reconciliation["does_not_mutate_oms"] is True
    assert reconciliation["does_not_mutate_production_ledger"] is True
    subsystem = next(
        item
        for item in summary["subsystems"]
        if item["id"] == "execution_reconciliation"
    )
    assert subsystem["status"] == "manual_action_required"
    assert subsystem["next_action"] == (
        "review_manual_execution_and_import_broker_statement"
    )
    assert subsystem["detail_status"] == "manual_execution_recorded:1"


def test_operations_today_prioritizes_unknown_controlled_submission() -> None:
    controlled_summary = {
        "schema_version": "karkinos.controlled_submission_reconciliation.v1",
        "submit_intent_id": "a" * 64,
        "client_order_id": "KARK-controlled-1",
        "intent_status": "submission_unknown",
        "new_submissions_blocked": True,
        "recovery_resubmission_enabled": False,
        "does_not_mutate_production_ledger": True,
    }
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan={
            **_plan(order_intent_count=0),
            "manual_ready_count": 0,
            "conclusion_status": "no_manual_action",
        },
        daily_operations=_operations(manual_ready_count=0),
        order_facts=[],
        fill_facts=[],
        execution_reconciliation_open_items=[
            {
                "order_id": "OMS-CONTROLLED-1",
                "item_status": "controlled_submission_unknown",
                "suggested_action": "recover_controlled_submission_by_query",
                "detail": "Outcome unknown; query only and never resubmit.",
                "created_at": "2026-07-13T10:00:00+08:00",
                "payload_json": {
                    "controlled_submission_evidence_summary": controlled_summary,
                },
            }
        ],
        generated_at="2026-07-13T10:01:00+08:00",
    )

    reconciliation = summary["execution_reconciliation"]
    assert summary["conclusion_status"] == "manual_action_required"
    assert reconciliation["controlled_submission_review_count"] == 1
    assert reconciliation["controlled_submission_unknown_count"] == 1
    assert reconciliation["next_review_step"] == (
        "recover_controlled_submission_by_query"
    )
    assert reconciliation["detail_status"] == "controlled_submission_unknown:1"
    assert (
        reconciliation["first_open_item"]["controlled_submission_evidence_summary"]
        == controlled_summary
    )
    subsystem = next(
        item
        for item in summary["subsystems"]
        if item["id"] == "execution_reconciliation"
    )
    assert subsystem["next_action"] == "recover_controlled_submission_by_query"
    assert subsystem["detail_status"] == "controlled_submission_unknown:1"


def test_operations_today_requires_shadow_divergence_review() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[
            {
                "order_id": "SHADOW-2026-07-01-7",
                "symbol": "600519",
                "status": "shadow_recorded",
                "execution_mode": "paper_shadow",
                "payload_json": '{"run_id": "shadow:2026-07-01"}',
                "timestamp": "2026-07-01T09:33:00+08:00",
            }
        ],
        fill_facts=[],
    )

    assert summary["paper_shadow"]["status"] == "review_required"
    assert summary["paper_shadow"]["simulated_order_count"] == 1
    assert summary["paper_shadow"]["divergence_reviewed_count"] == 0
    assert summary["paper_shadow"]["next_manual_review_step"] == (
        "review_shadow_divergence"
    )


def test_operations_today_marks_shadow_review_within_expectations() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[
            {
                "order_id": "SHADOW-2026-07-01-7",
                "symbol": "600519",
                "status": "shadow_recorded",
                "execution_mode": "paper_shadow",
                "payload_json": (
                    '{"run_id": "shadow:2026-07-01", '
                    '"divergence_status": "within_expectations"}'
                ),
                "updated_at": "2026-07-01T09:35:00+08:00",
            }
        ],
        fill_facts=[
            {
                "fill_id": "FILL-1",
                "order_id": "SHADOW-2026-07-01-7",
                "execution_mode": "paper_shadow",
                "timestamp": "2026-07-01T09:34:00+08:00",
            }
        ],
    )

    assert summary["paper_shadow"]["status"] == "within_expectations"
    assert summary["paper_shadow"]["simulated_fill_count"] == 1
    assert summary["paper_shadow"]["divergence_reviewed_count"] == 1
    assert summary["paper_shadow"]["next_manual_review_step"] == (
        "review_manual_confirmation"
    )


def test_operations_today_prefers_persisted_paper_shadow_run() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:abc123",
            "plan_date": "2026-07-01",
            "input_fingerprint": "abc123",
            "status": "within_expectations",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 1,
            "divergence_status": "within_expectations",
            "next_manual_review_step": "review_manual_confirmation",
            "limitations_json": "[]",
            "payload_json": (
                '{"input_snapshot": {"schema_version": '
                '"karkinos.paper_shadow_run.input_snapshot.v1", '
                '"plan_date": "2026-07-01", '
                '"input_fingerprint": "abc123", '
                '"order_intent_count": 1, '
                '"does_not_submit_broker_order": true, '
                '"does_not_mutate_production_ledger": true}, '
                '"orders": [{"order_id": "SHADOW-1"}]}'
            ),
            "updated_at": "2026-07-01T09:36:00+08:00",
        },
    )

    assert summary["paper_shadow"]["run_id"] == "shadow:2026-07-01:abc123"
    assert summary["paper_shadow"]["status"] == "within_expectations"
    assert summary["paper_shadow"]["input_fingerprint"] == "abc123"
    assert summary["paper_shadow"]["input_snapshot"] == {
        "schema_version": "karkinos.paper_shadow_run.input_snapshot.v1",
        "plan_date": "2026-07-01",
        "input_fingerprint": "abc123",
        "order_intent_count": 1,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    assert summary["paper_shadow"]["simulated_order_count"] == 1
    assert summary["paper_shadow"]["simulated_fill_count"] == 1
    assert summary["paper_shadow"]["last_run_at"] == "2026-07-01T09:36:00+08:00"


def test_operations_today_marks_failed_paper_shadow_run_as_blocked() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:failed",
            "plan_date": "2026-07-01",
            "input_fingerprint": "failed",
            "status": "failed",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 0,
            "divergence_status": "failed",
            "next_manual_review_step": "inspect_failed_run",
            "limitations_json": ('["Paper/shadow simulation failed: fixture error"]'),
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"status": "failed", "divergence_status": "failed"}]}'
            ),
            "updated_at": "2026-07-01T09:36:00+08:00",
        },
    )

    subsystem = next(
        item for item in summary["subsystems"] if item["id"] == "paper_shadow"
    )

    assert summary["paper_shadow"]["status"] == "failed"
    assert summary["paper_shadow"]["limitations"] == [
        "Paper/shadow simulation failed: fixture error"
    ]
    assert summary["paper_shadow"]["next_manual_review_step"] == "inspect_failed_run"
    assert summary["conclusion_status"] == "blocked"
    assert summary["primary_target"] == "paper-shadow"
    assert summary["health"]["blocked"] >= 1
    assert subsystem["status"] == "blocked"
    assert subsystem["next_action"] == "inspect_failed_run"
    assert "Paper/shadow simulation failed: fixture error" in subsystem["limitations"]


def test_operations_today_surfaces_paper_shadow_review_queue() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:partial",
            "plan_date": "2026-07-01",
            "input_fingerprint": "partial",
            "status": "diverged",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 1,
            "divergence_status": "diverged",
            "next_manual_review_step": "resolve_shadow_divergence",
            "limitations_json": "[]",
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"status": "partially_filled", '
                '"divergence_status": "diverged"}], '
                '"review_queue": [{"review_id": "shadow:2026-07-01:partial:ACTION-1", '
                '"order_intent_ref": "action:ACTION-1", '
                '"order_id": "SHADOW-1", "symbol": "600519", '
                '"status": "partially_filled", '
                '"divergence_status": "diverged", '
                '"severity": "warning", '
                '"required_action": "resolve_shadow_divergence", '
                '"reason": "Paper/shadow order partially_filled; compare simulated execution with the original order intent before manual confirmation.", '
                '"does_not_submit_broker_order": true, '
                '"does_not_mutate_production_ledger": true}]}'
            ),
            "updated_at": "2026-07-01T09:36:00+08:00",
        },
    )

    assert summary["paper_shadow"]["review_queue"] == [
        {
            "review_id": "shadow:2026-07-01:partial:ACTION-1",
            "order_intent_ref": "action:ACTION-1",
            "order_id": "SHADOW-1",
            "symbol": "600519",
            "status": "partially_filled",
            "divergence_status": "diverged",
            "severity": "warning",
            "required_action": "resolve_shadow_divergence",
            "reason": "Paper/shadow order partially_filled; compare simulated execution with the original order intent before manual confirmation.",
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
    ]


def test_operations_today_blocks_manual_handoff_until_shadow_review_is_accepted() -> (
    None
):
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:partial",
            "plan_date": "2026-07-01",
            "input_fingerprint": "partial",
            "status": "diverged",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 1,
            "divergence_status": "diverged",
            "next_manual_review_step": "resolve_shadow_divergence",
            "limitations_json": "[]",
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"symbol": "600519", '
                '"status": "partially_filled", '
                '"divergence_status": "diverged"}], '
                '"review_queue": [{"review_id": "shadow:2026-07-01:partial:ACTION-1", '
                '"order_intent_ref": "action:ACTION-1", '
                '"order_id": "SHADOW-1", '
                '"symbol": "600519", '
                '"status": "partially_filled", '
                '"divergence_status": "diverged", '
                '"severity": "warning", '
                '"required_action": "resolve_shadow_divergence", '
                '"reason": "Review before handoff.", '
                '"does_not_submit_broker_order": true, '
                '"does_not_mutate_production_ledger": true}]}'
            ),
            "updated_at": "2026-07-01T09:36:00+08:00",
        },
    )

    assert summary["paper_shadow"]["manual_handoff"] == {
        "ready": False,
        "status": "blocked_by_unresolved_divergence",
        "blockers": ["unresolved_paper_shadow_divergence"],
        "required_actions": ["resolve_shadow_divergence"],
        "review_queue_count": 1,
        "highest_severity": "warning",
        "review_status": None,
        "reviewed_at": None,
        "reviewer": None,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def test_operations_today_marks_accepted_shadow_divergence_ready_for_handoff() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:diverged",
            "plan_date": "2026-07-01",
            "input_fingerprint": "diverged",
            "status": "diverged",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 0,
            "divergence_status": "diverged",
            "next_manual_review_step": "resolve_shadow_divergence",
            "review_status": "accepted_for_manual_confirmation",
            "reviewed_at": "2026-07-01T10:10:00+08:00",
            "reviewer": "local-operator",
            "limitations_json": "[]",
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"symbol": "600519", '
                '"status": "partially_filled", '
                '"divergence_status": "diverged"}], '
                '"review": {"review_status": '
                '"accepted_for_manual_confirmation"}}'
            ),
            "updated_at": "2026-07-01T10:10:00+08:00",
        },
    )

    assert summary["paper_shadow"]["manual_handoff"] == {
        "ready": True,
        "status": "ready_after_accepted_review",
        "blockers": [],
        "required_actions": ["review_manual_confirmation"],
        "review_queue_count": 1,
        "highest_severity": "warning",
        "review_status": "accepted_for_manual_confirmation",
        "reviewed_at": "2026-07-01T10:10:00+08:00",
        "reviewer": "local-operator",
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def test_operations_today_synthesizes_review_queue_for_legacy_diverged_run() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:legacy",
            "plan_date": "2026-07-01",
            "input_fingerprint": "legacy",
            "status": "diverged",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 1,
            "divergence_status": "diverged",
            "next_manual_review_step": "resolve_shadow_divergence",
            "limitations_json": "[]",
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"symbol": "600519", '
                '"status": "partially_filled", '
                '"divergence_status": "diverged", '
                '"filled_quantity": "40", '
                '"remaining_quantity": "60", '
                '"order_intent": {"action_ref": "action:ACTION-1"}}]}'
            ),
            "updated_at": "2026-07-01T09:36:00+08:00",
        },
    )

    assert summary["paper_shadow"]["review_queue"] == [
        {
            "review_id": "shadow:2026-07-01:legacy:ACTION-1",
            "order_intent_ref": "action:ACTION-1",
            "order_id": "SHADOW-1",
            "symbol": "600519",
            "status": "partially_filled",
            "divergence_status": "diverged",
            "severity": "warning",
            "required_action": "resolve_shadow_divergence",
            "reason": (
                "Paper/shadow order partially_filled requires divergence review "
                "before manual confirmation."
            ),
            "filled_quantity": "40",
            "remaining_quantity": "60",
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
    ]


def test_operations_today_synthesizes_oms_evidence_for_legacy_review_queue() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:legacy-oms",
            "plan_date": "2026-07-01",
            "input_fingerprint": "legacy-oms",
            "status": "diverged",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 0,
            "divergence_status": "diverged",
            "next_manual_review_step": "resolve_shadow_divergence",
            "limitations_json": "[]",
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"symbol": "600519", '
                '"status": "cancelled", '
                '"divergence_status": "diverged", '
                '"filled_quantity": "0", '
                '"remaining_quantity": "100", '
                '"order_intent": {"action_ref": "action:ACTION-1"}, '
                '"oms_transitions": ['
                '{"sequence": 1, "from_status": null, '
                '"to_status": "staged", "source": "paper_shadow_daily", '
                '"reason": "", "filled_quantity": "0"}, '
                '{"sequence": 2, "from_status": "staged", '
                '"to_status": "submitted", "source": "paper_shadow_daily", '
                '"reason": "", "filled_quantity": "0"}, '
                '{"sequence": 3, "from_status": "submitted", '
                '"to_status": "cancelled", "source": "paper_shadow_daily", '
                '"reason": "operator_cancelled", "filled_quantity": "0"}]}]}'
            ),
            "updated_at": "2026-07-01T09:36:00+08:00",
        },
    )

    item = summary["paper_shadow"]["review_queue"][0]

    assert item["evidence_refs"] == [
        "action:ACTION-1",
        "paper_order:SHADOW-1",
        "oms_transition:SHADOW-1:1:staged",
        "oms_transition:SHADOW-1:2:submitted",
        "oms_transition:SHADOW-1:3:cancelled",
    ]
    assert item["oms_status_path"] == ["staged", "submitted", "cancelled"]
    assert item["oms_transition_refs"] == [
        "oms_transition:SHADOW-1:1:staged",
        "oms_transition:SHADOW-1:2:submitted",
        "oms_transition:SHADOW-1:3:cancelled",
    ]
    assert item["terminal_status"] == "cancelled"
    assert item["terminal_reason"] == "operator_cancelled"
    assert item["terminal_oms_transition_ref"] == (
        "oms_transition:SHADOW-1:3:cancelled"
    )
    assert item["oms_transitions"][-1] == {
        "sequence": 3,
        "from_status": "submitted",
        "to_status": "cancelled",
        "source": "paper_shadow_daily",
        "reason": "operator_cancelled",
        "filled_quantity": "0",
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    assert item["does_not_submit_broker_order"] is True
    assert item["does_not_mutate_production_ledger"] is True


def test_operations_today_synthesizes_review_queue_for_missing_simulation() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:missing",
            "plan_date": "2026-07-01",
            "input_fingerprint": "missing",
            "status": "review_required",
            "order_intent_count": 1,
            "simulated_order_count": 0,
            "simulated_fill_count": 0,
            "divergence_status": "review_required",
            "next_manual_review_step": "review_shadow_divergence",
            "limitations_json": '["order_intent[1] missing estimated_price"]',
            "payload_json": (
                '{"divergence_summary": {"execution_comparison": '
                '{"missing_order_intent_refs": ["action:ACTION-1"]}}}'
            ),
            "updated_at": "2026-07-01T09:36:00+08:00",
        },
    )

    assert summary["paper_shadow"]["review_queue"] == [
        {
            "review_id": "shadow:2026-07-01:missing:ACTION-1",
            "order_intent_ref": "action:ACTION-1",
            "order_id": None,
            "symbol": None,
            "status": "missing_simulation",
            "divergence_status": "review_required",
            "severity": "warning",
            "required_action": "review_shadow_divergence",
            "reason": (
                "Paper/shadow simulation is missing for action:ACTION-1; "
                "review the order intent before manual confirmation."
            ),
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
    ]


def test_operations_today_marks_running_paper_shadow_run_as_waiting() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:running",
            "plan_date": "2026-07-01",
            "input_fingerprint": "running",
            "status": "running",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 0,
            "divergence_status": "running",
            "next_manual_review_step": "",
            "limitations_json": "[]",
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"status": "submitted", "divergence_status": "running"}]}'
            ),
            "updated_at": "2026-07-01T09:36:00+08:00",
        },
    )

    subsystem = next(
        item for item in summary["subsystems"] if item["id"] == "paper_shadow"
    )

    assert summary["paper_shadow"]["status"] == "running"
    assert summary["paper_shadow"]["next_manual_review_step"] == (
        "wait_for_paper_shadow_run"
    )
    assert summary["conclusion_status"] == "degraded"
    assert summary["primary_target"] == "paper-shadow"
    assert subsystem["status"] == "degraded"
    assert subsystem["next_action"] == "wait_for_paper_shadow_run"
    assert subsystem["detail_status"] == "running"


def test_operations_today_treats_accepted_paper_shadow_review_as_gate_passed() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:diverged",
            "plan_date": "2026-07-01",
            "input_fingerprint": "diverged",
            "status": "diverged",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 0,
            "divergence_status": "diverged",
            "next_manual_review_step": "resolve_shadow_divergence",
            "review_status": "accepted_for_manual_confirmation",
            "reviewed_at": "2026-07-01T10:10:00+08:00",
            "reviewer": "local-operator",
            "limitations_json": "[]",
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"status": "partially_filled", '
                '"divergence_status": "diverged"}], '
                '"review": {"review_status": '
                '"accepted_for_manual_confirmation"}}'
            ),
            "updated_at": "2026-07-01T10:10:00+08:00",
        },
    )

    subsystem = next(
        item for item in summary["subsystems"] if item["id"] == "paper_shadow"
    )

    assert summary["paper_shadow"]["status"] == "diverged"
    assert summary["paper_shadow"]["effective_status"] == (
        "accepted_for_manual_confirmation"
    )
    assert summary["paper_shadow"]["divergence_status"] == "diverged"
    assert summary["paper_shadow"]["review_status"] == (
        "accepted_for_manual_confirmation"
    )
    assert summary["paper_shadow"]["next_manual_review_step"] == (
        "review_manual_confirmation"
    )
    assert subsystem["status"] == "pass"
    assert subsystem["next_action"] == "review_manual_confirmation"
    assert subsystem["detail_status"] == "accepted_for_manual_confirmation"
    assert summary["conclusion_status"] == "manual_action_required"
    assert summary["primary_target"] == "trading"


def test_operations_today_keeps_failed_shadow_run_blocked_even_if_review_says_accepted() -> (
    None
):
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        paper_shadow_run={
            "run_id": "shadow:2026-07-01:failed",
            "plan_date": "2026-07-01",
            "input_fingerprint": "failed",
            "status": "failed",
            "order_intent_count": 1,
            "simulated_order_count": 1,
            "simulated_fill_count": 0,
            "divergence_status": "failed",
            "next_manual_review_step": "review_manual_confirmation",
            "review_status": "accepted_for_manual_confirmation",
            "reviewed_at": "2026-07-01T10:10:00+08:00",
            "reviewer": "local-operator",
            "limitations_json": '["Paper/shadow simulation failed."]',
            "payload_json": (
                '{"orders": [{"order_id": "SHADOW-1", '
                '"status": "failed", "divergence_status": "failed"}], '
                '"review": {"review_status": '
                '"accepted_for_manual_confirmation"}}'
            ),
            "updated_at": "2026-07-01T10:10:00+08:00",
        },
    )

    subsystem = next(
        item for item in summary["subsystems"] if item["id"] == "paper_shadow"
    )

    assert summary["paper_shadow"]["status"] == "failed"
    assert summary["paper_shadow"]["effective_status"] == "failed"
    assert summary["paper_shadow"]["next_manual_review_step"] == "inspect_failed_run"
    assert subsystem["status"] == "blocked"
    assert subsystem["next_action"] == "inspect_failed_run"
    assert subsystem["detail_status"] == "failed"
    assert summary["conclusion_status"] == "blocked"
    assert summary["primary_target"] == "paper-shadow"


def test_operations_today_surfaces_failed_scheduler_run() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        automation_runs=[
            {
                "run_id": "market-session:2026-07-01:100000",
                "run_type": "market_session",
                "run_date": "2026-07-01",
                "status": "paper_shadow_failed",
                "execution_mode": "paper_shadow",
                "started_at": "2026-07-01T10:00:00+08:00",
                "finished_at": "2026-07-01T10:00:01+08:00",
                "payload_json": (
                    '{"input_fingerprint": "abc123", '
                    '"idempotency_key": "market_session:2026-07-01:abc123", '
                    '"input_snapshot": {"order_intent_count": 1}, '
                    '"retry_state": {"attempt": 1, "max_attempts": 1, '
                    '"retryable": true}, '
                    '"error": {"type": "RuntimeError", "message": "fixture"}, '
                    '"does_not_submit_broker_order": true, '
                    '"limitations": ["Paper/shadow run failed; no broker order was submitted."]}'
                ),
            }
        ],
    )

    subsystem = next(
        item for item in summary["subsystems"] if item["id"] == "scheduler"
    )

    assert summary["scheduler"] == {
        "status": "paper_shadow_failed",
        "run_id": "market-session:2026-07-01:100000",
        "run_type": "market_session",
        "run_date": "2026-07-01",
        "execution_mode": "paper_shadow",
        "last_run_at": "2026-07-01T10:00:01+08:00",
        "input_fingerprint": "abc123",
        "idempotency_key": "market_session:2026-07-01:abc123",
        "input_snapshot": {"order_intent_count": 1},
        "retry_state": {"attempt": 1, "max_attempts": 1, "retryable": True},
        "error": {"type": "RuntimeError", "message": "fixture"},
        "suggested_action": "inspect_failed_paper_shadow_run",
        "requires_manual_review": True,
        "retry_recommended": True,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
        "limitations": ["Paper/shadow run failed; no broker order was submitted."],
    }
    assert subsystem["status"] == "blocked"
    assert subsystem["target"] == "scheduler"
    assert subsystem["last_run_at"] == "2026-07-01T10:00:01+08:00"
    assert subsystem["next_action"] == "inspect_scheduler_failure"
    assert subsystem["detail_status"] == "paper_shadow_failed"
    assert subsystem["limitations"] == [
        "Paper/shadow run failed; no broker order was submitted."
    ]
    assert summary["conclusion_status"] == "blocked"
    assert summary["primary_target"] == "scheduler"


def test_operations_today_surfaces_scheduler_retry_attempt_in_runbook() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        automation_runs=[
            {
                "run_id": "market_session:2026-07-01:abc123",
                "run_type": "market_session",
                "run_date": "2026-07-01",
                "status": "paper_shadow_failed",
                "execution_mode": "paper_shadow",
                "started_at": "2026-07-01T10:00:00+08:00",
                "finished_at": "2026-07-01T10:05:01+08:00",
                "payload_json": (
                    '{"input_fingerprint": "abc123", '
                    '"idempotency_key": "market_session:2026-07-01:abc123", '
                    '"retry_state": {"attempt": 2, "max_attempts": 2, '
                    '"retryable": true, "previous_attempts": 1}, '
                    '"error": {"type": "RuntimeError", "message": "fixture"}, '
                    '"does_not_submit_broker_order": true, '
                    '"limitations": ["Paper/shadow run failed; no broker order was submitted."]}'
                ),
            }
        ],
    )

    subsystem = next(
        item for item in summary["subsystems"] if item["id"] == "scheduler"
    )

    assert summary["scheduler"]["retry_state"] == {
        "attempt": 2,
        "max_attempts": 2,
        "retryable": True,
        "previous_attempts": 1,
    }
    assert subsystem["limitations"] == [
        "Paper/shadow run failed; no broker order was submitted.",
        "Scheduler retry attempt 2 of 2; previous attempts: 1.",
    ]
    assert subsystem["next_action"] == "inspect_scheduler_failure"
    assert subsystem["detail_status"] == "paper_shadow_failed"
