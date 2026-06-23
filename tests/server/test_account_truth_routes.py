from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

from fastapi.routing import APIRoute

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.db import AppDatabase

BROKER_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,100,10.23,1023.00,5.00,0.00,-1028.00,8972.00,100,10.28,synthetic buy row
synthetic-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,SYN001,合成样例股票A,stock,CNY,0,10.40,0.00,0.00,0.00,0.00,8972.00,100,10.28,synthetic position snapshot
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,8972.00,,,
"""


def _route(router, path: str, method: str = "GET"):
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def _seed_account_truth_db(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = BrokerEvidenceRepository(db._path)
    preview = parse_broker_statement_csv(BROKER_STATEMENT)
    first_run = repository.save_preview(
        preview,
        source_name="synthetic-safe-example.csv",
    )
    duplicate_run = repository.save_preview(
        preview,
        source_name="synthetic-duplicate.csv",
    )
    return db, first_run, duplicate_run


def test_account_truth_import_runs_list_review_metadata(tmp_path, monkeypatch):
    from server.routes import account_truth as account_truth_routes

    db, first_run, duplicate_run = _seed_account_truth_db(tmp_path)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = account_truth_routes.create_router()
    endpoint = _route(router, "/api/account-truth/import-runs").endpoint

    response = asyncio.run(endpoint())

    assert [run["import_run_id"] for run in response] == [
        duplicate_run.import_run_id,
        first_run.import_run_id,
    ]
    assert response[0]["source_type"] == "canonical_broker_statement_csv"
    assert response[0]["source_name"] == "synthetic-duplicate.csv"
    assert response[0]["row_count"] == 3
    assert response[0]["valid_row_count"] == 3
    assert response[0]["invalid_row_count"] == 0
    assert response[0]["row_duplicate_count"] == 0
    assert response[0]["file_duplicate_count"] == 1
    assert response[0]["validation_status"] == "warning"
    assert response[0]["duplicate_of_import_run_id"] == first_run.import_run_id
    assert response[0]["created_at"]
    assert isinstance(response[0]["limitations"], list)


def test_account_truth_reconciliation_reports_list_and_detail(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, first_run, duplicate_run = _seed_account_truth_db(tmp_path)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = account_truth_routes.create_router()
    list_endpoint = _route(
        router,
        "/api/account-truth/reconciliation-reports",
    ).endpoint
    detail_endpoint = _route(
        router,
        "/api/account-truth/reconciliation-reports/{import_run_id}",
    ).endpoint

    reports = asyncio.run(list_endpoint(status="mismatch"))
    detail = asyncio.run(detail_endpoint(import_run_id=first_run.import_run_id))
    duplicate_detail = asyncio.run(
        detail_endpoint(import_run_id=duplicate_run.import_run_id)
    )

    assert [report["import_run_id"] for report in reports] == [first_run.import_run_id]
    assert reports[0]["status"] == "mismatch"
    assert reports[0]["unresolved_count"] > 0
    assert reports[0]["row_count"] == 3
    assert reports[0]["validation_status"] == "pass"

    assert detail["schema_version"] == "karkinos.account_truth.reconciliation.v1"
    assert detail["import_run_id"] == first_run.import_run_id
    assert detail["status"] == "mismatch"
    assert detail["items"]
    position_item = next(
        item
        for item in detail["items"]
        if item["category"] == "position" and item["symbol"] == "SYN001"
    )
    assert position_item["item_key"] == "position:SYN001"
    assert position_item["display_name"] == "合成样例股票A"
    assert position_item["broker_value"] == "100"
    assert position_item["karkinos_value"] == "0"
    assert position_item["difference"] == "100"
    assert position_item["severity"] == "mismatch"
    assert position_item["suggested_review_action"] == "review_position_difference"
    assert position_item["detail_code"] == "account_truth.position_quantity_compared"
    assert position_item["evidence_references"] == [
        f"broker_event:{first_run.import_run_id}:SYN001:position_snapshot",
    ]

    cost_basis_item = next(
        item
        for item in detail["items"]
        if item["category"] == "cost_basis" and item["symbol"] == "SYN001"
    )
    assert cost_basis_item["detail_code"] == "account_truth.cost_basis_compared"
    assert cost_basis_item["display_name"] == "合成样例股票A"
    assert cost_basis_item["detail_context"] == {}

    assert duplicate_detail["status"] == "blocked"
    assert duplicate_detail["items"][0]["suggested_review_action"] == (
        "import_broker_evidence"
    )


def test_account_truth_review_action_records_ledger_candidate_without_mutating_ledger(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, first_run, _duplicate_run = _seed_account_truth_db(tmp_path)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = account_truth_routes.create_router()
    review_endpoint = _route(
        router,
        "/api/account-truth/reconciliation-reports/{import_run_id}/items/{item_key}/review",
        "POST",
    ).endpoint
    detail_endpoint = _route(
        router,
        "/api/account-truth/reconciliation-reports/{import_run_id}",
    ).endpoint
    ledger_count_before = _ledger_entry_count(db._path)

    response = asyncio.run(
        review_endpoint(
            import_run_id=first_run.import_run_id,
            item_key="position:SYN001",
            body=account_truth_routes.ReviewDecisionCreate(
                category="position",
                symbol="SYN001",
                review_status="ledger_candidate",
                note="prepare candidate for later explicit confirmation",
                reviewer="local-reviewer",
            ),
        )
    )
    detail = asyncio.run(detail_endpoint(import_run_id=first_run.import_run_id))

    assert response["import_run_id"] == first_run.import_run_id
    assert response["item_key"] == "position:SYN001"
    assert response["category"] == "position"
    assert response["symbol"] == "SYN001"
    assert response["review_status"] == "ledger_candidate"
    assert response["note"] == "prepare candidate for later explicit confirmation"
    assert response["reviewer"] == "local-reviewer"
    assert response["does_not_mutate_production_ledger"] is True
    assert _ledger_entry_count(db._path) == ledger_count_before

    reviewed_item = next(
        item for item in detail["items"] if item["item_key"] == "position:SYN001"
    )
    assert reviewed_item["latest_review"]["review_status"] == "ledger_candidate"
    assert reviewed_item["latest_review"]["does_not_mutate_production_ledger"] is True


def test_account_truth_score_endpoint_exposes_component_reasons(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, first_run, _duplicate_run = _seed_account_truth_db(tmp_path)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = account_truth_routes.create_router()
    score_endpoint = _route(router, "/api/account-truth/score").endpoint

    score = asyncio.run(score_endpoint())

    assert score["schema_version"] == "karkinos.account_truth.score.v1"
    assert score["import_run_id"] == first_run.import_run_id
    assert score["status"] == "available"
    assert score["gate_status"] == "blocked"
    assert score["score"] < 100
    assert score["cash_status"] == "mismatch"
    assert score["position_status"] == "mismatch"
    assert score["fee_status"] == "mismatch"
    assert score["cost_basis_status"] == "mismatch"
    assert score["data_freshness_status"] == "fresh"
    assert score["unresolved_mismatch_count"] > 0
    assert "review_position_difference" in score["required_actions"]
    assert "unresolved_position_difference" in score["blocking_reasons"]
    assert score["limitations"]


def _ledger_entry_count(db_path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0])
