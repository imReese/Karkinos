from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from account_truth.manual_review import (
    MANUAL_REVIEW_STATUSES,
    ManualReviewRepository,
)


def test_manual_review_repository_records_all_review_statuses(tmp_path: Path) -> None:
    repository = ManualReviewRepository(tmp_path / "account-truth.db")

    decisions = [
        repository.record_decision(
            import_run_id="import_synthetic",
            item_key=f"cash:{status}",
            category="cash",
            review_status=status,
            note=f"synthetic note for {status}",
            reviewer="local-reviewer",
        )
        for status in MANUAL_REVIEW_STATUSES
    ]

    assert [decision.review_status for decision in decisions] == list(
        MANUAL_REVIEW_STATUSES
    )
    assert all(decision.import_run_id == "import_synthetic" for decision in decisions)
    assert all(decision.created_at for decision in decisions)
    assert all(decision.updated_at for decision in decisions)

    saved = repository.list_decisions("import_synthetic")
    assert [decision.review_status for decision in saved] == list(
        MANUAL_REVIEW_STATUSES
    )
    assert saved[0].note == "synthetic note for accepted"
    assert saved[0].reviewer == "local-reviewer"


def test_manual_review_repository_updates_existing_item_decision(
    tmp_path: Path,
) -> None:
    repository = ManualReviewRepository(tmp_path / "account-truth.db")

    first = repository.record_decision(
        import_run_id="import_synthetic",
        item_key="position:SYN001",
        category="position",
        symbol="SYN001",
        review_status="needs_investigation",
        note="initial review",
        reviewer="operator-a",
    )
    updated = repository.record_decision(
        import_run_id="import_synthetic",
        item_key="position:SYN001",
        category="position",
        symbol="SYN001",
        review_status="known_difference",
        note="broker rounding difference",
        reviewer="operator-b",
    )

    assert updated.id == first.id
    assert updated.review_status == "known_difference"
    assert updated.note == "broker rounding difference"
    assert updated.reviewer == "operator-b"
    assert updated.created_at == first.created_at
    assert updated.updated_at >= first.updated_at
    assert repository.list_decisions("import_synthetic") == [updated]


def test_manual_review_repository_rejects_unknown_status(tmp_path: Path) -> None:
    repository = ManualReviewRepository(tmp_path / "account-truth.db")

    with pytest.raises(ValueError, match="unsupported manual review status"):
        repository.record_decision(
            import_run_id="import_synthetic",
            item_key="cash",
            category="cash",
            review_status="auto_fix",
        )


def test_ledger_candidate_review_does_not_mutate_production_ledger(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "account-truth.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE ledger_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT NOT NULL,
                amount REAL
            )
            """)
        conn.execute(
            "INSERT INTO ledger_entries (entry_type, amount) VALUES (?, ?)",
            ("cash_deposit", 1000.0),
        )
        conn.commit()

    repository = ManualReviewRepository(db_path)
    repository.record_decision(
        import_run_id="import_synthetic",
        item_key="fee:SYN001",
        category="fee",
        symbol="SYN001",
        review_status="ledger_candidate",
        note="candidate only; no automatic ledger mutation",
        reviewer="local-reviewer",
    )

    with sqlite3.connect(db_path) as conn:
        ledger_count = conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        ledger_amount = conn.execute(
            "SELECT SUM(amount) FROM ledger_entries"
        ).fetchone()[0]

    assert ledger_count == 1
    assert ledger_amount == 1000.0
