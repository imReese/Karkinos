from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from account_truth.evidence_scope_review import (
    EvidenceScopeReviewReadRejected,
    EvidenceScopeReviewRejected,
    EvidenceScopeReviewRepository,
)

_FILE_FINGERPRINT = "a" * 64
_OBSERVED_SCOPE_FINGERPRINT = "sha256:" + "b" * 64
_ACCOUNT_REFERENCE_HASH = "sha256:" + "c" * 64


def _record(repository: EvidenceScopeReviewRepository):
    return repository.record_review(
        import_run_id="import_synthetic",
        import_file_fingerprint=_FILE_FINGERPRINT,
        observed_scope_fingerprint=_OBSERVED_SCOPE_FINGERPRINT,
        provider="citic",
        account_alias="中信证券主账户",
        account_reference_hash=_ACCOUNT_REFERENCE_HASH,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-01-31",
        asset_classes=["stock", "fund"],
        full_account_scope_attested=True,
    )


def test_scope_review_missing_reads_are_zero_write(tmp_path: Path) -> None:
    db_path = tmp_path / "missing" / "account-truth.db"
    repository = EvidenceScopeReviewRepository(db_path)

    assert repository.get_latest_review("missing") is None
    assert repository.list_review_history("missing") == []
    assert not db_path.parent.exists()


def test_scope_review_is_append_only_idempotent_and_revocable(tmp_path: Path) -> None:
    db_path = tmp_path / "account-truth.db"
    repository = EvidenceScopeReviewRepository(db_path)

    accepted = _record(repository)
    replay = _record(repository)
    revoked = repository.revoke_latest(
        import_run_id="import_synthetic",
        expected_observed_scope_fingerprint=_OBSERVED_SCOPE_FINGERPRINT,
    )
    revoke_replay = repository.revoke_latest(
        import_run_id="import_synthetic",
        expected_observed_scope_fingerprint=_OBSERVED_SCOPE_FINGERPRINT,
    )

    assert accepted.decision == "accepted"
    assert accepted.account_alias == "中信证券主账户"
    assert accepted.account_reference_hash == _ACCOUNT_REFERENCE_HASH
    assert replay.review_id == accepted.review_id
    assert replay.reused is True
    assert revoked.decision == "revoked"
    assert revoked.review_id != accepted.review_id
    assert revoke_replay.review_id == revoked.review_id
    assert revoke_replay.reused is True
    assert [
        item.decision for item in repository.list_review_history("import_synthetic")
    ] == [
        "accepted",
        "revoked",
    ]
    assert repository.get_latest_review("import_synthetic") == revoked

    with sqlite3.connect(db_path) as conn:
        dump = "\n".join(conn.iterdump())
    assert "private-account-id-must-not-be-persisted" not in dump


def test_scope_review_rejects_invalid_or_unattested_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "account-truth.db"
    repository = EvidenceScopeReviewRepository(db_path)

    with pytest.raises(EvidenceScopeReviewRejected) as exc_info:
        repository.record_review(
            import_run_id="import_synthetic",
            import_file_fingerprint=_FILE_FINGERPRINT,
            observed_scope_fingerprint=_OBSERVED_SCOPE_FINGERPRINT,
            provider="citic",
            account_alias="primary",
            account_reference_hash=_ACCOUNT_REFERENCE_HASH,
            coverage_start_date="2026-02-01",
            coverage_end_date="2026-01-01",
            asset_classes=["stock"],
            full_account_scope_attested=True,
        )
    assert exc_info.value.code == "account_truth_evidence_scope_coverage_window_invalid"

    with pytest.raises(EvidenceScopeReviewRejected) as exc_info:
        repository.record_review(
            import_run_id="import_synthetic",
            import_file_fingerprint=_FILE_FINGERPRINT,
            observed_scope_fingerprint=_OBSERVED_SCOPE_FINGERPRINT,
            provider="citic",
            account_alias="primary",
            account_reference_hash=_ACCOUNT_REFERENCE_HASH,
            coverage_start_date="2026-01-01",
            coverage_end_date="2026-01-31",
            asset_classes=["stock"],
            full_account_scope_attested=False,
        )
    assert exc_info.value.code == "account_truth_evidence_scope_attestation_required"
    assert not db_path.exists()


def test_scope_review_partial_schema_fails_closed_without_repair(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "account-truth.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE account_truth_evidence_scope_reviews (id INTEGER PRIMARY KEY)"
        )
        conn.commit()
    before = db_path.stat()

    with pytest.raises(EvidenceScopeReviewReadRejected) as exc_info:
        EvidenceScopeReviewRepository(db_path).get_latest_review("missing")

    assert exc_info.value.code == (
        "account_truth_evidence_scope_review_schema_incomplete"
    )
    with pytest.raises(EvidenceScopeReviewRejected) as write_exc:
        _record(EvidenceScopeReviewRepository(db_path))
    assert write_exc.value.code == (
        "account_truth_evidence_scope_review_schema_incompatible"
    )
    after = db_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_scope_review_corrupt_record_fails_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "account-truth.db"
    repository = EvidenceScopeReviewRepository(db_path)
    accepted = _record(repository)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE account_truth_evidence_scope_reviews "
            "SET account_reference_hash = ? WHERE review_id = ?",
            ("raw-private-account-id", accepted.review_id),
        )
        conn.commit()

    with pytest.raises(EvidenceScopeReviewReadRejected) as exc_info:
        repository.get_latest_review("import_synthetic")

    assert exc_info.value.code == ("account_truth_evidence_scope_review_record_invalid")
