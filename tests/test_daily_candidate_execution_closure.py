from __future__ import annotations

from server.ai_runtime.contracts import content_fingerprint
from server.db import AppDatabase
from server.services.daily_candidate_execution_closure import (
    build_daily_candidate_execution_closure,
    project_daily_candidate_execution_evidence_summary,
    verify_daily_candidate_execution_closure,
)
from server.services.execution_reconciliation import ExecutionReconciliationService
from server.services.oms import OmsService


def _db_and_oms(tmp_path) -> tuple[AppDatabase, OmsService]:
    db = AppDatabase(tmp_path / "daily-candidate-execution-closure.db")
    db.init_sync()
    return db, OmsService(db=db)


def _order(oms: OmsService) -> dict:
    return oms.create_order_intent(
        intent_key="daily:2026-08-14:600519:buy",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=10.0,
        source="daily_trading_plan",
        source_ref="action:1",
    )


def test_execution_closure_is_not_required_without_prior_production_orders(
    tmp_path,
) -> None:
    db, _oms = _db_and_oms(tmp_path)

    result = build_daily_candidate_execution_closure(db)

    assert result["status"] == "not_required"
    assert result["production_order_count"] == 0
    assert result["blockers"] == []
    assert len(result["evidence_fingerprint"]) == 64
    assert verify_daily_candidate_execution_closure(result) is True

    tampered = {**result, "status": "pass"}
    assert verify_daily_candidate_execution_closure(tampered) is False


def test_execution_closure_blocks_order_without_reconciliation(tmp_path) -> None:
    db, oms = _db_and_oms(tmp_path)
    _order(oms)

    result = build_daily_candidate_execution_closure(db)

    assert result["status"] == "blocked"
    assert result["production_order_count"] == 1
    assert "execution_reconciliation_item_missing" in result["orders"][0]["blockers"]
    assert "plan_paper_actual_comparison_missing" in result["orders"][0]["blockers"]


def test_execution_closure_accepts_current_no_fill_terminal_reconciliation(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _order(oms)
    oms.transition_order(
        order["order_id"],
        to_status="cancelled",
        reason="operator cancelled before broker execution",
        actor="owner",
    )
    ExecutionReconciliationService(db=db).run_reconciliation(run_date="2026-08-14")

    result = build_daily_candidate_execution_closure(db)

    assert result["status"] == "pass"
    assert result["production_order_count"] == 1
    assert result["clear_order_count"] == 1
    assert result["orders"][0]["reconciliation_item_status"] == "cancelled"


def test_execution_closure_replays_actual_comparison_from_current_sources(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _order(oms)
    db.upsert_execution_reconciliation_run_sync(
        run_id="execution-reconciliation:tampered",
        run_date="2026-08-14",
        status="clear",
        item_count=1,
        open_item_count=0,
        payload={"schema_version": "karkinos.execution_reconciliation.v1"},
        items=[
            {
                "order_id": order["order_id"],
                "item_status": "synthetic_clear",
                "suggested_action": "no_action",
                "detail": "fixture",
                "payload": {
                    "plan_paper_actual_comparison": {
                        "schema_version": "karkinos.plan_paper_actual_comparison.v1",
                        "status": "pass",
                        "actual": {"import_run_ids": ["import-1"]},
                        "evidence_fingerprint": "a" * 64,
                    }
                },
            }
        ],
    )

    result = build_daily_candidate_execution_closure(db)

    assert result["status"] == "blocked"
    assert (
        "plan_paper_actual_current_source_not_pass" in result["orders"][0]["blockers"]
    )
    assert "plan_paper_actual_current_source_changed" in result["orders"][0]["blockers"]


def test_execution_summary_counts_actual_without_trial_credit() -> None:
    closure = {
        "schema_version": "karkinos.daily_candidate_execution_closure.v1",
        "status": "pass",
        "production_order_count": 1,
        "clear_order_count": 1,
        "scan_truncated": False,
        "orders": [
            {
                "order_ref": "a" * 16,
                "oms_status": "reconciled",
                "reconciliation_item_status": "clear",
                "plan_paper_actual_status": "pass",
                "plan_paper_actual_fingerprint": "b" * 64,
                "status": "pass",
                "blockers": [],
            }
        ],
        "blockers": [],
        "persisted_evidence_only": True,
        "provider_contact_performed": False,
        "manual_review_required": False,
        "authorizes_execution": False,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_change_capital_authority": True,
    }
    closure["evidence_fingerprint"] = content_fingerprint(closure)

    summary = project_daily_candidate_execution_evidence_summary(closure)

    assert summary["status"] == "pass"
    assert summary["reconciled_actual_order_count"] == 1
    assert summary["reconciled_no_fill_order_count"] == 0
    assert summary["comparison_coverage_complete"] is True
    assert summary["actual_orders_attributed_to_trial"] is False
    assert summary["actual_orders_count_toward_simulated_trial_threshold"] is False
