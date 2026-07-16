from __future__ import annotations

from types import SimpleNamespace

from server.db import AppDatabase
from server.routes.decision import _strategy_attribution_gate_evidence


def _database(tmp_path) -> AppDatabase:
    db = AppDatabase(tmp_path / "decision-attribution.db")
    db.init_sync()
    db.set_runtime_control_sync(
        "account_strategy_assignment",
        {
            "strategy_id": "dual_ma",
            "strategy_name": "dual_ma",
            "status": "research_only",
            "scope": "account",
            "auto_trade_enabled": False,
            "attribution_status": "assignment_only",
            "limitations": [],
        },
    )
    return db


def test_no_strategy_fill_does_not_create_a_circular_decision_blocker(tmp_path) -> None:
    db = _database(tmp_path)

    gate = _strategy_attribution_gate_evidence(
        SimpleNamespace(config=SimpleNamespace(strategy="dual_ma")),
        db,
        [],
    )

    assert gate["gate_status"] == "pass"
    assert gate["contribution_status"] == "no_linked_fills"
    assert gate["evidence_binding_status"] == "not_applicable"
    assert gate["has_evidence"] is True
    assert gate["required_actions"] == []
    assert gate["blocking_reasons"] == []


def test_linked_candidate_signal_can_proceed_before_first_fill(tmp_path) -> None:
    db = _database(tmp_path)
    signal_id = db.save_signal_sync(
        timestamp="2026-07-16T09:30:00+08:00",
        strategy_id="dual_ma",
        symbol="510300",
        direction="buy",
        target_weight=0.2,
        price=4.57,
        asset_class="fund",
    )

    gate = _strategy_attribution_gate_evidence(
        SimpleNamespace(config=SimpleNamespace(strategy="dual_ma")),
        db,
        [
            {
                "strategy_id": "dual_ma",
                "source_signal_id": signal_id,
                "symbol": "510300",
            }
        ],
    )

    assert gate["gate_status"] == "pass"
    assert gate["contribution_status"] == "no_linked_fills"
    assert gate["attribution_status"] == "signal_chain_pending"
    assert gate["required_actions"] == []


def test_unattributed_strategy_fill_requires_lineage_review(tmp_path) -> None:
    db = _database(tmp_path)
    db.record_fill_sync(
        fill_id="FILL-UNATTRIBUTED-1",
        order_id="ORDER-WITHOUT-STRATEGY-LINEAGE",
        timestamp="2026-07-16T10:00:00+08:00",
        symbol="600000",
        side="buy",
        fill_price=10,
        fill_quantity=100,
        commission=5,
        slippage=1,
        asset_class="stock",
        execution_mode="manual",
        source="manual_confirmed_execution",
        source_ref="FILL-UNATTRIBUTED-1",
        metadata={"strategy_id": "dual_ma"},
    )

    gate = _strategy_attribution_gate_evidence(
        SimpleNamespace(config=SimpleNamespace(strategy="dual_ma")),
        db,
        [],
    )

    assert gate["gate_status"] == "blocked"
    assert gate["contribution_status"] == "no_linked_fills"
    assert gate["evidence_binding_status"] == "blocked"
    assert gate["has_evidence"] is False
    assert gate["unattributed_fill_count"] == 1
    assert gate["required_actions"] == ["review_unattributed_strategy_fill_lineage"]
    assert gate["blocking_reasons"] == [
        "unattributed_strategy_fills_require_lineage_review"
    ]
