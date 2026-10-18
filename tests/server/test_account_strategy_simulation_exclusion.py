from __future__ import annotations

from types import SimpleNamespace

from server.db import AppDatabase
from server.routes.account_strategy import _linked_strategy_evidence


def test_paper_shadow_orders_and_fills_are_excluded_from_strategy_attribution() -> None:
    class FakeDb:
        def list_signal_journal_sync(self, limit: int, offset: int, **_filters):
            return [
                {
                    "signal": {
                        "id": 7,
                        "strategy_id": "dual_ma",
                        "symbol": "600066",
                        "asset_class": "stock",
                    },
                    "risk_decision": {
                        "decision_id": "RISK-PAPER-1",
                        "intent_id": "INTENT-PAPER-1",
                    },
                }
            ]

        def list_orders_sync(self, limit: int, offset: int, **_filters):
            return [
                {
                    "order_id": "SHADOW-ORDER-1",
                    "risk_decision_id": "RISK-PAPER-1",
                    "intent_id": "INTENT-PAPER-1",
                    "execution_mode": "paper_shadow",
                }
            ]

        def list_fills_sync(self, limit: int, offset: int, **_filters):
            return [
                {
                    "fill_id": "SHADOW-FILL-1",
                    "order_id": "SHADOW-ORDER-1",
                    "metadata_json": (
                        '{"execution_mode":"paper_shadow",'
                        '"strategy_id":"dual_ma","source_signal_id":7}'
                    ),
                }
            ]

    assignment = SimpleNamespace(
        strategy_id="dual_ma",
        scope="account",
        asset_class=None,
        symbol=None,
    )

    evidence = _linked_strategy_evidence(FakeDb(), assignment)

    assert evidence["linked_orders"] == []
    assert evidence["linked_fills"] == []
    assert evidence["unattributed_fills"] == []
    assert evidence["unattributed_fill_count"] == 0


def test_simulation_order_is_reopened_for_a_fill_linked_only_by_metadata(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    signal_id = db.save_signal_sync(
        timestamp="2026-04-18T09:30:00+08:00",
        strategy_id="dual_ma",
        symbol="600066",
        direction="buy",
        target_weight=0.1,
        price=1,
        asset_class="stock",
    )
    db.record_order_sync(
        order_id="unlinked-shadow-order",
        timestamp="2026-04-18T09:31:00+08:00",
        symbol="600066",
        side="buy",
        order_type="market",
        quantity=100,
        price=1,
        execution_mode="paper_shadow",
        payload={},
    )
    db.record_fill_sync(
        fill_id="metadata-linked-shadow-fill",
        order_id="unlinked-shadow-order",
        timestamp="2026-04-18T09:32:00+08:00",
        symbol="600066",
        side="buy",
        fill_price=1,
        fill_quantity=100,
        execution_mode="paper_shadow",
        metadata={"strategy_id": "dual_ma", "source_signal_id": signal_id},
    )
    assignment = SimpleNamespace(
        strategy_id="dual_ma", scope="symbol", symbol="600066", asset_class=None
    )

    evidence = _linked_strategy_evidence(db, assignment)

    assert evidence["signal_ids"] == {signal_id}
    assert evidence["linked_orders"] == []
    assert evidence["linked_fills"] == []
    assert evidence["unattributed_fills"] == []
    assert evidence["unattributed_fill_count"] == 0
