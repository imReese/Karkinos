from __future__ import annotations

from types import SimpleNamespace

from server.routes.account_strategy import _linked_strategy_evidence


def test_paper_shadow_orders_and_fills_are_excluded_from_strategy_attribution() -> None:
    class FakeDb:
        def list_signal_journal_sync(self, limit: int, offset: int):
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

        def list_orders_sync(self, limit: int, offset: int):
            return [
                {
                    "order_id": "SHADOW-ORDER-1",
                    "risk_decision_id": "RISK-PAPER-1",
                    "intent_id": "INTENT-PAPER-1",
                    "execution_mode": "paper_shadow",
                }
            ]

        def list_fills_sync(self, limit: int, offset: int):
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
