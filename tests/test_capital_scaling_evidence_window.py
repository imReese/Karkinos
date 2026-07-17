from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from server.db import AppDatabase
from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
)
from server.services.capital_scaling_evidence_window import (
    CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
    MAX_SOURCE_ROWS,
    CapitalScalingEvidenceWindowService,
)
from server.services.controlled_session_runtime_rate_limiter import (
    CONTROLLED_SESSION_RATE_ADMISSION_SCHEMA_VERSION,
)
from server.services.execution_batch_reconciliation import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    ExecutionBatchReconciliationService,
)

START = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
_FIXED_DB_NOW = datetime(
    2026,
    7,
    10,
    17,
    0,
    tzinfo=timezone(timedelta(hours=8)),
)


class _FrozenDatabaseDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return _FIXED_DB_NOW.replace(tzinfo=None)
        return _FIXED_DB_NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def _freeze_database_wall_clock(monkeypatch) -> None:
    monkeypatch.setattr("server.db.datetime", _FrozenDatabaseDateTime)


def _account_truth_source(observed_at: datetime, suffix: str) -> dict:
    return {
        "schema_version": "karkinos.account_truth.score.v1",
        "status": "available",
        "import_run_id": f"import-{suffix}",
        "created_at": observed_at.isoformat(),
        "score": 100,
        "gate_status": "pass",
        "cash_status": "pass",
        "position_status": "pass",
        "fee_status": "pass",
        "cost_basis_status": "pass",
        "data_freshness_status": "fresh",
        "unresolved_mismatch_count": 0,
        "resolved_review_count": 0,
        "account_id": "must-never-be-persisted",
        "source_name": "private-statement.csv",
    }


def _service_with_mutable_source(tmp_path):
    db = AppDatabase(tmp_path / "capital-scaling-window.db")
    db.init_sync()
    state = {
        "now": START + timedelta(hours=1, minutes=5),
        "source": _account_truth_source(START + timedelta(hours=1), "start"),
    }
    service = CapitalScalingEvidenceWindowService(
        db=db,
        account_truth_provider=lambda: state["source"],
        clock=lambda: state["now"],
    )
    return db, service, state


def _record_boundary_account_truth(service, state) -> tuple[dict, dict]:
    first = service.record_account_truth_snapshot()
    state["source"] = _account_truth_source(END - timedelta(hours=1), "end")
    state["now"] = END - timedelta(minutes=55)
    second = service.record_account_truth_snapshot()
    return first, second


def _seed_portfolio_boundaries(db: AppDatabase) -> None:
    for snapshot_id, observed_at, total_equity in (
        ("portfolio-start", START + timedelta(hours=2), "10000"),
        ("portfolio-end", END - timedelta(hours=2), "10800"),
    ):
        db.append_event_sync(
            event_type="portfolio.snapshot.created",
            timestamp=observed_at.isoformat(),
            entity_type="portfolio",
            entity_id="default",
            source="portfolio_snapshots",
            source_ref=snapshot_id,
            payload={
                "snapshot_id": snapshot_id,
                "timestamp": observed_at.isoformat(),
                "cash": "5000",
                "total_equity": total_equity,
                "positions": [],
                "allocation": {},
            },
        )


def _seed_reconciled_real_fill(db: AppDatabase) -> None:
    db.record_fill_sync(
        fill_id="real-fill-1",
        order_id="real-order-1",
        timestamp=(START + timedelta(days=9, hours=8)).isoformat(),
        symbol="510300",
        side="buy",
        fill_price=6.0,
        fill_quantity=100.0,
        commission=5.0,
        slippage=0.3,
        asset_class="etf",
        execution_mode="manual",
        provider_name="reviewed-local-broker",
        broker_order_id="broker-order-1",
        source="broker_evidence_reconciled_fill",
        source_ref="broker-fill-1",
        metadata={
            "account_truth_import_run_id": "import-end",
            "execution_reconciliation_run_id": "execution-reconciliation:2026-07-10",
            "capacity_model_ref": "capacity_model:cn-etf-v1",
            "market_data_ref": "market_snapshot:510300:2026-07-10",
            "capacity_limit_notional": "1000",
            "available_liquidity_notional": "1200",
        },
    )


def _seed_operating_sample(
    db: AppDatabase,
    *,
    include_reconciliation: bool = True,
    include_batch: bool = True,
) -> None:
    observed_at = START + timedelta(days=9, hours=9)
    db.append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
        timestamp=observed_at.isoformat(),
        entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
        entity_id="healthy-soak-2026-07-10",
        source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
        source_ref="reviewed-local-broker",
        payload={
            "observed_at": observed_at.isoformat(),
            "trading_day": "2026-07-10",
            "soak_status": "healthy",
            "qualifies_for_healthy_soak_day": True,
            "blockers": [],
        },
    )
    db.upsert_oms_order_sync(
        {
            "order_id": "real-order-1",
            "intent_key": "capital-scaling-real-order-1",
            "symbol": "510300",
            "side": "buy",
            "asset_class": "etf",
            "quantity": 100.0,
            "order_type": "limit",
            "limit_price": 6.0,
            "status": "filled",
            "broker_submission_enabled": False,
            "source": "capital_scaling_test_evidence",
            "source_ref": "manual-review-1",
            "payload": {"execution_mode": "manual"},
        }
    )
    if include_reconciliation:
        db.upsert_execution_reconciliation_run_sync(
            run_id="execution-reconciliation:2026-07-10",
            run_date="2026-07-10",
            status="clear",
            item_count=1,
            open_item_count=0,
            payload={"schema_version": "karkinos.execution_reconciliation.v1"},
            items=[
                {
                    "order_id": "real-order-1",
                    "item_status": "matched_terminal",
                    "suggested_action": "no_action",
                    "gateway_event_count": 1,
                    "broker_event_count": 1,
                    "detail": "deterministic reconciled test order",
                    "payload": {
                        "oms_status": "filled",
                        "execution_mode": "manual",
                    },
                }
            ],
        )
        if include_batch:
            batch_service = ExecutionBatchReconciliationService(
                db=db,
                clock=lambda: observed_at,
            )
            batch_preview = batch_service.preview(
                batch_id="capital-scaling-batch-2026-07-10",
                order_ids=["real-order-1"],
                reconciliation_run_id="execution-reconciliation:2026-07-10",
            )
            batch_service.record(
                batch_id="capital-scaling-batch-2026-07-10",
                order_ids=["real-order-1"],
                reconciliation_run_id="execution-reconciliation:2026-07-10",
                batch_reconciliation_fingerprint=batch_preview[
                    "batch_reconciliation_fingerprint"
                ],
                operator_label="deterministic-test-owner",
                acknowledgement=EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
            )
    db.record_order_sync(
        order_id="paper-shadow-order-1",
        timestamp=observed_at.isoformat(),
        symbol="510300",
        side="buy",
        order_type="limit",
        quantity=100.0,
        price=6.0,
        asset_class="etf",
        execution_mode="paper_shadow",
        status="filled",
        source="paper_shadow_daily",
        source_ref="paper-shadow-run-1",
        payload={"divergence_status": "within_expectations"},
    )


def test_account_truth_snapshot_is_sanitized_append_only_and_reused(tmp_path) -> None:
    db, service, _ = _service_with_mutable_source(tmp_path)

    preview = service.preview_account_truth_snapshot()
    recorded = service.record_account_truth_snapshot()
    rerun = service.record_account_truth_snapshot()

    assert preview["status"] == "clear"
    assert preview["persisted"] is False
    assert recorded["persisted"] is True
    assert recorded["reused"] is False
    assert rerun["event_id"] == recorded["event_id"]
    assert rerun["reused"] is True
    assert (
        len(
            db.list_events_sync(
                event_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE
            )
        )
        == 1
    )
    serialized = json.dumps(recorded, sort_keys=True)
    assert "must-never-be-persisted" not in serialized
    assert "private-statement.csv" not in serialized
    assert "account_id" not in serialized


def test_account_truth_snapshot_fails_closed_when_capture_is_not_timely(
    tmp_path,
) -> None:
    _, service, state = _service_with_mutable_source(tmp_path)
    state["now"] = START + timedelta(hours=2)

    preview = service.preview_account_truth_snapshot()

    assert preview["status"] == "blocked"
    assert "account_truth_capture_lag_exceeded" in preview["blockers"]
    assert preview["does_not_issue_capital_authorization"] is True


def test_clear_evidence_window_computes_after_cost_incident_and_capacity_facts(
    tmp_path,
) -> None:
    db, service, state = _service_with_mutable_source(tmp_path)
    _record_boundary_account_truth(service, state)
    _seed_portfolio_boundaries(db)
    _seed_reconciled_real_fill(db)
    _seed_operating_sample(db)

    preview = service.preview_window(
        review_window_start=START,
        review_window_end=END,
    )
    recorded = service.record_window(
        review_window_start=START,
        review_window_end=END,
    )
    rerun = service.record_window(
        review_window_start=START,
        review_window_end=END,
    )

    assert preview["status"] == "clear"
    assert preview["facts"]["account_truth"]["status"] == "clear"
    assert preview["facts"]["after_cost"]["metrics"]["after_cost_return_pct"] == "0.08"
    assert preview["facts"]["incident"]["metrics"] == {
        "critical_incident_count": 0,
        "policy_violation_count": 0,
        "broker_disconnect_count": 0,
    }
    capacity = preview["facts"]["capacity"]["metrics"]
    assert capacity["fill_count"] == 1
    assert capacity["average_slippage_bps"] == "5"
    assert capacity["p95_slippage_bps"] == "5"
    assert capacity["capacity_utilization_pct"] == "0.6"
    assert capacity["liquidity_utilization_pct"] == "0.5"
    operating_sample = preview["facts"]["operating_sample"]["metrics"]
    assert operating_sample["reviewed_trading_days"] == 1
    assert operating_sample["order_count"] == 1
    assert operating_sample["filled_order_count"] == 1
    assert operating_sample["rejected_order_count"] == 0
    assert operating_sample["partial_fill_count"] == 0
    assert operating_sample["unresolved_reconciliation_count"] == 0
    assert operating_sample["paper_shadow_divergence_count"] == 0
    assert operating_sample["max_drawdown_pct"] == "0"
    execution_scope = preview["facts"]["execution_scope"]
    assert execution_scope["status"] == "clear"
    assert execution_scope["metrics"]["sampled_order_count"] == 1
    assert execution_scope["metrics"]["exact_batch_bound_order_count"] == 1
    assert execution_scope["metrics"]["unbound_order_count"] == 0
    assert recorded["persisted"] is True
    assert rerun["event_id"] == recorded["event_id"]
    assert rerun["reused"] is True
    assert (
        len(db.list_events_sync(event_type=CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE))
        == 1
    )
    assert recorded["authority_change_applied"] is False
    assert recorded["does_not_submit_or_cancel_broker_order"] is True


def test_execution_scope_blocks_unbound_operating_sample_order(tmp_path) -> None:
    db, service, state = _service_with_mutable_source(tmp_path)
    _record_boundary_account_truth(service, state)
    _seed_portfolio_boundaries(db)
    _seed_reconciled_real_fill(db)
    _seed_operating_sample(db, include_batch=False)

    result = service.preview_window(
        review_window_start=START,
        review_window_end=END,
    )

    execution_scope = result["facts"]["execution_scope"]
    assert execution_scope["status"] == "blocked"
    assert "execution_scope_order_unbound:real-order-1" in execution_scope["blockers"]
    assert execution_scope["metrics"]["unbound_order_count"] == 1
    assert result["automatic_scale_up_enabled"] is False
    assert result["authority_change_applied"] is False


def test_execution_scope_rechecks_exact_batch_source_drift(tmp_path) -> None:
    db, service, state = _service_with_mutable_source(tmp_path)
    _record_boundary_account_truth(service, state)
    _seed_portfolio_boundaries(db)
    _seed_reconciled_real_fill(db)
    _seed_operating_sample(db)
    db.upsert_oms_order_sync(
        {
            "order_id": "real-order-1",
            "intent_key": "capital-scaling-real-order-1",
            "symbol": "510300",
            "side": "buy",
            "asset_class": "etf",
            "quantity": 100.0,
            "order_type": "limit",
            "limit_price": 6.0,
            "status": "filled",
            "broker_submission_enabled": False,
            "source": "capital_scaling_test_evidence",
            "source_ref": "changed-after-batch-recording",
            "payload": {"execution_mode": "manual"},
        }
    )

    result = service.preview_window(
        review_window_start=START,
        review_window_end=END,
    )

    execution_scope = result["facts"]["execution_scope"]
    assert execution_scope["status"] == "blocked"
    assert any(
        blocker.startswith("execution_batch_not_current_clear:")
        for blocker in execution_scope["blockers"]
    )
    assert "execution_scope_order_unbound:real-order-1" in execution_scope["blockers"]
    assert result["automatic_scale_up_enabled"] is False


def test_execution_scope_accepts_exact_persisted_runtime_admission(
    monkeypatch,
    tmp_path,
) -> None:
    db, service, state = _service_with_mutable_source(tmp_path)
    _record_boundary_account_truth(service, state)
    _seed_portfolio_boundaries(db)
    _seed_reconciled_real_fill(db)
    _seed_operating_sample(db, include_batch=False)
    admitted_at = START + timedelta(days=9, hours=7, minutes=59)
    admitted_at_epoch_ms = int(admitted_at.timestamp() * 1000)
    admission = {
        "schema_version": CONTROLLED_SESSION_RATE_ADMISSION_SCHEMA_VERSION,
        "admission_id": "a" * 64,
        "session_id": "session-1",
        "session_fingerprint": "b" * 64,
        "reservation_id": "reservation-1",
        "authorization_id": "authorization-1",
        "account_alias": "review-account",
        "strategy_id": "review-strategy",
        "order_id": "real-order-1",
        "request_id": "c" * 64,
        "status": "admitted",
        "runtime_admission_granted": True,
        "runtime_live_gates_verified": True,
        "authorizes_broker_submission": False,
    }
    admission_row = {
        **{
            key: admission[key]
            for key in (
                "admission_id",
                "session_id",
                "session_fingerprint",
                "reservation_id",
                "authorization_id",
                "account_alias",
                "strategy_id",
                "order_id",
                "request_id",
                "status",
            )
        },
        "admitted_at": admitted_at.isoformat(),
        "admitted_at_epoch_ms": admitted_at_epoch_ms,
        "payload_json": json.dumps(admission, sort_keys=True),
    }
    runtime_session = {
        "session_id": "session-1",
        "session_fingerprint": "b" * 64,
        "reservation_id": "reservation-1",
        "authorization_id": "authorization-1",
        "account_alias": "review-account",
        "strategy_id": "review-strategy",
        "effective_at_epoch_ms": admitted_at_epoch_ms - 60_000,
        "expires_at_epoch_ms": admitted_at_epoch_ms + 60_000,
        "status": "revoked",
    }
    monkeypatch.setattr(
        db,
        "list_controlled_session_rate_admissions_sync",
        lambda **_: [admission_row],
    )
    monkeypatch.setattr(
        db,
        "get_controlled_session_runtime_session_sync",
        lambda session_id: runtime_session if session_id == "session-1" else None,
    )

    result = service.preview_window(
        review_window_start=START,
        review_window_end=END,
    )

    execution_scope = result["facts"]["execution_scope"]
    assert execution_scope["status"] == "clear"
    assert execution_scope["metrics"]["runtime_session_bound_order_count"] == 1
    assert execution_scope["metrics"]["exact_batch_bound_order_count"] == 0
    assert execution_scope["metrics"]["runtime_session_count"] == 1
    assert result["authority_change_applied"] is False
    assert result["does_not_submit_or_cancel_broker_order"] is True


def test_window_blocks_missing_boundaries_and_incomplete_real_fill_metadata(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-window.db")
    db.init_sync()
    db.record_fill_sync(
        fill_id="incomplete-real-fill",
        order_id="real-order-1",
        timestamp=(START + timedelta(days=10)).isoformat(),
        symbol="510300",
        side="buy",
        fill_price=6.0,
        fill_quantity=100.0,
        execution_mode="manual",
        provider_name="reviewed-local-broker",
        broker_order_id="broker-order-1",
        source="broker_evidence_reconciled_fill",
        metadata={},
    )
    service = CapitalScalingEvidenceWindowService(db=db, clock=lambda: END)

    result = service.preview_window(
        review_window_start=START,
        review_window_end=END,
    )

    assert result["status"] == "blocked"
    assert "account_truth:start_account_truth_snapshot_missing" in result["blockers"]
    assert "after_cost:portfolio_boundary_snapshots_missing" in result["blockers"]
    assert "capacity:real_fill_capacity_metadata_incomplete" in result["blockers"]
    assert result["facts"]["incident"]["status"] == "clear"
    assert result["authority_change_applied"] is False


def test_incident_fact_counts_persisted_critical_policy_and_disconnect_events(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-window.db")
    db.init_sync()
    observed_at = _FIXED_DB_NOW.astimezone(timezone.utc)
    db.upsert_automation_alert_sync(
        alert_key="critical:test",
        severity="critical",
        category="test",
        title="critical evidence",
        detail="synthetic deterministic incident",
        source="test",
        source_ref="incident-1",
        payload={},
    )
    db.record_broker_gateway_event_sync(
        gateway_id="live_disabled",
        event_type="live_submission_rejected",
        order_id="order-1",
        status="rejected",
        payload={"submitted_to_broker": False},
    )
    db.append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
        timestamp=observed_at.isoformat(),
        entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
        entity_id="soak-disconnect",
        source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
        source_ref="fixture-readonly",
        payload={
            "observed_at": observed_at.isoformat(),
            "soak_status": "blocked",
            "blockers": ["connector_unavailable"],
        },
    )
    service = CapitalScalingEvidenceWindowService(db=db, clock=lambda: observed_at)

    result = service.preview_window(
        review_window_start=observed_at - timedelta(days=1),
        review_window_end=observed_at + timedelta(days=1),
    )

    incident = result["facts"]["incident"]
    assert incident["status"] == "clear"
    assert incident["metrics"] == {
        "critical_incident_count": 1,
        "policy_violation_count": 1,
        "broker_disconnect_count": 1,
    }
    assert result["status"] == "blocked"
    assert result["automatic_scale_up_enabled"] is False


def test_operating_sample_blocks_missing_reconciliation_coverage(tmp_path) -> None:
    db, service, state = _service_with_mutable_source(tmp_path)
    _record_boundary_account_truth(service, state)
    _seed_portfolio_boundaries(db)
    _seed_reconciled_real_fill(db)
    _seed_operating_sample(db, include_reconciliation=False)

    result = service.preview_window(
        review_window_start=START,
        review_window_end=END,
    )

    operating_sample = result["facts"]["operating_sample"]
    assert operating_sample["status"] == "blocked"
    assert "execution_reconciliation_sample_missing" in operating_sample["blockers"]
    assert "reconciliation_latency_sample_missing" in operating_sample["blockers"]
    assert result["authority_change_applied"] is False


def test_operating_sample_keeps_rejected_partial_and_cancelled_outcomes_distinct(
    tmp_path,
) -> None:
    db, service, state = _service_with_mutable_source(tmp_path)
    _record_boundary_account_truth(service, state)
    _seed_portfolio_boundaries(db)
    _seed_reconciled_real_fill(db)
    _seed_operating_sample(db)
    for order_id, status_path in (
        ("rejected-order", ("rejected", "reconciled")),
        ("partial-cancelled-order", ("partially_filled", "cancelled", "reconciled")),
    ):
        db.upsert_oms_order_sync(
            {
                "order_id": order_id,
                "intent_key": f"capital-scaling-{order_id}",
                "symbol": "510300",
                "side": "buy",
                "asset_class": "etf",
                "quantity": 100.0,
                "order_type": "limit",
                "limit_price": 6.0,
                "status": "reconciled",
                "broker_submission_enabled": False,
                "source": "capital_scaling_test_evidence",
                "source_ref": "manual-review-variants",
                "payload": {"execution_mode": "manual"},
            }
        )
        previous = "accepted"
        for status in status_path:
            db.record_oms_transition_sync(
                order_id=order_id,
                from_status=previous,
                to_status=status,
                reason="deterministic terminal-outcome evidence",
                actor="test-operator",
            )
            previous = status
    db.record_fill_sync(
        fill_id="partial-real-fill",
        order_id="partial-cancelled-order",
        timestamp=(START + timedelta(days=9, hours=8, minutes=30)).isoformat(),
        symbol="510300",
        side="buy",
        fill_price=6.0,
        fill_quantity=40.0,
        commission=2.0,
        slippage=0.12,
        asset_class="etf",
        execution_mode="manual",
        provider_name="reviewed-local-broker",
        broker_order_id="broker-order-partial",
        source="broker_evidence_reconciled_fill",
        source_ref="broker-fill-partial",
        metadata={
            "account_truth_import_run_id": "import-end",
            "execution_reconciliation_run_id": ("execution-reconciliation:2026-07-10"),
            "capacity_model_ref": "capacity_model:cn-etf-v1",
            "market_data_ref": "market_snapshot:510300:2026-07-10:partial",
            "capacity_limit_notional": "1000",
            "available_liquidity_notional": "1200",
        },
    )
    db.upsert_execution_reconciliation_run_sync(
        run_id="execution-reconciliation:2026-07-10",
        run_date="2026-07-10",
        status="clear",
        item_count=3,
        open_item_count=0,
        payload={"schema_version": "karkinos.execution_reconciliation.v1"},
        items=[
            {
                "order_id": order_id,
                "item_status": "matched_terminal",
                "suggested_action": "no_action",
                "detail": "deterministic outcome coverage",
            }
            for order_id in (
                "real-order-1",
                "rejected-order",
                "partial-cancelled-order",
            )
        ],
    )
    observed_at = START + timedelta(days=9, hours=9)
    db.record_order_sync(
        order_id="paper-shadow-order-1",
        timestamp=observed_at.isoformat(),
        symbol="510300",
        side="buy",
        order_type="limit",
        quantity=100.0,
        price=6.0,
        asset_class="etf",
        execution_mode="paper_shadow",
        status="filled",
        source="paper_shadow_daily",
        source_ref="paper-shadow-run-1",
        payload={"divergence_status": "diverged"},
    )

    result = service.preview_window(
        review_window_start=START,
        review_window_end=END,
    )

    operating_sample = result["facts"]["operating_sample"]
    assert operating_sample["status"] == "clear"
    assert operating_sample["metrics"]["order_count"] == 3
    assert operating_sample["metrics"]["filled_order_count"] == 1
    assert operating_sample["metrics"]["rejected_order_count"] == 1
    assert operating_sample["metrics"]["partial_fill_count"] == 1
    assert operating_sample["metrics"]["cancelled_or_expired_order_count"] == 1
    assert operating_sample["metrics"]["paper_shadow_divergence_count"] == 1


def test_unitized_drawdown_removes_external_deposit_effect(tmp_path) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-drawdown.db")
    db.init_sync()
    for snapshot_id, observed_at, total_equity in (
        ("drawdown-start", START + timedelta(days=1), "1000"),
        ("drawdown-after-deposit", START + timedelta(days=2), "2000"),
        ("drawdown-loss", START + timedelta(days=3), "1800"),
    ):
        db.append_event_sync(
            event_type="portfolio.snapshot.created",
            timestamp=observed_at.isoformat(),
            entity_type="portfolio",
            entity_id="default",
            source="portfolio_snapshots",
            source_ref=snapshot_id,
            payload={
                "snapshot_id": snapshot_id,
                "timestamp": observed_at.isoformat(),
                "total_equity": total_equity,
            },
        )
    asyncio.run(
        db.add_cash_flow(
            (START + timedelta(days=1, hours=12)).isoformat(),
            1000.0,
            "deposit",
            "deterministic unitization test",
        )
    )
    service = CapitalScalingEvidenceWindowService(db=db, clock=lambda: END)

    drawdown, blockers, source_refs = service._unitized_drawdown(
        start=START,
        end=END,
    )

    assert blockers == []
    assert drawdown is not None
    assert str(drawdown.normalize()) == "0.1"
    assert any(ref.startswith("cash_flow:") for ref in source_refs)


def test_truncated_source_scan_fails_closed(monkeypatch, tmp_path) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-window.db")
    db.init_sync()
    monkeypatch.setattr(
        db,
        "list_fills_sync",
        lambda **_: [{} for _ in range(MAX_SOURCE_ROWS)],
    )
    service = CapitalScalingEvidenceWindowService(db=db, clock=lambda: END)

    result = service.preview_window(
        review_window_start=START,
        review_window_end=END,
    )

    assert "capacity:fill_scan_truncated" in result["blockers"]
    assert result["facts"]["capacity"]["status"] == "blocked"
    assert result["automatic_scale_up_enabled"] is False
