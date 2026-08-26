from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from server.db import AppDatabase
from server.projections.service import build_portfolio_projection_from_db
from server.services.controlled_submission_ledger_posting import (
    CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT,
    CONTROLLED_SUBMISSION_LEDGER_POSTING_REJECTION_EVENT_TYPE,
    ControlledSubmissionLedgerPostingRejected,
    ControlledSubmissionLedgerPostingService,
)
from tests.test_controlled_submission_reconciliation_clearance import (
    _approval,
    _environment,
    _identity,
    _ledger_posting_approval,
    _preview,
    _record,
)

pytestmark = pytest.mark.trading_safety


_FAULTS = (
    (
        "second_ledger_entry",
        """
        CREATE TRIGGER fail_controlled_posting_checkpoint
        BEFORE INSERT ON ledger_entries
        WHEN NEW.source = 'controlled_submission_ledger_posting'
         AND (
             SELECT COUNT(*) FROM ledger_entries
             WHERE source = 'controlled_submission_ledger_posting'
         ) = 1
        BEGIN
            SELECT RAISE(ABORT, 'deterministic second ledger entry failure');
        END
        """,
    ),
    (
        "posting_record",
        """
        CREATE TRIGGER fail_controlled_posting_checkpoint
        BEFORE INSERT ON controlled_submission_ledger_postings
        BEGIN
            SELECT RAISE(ABORT, 'deterministic posting record failure');
        END
        """,
    ),
    (
        "completion_event",
        """
        CREATE TRIGGER fail_controlled_posting_checkpoint
        BEFORE INSERT ON event_log
        WHEN NEW.event_type = 'controlled_broker.ledger_posted'
        BEGIN
            SELECT RAISE(ABORT, 'deterministic completion event failure');
        END
        """,
    ),
)


def _install_fault(db_path: Path, statement: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(statement)
        conn.commit()


def _remove_fault(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TRIGGER fail_controlled_posting_checkpoint")
        conn.commit()


def _restart_service(env: dict) -> ControlledSubmissionLedgerPostingService:
    restarted_db = AppDatabase(Path(env["db"]._path))
    return ControlledSubmissionLedgerPostingService(
        db=restarted_db,
        account_truth_provider=lambda: env["account_truth"],
        trusted_operator_identities=[_identity(env["private_key"])],
        clock=lambda: env["clock"][0],
    )


@pytest.mark.parametrize(("checkpoint", "trigger_sql"), _FAULTS)
def test_posting_fault_rolls_back_every_financial_fact_and_restart_retries_once(
    tmp_path: Path,
    checkpoint: str,
    trigger_sql: str,
) -> None:
    env = _environment(tmp_path)
    clearance_preview = _preview(env)
    clearance = _record(
        env,
        clearance_preview,
        _approval(env, clearance_preview["clearance_fingerprint"]),
    )
    service = _restart_service(env)
    preview = service.preview(clearance_id=clearance["clearance_id"])
    approval = _ledger_posting_approval(env, preview["posting_fingerprint"])

    order_before = env["db"].get_oms_order_sync(preview["order_id"])
    intent_before = env["db"].get_controlled_broker_submit_intent_sync(
        preview["submit_intent_id"]
    )
    clearance_before = env[
        "db"
    ].get_controlled_submission_reconciliation_clearance_sync(preview["clearance_id"])
    _install_fault(Path(env["db"]._path), trigger_sql)

    with pytest.raises(ControlledSubmissionLedgerPostingRejected) as exc:
        service.apply(
            clearance_id=preview["clearance_id"],
            posting_fingerprint=preview["posting_fingerprint"],
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=approval["proof_signature_base64"],
            acknowledgement=CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT,
        )

    assert exc.value.evidence["rejection_reasons"] == [
        "controlled_ledger_posting_transaction_rejected"
    ]
    assert exc.value.evidence["transaction_blockers"] == [
        "controlled_ledger_posting_transaction_unavailable"
    ]
    assert env["db"].get_ledger_entries_sync() == [], checkpoint
    assert env["db"].list_controlled_submission_ledger_postings_sync() == []
    assert (
        env["db"].list_events_sync(
            event_type="portfolio.ledger_entry.recorded",
            limit=10,
        )
        == []
    )
    assert (
        env["db"].list_events_sync(
            event_type="controlled_broker.ledger_posted",
            limit=10,
        )
        == []
    )
    assert (
        len(
            env["db"].list_events_sync(
                event_type=CONTROLLED_SUBMISSION_LEDGER_POSTING_REJECTION_EVENT_TYPE,
                limit=10,
            )
        )
        == 1
    )
    assert env["db"].get_oms_order_sync(preview["order_id"]) == order_before
    assert (
        env["db"].get_controlled_broker_submit_intent_sync(preview["submit_intent_id"])
        == intent_before
    )
    assert (
        env["db"].get_controlled_submission_reconciliation_clearance_sync(
            preview["clearance_id"]
        )
        == clearance_before
    )
    projection = build_portfolio_projection_from_db(env["db"])
    assert "600519" not in projection.positions
    assert projection.cash == 0

    _remove_fault(Path(env["db"]._path))
    restarted_service = _restart_service(env)
    retry_preview = restarted_service.preview(clearance_id=preview["clearance_id"])
    assert retry_preview["posting_fingerprint"] == preview["posting_fingerprint"]
    retry_approval = _ledger_posting_approval(
        env,
        retry_preview["posting_fingerprint"],
    )
    posted = restarted_service.apply(
        clearance_id=retry_preview["clearance_id"],
        posting_fingerprint=retry_preview["posting_fingerprint"],
        operator_approval_id=retry_approval["approval_id"],
        operator_proof_signature_base64=retry_approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT,
    )
    replayed = _restart_service(env).apply(
        clearance_id=retry_preview["clearance_id"],
        posting_fingerprint=retry_preview["posting_fingerprint"],
        operator_approval_id=posted["operator_approval_id"],
        operator_proof_signature_base64="unused-on-exact-replay",
        acknowledgement=CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT,
    )

    assert posted["status"] == "applied"
    assert posted["reused"] is False
    assert replayed["status"] == "applied"
    assert replayed["reused"] is True
    assert len(env["db"].get_ledger_entries_sync()) == 2
    assert len(env["db"].list_controlled_submission_ledger_postings_sync()) == 1
    assert (
        len(
            env["db"].list_events_sync(
                event_type="portfolio.ledger_entry.recorded",
                limit=10,
            )
        )
        == 2
    )
    assert (
        len(
            env["db"].list_events_sync(
                event_type="controlled_broker.ledger_posted",
                limit=10,
            )
        )
        == 1
    )


def test_committed_posting_recovers_valuation_publication_after_restart_without_repost(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    clearance_preview = _preview(env)
    clearance = _record(
        env,
        clearance_preview,
        _approval(env, clearance_preview["clearance_fingerprint"]),
    )
    service = _restart_service(env)
    assert service.get_status()["valuation_publication_recovery_mode"] == (
        "exact_idempotent_posting_replay"
    )
    preview = service.preview(clearance_id=clearance["clearance_id"])
    approval = _ledger_posting_approval(env, preview["posting_fingerprint"])

    order_before = env["db"].get_oms_order_sync(preview["order_id"])
    oms_transitions_before = env["db"].list_oms_transitions_sync(preview["order_id"])
    intent_before = env["db"].get_controlled_broker_submit_intent_sync(
        preview["submit_intent_id"]
    )

    def fail_valuation_publication(*_args, **_kwargs):
        raise RuntimeError("injected post-commit valuation publication failure")

    service._db._financial_facts._valuation_transaction_writer = (
        fail_valuation_publication
    )
    posted = service.apply(
        clearance_id=preview["clearance_id"],
        posting_fingerprint=preview["posting_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT,
    )

    assert posted["status"] == "applied"
    assert posted["reused"] is False
    assert posted["post_apply_status"] == "valuation_publication_recovery_required"
    assert posted["post_valuation_publication_status"] == "publication_failed"
    assert posted["post_valuation_publication_recovery_required"] is True
    assert posted["post_valuation_snapshot_id"] == ""
    publication = env["db"].get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "failed"
    ledger_after_commit = env["db"].get_ledger_entries_sync()
    postings_after_commit = env["db"].list_controlled_submission_ledger_postings_sync()
    ledger_events_after_commit = env["db"].list_events_sync(
        event_type="portfolio.ledger_entry.recorded",
        limit=10,
    )
    posting_events_after_commit = env["db"].list_events_sync(
        event_type="controlled_broker.ledger_posted",
        limit=10,
    )
    assert len(ledger_after_commit) == 2
    assert len(postings_after_commit) == 1
    assert len(ledger_events_after_commit) == 2
    assert len(posting_events_after_commit) == 1

    recovered = _restart_service(env).apply(
        clearance_id=preview["clearance_id"],
        posting_fingerprint=preview["posting_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT,
    )

    assert recovered["status"] == "applied"
    assert recovered["reused"] is True
    assert recovered["post_valuation_publication_status"] == "published"
    assert recovered["post_valuation_publication_recovery_required"] is False
    assert recovered["post_valuation_snapshot_id"]
    assert recovered["post_ledger_cutoff_id"] == posted["post_ledger_cutoff_id"]
    publication = env["db"].get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "ready"
    assert publication["snapshot_id"] == recovered["post_valuation_snapshot_id"]
    assert env["db"].get_ledger_entries_sync() == ledger_after_commit
    assert (
        env["db"].list_controlled_submission_ledger_postings_sync()
        == postings_after_commit
    )
    assert (
        env["db"].list_events_sync(
            event_type="portfolio.ledger_entry.recorded",
            limit=10,
        )
        == ledger_events_after_commit
    )
    assert (
        env["db"].list_events_sync(
            event_type="controlled_broker.ledger_posted",
            limit=10,
        )
        == posting_events_after_commit
    )
    assert env["db"].get_oms_order_sync(preview["order_id"]) == order_before
    assert (
        env["db"].list_oms_transitions_sync(preview["order_id"])
        == oms_transitions_before
    )
    assert (
        env["db"].get_controlled_broker_submit_intent_sync(preview["submit_intent_id"])
        == intent_before
    )
