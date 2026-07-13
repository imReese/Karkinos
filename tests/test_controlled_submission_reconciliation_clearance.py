from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
    ControlledSubmissionReconciliationClearanceRejected,
    ControlledSubmissionReconciliationClearanceService,
)
from server.services.execution_batch_reconciliation import (
    ExecutionBatchReconciliationService,
)
from server.services.execution_reconciliation import ExecutionReconciliationService
from server.services.oms import OmsService
from server.services.operator_approval import OperatorApprovalService
from server.services.per_order_confirmation import build_order_fingerprint

NOW = datetime(2026, 7, 13, 3, 0, tzinfo=timezone.utc)
REVIEW_RUN_ID = "execution-reconciliation:2026-07-13"


def _identity(private_key: Ed25519PrivateKey) -> TrustedOperatorIdentityConfig:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return TrustedOperatorIdentityConfig(
        operator_id="local-clearance-owner",
        key_id="clearance-key-1",
        algorithm="ed25519",
        public_key_base64=base64.b64encode(public_bytes).decode("ascii"),
        enabled=True,
    )


def _statement(*, quantities: tuple[int, ...] = (40, 60)) -> str:
    rows = []
    for index, quantity in enumerate(quantities, start=1):
        gross = quantity * 10
        rows.append(
            ",".join(
                [
                    f"controlled-fill-{index}",
                    "trade_buy",
                    f"2026-07-13T10:0{index}:00+08:00",
                    "2026-07-14",
                    "600519",
                    "贵州茅台",
                    "stock",
                    "CNY",
                    str(quantity),
                    "10.00",
                    f"{gross}.00",
                    "1.00",
                    "0.00",
                    f"-{gross + 1}.00",
                    "100000.00",
                    str(quantity),
                    "10.01",
                    "reviewed controlled fill",
                    "0.00",
                ]
            )
        )
    return (
        "event_id,event_type,occurred_at,settled_at,symbol,instrument_name,"
        "asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,"
        "cash_balance,position_quantity,cost_basis,note,transfer_fee\n"
        + "\n".join(rows)
        + "\n"
    )


def _environment(tmp_path, *, quantities: tuple[int, ...] = (40, 60)) -> dict:
    clock = [NOW]
    db = AppDatabase(tmp_path / "controlled-clearance.db")
    db.init_sync()
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key="controlled-clearance-order-1",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=10,
        source="controlled_clearance_test",
        source_ref="decision-1",
    )
    order = oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed exact order",
        actor="local-clearance-owner",
    )
    submit_intent_id = hashlib.sha256(b"clearance-submit-intent").hexdigest()
    submit_fingerprint = hashlib.sha256(b"clearance-submit").hexdigest()
    prepared = db.prepare_controlled_broker_submit_intent_sync(
        intent={
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "order_id": order["order_id"],
            "order_fingerprint": build_order_fingerprint(order),
            "confirmation_id": "c" * 64,
            "dossier_fingerprint": "d" * 64,
            "gateway_id": "qmt-controlled-write-1",
            "gateway_verification_fingerprint": "e" * 64,
            "release_evidence_id": "f" * 64,
            "release_evidence_fingerprint": "a" * 64,
            "client_order_id": "KARK-clearance-client-order-1",
            "operator_id": "local-clearance-owner",
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
            },
            "created_at": NOW.isoformat(),
        }
    )
    assert prepared["external_call_permitted"] is True
    finalized = db.finalize_controlled_broker_submit_intent_sync(
        submit_intent_id=submit_intent_id,
        status="submitted",
        broker_order_id="BROKER-CLEARANCE-1",
        broker_status="accepted",
        result={
            "status": "accepted",
            "submitted": True,
            "definitive": True,
            "client_order_id": "KARK-clearance-client-order-1",
            "order_fingerprint": build_order_fingerprint(order),
            "broker_order_id": "BROKER-CLEARANCE-1",
        },
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=int(NOW.timestamp() * 1000) + 1,
        finalized_at=(NOW + timedelta(milliseconds=1)).isoformat(),
    )
    assert finalized["status"] == "submitted"

    repository = BrokerEvidenceRepository(Path(db._path))
    import_run = repository.save_preview(
        parse_broker_statement_csv(_statement(quantities=quantities)),
        source_name="broker_statement.csv",
    )
    reconciliation = ExecutionReconciliationService(db=db).run_reconciliation(
        run_date="2026-07-13"
    )
    private_key = Ed25519PrivateKey.generate()
    identity = _identity(private_key)
    approvals = OperatorApprovalService(
        db=db,
        trusted_identities=[identity],
        clock=lambda: clock[0],
        nonce_factory=lambda: "controlled-clearance-nonce-000000000000000001",
    )
    account_truth = {
        "status": "clear",
        "source_fingerprint": "1" * 64,
        "import_run_id": import_run.import_run_id,
        "file_fingerprint": import_run.file_fingerprint,
        "source_type": import_run.source_type,
        "captured_at": NOW.isoformat(),
        "data_freshness_status": "fresh",
        "reconciliation_status": "clear",
        "gate_status": "pass",
        "unresolved_mismatch_count": 0,
        "ledger_coverage": {"status": "covered"},
        "does_not_mutate_production_ledger": True,
        "private_account_number": "must-not-leak",
    }
    service = ControlledSubmissionReconciliationClearanceService(
        db=db,
        account_truth_provider=lambda: account_truth,
        trusted_operator_identities=[identity],
        clock=lambda: clock[0],
    )
    return {
        "db": db,
        "oms": oms,
        "order": order,
        "submit_intent_id": submit_intent_id,
        "submit_fingerprint": submit_fingerprint,
        "import_run": import_run,
        "reconciliation": reconciliation,
        "account_truth": account_truth,
        "service": service,
        "private_key": private_key,
        "approvals": approvals,
        "clock": clock,
    }


def _approval(env: dict, fingerprint: str) -> dict:
    challenge = env["approvals"].create_challenge(
        operator_id="local-clearance-owner",
        key_id="clearance-key-1",
        action="clear_controlled_submission_reconciliation",
        artifact_type="controlled_submission_reconciliation_clearance",
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


def _preview(env: dict) -> dict:
    return env["service"].preview(
        submit_intent_id=env["submit_intent_id"],
        reconciliation_run_id=REVIEW_RUN_ID,
    )


def _record(env: dict, preview: dict, approval: dict) -> dict:
    return env["service"].record(
        submit_intent_id=env["submit_intent_id"],
        reconciliation_run_id=REVIEW_RUN_ID,
        clearance_fingerprint=preview["clearance_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
    )


def test_signed_full_fill_clearance_atomically_records_fills_and_releases_interlock(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    approval = _approval(env, preview["clearance_fingerprint"])

    cleared = _record(env, preview, approval)
    retry = _record(env, preview, approval)

    assert preview["review_status"] == "ready_for_final_signature", preview["blockers"]
    assert preview["fill_count"] == 2
    assert preview["fill_quantity"] == "100"
    assert cleared["status"] == "cleared"
    assert cleared["interlock_released"] is True
    assert cleared["oms_terminal_status"] == "filled"
    assert cleared["real_fills_recorded"] is True
    assert cleared["production_ledger_mutated"] is False
    assert retry["reused"] is True
    assert env["db"].get_oms_order_sync(env["order"]["order_id"])["status"] == (
        "filled"
    )
    transitions = env["db"].list_oms_transitions_sync(env["order"]["order_id"])
    assert [item["to_status"] for item in transitions][-2:] == ["accepted", "filled"]
    fills = env["db"].list_fills_sync(order_id=env["order"]["order_id"])
    assert len(fills) == 2
    assert sum(float(item["fill_quantity"]) for item in fills) == 100
    assert {item["execution_mode"] for item in fills} == {"controlled_live"}
    assert {item["broker_order_id"] for item in fills} == {"BROKER-CLEARANCE-1"}
    assert env["db"].list_unreconciled_controlled_broker_submit_intents_sync() == []
    clearance_run_id = cleared["clearance_reconciliation_run_id"]
    clearance_run = env["db"].get_execution_reconciliation_run_sync(clearance_run_id)
    clearance_items = env["db"].list_execution_reconciliation_items_sync(
        clearance_run_id
    )
    assert clearance_run["status"] == "clear"
    assert clearance_items[0]["item_status"] == (
        "controlled_submission_reconciliation_cleared"
    )
    assert clearance_items[0]["suggested_action"] == "no_action"
    batch = ExecutionBatchReconciliationService(db=env["db"], clock=lambda: NOW)
    batch_preview = batch.preview(
        batch_id="controlled-clearance-batch-1",
        order_ids=[env["order"]["order_id"]],
        reconciliation_run_id=clearance_run_id,
    )
    assert batch_preview["status"] == "clear", batch_preview["blockers"]
    assert env["db"].get_ledger_entries_sync() == []
    assert "must-not-leak" not in str(cleared)


def test_partial_fill_cannot_clear_or_mutate_any_terminal_state(tmp_path) -> None:
    env = _environment(tmp_path, quantities=(40,))

    preview = _preview(env)

    assert preview["review_ready"] is False
    assert "controlled_submission_clearance_item_not_clearable" in preview["blockers"]
    assert "controlled_submission_clearance_full_fill_required" in preview["blockers"]
    assert env["db"].get_oms_order_sync(env["order"]["order_id"])["status"] == (
        "submitted"
    )
    assert env["db"].list_fills_sync(order_id=env["order"]["order_id"]) == []
    assert len(env["db"].list_unreconciled_controlled_broker_submit_intents_sync()) == 1
    assert env["db"].get_ledger_entries_sync() == []


def test_partial_events_from_different_imports_cannot_be_aggregated(tmp_path) -> None:
    env = _environment(tmp_path, quantities=(40,))
    repository = BrokerEvidenceRepository(Path(env["db"]._path))
    second_statement = _statement(quantities=(60,)).replace(
        "controlled-fill-1",
        "controlled-fill-cross-import",
    )
    repository.save_preview(
        parse_broker_statement_csv(second_statement),
        source_name="second-broker-statement.csv",
    )

    reconciliation = ExecutionReconciliationService(db=env["db"]).run_reconciliation(
        run_date="2026-07-13"
    )
    item = next(
        row
        for row in reconciliation["items"]
        if row["order_id"] == env["order"]["order_id"]
    )
    preview = _preview(env)

    assert item["item_status"] == "controlled_submission_broker_evidence_mismatch"
    assert preview["review_ready"] is False
    assert "controlled_submission_clearance_item_not_clearable" in preview["blockers"]
    assert env["db"].list_fills_sync(order_id=env["order"]["order_id"]) == []
    assert env["db"].get_ledger_entries_sync() == []


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        (
            lambda env: env["account_truth"].update(
                {"captured_at": (NOW - timedelta(seconds=121)).isoformat()}
            ),
            "controlled_submission_clearance_account_truth_stale",
        ),
        (
            lambda env: env["account_truth"].update(
                {"ledger_coverage": {"status": "stale"}}
            ),
            "controlled_submission_clearance_account_truth_ledger_not_covered",
        ),
        (
            lambda env: env["account_truth"].update({"import_run_id": "import_wrong"}),
            "controlled_submission_clearance_account_truth_import_mismatch",
        ),
    ],
)
def test_account_truth_drift_fails_closed_without_fill_or_ledger_mutation(
    tmp_path,
    mutation,
    blocker,
) -> None:
    env = _environment(tmp_path)
    mutation(env)

    preview = _preview(env)

    assert preview["review_ready"] is False
    assert blocker in preview["blockers"]
    assert env["db"].list_fills_sync(order_id=env["order"]["order_id"]) == []
    assert env["db"].get_ledger_entries_sync() == []


def test_superseded_reconciliation_item_invalidates_signed_preview(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    approval = _approval(env, preview["clearance_fingerprint"])
    env["db"].upsert_execution_reconciliation_run_sync(
        run_id="execution-reconciliation:superseding",
        run_date="2026-07-13",
        status="open_items",
        item_count=1,
        open_item_count=1,
        payload={"schema_version": "karkinos.execution_reconciliation.v1"},
        items=[
            {
                "order_id": env["order"]["order_id"],
                "item_status": "controlled_submission_broker_evidence_mismatch",
                "suggested_action": (
                    "enable_kill_switch_and_review_controlled_submission"
                ),
                "detail": "newer mismatch",
                "payload": {},
            }
        ],
    )

    with pytest.raises(ControlledSubmissionReconciliationClearanceRejected) as exc_info:
        _record(env, preview, approval)

    assert "controlled_submission_clearance_review_blocked" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert env["db"].list_fills_sync(order_id=env["order"]["order_id"]) == []
    assert env["db"].get_ledger_entries_sync() == []


def test_wrong_signature_domain_is_rejected_and_audited(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    challenge = env["approvals"].create_challenge(
        operator_id="local-clearance-owner",
        key_id="clearance-key-1",
        action="submit_confirmed_broker_order",
        artifact_type="controlled_broker_submission",
        artifact_fingerprint=preview["clearance_fingerprint"],
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    signature_base64 = base64.b64encode(signature).decode("ascii")
    wrong = env["approvals"].verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature_base64,
    )

    with pytest.raises(ControlledSubmissionReconciliationClearanceRejected) as exc_info:
        env["service"].record(
            submit_intent_id=env["submit_intent_id"],
            reconciliation_run_id=REVIEW_RUN_ID,
            clearance_fingerprint=preview["clearance_fingerprint"],
            operator_approval_id=wrong["approval_id"],
            operator_proof_signature_base64=signature_base64,
            acknowledgement=CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
        )

    assert "controlled_submission_clearance_operator_approval_blocked" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert signature_base64 not in str(exc_info.value.evidence)
    assert env["db"].list_fills_sync(order_id=env["order"]["order_id"]) == []
    assert env["db"].get_ledger_entries_sync() == []


def test_concurrent_exact_clearance_is_atomic_and_idempotent(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    approval = _approval(env, preview["clearance_fingerprint"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: _record(env, preview, approval),
                range(2),
            )
        )

    assert {item["status"] for item in results} == {"cleared"}
    assert sum(1 for item in results if item["reused"]) == 1
    assert len(env["db"].list_fills_sync(order_id=env["order"]["order_id"])) == 2
    transitions = env["db"].list_oms_transitions_sync(env["order"]["order_id"])
    assert [item["to_status"] for item in transitions].count("filled") == 1
    assert (
        len(env["db"].list_controlled_submission_reconciliation_clearances_sync()) == 1
    )
    assert env["db"].get_ledger_entries_sync() == []
