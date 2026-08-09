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
from account_truth.citic_source_intake import CiticSourceIntakeRepository
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReviewRepository,
)
from account_truth.citic_source_scope_review import (
    CiticSourceScopeReviewReadRejected,
    CiticSourceScopeReviewRejected,
    CiticSourceScopeReviewRepository,
)

_PRIVATE_SOURCE = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method,broker_order_id,client_order_id
private-buy,trade_buy,2026-05-05T09:35:00+08:00,2026-05-06,PRIVATE-SYMBOL,PRIVATE-NAME,stock,CNY,100,10,1000,0,0,-1005,,,,PRIVATE-NOTE,0,,PRIVATE-ORDER,
"""
_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_ACCOUNT_REFERENCE_HASH = "sha256:" + "c" * 64


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


def _evidence(db_path: Path):
    preview = _preview()
    intake = CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    query_review = CiticSourceQueryWindowReviewRepository(
        db_path,
        clock=lambda: _NOW,
    ).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        expected_source_preview_fingerprint=intake.source_preview_fingerprint,
        query_start_date="2026-05-01",
        query_end_date="2026-05-31",
        query_window_attested=True,
    )
    return preview, intake, query_review


def _repository(db_path: Path):
    return CiticSourceScopeReviewRepository(db_path, clock=lambda: _NOW)


def _record(repository, preview, intake, query_review, **overrides):
    values = {
        "intake_id": intake.intake_id,
        "expected_file_fingerprint": preview.file_fingerprint,
        "expected_source_preview_fingerprint": intake.source_preview_fingerprint,
        "expected_query_window_review_id": query_review.review_id,
        "expected_query_window_review_fingerprint": (query_review.review_fingerprint),
        "account_alias": "citic-primary",
        "account_reference_hash": _ACCOUNT_REFERENCE_HASH,
        "account_type": "cash",
        "market_scopes": ["shanghai_a", "shenzhen_a"],
        "asset_classes": ["stock"],
        "business_types": ["history_trades"],
        "no_other_filters_attested": True,
        "complete_returned_results_attested": True,
        "source_scope_attested": True,
    }
    values.update(overrides)
    return repository.record_review(**values)


def test_source_scope_review_persists_only_sanitized_explicit_scope(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview, intake, query_review = _evidence(db_path)
    repository = _repository(db_path)

    review = _record(repository, preview, intake, query_review)

    assert review.review_id.startswith("citic_scope_review_")
    assert review.intake_id == intake.intake_id
    assert review.query_window_review_id == query_review.review_id
    assert review.account_alias == "citic-primary"
    assert review.account_reference_hash == _ACCOUNT_REFERENCE_HASH
    assert review.account_type == "cash"
    assert review.market_scopes == ["shanghai_a", "shenzhen_a"]
    assert review.asset_classes == ["stock"]
    assert review.business_types == ["history_trades"]
    assert review.no_other_filters_attested is True
    assert review.complete_returned_results_attested is True
    assert review.source_scope_attested is True
    assert review.decision == "accepted"
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
        "raw-private-account-identifier",
    ):
        assert private_value not in dump


def test_source_scope_review_is_idempotent_conflict_safe_and_revocable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview, intake, query_review = _evidence(db_path)
    repository = _repository(db_path)

    accepted = _record(repository, preview, intake, query_review)
    replay = _record(repository, preview, intake, query_review)
    assert replay.review_id == accepted.review_id
    assert replay.reused is True

    with pytest.raises(CiticSourceScopeReviewRejected) as conflict:
        _record(
            repository,
            preview,
            intake,
            query_review,
            market_scopes=["shanghai_a"],
        )
    assert conflict.value.code == "citic_source_scope_active_review_conflict"

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

    replacement = _record(
        repository,
        preview,
        intake,
        query_review,
        market_scopes=["shanghai_a"],
    )
    assert replacement.decision == "accepted"
    assert replacement.supersedes_review_id == revoked.review_id


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        (
            {"no_other_filters_attested": False},
            "citic_source_scope_no_other_filters_attestation_missing",
        ),
        (
            {"complete_returned_results_attested": False},
            "citic_source_scope_complete_results_attestation_missing",
        ),
        (
            {"source_scope_attested": False},
            "citic_source_scope_attestation_missing",
        ),
        (
            {"account_reference_hash": "raw-private-account-identifier"},
            "citic_source_scope_account_reference_invalid",
        ),
        ({"market_scopes": []}, "citic_source_scope_market_scopes_invalid"),
        ({"asset_classes": []}, "citic_source_scope_asset_classes_invalid"),
        ({"business_types": []}, "citic_source_scope_business_types_invalid"),
    ],
)
def test_source_scope_review_rejects_missing_or_unsafe_scope(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_code: str,
) -> None:
    db_path = tmp_path / "app.db"
    preview, intake, query_review = _evidence(db_path)

    with pytest.raises(CiticSourceScopeReviewRejected) as exc_info:
        _record(
            _repository(db_path),
            preview,
            intake,
            query_review,
            **overrides,
        )

    assert exc_info.value.code == expected_code


def test_source_scope_review_requires_current_query_window_and_pending_source(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    preview, intake, query_review = _evidence(db_path)
    repository = _repository(db_path)

    with pytest.raises(CiticSourceScopeReviewRejected) as mismatch:
        _record(
            repository,
            preview,
            intake,
            query_review,
            expected_query_window_review_fingerprint="sha256:" + "0" * 64,
        )
    assert mismatch.value.code == ("citic_source_scope_query_window_review_mismatch")

    CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="rejected",
    )
    with pytest.raises(CiticSourceScopeReviewRejected) as closed:
        _record(repository, preview, intake, query_review)
    assert closed.value.code == "citic_source_scope_source_not_pending"


def test_source_scope_review_missing_reads_are_zero_write(tmp_path: Path) -> None:
    db_path = tmp_path / "missing-parent" / "app.db"
    repository = _repository(db_path)

    assert repository.get_latest_review("citic_intake_missing") is None
    assert repository.list_latest_reviews() == []
    assert not db_path.parent.exists()


def test_source_scope_review_partial_or_corrupt_store_fails_closed(
    tmp_path: Path,
) -> None:
    partial_path = tmp_path / "partial.db"
    with sqlite3.connect(partial_path) as conn:
        conn.execute("CREATE TABLE citic_source_scope_reviews (id INTEGER PRIMARY KEY)")
        conn.commit()
    before = partial_path.stat()

    with pytest.raises(CiticSourceScopeReviewReadRejected) as partial:
        _repository(partial_path).list_latest_reviews()
    assert partial.value.code == "citic_source_scope_review_schema_incomplete"
    after = partial_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)

    db_path = tmp_path / "corrupt.db"
    preview, intake, query_review = _evidence(db_path)
    review = _record(_repository(db_path), preview, intake, query_review)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE citic_source_scope_reviews SET account_reference_hash = ? "
            "WHERE review_id = ?",
            ("raw-private-account-identifier", review.review_id),
        )
        conn.commit()
    with pytest.raises(CiticSourceScopeReviewReadRejected) as corrupt:
        _repository(db_path).get_latest_review(intake.intake_id)
    assert corrupt.value.code == "citic_source_scope_review_record_invalid"
