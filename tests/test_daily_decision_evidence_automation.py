from __future__ import annotations

import asyncio
import time

from server.db import AppDatabase
from server.services import daily_decision_evidence_automation as automation_module
from server.services.daily_decision_evidence_automation import (
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    DailyDecisionEvidenceAutomationService,
    project_daily_candidate_financial_preflight,
)
from server.services.oms import OmsService
from server.services.trading_controls import TradingControlState


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send(self, *, title: str, message: str) -> None:
        self.messages.append((title, message))


def _decision(*, risk_checked: bool) -> dict:
    return {
        "decision_date": "2026-07-02",
        "generated_at": "2026-07-02T09:35:00+08:00",
        "decision": "review_required",
        "summary": {
            "candidate_count": 1,
            "portfolio": {
                "valuation_snapshot_id": "valuation-001",
                "ledger_cutoff_id": 7,
            },
            "account_truth": {
                "schema_version": "karkinos.account_truth.promotion_evidence.v1",
                "status": "available",
                "promotion_status": "clear",
                "gate_status": "pass",
                "data_freshness_status": "fresh",
                "unresolved_mismatch_count": 0,
                "import_run_id": "AT-001",
                "source_fingerprint": "c" * 64,
                "captured_at": "2026-07-02T09:30:00+08:00",
                "current_age_seconds": 300,
                "max_age_seconds": 86400,
                "reconciliation_status": "pass",
                "ledger_coverage": {"status": "covered"},
            },
            "market_data": {
                "source_health": "live",
                "latest_quote_timestamp": "2026-07-02T09:34:00+08:00",
            },
        },
        "candidates": [
            {
                "action_id": 1,
                "symbol": "600519",
                "action": "buy",
                "evidence": {
                    "strategy": {
                        "strategy_id": "dual_ma",
                        "order_generation_gate": {
                            "schema_version": (
                                "karkinos.strategy_order_generation_gate.v1"
                            ),
                            "status": "pass",
                            "as_of_date": "2026-07-02",
                            "blockers": [],
                            "persisted_facts_only": True,
                            "provider_contact_performed": False,
                            "paper_shadow_evaluation_only": True,
                            "does_not_create_order": True,
                            "does_not_authorize_execution": True,
                            "does_not_change_capital_authority": True,
                            "broker_submission_enabled": False,
                            "promotion": {
                                "status": "pass",
                                "stage": "paper_shadow",
                                "gate_status": "paper_shadow_enabled",
                                "live_like_enabled": False,
                                "human_reviewer": "owner",
                                "human_review_note_recorded": True,
                                "comparison_fingerprint": "e" * 64,
                                "human_approval_id": "approval-fixture",
                                "strategy_advancement_gate_fingerprint": "a" * 64,
                                "fee_schedule_binding": {
                                    "fee_schedule_review_fingerprint": "b" * 64,
                                },
                                "dataset_replay": {
                                    "status": "pass",
                                    "blockers": [],
                                    "evidence_fingerprint": "f" * 64,
                                    "persisted_market_bars_only": True,
                                    "provider_contacted": False,
                                    "baseline_manifest_matches_candidate": True,
                                    "baseline_snapshot_id": "dataset-fixture",
                                    "candidate_snapshot_id": "dataset-fixture",
                                },
                            },
                        },
                    },
                },
                "risk_gate_status": "passed" if risk_checked else "not_checked",
                "manual_confirmation_status": (
                    "ready_for_manual_confirmation"
                    if risk_checked
                    else "awaiting_risk_gate"
                ),
            }
        ],
    }


def _plan(*, risk_checked: bool) -> dict:
    order_intents = []
    blockers = [
        {
            "action_id": 1,
            "symbol": "600519",
            "reason": "awaiting_risk_gate",
        }
    ]
    if risk_checked:
        blockers = []
        order_intents = [
            {
                "intent_id": "ACTION-1-BATCH-RISK",
                "action_id": 1,
                "strategy_id": "dual_ma",
                "symbol": "600519",
                "side": "buy",
                "asset_class": "stock",
                "estimated_quantity": 100,
                "estimated_price": 10.0,
                "market_quote_price": 10.0,
                "market_quote_timestamp": "2026-07-02T09:34:00+08:00",
                "market_quote_source": "fixture",
                "risk_decision_id": "RISK-001",
                "risk_gate_status": "passed",
                "manual_confirmation_status": "ready_for_manual_confirmation",
                "submission_status": "manual_confirmation_required",
                "fee_rule_id": "reviewed-account-fees:v1",
                "fee_rule_version": "v1",
                "estimated_gross_amount": 1000.0,
                "estimated_total_fee": 5.0,
                "estimated_net_cash_impact": -1005.0,
                "available_cash_before": 5000.0,
                "available_cash_after": 3995.0,
                "cash_status": "sufficient",
                "fee_breakdown": {"commission": "5.00"},
                "constraint_checks": [
                    {"id": "trading_unit", "status": "pass"},
                    {"id": "fee_tax_preview", "status": "pass"},
                ],
                "does_not_submit_broker_order": True,
                "evidence_refs": [
                    "action:1",
                    "strategy:dual_ma",
                    "strategy_advancement:" + "a" * 64,
                    "reviewed_fee_schedule:" + "b" * 64,
                    "risk:RISK-001",
                    "account_truth:AT-001",
                ],
            }
        ]
    return {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T09:35:00+08:00",
        "conclusion_status": (
            "manual_confirmation_ready" if risk_checked else "no_manual_action"
        ),
        "candidate_pool_count": 1,
        "manual_ready_count": 1 if risk_checked else 0,
        "blocked_count": 0 if risk_checked else 1,
        "order_intents": order_intents,
        "blockers": blockers,
    }


def _financial_preflight_inputs() -> dict:
    decision = _decision(risk_checked=False)
    decision["candidates"][0]["evidence"]["data_freshness"] = {
        "status": "fresh",
        "price": 10.0,
        "quote_timestamp": "2026-07-02T09:34:00+08:00",
        "quote_source": "persisted_fixture",
    }
    return {
        "decision_payload": decision,
        "trading_plan": _plan(risk_checked=False),
        "reviewed_fee_schedule": {
            "status": "active",
            "review": {
                "review_fingerprint": "b" * 64,
                "effective_start_date": "2026-01-01",
                "effective_end_date": "2026-12-31",
            },
            "blockers": [],
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
        "execution_closure": {
            "schema_version": "karkinos.daily_candidate_execution_closure.v1",
            "status": "not_required",
            "blockers": [],
            "evidence_fingerprint": "d" * 64,
        },
        "automation_status": {
            "automation_ready": True,
            "kill_switch_enabled": False,
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "allowed_execution_modes": [
                "manual_confirmation",
                "paper_shadow",
                "dry_run",
            ],
        },
        "runtime_status": {
            "schema_version": "karkinos.daily_candidate_runtime_status.v1",
            "status": "monitor_running_due",
            "run_date": "2026-07-02",
            "schedule_status": "due",
            "background_monitor_running": True,
            "background_attempt_due": True,
            "manual_run_window_open": True,
            "operational_blockers": [],
            "provider_contact_performed": False,
            "database_writes_performed": False,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
    }


def test_financial_preflight_opens_only_risk_and_paper_shadow_attempt() -> None:
    result = project_daily_candidate_financial_preflight(
        **_financial_preflight_inputs()
    )

    assert result["status"] == "ready_for_paper_shadow_attempt"
    assert result["financial_gate_status"] == "pass"
    assert result["eligible_candidate_count"] == 1
    assert result["eligible_to_start_manual_attempt"] is True
    assert result["eligible_for_background_attempt"] is True
    assert result["eligible_to_create_manual_ticket"] is False
    assert result["risk_evaluation_performed"] is False
    assert result["paper_shadow_run_performed"] is False
    assert result["manual_ticket_created"] is False
    assert result["database_writes_performed"] is False
    assert result["provider_contact_performed"] is False
    assert result["broker_submission_enabled"] is False
    assert result["authorizes_execution"] is False
    assert result["changes_capital_authority"] is False
    assert result["profitability_claim"] == "not_established"


def test_financial_preflight_fails_closed_on_account_truth_staleness() -> None:
    inputs = _financial_preflight_inputs()
    inputs["decision_payload"]["summary"]["account_truth"].update(
        {
            "data_freshness_status": "stale",
            "current_age_seconds": 90000,
        }
    )

    result = project_daily_candidate_financial_preflight(**inputs)

    assert result["status"] == "no_action"
    assert result["financial_gate_status"] == "blocked"
    assert result["eligible_for_background_attempt"] is False
    assert "account_truth_not_fresh" in result["no_action_reasons"]
    assert "account_truth_age_exceeds_reviewed_limit" in result["no_action_reasons"]


def test_financial_preflight_fails_closed_on_fee_or_strategy_binding_drift() -> None:
    inputs = _financial_preflight_inputs()
    inputs["reviewed_fee_schedule"] = {
        **inputs["reviewed_fee_schedule"],
        "status": "missing",
        "review": None,
        "blockers": ["reviewed_fee_schedule_review_missing"],
    }

    result = project_daily_candidate_financial_preflight(**inputs)

    assert result["status"] == "no_action"
    assert result["eligible_candidate_count"] == 0
    assert "reviewed_fee_schedule_review_missing" in result["no_action_reasons"]
    assert "reviewed_fee_schedule_not_active" in result["no_action_reasons"]
    assert any(
        "reviewed_fee_schedule_active_binding_mismatch" in blocker
        for blocker in result["no_action_reasons"]
    )


def test_financial_preflight_keeps_clear_financial_facts_closed_after_window() -> None:
    inputs = _financial_preflight_inputs()
    inputs["runtime_status"].update(
        {
            "status": "monitor_running_schedule_blocked",
            "schedule_status": "missed_decision_window",
            "background_attempt_due": False,
            "manual_run_window_open": False,
            "operational_blockers": ["daily_candidate_background_window_missed"],
        }
    )

    result = project_daily_candidate_financial_preflight(**inputs)

    assert result["status"] == "no_action"
    assert result["financial_gate_status"] == "pass"
    assert result["eligible_to_start_manual_attempt"] is False
    assert result["eligible_for_background_attempt"] is False
    assert result["no_action_reasons"] == ["daily_candidate_background_window_missed"]


def test_automatic_evidence_chain_runs_risk_then_idempotent_paper_shadow(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    notifier = RecordingNotifier()
    state = {"risk_checked": False, "risk_calls": 0, "plan_reads": 0}

    async def read_plan():
        state["plan_reads"] += 1
        checked = bool(state["risk_checked"])
        decision = _decision(risk_checked=checked)
        decision["summary"]["account_truth"]["current_age_seconds"] = (
            300 + state["plan_reads"]
        )
        return decision, _plan(risk_checked=checked)

    async def run_risk():
        state["risk_calls"] += 1
        state["risk_checked"] = True
        already_checked = state["risk_calls"] > 1
        return {
            "status": "completed",
            "candidate_count": 1,
            "processed_count": 0 if already_checked else 1,
            "passed_count": 0 if already_checked else 1,
            "blocked_count": 0,
            "skipped_count": 1 if already_checked else 0,
            "risk_decision_writes_performed": not already_checked,
            "blockers": [],
        }

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=controls,
        notifier=notifier,
        plan_reader=read_plan,
        risk_runner=run_risk,
    )

    first = asyncio.run(service.run_once())
    second = asyncio.run(service.run_once())

    assert first["status"] == "paper_shadow_completed"
    assert first["input_identity_schema_version"] == (
        "karkinos.daily_candidate_input_identity.v2"
    )
    assert first["risk"]["passed_count"] == 1
    assert first["risk"]["newly_passed_count"] == 1
    assert first["paper_shadow"]["status"] == "within_expectations"
    assert first["paper_shadow"]["simulated_order_count"] == 1
    assert first["manual_confirmation_required"] is True
    assert first["broker_submission_enabled"] is False
    assert first["does_not_submit_broker_order"] is True
    assert first["does_not_mutate_production_ledger"] is True
    assert first["production_gate"]["status"] == "pass"
    assert first["decision_outcome"] == "manual_order_ticket_candidate"
    assert first["manual_ticket_candidate_count"] == 1
    ticket = first["manual_order_ticket_candidates"][0]
    assert ticket["schema_version"] == "karkinos.manual_order_ticket_candidate.v1"
    assert ticket["intent_id"] == "ACTION-1-BATCH-RISK"
    assert ticket["symbol"] == "600519"
    assert ticket["side"] == "buy"
    assert ticket["quantity"] == 100
    assert ticket["limit_price"] == 10.0
    assert ticket["market_quote"] == {
        "price": 10.0,
        "timestamp": "2026-07-02T09:34:00+08:00",
        "source": "fixture",
        "age_seconds_at_decision": 60,
        "max_age_seconds": 300,
    }
    assert ticket["fee_breakdown"] == {"commission": "5.00"}
    assert ticket["paper_shadow"]["run_id"] == first["paper_shadow"]["run_id"]
    assert (
        ticket["strategy_gate_binding"]
        == first["input_snapshot"]["strategy_gate_bindings"][0]
    )
    assert ticket["strategy_gate_binding"]["candidate_snapshot_id"] == (
        "dataset-fixture"
    )
    assert ticket["strategy_gate_binding"]["dataset_replay_fingerprint"] == ("f" * 64)
    assert (
        ticket["account_truth_binding"]
        == first["input_snapshot"]["account_truth_binding"]
    )
    assert ticket["account_truth_binding"]["age_seconds_at_decision"] == 300
    assert ticket["account_truth_binding"]["valuation_snapshot_id"] == ("valuation-001")
    assert ticket["account_truth_binding"]["ledger_cutoff_id"] == 7
    assert ticket["account_truth_binding"]["provider_contact_performed"] is False
    assert ticket["prior_execution_closure_fingerprint"] == (
        first["execution_closure"]["evidence_fingerprint"]
    )
    assert len(ticket["ticket_candidate_fingerprint"]) == 64
    assert ticket["manual_confirmation_required"] is True
    assert ticket["creates_oms_order"] is False
    assert ticket["authorizes_execution"] is False
    assert ticket["broker_submission_enabled"] is False
    assert first["profitability_claim"] == "not_established_by_daily_run"
    assert first["notification"] == {"status": "sent", "sent": True}
    assert second["notification"] == {
        "status": "skipped_duplicate_evidence",
        "sent": False,
    }
    assert second["risk"]["passed_count"] == 1
    assert second["risk"]["newly_passed_count"] == 0
    assert second["input_fingerprint"] == first["input_fingerprint"]
    assert first["input_snapshot"]["account_truth_age_seconds_at_decision"] == 300
    assert first["input_snapshot"]["account_truth_max_age_seconds"] == 86400
    assert state["risk_calls"] == 2
    assert len(notifier.messages) == 1
    assert "仍需在 Web 中人工复核" in notifier.messages[0][1]
    assert db.latest_paper_shadow_run_sync(plan_date="2026-07-02") is not None
    assert len(db.list_orders_sync()) == 1
    assert len(db.list_fills_sync()) == 1
    assert db.list_manual_orders_sync() == []
    assert db.get_ledger_entries_sync() == []
    assert (
        len(
            db.list_automation_runs_sync(
                run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE
            )
        )
        == 1
    )
    assert len(db.list_automation_runs_sync(run_type="daily_paper_shadow")) == 1


def test_background_no_action_notification_is_sanitized_and_non_authorizing(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    notifier = RecordingNotifier()

    async def unused_plan_reader():
        raise AssertionError("notification must not read financial facts")

    async def unused_risk_runner():
        raise AssertionError("notification must not run risk")

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=TradingControlState(db=db),
        notifier=notifier,
        plan_reader=unused_plan_reader,
        risk_runner=unused_risk_runner,
    )

    status = asyncio.run(
        service._send_no_action_notification(
            result={
                "plan_date": "2026-07-02",
                "no_action_reasons": [
                    "account_truth_reconciliation_not_pass",
                    "market_quote_too_old_for_decision",
                ],
            }
        )
    )

    assert status == {"status": "sent", "sent": True}
    assert len(notifier.messages) == 1
    title, message = notifier.messages[0]
    assert title == "Karkinos 每日候选 NO-ACTION: 2026-07-02"
    assert "account_truth_reconciliation_not_pass" in message
    assert "market_quote_too_old_for_decision" in message
    assert "未创建 OMS 订单" in message
    assert "balance" not in message.lower()


def test_background_no_action_notification_timeout_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    class SlowNotifier:
        def send(self, *, title, message):
            del title, message
            time.sleep(0.05)

    async def unused_plan_reader():
        raise AssertionError("notification must not read financial facts")

    async def unused_risk_runner():
        raise AssertionError("notification must not run risk")

    monkeypatch.setattr(
        automation_module,
        "DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS",
        0.001,
    )
    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=TradingControlState(db=db),
        notifier=SlowNotifier(),
        plan_reader=unused_plan_reader,
        risk_runner=unused_risk_runner,
    )

    status = asyncio.run(
        service._send_no_action_notification(
            result={"plan_date": "2026-07-02", "no_action_reasons": []}
        )
    )

    assert status == {
        "status": "failed",
        "sent": False,
        "error_type": "TimeoutError",
    }


def test_daily_candidate_input_identity_preserves_same_day_strategy_drift(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    state = {"risk_checked": False, "dataset_fingerprint": "f" * 64}

    async def read_plan():
        decision = _decision(risk_checked=bool(state["risk_checked"]))
        decision["candidates"][0]["evidence"]["strategy"]["order_generation_gate"][
            "promotion"
        ]["dataset_replay"]["evidence_fingerprint"] = state["dataset_fingerprint"]
        return decision, _plan(risk_checked=bool(state["risk_checked"]))

    async def run_risk():
        state["risk_checked"] = True
        return {"status": "completed", "passed_count": 1, "blockers": []}

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=TradingControlState(db=db),
        notifier=RecordingNotifier(),
        plan_reader=read_plan,
        risk_runner=run_risk,
    )

    first = asyncio.run(service.run_once())
    state["dataset_fingerprint"] = "1" * 64
    second = asyncio.run(service.run_once())

    assert first["decision_outcome"] == "manual_order_ticket_candidate"
    assert second["decision_outcome"] == "manual_order_ticket_candidate"
    assert first["input_fingerprint"] != second["input_fingerprint"]
    rows = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE
    )
    assert len(rows) == 2
    assert len({row["run_id"] for row in rows}) == 2


def test_automatic_evidence_chain_fails_closed_on_incomplete_risk_evidence(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    notifier = RecordingNotifier()

    async def read_plan():
        return _decision(risk_checked=False), _plan(risk_checked=False)

    async def run_risk():
        return {
            "status": "blocked_by_data_quality",
            "candidate_count": 1,
            "processed_count": 0,
            "passed_count": 0,
            "blocked_count": 0,
            "skipped_count": 1,
            "risk_decision_writes_performed": False,
            "blockers": [{"code": "valuation_snapshot_not_complete"}],
        }

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=TradingControlState(db=db),
        notifier=notifier,
        plan_reader=read_plan,
        risk_runner=run_risk,
    )

    result = asyncio.run(service.run_once())

    assert result["status"] == "blocked_by_data_quality"
    assert result["risk"]["risk_decision_writes_performed"] is False
    assert result["paper_shadow"]["status"] == "not_run"
    assert db.latest_paper_shadow_run_sync(plan_date="2026-07-02") is None
    assert db.list_orders_sync() == []
    assert db.list_fills_sync() == []
    assert notifier.messages == []


def test_daily_candidate_preserves_distinct_sanitized_risk_failures(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    state = {"error": "risk-source-a"}

    async def read_plan():
        return _decision(risk_checked=False), _plan(risk_checked=False)

    async def run_risk():
        raise RuntimeError(state["error"])

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=TradingControlState(db=db),
        notifier=RecordingNotifier(),
        plan_reader=read_plan,
        risk_runner=run_risk,
    )

    first = asyncio.run(service.run_once())
    state["error"] = "risk-source-b"
    second = asyncio.run(service.run_once())

    assert first["status"] == "risk_gate_failed"
    assert first["decision_outcome"] == "no_action"
    assert first["risk"]["error_type"] == "RuntimeError"
    assert len(first["risk"]["error_fingerprint"]) == 64
    assert "error" not in first["risk"]
    assert first["input_fingerprint"] != second["input_fingerprint"]
    assert (
        len(
            db.list_automation_runs_sync(
                run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE
            )
        )
        == 2
    )


def test_automatic_evidence_chain_obeys_kill_switch_before_risk_writes(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    risk_called = False

    async def read_plan():
        return _decision(risk_checked=False), _plan(risk_checked=False)

    async def run_risk():
        nonlocal risk_called
        risk_called = True
        return {"status": "completed"}

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=controls,
        notifier=RecordingNotifier(),
        plan_reader=read_plan,
        risk_runner=run_risk,
    )

    result = asyncio.run(service.run_once())

    assert result["status"] == "blocked_by_kill_switch"
    assert risk_called is False
    assert db.get_risk_decisions_sync() == []
    assert db.latest_paper_shadow_run_sync(plan_date="2026-07-02") is None
    assert db.list_orders_sync() == []


def test_daily_candidate_fails_closed_when_quote_is_after_decision_time(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    decision = _decision(risk_checked=True)
    decision["summary"]["market_data"][
        "latest_quote_timestamp"
    ] = "2026-07-02T09:36:00+08:00"

    async def read_plan():
        return decision, _plan(risk_checked=True)

    async def run_risk():
        return {
            "status": "completed",
            "candidate_count": 1,
            "processed_count": 0,
            "passed_count": 0,
            "blocked_count": 0,
            "skipped_count": 1,
            "risk_decision_writes_performed": False,
            "blockers": [],
        }

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["status"] == "paper_shadow_completed"
    assert result["decision_outcome"] == "no_action"
    assert result["manual_ticket_candidate_count"] == 0
    assert result["manual_order_ticket_candidates"] == []
    assert result["production_gate"]["status"] == "blocked"
    assert "market_quote_after_decision_generation" in result["no_action_reasons"]
    assert result["does_not_submit_broker_order"] is True


def test_daily_candidate_fails_closed_outside_reviewed_decision_window(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    decision = _decision(risk_checked=True)
    plan = _plan(risk_checked=True)
    decision["generated_at"] = "2026-07-02T14:00:00+08:00"
    decision["summary"]["market_data"][
        "latest_quote_timestamp"
    ] = "2026-07-02T13:59:00+08:00"
    plan["generated_at"] = "2026-07-02T14:00:01+08:00"
    plan["order_intents"][0]["market_quote_timestamp"] = "2026-07-02T13:59:00+08:00"

    async def read_plan():
        return decision, plan

    async def run_risk():
        return {"status": "completed", "blockers": []}

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["decision_outcome"] == "no_action"
    assert result["manual_order_ticket_candidates"] == []
    assert result["input_snapshot"]["decision_window"]["status"] == "blocked"
    assert "decision_generated_outside_reviewed_window" in result["no_action_reasons"]
    assert "plan_generated_outside_reviewed_window" in result["no_action_reasons"]
    assert result["does_not_submit_broker_order"] is True


def test_daily_candidate_fails_closed_when_quote_exceeds_reviewed_age(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    decision = _decision(risk_checked=True)
    plan = _plan(risk_checked=True)
    decision["summary"]["market_data"][
        "latest_quote_timestamp"
    ] = "2026-07-02T09:20:00+08:00"
    plan["order_intents"][0]["market_quote_timestamp"] = "2026-07-02T09:20:00+08:00"

    async def read_plan():
        return decision, plan

    async def run_risk():
        return {"status": "completed", "blockers": []}

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["decision_outcome"] == "no_action"
    assert "market_quote_too_old_for_decision" in result["no_action_reasons"]
    assert (
        "order_intent_0:market_quote_too_old_for_decision"
        in result["no_action_reasons"]
    )
    assert result["manual_order_ticket_candidates"] == []


def test_daily_candidate_replays_frozen_dataset_and_strategy_gate(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    decision = _decision(risk_checked=True)
    plan = _plan(risk_checked=True)
    decision["candidates"][0]["evidence"]["strategy"]["order_generation_gate"][
        "promotion"
    ]["dataset_replay"]["status"] = "blocked"

    async def read_plan():
        return decision, plan

    async def run_risk():
        return {"status": "completed", "blockers": []}

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["decision_outcome"] == "no_action"
    assert (
        "order_intent_0:strategy_frozen_dataset_replay_not_pass"
        in result["no_action_reasons"]
    )
    assert result["input_snapshot"]["strategy_gate_bindings"] == []
    assert result["manual_order_ticket_candidates"] == []


def test_daily_candidate_fails_closed_on_non_finite_estimated_fee(tmp_path) -> None:
    for index, invalid_fee in enumerate((float("nan"), float("inf"))):
        db = AppDatabase(tmp_path / f"app-{index}.db")
        db.init_sync()
        plan = _plan(risk_checked=True)
        plan["order_intents"][0]["estimated_total_fee"] = invalid_fee

        async def read_plan():
            return _decision(risk_checked=True), plan

        async def run_risk():
            return {
                "status": "completed",
                "candidate_count": 1,
                "processed_count": 0,
                "passed_count": 0,
                "blocked_count": 0,
                "skipped_count": 1,
                "risk_decision_writes_performed": False,
                "blockers": [],
            }

        result = asyncio.run(
            DailyDecisionEvidenceAutomationService(
                db=db,
                trading_controls=TradingControlState(db=db),
                notifier=RecordingNotifier(),
                plan_reader=read_plan,
                risk_runner=run_risk,
            ).run_once()
        )

        assert result["decision_outcome"] == "no_action"
        assert "order_intent_0:estimated_fee_invalid" in result["no_action_reasons"]


def test_daily_candidate_requires_same_day_account_truth_promotion_evidence(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    decision = _decision(risk_checked=True)
    decision["summary"]["account_truth"]["captured_at"] = "2026-07-01T15:01:00+08:00"

    async def read_plan():
        return decision, _plan(risk_checked=True)

    async def run_risk():
        return {"status": "completed", "blockers": []}

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["decision_outcome"] == "no_action"
    assert result["manual_order_ticket_candidates"] == []
    assert "account_truth_not_bound_to_plan_date" in result["no_action_reasons"]


def test_daily_candidate_requires_explicit_clear_reconciled_account_truth(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    decision = _decision(risk_checked=True)
    decision["summary"]["account_truth"]["promotion_status"] = "blocked"
    decision["summary"]["account_truth"]["reconciliation_status"] = "blocked"

    async def read_plan():
        return decision, _plan(risk_checked=True)

    async def run_risk():
        return {"status": "completed", "blockers": []}

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["decision_outcome"] == "no_action"
    assert "account_truth_promotion_status_not_clear" in result["no_action_reasons"]
    assert "account_truth_reconciliation_not_pass" in result["no_action_reasons"]


def test_daily_candidate_rejects_account_truth_captured_after_decision(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    decision = _decision(risk_checked=True)
    decision["summary"]["account_truth"]["captured_at"] = "2026-07-02T09:36:00+08:00"
    decision["summary"]["account_truth"]["current_age_seconds"] = 0

    async def read_plan():
        return decision, _plan(risk_checked=True)

    async def run_risk():
        return {"status": "completed", "blockers": []}

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["decision_outcome"] == "no_action"
    assert "account_truth_after_decision_generation" in result["no_action_reasons"]
    assert result["input_snapshot"]["account_truth_age_seconds_at_decision"] is None
    assert result["manual_order_ticket_candidates"] == []


def test_daily_candidate_blocks_until_prior_production_order_is_reconciled(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    OmsService(db=db).create_order_intent(
        intent_key="prior-production-order",
        symbol="600000",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=10.0,
        source="daily_trading_plan",
        source_ref="action:prior",
    )

    async def read_plan():
        return _decision(risk_checked=True), _plan(risk_checked=True)

    async def run_risk():
        return {"status": "completed", "blockers": []}

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["decision_outcome"] == "no_action"
    assert result["execution_closure"]["status"] == "blocked"
    assert "prior_execution_not_reconciled" in result["no_action_reasons"]


def test_daily_candidate_requires_each_intent_to_bind_current_quote(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    plan = _plan(risk_checked=True)
    plan["order_intents"][0]["market_quote_price"] = 10.5

    async def read_plan():
        return _decision(risk_checked=True), plan

    async def run_risk():
        return {"status": "completed", "blockers": []}

    result = asyncio.run(
        DailyDecisionEvidenceAutomationService(
            db=db,
            trading_controls=TradingControlState(db=db),
            notifier=RecordingNotifier(),
            plan_reader=read_plan,
            risk_runner=run_risk,
        ).run_once()
    )

    assert result["decision_outcome"] == "no_action"
    assert (
        "order_intent_0:estimated_price_not_bound_to_market_quote"
        in result["no_action_reasons"]
    )
