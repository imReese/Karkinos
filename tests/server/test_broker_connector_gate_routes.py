from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

from fastapi.routing import APIRoute

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    BrokerFillFact,
    BrokerPositionFact,
)
from account_truth.broker_connector_evidence import (
    BROKER_CONNECTOR_SOURCE_TYPE,
    build_broker_connector_evidence_preview,
)
from account_truth.broker_evidence import BrokerEvidenceRepository
from analytics.benchmark_fixtures import build_benchmark_fixture_backtest_rows
from server.db import AppDatabase
from tests.analytics.test_strategy_validation_matrix import REQUIRED_STRATEGY_IDS


def test_decision_today_blocks_from_unresolved_connector_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    from server.routes import decision as decision_routes

    db = _db_with_unresolved_connector_evidence(tmp_path)

    def get_action_tasks_sync(statuses=None, limit=50, offset=0):
        return [
            {
                "id": 9,
                "source_signal_id": 1,
                "symbol": "SYN001",
                "direction": "buy",
                "strategy_id": "dual_ma",
                "asset_class": "stock",
                "risk_gate_status": "passed",
                "risk_gate_passed": True,
                "manual_confirmation_required": True,
                "manual_confirmation_status": "ready_for_manual_confirmation",
            }
        ]

    db.get_action_tasks_sync = get_action_tasks_sync
    db.list_signal_journal_sync = lambda limit=50, offset=0: []
    db.get_latest_quote_sync = lambda symbol, asset_type=None: {
        "symbol": symbol,
        "asset_type": asset_type or "stock",
        "price": 10.40,
        "quote_status": "live",
        "quote_timestamp": "2026-06-22T15:05:00+08:00",
        "quote_source": "synthetic-fixture",
    }
    db.get_backtest_results = _empty_backtest_results

    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db, config=SimpleNamespace(initial_cash=0)),
    )

    router = decision_routes.create_router()
    endpoint = _route(router, "/api/decision/today").endpoint

    response = asyncio.run(endpoint())

    assert response["decision"] == "review_required"
    account_truth = response["summary"]["account_truth"]
    assert account_truth["status"] == "available"
    assert account_truth["source_type"] == BROKER_CONNECTOR_SOURCE_TYPE
    assert account_truth["gate_status"] == "blocked"
    assert account_truth["has_evidence"] is True
    assert account_truth["unresolved_mismatch_count"] > 0
    assert "unresolved_cash_difference" in account_truth["blocking_reasons"]
    candidate = response["candidates"][0]
    assert candidate["manual_confirmation_status"] == "blocked_by_account_truth"
    assert candidate["evidence"]["account_truth"]["source_type"] == (
        BROKER_CONNECTOR_SOURCE_TYPE
    )


def test_backtest_promotion_readiness_blocks_from_unresolved_connector_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    from server.routes import backtest as backtest_routes

    db = _db_with_unresolved_connector_evidence(tmp_path)
    db.get_backtest_results = _benchmark_backtest_results
    db.get_risk_decisions_sync = lambda limit=500, offset=0: [
        {
            "decision_id": f"RISK-{strategy_id}",
            "passed": 0,
            "payload_json": json.dumps(
                {
                    "intent": {"strategy_id": strategy_id},
                    "decision": {"passed": False, "reasons": ["synthetic fixture"]},
                }
            ),
        }
        for strategy_id in sorted(REQUIRED_STRATEGY_IDS)
    ]
    db.list_orders_sync = lambda limit=500, offset=0: [
        {
            "order_id": f"SHADOW-{strategy_id}",
            "execution_mode": "paper_shadow",
            "status": "shadow_recorded",
            "payload_json": json.dumps(
                {
                    "strategy_id": strategy_id,
                    "divergence_status": "within_expectations",
                }
            ),
        }
        for strategy_id in sorted(REQUIRED_STRATEGY_IDS)
    ]

    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db, config=SimpleNamespace(initial_cash=0)),
    )

    router = backtest_routes.create_router()
    endpoint = _route(
        router,
        "/api/backtest/strategy-promotion-readiness",
    ).endpoint

    response = asyncio.run(endpoint())

    assert response.required_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert response.promotable_strategy_count == 0
    assert response.is_complete is False
    assert all(row.account_truth_gate_status == "blocked" for row in response.rows)
    assert all(row.account_truth_score is not None for row in response.rows)
    assert all(
        row.missing_requirements == ["account_truth_gate_pass"] for row in response.rows
    )


def _db_with_unresolved_connector_evidence(tmp_path) -> AppDatabase:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = BrokerEvidenceRepository(db._path)
    preview = build_broker_connector_evidence_preview(_connector_snapshot())
    repository.save_preview(preview, source_name="synthetic readonly connector")
    return db


def _connector_snapshot() -> BrokerConnectorSnapshot:
    return BrokerConnectorSnapshot(
        connector_id="fake_qmt_readonly",
        source_name="synthetic deterministic readonly fixture",
        account_id="synthetic-account",
        account_alias="safe-local-alias",
        captured_at="2026-06-22T15:05:00+08:00",
        health=BrokerConnectorHealth(
            status="healthy",
            checked_at="2026-06-22T15:05:00+08:00",
            message="synthetic connector is healthy",
        ),
        cash=BrokerCashFact(
            currency="CNY",
            balance=Decimal("8972.00"),
            available=Decimal("8800.00"),
        ),
        positions=[
            BrokerPositionFact(
                symbol="SYN001",
                instrument_name="合成样例股票A",
                asset_class="stock",
                quantity=Decimal("100"),
                available_quantity=Decimal("0"),
                cost_basis=Decimal("10.28"),
                market_price=Decimal("10.40"),
            )
        ],
        fills=[
            BrokerFillFact(
                fill_id="synthetic-fill-001",
                order_id="synthetic-order-001",
                symbol="SYN001",
                side="buy",
                quantity=Decimal("100"),
                price=Decimal("10.23"),
                fee=Decimal("5.00"),
                tax=Decimal("0.00"),
                net_amount=Decimal("-1028.00"),
                filled_at="2026-06-22T10:05:05+08:00",
            )
        ],
    )


async def _empty_backtest_results() -> list[dict[str, object]]:
    return []


async def _benchmark_backtest_results() -> list[dict[str, object]]:
    return build_benchmark_fixture_backtest_rows()


def _route(router, path: str, method: str = "GET"):
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )
