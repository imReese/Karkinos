from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from server.account_truth_gate import build_latest_account_truth_score_payload
from server.db import AppDatabase
from server.ledger.models import LedgerEntry
from server.projections.service import (
    build_portfolio_projection,
    build_portfolio_projection_from_db,
)
from server.services.controlled_submission_ledger_correction import (
    CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT,
    ControlledSubmissionLedgerCorrectionRejected,
    ControlledSubmissionLedgerCorrectionService,
    build_controlled_ledger_correction_plan,
)
from server.services.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
)
from server.services.execution_reconciliation import ExecutionReconciliationService
from tests.test_controlled_submission_reconciliation_clearance import (
    NOW,
    _apply_ledger_posting,
    _approval,
    _bind_controlled_account_alias,
    _environment,
    _identity,
    _ledger_posting_service,
    _preview,
    _record,
    _record_cancelled_lifecycle,
)

REASON = "operator_confirmed_mapping_error"
OPERATOR_ID = "local-clearance-owner"
pytestmark = pytest.mark.trading_safety


def _endpoint(router, path: str):
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path
    )


def _posted_environment(tmp_path) -> tuple[dict, dict]:
    env = _environment(tmp_path)
    clearance_preview = _preview(env)
    clearance = _record(
        env,
        clearance_preview,
        _approval(env, clearance_preview["clearance_fingerprint"]),
    )
    posting_service = _ledger_posting_service(env)
    posting_preview = posting_service.preview(clearance_id=clearance["clearance_id"])
    posted = _apply_ledger_posting(
        env,
        service=posting_service,
        preview=posting_preview,
    )
    return env, posted


def _service(env: dict, *, db=None) -> ControlledSubmissionLedgerCorrectionService:
    return ControlledSubmissionLedgerCorrectionService(
        db=db or env["db"],
        account_truth_provider=lambda: env["account_truth"],
        trusted_operator_identities=[_identity(env["private_key"])],
        clock=lambda: env["clock"][0],
    )


def _correction_approval(env: dict, fingerprint: str) -> dict:
    challenge = env["approvals"].create_challenge(
        operator_id=OPERATOR_ID,
        key_id="clearance-key-1",
        action="reverse_controlled_submission_ledger_posting",
        artifact_type="controlled_submission_ledger_correction",
        artifact_fingerprint=fingerprint,
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    signature_base64 = base64.b64encode(signature).decode("ascii")
    approval = env["approvals"].verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature_base64,
    )
    return {**approval, "proof_signature_base64": signature_base64}


def _apply_correction(env: dict, service, preview: dict) -> dict:
    approval = _correction_approval(env, preview["correction_fingerprint"])
    return service.apply(
        posting_id=preview["posting_id"],
        reason_code=preview["reason_code"],
        operator_id=preview["operator_id"],
        correction_fingerprint=preview["correction_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT,
    )


def test_signed_correction_preserves_history_and_restores_canonical_projection(
    tmp_path,
) -> None:
    env, posted = _posted_environment(tmp_path)
    original_ids = posted["ledger_entry_ids"]
    before = build_portfolio_projection_from_db(env["db"])
    service = _service(env)
    preview = service.preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )

    corrected = _apply_correction(env, service, preview)
    after = build_portfolio_projection_from_db(env["db"])
    ledger = env["db"].get_ledger_entries_sync(limit=20)

    assert before.positions["600519"].quantity == Decimal("100")
    assert before.cash == Decimal("-1002")
    assert preview["review_ready"] is True, preview["blockers"]
    assert preview["correction_plan"]["cash_delta"] == "1002"
    assert preview["correction_plan"]["position_before"]["quantity"] == "100"
    assert preview["correction_plan"]["position_after"]["quantity"] == "0"
    assert corrected["status"] == "applied"
    assert corrected["post_apply_status"] == "account_truth_recheck_required"
    assert after.cash == Decimal("0")
    assert after.positions["600519"].quantity == Decimal("0")
    assert after.positions["600519"].avg_cost == Decimal("0")
    assert after.positions["600519"].realized_pnl == Decimal("0")
    assert after.positions["600519"].commission_paid == Decimal("0")
    assert len(ledger) == 3
    assert {row["id"] for row in ledger}.issuperset(original_ids)
    assert (
        sum(row["source"] == "controlled_submission_ledger_posting" for row in ledger)
        == 2
    )
    correction_entry = next(
        row
        for row in ledger
        if row["source"] == "controlled_submission_ledger_correction"
    )
    assert correction_entry["entry_type"] == "controlled_projection_correction"
    assert correction_entry["correction_payload_json"]
    assert len(env["db"].list_controlled_submission_ledger_corrections_sync()) == 1


def test_correction_retry_after_restart_is_exactly_once(tmp_path) -> None:
    env, posted = _posted_environment(tmp_path)
    service = _service(env)
    preview = service.preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )
    first = _apply_correction(env, service, preview)

    restarted_db = AppDatabase(env["db"]._path)
    restarted_db.init_sync()
    retry = _service(env, db=restarted_db).apply(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
        correction_fingerprint=preview["correction_fingerprint"],
        operator_approval_id=first["operator_approval_id"],
        operator_proof_signature_base64="unused-on-exact-retry",
        acknowledgement=CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT,
    )

    assert retry["reused"] is True
    assert retry["correction_id"] == first["correction_id"]
    assert len(restarted_db.list_controlled_submission_ledger_corrections_sync()) == 1
    assert len(restarted_db.get_ledger_entries_sync(limit=20)) == 3


def test_concurrent_correction_commits_one_compensating_event(tmp_path) -> None:
    env, posted = _posted_environment(tmp_path)
    service = _service(env)
    preview = service.preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )
    approval = _correction_approval(env, preview["correction_fingerprint"])

    def apply_once() -> dict:
        return _service(env).apply(
            posting_id=posted["posting_id"],
            reason_code=REASON,
            operator_id=OPERATOR_ID,
            correction_fingerprint=preview["correction_fingerprint"],
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=approval["proof_signature_base64"],
            acknowledgement=(CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply_once(), range(2)))

    assert sorted(result["reused"] for result in results) == [False, True]
    assert len(env["db"].list_controlled_submission_ledger_corrections_sync()) == 1
    ledger = env["db"].get_ledger_entries_sync(limit=20)
    assert (
        sum(
            row["source"] == "controlled_submission_ledger_correction" for row in ledger
        )
        == 1
    )


def test_ledger_drift_inside_apply_transaction_rejects_whole_correction(
    tmp_path,
    monkeypatch,
) -> None:
    env, posted = _posted_environment(tmp_path)
    service = _service(env)
    preview = service.preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )
    approval = _correction_approval(env, preview["correction_fingerprint"])
    original_record = env["db"].record_controlled_submission_ledger_correction_sync

    def record_after_drift(*, correction: dict) -> dict:
        env["db"].insert_ledger_entry_sync(
            entry_type="cash_deposit",
            timestamp=(NOW + timedelta(hours=1)).isoformat(),
            amount=1,
            source="deterministic_race_fixture",
            source_ref="correction-ledger-race",
        )
        return original_record(correction=correction)

    monkeypatch.setattr(
        env["db"],
        "record_controlled_submission_ledger_correction_sync",
        record_after_drift,
    )
    with pytest.raises(ControlledSubmissionLedgerCorrectionRejected) as exc:
        service.apply(
            posting_id=posted["posting_id"],
            reason_code=REASON,
            operator_id=OPERATOR_ID,
            correction_fingerprint=preview["correction_fingerprint"],
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=approval["proof_signature_base64"],
            acknowledgement=(CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT),
        )

    assert "controlled_ledger_correction_transaction_rejected" in (
        exc.value.evidence["rejection_reasons"]
    )
    assert "controlled_ledger_correction_pre_ledger_cutoff_changed" in (
        exc.value.evidence["transaction_blockers"]
    )
    assert env["db"].list_controlled_submission_ledger_corrections_sync() == []
    ledger = env["db"].get_ledger_entries_sync(limit=20)
    assert all(
        row["source"] != "controlled_submission_ledger_correction" for row in ledger
    )


def test_dependent_sell_blocks_correction_preview(tmp_path) -> None:
    env, posted = _posted_environment(tmp_path)
    env["db"].insert_ledger_entry_sync(
        entry_type="trade_sell",
        timestamp=(NOW + timedelta(hours=1)).isoformat(),
        symbol="600519",
        direction="sell",
        quantity=100,
        price=11,
        commission=1,
        asset_class="stock",
        source="deterministic_dependent_trade_fixture",
        source_ref="dependent-sell",
    )

    preview = _service(env).preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )

    assert preview["review_ready"] is False
    assert "controlled_ledger_correction_replay_invalid" in preview["blockers"]
    assert env["db"].list_controlled_submission_ledger_corrections_sync() == []


def test_zero_fill_posting_has_no_financial_fact_to_correct(tmp_path) -> None:
    env = _environment(tmp_path, quantities=())
    _bind_controlled_account_alias(env)
    _record_cancelled_lifecycle(env, filled_quantity=0, cancelled_quantity=100)
    run = ExecutionReconciliationService(db=env["db"]).run_reconciliation(
        run_date="2026-07-14"
    )
    clearance_preview = env["service"].preview(
        submit_intent_id=env["submit_intent_id"],
        reconciliation_run_id=run["run_id"],
    )
    approval = _approval(env, clearance_preview["clearance_fingerprint"])
    clearance = env["service"].record(
        submit_intent_id=env["submit_intent_id"],
        reconciliation_run_id=run["run_id"],
        clearance_fingerprint=clearance_preview["clearance_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
    )
    posting_service = _ledger_posting_service(env)
    posting_preview = posting_service.preview(clearance_id=clearance["clearance_id"])
    posted = _apply_ledger_posting(
        env,
        service=posting_service,
        preview=posting_preview,
    )

    preview = _service(env).preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )

    assert preview["review_ready"] is False
    assert "controlled_ledger_correction_zero_fill_posting" in preview["blockers"]
    assert env["db"].get_ledger_entries_sync() == []


def test_correction_forces_account_truth_to_require_newer_broker_evidence(
    tmp_path,
) -> None:
    env, posted = _posted_environment(tmp_path)
    preview = _service(env).preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )
    _apply_correction(env, _service(env), preview)

    state = SimpleNamespace(
        db=env["db"],
        config=SimpleNamespace(initial_cash=0),
    )
    account_truth = build_latest_account_truth_score_payload(state)

    assert account_truth["ledger_coverage"]["status"] == "stale"
    assert account_truth["gate_status"] == "blocked"
    assert (
        "account_truth_evidence_predates_latest_ledger"
        in account_truth["blocking_reasons"]
    )


def test_correction_reconciles_ledger_portfolio_overview_and_account_truth(
    tmp_path,
    monkeypatch,
) -> None:
    from server.routes import ledger as ledger_routes
    from server.routes import portfolio as portfolio_routes

    env, posted = _posted_environment(tmp_path)
    preview = _service(env).preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )
    corrected = _apply_correction(env, _service(env), preview)
    state = SimpleNamespace(
        db=env["db"],
        config=SimpleNamespace(
            initial_cash=0,
            assets=[],
            live_poll_interval=60,
        ),
        scheduler=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: state)

    portfolio_router = portfolio_routes.create_router()
    snapshot = asyncio.run(_endpoint(portfolio_router, "/api/portfolio")())
    positions = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/positions")())
    allocation = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/allocation")())
    overview = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/overview")())
    equity_series = asyncio.run(
        _endpoint(portfolio_router, "/api/portfolio/equity-curve/series")(range="all")
    )
    account_state = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/state")())
    cockpit = asyncio.run(_endpoint(portfolio_router, "/api/portfolio/cockpit")())
    history = asyncio.run(
        _endpoint(ledger_routes.create_router(), "/api/ledger/entries")(
            limit=50,
            offset=0,
        )
    )
    account_truth = build_latest_account_truth_score_payload(state)

    assert positions == []
    assert snapshot.positions == []
    assert [item.symbol for item in snapshot.closed_positions] == ["600519"]
    assert all(item.asset_class == "cash" for item in allocation)
    assert overview.positions_count == 0
    assert overview.realized_pnl == pytest.approx(snapshot.realized_pnl_total)
    assert cockpit.positions == []
    assert account_state.snapshot.positions == []
    assert snapshot.valuation_snapshot_id == corrected["post_valuation_snapshot_id"]
    assert snapshot.valuation_snapshot_id == overview.valuation_snapshot_id
    assert snapshot.valuation_snapshot_id == cockpit.summary.valuation_snapshot_id
    assert snapshot.valuation_snapshot_id == (
        account_state.summary.valuation_snapshot_id
    )
    assert snapshot.ledger_cutoff_id == corrected["post_ledger_cutoff_id"]
    assert snapshot.ledger_cutoff_id == overview.ledger_cutoff_id
    assert snapshot.ledger_cutoff_id == cockpit.summary.ledger_cutoff_id
    assert snapshot.ledger_cutoff_id == account_state.summary.ledger_cutoff_id
    assert equity_series[-1].valuation_snapshot_id == snapshot.valuation_snapshot_id
    assert equity_series[-1].ledger_cutoff_id == snapshot.ledger_cutoff_id
    assert equity_series[-1].total == pytest.approx(snapshot.total_equity)
    assert len(history) == 3
    assert sum(item.entry_type == "trade_buy" for item in history) == 2
    correction_history = next(
        item
        for item in history
        if item.entry_type == "controlled_projection_correction"
    )
    assert correction_history.correction_payload["posting_id"] == posted["posting_id"]
    assert account_truth["ledger_coverage"]["status"] == "stale"
    assert account_truth["gate_status"] == "blocked"


def test_tampered_correction_evidence_fails_closed_during_replay(tmp_path) -> None:
    env, posted = _posted_environment(tmp_path)
    preview = _service(env).preview(
        posting_id=posted["posting_id"],
        reason_code=REASON,
        operator_id=OPERATOR_ID,
    )
    corrected = _apply_correction(env, _service(env), preview)
    with sqlite3.connect(env["db"]._path) as conn:
        row = conn.execute(
            "SELECT correction_payload_json FROM ledger_entries WHERE id = ?",
            (corrected["correction_ledger_entry_id"],),
        ).fetchone()
        payload = json.loads(row[0])
        payload["position_before"]["quantity"] = "99"
        conn.execute(
            "UPDATE ledger_entries SET correction_payload_json = ? WHERE id = ?",
            (json.dumps(payload), corrected["correction_ledger_entry_id"]),
        )
        conn.commit()

    with pytest.raises(ValueError, match="position evidence drifted"):
        build_portfolio_projection_from_db(env["db"])


def test_canonical_replay_derives_exact_sell_posting_reversal() -> None:
    rows = [
        {
            "id": 1,
            "entry_type": "trade_buy",
            "timestamp": "2026-07-10T02:00:00+00:00",
            "symbol": "600519",
            "direction": "buy",
            "quantity": 100.0,
            "price": 10.0,
            "commission": 2.0,
            "asset_class": "stock",
            "source": "manual",
        },
        {
            "id": 2,
            "entry_type": "trade_sell",
            "timestamp": "2026-07-11T02:00:00+00:00",
            "symbol": "600519",
            "direction": "sell",
            "quantity": 40.0,
            "price": 12.0,
            "commission": 1.0,
            "asset_class": "stock",
            "source": "controlled_submission_ledger_posting",
            "source_ref": "controlled-sell-fill-1",
        },
    ]
    plan = build_controlled_ledger_correction_plan(
        ledger_rows=rows,
        original_entry_ids=[2],
        posting_id="a" * 64,
    )
    corrected = build_portfolio_projection(
        [
            *(LedgerEntry.from_row(row) for row in rows),
            LedgerEntry(
                id=3,
                entry_type="controlled_projection_correction",
                timestamp=plan["effective_at"],
                symbol=plan["symbol"],
                asset_class=plan["asset_class"],
                source="controlled_submission_ledger_correction",
                source_ref="b" * 64,
                correction_payload=plan,
            ),
        ]
    )
    target = build_portfolio_projection([LedgerEntry.from_row(rows[0])])

    assert plan["cash_delta"] == "-479"
    assert plan["position_before"]["quantity"] == "60"
    assert plan["position_after"]["quantity"] == "100"
    assert corrected.cash == target.cash == Decimal("-1002")
    assert corrected.positions["600519"].quantity == Decimal("100")
    assert corrected.positions["600519"].avg_cost == Decimal("10.02")
    assert corrected.positions["600519"].realized_pnl == Decimal("0")
    assert corrected.positions["600519"].commission_paid == Decimal("2")


def test_existing_database_adds_explicit_correction_schema(tmp_path) -> None:
    db = AppDatabase(tmp_path / "existing-before-correction.db")
    db.init_sync()
    with sqlite3.connect(db._path) as conn:
        conn.execute("DROP TABLE controlled_submission_ledger_corrections")
        conn.execute("ALTER TABLE ledger_entries DROP COLUMN correction_payload_json")
        conn.commit()

    AppDatabase(db._path).init_sync()
    with sqlite3.connect(db._path) as conn:
        ledger_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(ledger_entries)")
        }
        correction_table = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table'
              AND name = 'controlled_submission_ledger_corrections'
            """).fetchone()

    assert "correction_payload_json" in ledger_columns
    assert correction_table[0] == "controlled_submission_ledger_corrections"
