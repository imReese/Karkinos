from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_COLUMNS,
    CITIC_HISTORY_XLS_SOURCE_TYPE,
)
from account_truth.citic_source_intake import CiticSourceIntakeRepository
from server.config import CiticHistoryXlsDirectoryConfig
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
    assert duplicate_run.import_run_id == first_run.import_run_id
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = account_truth_routes.create_router()
    endpoint = _route(router, "/api/account-truth/import-runs").endpoint

    response = asyncio.run(endpoint())

    assert [run["import_run_id"] for run in response] == [
        duplicate_run.import_run_id,
    ]
    assert response[0]["source_type"] == "canonical_broker_statement_csv"
    assert response[0]["source_name"] == "synthetic-duplicate.csv"
    assert response[0]["row_count"] == 3
    assert response[0]["valid_row_count"] == 3
    assert response[0]["invalid_row_count"] == 0
    assert response[0]["row_duplicate_count"] == 0
    assert response[0]["file_duplicate_count"] == 0
    assert response[0]["validation_status"] == "pass"
    assert response[0]["duplicate_of_import_run_id"] is None
    assert response[0]["created_at"]
    assert isinstance(response[0]["limitations"], list)


def test_account_truth_broker_statement_preview_is_read_only(tmp_path, monkeypatch):
    from server.routes import account_truth as account_truth_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = account_truth_routes.create_router()
    endpoint = _route(
        router, "/api/account-truth/broker-statement/preview", "POST"
    ).endpoint
    ledger_count_before = _ledger_entry_count(db._path)

    response = asyncio.run(
        endpoint(
            body=account_truth_routes.BrokerStatementPreviewCreate(
                content=BROKER_STATEMENT,
                source_name="local-statement.csv",
            )
        )
    )

    assert response["schema_version"] == "karkinos.broker_statement.v2"
    assert response["source_name"] == "local-statement.csv"
    assert response["validation_status"] == "pass"
    assert response["row_count"] == 3
    assert response["valid_row_count"] == 3
    assert response["does_not_mutate_production_ledger"] is True
    assert response["total_event_count"] == 3
    assert response["events_preview"][0]["event_type"] == "trade_buy"
    assert BrokerEvidenceRepository(db._path).list_import_runs(limit=10) == []
    assert _ledger_entry_count(db._path) == ledger_count_before


def test_citic_history_xls_preview_is_private_and_never_persisted(monkeypatch):
    from server.routes import account_truth as account_truth_routes

    private_file_bytes = b"private-account-export"
    parsed_preview = replace(
        parse_broker_statement_csv(BROKER_STATEMENT),
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
        limitations=["settlement components are missing"],
    )
    captured_content: list[bytes] = []

    def parse_preview(content: bytes):
        captured_content.append(content)
        return parsed_preview

    monkeypatch.setattr(account_truth_routes, "parse_citic_history_xls", parse_preview)
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: pytest.fail("read-only CITIC preview must not access app state"),
    )
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/citic-history-xls/preview",
        "POST",
    ).endpoint

    response = asyncio.run(
        endpoint(
            body=account_truth_routes.CiticHistoryXlsPreviewCreate(
                content_base64=base64.b64encode(private_file_bytes).decode("ascii")
            )
        )
    )

    assert captured_content == [private_file_bytes]
    assert response["source_type"] == "citic_history_xls_preview"
    assert response["validation_status"] == "blocked"
    assert response["row_count"] == 3
    assert response["total_event_count"] == 3
    assert response["recognized_non_financial_activity_count"] == 0
    assert response["required_evidence"] == [
        "itemized_settlement_or_cash_flow",
        "current_cash_and_position_snapshot",
    ]
    assert response["source_preview_fingerprint"]
    assert response["recordable_for_follow_up"] is True
    soak_candidate = response["broker_soak_candidate"]
    assert soak_candidate["schema_version"] == (
        "karkinos.account_truth.citic_broker_soak_candidate.v1"
    )
    assert soak_candidate["status"] == "blocked"
    assert soak_candidate["eligible_for_broker_soak"] is False
    assert soak_candidate["connector_registered"] is False
    assert soak_candidate["does_not_record_soak_evidence"] is True
    assert soak_candidate["does_not_submit_broker_order"] is True
    assert soak_candidate["authorizes_execution"] is False
    assert soak_candidate["changes_capital_authority"] is False
    assert response["events_included"] is False
    assert response["evidence_persisted"] is False
    assert response["does_not_mutate_production_ledger"] is True
    assert response["does_not_contact_provider"] is True
    assert response["does_not_enable_broker_submission"] is True
    assert response["does_not_change_capital_authority"] is True
    serialized = json.dumps(response, ensure_ascii=False)
    assert "events_preview" not in response
    assert "source_name" not in response
    assert "SYN001" not in serialized
    assert "合成样例股票A" not in serialized
    assert "private-account-export" not in serialized


def test_citic_history_xls_intake_requires_explicit_review_and_stores_no_events(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    private_file_bytes = b"private-account-export"
    parsed_preview = replace(
        parse_broker_statement_csv(BROKER_STATEMENT),
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
        limitations=["settlement components are missing"],
    )
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr(
        account_truth_routes, "parse_citic_history_xls", lambda _: parsed_preview
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    router = account_truth_routes.create_router()
    record_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/intakes",
        "POST",
    ).endpoint
    list_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/intakes",
    ).endpoint
    ledger_count_before = _ledger_entry_count(db._path)

    response = asyncio.run(
        record_endpoint(
            body=account_truth_routes.CiticHistoryXlsIntakeCreate(
                content_base64=base64.b64encode(private_file_bytes).decode("ascii"),
                expected_file_fingerprint=parsed_preview.file_fingerprint,
                review_status="follow_up_required",
            )
        )
    )
    listed = asyncio.run(list_endpoint(limit=50))

    assert response["review_status"] == "follow_up_required"
    assert response["source_intake_persisted"] is True
    assert response["events_persisted"] is False
    assert response["eligible_for_account_truth"] is False
    assert response["eligible_for_reconciliation"] is False
    assert response["does_not_mutate_production_ledger"] is True
    assert response["does_not_contact_provider"] is True
    assert response["does_not_enable_broker_submission"] is True
    assert response["does_not_change_capital_authority"] is True
    assert listed == [response]
    assert _ledger_entry_count(db._path) == ledger_count_before
    assert BrokerEvidenceRepository(db._path).list_events(response["intake_id"]) == []
    assert len(CiticSourceIntakeRepository(db._path).list_intakes()) == 1
    serialized = json.dumps(response, ensure_ascii=False)
    assert "SYN001" not in serialized
    assert "合成样例股票A" not in serialized
    assert "private-account-export" not in serialized


def test_citic_history_xls_intake_rechecks_previewed_file_identity(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    parsed_preview = replace(
        parse_broker_statement_csv(BROKER_STATEMENT),
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
    )
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr(
        account_truth_routes, "parse_citic_history_xls", lambda _: parsed_preview
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/citic-history-xls/intakes",
        "POST",
    ).endpoint

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                body=account_truth_routes.CiticHistoryXlsIntakeCreate(
                    content_base64=base64.b64encode(b"changed-file").decode("ascii"),
                    expected_file_fingerprint="0" * 64,
                    review_status="follow_up_required",
                )
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "citic_source_file_fingerprint_mismatch"
    assert CiticSourceIntakeRepository(db._path).list_intakes() == []


def test_citic_query_window_review_is_explicit_revocable_and_non_authorizing(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    private_file_bytes = b"private-account-export"
    parsed_preview = replace(
        parse_broker_statement_csv(BROKER_STATEMENT),
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
        limitations=["settlement components are missing"],
    )
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr(
        account_truth_routes, "parse_citic_history_xls", lambda _: parsed_preview
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    router = account_truth_routes.create_router()
    intake_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/intakes",
        "POST",
    ).endpoint
    review_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/query-window-reviews",
        "POST",
    ).endpoint
    revoke_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/query-window-reviews/revoke",
        "POST",
    ).endpoint
    scope_review_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/source-scope-reviews",
        "POST",
    ).endpoint
    scope_revoke_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/source-scope-reviews/revoke",
        "POST",
    ).endpoint
    list_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/intakes",
    ).endpoint
    transport = base64.b64encode(private_file_bytes).decode("ascii")

    intake = asyncio.run(
        intake_endpoint(
            body=account_truth_routes.CiticHistoryXlsIntakeCreate(
                content_base64=transport,
                expected_file_fingerprint=parsed_preview.file_fingerprint,
                review_status="follow_up_required",
            )
        )
    )
    recorded = asyncio.run(
        review_endpoint(
            body=account_truth_routes.CiticHistoryXlsQueryWindowReviewCreate(
                content_base64=transport,
                expected_file_fingerprint=parsed_preview.file_fingerprint,
                expected_source_preview_fingerprint=intake[
                    "source_preview_fingerprint"
                ],
                query_start_date="2026-01-01",
                query_end_date="2026-01-31",
                query_window_attested=True,
            )
        )
    )

    assert recorded["status"] == "recorded"
    assert recorded["query_window_review_write_performed"] is True
    assert recorded["events_persisted"] is False
    assert recorded["does_not_mutate_broker_evidence"] is True
    assert recorded["does_not_mutate_production_ledger"] is True
    assert recorded["does_not_reconcile_account"] is True
    assert recorded["does_not_enable_broker_submission"] is True
    assert recorded["does_not_change_capital_authority"] is True
    assert recorded["review"]["effective_status"] == "active"
    assert recorded["review"]["eligible_for_account_truth"] is False
    assert recorded["review"]["eligible_for_reconciliation"] is False
    scope_recorded = asyncio.run(
        scope_review_endpoint(
            body=account_truth_routes.CiticHistoryXlsSourceScopeReviewCreate(
                intake_id=intake["intake_id"],
                expected_file_fingerprint=parsed_preview.file_fingerprint,
                expected_source_preview_fingerprint=intake[
                    "source_preview_fingerprint"
                ],
                expected_query_window_review_id=recorded["review"]["review_id"],
                expected_query_window_review_fingerprint=recorded["review"][
                    "review_fingerprint"
                ],
                account_alias="citic-primary",
                account_reference_hash="sha256:" + "c" * 64,
                account_type="cash",
                market_scopes=["shanghai_a", "shenzhen_a"],
                asset_classes=["stock"],
                business_types=["history_trades"],
                no_other_filters_attested=True,
                complete_returned_results_attested=True,
                source_scope_attested=True,
            )
        )
    )
    assert scope_recorded["status"] == "recorded"
    assert scope_recorded["source_scope_review_write_performed"] is True
    assert scope_recorded["raw_account_identifier_persisted"] is False
    assert scope_recorded["events_persisted"] is False
    assert scope_recorded["does_not_mutate_query_window_review"] is True
    assert scope_recorded["does_not_mutate_broker_evidence"] is True
    assert scope_recorded["does_not_mutate_production_ledger"] is True
    assert scope_recorded["does_not_enable_broker_submission"] is True
    assert scope_recorded["does_not_change_capital_authority"] is True
    assert scope_recorded["review"]["effective_status"] == "active"
    assert scope_recorded["review"]["complete_returned_results_attested"] is True
    assert scope_recorded["review"]["eligible_for_account_truth"] is False
    listed = asyncio.run(list_endpoint(limit=50))
    assert listed[0]["query_window_review"]["effective_status"] == "active"
    assert listed[0]["source_scope_review"]["effective_status"] == "active"

    scope_revoked = asyncio.run(
        scope_revoke_endpoint(
            body=account_truth_routes.CiticHistoryXlsSourceScopeReviewRevoke(
                intake_id=intake["intake_id"],
                expected_active_review_id=scope_recorded["review"]["review_id"],
                expected_active_review_fingerprint=scope_recorded["review"][
                    "review_fingerprint"
                ],
            )
        )
    )
    assert scope_revoked["status"] == "revoked"
    assert scope_revoked["review"]["effective_status"] == "revoked"

    revoked = asyncio.run(
        revoke_endpoint(
            body=account_truth_routes.CiticHistoryXlsQueryWindowReviewRevoke(
                intake_id=intake["intake_id"],
                expected_active_review_id=recorded["review"]["review_id"],
                expected_active_review_fingerprint=recorded["review"][
                    "review_fingerprint"
                ],
            )
        )
    )

    assert revoked["status"] == "revoked"
    assert revoked["review"]["effective_status"] == "revoked"
    assert (
        asyncio.run(list_endpoint(limit=50))[0]["query_window_review"][
            "effective_status"
        ]
        == "revoked"
    )
    assert BrokerEvidenceRepository(db._path).list_import_runs() == []
    serialized = json.dumps(recorded, ensure_ascii=False)
    assert private_file_bytes.decode("ascii") not in serialized
    assert "SYN001" not in serialized
    assert "合成样例股票A" not in serialized
    serialized_scope = json.dumps(scope_recorded, ensure_ascii=False)
    assert "raw-private-account-identifier" not in serialized_scope


def test_citic_history_xls_intake_list_get_does_not_create_database_or_schema(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db_path = tmp_path / "missing-parent" / "app.db"
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=SimpleNamespace(_path=db_path)),
    )
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/citic-history-xls/intakes",
    ).endpoint

    assert asyncio.run(endpoint(limit=50)) == []
    assert not db_path.parent.exists()


def test_configured_citic_directory_scan_and_review_are_private_and_non_authorizing(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    private_directory = tmp_path / "private-account-exports"
    private_directory.mkdir()
    private_name = "private-history-trades-202601.xls"
    private_content = b"private-account-export-content"
    (private_directory / private_name).write_bytes(private_content)
    base_preview = replace(
        parse_broker_statement_csv(BROKER_STATEMENT),
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
        limitations=["settlement components are missing"],
    )

    def parse_preview(content: bytes):
        return replace(
            base_preview,
            file_fingerprint=hashlib.sha256(content).hexdigest(),
        )

    monkeypatch.setattr(
        "account_truth.citic_history_xls_directory.parse_citic_history_xls",
        parse_preview,
    )
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(
            citic_history_xls_directory=CiticHistoryXlsDirectoryConfig(
                enabled=True,
                path=str(private_directory),
                max_files=24,
                max_file_bytes=1024,
                max_total_bytes=4096,
            )
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    router = account_truth_routes.create_router()
    status_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/directory",
    ).endpoint
    scan_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/directory/scan",
        "POST",
    ).endpoint
    intake_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/directory/intakes",
        "POST",
    ).endpoint
    query_window_endpoint = _route(
        router,
        "/api/account-truth/citic-history-xls/directory/query-window-reviews",
        "POST",
    ).endpoint
    ledger_count_before = _ledger_entry_count(db._path)

    status = asyncio.run(status_endpoint())
    scan = asyncio.run(scan_endpoint())

    assert status["enabled"] is True
    assert status["state"] == "configured"
    assert status["configured_path_included"] is False
    assert status["source_names_included"] is False
    assert scan["state"] == "ready"
    assert scan["candidate_file_count"] == 1
    assert scan["preview_count"] == 1
    assert scan["recognized_event_count"] == 3
    assert scan["source_name_month_hints_included"] is True
    assert scan["source_name_month_hints_are_evidence"] is False
    assert scan["items"][0]["local_name_month_hint"] == "2026-01"
    assert scan["items"][0]["local_name_month_hint_is_evidence"] is False
    assert scan["items"][0]["query_window_inferred"] is False
    assert scan["query_window_review_summary"] == {
        "reviewed_source_count": 0,
        "unreviewed_source_count": 1,
        "all_current_sources_reviewed": False,
        "complete_coverage_proven": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
    }
    query_window_batch = scan["query_window_batch_assessment"]
    assert query_window_batch["status"] == "blocked"
    assert query_window_batch["integrity_status"] == "not_available"
    assert query_window_batch["source_count"] == 1
    assert query_window_batch["reviewed_source_count"] == 0
    assert query_window_batch["unreviewed_source_count"] == 1
    assert query_window_batch["declared_window_start_date"] is None
    assert query_window_batch["declared_window_end_date"] is None
    assert query_window_batch["complete_account_coverage_proven"] is False
    assert query_window_batch["events_included"] is False
    assert query_window_batch["source_names_included"] is False
    assert query_window_batch["paths_included"] is False
    assert query_window_batch["assessment_persisted"] is False
    assert query_window_batch["database_writes_performed"] is False
    assert query_window_batch["provider_contacted"] is False
    assert query_window_batch["eligible_for_account_truth"] is False
    assert query_window_batch["eligible_for_reconciliation"] is False
    assert query_window_batch["authorizes_execution"] is False
    assert query_window_batch["changes_capital_authority"] is False
    batch_assessment = scan["batch_assessment"]
    assert batch_assessment["status"] == "blocked"
    assert batch_assessment["integrity_status"] == "clear"
    assert batch_assessment["source_count"] == 1
    assert batch_assessment["observed_event_count"] == 3
    assert batch_assessment["unique_event_count"] == 3
    assert batch_assessment["cross_file_duplicate_event_count"] == 0
    assert batch_assessment["conflicting_event_identity_count"] == 0
    assert batch_assessment["observed_event_months"]
    assert batch_assessment["query_windows_reviewed"] is False
    assert batch_assessment["complete_coverage_proven"] is False
    assert batch_assessment["events_included"] is False
    assert batch_assessment["private_fields_included"] is False
    assert batch_assessment["source_names_included"] is False
    assert batch_assessment["paths_included"] is False
    assert batch_assessment["evidence_persisted"] is False
    assert batch_assessment["eligible_for_account_truth"] is False
    assert batch_assessment["eligible_for_reconciliation"] is False
    lineage = scan["canonical_lineage_assessment"]
    assert lineage["status"] == "blocked"
    assert lineage["event_lineage_status"] == "not_available"
    assert lineage["source_supported_event_count"] == 1
    assert lineage["canonical_supported_event_count"] == 0
    assert lineage["source_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 1}
    ]
    assert lineage["canonical_event_type_counts"] == []
    assert lineage["semantically_matched_event_type_counts"] == []
    assert lineage["source_unmatched_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 1}
    ]
    assert lineage["canonical_unmatched_event_type_counts"] == []
    assert lineage["canonical_events_with_broker_order_identity_count"] == 0
    assert lineage["canonical_import_reference"] is None
    assert "citic_canonical_lineage_canonical_import_missing" in lineage["blockers"]
    assert lineage["events_included"] is False
    assert lineage["transaction_details_included"] is False
    assert lineage["source_names_included"] is False
    assert lineage["paths_included"] is False
    assert lineage["assessment_persisted"] is False
    assert lineage["database_writes_performed"] is False
    assert lineage["authorizes_execution"] is False
    assert (
        scan["items"][0]["broker_soak_candidate"]["eligible_for_broker_soak"] is False
    )
    assert (
        scan["items"][0]["broker_soak_candidate"]["does_not_register_connector"] is True
    )
    assert scan["scan_persisted"] is False
    assert scan["events_persisted"] is False
    assert scan["eligible_for_account_truth"] is False
    assert scan["eligible_for_reconciliation"] is False
    assert CiticSourceIntakeRepository(db._path).list_intakes() == []
    assert BrokerEvidenceRepository(db._path).list_import_runs() == []
    serialized_scan = json.dumps(scan, ensure_ascii=False)
    assert private_name not in serialized_scan
    assert str(private_directory) not in serialized_scan
    assert private_content.decode("ascii") not in serialized_scan
    assert "SYN001" not in serialized_scan
    assert "合成样例股票A" not in serialized_scan

    intake = asyncio.run(
        intake_endpoint(
            body=account_truth_routes.CiticHistoryXlsDirectoryIntakeCreate(
                expected_file_fingerprint=scan["items"][0]["file_fingerprint"],
                review_status="follow_up_required",
            )
        )
    )

    assert intake["review_status"] == "follow_up_required"
    assert intake["events_persisted"] is False
    assert intake["eligible_for_account_truth"] is False
    assert intake["eligible_for_reconciliation"] is False
    query_window_review = asyncio.run(
        query_window_endpoint(
            body=(
                account_truth_routes.CiticHistoryXlsDirectoryQueryWindowReviewCreate(
                    expected_file_fingerprint=scan["items"][0]["file_fingerprint"],
                    expected_source_preview_fingerprint=scan["items"][0][
                        "source_preview_fingerprint"
                    ],
                    query_start_date="2026-01-01",
                    query_end_date="2026-01-31",
                    query_window_attested=True,
                )
            )
        )
    )
    reviewed_scan = asyncio.run(scan_endpoint())

    assert query_window_review["status"] == "recorded"
    assert reviewed_scan["query_window_review_summary"]["reviewed_source_count"] == 1
    assert reviewed_scan["query_window_review_summary"]["unreviewed_source_count"] == 0
    assert (
        reviewed_scan["query_window_review_summary"]["all_current_sources_reviewed"]
        is True
    )
    assert (
        reviewed_scan["query_window_review_summary"]["complete_coverage_proven"]
        is False
    )
    reviewed_query_window_batch = reviewed_scan["query_window_batch_assessment"]
    assert reviewed_query_window_batch["integrity_status"] == "clear"
    assert reviewed_query_window_batch["reviewed_source_count"] == 1
    assert reviewed_query_window_batch["unreviewed_source_count"] == 0
    assert reviewed_query_window_batch["all_current_sources_reviewed"] is True
    assert reviewed_query_window_batch["declared_window_start_date"] == "2026-01-01"
    assert reviewed_query_window_batch["declared_window_end_date"] == "2026-01-31"
    assert reviewed_query_window_batch["gap_calendar_day_count"] == 0
    assert reviewed_query_window_batch["overlap_calendar_day_count"] == 0
    assert reviewed_query_window_batch["complete_account_coverage_proven"] is False
    assert reviewed_query_window_batch["eligible_for_account_truth"] is False
    assert reviewed_query_window_batch["authorizes_execution"] is False
    assert (
        reviewed_scan["items"][0]["source_intake"]["query_window_review"][
            "effective_status"
        ]
        == "active"
    )
    assert len(CiticSourceIntakeRepository(db._path).list_intakes()) == 1
    assert BrokerEvidenceRepository(db._path).list_import_runs() == []
    assert _ledger_entry_count(db._path) == ledger_count_before


def test_configured_citic_directory_review_rejects_source_drift(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    private_directory = tmp_path / "exports"
    private_directory.mkdir()
    source = private_directory / "private.xls"
    source.write_bytes(b"original")
    base_preview = replace(
        parse_broker_statement_csv(BROKER_STATEMENT),
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
    )
    monkeypatch.setattr(
        "account_truth.citic_history_xls_directory.parse_citic_history_xls",
        lambda content: replace(
            base_preview,
            file_fingerprint=hashlib.sha256(content).hexdigest(),
        ),
    )
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    config = CiticHistoryXlsDirectoryConfig(
        enabled=True,
        path=str(private_directory),
        max_files=24,
        max_file_bytes=1024,
        max_total_bytes=4096,
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(
            db=db, config=SimpleNamespace(citic_history_xls_directory=config)
        ),
    )
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/citic-history-xls/directory/intakes",
        "POST",
    ).endpoint
    original_fingerprint = hashlib.sha256(b"original").hexdigest()
    source.write_bytes(b"changed")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                body=account_truth_routes.CiticHistoryXlsDirectoryIntakeCreate(
                    expected_file_fingerprint=original_fingerprint,
                    review_status="follow_up_required",
                )
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == (
        "citic_history_xls_directory_fingerprint_not_found"
    )
    assert CiticSourceIntakeRepository(db._path).list_intakes() == []


def test_citic_history_xls_preview_rejects_invalid_base64():
    from server.routes import account_truth as account_truth_routes

    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/citic-history-xls/preview",
        "POST",
    ).endpoint

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                body=account_truth_routes.CiticHistoryXlsPreviewCreate(
                    content_base64="not-base64"
                )
            )
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "citic_history_xls_invalid_transport"


@pytest.mark.parametrize(
    ("content_base64", "status_code", "error_code"),
    [
        ("", 422, "citic_history_xls_empty_transport"),
        (
            "A" * (10 * 1024 * 1024 * 4 // 3 + 5),
            413,
            "citic_history_xls_transport_too_large",
        ),
    ],
)
def test_citic_history_xls_preview_rejects_unsafe_transport_without_echo(
    content_base64,
    status_code,
    error_code,
):
    from server.routes import account_truth as account_truth_routes

    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/citic-history-xls/preview",
        "POST",
    ).endpoint

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                body=account_truth_routes.CiticHistoryXlsPreviewCreate(
                    content_base64=content_base64
                )
            )
        )

    assert exc_info.value.status_code == status_code
    assert exc_info.value.detail["code"] == error_code
    if content_base64:
        assert content_base64 not in json.dumps(exc_info.value.detail)


def test_account_truth_collector_status_is_read_only(tmp_path, monkeypatch):
    from server.routes import account_truth as account_truth_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    payload = {
        "schema_version": (
            "karkinos.account_truth.local_broker_statement_collector.v1"
        ),
        "enabled": True,
        "state": "imported",
        "configured_path": "broker_statement.csv",
        "source_name": "broker_statement.csv",
        "file_present": True,
        "import_run_id": "import-local-1",
        "does_not_mutate_production_ledger": True,
        "does_not_contact_provider": True,
        "does_not_change_execution_authority": True,
    }
    status = SimpleNamespace(to_dict=lambda: dict(payload))
    collector = SimpleNamespace(status=lambda: status)
    fake_state = SimpleNamespace(db=db, broker_statement_collector=collector)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/broker-statement/collector",
    ).endpoint
    ledger_count_before = _ledger_entry_count(db._path)

    response = asyncio.run(endpoint())

    assert response == payload
    assert _ledger_entry_count(db._path) == ledger_count_before


def test_account_truth_broker_statement_import_stages_evidence_only(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = account_truth_routes.create_router()
    endpoint = _route(
        router, "/api/account-truth/broker-statement/import", "POST"
    ).endpoint
    ledger_count_before = _ledger_entry_count(db._path)

    response = asyncio.run(
        endpoint(
            body=account_truth_routes.BrokerStatementPreviewCreate(
                content=BROKER_STATEMENT,
                source_name="local-statement.csv",
            )
        )
    )
    import_run = response["import_run"]

    assert import_run["source_name"] == "local-statement.csv"
    assert import_run["row_count"] == 3
    assert response["does_not_mutate_production_ledger"] is True
    assert response["report"]["import_run_id"] == import_run["import_run_id"]
    assert response["report"]["status"] == "mismatch"
    assert _ledger_entry_count(db._path) == ledger_count_before

    repository = BrokerEvidenceRepository(db._path)
    assert len(repository.list_events(import_run["import_run_id"])) == 3


def test_account_truth_reconciliation_reports_list_and_detail(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, first_run, duplicate_run = _seed_account_truth_db(tmp_path)
    assert duplicate_run.import_run_id == first_run.import_run_id
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
    detail = asyncio.run(detail_endpoint(import_run_id=duplicate_run.import_run_id))

    assert [report["import_run_id"] for report in reports] == [
        duplicate_run.import_run_id
    ]
    assert reports[0]["status"] == "mismatch"
    assert reports[0]["unresolved_count"] > 0
    assert reports[0]["row_count"] == 3
    assert reports[0]["validation_status"] == "pass"
    assert reports[0]["source_name"] == "synthetic-duplicate.csv"

    assert detail["schema_version"] == "karkinos.account_truth.reconciliation.v1"
    assert detail["import_run_id"] == duplicate_run.import_run_id
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
    assert cost_basis_item["detail_context"] == {
        "broker_cost_basis_method": "unspecified",
        "karkinos_cost_basis_method": "moving_average_buy_cost",
        "comparison_unit": "per_share_cost_basis",
        "comparison_precision": "decimal_string_no_rounding",
        "precision_limitation": (
            "broker_display_precision_fee_allocation_tax_timing_transfer_fee_rounding"
        ),
    }


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
    assert response["evidence_fingerprint"]
    assert response["does_not_mutate_production_ledger"] is True
    assert _ledger_entry_count(db._path) == ledger_count_before

    reviewed_item = next(
        item for item in detail["items"] if item["item_key"] == "position:SYN001"
    )
    assert reviewed_item["latest_review"]["review_status"] == "ledger_candidate"
    assert reviewed_item["latest_review"]["is_current"] is True
    assert reviewed_item["latest_review"]["does_not_mutate_production_ledger"] is True

    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-01-16T09:35:00+08:00",
        symbol="SYN001",
        direction="buy",
        quantity=10,
        price=10.0,
        gross_amount=100.0,
        net_cash_impact=-100.0,
        created_at="2099-01-01T00:00:00+08:00",
    )
    changed_detail = asyncio.run(detail_endpoint(import_run_id=first_run.import_run_id))
    changed_item = next(
        item
        for item in changed_detail["items"]
        if item["item_key"] == "position:SYN001"
    )
    assert changed_item["latest_review"]["is_current"] is False
    assert (
        changed_item["latest_review"]["evidence_fingerprint"]
        != changed_item["evidence_fingerprint"]
    )


def test_account_truth_score_endpoint_exposes_component_reasons(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, _first_run, duplicate_run = _seed_account_truth_db(tmp_path)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = account_truth_routes.create_router()
    score_endpoint = _route(router, "/api/account-truth/score").endpoint

    score = asyncio.run(score_endpoint())

    assert score["schema_version"] == "karkinos.account_truth.score.v1"
    assert score["import_run_id"] == duplicate_run.import_run_id
    assert score["source_name"] == "synthetic-duplicate.csv"
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


def test_account_truth_evidence_readiness_projects_canonical_blockers(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, _first_run, duplicate_run = _seed_account_truth_db(tmp_path)
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/evidence-readiness",
    ).endpoint
    ledger_count_before = _ledger_entry_count(db._path)

    readiness = asyncio.run(endpoint())

    assert readiness["schema_version"] == (
        "karkinos.account_truth.evidence_readiness.v2"
    )
    assert readiness["status"] == "blocked"
    assert readiness["account_truth_import_run_id"] == duplicate_run.import_run_id
    assert readiness["account_truth_gate_status"] == "blocked"
    requirements = {item["requirement"]: item["status"] for item in readiness["items"]}
    assert requirements["canonical_broker_evidence"] == "pass"
    assert requirements["reviewed_account_and_period_scope"] == "blocked"
    assert requirements["current_cash_snapshot"] == "mismatch"
    assert requirements["current_position_snapshot"] == "mismatch"
    assert requirements["known_incomplete_source_reviews"] == "pass"
    assert readiness["persisted_facts_only"] is True
    assert readiness["provider_contacted"] is False
    assert readiness["database_writes_performed"] is False
    assert readiness["authorizes_execution"] is False
    assert readiness["changes_capital_authority"] is False
    scope = readiness["evidence_scope"]
    assert scope["schema_version"] == "karkinos.account_truth.evidence_scope.v1"
    assert scope["status"] == "blocked"
    assert scope["account_binding"]["status"] == "missing"
    assert scope["declared_coverage_window"]["status"] == "missing"
    assert scope["observed_event_window"]["status"] == "available"
    assert scope["observed_event_window"]["occurred_start_date"] == "2026-01-05"
    assert scope["observed_event_window"]["occurred_end_date"] == "2026-01-15"
    assert scope["asset_scope"]["observed_asset_classes"] == ["stock"]
    assert scope["snapshot_evidence"]["latest_cash_snapshot_date"] == "2026-01-15"
    assert scope["database_writes_performed"] is False
    assert scope["authorizes_execution"] is False
    assert _ledger_entry_count(db._path) == ledger_count_before


def test_account_truth_scope_review_is_exact_append_only_and_revocable(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, _first_run, import_run = _seed_account_truth_db(tmp_path)
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    router = account_truth_routes.create_router()
    readiness_endpoint = _route(
        router,
        "/api/account-truth/evidence-readiness",
    ).endpoint
    review_endpoint = _route(
        router,
        "/api/account-truth/evidence-scope/reviews",
        "POST",
    ).endpoint
    revoke_endpoint = _route(
        router,
        "/api/account-truth/evidence-scope/reviews/revoke",
        "POST",
    ).endpoint
    before = asyncio.run(readiness_endpoint())
    observed_fingerprint = before["evidence_scope"]["observed_scope_fingerprint"]
    ledger_count_before = _ledger_entry_count(db._path)

    recorded = asyncio.run(
        review_endpoint(
            body=account_truth_routes.EvidenceScopeReviewCreate(
                import_run_id=import_run.import_run_id,
                expected_observed_scope_fingerprint=observed_fingerprint,
                provider="citic",
                account_alias="中信证券主账户",
                account_reference_hash="sha256:" + "c" * 64,
                coverage_start_date="2026-01-01",
                coverage_end_date="2026-01-31",
                asset_classes=["stock"],
                full_account_scope_attested=True,
            )
        )
    )

    assert recorded["schema_version"] == (
        "karkinos.account_truth.evidence_scope_review_command.v1"
    )
    assert recorded["status"] == "recorded"
    assert recorded["scope_review_write_performed"] is True
    assert recorded["writes_only_scope_review_store"] is True
    assert recorded["does_not_mutate_production_ledger"] is True
    assert recorded["provider_contacted"] is False
    assert recorded["authorizes_execution"] is False
    scope = recorded["readiness"]["evidence_scope"]
    assert scope["status"] == "complete"
    assert scope["account_binding"] == {
        "status": "bound",
        "provider": "citic",
        "account_alias": "中信证券主账户",
        "account_reference_hash": "sha256:" + "c" * 64,
    }
    assert scope["declared_coverage_window"] == {
        "status": "complete",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
    }
    assert scope["asset_scope"]["status"] == "complete"
    assert scope["database_writes_performed"] is False
    assert scope["authorizes_execution"] is False

    revoked = asyncio.run(
        revoke_endpoint(
            body=account_truth_routes.EvidenceScopeReviewRevoke(
                import_run_id=import_run.import_run_id,
                expected_observed_scope_fingerprint=observed_fingerprint,
            )
        )
    )
    assert revoked["status"] == "revoked"
    assert revoked["readiness"]["evidence_scope"]["status"] == "blocked"
    assert "account_truth_evidence_scope_review_revoked" in (
        revoked["readiness"]["evidence_scope"]["blockers"]
    )
    assert _ledger_entry_count(db._path) == ledger_count_before
    with sqlite3.connect(db._path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM account_truth_evidence_scope_reviews"
            ).fetchone()[0]
            == 2
        )


def test_account_truth_scope_review_rejects_stale_observed_fingerprint(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, _first_run, import_run = _seed_account_truth_db(tmp_path)
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/evidence-scope/reviews",
        "POST",
    ).endpoint

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                body=account_truth_routes.EvidenceScopeReviewCreate(
                    import_run_id=import_run.import_run_id,
                    expected_observed_scope_fingerprint="sha256:" + "0" * 64,
                    provider="citic",
                    account_alias="primary",
                    account_reference_hash="sha256:" + "c" * 64,
                    coverage_start_date="2026-01-01",
                    coverage_end_date="2026-01-31",
                    asset_classes=["stock"],
                    full_account_scope_attested=True,
                )
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == (
        "account_truth_evidence_scope_review_fingerprint_mismatch"
    )
    with sqlite3.connect(db._path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE name = 'account_truth_evidence_scope_reviews'"
            ).fetchone()[0]
            == 0
        )


def test_account_truth_scope_review_cannot_override_evidence_integrity_blocker(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, _first_run, import_run = _seed_account_truth_db(tmp_path)
    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE broker_import_runs SET valid_row_count = valid_row_count + 1 "
            "WHERE import_run_id = ?",
            (import_run.import_run_id,),
        )
        conn.commit()
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    router = account_truth_routes.create_router()
    readiness = asyncio.run(
        _route(router, "/api/account-truth/evidence-readiness").endpoint()
    )
    observed_scope = readiness["evidence_scope"]
    endpoint = _route(
        router,
        "/api/account-truth/evidence-scope/reviews",
        "POST",
    ).endpoint

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                body=account_truth_routes.EvidenceScopeReviewCreate(
                    import_run_id=import_run.import_run_id,
                    expected_observed_scope_fingerprint=observed_scope[
                        "observed_scope_fingerprint"
                    ],
                    provider="citic",
                    account_alias="primary",
                    account_reference_hash="sha256:" + "c" * 64,
                    coverage_start_date="2026-01-01",
                    coverage_end_date="2026-01-31",
                    asset_classes=["stock"],
                    full_account_scope_attested=True,
                )
            )
        )

    assert (
        "account_truth_evidence_scope_event_count_mismatch"
        in observed_scope["blockers"]
    )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == (
        "account_truth_evidence_scope_review_evidence_integrity_blocked"
    )
    with sqlite3.connect(db._path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE name = 'account_truth_evidence_scope_reviews'"
            ).fetchone()[0]
            == 0
        )


def test_account_truth_score_blocks_when_broker_import_predates_ledger(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, _first_run, _duplicate_run = _seed_account_truth_db(tmp_path)
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-01-16T09:00:00+08:00",
        amount=100.0,
        created_at="2099-01-01T00:00:00+08:00",
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    score_endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/score",
    ).endpoint

    score = asyncio.run(score_endpoint())

    assert score["gate_status"] == "blocked"
    assert score["data_freshness_status"] == "stale"
    assert score["ledger_coverage"]["status"] == "stale"
    assert "account_truth_evidence_predates_latest_ledger" in score["blocking_reasons"]
    assert (
        "reimport_broker_statement_after_latest_ledger_fact"
        in score["required_actions"]
    )


def test_account_truth_get_routes_do_not_initialize_missing_database(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db_path = tmp_path / "missing" / "app.db"
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=SimpleNamespace(_path=db_path)),
    )
    router = account_truth_routes.create_router()

    import_runs = asyncio.run(
        _route(router, "/api/account-truth/import-runs").endpoint(limit=50)
    )
    reports = asyncio.run(
        _route(router, "/api/account-truth/reconciliation-reports").endpoint(
            status=None,
            limit=50,
        )
    )
    score = asyncio.run(_route(router, "/api/account-truth/score").endpoint())
    readiness = asyncio.run(
        _route(router, "/api/account-truth/evidence-readiness").endpoint()
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            _route(
                router,
                "/api/account-truth/reconciliation-reports/{import_run_id}",
            ).endpoint(import_run_id="missing")
        )

    assert import_runs == []
    assert reports == []
    assert score["status"] == "missing"
    assert score["gate_status"] == "blocked"
    assert readiness["status"] == "blocked"
    assert readiness["database_writes_performed"] is False
    assert exc_info.value.status_code == 404
    assert not db_path.parent.exists()


def test_account_truth_get_route_rejects_partial_broker_schema_without_repair(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE broker_import_runs (id INTEGER PRIMARY KEY)")
        conn.commit()
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=SimpleNamespace(_path=db_path)),
    )
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/import-runs",
    ).endpoint

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(endpoint(limit=50))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "code": "broker_evidence_schema_incomplete",
        "message": "Persisted Account Truth evidence is unavailable.",
    }
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "broker_evidence_events" not in tables


def test_account_truth_detail_rejects_partial_review_schema_without_repair(
    tmp_path,
    monkeypatch,
):
    from server.routes import account_truth as account_truth_routes

    db, first_run, _duplicate_run = _seed_account_truth_db(tmp_path)
    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "CREATE TABLE reconciliation_review_decisions (id INTEGER PRIMARY KEY)"
        )
        conn.commit()
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    endpoint = _route(
        account_truth_routes.create_router(),
        "/api/account-truth/reconciliation-reports/{import_run_id}",
    ).endpoint

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(endpoint(import_run_id=first_run.import_run_id))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "code": "manual_review_schema_incomplete",
        "message": "Persisted Account Truth evidence is unavailable.",
    }
    with sqlite3.connect(db._path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "reconciliation_review_history" not in tables


def _ledger_entry_count(db_path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0])
