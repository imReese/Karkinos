from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from server.db import AppDatabase
from server.services.daily_candidate_execution_closure import (
    build_daily_candidate_execution_closure,
)
from server.services.daily_candidate_trial import (
    DAILY_CANDIDATE_TRIAL_REVIEW_CONFIRMATION,
    DailyCandidateTrialReviewRejected,
    DailyCandidateTrialService,
)
from server.services.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
    daily_candidate_input_fingerprint,
    daily_candidate_record_fingerprint,
    manual_ticket_candidate_fingerprint,
)

STRATEGY_ADVANCEMENT_REF = "strategy_advancement:" + "a" * 64
REVIEWED_FEE_SCHEDULE_REF = "reviewed_fee_schedule:" + "b" * 64


def _trading_days(count: int = 20) -> list[str]:
    return [f"2026-07-{day:02d}" for day in range(1, count + 1)]


def _seed_verified_calendar(db: AppDatabase, days: list[str]) -> None:
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "fixture",
            "schema_version": "karkinos.market_calendar.v1",
            "status": "available",
            "trading_day_count": len(days),
            "closed_day_count": 365 - len(days),
            "source_fingerprint": "calendar-fingerprint",
            "official_verification_status": "verified",
            "days": [
                {
                    "date": day,
                    "is_trading_day": True,
                    "day_type": "trading_day",
                    "reason_code": "trading_day",
                }
                for day in days
            ],
        }
    )


def _seed_qualifying_day(
    db: AppDatabase,
    *,
    day: str,
    order_count: int = 3,
    suffix: str = "primary",
    schema_version: str = DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
    strategy_advancement_ref: str = STRATEGY_ADVANCEMENT_REF,
    reviewed_fee_schedule_ref: str = REVIEWED_FEE_SCHEDULE_REF,
) -> None:
    paper_fingerprint = f"paper-{day}-{suffix}"
    paper_run_id = f"shadow:{day}:{suffix}"
    db.upsert_paper_shadow_run_sync(
        run_id=paper_run_id,
        plan_date=day,
        input_fingerprint=paper_fingerprint,
        status="within_expectations",
        order_intent_count=order_count,
        simulated_order_count=order_count,
        simulated_fill_count=order_count,
        divergence_status="within_expectations",
        next_manual_review_step="review_manual_confirmation",
        limitations=[],
        payload={"orders": []},
    )
    execution_closure = build_daily_candidate_execution_closure(db)
    account_truth_binding = {
        "schema_version": "karkinos.daily_candidate_account_truth_binding.v1",
        "account_truth_ref": "account_truth:account-truth-fixture",
        "source_fingerprint": "c" * 64,
        "captured_at": f"{day}T09:30:00+08:00",
        "age_seconds_at_decision": 300,
        "max_age_seconds": 86400,
        "valuation_snapshot_id": "valuation-fixture",
        "ledger_cutoff_id": 7,
        "reconciliation_status": "pass",
        "ledger_coverage_status": "covered",
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    strategy_gate_bindings = [
        {
            "schema_version": "karkinos.daily_candidate_strategy_gate_binding.v1",
            "action_id": index + 1,
            "strategy_ref": "strategy:fixture",
            "strategy_advancement_ref": strategy_advancement_ref,
            "reviewed_fee_schedule_ref": reviewed_fee_schedule_ref,
            "comparison_fingerprint": "e" * 64,
            "human_approval_id": "approval-fixture",
            "dataset_replay_fingerprint": "f" * 64,
            "baseline_snapshot_id": "dataset-fixture",
            "candidate_snapshot_id": "dataset-fixture",
            "persisted_facts_only": True,
            "provider_contact_performed": False,
            "paper_shadow_evaluation_only": True,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }
        for index in range(order_count)
    ]
    tickets = []
    for index in range(order_count):
        ticket = {
            "schema_version": "karkinos.manual_order_ticket_candidate.v1",
            "plan_date": day,
            "intent_id": f"intent-{index + 1}",
            "action_id": index + 1,
            "symbol": f"600{index:03d}",
            "side": "buy",
            "quantity": 100,
            "limit_price": 10.0,
            "market_quote": {
                "price": 10.0,
                "timestamp": f"{day}T09:34:00+08:00",
                "source": "fixture",
                "age_seconds_at_decision": 60,
                "max_age_seconds": 300,
            },
            "paper_shadow": {
                "run_id": paper_run_id,
                "input_fingerprint": paper_fingerprint,
                "status": "within_expectations",
                "divergence_status": "within_expectations",
            },
            "strategy_gate_binding": strategy_gate_bindings[index],
            "account_truth_binding": account_truth_binding,
            "prior_execution_closure_fingerprint": execution_closure[
                "evidence_fingerprint"
            ],
            "evidence_refs": [
                "strategy:fixture",
                strategy_advancement_ref,
                reviewed_fee_schedule_ref,
                f"risk:risk-{index + 1}",
                "account_truth:account-truth-fixture",
            ],
            "manual_confirmation_required": True,
            "creates_oms_order": False,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
            "does_not_change_capital_authority": True,
        }
        ticket["ticket_candidate_fingerprint"] = manual_ticket_candidate_fingerprint(
            ticket
        )
        tickets.append(ticket)
    payload = {
        "schema_version": schema_version,
        "input_identity_schema_version": (
            DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION
        ),
        "input_fingerprint": "",
        "input_snapshot": {
            "decision_date": day,
            "plan_date": day,
            "valuation_snapshot_id": "valuation-fixture",
            "ledger_cutoff_id": 7,
            "account_truth_ref": "account_truth:account-truth-fixture",
            "account_truth_source_fingerprint": "c" * 64,
            "account_truth_captured_at": f"{day}T09:30:00+08:00",
            "account_truth_age_seconds_at_decision": 300,
            "account_truth_max_age_seconds": 86400,
            "account_truth_reconciliation_status": "pass",
            "account_truth_ledger_coverage_status": "covered",
            "account_truth_binding": account_truth_binding,
            "decision_plan_fingerprint": hashlib.sha256(
                f"{day}:{suffix}".encode("utf-8")
            ).hexdigest(),
            "decision_window": {
                "schema_version": "karkinos.daily_candidate_decision_window.v1",
                "timezone": "Asia/Shanghai",
                "start": "09:35",
                "end_exclusive": "09:45",
                "decision_generated_at": f"{day}T09:35:00+08:00",
                "plan_generated_at": f"{day}T09:35:01+08:00",
                "status": "pass",
            },
            "market_quote_timestamp": f"{day}T09:34:00+08:00",
            "market_quote_age_seconds_at_decision": 60,
            "market_quote_max_age_seconds": 300,
            "paper_shadow_run_id": paper_run_id,
            "paper_shadow_input_fingerprint": paper_fingerprint,
            "execution_closure_fingerprint": execution_closure["evidence_fingerprint"],
            "market_quote_bindings": [
                {
                    "intent_ref": f"intent-{index + 1}",
                    "timestamp": f"{day}T09:34:00+08:00",
                    "source": "fixture",
                    "price": 10.0,
                }
                for index in range(order_count)
            ],
            "strategy_advancement_refs": [strategy_advancement_ref],
            "reviewed_fee_schedule_refs": [reviewed_fee_schedule_ref],
            "strategy_gate_bindings": strategy_gate_bindings,
        },
        "candidate_count": order_count,
        "risk": {"status": "completed", "passed_count": order_count},
        "production_gate": {
            "status": "pass",
            "blockers": [],
        },
        "decision_outcome": "manual_order_ticket_candidate",
        "manual_ticket_candidate_count": order_count,
        "manual_order_ticket_candidates": tickets,
        "no_action_reasons": [],
        "strategy_bindings": [
            {
                "strategy_ref": "strategy:fixture",
                "strategy_advancement_ref": strategy_advancement_ref,
                "reviewed_fee_schedule_ref": reviewed_fee_schedule_ref,
            }
        ],
        "profitability_claim": "not_established_by_daily_run",
        "paper_shadow": {
            "status": "within_expectations",
            "divergence_status": "within_expectations",
            "run_id": paper_run_id,
            "input_fingerprint": paper_fingerprint,
            "simulated_order_count": order_count,
            "simulated_fill_count": order_count,
        },
        "execution_closure": execution_closure,
        "manual_confirmation_required": True,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
        "limitations": [],
    }
    payload["input_fingerprint"] = daily_candidate_input_fingerprint(payload)
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync(
        {
            "run_id": f"daily-candidate:{day}:{suffix}",
            "run_type": DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
            "run_date": day,
            "status": "paper_shadow_completed",
            "execution_mode": "paper_shadow",
            "started_at": f"{day}T09:35:00+08:00",
            "finished_at": f"{day}T09:36:00+08:00",
            "source_ref": paper_run_id,
            "payload": payload,
        }
    )


def test_daily_candidate_trial_requires_20_days_and_50_orders(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    days = _trading_days()
    _seed_verified_calendar(db, days)
    for day in days[:19]:
        _seed_qualifying_day(db, day=day, order_count=3)

    collecting = DailyCandidateTrialService(db=db).get_status()

    assert collecting["status"] == "collecting_forward_operating_evidence"
    assert collecting["qualifying_trading_day_count"] == 19
    assert collecting["simulated_order_count"] == 57
    assert collecting["remaining_trading_days"] == 1
    assert collecting["remaining_simulated_orders"] == 0
    assert collecting["eligible_for_human_go_no_go_review"] is False
    assert "qualifying_trading_days_insufficient" in collecting["blockers"]
    assert collecting["authorizes_execution"] is False

    _seed_qualifying_day(db, day=days[19], order_count=3)
    ready = DailyCandidateTrialService(db=db).get_status()

    assert ready["status"] == "eligible_for_human_go_no_go_review"
    assert ready["qualifying_trading_day_count"] == 20
    assert ready["simulated_order_count"] == 60
    assert ready["remaining_trading_days"] == 0
    assert ready["remaining_simulated_orders"] == 0
    assert ready["blockers"] == []
    assert ready["latest_daily_run"]["decision_outcome"] == (
        "manual_order_ticket_candidate"
    )
    assert ready["latest_daily_run"]["run_date"] == days[19]
    assert ready["does_not_establish_future_profitability"] is True
    assert ready["automatic_order_submission_enabled"] is False
    assert ready["automatic_capital_scaling_enabled"] is False


def test_daily_candidate_trial_excludes_pre_closure_v2_records(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(
        db,
        day=day,
        schema_version="karkinos.daily_decision_evidence_automation.v2",
    )

    status = DailyCandidateTrialService(db=db).get_status()

    assert status["qualifying_trading_day_count"] == 0
    assert status["excluded_days"][0]["blockers"] == [
        "daily_candidate_contract_missing"
    ]


def test_daily_candidate_trial_excludes_tampered_manual_ticket(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(row["payload_json"])
    payload["manual_order_ticket_candidates"][0]["limit_price"] = 99.0
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync({**row, "payload": payload})

    status = DailyCandidateTrialService(db=db).get_status()

    assert status["qualifying_trading_day_count"] == 0
    blockers = status["excluded_days"][0]["blockers"]
    assert "manual_order_ticket_candidate_0:fingerprint_mismatch" in blockers
    assert "manual_order_ticket_candidate_0:market_quote_price_mismatch" in blockers


def test_daily_candidate_trial_replays_ticket_paper_shadow_binding(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(row["payload_json"])
    ticket = payload["manual_order_ticket_candidates"][0]
    ticket["paper_shadow"]["input_fingerprint"] = "drifted-paper-source"
    ticket["ticket_candidate_fingerprint"] = manual_ticket_candidate_fingerprint(ticket)
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync({**row, "payload": payload})

    status = DailyCandidateTrialService(db=db).get_status()

    blockers = status["excluded_days"][0]["blockers"]
    assert "manual_order_ticket_candidate_0:paper_shadow_fingerprint_mismatch" in (
        blockers
    )


def test_daily_candidate_trial_excludes_invalid_ticket_count_without_crashing(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(row["payload_json"])
    payload["manual_ticket_candidate_count"] = "not-a-count"
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync({**row, "payload": payload})

    status = DailyCandidateTrialService(db=db).get_status()

    assert "manual_order_ticket_candidate_count_invalid" in (
        status["excluded_days"][0]["blockers"]
    )


def test_daily_candidate_trial_blocks_same_day_input_conflict(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    days = _trading_days()
    _seed_verified_calendar(db, days)
    for day in days:
        _seed_qualifying_day(db, day=day, order_count=3)
    _seed_qualifying_day(db, day=days[-1], order_count=3, suffix="drifted")

    status = DailyCandidateTrialService(db=db).get_status()

    excluded = next(
        day for day in status["excluded_days"] if day["run_date"] == days[-1]
    )
    assert "daily_candidate_input_conflict" in excluded["blockers"]
    assert status["qualifying_trading_day_count"] == 19
    assert status["eligible_for_human_go_no_go_review"] is False


def test_daily_candidate_trial_excludes_run_started_after_reviewed_window(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    db.upsert_automation_run_sync(
        {
            **row,
            "started_at": f"{day}T14:00:00+08:00",
            "payload": json.loads(row["payload_json"]),
        }
    )

    status = DailyCandidateTrialService(db=db).get_status()

    assert status["qualifying_trading_day_count"] == 0
    assert (
        "daily_candidate_run_started_outside_reviewed_window"
        in status["excluded_days"][0]["blockers"]
    )


def test_daily_candidate_trial_replays_final_decision_window(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(row["payload_json"])
    payload["input_snapshot"]["decision_window"][
        "decision_generated_at"
    ] = f"{day}T14:00:00+08:00"
    payload["input_snapshot"]["decision_window"][
        "plan_generated_at"
    ] = f"{day}T14:00:01+08:00"
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync({**row, "payload": payload})

    status = DailyCandidateTrialService(db=db).get_status()

    blockers = status["excluded_days"][0]["blockers"]
    assert "daily_candidate_decision_generated_outside_window" in blockers
    assert "daily_candidate_plan_generated_outside_window" in blockers


def test_daily_candidate_trial_replays_quote_age_limit(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(row["payload_json"])
    stale_quote_at = f"{day}T09:20:00+08:00"
    snapshot = payload["input_snapshot"]
    snapshot["market_quote_timestamp"] = stale_quote_at
    snapshot["market_quote_age_seconds_at_decision"] = 900
    snapshot["market_quote_bindings"][0]["timestamp"] = stale_quote_at
    ticket = payload["manual_order_ticket_candidates"][0]
    ticket["market_quote"]["timestamp"] = stale_quote_at
    ticket["market_quote"]["age_seconds_at_decision"] = 900
    ticket["ticket_candidate_fingerprint"] = manual_ticket_candidate_fingerprint(ticket)
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync({**row, "payload": payload})

    status = DailyCandidateTrialService(db=db).get_status()

    blockers = status["excluded_days"][0]["blockers"]
    assert "daily_candidate_market_quote_too_old" in blockers
    assert "manual_order_ticket_candidate_0:market_quote_too_old" in blockers


def test_daily_candidate_trial_replays_account_truth_age_at_decision(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(row["payload_json"])
    snapshot = payload["input_snapshot"]
    snapshot["account_truth_captured_at"] = f"{day}T09:36:00+08:00"
    snapshot["account_truth_age_seconds_at_decision"] = 0
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync({**row, "payload": payload})

    status = DailyCandidateTrialService(db=db).get_status()

    blockers = status["excluded_days"][0]["blockers"]
    assert "daily_candidate_account_truth_age_invalid" in blockers
    assert "daily_candidate_account_truth_age_snapshot_mismatch" in blockers


def test_daily_candidate_trial_rejects_ticket_account_truth_binding_drift(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(row["payload_json"])
    ticket = payload["manual_order_ticket_candidates"][0]
    ticket["account_truth_binding"]["source_fingerprint"] = "d" * 64
    ticket["ticket_candidate_fingerprint"] = manual_ticket_candidate_fingerprint(ticket)
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync({**row, "payload": payload})

    status = DailyCandidateTrialService(db=db).get_status()

    assert (
        "manual_order_ticket_candidate_0:account_truth_binding_mismatch"
        in status["excluded_days"][0]["blockers"]
    )


def test_daily_candidate_trial_replays_frozen_strategy_gate_binding(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    _seed_verified_calendar(db, [day])
    _seed_qualifying_day(db, day=day, order_count=1)
    row = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(row["payload_json"])
    payload["input_snapshot"]["strategy_gate_bindings"][0][
        "dataset_replay_fingerprint"
    ] = "drifted"
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync({**row, "payload": payload})

    status = DailyCandidateTrialService(db=db).get_status()

    assert (
        "manual_order_ticket_candidate_0:dataset_replay_fingerprint_invalid"
        in status["excluded_days"][0]["blockers"]
    )


def test_daily_candidate_trial_starts_new_epoch_after_frozen_binding_change(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    days = _trading_days(30)
    _seed_verified_calendar(db, days)
    next_strategy = "strategy_advancement:" + "d" * 64
    next_fee_schedule = "reviewed_fee_schedule:" + "e" * 64
    for day in days[:10]:
        _seed_qualifying_day(db, day=day, order_count=3)
    for day in days[10:]:
        _seed_qualifying_day(
            db,
            day=day,
            order_count=3,
            strategy_advancement_ref=next_strategy,
            reviewed_fee_schedule_ref=next_fee_schedule,
        )

    status = DailyCandidateTrialService(db=db).get_status()

    assert status["trial_epoch_start_date"] == days[10]
    assert status["trial_epoch_id"]
    assert status["qualifying_trading_day_count"] == 20
    assert status["simulated_order_count"] == 60
    assert status["superseded_qualifying_day_count"] == 10
    assert status["strategy_advancement_refs"] == [next_strategy]
    assert status["reviewed_fee_schedule_refs"] == [next_fee_schedule]
    assert status["eligible_for_human_go_no_go_review"] is True
    assert "strategy_trial_binding_changed" not in status["blockers"]
    assert "fee_schedule_trial_binding_changed" not in status["blockers"]


def test_daily_candidate_trial_blocks_review_when_latest_day_is_not_qualifying(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    days = _trading_days(21)
    _seed_verified_calendar(db, days)
    for day in days:
        _seed_qualifying_day(db, day=day, order_count=3)
    latest = db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        run_date=days[-1],
        limit=1,
        offset=0,
    )[0]
    payload = json.loads(latest["payload_json"])
    payload["production_gate"] = {
        **payload["production_gate"],
        "status": "blocked",
        "blockers": ["current_strategy_evidence_drifted"],
    }
    payload["decision_outcome"] = "no_action"
    payload["manual_ticket_candidate_count"] = 0
    payload["manual_order_ticket_candidates"] = []
    payload["no_action_reasons"] = ["current_strategy_evidence_drifted"]
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    db.upsert_automation_run_sync(
        {**latest, "status": "risk_gate_failed", "payload": payload}
    )

    status = DailyCandidateTrialService(db=db).get_status()

    assert status["qualifying_trading_day_count"] == 20
    assert status["simulated_order_count"] == 60
    assert "latest_daily_candidate_not_qualifying" in status["blockers"]
    assert status["eligible_for_human_go_no_go_review"] is False


def test_daily_candidate_trial_does_not_merge_repeated_old_binding_epochs(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    days = _trading_days(15)
    _seed_verified_calendar(db, days)
    middle_strategy = "strategy_advancement:" + "d" * 64
    for day in days[:5]:
        _seed_qualifying_day(db, day=day)
    for day in days[5:10]:
        _seed_qualifying_day(
            db,
            day=day,
            strategy_advancement_ref=middle_strategy,
        )
    for day in days[10:]:
        _seed_qualifying_day(db, day=day)

    status = DailyCandidateTrialService(db=db).get_status()

    assert status["trial_epoch_start_date"] == days[10]
    assert status["qualifying_trading_day_count"] == 5
    assert status["superseded_qualifying_day_count"] == 10
    assert [day["run_date"] for day in status["qualifying_days"]] == days[10:]
    assert "qualifying_trading_days_insufficient" in status["blockers"]


def test_daily_candidate_trial_reads_complete_history_past_ui_page_limit(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    day = _trading_days()[0]
    for index in range(501):
        db.upsert_automation_run_sync(
            {
                "run_id": f"legacy-daily-candidate:{index}",
                "run_type": DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
                "run_date": day,
                "status": "no_candidates",
                "execution_mode": "paper_shadow",
                "started_at": f"{day}T09:35:00+08:00",
                "finished_at": f"{day}T09:35:01+08:00",
                "source_ref": None,
                "payload": {"schema_version": "legacy"},
            }
        )

    status = DailyCandidateTrialService(db=db).get_status()

    assert status["run_scan_truncated"] is False
    assert "daily_candidate_run_scan_truncated" not in status["blockers"]
    assert status["excluded_days"][0]["blockers"] == [
        "daily_candidate_contract_missing"
    ]


def test_daily_candidate_trial_review_is_exact_human_no_authority_record(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    days = _trading_days()
    _seed_verified_calendar(db, days)
    for day in days:
        _seed_qualifying_day(db, day=day, order_count=3)
    clock = lambda: datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)
    service = DailyCandidateTrialService(db=db, clock=clock)
    status = service.get_status()

    recorded = service.record_review(
        expected_trial_fingerprint=status["trial_fingerprint"],
        decision="go_to_bounded_manual_trial",
        reviewed_by="owner",
        note="Proceed only with separately bounded manual orders.",
        confirmation=DAILY_CANDIDATE_TRIAL_REVIEW_CONFIRMATION,
    )
    replay = service.record_review(
        expected_trial_fingerprint=status["trial_fingerprint"],
        decision="go_to_bounded_manual_trial",
        reviewed_by="owner",
        note="Proceed only with separately bounded manual orders.",
        confirmation=DAILY_CANDIDATE_TRIAL_REVIEW_CONFIRMATION,
    )

    assert recorded["status"] == "recorded"
    assert recorded["broker_submission_enabled"] is False
    assert recorded["authorizes_execution"] is False
    assert recorded["changes_capital_authority"] is False
    assert replay["review_id"] == recorded["review_id"]
    assert replay["reused"] is True
    reviewed_status = service.get_status()
    assert reviewed_status["status"] == (
        "human_go_to_bounded_manual_trial_recorded_without_authority"
    )


def test_daily_candidate_trial_rejects_go_before_evidence_threshold(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    days = _trading_days()
    _seed_verified_calendar(db, days)
    _seed_qualifying_day(db, day=days[0], order_count=1)
    service = DailyCandidateTrialService(db=db)
    status = service.get_status()

    with pytest.raises(DailyCandidateTrialReviewRejected) as exc_info:
        service.record_review(
            expected_trial_fingerprint=status["trial_fingerprint"],
            decision="go_to_bounded_manual_trial",
            reviewed_by="owner",
            note="Too early.",
            confirmation=DAILY_CANDIDATE_TRIAL_REVIEW_CONFIRMATION,
        )

    assert (
        "go_decision_exceeds_operating_evidence"
        in exc_info.value.evidence["rejection_reasons"]
    )
    assert exc_info.value.evidence["status"] == "rejected"
    assert exc_info.value.evidence["authorizes_execution"] is False
