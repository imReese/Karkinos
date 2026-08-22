from __future__ import annotations

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.broker_statement_roll_forward import (
    DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX,
    roll_forward_daily_broker_statement,
)
from account_truth.evidence_scope_review import EvidenceScopeReviewRepository
from account_truth.source_fact_continuity import (
    assess_account_truth_source_fact_continuity,
    assess_account_truth_source_fact_history_continuity,
    source_fact_continuity_allows_inheritance,
)
from server.services.account_truth_evidence_readiness import (
    build_account_truth_evidence_scope,
    project_account_truth_evidence_scope,
)

_HEADER = (
    "event_id,event_type,occurred_at,settled_at,symbol,instrument_name,"
    "asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,"
    "cash_balance,position_quantity,cost_basis,note,transfer_fee,"
    "cost_basis_method,broker_order_id,client_order_id\n"
)
_BASE_ROWS = (
    "cash-old,cash_snapshot,2026-08-01T15:00:00+08:00,2026-08-01,,,,CNY,"
    "0,0,0,0,0,0,900,,,,0,,,\n"
    "cash-anchor,cash_snapshot,2026-08-10T15:00:00+08:00,2026-08-10,,,,CNY,"
    "0,0,0,0,0,0,1000,,,,0,,,\n"
    "position-anchor,position_snapshot,2026-08-10T15:00:00+08:00,2026-08-10,"
    "SYN001,Synthetic Stock,stock,CNY,0,10,0,0,0,0,,10,10,source position,"
    "0,broker_remaining_cost,,\n"
    "sell-001,trade_sell,2026-08-17T10:00:00+08:00,,SYN001,Synthetic Stock,"
    "stock,CNY,10,12,120,1,1,118,,0,0,source sell,0,broker_remaining_cost,"
    "order-001,client-001\n"
)


def _save(repository, path):
    return repository.save_preview(parse_broker_statement_csv(path.read_bytes()))


def _events(repository, import_run):
    return repository.list_events(import_run.import_run_id)


def _record_scope_review(repository, import_run, *, db_path) -> None:
    scope = project_account_truth_evidence_scope(
        score={"import_run_id": import_run.import_run_id},
        import_run=import_run,
        events=_events(repository, import_run),
    )
    EvidenceScopeReviewRepository(db_path).record_review(
        import_run_id=import_run.import_run_id,
        import_file_fingerprint=import_run.file_fingerprint,
        observed_scope_fingerprint=str(scope["observed_scope_fingerprint"]),
        provider="synthetic_broker",
        account_alias="synthetic_account",
        account_reference_hash="sha256:" + "a" * 64,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-08-21",
        asset_classes=["cash", "stock"],
        full_account_scope_attested=True,
        reviewer="synthetic_owner",
    )


def test_continuity_accepts_superseded_snapshot_and_historical_settlement_metadata(
    tmp_path,
) -> None:
    path = tmp_path / "broker_statement.csv"
    path.write_text(_HEADER + _BASE_ROWS, encoding="utf-8")
    repository = BrokerEvidenceRepository(tmp_path / "app.db")
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    reviewed = _save(repository, path)

    rows = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX)
        and not line.startswith("cash-old,")
    ]
    path.write_text(
        "\n".join(rows).replace(
            "2026-08-17T10:00:00+08:00,,SYN001",
            "2026-08-17T10:00:00+08:00,2026-08-18,SYN001",
        )
        + "\n",
        encoding="utf-8",
    )
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    current = _save(repository, path)

    continuity = assess_account_truth_source_fact_continuity(
        current_import=current,
        current_events=_events(repository, current),
        reviewed_import=reviewed,
        reviewed_events=_events(repository, reviewed),
    )

    assert continuity["status"] == "continuous"
    assert continuity["mode"] == "canonical_state_refresh"
    assert continuity["settlement_metadata_changed_count"] == 1
    assert continuity["removed_activity_count"] == 0
    assert continuity["changed_activity_count"] == 0
    assert source_fact_continuity_allows_inheritance(continuity) is True


def test_scope_review_continues_across_append_only_activity_and_extends_window(
    tmp_path,
) -> None:
    path = tmp_path / "broker_statement.csv"
    path.write_text(_HEADER + _BASE_ROWS, encoding="utf-8")
    db_path = tmp_path / "app.db"
    repository = BrokerEvidenceRepository(db_path)
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    reviewed = _save(repository, path)
    _record_scope_review(repository, reviewed, db_path=db_path)

    path.write_text(
        path.read_text(encoding="utf-8")
        + "transfer-001,transfer_in,2026-08-24T08:30:00+08:00,2026-08-24,,,,"
        "CNY,0,0,0,0,0,50,1050,,,,0,,,,\n",
        encoding="utf-8",
    )
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    current = _save(repository, path)

    scope = build_account_truth_evidence_scope(
        db_path=db_path,
        score={"import_run_id": current.import_run_id},
    )
    continuity = assess_account_truth_source_fact_history_continuity(
        repository=repository,
        current_import=current,
        reviewed_import=reviewed,
    )

    assert scope["status"] == "complete"
    assert scope["review"]["binding_mode"] == "inherited_source_fact_continuity"
    assert scope["source_fact_continuity"]["added_activity_count"] == 1
    assert scope["declared_coverage_window"]["reviewed_end_date"] == "2026-08-21"
    assert scope["declared_coverage_window"]["end_date"] == "2026-08-24"
    assert continuity["status"] == "continuous"


def test_continuity_rejects_economic_activity_change_and_later_reversion(
    tmp_path,
) -> None:
    path = tmp_path / "broker_statement.csv"
    path.write_text(_HEADER + _BASE_ROWS, encoding="utf-8")
    repository = BrokerEvidenceRepository(tmp_path / "app.db")
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    reviewed = _save(repository, path)

    changed = path.read_text(encoding="utf-8").replace(
        ",120,1,1,118,,0,0,source sell,",
        ",120,2,1,117,,0,0,source sell,",
    )
    path.write_text(changed, encoding="utf-8")
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    changed_import = _save(repository, path)
    direct = assess_account_truth_source_fact_continuity(
        current_import=changed_import,
        current_events=_events(repository, changed_import),
        reviewed_import=reviewed,
        reviewed_events=_events(repository, reviewed),
    )
    assert direct["status"] == "blocked"
    assert "account_truth_source_fact_continuity_activity_changed" in direct["blockers"]

    path.write_text(_HEADER + _BASE_ROWS, encoding="utf-8")
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-25",
        max_file_bytes=1024 * 1024,
    )
    reverted = _save(repository, path)
    history = assess_account_truth_source_fact_history_continuity(
        repository=repository,
        current_import=reverted,
        reviewed_import=reviewed,
    )
    assert history["status"] == "blocked"
    assert (
        "account_truth_source_fact_continuity_activity_changed" in history["blockers"]
    )


def test_continuity_rejects_removed_activity(tmp_path) -> None:
    path = tmp_path / "broker_statement.csv"
    path.write_text(_HEADER + _BASE_ROWS, encoding="utf-8")
    repository = BrokerEvidenceRepository(tmp_path / "app.db")
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    reviewed = _save(repository, path)

    rows = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX)
        and not line.startswith("sell-001,")
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    current = _save(repository, path)
    continuity = assess_account_truth_source_fact_continuity(
        current_import=current,
        current_events=_events(repository, current),
        reviewed_import=reviewed,
        reviewed_events=_events(repository, reviewed),
    )

    assert continuity["status"] == "blocked"
    assert continuity["removed_activity_count"] == 1
    assert (
        "account_truth_source_fact_continuity_activity_removed"
        in continuity["blockers"]
    )
