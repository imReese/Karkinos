from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
    CiticSourceQueryWindowReviewReadRejected,
    CiticSourceQueryWindowReviewRejected,
    CiticSourceQueryWindowReviewRepository,
)

_PRIVATE_SOURCE = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method,broker_order_id,client_order_id
private-buy,trade_buy,2026-05-05T09:35:00+08:00,2026-05-06,PRIVATE-SYMBOL,PRIVATE-NAME,stock,CNY,100,10,1000,0,0,-1005,,,,PRIVATE-NOTE,0,,PRIVATE-ORDER,
"""
_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


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


def _intake(db_path: Path, preview=None):
    source = preview or _preview()
    return CiticSourceIntakeRepository(db_path).record_review(
        source,
        expected_file_fingerprint=source.file_fingerprint,
        review_status="follow_up_required",
    )


def _repository(db_path: Path):
    return CiticSourceQueryWindowReviewRepository(
        db_path,
        clock=lambda: _NOW,
    )


def _record(repository, preview=None, **overrides):
    source = preview or _preview()
    values = {
        "expected_file_fingerprint": source.file_fingerprint,
        "expected_source_preview_fingerprint": (
            citic_source_preview_fingerprint(source)
        ),
        "query_start_date": "2026-05-01",
        "query_end_date": "2026-05-31",
        "query_window_attested": True,
    }
    values.update(overrides)
    return repository.record_review(source, **values)


def test_query_window_review_persists_only_exact_sanitized_scope(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    intake = _intake(db_path, preview)
    repository = _repository(db_path)

    review = _record(repository, preview)

    assert review.review_id.startswith("citic_window_review_")
    assert review.intake_id == intake.intake_id
    assert review.file_fingerprint == preview.file_fingerprint
    assert review.source_preview_fingerprint == intake.source_preview_fingerprint
    assert review.query_start_date == "2026-05-01"
    assert review.query_end_date == "2026-05-31"
    assert review.query_window_attested is True
    assert review.decision == "accepted"
    assert review.supersedes_review_id is None
    assert review.review_fingerprint.startswith("sha256:")
    assert repository.get_latest_review(intake.intake_id) == review
    assert repository.list_latest_reviews() == [review]

    with sqlite3.connect(db_path) as conn:
        dump = "\n".join(conn.iterdump())
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE name = 'broker_evidence_events'"
            ).fetchone()[0]
            == 0
        )
    for private_value in (
        "PRIVATE-SYMBOL",
        "PRIVATE-NAME",
        "PRIVATE-NOTE",
        "PRIVATE-ORDER",
    ):
        assert private_value not in dump


def test_query_window_review_is_idempotent_conflict_safe_and_revocable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    intake = _intake(db_path, preview)
    repository = _repository(db_path)

    accepted = _record(repository, preview)
    replay = _record(repository, preview)
    assert replay.review_id == accepted.review_id
    assert replay.reused is True

    with pytest.raises(CiticSourceQueryWindowReviewRejected) as conflict:
        _record(repository, preview, query_end_date="2026-05-30")
    assert conflict.value.code == ("citic_source_query_window_active_review_conflict")

    revoked = repository.revoke_latest(
        intake_id=intake.intake_id,
        expected_active_review_id=accepted.review_id,
        expected_active_review_fingerprint=accepted.review_fingerprint,
    )
    assert revoked.decision == "revoked"
    assert revoked.supersedes_review_id == accepted.review_id
    revoke_replay = repository.revoke_latest(
        intake_id=intake.intake_id,
        expected_active_review_id=accepted.review_id,
        expected_active_review_fingerprint=accepted.review_fingerprint,
    )
    assert revoke_replay.review_id == revoked.review_id
    assert revoke_replay.reused is True

    replacement = _record(repository, preview, query_end_date="2026-05-30")
    assert replacement.decision == "accepted"
    assert replacement.review_id != accepted.review_id
    assert replacement.supersedes_review_id == revoked.review_id
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM citic_source_query_window_reviews"
            ).fetchone()[0]
            == 3
        )


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        (
            {"query_window_attested": False},
            "citic_source_query_window_attestation_missing",
        ),
        (
            {"query_start_date": "2026-05-31", "query_end_date": "2026-05-01"},
            "citic_source_query_window_date_order_invalid",
        ),
        (
            {"query_start_date": "2026-04-01", "query_end_date": "2026-05-02"},
            "citic_source_query_window_exceeds_one_month",
        ),
        (
            {"query_start_date": "2026-08-01", "query_end_date": "2026-08-31"},
            "citic_source_query_window_future_date",
        ),
        (
            {"query_start_date": "2026-05-06", "query_end_date": "2026-05-31"},
            "citic_source_query_window_event_outside_reviewed_range",
        ),
        (
            {"expected_file_fingerprint": "0" * 64},
            "citic_source_query_window_file_fingerprint_mismatch",
        ),
        (
            {"expected_source_preview_fingerprint": "0" * 64},
            "citic_source_query_window_source_preview_mismatch",
        ),
    ],
)
def test_query_window_review_rejects_unverified_or_impossible_scope(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_code: str,
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    _intake(db_path, preview)

    with pytest.raises(CiticSourceQueryWindowReviewRejected) as exc_info:
        _record(_repository(db_path), preview, **overrides)

    assert exc_info.value.code == expected_code


def test_query_window_review_requires_current_follow_up_intake(tmp_path: Path) -> None:
    preview = _preview()
    missing_path = tmp_path / "missing" / "app.db"

    with pytest.raises(CiticSourceQueryWindowReviewRejected) as missing:
        _record(_repository(missing_path), preview)
    assert missing.value.code == "citic_source_query_window_intake_missing"
    assert not missing_path.parent.exists()

    db_path = tmp_path / "rejected.db"
    intake_repository = CiticSourceIntakeRepository(db_path)
    intake_repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="rejected",
    )
    with pytest.raises(CiticSourceQueryWindowReviewRejected) as rejected:
        _record(_repository(db_path), preview)
    assert rejected.value.code == "citic_source_query_window_source_not_pending"
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE name = 'citic_source_query_window_reviews'"
            ).fetchone()[0]
            == 0
        )


def test_non_financial_only_source_can_attest_an_explicit_empty_event_window(
    tmp_path: Path,
) -> None:
    preview = replace(
        _preview(),
        row_count=1,
        valid_row_count=0,
        invalid_row_count=0,
        events=[],
        errors=[
            BrokerStatementValidationError(
                row_number=2,
                code="citic_history_xls_non_financial_activity_ignored",
                message="Reviewed non-financial activity.",
            )
        ],
    )
    db_path = tmp_path / "app.db"
    _intake(db_path, preview)

    review = _record(
        _repository(db_path),
        preview,
        query_start_date="2026-04-01",
        query_end_date="2026-04-30",
    )

    assert review.decision == "accepted"
    assert review.query_start_date == "2026-04-01"
    assert review.query_end_date == "2026-04-30"


def test_missing_query_window_review_reads_are_zero_write(tmp_path: Path) -> None:
    db_path = tmp_path / "missing-parent" / "app.db"
    repository = _repository(db_path)

    assert repository.get_latest_review("citic_intake_missing") is None
    assert repository.list_latest_reviews() == []
    assert not db_path.parent.exists()


def test_partial_or_corrupt_query_window_store_fails_closed_without_repair(
    tmp_path: Path,
) -> None:
    partial_path = tmp_path / "partial.db"
    with sqlite3.connect(partial_path) as conn:
        conn.execute(
            "CREATE TABLE citic_source_query_window_reviews " "(id INTEGER PRIMARY KEY)"
        )
        conn.commit()
    before = partial_path.stat()

    with pytest.raises(CiticSourceQueryWindowReviewReadRejected) as partial:
        _repository(partial_path).list_latest_reviews()
    assert partial.value.code == ("citic_source_query_window_review_schema_incomplete")
    after = partial_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)

    corrupt_path = tmp_path / "corrupt.db"
    preview = _preview()
    intake = _intake(corrupt_path, preview)
    repository = _repository(corrupt_path)
    _record(repository, preview)
    with sqlite3.connect(corrupt_path) as conn:
        conn.execute(
            "UPDATE citic_source_query_window_reviews "
            "SET query_end_date = 'not-a-date'"
        )
        conn.commit()

    with pytest.raises(CiticSourceQueryWindowReviewReadRejected) as corrupt:
        repository.get_latest_review(intake.intake_id)
    assert corrupt.value.code == ("citic_source_query_window_review_record_invalid")
