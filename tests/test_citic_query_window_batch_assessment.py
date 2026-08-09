from __future__ import annotations

import json
from types import SimpleNamespace

from server.services.citic_source_query_window_review import (
    project_citic_query_window_batch_assessment,
)


def _review(
    *,
    intake_id: str,
    start: str,
    end: str,
    review_fingerprint: str | None = None,
) -> SimpleNamespace:
    suffix = intake_id.removeprefix("citic_intake_") or "0"
    return SimpleNamespace(
        intake_id=intake_id,
        query_start_date=start,
        query_end_date=end,
        query_window_attested=True,
        decision="accepted",
        review_fingerprint=(review_fingerprint or f"sha256:{suffix[-1] * 64}"),
    )


def test_query_window_batch_assessment_fails_closed_without_reviews() -> None:
    first = project_citic_query_window_batch_assessment(
        source_count=4,
        active_reviews=(),
    )
    second = project_citic_query_window_batch_assessment(
        source_count=4,
        active_reviews=(),
    )

    assert first["status"] == "blocked"
    assert first["integrity_status"] == "not_available"
    assert first["reviewed_source_count"] == 0
    assert first["unreviewed_source_count"] == 4
    assert first["all_current_sources_reviewed"] is False
    assert first["declared_window_start_date"] is None
    assert first["declared_window_end_date"] is None
    assert first["covered_calendar_day_count"] == 0
    assert first["gap_calendar_day_count"] == 0
    assert first["overlap_calendar_day_count"] == 0
    assert "citic_query_window_batch_sources_unreviewed" in first["blockers"]
    assert first["complete_account_coverage_proven"] is False
    assert first["eligible_for_account_truth"] is False
    assert first["eligible_for_reconciliation"] is False
    assert first["authorizes_execution"] is False
    assert first["changes_capital_authority"] is False
    assert first["assessment_fingerprint"] == second["assessment_fingerprint"]


def test_query_window_batch_assessment_keeps_partial_reviews_explicit() -> None:
    assessment = project_citic_query_window_batch_assessment(
        source_count=2,
        active_reviews=(
            _review(
                intake_id="citic_intake_1",
                start="2026-04-01",
                end="2026-04-30",
            ),
        ),
    )

    assert assessment["integrity_status"] == "partial"
    assert assessment["reviewed_source_count"] == 1
    assert assessment["unreviewed_source_count"] == 1
    assert assessment["declared_window_start_date"] == "2026-04-01"
    assert assessment["declared_window_end_date"] == "2026-04-30"
    assert assessment["covered_calendar_day_count"] == 30
    assert assessment["gap_calendar_day_count"] == 0
    assert assessment["overlap_calendar_day_count"] == 0
    assert assessment["declared_windows_contiguous"] is True
    assert assessment["declared_windows_non_overlapping"] is True


def test_query_window_batch_assessment_identifies_contiguous_reviewed_windows() -> None:
    assessment = project_citic_query_window_batch_assessment(
        source_count=2,
        active_reviews=(
            _review(
                intake_id="citic_intake_1",
                start="2026-04-01",
                end="2026-04-30",
            ),
            _review(
                intake_id="citic_intake_2",
                start="2026-05-01",
                end="2026-05-31",
            ),
        ),
    )

    assert assessment["integrity_status"] == "clear"
    assert assessment["all_current_sources_reviewed"] is True
    assert assessment["declared_window_start_date"] == "2026-04-01"
    assert assessment["declared_window_end_date"] == "2026-05-31"
    assert assessment["covered_calendar_day_count"] == 61
    assert assessment["gap_calendar_day_count"] == 0
    assert assessment["overlap_calendar_day_count"] == 0
    assert assessment["declared_windows_contiguous"] is True
    assert assessment["declared_windows_non_overlapping"] is True
    assert assessment["complete_account_coverage_proven"] is False
    assert "citic_query_window_batch_complete_account_coverage_unproven" in (
        assessment["blockers"]
    )


def test_query_window_batch_assessment_blocks_calendar_gaps() -> None:
    assessment = project_citic_query_window_batch_assessment(
        source_count=2,
        active_reviews=(
            _review(
                intake_id="citic_intake_1",
                start="2026-04-01",
                end="2026-04-30",
            ),
            _review(
                intake_id="citic_intake_2",
                start="2026-05-02",
                end="2026-05-31",
            ),
        ),
    )

    assert assessment["integrity_status"] == "blocked"
    assert assessment["gap_calendar_day_count"] == 1
    assert assessment["overlap_calendar_day_count"] == 0
    assert assessment["declared_windows_contiguous"] is False
    assert "citic_query_window_batch_calendar_gap" in assessment["blockers"]


def test_query_window_batch_assessment_blocks_overlapping_days() -> None:
    assessment = project_citic_query_window_batch_assessment(
        source_count=2,
        active_reviews=(
            _review(
                intake_id="citic_intake_1",
                start="2026-04-01",
                end="2026-04-30",
            ),
            _review(
                intake_id="citic_intake_2",
                start="2026-04-30",
                end="2026-05-29",
            ),
        ),
    )

    assert assessment["integrity_status"] == "blocked"
    assert assessment["gap_calendar_day_count"] == 0
    assert assessment["overlap_calendar_day_count"] == 1
    assert assessment["declared_windows_non_overlapping"] is False
    assert "citic_query_window_batch_calendar_overlap" in assessment["blockers"]


def test_query_window_batch_assessment_blocks_duplicate_review_identity() -> None:
    assessment = project_citic_query_window_batch_assessment(
        source_count=2,
        active_reviews=(
            _review(
                intake_id="citic_intake_1",
                start="2026-04-01",
                end="2026-04-30",
            ),
            _review(
                intake_id="citic_intake_1",
                start="2026-05-01",
                end="2026-05-31",
                review_fingerprint=f"sha256:{'2' * 64}",
            ),
        ),
    )

    assert assessment["integrity_status"] == "blocked"
    assert assessment["reviewed_source_count"] == 1
    assert assessment["unreviewed_source_count"] == 1
    assert assessment["invalid_review_count"] == 1
    assert "citic_query_window_batch_review_invalid" in assessment["blockers"]


def test_query_window_batch_assessment_binds_review_identity_without_exposing_it() -> (
    None
):
    first = project_citic_query_window_batch_assessment(
        source_count=1,
        active_reviews=(
            _review(
                intake_id="citic_intake_private_1",
                start="2026-04-01",
                end="2026-04-30",
                review_fingerprint=f"sha256:{'a' * 64}",
            ),
        ),
    )
    second = project_citic_query_window_batch_assessment(
        source_count=1,
        active_reviews=(
            _review(
                intake_id="citic_intake_private_1",
                start="2026-04-01",
                end="2026-04-30",
                review_fingerprint=f"sha256:{'b' * 64}",
            ),
        ),
    )

    assert first["assessment_fingerprint"] != second["assessment_fingerprint"]
    serialized = json.dumps(first, sort_keys=True)
    assert "citic_intake_private_1" not in serialized
    assert f"sha256:{'a' * 64}" not in serialized
    assert first["reviewed_query_windows_included"] is True
    assert first["source_names_included"] is False
    assert first["paths_included"] is False
    assert first["events_included"] is False
    assert first["transaction_details_included"] is False
    assert first["assessment_persisted"] is False
    assert first["database_writes_performed"] is False
    assert first["provider_contacted"] is False
