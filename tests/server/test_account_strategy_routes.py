from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from core.events import OrderIntentEvent, RiskDecisionEvent
from core.types import OrderSide, Symbol
from server.db import AppDatabase


def _route(router, path: str, method: str = "GET"):
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


class StrategyHealthFakeDb:
    def __init__(
        self,
        *,
        assignment_status: str = "research_only",
        linked_fill: bool = False,
        valuation_available: bool = True,
        unattributed_fill: bool = False,
    ) -> None:
        self.assignment_status = assignment_status
        self.linked_fill = linked_fill
        self.valuation_available = valuation_available
        self.unattributed_fill = unattributed_fill

    def get_runtime_control_sync(self, key):
        return {
            "strategy_id": "dual_ma",
            "strategy_name": "dual_ma",
            "status": self.assignment_status,
            "scope": "account",
            "auto_trade_enabled": False,
            "attribution_status": "assignment_only",
            "limitations": [
                "Strategy assignment is research evidence only until signals, reviews, and fills are attributed."
            ],
        }

    def list_signal_journal_sync(self, limit=500, offset=0):
        return [
            {
                "signal": {
                    "id": 1,
                    "strategy_id": "dual_ma",
                    "symbol": "510300",
                    "asset_class": "fund",
                }
            }
        ]

    def list_orders_sync(self, limit=1000, offset=0):
        return []

    def list_fills_sync(self, limit=1000, offset=0):
        fills = []
        if self.linked_fill:
            fills.append(
                {
                    "fill_id": "FILL-HEALTH-LINKED",
                    "order_id": "ORD-HEALTH-LINKED",
                    "timestamp": "2026-06-18T09:35:00",
                    "symbol": "510300",
                    "side": "buy",
                    "fill_price": 4.57,
                    "fill_quantity": 100,
                    "commission": 5.0,
                    "slippage": 0,
                    "asset_class": "fund",
                    "metadata_json": '{"strategy_id":"dual_ma","source_signal_id":1}',
                }
            )
        if self.unattributed_fill:
            fills.append(
                {
                    "fill_id": "FILL-HEALTH-UNATTRIBUTED",
                    "order_id": "ORD-HEALTH-UNATTRIBUTED",
                    "timestamp": "2026-06-18T09:45:00",
                    "symbol": "510300",
                    "side": "buy",
                    "fill_price": 4.58,
                    "fill_quantity": 100,
                    "commission": 5.0,
                    "slippage": 0,
                    "asset_class": "fund",
                    "metadata_json": '{"strategy_id":"dual_ma"}',
                }
            )
        return fills

    def get_latest_quote_sync(self, symbol, asset_type=None):
        if not self.valuation_available:
            return None
        return {"price": 4.8}

    def get_ledger_entries_sync(self, limit=1000, offset=0):
        return []

    def get_cash_flows_sync(self, limit=1000, offset=0):
        return []


async def _strategy_contribution_response(monkeypatch, db):
    from server.routes import account_strategy as account_strategy_routes

    state = SimpleNamespace(config=SimpleNamespace(strategy="dual_ma"), db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    router = account_strategy_routes.create_router()
    endpoint = _route(router, "/api/account-strategy/contribution", "GET").endpoint
    return await endpoint()


@pytest.mark.asyncio
async def test_account_strategy_defaults_to_research_only_config_strategy(monkeypatch):
    from server.routes import account_strategy as account_strategy_routes

    router = account_strategy_routes.create_router()
    endpoint = _route(router, "/api/account-strategy", "GET").endpoint

    state = SimpleNamespace(
        config=SimpleNamespace(strategy="dual_ma"),
        db=SimpleNamespace(get_runtime_control_sync=lambda key: None),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: state)

    response = await endpoint()

    assert response.strategy_id == "dual_ma"
    assert response.status == "research_only"
    assert response.scope == "account"
    assert response.auto_trade_enabled is False
    assert response.attribution_status == "not_started"
    assert response.limitations == [
        "Strategy assignment is research evidence only until signals, reviews, and fills are attributed."
    ]


@pytest.mark.asyncio
async def test_account_strategy_contribution_marks_strategy_health_states(monkeypatch):
    cases = [
        (
            StrategyHealthFakeDb(linked_fill=True),
            "healthy",
            ["linked_fill_evidence_available"],
        ),
        (
            StrategyHealthFakeDb(linked_fill=True, unattributed_fill=True),
            "degraded",
            ["unattributed_strategy_movement"],
        ),
        (
            StrategyHealthFakeDb(linked_fill=True, valuation_available=False),
            "stale",
            ["valuation_missing"],
        ),
        (
            StrategyHealthFakeDb(assignment_status="paused", linked_fill=True),
            "paused",
            ["assignment_paused"],
        ),
        (
            StrategyHealthFakeDb(linked_fill=False),
            "needs_review",
            ["linked_fill_evidence_missing"],
        ),
    ]

    for db, expected_status, expected_reasons in cases:
        response = await _strategy_contribution_response(monkeypatch, db)

        assert response.strategy_health_status == expected_status
        assert response.strategy_health_reasons == expected_reasons


@pytest.mark.asyncio
async def test_account_strategy_update_persists_manual_confirm_assignment(monkeypatch):
    from server.models import AccountStrategyAssignmentUpdate
    from server.routes import account_strategy as account_strategy_routes

    router = account_strategy_routes.create_router()
    endpoint = _route(router, "/api/account-strategy", "PUT").endpoint
    persisted: dict[str, object] = {}

    class FakeDb:
        def get_runtime_control_sync(self, key):
            return persisted.get(key)

        def set_runtime_control_sync(self, key, value):
            persisted[key] = value

    state = SimpleNamespace(config=SimpleNamespace(strategy="dual_ma"), db=FakeDb())
    monkeypatch.setattr("server.app.get_app_state", lambda: state)

    response = await endpoint(
        AccountStrategyAssignmentUpdate(
            strategy_id="bollinger",
            status="paper_review",
            scope="symbol",
            symbol="600002",
            effective_from="2026-06-18",
            notes="observe before manual confirmation",
        )
    )

    assert response.strategy_id == "bollinger"
    assert response.status == "paper_review"
    assert response.scope == "symbol"
    assert response.symbol == "600002"
    assert response.auto_trade_enabled is False
    assert response.attribution_status == "assignment_only"
    assert persisted["account_strategy_assignment"]["strategy_id"] == "bollinger"
    assert persisted["account_strategy_assignment"]["auto_trade_enabled"] is False


@pytest.mark.asyncio
async def test_account_strategy_asset_class_scope_filters_attribution(monkeypatch):
    from server.models import AccountStrategyAssignmentUpdate
    from server.routes import account_strategy as account_strategy_routes

    router = account_strategy_routes.create_router()
    update_endpoint = _route(router, "/api/account-strategy", "PUT").endpoint
    attribution_endpoint = _route(
        router, "/api/account-strategy/attribution", "GET"
    ).endpoint
    persisted: dict[str, object] = {}

    class FakeDb:
        def get_runtime_control_sync(self, key):
            return persisted.get(key)

        def set_runtime_control_sync(self, key, value):
            persisted[key] = value

        def list_signal_journal_sync(self, limit=500, offset=0):
            return [
                {
                    "signal": {
                        "id": 1,
                        "strategy_id": "dual_ma",
                        "symbol": "600519",
                        "asset_class": "stock",
                    }
                },
                {
                    "signal": {
                        "id": 2,
                        "strategy_id": "dual_ma",
                        "symbol": "019999",
                        "asset_class": "fund",
                    }
                },
            ]

        def list_orders_sync(self, limit=1000, offset=0):
            return []

        def list_fills_sync(self, limit=1000, offset=0):
            return []

    state = SimpleNamespace(config=SimpleNamespace(strategy="dual_ma"), db=FakeDb())
    monkeypatch.setattr("server.app.get_app_state", lambda: state)

    response = await update_endpoint(
        AccountStrategyAssignmentUpdate(
            strategy_id="dual_ma",
            status="paper_review",
            scope="asset_class",
            asset_class="stock",
            effective_from="2026-06-18",
            notes="stock lane only",
        )
    )
    attribution = await attribution_endpoint()

    assert response.scope == "asset_class"
    assert response.asset_class == "stock"
    assert persisted["account_strategy_assignment"]["asset_class"] == "stock"
    assert attribution.signal_count == 1
    assert attribution.evidence_refs == ["signal:1"]


@pytest.mark.asyncio
async def test_account_strategy_attribution_links_signal_order_and_fill_without_claiming_pnl(
    monkeypatch, tmp_path
):
    from datetime import datetime
    from decimal import Decimal

    from server.routes import account_strategy as account_strategy_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.set_runtime_control_sync(
        "account_strategy_assignment",
        {
            "strategy_id": "dual_ma",
            "strategy_name": "dual_ma",
            "status": "research_only",
            "scope": "account",
            "symbol": None,
            "effective_from": "2026-06-18",
            "auto_trade_enabled": False,
            "attribution_status": "assignment_only",
            "attributed_pnl": None,
            "realized_pnl": None,
            "unrealized_pnl": None,
            "total_fees": None,
            "notes": "fixture assignment",
            "updated_at": "2026-06-18T10:00:00",
            "limitations": [
                "Strategy assignment is research evidence only until signals, reviews, and fills are attributed."
            ],
        },
    )
    db.save_signal_sync(
        timestamp="2026-06-18T09:30:00",
        strategy_id="dual_ma",
        symbol="510300",
        direction="buy",
        target_weight=0.2,
        price=4.56,
        asset_class="fund",
    )
    db.upsert_action_task_sync(
        source_signal_id=1,
        symbol="510300",
        title="研究信号",
        detail="dual_ma 触发",
        direction="buy",
        urgency="medium",
        target_weight=0.2,
        price=4.56,
        strategy_id="dual_ma",
        timestamp="2026-06-18T09:31:00",
        asset_class="fund",
    )
    intent = OrderIntentEvent(
        timestamp=datetime(2026, 6, 18, 9, 32),
        intent_id="INTENT-ATTR-1",
        strategy_id="dual_ma",
        symbol=Symbol("510300"),
        side=OrderSide.BUY,
        target_weight=Decimal("0.20"),
        quantity=Decimal("100"),
        reference_price=Decimal("4.56"),
        source_signal_id="1",
        reason="attribution fixture",
    )
    decision = RiskDecisionEvent(
        timestamp=datetime(2026, 6, 18, 9, 33),
        decision_id="RISK-ATTR-1",
        intent_id=intent.intent_id,
        passed=True,
        symbol=intent.symbol,
        side=intent.side,
        reasons=[],
        severity="info",
    )
    db.save_risk_decision_sync(intent=intent, decision=decision)
    db.record_signal_review_sync(
        signal_id=1,
        reviewed_at="2026-06-18T09:33:30",
        user_decision="accepted",
        outcome="paper_order_prepared",
        review_notes="Research-only review accepted the candidate for paper execution.",
        reviewer="local",
    )
    db.record_order_sync(
        order_id="ORD-ATTR-1",
        timestamp="2026-06-18T09:34:00",
        symbol="510300",
        side="buy",
        order_type="market",
        quantity=100,
        price=4.57,
        asset_class="fund",
        intent_id="INTENT-ATTR-1",
        risk_decision_id="RISK-ATTR-1",
        execution_mode="paper",
        status="filled",
        source="paper_execution",
        source_ref="ORD-ATTR-1",
        payload={"strategy_id": "dual_ma", "source_signal_id": 1},
    )
    db.record_fill_sync(
        fill_id="FILL-ATTR-1",
        order_id="ORD-ATTR-1",
        timestamp="2026-06-18T09:35:00",
        symbol="510300",
        side="buy",
        fill_price=4.57,
        fill_quantity=100,
        commission=5.0,
        slippage=1.5,
        asset_class="fund",
        execution_mode="paper",
        source="paper_execution",
        source_ref="FILL-ATTR-1",
        metadata={"strategy_id": "dual_ma", "source_signal_id": 1},
    )

    state = SimpleNamespace(config=SimpleNamespace(strategy="dual_ma"), db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    router = account_strategy_routes.create_router()
    endpoint = _route(router, "/api/account-strategy/attribution", "GET").endpoint

    response = await endpoint()

    assert response.strategy_id == "dual_ma"
    assert response.attribution_status == "evidence_linked_pnl_pending"
    assert response.signal_count == 1
    assert response.action_count == 1
    assert response.risk_decision_count == 1
    assert response.order_count == 1
    assert response.fill_count == 1
    assert response.total_fees == 6.5
    assert response.attributed_pnl is None
    assert response.unattributed_fill_count == 0
    assert response.evidence_refs == [
        "signal:1",
        "action:1",
        "risk:RISK-ATTR-1",
        "review:1",
        "order:ORD-ATTR-1",
        "fill:FILL-ATTR-1",
    ]
    assert response.limitations == [
        "P/L contribution is not calculated until fills are reconciled with position and valuation history."
    ]


@pytest.mark.asyncio
async def test_holding_strategy_attribution_filters_exact_symbol_evidence(
    monkeypatch,
):
    from server.routes import account_strategy as account_strategy_routes

    class FakeDb:
        def get_runtime_control_sync(self, key):
            return {
                "strategy_id": "dual_ma",
                "strategy_name": "dual_ma",
                "status": "research_only",
                "scope": "account",
                "auto_trade_enabled": False,
                "attribution_status": "assignment_only",
                "limitations": [
                    "Strategy assignment is research evidence only until signals, reviews, and fills are attributed."
                ],
            }

        def list_signal_journal_sync(self, limit=500, offset=0):
            return [
                {
                    "signal": {
                        "id": 1,
                        "strategy_id": "dual_ma",
                        "symbol": "510300",
                        "asset_class": "fund",
                    },
                    "action_task": {"id": 101},
                    "risk_decision": {
                        "decision_id": "RISK-HOLDING-1",
                        "intent_id": "INTENT-HOLDING-1",
                    },
                    "review": {"signal_id": 1},
                },
                {
                    "signal": {
                        "id": 2,
                        "strategy_id": "dual_ma",
                        "symbol": "600000",
                        "asset_class": "stock",
                    },
                    "action_task": {"id": 202},
                    "risk_decision": {
                        "decision_id": "RISK-OTHER-1",
                        "intent_id": "INTENT-OTHER-1",
                    },
                    "review": {"signal_id": 2},
                },
            ]

        def list_orders_sync(self, limit=1000, offset=0):
            return [
                {
                    "order_id": "ORD-HOLDING-1",
                    "symbol": "510300",
                    "payload_json": '{"source_signal_id":1}',
                    "risk_decision_id": "RISK-HOLDING-1",
                    "intent_id": "INTENT-HOLDING-1",
                },
                {
                    "order_id": "ORD-OTHER-1",
                    "symbol": "600000",
                    "payload_json": '{"source_signal_id":2}',
                    "risk_decision_id": "RISK-OTHER-1",
                    "intent_id": "INTENT-OTHER-1",
                },
            ]

        def list_fills_sync(self, limit=1000, offset=0):
            return [
                {
                    "fill_id": "FILL-HOLDING-1",
                    "order_id": "ORD-HOLDING-1",
                    "timestamp": "2026-06-18T09:35:00",
                    "symbol": "510300",
                    "side": "buy",
                    "fill_price": 4.57,
                    "fill_quantity": 100,
                    "commission": 5.0,
                    "slippage": 0,
                    "asset_class": "fund",
                    "metadata_json": '{"strategy_id":"dual_ma","source_signal_id":1}',
                },
                {
                    "fill_id": "FILL-OTHER-1",
                    "order_id": "ORD-OTHER-1",
                    "timestamp": "2026-06-18T10:00:00",
                    "symbol": "600000",
                    "side": "buy",
                    "fill_price": 10,
                    "fill_quantity": 10,
                    "commission": 1,
                    "slippage": 0,
                    "asset_class": "stock",
                    "metadata_json": '{"strategy_id":"dual_ma","source_signal_id":2}',
                },
            ]

    state = SimpleNamespace(config=SimpleNamespace(strategy="dual_ma"), db=FakeDb())
    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    router = account_strategy_routes.create_router()
    endpoint = _route(
        router,
        "/api/account-strategy/holdings/{symbol}/attribution",
        "GET",
    ).endpoint

    response = await endpoint(symbol="510300")

    assert response.strategy_id == "dual_ma"
    assert response.symbol == "510300"
    assert response.assignment_scope == "account"
    assert response.assignment_applies_to_symbol is True
    assert response.attribution_status == "holding_evidence_linked_review_required"
    assert response.signal_count == 1
    assert response.action_count == 1
    assert response.risk_decision_count == 1
    assert response.order_count == 1
    assert response.fill_count == 1
    assert response.evidence_refs == [
        "signal:1",
        "action:101",
        "risk:RISK-HOLDING-1",
        "review:1",
        "order:ORD-HOLDING-1",
        "fill:FILL-HOLDING-1",
    ]
    assert response.limitations == [
        "Holding-level strategy attribution is evidence-only until the linked fills are reviewed against the production ledger and valuation history."
    ]


@pytest.mark.asyncio
async def test_account_strategy_contribution_separates_unrealized_pnl_and_costs(
    monkeypatch, tmp_path
):
    from datetime import datetime
    from decimal import Decimal

    from server.routes import account_strategy as account_strategy_routes

    db = AppDatabase(tmp_path / "app.db")
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
            "limitations": [
                "Strategy assignment is research evidence only until signals, reviews, and fills are attributed."
            ],
        },
    )
    db.save_signal_sync(
        timestamp="2026-06-18T09:30:00",
        strategy_id="dual_ma",
        symbol="510300",
        direction="buy",
        target_weight=0.2,
        price=4.56,
        asset_class="fund",
    )
    db.upsert_action_task_sync(
        source_signal_id=1,
        symbol="510300",
        title="研究信号",
        detail="dual_ma 触发",
        direction="buy",
        urgency="medium",
        target_weight=0.2,
        price=4.56,
        strategy_id="dual_ma",
        timestamp="2026-06-18T09:31:00",
        asset_class="fund",
    )
    intent = OrderIntentEvent(
        timestamp=datetime(2026, 6, 18, 9, 32),
        intent_id="INTENT-CONTRIB-1",
        strategy_id="dual_ma",
        symbol=Symbol("510300"),
        side=OrderSide.BUY,
        target_weight=Decimal("0.20"),
        quantity=Decimal("100"),
        reference_price=Decimal("4.56"),
        source_signal_id="1",
        reason="contribution fixture",
    )
    db.save_risk_decision_sync(
        intent=intent,
        decision=RiskDecisionEvent(
            timestamp=datetime(2026, 6, 18, 9, 33),
            decision_id="RISK-CONTRIB-1",
            intent_id=intent.intent_id,
            passed=True,
            symbol=intent.symbol,
            side=intent.side,
            reasons=[],
            severity="info",
        ),
    )
    db.record_order_sync(
        order_id="ORD-CONTRIB-1",
        timestamp="2026-06-18T09:34:00",
        symbol="510300",
        side="buy",
        order_type="market",
        quantity=100,
        price=4.57,
        asset_class="fund",
        intent_id="INTENT-CONTRIB-1",
        risk_decision_id="RISK-CONTRIB-1",
        execution_mode="paper",
        status="filled",
        source="paper_execution",
        source_ref="ORD-CONTRIB-1",
        payload={"strategy_id": "dual_ma", "source_signal_id": 1},
    )
    db.record_fill_sync(
        fill_id="FILL-CONTRIB-1",
        order_id="ORD-CONTRIB-1",
        timestamp="2026-06-18T09:35:00",
        symbol="510300",
        side="buy",
        fill_price=4.57,
        fill_quantity=100,
        commission=5.0,
        slippage=1.5,
        asset_class="fund",
        execution_mode="paper",
        source="paper_execution",
        source_ref="FILL-CONTRIB-1",
        metadata={"strategy_id": "dual_ma", "source_signal_id": 1},
    )
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="fund",
        price=4.8,
        quote_timestamp="2026-06-18T15:00:00+08:00",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="ok",
        quote_status="confirmed",
    )

    state = SimpleNamespace(config=SimpleNamespace(strategy="dual_ma"), db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    router = account_strategy_routes.create_router()
    endpoint = _route(router, "/api/account-strategy/contribution", "GET").endpoint

    response = await endpoint()

    assert response.strategy_id == "dual_ma"
    assert response.contribution_status == "estimated_from_linked_fills"
    assert response.linked_fill_count == 1
    assert response.gross_realized_pnl == 0
    assert response.gross_unrealized_pnl == 23
    assert response.total_commission == 5
    assert response.total_slippage == 1.5
    assert response.total_tax == 0
    assert response.net_contribution == 16.5
    assert response.unattributed_account_pnl is None
    assert response.manual_unattributed_pnl is None
    assert response.cash_flow_pnl is None
    assert response.missing_valuation_symbols == []
    assert response.limitations == [
        "Contribution is estimated only from fully linked strategy fills and latest local quotes; manual, cash-flow, and missing-evidence movements are separated and excluded from net contribution."
    ]


@pytest.mark.asyncio
async def test_account_strategy_contribution_separates_tax_manual_cash_and_missing_evidence(
    monkeypatch, tmp_path
):
    from datetime import datetime
    from decimal import Decimal

    from server.routes import account_strategy as account_strategy_routes

    db = AppDatabase(tmp_path / "app.db")
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
            "limitations": [
                "Strategy assignment is research evidence only until signals, reviews, and fills are attributed."
            ],
        },
    )
    db.save_signal_sync(
        timestamp="2026-06-18T09:30:00",
        strategy_id="dual_ma",
        symbol="510300",
        direction="buy",
        target_weight=0.2,
        price=4.56,
        asset_class="fund",
    )
    intent = OrderIntentEvent(
        timestamp=datetime(2026, 6, 18, 9, 32),
        intent_id="INTENT-COMPONENTS-1",
        strategy_id="dual_ma",
        symbol=Symbol("510300"),
        side=OrderSide.BUY,
        target_weight=Decimal("0.20"),
        quantity=Decimal("100"),
        reference_price=Decimal("4.56"),
        source_signal_id="1",
        reason="component attribution fixture",
    )
    db.save_risk_decision_sync(
        intent=intent,
        decision=RiskDecisionEvent(
            timestamp=datetime(2026, 6, 18, 9, 33),
            decision_id="RISK-COMPONENTS-1",
            intent_id=intent.intent_id,
            passed=True,
            symbol=intent.symbol,
            side=intent.side,
            reasons=[],
            severity="info",
        ),
    )
    db.record_order_sync(
        order_id="ORD-COMPONENTS-1",
        timestamp="2026-06-18T09:34:00",
        symbol="510300",
        side="buy",
        order_type="market",
        quantity=100,
        price=4.57,
        asset_class="fund",
        intent_id="INTENT-COMPONENTS-1",
        risk_decision_id="RISK-COMPONENTS-1",
        execution_mode="paper",
        status="filled",
        source="paper_execution",
        source_ref="ORD-COMPONENTS-1",
        payload={"strategy_id": "dual_ma", "source_signal_id": 1},
    )
    db.record_fill_sync(
        fill_id="FILL-COMPONENTS-1",
        order_id="ORD-COMPONENTS-1",
        timestamp="2026-06-18T09:35:00",
        symbol="510300",
        side="buy",
        fill_price=4.57,
        fill_quantity=100,
        commission=5.4,
        slippage=1.5,
        asset_class="fund",
        execution_mode="paper",
        source="paper_execution",
        source_ref="FILL-COMPONENTS-1",
        metadata={
            "strategy_id": "dual_ma",
            "source_signal_id": 1,
            "fee_breakdown": {
                "commission": "5.0",
                "transfer_fee": "0.4",
                "stamp_tax": "2.0",
            },
        },
    )
    db.record_fill_sync(
        fill_id="FILL-MISSING-EVIDENCE",
        order_id="ORD-MISSING-EVIDENCE",
        timestamp="2026-06-18T10:00:00",
        symbol="600000",
        side="buy",
        fill_price=10,
        fill_quantity=10,
        commission=1,
        slippage=0.5,
        asset_class="stock",
        execution_mode="paper",
        source="paper_execution",
        source_ref="FILL-MISSING-EVIDENCE",
        metadata={"strategy_id": "dual_ma"},
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-06-18T10:30:00",
        amount=60,
        symbol="600001",
        direction="buy",
        quantity=20,
        price=3,
        commission=0.2,
        gross_amount=60,
        net_cash_impact=-60.2,
        asset_class="stock",
        note="manual fixture",
        source="manual",
    )
    await db.add_cash_flow(
        timestamp="2026-06-18T08:00:00",
        amount=1000,
        flow_type="deposit",
        note="fixture deposit",
    )
    await db.add_cash_flow(
        timestamp="2026-06-18T08:30:00",
        amount=200,
        flow_type="withdraw",
        note="fixture withdraw",
    )
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="fund",
        price=4.8,
        quote_timestamp="2026-06-18T15:00:00+08:00",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="ok",
        quote_status="confirmed",
    )
    db.upsert_latest_quote_sync(
        symbol="600000",
        asset_type="stock",
        price=11,
        quote_timestamp="2026-06-18T15:00:00+08:00",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="ok",
        quote_status="confirmed",
    )
    db.upsert_latest_quote_sync(
        symbol="600001",
        asset_type="stock",
        price=4,
        quote_timestamp="2026-06-18T15:00:00+08:00",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="ok",
        quote_status="confirmed",
    )

    state = SimpleNamespace(config=SimpleNamespace(strategy="dual_ma"), db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    router = account_strategy_routes.create_router()
    endpoint = _route(router, "/api/account-strategy/contribution", "GET").endpoint

    response = await endpoint()

    assert response.contribution_status == "estimated_from_linked_fills"
    assert response.linked_fill_count == 1
    assert response.gross_unrealized_pnl == 23
    assert response.total_commission == 5.4
    assert response.total_tax == 2
    assert response.total_slippage == 1.5
    assert response.net_contribution == 14.1
    assert response.unattributed_account_pnl == 8.5
    assert response.manual_unattributed_pnl == 19.8
    assert response.cash_flow_pnl == 800
    assert response.evidence_refs == ["fill:FILL-COMPONENTS-1"]
