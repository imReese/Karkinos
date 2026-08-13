from __future__ import annotations

import json
from types import SimpleNamespace

from server.services.citic_source_scope_review import (
    project_citic_source_scope_batch_assessment,
)


def _query(intake_id: str, marker: str = "a") -> SimpleNamespace:
    return SimpleNamespace(
        intake_id=intake_id,
        decision="accepted",
        query_window_attested=True,
        review_id=f"citic_window_review_{marker}",
        review_fingerprint=f"sha256:{marker * 64}",
        file_fingerprint=marker * 64,
        source_preview_fingerprint=(marker.upper().lower() * 64),
    )


def _scope(
    query: SimpleNamespace,
    *,
    review_marker: str,
    account_marker: str = "c",
    market_scopes: list[str] | None = None,
    account_value_band: str | None = "cny_0_20000",
) -> SimpleNamespace:
    return SimpleNamespace(
        intake_id=query.intake_id,
        decision="accepted",
        query_window_review_id=query.review_id,
        query_window_review_fingerprint=query.review_fingerprint,
        file_fingerprint=query.file_fingerprint,
        source_preview_fingerprint=query.source_preview_fingerprint,
        account_alias="citic-primary",
        account_reference_hash=f"sha256:{account_marker * 64}",
        account_type="cash",
        market_scopes=market_scopes or ["shanghai_a", "shenzhen_a"],
        asset_classes=["stock"],
        account_value_band=account_value_band,
        business_types=["history_trades"],
        no_other_filters_attested=True,
        complete_returned_results_attested=True,
        source_scope_attested=True,
        review_fingerprint=f"sha256:{review_marker * 64}",
    )


def test_source_scope_batch_assessment_fails_closed_without_scope_reviews() -> None:
    query = _query("citic_intake_1")
    assessment = project_citic_source_scope_batch_assessment(
        source_count=1,
        active_query_window_reviews=[query],
        active_scope_reviews=[],
    )

    assert assessment["status"] == "blocked"
    assert assessment["integrity_status"] == "partial"
    assert assessment["reviewed_source_count"] == 0
    assert assessment["unreviewed_source_count"] == 1
    assert assessment["all_current_sources_reviewed"] is False
    assert assessment["account_scope_bound"] is False
    assert assessment["declared_source_scope_complete"] is False
    assert assessment["no_other_filters_attested"] is False
    assert assessment["complete_returned_results_attested"] is False
    assert "citic_source_scope_batch_sources_unreviewed" in assessment["blockers"]
    assert assessment["eligible_for_account_truth"] is False
    assert assessment["eligible_for_reconciliation"] is False
    assert assessment["authorizes_execution"] is False
    assert assessment["changes_capital_authority"] is False


def test_source_scope_batch_assessment_accepts_only_consistent_exact_reviews() -> None:
    first_query = _query("citic_intake_1", "a")
    second_query = _query("citic_intake_2", "b")
    assessment = project_citic_source_scope_batch_assessment(
        source_count=2,
        active_query_window_reviews=[first_query, second_query],
        active_scope_reviews=[
            _scope(first_query, review_marker="d"),
            _scope(second_query, review_marker="e"),
        ],
    )

    assert assessment["integrity_status"] == "clear"
    assert assessment["all_current_sources_reviewed"] is True
    assert assessment["account_binding_consistent"] is True
    assert assessment["declared_scope_consistent"] is True
    assert assessment["account_scope_bound"] is True
    assert assessment["declared_source_scope_complete"] is True
    assert assessment["no_other_filters_attested"] is True
    assert assessment["complete_returned_results_attested"] is True
    assert assessment["declared_account_type"] == "cash"
    assert assessment["declared_market_scopes"] == [
        "shanghai_a",
        "shenzhen_a",
    ]
    assert assessment["declared_asset_classes"] == ["stock"]
    assert assessment["declared_account_value_band"] == "cny_0_20000"
    assert assessment["declared_business_types"] == ["history_trades"]
    assert assessment["complete_account_coverage_proven"] is False
    assert "citic_source_scope_batch_complete_account_coverage_unproven" in (
        assessment["blockers"]
    )


def test_source_scope_batch_assessment_blocks_account_and_scope_drift() -> None:
    first_query = _query("citic_intake_1", "a")
    second_query = _query("citic_intake_2", "b")
    account_drift = project_citic_source_scope_batch_assessment(
        source_count=2,
        active_query_window_reviews=[first_query, second_query],
        active_scope_reviews=[
            _scope(first_query, review_marker="d", account_marker="c"),
            _scope(second_query, review_marker="e", account_marker="f"),
        ],
    )
    scope_drift = project_citic_source_scope_batch_assessment(
        source_count=2,
        active_query_window_reviews=[first_query, second_query],
        active_scope_reviews=[
            _scope(first_query, review_marker="d"),
            _scope(
                second_query,
                review_marker="e",
                market_scopes=["shanghai_a"],
            ),
        ],
    )

    assert account_drift["integrity_status"] == "blocked"
    assert account_drift["account_scope_bound"] is False
    assert (
        "citic_source_scope_batch_account_binding_conflict" in account_drift["blockers"]
    )
    assert scope_drift["integrity_status"] == "blocked"
    assert scope_drift["declared_source_scope_complete"] is False
    assert "citic_source_scope_batch_declared_scope_conflict" in scope_drift["blockers"]

    value_band_drift = project_citic_source_scope_batch_assessment(
        source_count=2,
        active_query_window_reviews=[first_query, second_query],
        active_scope_reviews=[
            _scope(first_query, review_marker="d"),
            _scope(
                second_query,
                review_marker="e",
                account_value_band="cny_20000_50000",
            ),
        ],
    )
    assert value_band_drift["integrity_status"] == "blocked"
    assert value_band_drift["declared_scope_consistent"] is False
    assert (
        "citic_source_scope_batch_declared_scope_conflict"
        in value_band_drift["blockers"]
    )


def test_source_scope_batch_assessment_rejects_legacy_missing_value_band() -> None:
    query = _query("citic_intake_1")
    assessment = project_citic_source_scope_batch_assessment(
        source_count=1,
        active_query_window_reviews=[query],
        active_scope_reviews=[
            _scope(query, review_marker="d", account_value_band=None)
        ],
    )

    assert assessment["integrity_status"] == "blocked"
    assert assessment["invalid_scope_review_count"] == 1
    assert assessment["all_current_sources_reviewed"] is False
    assert assessment["declared_account_value_band"] is None


def test_source_scope_batch_assessment_rejects_stale_query_binding() -> None:
    query = _query("citic_intake_1")
    scope = _scope(query, review_marker="d")
    scope.query_window_review_fingerprint = "sha256:" + "f" * 64

    assessment = project_citic_source_scope_batch_assessment(
        source_count=1,
        active_query_window_reviews=[query],
        active_scope_reviews=[scope],
    )

    assert assessment["integrity_status"] == "blocked"
    assert assessment["invalid_scope_review_count"] == 1
    assert assessment["reviewed_source_count"] == 0
    assert "citic_source_scope_batch_review_invalid" in assessment["blockers"]


def test_source_scope_batch_fingerprint_binds_account_without_exposing_hash() -> None:
    query = _query("citic_intake_1")
    first = project_citic_source_scope_batch_assessment(
        source_count=1,
        active_query_window_reviews=[query],
        active_scope_reviews=[_scope(query, review_marker="d", account_marker="c")],
    )
    second = project_citic_source_scope_batch_assessment(
        source_count=1,
        active_query_window_reviews=[query],
        active_scope_reviews=[_scope(query, review_marker="d", account_marker="e")],
    )

    assert first["assessment_fingerprint"] != second["assessment_fingerprint"]
    serialized = json.dumps(first, sort_keys=True)
    assert f"sha256:{'c' * 64}" not in serialized
    assert "citic_intake_1" not in serialized
    assert first["account_reference_hashes_included"] is False
    assert first["events_included"] is False
    assert first["source_names_included"] is False
    assert first["paths_included"] is False
    assert first["database_writes_performed"] is False
    assert first["provider_contacted"] is False
