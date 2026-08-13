from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from server.db import AppDatabase
from server.services.execution_batch_reconciliation import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    ExecutionBatchReconciliationRejected,
    ExecutionBatchReconciliationService,
    resolve_prior_batch_reconciliation,
)

NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)
RUN_ID = "execution-reconciliation:2026-07-10"


def _db(tmp_path) -> AppDatabase:
    db = AppDatabase(tmp_path / "execution-batch-reconciliation.db")
    db.init_sync()
    return db


def _seed_order(
    db: AppDatabase,
    *,
    order_id: str = "prior-order-1",
    status: str = "cancelled",
    execution_mode: str = "manual",
    strategy_id: str = "",
) -> None:
    payload = {"execution_mode": execution_mode}
    if strategy_id:
        db.upsert_action_task_sync(
            source_signal_id=9001,
            symbol="510300",
            title="AI shadow prior order",
            detail="exact strategy lineage fixture",
            direction="buy",
            urgency="normal",
            target_weight=0.01,
            price=6.0,
            strategy_id=strategy_id,
            timestamp=NOW.isoformat(),
            asset_class="fund",
        )
        action = db.get_action_tasks_sync(limit=1)[0]
        payload["gateway_evidence"] = {
            "research_evidence": {"evidence_ref": f"decision_action:{action['id']}"}
        }
    db.upsert_oms_order_sync(
        {
            "order_id": order_id,
            "intent_key": f"intent-{order_id}",
            "symbol": "510300",
            "side": "buy",
            "asset_class": "etf",
            "quantity": 100.0,
            "order_type": "limit",
            "limit_price": 6.0,
            "status": status,
            "broker_submission_enabled": False,
            "source": "deterministic_batch_test",
            "source_ref": "prior-controlled-batch",
            "payload": payload,
        }
    )


def _seed_reconciliation(
    db: AppDatabase,
    *,
    order_id: str = "prior-order-1",
    oms_status: str = "cancelled",
    suggested_action: str = "no_action",
    plan_paper_actual: dict | None = None,
) -> None:
    item_payload = {
        "oms_status": oms_status,
        "execution_mode": "manual",
    }
    if plan_paper_actual is not None:
        item_payload["plan_paper_actual_comparison"] = plan_paper_actual
    db.upsert_execution_reconciliation_run_sync(
        run_id=RUN_ID,
        run_date="2026-07-10",
        status="clear" if suggested_action == "no_action" else "open_items",
        item_count=1,
        open_item_count=0 if suggested_action == "no_action" else 1,
        payload={"schema_version": "karkinos.execution_reconciliation.v1"},
        items=[
            {
                "order_id": order_id,
                "item_status": "cancelled",
                "suggested_action": suggested_action,
                "gateway_event_count": 0,
                "broker_event_count": 0,
                "detail": "deterministic exact batch item",
                "payload": item_payload,
            }
        ],
    )


def _record_clear_batch(db: AppDatabase) -> dict:
    service = ExecutionBatchReconciliationService(db=db, clock=lambda: NOW)
    preview = service.preview(
        batch_id="prior-batch-1",
        order_ids=["prior-order-1"],
        reconciliation_run_id=RUN_ID,
    )
    return service.record(
        batch_id="prior-batch-1",
        order_ids=["prior-order-1"],
        reconciliation_run_id=RUN_ID,
        batch_reconciliation_fingerprint=preview["batch_reconciliation_fingerprint"],
        operator_label="local-owner",
        acknowledgement=EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    )


def _plan_paper_actual_pass() -> dict:
    core = {
        "schema_version": "karkinos.plan_paper_actual_comparison.v1",
        "status": "pass",
        "blockers": [],
        "differences": [],
        "persisted_evidence_only": True,
        "human_review_required": False,
        "authorizes_execution": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_change_capital_authority": True,
    }
    encoded = json.dumps(
        core,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {**core, "evidence_fingerprint": hashlib.sha256(encoded).hexdigest()}


def test_clear_exact_batch_is_append_only_reused_and_resolvable(tmp_path) -> None:
    db = _db(tmp_path)
    _seed_order(db)
    _seed_reconciliation(db)
    service = ExecutionBatchReconciliationService(db=db, clock=lambda: NOW)

    preview = service.preview(
        batch_id="prior-batch-1",
        order_ids=["prior-order-1"],
        reconciliation_run_id=RUN_ID,
    )
    recorded = _record_clear_batch(db)
    rerun = _record_clear_batch(db)
    resolved = service.resolve_recorded(recorded["batch_reconciliation_fingerprint"])

    assert preview["status"] == "clear"
    assert preview["batch_reconciliation_clear"] is True
    assert preview["orders"][0]["effective_terminal_status"] == "cancelled"
    assert recorded["record_status"] == "recorded_clear"
    assert recorded["persisted"] is True
    assert rerun["event_id"] == recorded["event_id"]
    assert rerun["reused"] is True
    assert resolved["status"] == "pass"
    assert resolved["authorizes_next_batch"] is False
    assert recorded["safety"]["does_not_submit_broker_order"] is True
    assert db.list_fills_sync(order_id="prior-order-1") == []


def test_batch_blocks_duplicate_open_or_nonterminal_order_evidence(tmp_path) -> None:
    db = _db(tmp_path)
    _seed_order(db, status="manually_confirmed")
    _seed_reconciliation(
        db,
        oms_status="manually_confirmed",
        suggested_action="review_order_state",
    )
    service = ExecutionBatchReconciliationService(db=db, clock=lambda: NOW)

    result = service.preview(
        batch_id="prior-batch-1",
        order_ids=["prior-order-1", "prior-order-1"],
        reconciliation_run_id=RUN_ID,
    )

    assert result["status"] == "blocked"
    assert "batch_order_ids_invalid_or_duplicate" in result["blockers"]
    assert "batch_oms_order_not_terminal:prior-order-1" in result["blockers"]
    assert "batch_reconciliation_item_not_clear:prior-order-1" in result["blockers"]
    assert result["authorizes_next_batch"] is False


def test_ai_shadow_batch_requires_exact_clear_plan_paper_actual_comparison(
    tmp_path,
) -> None:
    db = _db(tmp_path)
    strategy_id = "ai_formula_shadow:candidate-reviewed"
    _seed_order(db, strategy_id=strategy_id)
    _seed_reconciliation(db)
    service = ExecutionBatchReconciliationService(db=db, clock=lambda: NOW)

    missing = service.preview(
        batch_id="prior-ai-shadow-batch",
        order_ids=["prior-order-1"],
        reconciliation_run_id=RUN_ID,
    )
    _seed_reconciliation(db, plan_paper_actual=_plan_paper_actual_pass())
    clear = service.preview(
        batch_id="prior-ai-shadow-batch",
        order_ids=["prior-order-1"],
        reconciliation_run_id=RUN_ID,
    )

    assert missing["status"] == "blocked"
    assert (
        "batch_ai_shadow_plan_paper_actual_not_clear:prior-order-1"
        in missing["blockers"]
    )
    assert clear["status"] == "clear"
    assert clear["orders"][0]["strategy_id"] == strategy_id
    assert clear["orders"][0]["plan_paper_actual_comparison"]["required"] is True


def test_filled_batch_requires_real_fill_account_truth_and_same_run_linkage(
    tmp_path,
) -> None:
    db = _db(tmp_path)
    _seed_order(db, status="filled")
    _seed_reconciliation(db, oms_status="filled")
    db.record_fill_sync(
        fill_id="real-fill-1",
        order_id="prior-order-1",
        timestamp=NOW.isoformat(),
        symbol="510300",
        side="buy",
        fill_price=6.0,
        fill_quantity=100.0,
        execution_mode="manual",
        provider_name="reviewed-local-broker",
        broker_order_id="broker-order-1",
        source="reconciled_real_fill",
        metadata={
            "account_truth_import_run_id": "account-truth-import-1",
            "execution_reconciliation_run_id": RUN_ID,
        },
    )
    service = ExecutionBatchReconciliationService(db=db, clock=lambda: NOW)

    clear = service.preview(
        batch_id="prior-batch-1",
        order_ids=["prior-order-1"],
        reconciliation_run_id=RUN_ID,
    )
    db.record_fill_sync(
        fill_id="real-fill-1",
        order_id="prior-order-1",
        timestamp=NOW.isoformat(),
        symbol="510300",
        side="buy",
        fill_price=6.0,
        fill_quantity=100.0,
        execution_mode="manual",
        provider_name="reviewed-local-broker",
        broker_order_id="broker-order-1",
        source="reconciled_real_fill",
        metadata={},
    )
    blocked = service.preview(
        batch_id="prior-batch-1",
        order_ids=["prior-order-1"],
        reconciliation_run_id=RUN_ID,
    )

    assert clear["status"] == "clear"
    assert clear["orders"][0]["real_fill_quantity"] == "100"
    assert blocked["status"] == "blocked"
    assert "batch_real_fill_linkage_incomplete:prior-order-1" in blocked["blockers"]
    assert (
        "batch_real_fill_reconciliation_mismatch:prior-order-1" in blocked["blockers"]
    )


def test_record_rejects_stale_fingerprint_and_audits_attempt(tmp_path) -> None:
    db = _db(tmp_path)
    _seed_order(db)
    _seed_reconciliation(db)
    service = ExecutionBatchReconciliationService(db=db, clock=lambda: NOW)

    with pytest.raises(ExecutionBatchReconciliationRejected) as exc_info:
        service.record(
            batch_id="prior-batch-1",
            order_ids=["prior-order-1"],
            reconciliation_run_id=RUN_ID,
            batch_reconciliation_fingerprint="0" * 64,
            operator_label="local-owner",
            acknowledgement=EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
        )

    assert exc_info.value.evidence["record_status"] == "rejected"
    assert exc_info.value.evidence["authorizes_next_batch"] is False
    assert service.list_records(limit=10)[0]["record_status"] == "rejected"


def test_recorded_batch_fails_resolution_after_bound_source_changes(tmp_path) -> None:
    db = _db(tmp_path)
    _seed_order(db)
    _seed_reconciliation(db)
    recorded = _record_clear_batch(db)
    db.update_oms_order_status_sync(
        order_id="prior-order-1",
        status="reconciled",
    )
    service = ExecutionBatchReconciliationService(db=db, clock=lambda: NOW)

    resolved = service.resolve_recorded(recorded["batch_reconciliation_fingerprint"])

    assert resolved["status"] == "blocked"
    assert "prior_batch_reconciliation_source_changed" in resolved["blockers"]
    assert resolved["authorizes_next_batch"] is False


def test_prior_batch_must_match_the_current_strategy(tmp_path) -> None:
    db = _db(tmp_path)
    _seed_order(db, strategy_id="ai_formula_shadow:reviewed-candidate")
    _seed_reconciliation(db, plan_paper_actual=_plan_paper_actual_pass())
    recorded = _record_clear_batch(db)

    matching, matching_blockers = resolve_prior_batch_reconciliation(
        db=db,
        fingerprint=recorded["batch_reconciliation_fingerprint"],
        expected_strategy_id="ai_formula_shadow:reviewed-candidate",
    )
    unrelated, unrelated_blockers = resolve_prior_batch_reconciliation(
        db=db,
        fingerprint=recorded["batch_reconciliation_fingerprint"],
        expected_strategy_id="ai_formula_shadow:another-candidate",
    )

    assert matching["status"] == "pass"
    assert matching["strategy_binding_complete"] is True
    assert matching["strategy_ids"] == ["ai_formula_shadow:reviewed-candidate"]
    assert matching_blockers == []
    assert unrelated["status"] == "blocked"
    assert "prior_batch_reconciliation_strategy_mismatch" in unrelated_blockers
    assert unrelated["authorizes_next_batch"] is False


def test_prior_batch_without_strategy_lineage_fails_closed(tmp_path) -> None:
    db = _db(tmp_path)
    _seed_order(db)
    _seed_reconciliation(db)
    recorded = _record_clear_batch(db)

    resolved, blockers = resolve_prior_batch_reconciliation(
        db=db,
        fingerprint=recorded["batch_reconciliation_fingerprint"],
        expected_strategy_id="reviewed-strategy",
    )

    assert resolved["status"] == "blocked"
    assert resolved["strategy_binding_complete"] is False
    assert "prior_batch_reconciliation_strategy_binding_incomplete" in blockers
    assert "prior_batch_reconciliation_strategy_mismatch" in blockers
    assert resolved["authorizes_next_batch"] is False
