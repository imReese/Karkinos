"""Daily paper/shadow run service tests."""

from __future__ import annotations

import json
import sqlite3

from server.db import AppDatabase
from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan


def test_paper_shadow_run_creates_simulated_order_and_fill_without_ledger_mutation(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash",
        timestamp="2026-07-02T09:00:00",
        amount=10000.0,
        note="opening cash",
        source="fixture",
        source_ref="opening-cash",
    )
    ledger_count_before = _ledger_entry_count(db)

    run = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
    )

    orders = db.list_orders_sync()
    fills = db.list_fills_sync()
    latest = db.latest_paper_shadow_run_sync(plan_date="2026-07-02")

    assert run["status"] == "within_expectations"
    assert run["divergence_status"] == "within_expectations"
    assert run["order_intent_count"] == 1
    assert run["simulated_order_count"] == 1
    assert run["simulated_fill_count"] == 1
    assert run["next_manual_review_step"] == "review_manual_confirmation"
    assert run["does_not_submit_broker_order"] is True
    assert run["does_not_mutate_production_ledger"] is True
    assert latest is not None
    assert latest["run_id"] == run["run_id"]
    expected_input_refs = {
        "source_decision": "buy",
        "trading_plan_ref": f"trading_plan:2026-07-02:{run['input_fingerprint'][:12]}",
        "trading_plan_schema_version": "karkinos.daily_trading_plan.v1",
    }
    assert run["input_refs"] == expected_input_refs
    assert json.loads(latest["payload_json"])["input_refs"] == expected_input_refs
    expected_evidence_refs = [
        "action:ACTION-1",
        "strategy:dual_ma",
        "risk:risk-001",
        "signal:signal-001",
        f"paper_order:{orders[0]['order_id']}",
        f"paper_fill:{fills[0]['fill_id']}",
        f"oms_transition:{orders[0]['order_id']}:1:staged",
        f"oms_transition:{orders[0]['order_id']}:2:submitted",
        f"oms_transition:{orders[0]['order_id']}:3:accepted",
        f"oms_transition:{orders[0]['order_id']}:4:filled",
    ]
    assert run["evidence_refs"] == expected_evidence_refs
    assert json.loads(latest["payload_json"])["evidence_refs"] == expected_evidence_refs
    expected_order_intent_summary = {
        "action_ref": "action:ACTION-1",
        "symbol": "600519",
        "side": "buy",
        "estimated_quantity": 100.0,
        "estimated_price": 10.0,
        "price_basis": "estimated_price",
        "estimated_gross_amount": 1000.0,
        "estimated_total_fee": 5.0,
        "fee_rule_id": "stock_a_commission_v1",
        "risk_gate_status": "passed",
        "manual_confirmation_status": "ready_for_manual_confirmation",
        "submission_status": "manual_confirmation_required",
        "strategy_refs": ["strategy:dual_ma"],
        "risk_refs": ["risk:risk-001"],
        "signal_refs": ["signal:signal-001"],
    }
    assert run["orders"][0]["order_intent"] == expected_order_intent_summary
    assert json.loads(latest["payload_json"])["orders"][0]["order_intent"] == (
        expected_order_intent_summary
    )
    expected_divergence_summary = {
        "status": "within_expectations",
        "order_intent_count": 1,
        "simulated_order_count": 1,
        "simulated_fill_count": 1,
        "missing_simulation_count": 0,
        "diverged_order_count": 0,
        "current_account_facts": {
            "available_cash": 5000.0,
            "cash_status_counts": {"sufficient": 1},
            "constraint_status_counts": {"pass": 2},
            "position_effect_count": 1,
        },
        "broker_account_truth_state": {
            "gate_status": "pass",
            "has_evidence": True,
            "blocking_reasons": [],
        },
        "cost_summary": {
            "estimated_total_fee": "5.0",
            "simulated_fee_tax_cost": "5.0100000",
            "simulated_slippage_cost": "0.00",
            "simulated_total_execution_cost": "5.0100000",
            "fee_rule_ids": ["stock_a_commission_v1"],
            "fill_count_with_cost_evidence": 1,
        },
        "expected_strategy_behavior": {
            "source_decision": "buy",
            "expected_order_count": 1,
            "symbols": ["600519"],
            "side_counts": {"buy": 1},
            "strategy_refs": ["strategy:dual_ma"],
            "risk_refs": ["risk:risk-001"],
            "signal_refs": ["signal:signal-001"],
            "risk_gate_status_counts": {"passed": 1},
            "manual_confirmation_status_counts": {"ready_for_manual_confirmation": 1},
            "submission_status_counts": {"manual_confirmation_required": 1},
        },
        "execution_comparison": {
            "matched_order_count": 1,
            "missing_order_intent_refs": [],
            "diverged_order_refs": [],
            "failed_order_refs": [],
            "simulated_status_counts": {"filled": 1},
            "fill_count_by_order": {orders[0]["order_id"]: 1},
            "filled_quantity_by_order": {orders[0]["order_id"]: "100.0"},
            "remaining_quantity_by_order": {orders[0]["order_id"]: "0.0"},
        },
        "realized_market_context": {
            "symbol_count": 1,
            "price_basis_counts": {"estimated_price": 1},
            "symbols": [
                {
                    "symbol": "600519",
                    "price_basis": "estimated_price",
                    "expected_price": 10.0,
                    "simulated_fill_prices": ["10.0"],
                    "simulated_slippage_cost": "0.00",
                }
            ],
        },
        "next_manual_review_step": "review_manual_confirmation",
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    assert run["divergence_summary"] == expected_divergence_summary
    assert json.loads(latest["payload_json"])["divergence_summary"] == (
        expected_divergence_summary
    )

    assert len(orders) == 1
    assert orders[0]["execution_mode"] == "paper_shadow"
    assert orders[0]["source"] == "paper_shadow_daily"
    assert orders[0]["status"] == "filled"
    oms_order = db.get_oms_order_sync(orders[0]["order_id"])
    oms_transitions = db.list_oms_transitions_sync(orders[0]["order_id"])
    assert oms_order is not None
    assert oms_order["status"] == "filled"
    assert oms_order["broker_submission_enabled"] == 0
    oms_payload = json.loads(oms_order["payload_json"])
    assert oms_payload["execution_mode"] == "paper_shadow"
    assert oms_payload["run_id"] == run["run_id"]
    assert oms_payload["does_not_submit_broker_order"] is True
    assert oms_payload["does_not_mutate_production_ledger"] is True
    assert [item["to_status"] for item in oms_transitions] == [
        "staged",
        "submitted",
        "accepted",
        "filled",
    ]
    assert json.loads(oms_transitions[-1]["payload_json"])["source"] == (
        "paper_shadow_daily"
    )
    order_payload = json.loads(orders[0]["payload_json"])
    assert order_payload["run_id"] == run["run_id"]
    assert order_payload["plan_date"] == "2026-07-02"
    assert order_payload["input_fingerprint"] == run["input_fingerprint"]
    assert order_payload["order_intent_ref"] == "action:ACTION-1"
    assert order_payload["context"]["strategy_id"] == "strategy:dual_ma"
    assert order_payload["context"]["risk_decision_id"] == "risk:risk-001"
    assert order_payload["context"]["signal_id"] == "signal:signal-001"
    assert order_payload["order_intent"] == expected_order_intent_summary
    assert order_payload["divergence_status"] == "within_expectations"
    assert order_payload["oms_transitions"][-1]["timestamp"] == ("2026-07-02T09:35:00")
    assert order_payload["oms_transitions"][-1]["source"] == "paper_shadow_daily"
    assert order_payload["does_not_submit_broker_order"] is True
    assert order_payload["does_not_mutate_production_ledger"] is True

    assert len(fills) == 1
    assert fills[0]["execution_mode"] == "paper_shadow"
    assert fills[0]["source"] == "paper_shadow_daily"
    assert fills[0]["order_id"] == orders[0]["order_id"]
    assert _ledger_entry_count(db) == ledger_count_before


def test_paper_shadow_run_summary_includes_cost_projection_evidence(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    run = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
        outcome_overrides={
            "600519": {
                "outcome": "filled",
                "fill_price": 10.10,
            }
        },
    )

    assert run["simulated_fill_count"] == 1
    assert run["fills"][0]["commission"] == "5.0101000"
    assert run["fills"][0]["slippage"] == "10.00"
    assert run["fills"][0]["fee_breakdown"]["total_fee"] == "5.0101000"
    assert run["fills"][0]["cost_modeling"]["reference_price"] == "10.0"


def test_paper_shadow_divergence_summary_compares_strategy_execution_and_market_context(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    run = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
        outcome_overrides={
            "600519": {
                "outcome": "partial",
                "fill_quantity": 40,
                "fill_price": 10.05,
            }
        },
    )

    order_id = run["orders"][0]["order_id"]
    summary = run["divergence_summary"]

    assert summary["expected_strategy_behavior"] == {
        "source_decision": "buy",
        "expected_order_count": 1,
        "symbols": ["600519"],
        "side_counts": {"buy": 1},
        "strategy_refs": ["strategy:dual_ma"],
        "risk_refs": ["risk:risk-001"],
        "signal_refs": ["signal:signal-001"],
        "risk_gate_status_counts": {"passed": 1},
        "manual_confirmation_status_counts": {"ready_for_manual_confirmation": 1},
        "submission_status_counts": {"manual_confirmation_required": 1},
    }
    assert summary["execution_comparison"] == {
        "matched_order_count": 1,
        "missing_order_intent_refs": [],
        "diverged_order_refs": ["action:ACTION-1"],
        "failed_order_refs": [],
        "simulated_status_counts": {"partially_filled": 1},
        "fill_count_by_order": {order_id: 1},
        "filled_quantity_by_order": {order_id: "40"},
        "remaining_quantity_by_order": {order_id: "60.0"},
    }
    assert summary["realized_market_context"] == {
        "symbol_count": 1,
        "price_basis_counts": {"estimated_price": 1},
        "symbols": [
            {
                "symbol": "600519",
                "price_basis": "estimated_price",
                "expected_price": 10.0,
                "simulated_fill_prices": ["10.05"],
                "simulated_slippage_cost": "2.00",
            }
        ],
    }
    assert summary["does_not_submit_broker_order"] is True
    assert summary["does_not_mutate_production_ledger"] is True


def test_paper_shadow_run_is_idempotent_for_same_plan_fingerprint(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    first = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
    )
    second = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:40:00",
    )

    assert second["run_id"] == first["run_id"]
    assert second["input_fingerprint"] == first["input_fingerprint"]
    assert len(db.list_orders_sync()) == 1
    assert len(db.list_fills_sync()) == 1
    assert _paper_shadow_run_count(db) == 1
    orders = db.list_orders_sync()
    assert len(db.list_oms_transitions_sync(orders[0]["order_id"])) == 4


def test_paper_shadow_run_creates_new_run_when_simulation_inputs_change(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    filled = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
    )
    rejected = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:40:00",
        outcome_overrides={
            "600519": {
                "outcome": "rejected",
                "reason": "fixture_reprice",
            }
        },
    )

    assert rejected["run_id"] != filled["run_id"]
    assert rejected["input_fingerprint"] != filled["input_fingerprint"]
    assert rejected["status"] == "diverged"
    assert _paper_shadow_run_count(db) == 2
    assert len(db.list_orders_sync()) == 2
    assert len(db.list_fills_sync()) == 1


def test_paper_shadow_run_records_review_required_when_intent_inputs_are_missing(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    plan = _trading_plan()
    plan["order_intents"][0]["estimated_price"] = None

    run = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=plan,
        generated_at="2026-07-02T09:35:00",
    )

    assert run["status"] == "review_required"
    assert run["order_intent_count"] == 1
    assert run["simulated_order_count"] == 0
    assert run["simulated_fill_count"] == 0
    assert run["next_manual_review_step"] == "review_shadow_divergence"
    assert any("estimated_price" in item for item in run["limitations"])
    assert db.list_orders_sync() == []
    assert db.list_fills_sync() == []


def test_paper_shadow_run_records_rejected_order_without_fill(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    run = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
        outcome_overrides={"600519": {"outcome": "rejected", "reason": "fixture"}},
    )

    orders = db.list_orders_sync()

    assert run["status"] == "diverged"
    assert run["divergence_status"] == "diverged"
    assert run["next_manual_review_step"] == "resolve_shadow_divergence"
    assert run["simulated_order_count"] == 1
    assert run["simulated_fill_count"] == 0
    assert orders[0]["status"] == "rejected"
    assert db.list_fills_sync() == []
    assert _paper_shadow_run_count(db) == 1


def test_paper_shadow_run_marks_partial_fill_as_diverged(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    run = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
        outcome_overrides={
            "600519": {
                "outcome": "partial",
                "fill_quantity": 40,
                "fill_price": 10.05,
            }
        },
    )

    orders = db.list_orders_sync()

    assert run["status"] == "diverged"
    assert run["divergence_status"] == "diverged"
    assert run["next_manual_review_step"] == "resolve_shadow_divergence"
    assert run["simulated_order_count"] == 1
    assert run["simulated_fill_count"] == 1
    assert run["orders"][0]["status"] == "partially_filled"
    assert run["orders"][0]["divergence_status"] == "diverged"
    review_item = run["review_queue"][0]
    assert review_item["review_id"] == f"{run['run_id']}:ACTION-1"
    assert review_item["order_intent_ref"] == "action:ACTION-1"
    assert review_item["order_id"] == run["orders"][0]["order_id"]
    assert review_item["symbol"] == "600519"
    assert review_item["status"] == "partially_filled"
    assert review_item["divergence_status"] == "diverged"
    assert review_item["severity"] == "warning"
    assert review_item["required_action"] == "resolve_shadow_divergence"
    assert review_item["reason"] == (
        "Paper/shadow order partially_filled; compare simulated execution "
        "with the original order intent before manual confirmation."
    )
    assert review_item["filled_quantity"] == "40"
    assert review_item["remaining_quantity"] == "60.0"
    assert review_item["does_not_submit_broker_order"] is True
    assert review_item["does_not_mutate_production_ledger"] is True
    saved = db.latest_paper_shadow_run_sync(plan_date="2026-07-02")
    assert saved is not None
    assert json.loads(saved["payload_json"])["review_queue"] == run["review_queue"]
    assert orders[0]["status"] == "partially_filled"


def test_paper_shadow_review_queue_carries_structured_review_evidence(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    run = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
        outcome_overrides={
            "600519": {
                "outcome": "partial",
                "fill_quantity": 40,
                "fill_price": 10.05,
            }
        },
    )

    item = run["review_queue"][0]

    assert item["strategy_refs"] == ["strategy:dual_ma"]
    assert item["risk_refs"] == ["risk:risk-001"]
    assert item["signal_refs"] == ["signal:signal-001"]
    assert item["evidence_refs"] == [
        "action:ACTION-1",
        "strategy:dual_ma",
        "risk:risk-001",
        "signal:signal-001",
        f"paper_order:{run['orders'][0]['order_id']}",
        f"paper_fill:{run['fills'][0]['fill_id']}",
    ]
    assert item["account_truth"] == {
        "gate_status": "pass",
        "has_evidence": True,
        "blocking_reasons": [],
    }
    assert item["risk_gate_status"] == "passed"
    assert item["manual_confirmation_status"] == "ready_for_manual_confirmation"
    assert item["submission_status"] == "manual_confirmation_required"
    assert item["cash_status"] == "sufficient"
    assert item["constraint_status_counts"] == {"pass": 2}
    assert item["cost_evidence"] == {
        "estimated_gross_amount": "1000.0",
        "estimated_total_fee": "5.0",
        "simulated_fee_tax_cost": run["fills"][0]["fee_breakdown"]["total_fee"],
        "simulated_slippage_cost": run["fills"][0]["slippage"],
        "fee_rule_id": "stock_a_commission_v1",
    }
    assert item["market_context"] == {
        "price_basis": "estimated_price",
        "expected_price": "10.0",
        "simulated_fill_prices": ["10.05"],
    }
    assert item["oms_status_path"] == [
        "staged",
        "submitted",
        "accepted",
        "partially_filled",
    ]
    assert item["oms_transition_refs"] == [
        f"oms_transition:{run['orders'][0]['order_id']}:1:staged",
        f"oms_transition:{run['orders'][0]['order_id']}:2:submitted",
        f"oms_transition:{run['orders'][0]['order_id']}:3:accepted",
        f"oms_transition:{run['orders'][0]['order_id']}:4:partially_filled",
    ]
    assert item["oms_transitions"] == [
        {
            "sequence": 1,
            "from_status": None,
            "to_status": "staged",
            "source": "paper_shadow_daily",
            "reason": "",
            "filled_quantity": "0",
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        },
        {
            "sequence": 2,
            "from_status": "staged",
            "to_status": "submitted",
            "source": "paper_shadow_daily",
            "reason": "",
            "filled_quantity": "0",
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        },
        {
            "sequence": 3,
            "from_status": "submitted",
            "to_status": "accepted",
            "source": "paper_shadow_daily",
            "reason": "",
            "filled_quantity": "0",
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        },
        {
            "sequence": 4,
            "from_status": "accepted",
            "to_status": "partially_filled",
            "source": "paper_shadow_daily",
            "reason": "",
            "filled_quantity": "40",
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        },
    ]
    assert item["does_not_submit_broker_order"] is True
    assert item["does_not_mutate_production_ledger"] is True


def test_paper_shadow_run_marks_cancelled_and_expired_orders_as_diverged(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    cancelled_plan = _trading_plan()
    expired_plan = _trading_plan()
    expired_plan["order_intents"][0]["action_id"] = "ACTION-2"

    cancelled = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=cancelled_plan,
        generated_at="2026-07-02T09:35:00",
        outcome_overrides={
            "600519": {"outcome": "cancelled", "reason": "operator_cancelled"}
        },
    )
    expired = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=expired_plan,
        generated_at="2026-07-02T09:36:00",
        outcome_overrides={
            "ACTION-2": {"outcome": "expired", "reason": "paper_session_closed"}
        },
    )

    assert cancelled["status"] == "diverged"
    assert cancelled["divergence_status"] == "diverged"
    assert cancelled["orders"][0]["status"] == "cancelled"
    assert cancelled["simulated_fill_count"] == 0
    assert expired["status"] == "diverged"
    assert expired["divergence_status"] == "diverged"
    assert expired["orders"][0]["status"] == "expired"
    assert expired["simulated_fill_count"] == 0


def test_paper_shadow_run_records_failed_run_when_simulation_errors(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    run = run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
        outcome_overrides={
            "600519": {
                "outcome": "partial",
                "fill_quantity": 1000,
            }
        },
    )

    orders = db.list_orders_sync()
    saved = db.latest_paper_shadow_run_sync(plan_date="2026-07-02")
    order_payload = json.loads(orders[0]["payload_json"])

    assert run["status"] == "failed"
    assert run["divergence_status"] == "failed"
    assert run["next_manual_review_step"] == "inspect_failed_run"
    assert run["simulated_order_count"] == 1
    assert run["simulated_fill_count"] == 0
    assert run["orders"][0]["status"] == "failed"
    assert run["orders"][0]["divergence_status"] == "failed"
    assert run["review_queue"][0]["required_action"] == "inspect_failed_run"
    assert run["review_queue"][0]["severity"] == "danger"
    assert run["review_queue"][0]["reason"] == (
        "Paper/shadow simulation failed for action:ACTION-1: "
        "ValueError: Paper fill quantity cannot exceed order quantity."
    )
    assert run["review_queue"][0]["does_not_submit_broker_order"] is True
    assert run["review_queue"][0]["does_not_mutate_production_ledger"] is True
    assert any(
        "Paper fill quantity cannot exceed order quantity" in item
        for item in run["limitations"]
    )
    assert saved is not None
    assert saved["status"] == "failed"
    assert orders[0]["execution_mode"] == "paper_shadow"
    assert orders[0]["status"] == "failed"
    assert order_payload["error_type"] == "ValueError"
    assert order_payload["does_not_submit_broker_order"] is True
    assert order_payload["does_not_mutate_production_ledger"] is True
    assert db.list_fills_sync() == []


def _trading_plan() -> dict:
    return {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T09:30:00",
        "source_decision": "buy",
        "available_cash": 5000.0,
        "account_truth": {
            "gate_status": "pass",
            "has_evidence": True,
            "blocking_reasons": [],
        },
        "order_intent_count": 1,
        "order_intents": [
            {
                "action_id": "ACTION-1",
                "symbol": "600519",
                "asset_class": "stock",
                "side": "buy",
                "estimated_price": 10.0,
                "estimated_quantity": 100.0,
                "estimated_gross_amount": 1000.0,
                "estimated_total_fee": 5.0,
                "fee_rule_id": "stock_a_commission_v1",
                "available_cash_before": 5000.0,
                "available_cash_after": 3995.0,
                "cash_status": "sufficient",
                "cash_shortfall": 0.0,
                "position_effect": {
                    "current_quantity": 0.0,
                    "current_avg_cost": 0.0,
                    "current_market_value": 0.0,
                    "estimated_quantity_after": 100.0,
                    "estimated_avg_cost_after": 10.0,
                    "cost_basis_method": "weighted_average_preview",
                },
                "constraint_checks": [
                    {"id": "trading_unit", "status": "pass"},
                    {"id": "cash_buffer", "status": "pass"},
                ],
                "risk_gate_status": "passed",
                "manual_confirmation_status": "ready_for_manual_confirmation",
                "submission_status": "manual_confirmation_required",
                "does_not_submit_broker_order": True,
                "evidence_refs": [
                    "strategy:dual_ma",
                    "risk:risk-001",
                    "signal:signal-001",
                ],
            }
        ],
    }


def _ledger_entry_count(db: AppDatabase) -> int:
    with sqlite3.connect(db._path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0])


def _paper_shadow_run_count(db: AppDatabase) -> int:
    with sqlite3.connect(db._path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM paper_shadow_runs").fetchone()[0])
