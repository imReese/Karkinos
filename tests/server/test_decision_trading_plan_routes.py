from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi.routing import APIRoute

from server.routes import decision as decision_routes
from server.services import decision_application
from server.services.daily_decision_evidence_identity import (
    daily_candidate_input_fingerprint,
    daily_candidate_record_fingerprint,
)
from server.services.decision_action_application import read_action_tasks
from server.services.decision_portfolio_projection import (
    action_filter_date,
    response_decision_date,
)
from server.services.decision_projection import (
    daily_candidate_generation_status,
    suppress_unverified_daily_scan_candidates,
)


def _endpoint(path: str, method: str = "GET"):
    router = decision_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


class FakeDecisionDb:
    def __init__(self) -> None:
        self.manual_orders: list[dict] = []
        self.order_facts: list[dict] = []
        self.ledger_entries: list[dict] = []

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

    def get_ledger_entries_sync(self, limit=500, offset=0):
        return [
            {
                "id": 1,
                "entry_type": "cash_deposit",
                "timestamp": "2026-07-01T09:30:00+08:00",
                "amount": 50_000.0,
                "asset_class": "cash",
                "source": "fixture",
            },
            {
                "id": 2,
                "entry_type": "trade_buy",
                "timestamp": "2026-07-01T09:40:00+08:00",
                "symbol": "600519",
                "direction": "buy",
                "quantity": 200.0,
                "price": 10.0,
                "commission": 0.0,
                "gross_amount": 2_000.0,
                "net_cash_impact": -2_000.0,
                "asset_class": "stock",
                "source": "fixture",
            },
        ][offset : offset + limit]

    def get_latest_quote_sync(self, symbol, asset_type=None):
        return {
            "symbol": symbol,
            "asset_type": asset_type or "stock",
            "price": 10.0,
            "previous_close": 9.5,
            "previous_close_date": "2026-06-30",
            "quote_status": "live",
            "quote_timestamp": "2026-07-01T09:45:00+08:00",
            "quote_source": "fixture",
        }

    def list_latest_quotes_sync(self):
        return [self.get_latest_quote_sync("600519", asset_type="stock")]

    def save_manual_order_sync(self, *args, **kwargs):
        raise AssertionError("trading plan must not save manual orders")

    def record_order_sync(self, *args, **kwargs):
        raise AssertionError("trading plan must not record order facts")

    def save_ledger_entry_sync(self, *args, **kwargs):
        raise AssertionError("trading plan must not write ledger entries")


def test_current_decision_excludes_prior_day_action_with_stale_valuation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "server.services.decision_portfolio_projection.get_shanghai_now",
        lambda: datetime(2026, 7, 2, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    context = {
        "authority": "persisted_valuation_snapshot",
        "valuation_snapshot": {"trade_date": "2026-07-01", "status": "degraded"},
    }

    assert action_filter_date(context) == "2026-07-02"
    assert response_decision_date(context, []) == "2026-07-02"
    assert read_action_tasks(FakeDecisionDb(), decision_date="2026-07-02") == []


def test_decision_account_truth_gate_uses_current_promotion_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "server.account_truth_gate.build_latest_account_truth_promotion_evidence",
        lambda state: {
            "schema_version": "karkinos.account_truth.promotion_evidence.v1",
            "status": "blocked",
            "gate_status": "pass",
            "score": 100,
            "import_run_id": "import-stale",
            "source_fingerprint": "a" * 64,
            "captured_at": "2026-07-01T15:00:00+08:00",
            "current_age_seconds": 90000,
            "max_age_seconds": 86400,
            "data_freshness_status": "stale",
            "unresolved_mismatch_count": 0,
            "reconciliation_status": "pass",
            "ledger_coverage": {"status": "covered"},
            "blockers": ["account_truth_import_stale"],
        },
    )

    result = decision_routes._account_truth_gate_evidence(SimpleNamespace())

    assert result["gate_status"] == "blocked"
    assert result["promotion_status"] == "blocked"
    assert result["data_freshness_status"] == "stale"
    assert result["blocking_reasons"] == ["account_truth_import_stale"]
    assert result["source_fingerprint"] == "a" * 64


def test_decision_trading_plan_route_returns_read_only_order_intent(monkeypatch):
    fake_db = FakeDecisionDb()
    fake_state = SimpleNamespace(
        db=fake_db,
        config=SimpleNamespace(
            assets=[],
            account_commission_rate=0.00015,
            account_min_commission=5.0,
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
    monkeypatch.setattr(
        "server.projections.valuation_snapshot.get_shanghai_now",
        lambda now=None: (
            now or datetime(2026, 7, 1, 9, 46, tzinfo=ZoneInfo("Asia/Shanghai"))
        ),
    )
    monkeypatch.setattr(
        "server.projections.quote_status.get_shanghai_now",
        lambda now=None: (
            now or datetime(2026, 7, 1, 9, 46, tzinfo=ZoneInfo("Asia/Shanghai"))
        ),
    )
    monkeypatch.setattr(
        "server.services.decision_portfolio_projection.get_shanghai_now",
        lambda: datetime(2026, 7, 1, 9, 46, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        decision_application,
        "_account_truth_gate_evidence",
        lambda state: {
            "gate_status": "pass",
            "data_freshness_status": "fresh",
            "unresolved_mismatch_count": 0,
            "import_run_id": "fixture-import",
        },
    )
    monkeypatch.setattr(
        decision_application,
        "resolve_strategy_order_generation_gate",
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

    endpoint = _endpoint("/api/decision/trading-plan")
    response = asyncio.run(endpoint())

    assert response["schema_version"] == "karkinos.daily_trading_plan.v1"
    generated_at = datetime.fromisoformat(response["generated_at"])
    assert generated_at.tzinfo is not None
    assert generated_at.utcoffset() is not None
    assert response["conclusion_status"] == "paper_shadow_required"
    assert response["candidate_pool_count"] == 1
    assert response["manual_ready_count"] == 0
    assert response["paper_shadow_ready_count"] == 1
    assert response["order_intent_count"] == 1
    assert response["default_execution_mode"] == "manual_confirmation"
    assert response["broker_bridge_status"] == "disabled"
    assert response["research_operation_preview"]["status"] == "unavailable"
    assert response["research_operation_preview"]["operations"] == []
    assert response["research_operation_preview"]["authorizes_order_creation"] is (
        False
    )
    assert response["research_operation_instruments"] == {
        "schema_version": "karkinos.decision.research_operation_instruments.v1",
        "requested_count": 0,
        "lookup_count": 0,
        "resolved_count": 0,
        "items": [],
        "missing_symbols": [],
        "lookup_truncated": False,
        "metadata_source": "persisted_instrument_metadata",
        "provider_contacted": False,
        "database_writes_performed": False,
        "read_only": True,
        "research_only": True,
        "authority_effect": "none",
    }

    intent = response["order_intents"][0]
    assert intent["action_id"] == 7
    assert intent["symbol"] == "600519"
    assert intent["side"] == "buy"
    assert intent["estimated_quantity"] == 800.0
    assert intent["estimated_net_cash_impact"] == -8005.08
    assert intent["position_effect"]["current_quantity"] == 200.0
    assert intent["position_effect"]["estimated_quantity_after"] == 1000.0
    assert intent["position_effect"]["cost_basis_method"] == "weighted_average_preview"
    assert intent["submission_status"] == "paper_shadow_required"
    assert intent["does_not_submit_broker_order"] is True
    assert fake_db.manual_orders == []
    assert fake_db.order_facts == []
    assert fake_db.ledger_entries == []


def test_daily_generation_distinguishes_failed_run_from_no_signal(
    monkeypatch,
) -> None:
    run_date = "2026-07-01"
    scan_run_id = "scan:verified-no-signal"
    evidence_run_id = "daily-evidence:verified-no-signal"
    evidence_payload = {
        "schema_version": "karkinos.daily_decision_evidence_automation.v3",
        "decision_outcome": "no_action",
        "input_snapshot": {"promoted_strategy_scan_run_id": scan_run_id},
        "production_gate": {"status": "pass", "blockers": []},
        "candidate_count": 0,
        "manual_ticket_candidate_count": 0,
        "manual_order_ticket_candidates": [],
    }
    evidence_payload["input_fingerprint"] = daily_candidate_input_fingerprint(
        evidence_payload
    )
    evidence_payload["production_record_fingerprint"] = (
        daily_candidate_record_fingerprint(evidence_payload)
    )
    evidence_row = {
        "run_id": evidence_run_id,
        "run_type": "daily_decision_evidence",
        "run_date": run_date,
        "status": "no_candidates",
        "payload_json": json.dumps(evidence_payload),
    }
    attempt_payload = {
        "result_run_id": evidence_run_id,
        "decision_outcome": "no_action",
        "promoted_strategy_scan_run_id": scan_run_id,
    }
    attempt_row = {
        "run_id": "automation:daily-candidate-background-attempt:2026-07-01",
        "status": "completed",
        "source_ref": evidence_run_id,
        "payload_json": json.dumps(attempt_payload),
    }

    class Db:
        def list_automation_runs_sync(self, **_kwargs):
            return [attempt_row]

        def get_automation_run_sync(self, run_id):
            return evidence_row if run_id == evidence_run_id else None

    monkeypatch.setattr(
        "server.projections.account_action_recommendation."
        "resolve_latest_verified_promoted_strategy_scan",
        lambda *_args, **_kwargs: {
            "status": "completed_no_signal",
            "run_id": scan_run_id,
            "normal_no_signal": True,
        },
    )
    db = Db()
    completed = daily_candidate_generation_status(db, run_date)
    assert completed["status"] == "completed_no_signal"
    assert completed["generation_verified"] is True
    assert completed["scan_run_id"] == scan_run_id

    evidence_payload["production_gate"] = {
        "status": "blocked",
        "blockers": ["account_truth_not_fresh"],
    }
    evidence_payload["input_fingerprint"] = daily_candidate_input_fingerprint(
        evidence_payload
    )
    evidence_payload["production_record_fingerprint"] = (
        daily_candidate_record_fingerprint(evidence_payload)
    )
    evidence_row["payload_json"] = json.dumps(evidence_payload)
    blocked = daily_candidate_generation_status(db, run_date)
    assert blocked["status"] == "blocked"
    assert blocked["failure_code"] == "account_truth_not_fresh"

    attempt_row["status"] = "failed_closed"
    attempt_payload["failure_stage"] = "initial_plan_read"
    attempt_payload["failure_code"] = "market_revision_changed_during_initial_read"
    attempt_row["payload_json"] = json.dumps(attempt_payload)
    failed = daily_candidate_generation_status(db, run_date)
    assert failed["status"] == "failed_closed"
    assert failed["generation_verified"] is False
    assert failed["failure_stage"] == "initial_plan_read"
    assert failed["failure_code"] == "market_revision_changed_during_initial_read"


def test_daily_generation_account_ineligible_is_blocked(monkeypatch) -> None:
    run_date = "2026-07-01"
    scan_run_id = "scan:account-blocked"
    evidence_run_id = "daily-evidence:account-blocked"
    evidence_payload = {
        "schema_version": "karkinos.daily_decision_evidence_automation.v3",
        "decision_outcome": "no_action",
        "input_snapshot": {"promoted_strategy_scan_run_id": scan_run_id},
    }
    evidence_payload["input_fingerprint"] = daily_candidate_input_fingerprint(
        evidence_payload
    )
    evidence_payload["production_record_fingerprint"] = (
        daily_candidate_record_fingerprint(evidence_payload)
    )
    attempt_payload = {
        "result_run_id": evidence_run_id,
        "decision_outcome": "no_action",
        "promoted_strategy_scan_run_id": scan_run_id,
    }
    attempt = {
        "status": "completed",
        "source_ref": evidence_run_id,
        "payload_json": json.dumps(attempt_payload),
    }

    class Db:
        def list_automation_runs_sync(self, **_kwargs):
            return [attempt]

        def get_automation_run_sync(self, run_id):
            if run_id != evidence_run_id:
                return None
            return {
                "run_type": "daily_decision_evidence",
                "run_date": run_date,
                "status": "no_candidates",
                "payload_json": json.dumps(evidence_payload),
            }

    monkeypatch.setattr(
        "server.projections.account_action_recommendation."
        "resolve_latest_verified_promoted_strategy_scan",
        lambda *_args, **_kwargs: {
            "status": "completed_no_signal",
            "run_id": scan_run_id,
            "normal_no_signal": False,
            "account_blocked_buys": [{"symbol": "301251"}],
        },
    )
    generation = daily_candidate_generation_status(Db(), run_date)
    assert generation["status"] == "blocked"
    assert generation["failure_code"] == "account_buy_candidates_ineligible"
    assert generation["generation_verified"] is False


def test_today_suppresses_orphan_scan_tasks_but_retains_other_manual_actions(
    monkeypatch,
) -> None:
    def candidate(action_id: int, strategy_id: str) -> dict:
        return {
            "action_id": action_id,
            "action": "buy",
            "symbol": str(action_id),
            "action_task_status": "pending",
            "risk_gate_status": "passed",
            "manual_confirmation_required": True,
            "manual_confirmation_status": "ready_for_manual_confirmation",
            "evidence": {
                "signal": {
                    "id": action_id + 100,
                    "timestamp": "2026-07-01T09:35:00+08:00",
                    "strategy_id": strategy_id,
                },
                "strategy": {"strategy_id": strategy_id},
                "certainty": {"status": "pass"},
                "account_truth": {"gate_status": "pass"},
                "strategy_attribution": {"gate_status": "pass"},
            },
        }

    scan_candidate = candidate(7, "ai_formula_shadow:one")
    manual_candidate = candidate(8, "manual_research")
    payload = {
        "lane": "daily",
        "decision_date": "2026-07-01",
        "decision": "buy",
        "requires_manual_confirmation": True,
        "generation": {
            "status": "failed_closed",
            "recommendation_authoritative": False,
            "bound_scan_action_ids": [],
            "formal_candidate_action_ids": [],
        },
        "candidates": [scan_candidate, manual_candidate],
        "summary": {
            "candidate_count": 2,
            "risk_blocked_count": 0,
            "ready_for_manual_confirmation_count": 2,
            "action_tasks": {"total_count": 2, "pending_count": 2},
            "audit": {"signal_count": 2, "risk_checked_count": 2},
            "market_data": {"source_health": "live"},
            "account_truth": {"gate_status": "pass"},
            "strategy_attribution": {"gate_status": "pass"},
        },
        "no_action_reasons": [],
    }
    filtered = suppress_unverified_daily_scan_candidates(payload)
    assert [item["action_id"] for item in filtered["candidates"]] == [8]
    assert filtered["decision"] == "buy"
    assert filtered["summary"]["candidate_count"] == 1
    assert filtered["summary"]["action_tasks"]["pending_count"] == 1
    assert filtered["suppressed_unverified_candidates"][0]["action_id"] == 7
    assert len(payload["candidates"]) == 2

    payload["generation"] = {
        "status": "completed_with_candidates",
        "recommendation_authoritative": True,
        "bound_scan_action_ids": [7, 9],
        "formal_candidate_action_ids": [7],
    }
    assert suppress_unverified_daily_scan_candidates(payload) is payload
    payload["generation"]["formal_candidate_action_ids"] = [9]
    assert [
        item["action_id"]
        for item in suppress_unverified_daily_scan_candidates(payload)["candidates"]
    ] == [8]

    async def raw_today(_state):
        return payload

    monkeypatch.setattr("server.dependencies.get_app_state", lambda: object())
    monkeypatch.setattr(decision_routes, "_today_decision_payload", raw_today)
    route_result = asyncio.run(_endpoint("/api/decision/today")())
    assert [item["action_id"] for item in route_result["candidates"]] == [8]
    assert route_result["summary"]["candidate_count"] == 1

    payload["generation"] = None
    missing_status = suppress_unverified_daily_scan_candidates(payload)
    assert [item["action_id"] for item in missing_status["candidates"]] == [8]
    assert missing_status["generation"]["status"] == "unavailable"
    assert missing_status["generation"]["recommendation_authoritative"] is False


def test_daily_generation_exposes_only_final_ticket_action_ids(monkeypatch) -> None:
    run_date = "2026-07-01"
    scan_run_id = "scan:verified-candidates"
    evidence_run_id = "daily-evidence:verified-candidates"
    tickets = [{"action_id": 7}]
    evidence_payload = {
        "schema_version": "karkinos.daily_decision_evidence_automation.v3",
        "decision_outcome": "manual_order_ticket_candidate",
        "input_snapshot": {"promoted_strategy_scan_run_id": scan_run_id},
        "production_gate": {"status": "pass", "blockers": []},
        "manual_ticket_candidate_count": 1,
        "manual_order_ticket_candidates": tickets,
    }
    evidence_payload["input_fingerprint"] = daily_candidate_input_fingerprint(
        evidence_payload
    )
    evidence_payload["production_record_fingerprint"] = (
        daily_candidate_record_fingerprint(evidence_payload)
    )
    attempt_payload = {
        "result_run_id": evidence_run_id,
        "decision_outcome": "manual_order_ticket_candidate",
        "promoted_strategy_scan_run_id": scan_run_id,
    }

    class Db:
        def list_automation_runs_sync(self, **_kwargs):
            return [
                {
                    "status": "completed",
                    "source_ref": evidence_run_id,
                    "payload_json": json.dumps(attempt_payload),
                }
            ]

        def get_automation_run_sync(self, run_id):
            if run_id != evidence_run_id:
                return None
            return {
                "run_type": "daily_decision_evidence",
                "run_date": run_date,
                "status": "paper_shadow_completed",
                "payload_json": json.dumps(evidence_payload),
            }

    monkeypatch.setattr(
        "server.projections.account_action_recommendation."
        "resolve_latest_verified_promoted_strategy_scan",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "run_id": scan_run_id,
            "selected_signal_count": 2,
            "action_task_ids": ["7", "9"],
        },
    )
    generation = daily_candidate_generation_status(Db(), run_date)
    assert generation["status"] == "completed_with_candidates"
    assert generation["bound_scan_action_ids"] == [7, 9]
    assert generation["formal_candidate_action_ids"] == [7]
    assert generation["recommendation_authoritative"] is True


def test_unlinked_daily_evidence_is_visible_without_recommendation_authority() -> None:
    class Db:
        def list_automation_runs_sync(self, *, run_type, **_kwargs):
            return (
                [{"run_id": "daily-evidence:manual"}]
                if run_type == "daily_decision_evidence"
                else []
            )

    generation = daily_candidate_generation_status(Db(), "2026-07-01")
    assert generation["status"] == "unlinked_daily_evidence"
    assert generation["daily_evidence_run_id"] == "daily-evidence:manual"
    assert generation["recommendation_authoritative"] is False


def test_scan_binding_changes_new_input_identity_without_changing_legacy_identity() -> (
    None
):
    legacy = {
        "input_snapshot": {"decision_plan_fingerprint": "fixture"},
        "decision_outcome": "no_action",
    }
    old_fingerprint = daily_candidate_input_fingerprint(legacy)
    assert old_fingerprint == (
        "9916b762f76a36f0169ad848d4aabc5d2d3c62481f87e10bffce727162b60f0d"
    )
    assert (
        daily_candidate_input_fingerprint(
            {
                **legacy,
                "input_snapshot": {
                    **legacy["input_snapshot"],
                    "promoted_strategy_scan_run_id": None,
                },
            }
        )
        == old_fingerprint
    )
    first = daily_candidate_input_fingerprint(
        {
            **legacy,
            "input_snapshot": {
                **legacy["input_snapshot"],
                "promoted_strategy_scan_run_id": "scan:one",
            },
        }
    )
    second = daily_candidate_input_fingerprint(
        {
            **legacy,
            "input_snapshot": {
                **legacy["input_snapshot"],
                "promoted_strategy_scan_run_id": "scan:two",
            },
        }
    )
    assert first != second
    assert first != old_fingerprint
