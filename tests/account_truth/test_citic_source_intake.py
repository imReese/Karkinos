from __future__ import annotations

import sqlite3
from dataclasses import replace
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
    CiticSourceIntakeReadRejected,
    CiticSourceIntakeRejected,
    CiticSourceIntakeRepository,
    citic_preview_is_recordable_for_follow_up,
    citic_source_preview_fingerprint,
)

_SENSITIVE_PREVIEW_CSV = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method,broker_order_id,client_order_id
synthetic-buy,trade_buy,2026-05-05T09:35:00+08:00,2026-05-06,SENSITIVE-SYMBOL,SENSITIVE-NAME,stock,CNY,100,10,1000,0,0,-1005,,,,SENSITIVE-NOTE,0,,ORDER-SYN-001,
"""


def _preview():
    canonical = parse_broker_statement_csv(_SENSITIVE_PREVIEW_CSV)
    return replace(
        canonical,
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
        limitations=["Itemized settlement components are absent from History Trades."],
        errors=[
            BrokerStatementValidationError(
                row_number=None,
                code="citic_history_xls_settlement_components_missing",
                message="Itemized settlement components are missing.",
            )
        ],
    )


def test_citic_source_intake_persists_only_sanitized_follow_up_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "account-truth.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE ledger_entries (id INTEGER PRIMARY KEY, amount TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO ledger_entries (amount) VALUES ('1000')")
        conn.commit()
    preview = _preview()
    repository = CiticSourceIntakeRepository(db_path)

    intake = repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )

    assert intake.intake_id.startswith("citic_intake_")
    assert intake.review_id.startswith("citic_review_")
    assert intake.source_preview_fingerprint == citic_source_preview_fingerprint(
        preview
    )
    assert intake.validation_status == "blocked"
    assert intake.recordable_for_follow_up is True
    assert intake.recognized_event_count == 1
    assert intake.error_codes == ["citic_history_xls_settlement_components_missing"]
    assert intake.required_evidence == [
        "itemized_settlement_or_cash_flow",
        "current_cash_and_position_snapshot",
    ]
    assert intake.review_status == "follow_up_required"
    assert repository.list_intakes() == [intake]

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'broker_evidence_events'"
            ).fetchone()[0]
            == 0
        )
        dump = "\n".join(conn.iterdump())
    for private_value in (
        "SENSITIVE-SYMBOL",
        "SENSITIVE-NAME",
        "SENSITIVE-NOTE",
        "ORDER-SYN-001",
    ):
        assert private_value not in dump


def test_citic_source_intake_records_non_financial_only_month_for_follow_up(
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
                message="Synthetic reviewed administration activity.",
            )
        ],
    )
    db_path = tmp_path / "account-truth.db"
    repository = CiticSourceIntakeRepository(db_path)

    assert citic_preview_is_recordable_for_follow_up(preview) is True
    intake = repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )

    assert intake.recognized_event_count == 0
    assert intake.required_evidence == [
        "current_cash_and_position_snapshot",
        "review_non_financial_activity",
    ]
    assert intake.error_codes == ["citic_history_xls_non_financial_activity_ignored"]
    assert repository.list_intakes() == [intake]
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'broker_evidence_events'"
            ).fetchone()[0]
            == 0
        )


def test_citic_source_intake_review_is_idempotent_and_rejection_is_terminal(
    tmp_path: Path,
) -> None:
    preview = _preview()
    repository = CiticSourceIntakeRepository(tmp_path / "account-truth.db")

    first = repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    replay = repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    rejected = repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="rejected",
    )

    assert replay.intake_id == first.intake_id
    assert replay.review_id == first.review_id
    assert replay.reused is True
    assert rejected.intake_id == first.intake_id
    assert rejected.review_id != first.review_id
    assert rejected.review_status == "rejected"

    with pytest.raises(CiticSourceIntakeRejected) as exc_info:
        repository.record_review(
            preview,
            expected_file_fingerprint=preview.file_fingerprint,
            review_status="follow_up_required",
        )
    assert exc_info.value.code == "citic_source_rejection_is_terminal"


def test_citic_source_intake_blocks_follow_up_for_unusable_source_but_allows_reject(
    tmp_path: Path,
) -> None:
    preview = replace(
        _preview(),
        normalized_columns=(),
        valid_row_count=0,
        invalid_row_count=1,
        events=[],
    )
    repository = CiticSourceIntakeRepository(tmp_path / "account-truth.db")

    assert citic_preview_is_recordable_for_follow_up(preview) is False
    with pytest.raises(CiticSourceIntakeRejected) as exc_info:
        repository.record_review(
            preview,
            expected_file_fingerprint=preview.file_fingerprint,
            review_status="follow_up_required",
        )
    assert exc_info.value.code == "citic_source_not_recordable_for_follow_up"

    rejected = repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="rejected",
    )
    assert rejected.review_status == "rejected"
    assert rejected.recordable_for_follow_up is False
    assert rejected.required_evidence[-1] == "resolve_invalid_rows"


def test_citic_source_intake_rechecks_exact_file_fingerprint(tmp_path: Path) -> None:
    preview = _preview()
    repository = CiticSourceIntakeRepository(tmp_path / "account-truth.db")

    with pytest.raises(CiticSourceIntakeRejected) as exc_info:
        repository.record_review(
            preview,
            expected_file_fingerprint="0" * 64,
            review_status="follow_up_required",
        )

    assert exc_info.value.code == "citic_source_file_fingerprint_mismatch"
    assert repository.list_intakes() == []


def test_citic_source_intake_repository_construction_and_missing_list_are_read_only(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing-parent" / "account-truth.db"

    repository = CiticSourceIntakeRepository(db_path)

    assert not db_path.parent.exists()
    assert repository.list_intakes() == []
    assert not db_path.parent.exists()


def test_citic_source_intake_list_ignores_unrelated_schema_without_writing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.commit()
    before = db_path.stat()

    assert CiticSourceIntakeRepository(db_path).list_intakes() == []

    after = db_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert tables == {"unrelated"}


def test_citic_source_intake_list_fails_closed_on_partial_schema_without_repair(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE citic_source_intakes (id INTEGER PRIMARY KEY)")
        conn.commit()
    before = db_path.stat()

    with pytest.raises(CiticSourceIntakeReadRejected) as exc_info:
        CiticSourceIntakeRepository(db_path).list_intakes()

    assert exc_info.value.code == "citic_source_intake_schema_incomplete"
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


def test_citic_source_intake_record_review_creates_schema_on_write(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "new-parent" / "account-truth.db"
    preview = _preview()

    intake = CiticSourceIntakeRepository(db_path).record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )

    assert intake.review_status == "follow_up_required"
    assert db_path.is_file()


@pytest.mark.parametrize(
    ("statement", "params"),
    [
        (
            "UPDATE citic_source_intakes SET required_evidence_json = ?",
            ("not-json",),
        ),
        (
            "UPDATE citic_source_intakes SET schema_version = ?",
            ("karkinos.account_truth.citic_source_intake.unknown",),
        ),
        (
            "UPDATE citic_source_intakes SET row_count = ?",
            (2,),
        ),
    ],
)
def test_citic_source_intake_list_fails_closed_on_invalid_persisted_record(
    tmp_path: Path,
    statement: str,
    params: tuple[object, ...],
) -> None:
    db_path = tmp_path / "app.db"
    preview = _preview()
    repository = CiticSourceIntakeRepository(db_path)
    repository.record_review(
        preview,
        expected_file_fingerprint=preview.file_fingerprint,
        review_status="follow_up_required",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(statement, params)
        conn.commit()
    before = db_path.stat()

    with pytest.raises(CiticSourceIntakeReadRejected) as exc_info:
        repository.list_intakes()

    assert exc_info.value.code == "citic_source_intake_record_invalid"
    after = db_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
