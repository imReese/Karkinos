from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from account_truth.broker_statement import (
    BrokerStatementValidationError,
    parse_broker_statement_csv,
)
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_COLUMNS,
    CITIC_HISTORY_XLS_SOURCE_TYPE,
)
from account_truth.citic_source_intake import (
    CiticSourceIntakeRepository,
    citic_source_preview_fingerprint,
)
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReviewRepository,
)
from account_truth.citic_source_scope_review import CiticSourceScopeReviewRepository
from server.services.citic_source_follow_up import build_citic_source_follow_up

_PRIVATE_SOURCE = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method,broker_order_id,client_order_id
private-buy,trade_buy,2026-05-05T09:35:00+08:00,2026-05-06,PRIVATE-SYMBOL,PRIVATE-NAME,stock,CNY,100,10,1000,0,0,-1005,,,,PRIVATE-NOTE,0,,PRIVATE-ORDER,
"""


def _preview():
    return replace(
        parse_broker_statement_csv(_PRIVATE_SOURCE),
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
        limitations=["Itemized settlement components are absent."],
        errors=[
            BrokerStatementValidationError(
                row_number=None,
                code="citic_history_xls_settlement_components_missing",
                message="Itemized settlement components are missing.",
            )
        ],
    )


def _preview_at(
    *,
    file_fingerprint: str,
    event_id: str,
    occurred_at: str,
    settled_at: str,
):
    preview = _preview()
    event = replace(
        preview.events[0],
        event_id=event_id,
        occurred_at=occurred_at,
        settled_at=settled_at,
    )
    return replace(
        preview,
        file_fingerprint=file_fingerprint,
        events=[event],
    )


def test_citic_source_follow_up_missing_store_is_zero_write(tmp_path: Path) -> None:
    db_path = tmp_path / "missing-parent" / "app.db"

    projection = build_citic_source_follow_up(db_path)

    assert projection["status"] == "no_follow_up_required"
    assert projection["subsystem_status"] == "skipped"
    assert projection["pending_source_count"] == 0
    assert projection["database_writes_performed"] is False
    assert not db_path.parent.exists()


def test_citic_source_follow_up_projects_only_sanitized_persisted_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    before = db_path.stat()

    first = build_citic_source_follow_up(db_path)
    replay = build_citic_source_follow_up(db_path)

    assert first == replay
    assert first["status"] == "follow_up_required"
    assert first["subsystem_status"] == "manual_action_required"
    assert first["pending_source_count"] == 1
    assert first["required_evidence"] == [
        "current_cash_and_position_snapshot",
        "itemized_settlement_or_cash_flow",
        "reviewed_query_window_for_source",
        "reviewed_source_scope_for_source",
        "consistent_reviewed_source_scope_for_each_source",
    ]
    assert first["reviewed_query_window_source_count"] == 0
    assert first["unreviewed_query_window_source_count"] == 1
    assert first["query_window_reviews_complete"] is False
    assert first["source_scope_reviews_complete"] is False
    assert first["next_manual_action"] == "review_citic_source_query_windows"
    assert first["error_codes"] == ["citic_history_xls_settlement_components_missing"]
    assert str(first["evidence_fingerprint"]).startswith("sha256:")
    assert first["persisted_facts_only"] is True
    assert first["eligible_for_account_truth"] is False
    assert first["eligible_for_reconciliation"] is False
    assert first["authorizes_execution"] is False
    assert first["changes_capital_authority"] is False
    serialized = json.dumps(first, ensure_ascii=False)
    for private_value in (
        "PRIVATE-SYMBOL",
        "PRIVATE-NAME",
        "PRIVATE-NOTE",
        "PRIVATE-ORDER",
        str(db_path),
    ):
        assert private_value not in serialized
    after = db_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_citic_source_follow_up_resolves_only_the_reviewed_query_window_subgap(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    intake = CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    repository = CiticSourceQueryWindowReviewRepository(db_path)
    accepted = repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        expected_source_preview_fingerprint=citic_source_preview_fingerprint(preview),
        query_start_date="2026-05-01",
        query_end_date="2026-05-31",
        query_window_attested=True,
    )

    reviewed = build_citic_source_follow_up(db_path)

    assert reviewed["status"] == "follow_up_required"
    assert reviewed["reviewed_query_window_source_count"] == 1
    assert reviewed["unreviewed_query_window_source_count"] == 0
    assert reviewed["query_window_reviews_complete"] is True
    assert "reviewed_query_window_for_source" not in reviewed["required_evidence"]
    assert reviewed["required_evidence"] == [
        "current_cash_and_position_snapshot",
        "itemized_settlement_or_cash_flow",
        "reviewed_source_scope_for_source",
        "consistent_reviewed_source_scope_for_each_source",
    ]
    assert reviewed["reviewed_source_scope_source_count"] == 0
    assert reviewed["unreviewed_source_scope_source_count"] == 1
    assert reviewed["source_scope_reviews_complete"] is False
    assert reviewed["next_manual_action"] == "review_citic_source_scopes"
    assert reviewed["eligible_for_account_truth"] is False
    assert reviewed["eligible_for_reconciliation"] is False
    assert reviewed["authorizes_execution"] is False
    assert reviewed["changes_capital_authority"] is False

    repository.revoke_latest(
        intake_id=intake.intake_id,
        expected_active_review_id=accepted.review_id,
        expected_active_review_fingerprint=accepted.review_fingerprint,
    )
    revoked = build_citic_source_follow_up(db_path)

    assert revoked["query_window_reviews_complete"] is False
    assert revoked["unreviewed_query_window_source_count"] == 1
    assert "reviewed_query_window_for_source" in revoked["required_evidence"]
    assert revoked["next_manual_action"] == "review_citic_source_query_windows"


def test_citic_source_follow_up_advances_only_after_exact_source_scope_review(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    intake = CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    query_review = CiticSourceQueryWindowReviewRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        expected_source_preview_fingerprint=citic_source_preview_fingerprint(preview),
        query_start_date="2026-05-01",
        query_end_date="2026-05-31",
        query_window_attested=True,
    )
    scope_review = CiticSourceScopeReviewRepository(db_path).record_review(
        intake_id=intake.intake_id,
        expected_file_fingerprint=preview.file_fingerprint,
        expected_source_preview_fingerprint=intake.source_preview_fingerprint,
        expected_query_window_review_id=query_review.review_id,
        expected_query_window_review_fingerprint=query_review.review_fingerprint,
        account_alias="citic-primary",
        account_reference_hash="sha256:" + "c" * 64,
        account_type="cash",
        market_scopes=["shanghai_a", "shenzhen_a"],
        asset_classes=["stock"],
        account_value_band="cny_0_20000",
        business_types=["history_trades"],
        no_other_filters_attested=True,
        complete_returned_results_attested=True,
        source_scope_attested=True,
    )

    reviewed = build_citic_source_follow_up(db_path)

    assert reviewed["reviewed_source_scope_source_count"] == 1
    assert reviewed["unreviewed_source_scope_source_count"] == 0
    assert reviewed["source_scope_reviews_complete"] is True
    assert reviewed["source_scope_batch_integrity_status"] == "clear"
    assert reviewed["source_scope_integrity_clear"] is True
    assert reviewed["source_scope_account_binding_consistent"] is True
    assert reviewed["source_scope_declared_scope_consistent"] is True
    assert reviewed["source_scope_complete_returned_results_attested"] is True
    assert "reviewed_source_scope_for_source" not in reviewed["required_evidence"]
    assert reviewed["next_manual_action"] == (
        "provide_citic_account_truth_evidence_or_reject_source"
    )
    assert reviewed["eligible_for_account_truth"] is False
    assert reviewed["eligible_for_reconciliation"] is False
    assert reviewed["authorizes_execution"] is False
    assert reviewed["changes_capital_authority"] is False
    serialized = json.dumps(reviewed, ensure_ascii=False)
    assert scope_review.account_reference_hash not in serialized


def test_citic_source_follow_up_keeps_cross_source_query_window_gaps_blocked(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    first = _preview_at(
        file_fingerprint="a" * 64,
        event_id="private-april-buy",
        occurred_at="2026-04-05T09:35:00+08:00",
        settled_at="2026-04-06",
    )
    second = _preview_at(
        file_fingerprint="b" * 64,
        event_id="private-may-buy",
        occurred_at="2026-05-05T09:35:00+08:00",
        settled_at="2026-05-06",
    )
    intake_repository = CiticSourceIntakeRepository(db_path)
    window_repository = CiticSourceQueryWindowReviewRepository(db_path)
    for preview, start, end in (
        (first, "2026-04-01", "2026-04-30"),
        (second, "2026-05-02", "2026-05-31"),
    ):
        intake_repository.record_review(
            preview,
            expected_file_fingerprint=preview.file_fingerprint,
            review_status="follow_up_required",
        )
        window_repository.record_review(
            preview,
            expected_file_fingerprint=preview.file_fingerprint,
            expected_source_preview_fingerprint=citic_source_preview_fingerprint(
                preview
            ),
            query_start_date=start,
            query_end_date=end,
            query_window_attested=True,
        )

    projection = build_citic_source_follow_up(db_path)

    assert projection["pending_source_count"] == 2
    assert projection["query_window_reviews_complete"] is True
    assert projection["query_window_batch_integrity_status"] == "blocked"
    assert projection["query_window_gap_calendar_day_count"] == 1
    assert projection["query_window_overlap_calendar_day_count"] == 0
    assert projection["query_window_integrity_clear"] is False
    assert "citic_query_window_batch_calendar_gap" in projection["blockers"]
    assert (
        "contiguous_non_overlapping_reviewed_query_windows"
        in projection["required_evidence"]
    )
    assert projection["next_manual_action"] == "review_citic_source_query_windows"
    assert projection["eligible_for_account_truth"] is False
    assert projection["eligible_for_reconciliation"] is False
    assert projection["authorizes_execution"] is False
    assert projection["changes_capital_authority"] is False


def test_citic_source_follow_up_fails_closed_at_intake_scan_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    base = CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    scanned = [
        replace(
            base,
            intake_id=f"citic_intake_{index:064x}",
            file_fingerprint=f"{index:064x}",
            source_preview_fingerprint=f"sha256:{index:064x}",
            review_id=f"citic_review_{index:064x}",
        )
        for index in range(200)
    ]
    monkeypatch.setattr(
        CiticSourceIntakeRepository,
        "list_intakes",
        lambda self, *, limit=50: scanned[:limit],
    )

    projection = build_citic_source_follow_up(db_path)

    assert projection["status"] == "citic_source_intake_scan_truncated"
    assert projection["subsystem_status"] == "blocked"
    assert projection["scanned_source_count"] == 200
    assert projection["intake_scan_truncated"] is True
    assert projection["count_complete"] is False
    assert "citic_source_intake_scan_truncated" in projection["blockers"]
    assert "complete_citic_source_intake_scan" in projection["required_evidence"]
    assert projection["next_manual_action"] == "review_citic_source_intake_scan_limit"
    assert projection["database_writes_performed"] is False


def test_citic_source_follow_up_closes_only_after_explicit_rejection(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    repository = CiticSourceIntakeRepository(db_path)
    repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    pending = build_citic_source_follow_up(db_path)

    repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="rejected",
    )
    closed = build_citic_source_follow_up(db_path)

    assert pending["status"] == "follow_up_required"
    assert closed["status"] == "no_follow_up_required"
    assert closed["pending_source_count"] == 0
    assert closed["evidence_fingerprint"] != pending["evidence_fingerprint"]


def test_citic_source_follow_up_surfaces_partial_schema_without_repair(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE citic_source_intakes (id INTEGER PRIMARY KEY)")
        conn.commit()
    before = db_path.stat()

    projection = build_citic_source_follow_up(db_path)

    assert projection["status"] == "citic_source_intake_schema_incomplete"
    assert projection["subsystem_status"] == "blocked"
    assert projection["count_complete"] is False
    assert projection["next_manual_action"] == (
        "repair_citic_source_intake_metadata_store"
    )
    assert projection["database_writes_performed"] is False
    after = db_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'citic_source_intake_reviews'"
            ).fetchone()[0]
            == 0
        )


def test_citic_source_follow_up_surfaces_partial_query_window_store_without_repair(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE citic_source_query_window_reviews " "(id INTEGER PRIMARY KEY)"
        )
        conn.commit()
    before = db_path.stat()

    projection = build_citic_source_follow_up(db_path)

    assert projection["status"] == (
        "citic_source_query_window_review_schema_incomplete"
    )
    assert projection["subsystem_status"] == "blocked"
    assert projection["count_complete"] is False
    assert projection["next_manual_action"] == (
        "repair_citic_source_query_window_review_store"
    )
    assert projection["database_writes_performed"] is False
    after = db_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_citic_source_follow_up_surfaces_partial_scope_store_without_repair(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    CiticSourceQueryWindowReviewRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        expected_source_preview_fingerprint=citic_source_preview_fingerprint(preview),
        query_start_date="2026-05-01",
        query_end_date="2026-05-31",
        query_window_attested=True,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE citic_source_scope_reviews (id INTEGER PRIMARY KEY)")
        conn.commit()
    before = db_path.stat()

    projection = build_citic_source_follow_up(db_path)

    assert projection["status"] == "citic_source_scope_review_schema_incomplete"
    assert projection["subsystem_status"] == "blocked"
    assert projection["count_complete"] is False
    assert projection["next_manual_action"] == (
        "repair_citic_source_scope_review_store"
    )
    assert projection["database_writes_performed"] is False
    after = db_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
