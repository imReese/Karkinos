from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_COLUMNS,
    CITIC_HISTORY_XLS_SOURCE_TYPE,
)
from account_truth.citic_history_xls_directory import (
    CiticHistoryXlsDirectoryRejected,
    build_citic_history_xls_batch_assessment,
    find_citic_history_xls_directory_preview,
    scan_citic_history_xls_directory,
)

BROKER_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
private-event,trade_buy,2026-05-01T09:35:00+08:00,2026-05-02,SYN001,Private Instrument,stock,CNY,100,10,1000,5,0,-1005,8995,100,10.05,private note
"""


def _preview_for_content(content: bytes):
    content_fingerprint = hashlib.sha256(content).hexdigest()
    preview = parse_broker_statement_csv(BROKER_STATEMENT)
    return replace(
        preview,
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        file_fingerprint=content_fingerprint,
        validation_status="blocked",
        events=[
            replace(
                event,
                event_id=f"citic-{content_fingerprint}",
                row_fingerprint=content_fingerprint,
            )
            for event in preview.events
        ],
    )


def _scan(path, **overrides):
    values = {
        "path": path,
        "enabled": True,
        "max_files": 10,
        "max_file_bytes": 1024,
        "max_total_bytes": 4096,
    }
    values.update(overrides)
    return scan_citic_history_xls_directory(**values)


def test_directory_scan_is_explicit_bounded_deduplicated_and_stable(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "private-export-name"
    source.mkdir()
    (source / "second-private-202606.xls").write_bytes(b"beta")
    (source / "first-private-202605.xls").write_bytes(b"alpha")
    (source / "duplicate-private-202605.xls").write_bytes(b"alpha")
    (source / "ignored.csv").write_bytes(b"ignored")
    nested = source / "nested"
    nested.mkdir()
    (nested / "nested-private.xls").write_bytes(b"nested")
    monkeypatch.setattr(
        "account_truth.citic_history_xls_directory.parse_citic_history_xls",
        _preview_for_content,
    )

    first = _scan(source)
    second = _scan(source)

    expected_fingerprints = tuple(
        sorted(hashlib.sha256(content).hexdigest() for content in (b"alpha", b"beta"))
    )
    assert first.state == "ready"
    assert first.candidate_file_count == 3
    assert first.preview_count == 2
    assert first.duplicate_file_count == 1
    assert first.unreadable_file_count == 0
    assert tuple(preview.file_fingerprint for preview in first.previews) == (
        expected_fingerprints
    )
    assert dict(first.local_name_month_hints) == {
        hashlib.sha256(b"alpha").hexdigest(): "2026-05",
        hashlib.sha256(b"beta").hexdigest(): "2026-06",
    }
    assert first.scan_fingerprint == second.scan_fingerprint
    assert first.batch_assessment.integrity_status == "clear"
    assert first.batch_assessment.source_count == 2
    assert first.batch_assessment.observed_event_count == 2
    assert first.batch_assessment.unique_event_count == 2
    assert first.batch_assessment.observed_event_months == ("2026-05",)
    assert first.batch_assessment.cross_file_duplicate_event_count == 0
    assert first.batch_assessment.conflicting_event_identity_count == 0
    assert first.batch_assessment.status == "blocked"
    assert first.batch_assessment.complete_coverage_proven is False
    assert first.batch_assessment.events_included is False
    assert first.batch_assessment.private_fields_included is False
    assert first.batch_assessment.source_names_included is False
    assert first.batch_assessment.paths_included is False
    assert first.batch_assessment.evidence_persisted is False
    assert first.batch_assessment.eligible_for_account_truth is False
    assert first.batch_assessment.eligible_for_reconciliation is False
    assert not hasattr(first, "configured_path")
    assert not hasattr(first, "source_names")
    assert first.scan_persisted is False
    assert first.events_persisted is False
    assert first.eligible_for_account_truth is False
    assert first.eligible_for_reconciliation is False


def test_directory_scan_drops_ambiguous_or_conflicting_local_month_hints(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "exports"
    source.mkdir()
    (source / "same-202605.xls").write_bytes(b"same")
    (source / "same-202606.xls").write_bytes(b"same")
    (source / "no-month.xls").write_bytes(b"other")
    monkeypatch.setattr(
        "account_truth.citic_history_xls_directory.parse_citic_history_xls",
        _preview_for_content,
    )

    scan = _scan(source)

    assert scan.preview_count == 2
    assert scan.duplicate_file_count == 1
    assert scan.local_name_month_hints == ()


def test_batch_assessment_blocks_cross_file_duplicate_events():
    first = _preview_for_content(b"first")
    second = _preview_for_content(b"second")
    second = replace(
        second,
        events=[
            replace(
                second.events[0],
                event_id=first.events[0].event_id,
                row_fingerprint=first.events[0].row_fingerprint,
            )
        ],
    )

    assessment = build_citic_history_xls_batch_assessment((first, second))

    assert assessment.integrity_status == "blocked"
    assert assessment.observed_event_count == 2
    assert assessment.unique_event_count == 1
    assert assessment.cross_file_duplicate_event_count == 1
    assert assessment.conflicting_event_identity_count == 0
    assert "citic_history_xls_batch_cross_file_duplicate_events" in (
        assessment.blockers
    )


def test_batch_assessment_blocks_conflicting_event_identity_without_private_data():
    first = _preview_for_content(b"first")
    second = _preview_for_content(b"second")
    second = replace(
        second,
        events=[replace(second.events[0], event_id=first.events[0].event_id)],
    )

    assessment = build_citic_history_xls_batch_assessment((first, second))

    assert assessment.integrity_status == "blocked"
    assert assessment.unique_event_count == 2
    assert assessment.cross_file_duplicate_event_count == 0
    assert assessment.conflicting_event_identity_count == 1
    assert "citic_history_xls_batch_conflicting_event_identity" in (assessment.blockers)
    assert "Private Instrument" not in repr(assessment)
    assert "SYN001" not in repr(assessment)


def test_disabled_directory_scan_does_not_require_a_present_path(tmp_path):
    scan = scan_citic_history_xls_directory(
        path=tmp_path / "missing-private-directory",
        enabled=False,
        max_files=10,
        max_file_bytes=1024,
        max_total_bytes=4096,
    )

    assert scan.state == "disabled"
    assert scan.error_codes == ("citic_history_xls_directory_disabled",)
    assert scan.previews == ()


def test_directory_scan_rejects_symlinks_without_blocking_stable_files(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "exports"
    source.mkdir()
    (source / "stable.xls").write_bytes(b"stable")
    outside = tmp_path / "outside.xls"
    outside.write_bytes(b"outside-private")
    (source / "linked.xls").symlink_to(outside)
    monkeypatch.setattr(
        "account_truth.citic_history_xls_directory.parse_citic_history_xls",
        _preview_for_content,
    )

    scan = _scan(source)

    assert scan.state == "partial"
    assert scan.candidate_file_count == 2
    assert scan.preview_count == 1
    assert scan.unreadable_file_count == 1
    assert scan.error_codes == ("citic_history_xls_directory_unsafe_file",)


def test_directory_scan_fails_closed_before_reading_over_total_limit(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "exports"
    source.mkdir()
    (source / "one.xls").write_bytes(b"a" * 700)
    (source / "two.xls").write_bytes(b"b" * 700)
    parser = monkeypatch.setattr(
        "account_truth.citic_history_xls_directory.parse_citic_history_xls",
        lambda _: pytest.fail("oversized directory must not parse files"),
    )

    scan = _scan(source, max_total_bytes=1024)

    assert parser is None
    assert scan.state == "blocked"
    assert scan.preview_count == 0
    assert scan.error_codes == ("citic_history_xls_directory_total_size_exceeded",)


def test_directory_review_resolution_rechecks_exact_current_fingerprint(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "exports"
    source.mkdir()
    file = source / "private.xls"
    file.write_bytes(b"original")
    monkeypatch.setattr(
        "account_truth.citic_history_xls_directory.parse_citic_history_xls",
        _preview_for_content,
    )
    original_fingerprint = hashlib.sha256(b"original").hexdigest()

    preview = find_citic_history_xls_directory_preview(
        expected_file_fingerprint=original_fingerprint,
        path=source,
        enabled=True,
        max_files=10,
        max_file_bytes=1024,
        max_total_bytes=4096,
    )
    assert preview.file_fingerprint == original_fingerprint

    file.write_bytes(b"changed")
    with pytest.raises(CiticHistoryXlsDirectoryRejected) as exc_info:
        find_citic_history_xls_directory_preview(
            expected_file_fingerprint=original_fingerprint,
            path=source,
            enabled=True,
            max_files=10,
            max_file_bytes=1024,
            max_total_bytes=4096,
        )

    assert exc_info.value.code == ("citic_history_xls_directory_fingerprint_not_found")
