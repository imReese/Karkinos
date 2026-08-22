from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.broker_statement_roll_forward import (
    roll_forward_daily_broker_statement,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReview,
    EvidenceScopeReviewRepository,
)
from server.services.account_truth_evidence_readiness import (
    apply_account_truth_evidence_scope_review,
    build_account_truth_evidence_readiness,
    build_account_truth_evidence_scope,
    project_account_truth_evidence_readiness,
    project_account_truth_evidence_scope,
)

_ROLL_FORWARD_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
cash-anchor,cash_snapshot,2026-08-10T15:00:00+08:00,2026-08-10,,,,CNY,0,0,0,0,0,0,1000,,,
position-anchor,position_snapshot,2026-08-10T15:00:00+08:00,2026-08-10,SYN001,Synthetic Stock,stock,CNY,0,10,0,0,0,0,,10,10,source position
sell-001,trade_sell,2026-08-17T10:00:00+08:00,,SYN001,Synthetic Stock,stock,CNY,10,12,120,1,1,118,,0,0,source sell
"""


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
    identity = f"{event_type}:{occurred_at}:{settled_at}:{asset_class}"
    row_number = {
        "trade_buy": 2,
        "trade_sell": 3,
        "position_snapshot": 4,
        "cash_snapshot": 5,
    }.get(event_type, 6)
    return SimpleNamespace(
        row_number=row_number,
        row_fingerprint=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        event_id=f"synthetic-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
        is_row_duplicate=False,
        event_type=event_type,
        occurred_at=occurred_at,
        settled_at=settled_at,
        asset_class=asset_class,
        currency="CNY",
        note="synthetic persisted fact",
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


def test_build_readiness_uses_an_explicit_frozen_clock(tmp_path, monkeypatch):
    frozen = datetime(2026, 8, 21, 7, 30, tzinfo=timezone.utc)
    observed: list[datetime] = []
    state = SimpleNamespace(db=SimpleNamespace(_path=tmp_path / "app.db"))
    monkeypatch.setattr(
        "server.services.account_truth_evidence_readiness."
        "build_latest_account_truth_score_payload",
        lambda state: _score(),
    )
    monkeypatch.setattr(
        "server.services.account_truth_evidence_readiness."
        "build_citic_source_follow_up",
        lambda path: _follow_up(),
    )
    monkeypatch.setattr(
        "server.services.account_truth_evidence_readiness."
        "build_account_truth_evidence_scope",
        lambda **kwargs: _complete_scope(),
    )

    def promotion_at_clock(state, *, clock=None):
        assert clock is not None
        observed.append(clock())
        return {
            "status": "clear",
            "data_freshness_status": "fresh",
            "blockers": [],
            "snapshot_capture": {"status": "clear"},
        }

    monkeypatch.setattr(
        "server.services.account_truth_evidence_readiness."
        "build_latest_account_truth_promotion_evidence",
        promotion_at_clock,
    )

    projection = build_account_truth_evidence_readiness(
        state,
        clock=lambda: frozen,
    )

    assert projection["status"] == "ready"
    assert observed == [frozen]


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


def test_evidence_readiness_blocks_fresh_import_with_stale_account_snapshots():
    projection = project_account_truth_evidence_readiness(
        score=_score(),
        citic_source_follow_up=_follow_up(),
        evidence_scope=_complete_scope(),
        promotion_evidence={
            "source_fingerprint": "e" * 64,
            "data_freshness_status": "stale",
            "snapshot_capture": {
                "status": "clear",
                "captured_at": "2026-01-15T07:10:00+00:00",
            },
            "blockers": ["account_truth_snapshot_stale"],
        },
    )

    items = {item["requirement"]: item for item in projection["items"]}
    assert projection["status"] == "blocked"
    assert "account_truth_snapshot_stale" in projection["blockers"]
    assert items["cash_and_position_snapshot_effective_freshness"]["status"] == (
        "stale"
    )
    assert projection["next_manual_action"] == (
        "import_current_cash_and_position_snapshots"
    )
    assert projection["provider_contacted"] is False
    assert projection["database_writes_performed"] is False
    assert projection["authorizes_execution"] is False
    assert projection["changes_capital_authority"] is False


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
        "settlement_date_missing_count": 0,
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


def test_evidence_scope_exposes_missing_optional_settlement_date() -> None:
    scope = project_account_truth_evidence_scope(
        score=_score(),
        import_run=SimpleNamespace(
            import_run_id="synthetic-import",
            schema_version="karkinos.account_truth.broker_evidence.v2",
            valid_row_count=1,
        ),
        events=[
            _stored_event(
                event_type="cash_snapshot",
                occurred_at="2026-01-15T15:10:00+08:00",
                settled_at="",
                asset_class="",
            )
        ],
    )

    assert scope["observed_event_window"]["status"] == "available"
    assert scope["observed_event_window"]["settled_start_date"] is None
    assert scope["observed_event_window"]["settlement_date_missing_count"] == 1
    assert "account_truth_observed_event_time_invalid" not in scope["blockers"]


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


def test_scope_review_inherits_across_valid_daily_derived_snapshots(tmp_path):
    statement_path = tmp_path / "broker_statement.csv"
    statement_path.write_text(_ROLL_FORWARD_STATEMENT, encoding="utf-8")
    database_path = tmp_path / "app.db"
    broker_repository = BrokerEvidenceRepository(database_path)

    first_roll = roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    first_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    first_scope = project_account_truth_evidence_scope(
        score={"import_run_id": first_import.import_run_id},
        import_run=first_import,
        events=broker_repository.list_events(first_import.import_run_id),
    )
    scope_repository = EvidenceScopeReviewRepository(database_path)
    accepted = scope_repository.record_review(
        import_run_id=first_import.import_run_id,
        import_file_fingerprint=first_import.file_fingerprint,
        observed_scope_fingerprint=str(first_scope["observed_scope_fingerprint"]),
        provider="synthetic_broker",
        account_alias="synthetic_account",
        account_reference_hash="sha256:" + "a" * 64,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-12-31",
        asset_classes=["stock"],
        full_account_scope_attested=True,
        reviewer="synthetic_owner",
    )

    second_roll = roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    second_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    inherited = build_account_truth_evidence_scope(
        db_path=database_path,
        score={"import_run_id": second_import.import_run_id},
    )

    assert first_roll.source_fact_fingerprint == second_roll.source_fact_fingerprint
    assert inherited["status"] == "complete"
    assert inherited["review"]["review_id"] == accepted.review_id
    assert inherited["review"]["binding_mode"] == "inherited_source_fact_lineage"
    assert inherited["review"]["reviewed_import_run_id"] == first_import.import_run_id
    assert inherited["snapshot_evidence"]["latest_cash_snapshot_date"] == "2026-08-24"
    assert inherited["blockers"] == []


def test_scope_review_inheritance_fails_closed_on_source_fact_drift(tmp_path):
    statement_path = tmp_path / "broker_statement.csv"
    statement_path.write_text(_ROLL_FORWARD_STATEMENT, encoding="utf-8")
    database_path = tmp_path / "app.db"
    broker_repository = BrokerEvidenceRepository(database_path)

    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    first_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    first_scope = project_account_truth_evidence_scope(
        score={"import_run_id": first_import.import_run_id},
        import_run=first_import,
        events=broker_repository.list_events(first_import.import_run_id),
    )
    EvidenceScopeReviewRepository(database_path).record_review(
        import_run_id=first_import.import_run_id,
        import_file_fingerprint=first_import.file_fingerprint,
        observed_scope_fingerprint=str(first_scope["observed_scope_fingerprint"]),
        provider="synthetic_broker",
        account_alias="synthetic_account",
        account_reference_hash="sha256:" + "a" * 64,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-12-31",
        asset_classes=["stock"],
        full_account_scope_attested=True,
        reviewer="synthetic_owner",
    )

    changed = statement_path.read_text(encoding="utf-8").replace(
        ",120,1,1,118,,0,0,source sell\n",
        ",120,2,1,117,,0,0,source sell\n",
    )
    statement_path.write_text(changed, encoding="utf-8")
    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    changed_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    blocked = build_account_truth_evidence_scope(
        db_path=database_path,
        score={"import_run_id": changed_import.import_run_id},
    )

    assert blocked["status"] == "blocked"
    assert "account_truth_evidence_scope_review_lineage_drift" in blocked["blockers"]
    assert blocked["review"] is None

    statement_path.write_text(_ROLL_FORWARD_STATEMENT, encoding="utf-8")
    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-25",
        max_file_bytes=1024 * 1024,
    )
    reverted_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    still_blocked = build_account_truth_evidence_scope(
        db_path=database_path,
        score={"import_run_id": reverted_import.import_run_id},
    )

    assert still_blocked["status"] == "blocked"
    assert "account_truth_evidence_scope_review_lineage_drift" in (
        still_blocked["blockers"]
    )


def test_revoking_inherited_scope_review_blocks_current_daily_snapshot(tmp_path):
    statement_path = tmp_path / "broker_statement.csv"
    statement_path.write_text(_ROLL_FORWARD_STATEMENT, encoding="utf-8")
    database_path = tmp_path / "app.db"
    broker_repository = BrokerEvidenceRepository(database_path)

    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    first_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    first_scope = project_account_truth_evidence_scope(
        score={"import_run_id": first_import.import_run_id},
        import_run=first_import,
        events=broker_repository.list_events(first_import.import_run_id),
    )
    scope_repository = EvidenceScopeReviewRepository(database_path)
    scope_repository.record_review(
        import_run_id=first_import.import_run_id,
        import_file_fingerprint=first_import.file_fingerprint,
        observed_scope_fingerprint=str(first_scope["observed_scope_fingerprint"]),
        provider="synthetic_broker",
        account_alias="synthetic_account",
        account_reference_hash="sha256:" + "a" * 64,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-12-31",
        asset_classes=["stock"],
        full_account_scope_attested=True,
        reviewer="synthetic_owner",
    )
    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    current_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    scope_repository.revoke_latest(
        import_run_id=first_import.import_run_id,
        expected_observed_scope_fingerprint=str(
            first_scope["observed_scope_fingerprint"]
        ),
        reviewer="synthetic_owner",
    )

    blocked = build_account_truth_evidence_scope(
        db_path=database_path,
        score={"import_run_id": current_import.import_run_id},
    )

    assert blocked["status"] == "blocked"
    assert blocked["review"]["binding_mode"] == "inherited_source_fact_lineage"
    assert "account_truth_evidence_scope_review_revoked" in blocked["blockers"]
