from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.db import AppDatabase
from server.services.controlled_broker_rejection_evidence import (
    CONTROLLED_BROKER_REJECTION_EXPORT_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_REJECTION_REVIEW_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_REJECTION_REVIEW_DISPOSITION,
    ControlledBrokerRejectionEvidenceRejected,
    ControlledBrokerRejectionEvidenceService,
)
from server.services.controlled_execution_operator_view import (
    ControlledExecutionOperatorViewService,
)
from server.services.oms import OmsService
from server.services.per_order_confirmation import build_order_fingerprint

NOW = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)


def _environment(
    tmp_path: Path,
    *,
    result_status: str = "rejected",
    definitive: bool = True,
    include_result_identity: bool = True,
) -> dict:
    db = AppDatabase(tmp_path / f"rejection-{result_status}.db")
    db.init_sync()
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key=f"rejection-{result_status}-order-1",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=10,
        source="controlled_rejection_test",
        source_ref="decision-1",
    )
    order = oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed exact order",
        actor="fixture-owner",
    )
    submit_intent_id = hashlib.sha256(
        f"rejection-{result_status}-submit-intent".encode()
    ).hexdigest()
    submit_fingerprint = hashlib.sha256(
        f"rejection-{result_status}-submit".encode()
    ).hexdigest()
    client_order_id = f"KARK-rejection-{result_status}-1"
    prepared = db.prepare_controlled_broker_submit_intent_sync(
        intent={
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "order_id": order["order_id"],
            "order_fingerprint": build_order_fingerprint(order),
            "confirmation_id": "c" * 64,
            "dossier_fingerprint": "d" * 64,
            "gateway_id": "fixture-controlled-gateway-1",
            "gateway_verification_fingerprint": "e" * 64,
            "release_evidence_id": "f" * 64,
            "release_evidence_fingerprint": "a" * 64,
            "client_order_id": client_order_id,
            "operator_id": "fixture-owner",
            "operator_approval_id": "b" * 64,
            "order_snapshot": {
                key: order.get(key)
                for key in (
                    "symbol",
                    "side",
                    "asset_class",
                    "quantity",
                    "order_type",
                    "limit_price",
                )
            },
            "prepared_at_epoch_ms": int(NOW.timestamp() * 1000),
            "prepared_at": NOW.isoformat(),
            "payload": {
                "submit_intent_id": submit_intent_id,
                "submit_fingerprint": submit_fingerprint,
                "order_id": order["order_id"],
                "account_alias": "main-cn-account",
            },
            "created_at": NOW.isoformat(),
        }
    )
    assert prepared["external_call_permitted"] is True
    result = {
        "status": result_status,
        "submitted": False,
        "definitive": definitive,
        "broker_order_id": "",
        "provider_message": "private raw provider text must not be exported",
        "api_key": "must-not-leak",
        "reason_codes": ["provider_secret_should_not_leak"],
    }
    if include_result_identity:
        result.update(
            {
                "client_order_id": client_order_id,
                "order_fingerprint": build_order_fingerprint(order),
            }
        )
    if result_status == "rejected_before_gateway_call":
        result["blockers"] = ["controlled_broker_submit_kill_switch_changed"]
    finalized_at = NOW + timedelta(milliseconds=1)
    finalized = db.finalize_controlled_broker_submit_intent_sync(
        submit_intent_id=submit_intent_id,
        status="rejected",
        broker_order_id="",
        broker_status=result_status,
        result=result,
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=int(finalized_at.timestamp() * 1000),
        finalized_at=finalized_at.isoformat(),
    )
    assert finalized["status"] == "rejected"
    return {
        "db": db,
        "order_id": order["order_id"],
        "submit_intent_id": submit_intent_id,
    }


def _protected_counts(db: AppDatabase) -> dict[str, int]:
    tables = (
        "oms_orders",
        "oms_transitions",
        "controlled_broker_submit_intents",
        "ledger_entries",
        "event_log",
        "controlled_submission_reconciliation_clearances",
        "controlled_submission_ledger_postings",
    )
    with sqlite3.connect(db._path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def test_definitive_rejection_exports_only_sanitized_persisted_evidence(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    service = ControlledBrokerRejectionEvidenceService(
        db=env["db"],
        clock=lambda: NOW + timedelta(minutes=1),
    )
    before = _protected_counts(env["db"])

    preview = service.preview(submit_intent_id=env["submit_intent_id"])

    assert preview["ready"] is True
    assert preview["status"] == "ready_for_human_review"
    assert (
        preview["rejection_evidence"]["classification"]
        == "definitive_gateway_rejection"
    )
    assert preview["rejection_evidence"]["result_status"] == "rejected"
    assert preview["rejection_evidence"]["submitted"] is False
    assert preview["rejection_evidence"]["definitive"] is True
    assert preview["retry_policy"] == {
        "same_intent_retry_allowed": False,
        "same_client_order_id_retry_allowed": False,
        "automatic_retry_allowed": False,
        "new_order_requires_new_decision_and_all_gates": True,
    }
    assert preview["safety"]["broker_submission_performed"] is False
    assert preview["safety"]["broker_retry_performed"] is False

    exported = service.export(
        submit_intent_id=env["submit_intent_id"],
        review_fingerprint=preview["review_fingerprint"],
        acknowledgement=CONTROLLED_BROKER_REJECTION_EXPORT_ACKNOWLEDGEMENT,
    )

    assert exported["status"] == "export_ready"
    assert exported["artifact"]["retry_performed"] is False
    assert exported["artifact"]["rejection_review_recorded"] is False
    assert "private raw provider text" not in exported["content"]
    assert "must-not-leak" not in exported["content"]
    assert "provider_secret_should_not_leak" not in exported["content"]
    assert _protected_counts(env["db"]) == before


def test_local_pre_gateway_rejection_preserves_reason_codes_without_retry(
    tmp_path: Path,
) -> None:
    env = _environment(
        tmp_path,
        result_status="rejected_before_gateway_call",
        definitive=False,
        include_result_identity=False,
    )
    preview = ControlledBrokerRejectionEvidenceService(db=env["db"]).preview(
        submit_intent_id=env["submit_intent_id"]
    )

    assert preview["ready"] is True
    assert (
        preview["rejection_evidence"]["classification"] == "local_pre_gateway_rejection"
    )
    assert preview["rejection_evidence"]["reason_codes"] == [
        "controlled_broker_submit_kill_switch_changed"
    ]
    assert preview["safety"]["provider_contact_performed"] is False


def test_non_rejected_or_ambiguous_evidence_fails_closed(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    db = env["db"]
    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE controlled_broker_submit_intents SET status = 'submission_unknown' WHERE submit_intent_id = ?",
            (env["submit_intent_id"],),
        )
        conn.commit()

    preview = ControlledBrokerRejectionEvidenceService(db=db).preview(
        submit_intent_id=env["submit_intent_id"]
    )

    assert preview["ready"] is False
    assert "controlled_broker_rejection_evidence_not_required" in preview["blockers"]


def test_export_rechecks_fingerprint_and_rejects_persisted_evidence_drift(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    db = env["db"]
    service = ControlledBrokerRejectionEvidenceService(db=db, clock=lambda: NOW)
    preview = service.preview(submit_intent_id=env["submit_intent_id"])
    with sqlite3.connect(db._path) as conn:
        row = conn.execute(
            "SELECT result_json FROM controlled_broker_submit_intents WHERE submit_intent_id = ?",
            (env["submit_intent_id"],),
        ).fetchone()
        result = json.loads(str(row[0]))
        result["status"] = "not_found"
        conn.execute(
            "UPDATE controlled_broker_submit_intents SET result_json = ? WHERE submit_intent_id = ?",
            (
                json.dumps(result, sort_keys=True, separators=(",", ":")),
                env["submit_intent_id"],
            ),
        )
        conn.commit()

    with pytest.raises(ControlledBrokerRejectionEvidenceRejected) as exc_info:
        service.export(
            submit_intent_id=env["submit_intent_id"],
            review_fingerprint=preview["review_fingerprint"],
            acknowledgement=CONTROLLED_BROKER_REJECTION_EXPORT_ACKNOWLEDGEMENT,
        )

    assert "controlled_broker_rejection_fingerprint_mismatch" in (
        exc_info.value.evidence["blockers"]
    )
    assert exc_info.value.evidence["export_performed"] is False


def test_restart_and_duplicate_export_are_deterministic(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    first = ControlledBrokerRejectionEvidenceService(db=env["db"], clock=lambda: NOW)
    restarted = ControlledBrokerRejectionEvidenceService(
        db=env["db"], clock=lambda: NOW + timedelta(hours=2)
    )
    first_preview = first.preview(submit_intent_id=env["submit_intent_id"])
    restarted_preview = restarted.preview(submit_intent_id=env["submit_intent_id"])
    assert (
        first_preview["review_fingerprint"] == restarted_preview["review_fingerprint"]
    )

    request = {
        "submit_intent_id": env["submit_intent_id"],
        "review_fingerprint": first_preview["review_fingerprint"],
        "acknowledgement": CONTROLLED_BROKER_REJECTION_EXPORT_ACKNOWLEDGEMENT,
    }
    first_export = first.export(**request)
    duplicate_export = restarted.export(**request)

    assert first_export["content"] == duplicate_export["content"]
    assert first_export["export_fingerprint"] == duplicate_export["export_fingerprint"]


def test_review_record_is_append_only_exactly_once_and_closes_order_journey(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    service = ControlledBrokerRejectionEvidenceService(
        db=env["db"],
        clock=lambda: NOW + timedelta(minutes=2),
    )
    preview = service.preview(submit_intent_id=env["submit_intent_id"])
    protected_before = _protected_counts(env["db"])
    request = {
        "submit_intent_id": env["submit_intent_id"],
        "review_fingerprint": preview["review_fingerprint"],
        "reviewer_id": "local-operator",
        "disposition": CONTROLLED_BROKER_REJECTION_REVIEW_DISPOSITION,
        "acknowledgement": CONTROLLED_BROKER_REJECTION_REVIEW_ACKNOWLEDGEMENT,
    }

    recorded = service.record_review(**request)
    restarted = ControlledBrokerRejectionEvidenceService(
        db=env["db"],
        clock=lambda: NOW + timedelta(days=1),
    ).record_review(**request)

    assert recorded["status"] == "recorded"
    assert recorded["record_performed"] is True
    assert recorded["reviewer_id"] == "local-operator"
    assert recorded["disposition"] == "acknowledged_no_retry"
    assert restarted["status"] == "already_recorded"
    assert restarted["reused"] is True
    assert restarted["review_id"] == recorded["review_id"]
    assert restarted["recorded_at"] == recorded["recorded_at"]
    assert recorded["safety"]["broker_retry_performed"] is False
    assert _protected_counts(env["db"]) == protected_before

    with sqlite3.connect(env["db"]._path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM controlled_broker_rejection_reviews"
        ).fetchall()
    assert len(rows) == 1
    assert "private raw provider text" not in str(rows[0][0])
    assert "must-not-leak" not in str(rows[0][0])

    operator_view = ControlledExecutionOperatorViewService(
        db=env["db"],
        clock=lambda: NOW + timedelta(minutes=3),
    ).summary()
    journey = operator_view["latest_order_journey"]
    assert operator_view["status"] == "order_journey_closed"
    assert operator_view["attention_order_journey_count"] == 0
    assert operator_view["primary_attention_order_journey"] is None
    assert journey["status"] == "submission_rejection_reviewed"
    assert journey["attention_required"] is False
    assert journey["attention_severity"] == "none"
    assert journey["next_operator_action"] == ("no_retry_create_new_decision_if_needed")
    review_stage = next(
        stage
        for stage in journey["stages"]
        if stage["key"] == "controlled_submission_rejection_review"
    )
    assert review_stage["complete"] is True
    assert review_stage["reviewer_id"] == "local-operator"
    assert operator_view["provider_contact_performed"] is False
    assert operator_view["broker_submission_enabled"] is False
    assert operator_view["broker_cancel_enabled"] is False


def test_review_record_rejects_conflicting_second_reviewer(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    service = ControlledBrokerRejectionEvidenceService(db=env["db"], clock=lambda: NOW)
    preview = service.preview(submit_intent_id=env["submit_intent_id"])
    base_request = {
        "submit_intent_id": env["submit_intent_id"],
        "review_fingerprint": preview["review_fingerprint"],
        "disposition": CONTROLLED_BROKER_REJECTION_REVIEW_DISPOSITION,
        "acknowledgement": CONTROLLED_BROKER_REJECTION_REVIEW_ACKNOWLEDGEMENT,
    }
    service.record_review(**base_request, reviewer_id="operator-a")

    with pytest.raises(ControlledBrokerRejectionEvidenceRejected) as exc_info:
        service.record_review(**base_request, reviewer_id="operator-b")

    assert exc_info.value.evidence["blockers"] == [
        "controlled_broker_rejection_review_already_recorded"
    ]
    assert exc_info.value.evidence["review_recorded"] is True
    with sqlite3.connect(env["db"]._path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM controlled_broker_rejection_reviews"
            ).fetchone()[0]
            == 1
        )


def test_concurrent_duplicate_review_records_once(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    preview = ControlledBrokerRejectionEvidenceService(db=env["db"]).preview(
        submit_intent_id=env["submit_intent_id"]
    )
    request = {
        "submit_intent_id": env["submit_intent_id"],
        "review_fingerprint": preview["review_fingerprint"],
        "reviewer_id": "local-operator",
        "disposition": CONTROLLED_BROKER_REJECTION_REVIEW_DISPOSITION,
        "acknowledgement": CONTROLLED_BROKER_REJECTION_REVIEW_ACKNOWLEDGEMENT,
    }

    def record() -> dict:
        return ControlledBrokerRejectionEvidenceService(
            db=env["db"],
            clock=lambda: NOW + timedelta(minutes=4),
        ).record_review(**request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: record(), range(2)))

    assert sorted(result["status"] for result in results) == [
        "already_recorded",
        "recorded",
    ]
    assert len({result["review_id"] for result in results}) == 1
    with sqlite3.connect(env["db"]._path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM controlled_broker_rejection_reviews"
            ).fetchone()[0]
            == 1
        )


def test_review_record_rechecks_evidence_under_write_lock(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    service = ControlledBrokerRejectionEvidenceService(db=env["db"], clock=lambda: NOW)
    preview = service.preview(submit_intent_id=env["submit_intent_id"])
    with sqlite3.connect(env["db"]._path) as conn:
        row = conn.execute(
            "SELECT result_json FROM controlled_broker_submit_intents WHERE submit_intent_id = ?",
            (env["submit_intent_id"],),
        ).fetchone()
        result = json.loads(str(row[0]))
        result["reason_codes"] = ["controlled_broker_submit_new_rejection_reason"]
        conn.execute(
            "UPDATE controlled_broker_submit_intents SET result_json = ? WHERE submit_intent_id = ?",
            (
                json.dumps(result, sort_keys=True, separators=(",", ":")),
                env["submit_intent_id"],
            ),
        )
        conn.commit()

    with pytest.raises(ControlledBrokerRejectionEvidenceRejected) as exc_info:
        service.record_review(
            submit_intent_id=env["submit_intent_id"],
            review_fingerprint=preview["review_fingerprint"],
            reviewer_id="local-operator",
            disposition=CONTROLLED_BROKER_REJECTION_REVIEW_DISPOSITION,
            acknowledgement=CONTROLLED_BROKER_REJECTION_REVIEW_ACKNOWLEDGEMENT,
        )

    assert "controlled_broker_rejection_fingerprint_mismatch" in (
        exc_info.value.evidence["blockers"]
    )
    with sqlite3.connect(env["db"]._path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM controlled_broker_rejection_reviews"
            ).fetchone()[0]
            == 0
        )


def test_operator_view_blocks_if_recorded_rejection_evidence_later_drifts(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    service = ControlledBrokerRejectionEvidenceService(db=env["db"], clock=lambda: NOW)
    preview = service.preview(submit_intent_id=env["submit_intent_id"])
    service.record_review(
        submit_intent_id=env["submit_intent_id"],
        review_fingerprint=preview["review_fingerprint"],
        reviewer_id="local-operator",
        disposition=CONTROLLED_BROKER_REJECTION_REVIEW_DISPOSITION,
        acknowledgement=CONTROLLED_BROKER_REJECTION_REVIEW_ACKNOWLEDGEMENT,
    )
    with sqlite3.connect(env["db"]._path) as conn:
        row = conn.execute(
            "SELECT result_json FROM controlled_broker_submit_intents WHERE submit_intent_id = ?",
            (env["submit_intent_id"],),
        ).fetchone()
        result = json.loads(str(row[0]))
        result["reason_codes"] = ["controlled_broker_submit_post_review_drift"]
        conn.execute(
            "UPDATE controlled_broker_submit_intents SET result_json = ? WHERE submit_intent_id = ?",
            (
                json.dumps(result, sort_keys=True, separators=(",", ":")),
                env["submit_intent_id"],
            ),
        )
        conn.commit()

    operator_view = ControlledExecutionOperatorViewService(
        db=env["db"],
        clock=lambda: NOW + timedelta(minutes=1),
    ).summary()

    assert operator_view["status"] == "blocked"
    assert (
        "controlled_broker_rejection_review_result_fingerprint_changed"
        in operator_view["source_blockers"]
    )
    assert operator_view["latest_order_journey"]["status"] == "submission_rejected"
    review_stage = next(
        stage
        for stage in operator_view["latest_order_journey"]["stages"]
        if stage["key"] == "controlled_submission_rejection_review"
    )
    assert review_stage["complete"] is False
