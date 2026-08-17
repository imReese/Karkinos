from __future__ import annotations

from types import SimpleNamespace

from account_truth.evidence_scope_review import EvidenceScopeReview
from server.services.account_truth_evidence_readiness import (
    apply_account_truth_evidence_scope_review,
    project_account_truth_evidence_readiness,
    project_account_truth_evidence_scope,
)


def _score(*, gate_status: str = "pass") -> dict[str, object]:
    return {
        "status": "available",
        "import_run_id": "synthetic-import",
        "gate_status": gate_status,
        "cash_status": "pass",
        "position_status": "pass",
        "fee_status": "pass",
        "cost_basis_status": "pass",
        "data_freshness_status": "fresh",
        "ledger_coverage": {"status": "covered"},
        "blocking_reasons": [],
        "required_actions": [],
    }


def _follow_up(*, pending_source_count: int = 0) -> dict[str, object]:
    pending = pending_source_count > 0
    return {
        "status": "follow_up_required" if pending else "no_follow_up_required",
        "pending_source_count": pending_source_count,
        "count_complete": True,
        "required_evidence": (
            [
                "current_cash_and_position_snapshot",
                "itemized_settlement_or_cash_flow",
            ]
            if pending
            else []
        ),
        "evidence_fingerprint": "sha256:" + "a" * 64,
        "next_manual_action": (
            "provide_citic_account_truth_evidence_or_reject_source"
            if pending
            else "none"
        ),
    }


def _complete_scope() -> dict[str, object]:
    return {
        "schema_version": "karkinos.account_truth.evidence_scope.v1",
        "status": "complete",
        "evidence_fingerprint": "sha256:" + "b" * 64,
        "blockers": [],
        "required_actions": [],
    }


def _stored_event(
    *,
    event_type: str,
    occurred_at: str,
    settled_at: str = "2026-01-15",
    asset_class: str = "stock",
) -> SimpleNamespace:
    return SimpleNamespace(
        is_row_duplicate=False,
        event_type=event_type,
        occurred_at=occurred_at,
        settled_at=settled_at,
        asset_class=asset_class,
        currency="CNY",
    )


def _accepted_review(observed_scope_fingerprint: str) -> EvidenceScopeReview:
    return EvidenceScopeReview(
        review_id="scope-review-1",
        schema_version="karkinos.account_truth.evidence_scope_review.v1",
        import_run_id="synthetic-import",
        import_file_fingerprint="a" * 64,
        observed_scope_fingerprint=observed_scope_fingerprint,
        provider="citic",
        account_alias="primary",
        account_reference_hash="sha256:" + "c" * 64,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-01-31",
        asset_classes=["stock"],
        full_account_scope_attested=True,
        decision="accepted",
        reviewer="local_owner",
        review_fingerprint="sha256:" + "d" * 64,
        created_at="2026-02-01T00:00:00+00:00",
    )


def test_evidence_readiness_blocks_incomplete_citic_sources_without_authority():
    projection = project_account_truth_evidence_readiness(
        score={},
        citic_source_follow_up=_follow_up(pending_source_count=4),
    )

    assert projection["schema_version"] == (
        "karkinos.account_truth.evidence_readiness.v2"
    )
    assert projection["status"] == "blocked"
    assert projection["account_truth_gate_status"] == "blocked"
    assert projection["known_incomplete_source_count"] == 4
    assert projection["required_evidence"] == [
        "current_cash_and_position_snapshot",
        "itemized_settlement_or_cash_flow",
    ]
    assert "citic_source_follow_up_required" in projection["blockers"]
    assert projection["persisted_facts_only"] is True
    assert projection["provider_contacted"] is False
    assert projection["database_writes_performed"] is False
    assert projection["eligible_for_reconciliation"] is False
    assert projection["authorizes_execution"] is False
    assert projection["changes_capital_authority"] is False


def test_evidence_readiness_requires_every_canonical_gate_to_pass():
    score = _score(gate_status="blocked")
    score["position_status"] = "mismatch"
    score["data_freshness_status"] = "stale"
    score["ledger_coverage"] = {"status": "stale"}
    score["blocking_reasons"] = ["unresolved_position_difference"]
    score["required_actions"] = ["review_position_difference"]

    projection = project_account_truth_evidence_readiness(
        score=score,
        citic_source_follow_up=_follow_up(),
    )

    items = {item["requirement"]: item for item in projection["items"]}
    assert projection["status"] == "blocked"
    assert items["current_position_snapshot"]["status"] == "mismatch"
    assert items["freshness_and_ledger_coverage"]["status"] == "stale"
    assert projection["next_manual_action"] == "review_position_difference"


def test_evidence_readiness_is_ready_only_for_complete_reviewed_evidence():
    projection = project_account_truth_evidence_readiness(
        score=_score(),
        citic_source_follow_up=_follow_up(),
        evidence_scope=_complete_scope(),
    )

    assert projection["status"] == "ready"
    assert projection["account_truth_gate_status"] == "pass"
    assert projection["next_manual_action"] == "none"
    assert projection["blockers"] == []
    assert projection["required_actions"] == []
    assert all(item["status"] == "pass" for item in projection["items"])
    assert str(projection["evidence_fingerprint"]).startswith("sha256:")


def test_evidence_readiness_fails_closed_when_source_counts_are_unreadable():
    follow_up = _follow_up()
    follow_up.update(
        {
            "status": "citic_source_intake_schema_incomplete",
            "count_complete": False,
            "next_manual_action": "repair_citic_source_intake_metadata_store",
        }
    )

    first = project_account_truth_evidence_readiness(
        score=_score(),
        citic_source_follow_up=follow_up,
        evidence_scope=_complete_scope(),
    )
    second = project_account_truth_evidence_readiness(
        score=_score(),
        citic_source_follow_up=follow_up,
        evidence_scope=_complete_scope(),
    )

    assert first["status"] == "blocked"
    assert first["source_review_count_complete"] is False
    assert "citic_source_intake_schema_incomplete" in first["blockers"]
    assert first["next_manual_action"] == ("repair_citic_source_intake_metadata_store")
    assert first["evidence_fingerprint"] == second["evidence_fingerprint"]


def test_evidence_readiness_projects_persisted_query_window_integrity_blockers():
    follow_up = _follow_up(pending_source_count=2)
    follow_up.update(
        {
            "blockers": ["citic_query_window_batch_calendar_gap"],
            "query_window_batch_integrity_status": "blocked",
            "query_window_batch_assessment_fingerprint": "sha256:" + "c" * 64,
            "query_window_gap_calendar_day_count": 1,
            "query_window_overlap_calendar_day_count": 0,
            "query_window_integrity_clear": False,
            "next_manual_action": "review_citic_source_query_windows",
        }
    )

    projection = project_account_truth_evidence_readiness(
        score=_score(),
        citic_source_follow_up=follow_up,
        evidence_scope=_complete_scope(),
    )

    assert projection["status"] == "blocked"
    assert "citic_query_window_batch_calendar_gap" in projection["blockers"]
    assert projection["next_manual_action"] == "review_citic_source_query_windows"
    assert projection["citic_source_follow_up"] == {
        "status": "follow_up_required",
        "pending_source_count": 2,
        "count_complete": True,
        "evidence_fingerprint": "sha256:" + "a" * 64,
        "query_window_batch_integrity_status": "blocked",
        "query_window_batch_assessment_fingerprint": "sha256:" + "c" * 64,
        "query_window_gap_calendar_day_count": 1,
        "query_window_overlap_calendar_day_count": 0,
        "query_window_integrity_clear": False,
        "source_scope_batch_integrity_status": "not_available",
        "source_scope_batch_assessment_fingerprint": "",
        "source_scope_integrity_clear": False,
        "source_scope_account_binding_consistent": False,
        "source_scope_declared_scope_consistent": False,
        "source_scope_complete_returned_results_attested": False,
        "intake_scan_truncated": False,
        "resolution": {
            "schema_version": (
                "karkinos.account_truth.citic_source_resolution_stage.v1"
            ),
            "status": "legacy_query_window_review_required",
            "pending_source_count": 2,
            "source_count_complete": True,
            "query_window_attestations_complete": False,
            "source_scope_attestations_complete": False,
            "legacy_source_attestations_complete": False,
            "canonical_account_truth_established_by_legacy_sources": False,
            "next_manual_action": "review_citic_source_query_windows",
            "satisfies_account_truth": False,
            "satisfies_reconciliation": False,
            "provider_contacted": False,
            "database_writes_performed": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
            "limitations": [
                "Reviewed legacy query windows and source scopes do not establish current or complete canonical Account Truth.",
                "Closing source follow-up still requires separately reviewed canonical evidence or an explicit source rejection.",
            ],
        },
    }
    assert projection["eligible_for_reconciliation"] is False
    assert projection["authorizes_execution"] is False
    assert projection["changes_capital_authority"] is False


def test_readiness_distinguishes_complete_legacy_attestations_from_canonical_scope():
    follow_up = _follow_up(pending_source_count=4)
    follow_up.update(
        {
            "query_window_integrity_clear": True,
            "source_scope_integrity_clear": True,
            "next_manual_action": (
                "provide_citic_account_truth_evidence_or_reject_source"
            ),
        }
    )

    projection = project_account_truth_evidence_readiness(
        score=_score(),
        citic_source_follow_up=follow_up,
        evidence_scope=_complete_scope(),
    )
    resolution = projection["citic_source_follow_up"]["resolution"]

    assert resolution["status"] == (
        "legacy_attestations_complete_canonical_resolution_required"
    )
    assert resolution["pending_source_count"] == 4
    assert resolution["legacy_source_attestations_complete"] is True
    assert resolution["canonical_account_truth_established_by_legacy_sources"] is False
    assert resolution["database_writes_performed"] is False
    assert resolution["authorizes_execution"] is False
    assert projection["status"] == "blocked"
    assert "citic_source_follow_up_required" in projection["blockers"]


def test_evidence_scope_exposes_observed_span_without_claiming_complete_coverage():
    import_run = SimpleNamespace(
        import_run_id="synthetic-import",
        schema_version="karkinos.account_truth.broker_evidence.v2",
        valid_row_count=3,
    )
    scope = project_account_truth_evidence_scope(
        score=_score(),
        import_run=import_run,
        events=[
            _stored_event(
                event_type="trade_buy",
                occurred_at="2026-01-05T09:35:00+08:00",
            ),
            _stored_event(
                event_type="position_snapshot",
                occurred_at="2026-01-15T15:10:00+08:00",
            ),
            _stored_event(
                event_type="cash_snapshot",
                occurred_at="2026-01-15T15:10:00+08:00",
                asset_class="",
            ),
        ],
    )

    assert scope["schema_version"] == "karkinos.account_truth.evidence_scope.v1"
    assert scope["status"] == "blocked"
    assert scope["account_binding"]["status"] == "missing"
    assert scope["declared_coverage_window"]["status"] == "missing"
    assert scope["observed_event_window"] == {
        "status": "available",
        "occurred_start_date": "2026-01-05",
        "occurred_end_date": "2026-01-15",
        "settled_start_date": "2026-01-15",
        "settled_end_date": "2026-01-15",
        "event_count": 3,
        "unique_event_count": 3,
        "expected_event_count": 3,
    }
    assert scope["asset_scope"]["observed_asset_classes"] == ["stock"]
    assert scope["snapshot_evidence"]["latest_cash_snapshot_date"] == "2026-01-15"
    assert "account_truth_account_scope_unbound" in scope["blockers"]
    assert "account_truth_coverage_window_undeclared" in scope["blockers"]
    assert scope["persisted_facts_only"] is True
    assert scope["database_writes_performed"] is False
    assert scope["authorizes_execution"] is False


def test_evidence_scope_fails_closed_on_invalid_event_time_or_count():
    scope = project_account_truth_evidence_scope(
        score=_score(),
        import_run=SimpleNamespace(
            import_run_id="synthetic-import",
            schema_version="karkinos.account_truth.broker_evidence.v2",
            valid_row_count=2,
        ),
        events=[
            _stored_event(
                event_type="cash_snapshot",
                occurred_at="2026-01-15 15:10:00",
                asset_class="",
            )
        ],
    )

    assert scope["observed_event_window"]["status"] == "blocked"
    assert "account_truth_evidence_scope_event_count_mismatch" in scope["blockers"]
    assert "account_truth_observed_event_time_invalid" in scope["blockers"]


def test_human_scope_review_cannot_clear_persisted_evidence_integrity_blocker():
    import_run = SimpleNamespace(
        import_run_id="synthetic-import",
        schema_version="karkinos.account_truth.broker_evidence.v2",
        file_fingerprint="a" * 64,
        valid_row_count=2,
    )
    observed = project_account_truth_evidence_scope(
        score=_score(),
        import_run=import_run,
        events=[
            _stored_event(
                event_type="position_snapshot",
                occurred_at="2026-01-15T15:10:00+08:00",
            )
        ],
    )
    review = _accepted_review(str(observed["observed_scope_fingerprint"]))

    scope = apply_account_truth_evidence_scope_review(
        observed_scope=observed,
        import_run=import_run,
        review=review,
    )

    assert scope["status"] == "blocked"
    assert "account_truth_evidence_scope_event_count_mismatch" in scope["blockers"]
    assert scope["authorizes_execution"] is False
    assert scope["changes_capital_authority"] is False


def test_exact_review_can_complete_scope_without_granting_authority():
    import_run = SimpleNamespace(
        import_run_id="synthetic-import",
        schema_version="karkinos.account_truth.broker_evidence.v2",
        file_fingerprint="a" * 64,
        valid_row_count=2,
    )
    observed = project_account_truth_evidence_scope(
        score=_score(),
        import_run=import_run,
        events=[
            _stored_event(
                event_type="position_snapshot",
                occurred_at="2026-01-15T15:10:00+08:00",
            ),
            _stored_event(
                event_type="cash_snapshot",
                occurred_at="2026-01-15T15:10:00+08:00",
                asset_class="",
            ),
        ],
    )
    review = _accepted_review(str(observed["observed_scope_fingerprint"]))

    complete = apply_account_truth_evidence_scope_review(
        observed_scope=observed,
        import_run=import_run,
        review=review,
    )
    readiness = project_account_truth_evidence_readiness(
        score=_score(),
        citic_source_follow_up=_follow_up(),
        evidence_scope=complete,
    )

    assert complete["status"] == "complete"
    assert complete["account_binding"]["status"] == "bound"
    assert complete["declared_coverage_window"]["status"] == "complete"
    assert complete["asset_scope"]["status"] == "complete"
    assert complete["blockers"] == []
    assert complete["database_writes_performed"] is False
    assert complete["authorizes_execution"] is False
    assert complete["changes_capital_authority"] is False
    assert readiness["status"] == "ready"
    assert readiness["authorizes_execution"] is False


def test_revoked_scope_review_fails_closed():
    import_run = SimpleNamespace(
        import_run_id="synthetic-import",
        schema_version="karkinos.account_truth.broker_evidence.v2",
        file_fingerprint="a" * 64,
        valid_row_count=1,
    )
    observed = project_account_truth_evidence_scope(
        score=_score(),
        import_run=import_run,
        events=[
            _stored_event(
                event_type="position_snapshot",
                occurred_at="2026-01-15T15:10:00+08:00",
            )
        ],
    )
    accepted = _accepted_review(str(observed["observed_scope_fingerprint"]))
    revoked = EvidenceScopeReview(**{**accepted.__dict__, "decision": "revoked"})

    scope = apply_account_truth_evidence_scope_review(
        observed_scope=observed,
        import_run=import_run,
        review=revoked,
    )

    assert scope["status"] == "blocked"
    assert "account_truth_evidence_scope_review_revoked" in scope["blockers"]
