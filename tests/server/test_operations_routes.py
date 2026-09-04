from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from analytics.acceptance_audit_report import build_acceptance_audit_export
from server.db import AppDatabase
from server.routes import operations as operations_routes
from tests.paper_shadow_fixtures import insert_paper_shadow_evidence


def _endpoint(path: str, method: str = "GET"):
    router = operations_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def _allow_paper_shadow_evaluation(monkeypatch) -> None:
    _freeze_valuation_clock(monkeypatch)
    monkeypatch.setattr(
        "server.services.decision_application._account_truth_gate_evidence",
        lambda state: {
            "gate_status": "pass",
            "data_freshness_status": "fresh",
            "unresolved_mismatch_count": 0,
            "import_run_id": "fixture-import",
        },
    )
    monkeypatch.setattr(
        "server.services.decision_application.resolve_strategy_order_generation_gate",
        lambda db, strategy_id, *, as_of_date=None: (
            {
                "status": "pass",
                "strategy_id": strategy_id,
                "paper_shadow_evaluation_only": True,
                "does_not_authorize_execution": True,
                "promotion": {
                    "strategy_advancement_gate_fingerprint": "fixture-gate",
                },
            },
            [],
        ),
    )


def _freeze_valuation_clock(monkeypatch) -> None:
    fixture_now = datetime(2026, 7, 1, 1, 46, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "server.projections.valuation_snapshot.get_shanghai_now",
        lambda now=None: fixture_now,
    )
    monkeypatch.setattr(
        "server.projections.quote_status.get_shanghai_now",
        lambda now=None: fixture_now,
    )


class FakeOperationsDb:
    def __init__(self) -> None:
        self.saved_manual_orders: list[dict] = []
        self.recorded_orders: list[dict] = []
        self.ledger_writes: list[dict] = []
        self.automation_runs: list[dict] = []
        self.execution_reconciliation_open_items: list[dict] = []
        self.ledger_entries: list[dict] = []
        self.latest_quote_previous_close: float | None = None

    def get_action_tasks_sync(self, statuses=None, limit=50, offset=0):
        return [
            {
                "id": 7,
                "source_signal_id": 17,
                "symbol": "600519",
                "title": "买入候选",
                "detail": "dual_ma 触发，目标仓位 20%",
                "direction": "buy",
                "urgency": "high",
                "target_weight": 0.2,
                "price": 10.0,
                "strategy_id": "dual_ma",
                "timestamp": "2026-07-01T09:45:00+08:00",
                "asset_class": "stock",
                "risk_gate_status": "passed",
                "risk_gate_passed": True,
                "risk_gate_severity": "info",
                "risk_gate_reasons": [],
                "manual_confirmation_required": True,
                "manual_confirmation_status": "ready_for_manual_confirmation",
                "manual_confirmation_reason": (
                    "Risk gate passed; manual confirmation is required."
                ),
            }
        ][offset : offset + limit]

    def list_signal_journal_sync(self, limit=50, offset=0):
        return []

    async def get_backtest_results(self):
        return []

    def get_account_truth_score_sync(self):
        return {
            "gate_status": "pass",
            "score": 98,
            "has_evidence": True,
            "unresolved_mismatch_count": 0,
        }

    def get_runtime_control_sync(self, key):
        return None

    def get_latest_quote_sync(self, symbol, asset_type=None):
        row = {
            "symbol": symbol,
            "asset_type": asset_type or "stock",
            "price": 10.0,
            "quote_status": "live",
            "quote_timestamp": "2026-07-01T09:45:00+08:00",
            "quote_source": "fixture",
        }
        if self.latest_quote_previous_close is not None:
            row.update(
                {
                    "previous_close": self.latest_quote_previous_close,
                    "previous_close_date": "2026-06-30",
                    "previous_close_source": "fixture_daily_close",
                }
            )
        return row

    def list_latest_quotes_sync(self):
        return [self.get_latest_quote_sync("600519", asset_type="stock")]

    def list_manual_orders_sync(self, status=None, limit=50, offset=0):
        return []

    def list_orders_sync(self, status=None, symbol=None, limit=100, offset=0):
        return []

    def list_fills_sync(self, order_id=None, symbol=None, limit=100, offset=0):
        return []

    def list_automation_runs_sync(self, run_type=None, limit=20, offset=0):
        rows = self.automation_runs
        if run_type is not None:
            rows = [row for row in rows if row.get("run_type") == run_type]
        return rows[offset : offset + limit]

    def list_execution_reconciliation_open_items_sync(self, limit=20, offset=0):
        return self.execution_reconciliation_open_items[offset : offset + limit]

    def get_ledger_entries_sync(self, limit=50, offset=0):
        return self.ledger_entries[offset : offset + limit]

    def save_manual_order_sync(self, *args, **kwargs):
        raise AssertionError("operations route must not save manual orders")

    def record_order_sync(self, *args, **kwargs):
        raise AssertionError("operations route must not record orders")

    def save_ledger_entry_sync(self, *args, **kwargs):
        raise AssertionError("operations route must not write ledger entries")


class FakePaperShadowOperationsDb(FakeOperationsDb):
    def __init__(self) -> None:
        super().__init__()
        self.recorded_fills: list[dict] = []
        self.paper_shadow_runs: list[dict] = []

    def record_order_sync(self, **kwargs):
        existing = next(
            (
                order
                for order in self.recorded_orders
                if order["order_id"] == kwargs["order_id"]
            ),
            None,
        )
        if existing is None:
            row = {"id": len(self.recorded_orders) + 1, **kwargs}
            row.setdefault("created_at", kwargs["timestamp"])
            row.setdefault("updated_at", kwargs["timestamp"])
            self.recorded_orders.append(row)
            return row["id"]
        existing.update(kwargs)
        return existing["id"]

    def record_fill_sync(self, **kwargs):
        existing = next(
            (
                fill
                for fill in self.recorded_fills
                if fill["fill_id"] == kwargs["fill_id"]
            ),
            None,
        )
        if existing is None:
            row = {"id": len(self.recorded_fills) + 1, **kwargs}
            row.setdefault("created_at", kwargs["timestamp"])
            row.setdefault("updated_at", kwargs["timestamp"])
            self.recorded_fills.append(row)
            return row["id"]
        existing.update(kwargs)
        return existing["id"]

    def list_orders_sync(self, status=None, symbol=None, limit=100, offset=0):
        rows = self.recorded_orders
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        if symbol is not None:
            rows = [row for row in rows if row.get("symbol") == symbol]
        return rows[offset : offset + limit]

    def list_fills_sync(self, order_id=None, symbol=None, limit=100, offset=0):
        rows = self.recorded_fills
        if order_id is not None:
            rows = [row for row in rows if row.get("order_id") == order_id]
        if symbol is not None:
            rows = [row for row in rows if row.get("symbol") == symbol]
        return rows[offset : offset + limit]

    def record_paper_shadow_run_sync(self, command):
        existing = self.get_paper_shadow_run_sync(command.run_id)
        if existing is not None:
            return existing
        for fact in command.orders:
            self.recorded_orders.append(
                {
                    "id": len(self.recorded_orders) + 1,
                    "order_id": fact.order_id,
                    "timestamp": fact.timestamp,
                    "symbol": fact.symbol,
                    "side": fact.side,
                    "order_type": fact.order_type,
                    "quantity": fact.quantity,
                    "price": fact.price,
                    "asset_class": fact.asset_class,
                    "intent_id": fact.intent_id,
                    "risk_decision_id": fact.risk_decision_id,
                    "execution_mode": fact.execution_mode,
                    "status": fact.status,
                    "source": fact.source,
                    "source_ref": fact.source_ref,
                    "payload": fact.payload,
                }
            )
        for fact in command.fills:
            self.recorded_fills.append(
                {
                    "id": len(self.recorded_fills) + 1,
                    "fill_id": fact.fill_id,
                    "order_id": fact.order_id,
                    "timestamp": fact.timestamp,
                    "symbol": fact.symbol,
                    "side": fact.side,
                    "fill_price": fact.fill_price,
                    "fill_quantity": fact.fill_quantity,
                    "commission": fact.commission,
                    "slippage": fact.slippage,
                    "asset_class": fact.asset_class,
                    "execution_mode": fact.execution_mode,
                    "provider_name": fact.provider_name,
                    "broker_order_id": fact.broker_order_id,
                    "source": fact.source,
                    "source_ref": fact.source_ref,
                    "metadata": fact.metadata,
                }
            )
        row = {
            "id": len(self.paper_shadow_runs) + 1,
            "run_id": command.run_id,
            "plan_date": command.plan_date,
            "input_fingerprint": command.input_fingerprint,
            "status": command.status,
            "order_intent_count": command.order_intent_count,
            "simulated_order_count": command.simulated_order_count,
            "simulated_fill_count": command.simulated_fill_count,
            "divergence_status": command.divergence_status,
            "next_manual_review_step": command.next_manual_review_step,
            "limitations_json": json.dumps(list(command.limitations)),
            "payload_json": json.dumps(command.payload),
            "created_at": "2026-07-02T09:35:00",
            "updated_at": "2026-07-02T09:35:00",
        }
        self.paper_shadow_runs.append(row)
        return row

    def record_paper_shadow_evidence_sync(self, **kwargs):
        existing = next(
            (
                run
                for run in self.paper_shadow_runs
                if run["run_id"] == kwargs["run_id"]
                or (
                    run["plan_date"] == kwargs["plan_date"]
                    and run["input_fingerprint"] == kwargs["input_fingerprint"]
                )
            ),
            None,
        )
        if existing is None:
            row = {
                "id": len(self.paper_shadow_runs) + 1,
                **kwargs,
                "created_at": "2026-07-02T09:35:00",
                "updated_at": "2026-07-02T09:35:00",
            }
            self.paper_shadow_runs.append(row)
            return row
        existing.update({**kwargs, "run_id": existing["run_id"]})
        existing["updated_at"] = "2026-07-02T09:40:00"
        return existing

    def latest_paper_shadow_run_sync(self, plan_date=None):
        rows = self.paper_shadow_runs
        if plan_date is not None:
            rows = [row for row in rows if row["plan_date"] == plan_date]
        return rows[-1] if rows else None

    def get_paper_shadow_run_sync(self, run_id):
        return next(
            (run for run in self.paper_shadow_runs if run["run_id"] == run_id),
            None,
        )

    def record_paper_shadow_run_review_sync(
        self,
        *,
        run_id,
        reviewed_at,
        review_status,
        review_notes,
        reviewer=None,
    ):
        run = self.get_paper_shadow_run_sync(run_id)
        if run is None:
            return None
        payload = (
            json.loads(run.get("payload_json") or "{}")
            if isinstance(run.get("payload_json"), str)
            else dict(run.get("payload") or {})
        )
        payload["review"] = {
            "review_status": review_status,
            "reviewed_at": reviewed_at,
            "review_notes": review_notes,
            "reviewer": reviewer,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
        run.update(
            {
                "review_status": review_status,
                "reviewed_at": reviewed_at,
                "review_notes": review_notes,
                "reviewer": reviewer,
                "next_manual_review_step": "review_manual_confirmation",
                "payload_json": json.dumps(payload, sort_keys=True),
                "updated_at": reviewed_at,
            }
        )
        return run


def _seed_persisted_portfolio_facts(db: FakeOperationsDb) -> None:
    db.latest_quote_previous_close = 9.5
    db.ledger_entries = [
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-06-30T09:00:00+08:00",
            "amount": 50_000.0,
            "source": "operations_route_fixture",
        },
        {
            "id": 2,
            "entry_type": "trade_buy",
            "timestamp": "2026-06-30T09:30:00+08:00",
            "symbol": "600519",
            "direction": "buy",
            "quantity": 200.0,
            "price": 8.0,
            "commission": 0.0,
            "asset_class": "stock",
            "source": "operations_route_fixture",
        },
    ]


def test_today_operations_route_returns_read_only_runbook(monkeypatch):
    _allow_paper_shadow_evaluation(monkeypatch)
    fake_db = FakeOperationsDb()
    _seed_persisted_portfolio_facts(fake_db)
    fake_state = SimpleNamespace(
        db=fake_db,
        config=SimpleNamespace(
            assets=[],
            broker_fee_schedule=SimpleNamespace(
                stock_a_commission_rate=0.00015,
                stock_a_min_commission=5.0,
                fund_etf_commission_rate=0.00012,
                fund_etf_min_commission=3.0,
                stamp_tax_rate=0.0005,
                transfer_fee_rate=0.00001,
                other_fee_rate=0,
                limitations=("broker_regulatory_fees_assumed_absorbed",),
            ),
        ),
        scheduler=SimpleNamespace(
            watchlist=[],
            latest_quotes={},
            portfolio=SimpleNamespace(
                cash=30000.0,
                positions={
                    "600519": SimpleNamespace(
                        quantity=200.0,
                        avg_cost=8.0,
                        market_value=2000.0,
                    )
                },
                total_equity=lambda: 50000.0,
            ),
        ),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)

    endpoint = _endpoint("/api/operations/today")
    response = asyncio.run(endpoint())

    assert response["schema_version"] == "karkinos.operations_today.v1"
    assert response["conclusion_status"] == "manual_action_required"
    assert response["daily_plan"]["order_intent_count"] == 1
    assert response["paper_shadow"]["status"] == "not_run"
    assert response["paper_shadow"]["next_manual_review_step"] == (
        "run_paper_shadow_daily"
    )
    acceptance_audit = next(
        item for item in response["subsystems"] if item["id"] == "acceptance_audit"
    )
    audit = build_acceptance_audit_export(selected_audit="operations_runbook")[
        "audits"
    ][0]
    expected_detail_status = (
        f"operations_runbook:{audit['completed_count']}/{audit['required_count']}"
    )
    assert acceptance_audit["status"] == "pass"
    assert acceptance_audit["detail_status"] == expected_detail_status
    assert acceptance_audit["next_action"] == "none"
    assert acceptance_audit["last_run_at"]
    assert any(
        "manual confirmation remains" in limitation
        for limitation in acceptance_audit["limitations"]
    )
    pilot_readiness = response["controlled_per_order_pilot_readiness"]
    assert pilot_readiness["schema_version"] == (
        "karkinos.controlled_per_order_pilot_readiness.v1"
    )
    assert pilot_readiness["status"] == "blocked"
    assert pilot_readiness["read_only_projection"] is True
    assert pilot_readiness["provider_contacted"] is False
    assert pilot_readiness["database_writes_performed"] is False
    assert pilot_readiness["authorizes_execution"] is False
    assert response["limitations"][0].startswith("Operations summary is read-only")
    assert response["citic_source_follow_up"]["status"] == "not_configured"
    assert response["citic_source_follow_up"]["database_writes_performed"] is False
    assert all(
        item["subsystem_id"] != "citic_source_follow_up"
        for item in response["attention_items"]
    )
    assert fake_db.saved_manual_orders == []
    assert fake_db.recorded_orders == []
    assert fake_db.ledger_writes == []


def test_pilot_readiness_factory_failure_is_a_blocker(monkeypatch):
    state = SimpleNamespace(
        db=FakeOperationsDb(),
        config=SimpleNamespace(
            broker_connectors=[],
            trusted_operator_identities=[],
        ),
    )

    def fail_write_release_factory(_state):
        raise RuntimeError("fixture source failure")

    monkeypatch.setattr(
        "server.composition.controlled_execution_services."
        "build_controlled_broker_write_release_service",
        fail_write_release_factory,
    )

    readiness = operations_routes._build_controlled_per_order_pilot_readiness(state)

    assert readiness["status"] == "blocked"
    assert any(
        "write_release_source_failed" in blocker for blocker in readiness["blockers"]
    )
    assert readiness["provider_contacted"] is False
    assert readiness["database_writes_performed"] is False
    assert readiness["authorizes_execution"] is False


def test_today_operations_route_surfaces_execution_reconciliation_open_items(
    monkeypatch,
):
    fake_db = FakeOperationsDb()
    fake_db.execution_reconciliation_open_items.append(
        {
            "order_id": "MANUAL-001",
            "item_status": "manual_execution_recorded",
            "suggested_action": "review_manual_execution_and_import_broker_statement",
            "detail": (
                "Manual execution evidence is recorded; import broker statement "
                "before ledger update."
            ),
            "created_at": "2026-07-01T10:10:00+08:00",
            "payload_json": json.dumps(
                {
                    "manual_execution_evidence_summary": {
                        "preview_fingerprint": "preview:abc123",
                        "submitted_to_broker": False,
                        "does_not_mutate_oms": True,
                        "does_not_mutate_production_ledger": True,
                    }
                }
            ),
        }
    )
    fake_state = SimpleNamespace(
        db=fake_db,
        config=SimpleNamespace(
            assets=[],
            broker_fee_schedule=SimpleNamespace(
                stock_a_commission_rate=0.00015,
                stock_a_min_commission=5.0,
                fund_etf_commission_rate=0.00012,
                fund_etf_min_commission=3.0,
                stamp_tax_rate=0.0005,
                transfer_fee_rate=0.00001,
                other_fee_rate=0,
                limitations=("broker_regulatory_fees_assumed_absorbed",),
            ),
        ),
        scheduler=SimpleNamespace(
            watchlist=[],
            latest_quotes={},
            portfolio=SimpleNamespace(
                cash=30000.0,
                positions={
                    "600519": SimpleNamespace(
                        quantity=200.0,
                        avg_cost=8.0,
                        market_value=2000.0,
                    )
                },
                total_equity=lambda: 50000.0,
            ),
        ),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)

    endpoint = _endpoint("/api/operations/today")
    response = asyncio.run(endpoint())

    reconciliation = response["execution_reconciliation"]
    assert reconciliation["open_item_count"] == 1
    assert reconciliation["manual_execution_review_count"] == 1
    assert reconciliation["first_open_item"]["order_id"] == "MANUAL-001"
    assert (
        reconciliation["first_open_item"]["manual_execution_evidence_summary"][
            "preview_fingerprint"
        ]
        == "preview:abc123"
    )
    assert reconciliation["does_not_submit_broker_order"] is True
    assert reconciliation["does_not_mutate_oms"] is True
    assert reconciliation["does_not_mutate_production_ledger"] is True
    subsystem = next(
        item
        for item in response["subsystems"]
        if item["id"] == "execution_reconciliation"
    )
    assert subsystem["status"] == "manual_action_required"
    assert subsystem["next_action"] == (
        "review_manual_execution_and_import_broker_statement"
    )
    assert fake_db.saved_manual_orders == []
    assert fake_db.recorded_orders == []
    assert fake_db.ledger_writes == []


def test_today_operations_route_surfaces_scheduler_run_evidence(monkeypatch):
    _freeze_valuation_clock(monkeypatch)
    fake_db = FakeOperationsDb()
    _seed_persisted_portfolio_facts(fake_db)
    plan_date = "2026-07-01"
    run_id = f"market-session:{plan_date}:100000"
    fake_db.automation_runs.append(
        {
            "run_id": run_id,
            "run_type": "market_session",
            "run_date": plan_date,
            "status": "paper_shadow_failed",
            "execution_mode": "paper_shadow",
            "started_at": f"{plan_date}T10:00:00+08:00",
            "finished_at": f"{plan_date}T10:00:01+08:00",
            "payload_json": (
                '{"input_fingerprint": "abc123", '
                '"retry_state": {"attempt": 1, "max_attempts": 1, '
                '"retryable": true}, '
                '"error": {"type": "RuntimeError", "message": "fixture"}, '
                '"does_not_submit_broker_order": true, '
                '"limitations": ["Paper/shadow run failed; no broker order was submitted."]}'
            ),
        }
    )
    fake_state = SimpleNamespace(
        db=fake_db,
        config=SimpleNamespace(
            assets=[],
            broker_fee_schedule=SimpleNamespace(
                stock_a_commission_rate=0.00015,
                stock_a_min_commission=5.0,
                fund_etf_commission_rate=0.00012,
                fund_etf_min_commission=3.0,
                stamp_tax_rate=0.0005,
                transfer_fee_rate=0.00001,
                other_fee_rate=0,
                limitations=("broker_regulatory_fees_assumed_absorbed",),
            ),
        ),
        scheduler=SimpleNamespace(
            watchlist=[],
            latest_quotes={},
            portfolio=SimpleNamespace(
                cash=30000.0,
                positions={
                    "600519": SimpleNamespace(
                        quantity=200.0,
                        avg_cost=8.0,
                        market_value=2000.0,
                    )
                },
                total_equity=lambda: 50000.0,
            ),
        ),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)

    endpoint = _endpoint("/api/operations/today")
    response = asyncio.run(endpoint())

    assert response["scheduler"]["run_id"] == run_id
    assert response["scheduler"]["status"] == "paper_shadow_failed"
    assert response["scheduler"]["retry_state"] == {
        "attempt": 1,
        "max_attempts": 1,
        "retryable": True,
    }
    scheduler = next(
        item for item in response["subsystems"] if item["id"] == "scheduler"
    )
    assert scheduler["status"] == "blocked"
    assert scheduler["next_action"] == "inspect_scheduler_failure"
    assert response["conclusion_status"] == "blocked"
    attention = next(
        item
        for item in response["attention_items"]
        if item["subsystem_id"] == "scheduler"
    )
    assert attention["evidence"] == {
        "status": "paper_shadow_failed",
        "observed_at": f"{plan_date}T10:00:01+08:00",
    }
    assert attention["resolution_condition"] == (
        "new_recognized_terminal_scheduler_run_required"
    )
    assert attention["manual_acknowledgement_clears_status"] is False
    assert attention["provider_contacted"] is False
    assert attention["database_writes_performed"] is False
    assert attention["authorizes_execution"] is False
    assert fake_db.saved_manual_orders == []
    assert fake_db.recorded_orders == []
    assert fake_db.ledger_writes == []


def test_paper_shadow_run_route_creates_idempotent_simulation_evidence(monkeypatch):
    _allow_paper_shadow_evaluation(monkeypatch)
    fake_db = FakePaperShadowOperationsDb()
    _seed_persisted_portfolio_facts(fake_db)
    fake_state = SimpleNamespace(
        db=fake_db,
        config=SimpleNamespace(
            assets=[],
            broker_fee_schedule=SimpleNamespace(
                stock_a_commission_rate=0.00015,
                stock_a_min_commission=5.0,
                fund_etf_commission_rate=0.00012,
                fund_etf_min_commission=3.0,
                stamp_tax_rate=0.0005,
                transfer_fee_rate=0.00001,
                other_fee_rate=0,
                limitations=("broker_regulatory_fees_assumed_absorbed",),
            ),
        ),
        scheduler=SimpleNamespace(
            watchlist=[],
            latest_quotes={},
            portfolio=SimpleNamespace(
                cash=30000.0,
                positions={
                    "600519": SimpleNamespace(
                        quantity=200.0,
                        avg_cost=8.0,
                        market_value=2000.0,
                    )
                },
                total_equity=lambda: 50000.0,
            ),
        ),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)

    endpoint = _endpoint("/api/operations/paper-shadow/run", method="POST")
    first = asyncio.run(endpoint())
    second = asyncio.run(endpoint())

    assert second["run_id"] == first["run_id"]
    assert second["status"] == "within_expectations"
    assert second["does_not_submit_broker_order"] is True
    assert second["does_not_mutate_production_ledger"] is True
    assert len(fake_db.paper_shadow_runs) == 1
    assert len(fake_db.recorded_orders) == 1
    assert len(fake_db.recorded_fills) == 1
    assert fake_db.recorded_orders[0]["execution_mode"] == "paper_shadow"
    assert fake_db.recorded_orders[0]["source"] == "paper_shadow_daily"
    assert fake_db.recorded_fills[0]["execution_mode"] == "paper_shadow"
    assert fake_db.saved_manual_orders == []
    assert fake_db.ledger_writes == []

    fake_db.recorded_orders = []
    fake_db.recorded_fills = []
    today_endpoint = _endpoint("/api/operations/today")
    today = asyncio.run(today_endpoint())

    assert today["paper_shadow"]["run_id"] == first["run_id"]
    assert today["paper_shadow"]["status"] == "within_expectations"
    assert today["paper_shadow"]["simulated_order_count"] == 1
    assert today["paper_shadow"]["evidence_refs"] == first["evidence_refs"]
    assert today["paper_shadow"]["divergence_summary"] == first["divergence_summary"]


def test_paper_shadow_run_review_route_records_review_without_execution_mutation(
    monkeypatch,
):
    fake_db = FakePaperShadowOperationsDb()
    fake_db.record_paper_shadow_evidence_sync(
        run_id="shadow:2026-07-02:diverged",
        plan_date="2026-07-02",
        input_fingerprint="diverged",
        status="diverged",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=0,
        divergence_status="diverged",
        next_manual_review_step="resolve_shadow_divergence",
        limitations=[],
        payload={"orders": [{"order_id": "SHADOW-1"}]},
    )
    fake_state = SimpleNamespace(db=fake_db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)

    endpoint = _endpoint(
        "/api/operations/paper-shadow/runs/{run_id}/review",
        method="POST",
    )
    response = asyncio.run(
        endpoint(
            "shadow:2026-07-02:diverged",
            operations_routes.PaperShadowRunReviewRequest(
                reviewed_at="2026-07-02T10:10:00",
                review_status="accepted_for_manual_confirmation",
                review_notes="Operator accepted simulated partial-fill evidence.",
                reviewer="local-operator",
            ),
        )
    )

    assert response["run_id"] == "shadow:2026-07-02:diverged"
    assert response["status"] == "diverged"
    assert response["divergence_status"] == "diverged"
    assert response["review_status"] == "accepted_for_manual_confirmation"
    assert response["reviewed_at"] == "2026-07-02T10:10:00"
    assert response["next_manual_review_step"] == "review_manual_confirmation"
    assert fake_db.saved_manual_orders == []
    assert fake_db.ledger_writes == []


def test_paper_shadow_run_review_route_rejects_failed_run_manual_handoff(
    monkeypatch,
    tmp_path,
):
    db = AppDatabase(tmp_path / "operations.db")
    db.init_sync()
    insert_paper_shadow_evidence(
        db,
        run_id="shadow:2026-07-02:failed",
        plan_date="2026-07-02",
        input_fingerprint="failed",
        status="failed",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=0,
        divergence_status="failed",
        next_manual_review_step="inspect_failed_run",
        limitations=["Paper/shadow simulation failed."],
        payload={"orders": [{"order_id": "SHADOW-1", "status": "failed"}]},
    )
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)

    endpoint = _endpoint(
        "/api/operations/paper-shadow/runs/{run_id}/review",
        method="POST",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                "shadow:2026-07-02:failed",
                operations_routes.PaperShadowRunReviewRequest(
                    reviewed_at="2026-07-02T10:10:00",
                    review_status="accepted_for_manual_confirmation",
                    review_notes="Operator tried to accept failed simulation evidence.",
                    reviewer="local-operator",
                ),
            )
        )

    assert exc_info.value.status_code == 400
    assert "failed paper/shadow run" in str(exc_info.value.detail)
    saved = db.get_paper_shadow_run_sync("shadow:2026-07-02:failed")
    assert saved is not None
    assert saved["review_status"] is None
    assert saved["next_manual_review_step"] == "inspect_failed_run"
