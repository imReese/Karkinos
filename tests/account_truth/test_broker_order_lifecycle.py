from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRejected,
    BrokerOrderLifecycleEvidenceRepository,
    preview_broker_order_lifecycle_export,
)

NOW = datetime(2026, 7, 13, 4, 0, 0, tzinfo=UTC)


def _export(
    *,
    source_sequence: int = 10,
    captured_at: datetime = NOW,
    status: str = "partially_filled",
    filled_quantity: str = "40",
    cancelled_quantity: str = "0",
    broker_order_id: str = "FIXTURE-ORDER-1",
    client_order_id: str = "KARK-client-order-1",
    account_id: str = "private-fixture-account-001",
) -> dict:
    fills = []
    if filled_quantity != "0":
        fills.append(
            {
                "broker_trade_id": "FIXTURE-TRADE-1",
                "broker_order_id": broker_order_id,
                "client_order_id": client_order_id,
                "symbol": "600519",
                "side": "buy",
                "quantity": filled_quantity,
                "price": "10.5",
                "fee": "1.2",
                "tax": "0",
                "transfer_fee": "0.02",
                "net_amount": "-421.22",
                "filled_at": (captured_at - timedelta(seconds=2)).isoformat(),
            }
        )
    return {
        "schema_version": "karkinos.broker_order_lifecycle_export.v1",
        "provider": "fixture_broker",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "fixture-controlled-gateway-1",
        "account_id": account_id,
        "account_alias": "main-cn-account",
        "captured_at": captured_at.isoformat(),
        "source_sequence": source_sequence,
        "orders": [
            {
                "broker_order_id": broker_order_id,
                "client_order_id": client_order_id,
                "symbol": "600519",
                "side": "buy",
                "status": status,
                "order_quantity": "100",
                "cumulative_filled_quantity": filled_quantity,
                "cancelled_quantity": cancelled_quantity,
                "average_fill_price": "10.5" if filled_quantity != "0" else None,
                "submitted_at": (captured_at - timedelta(seconds=5)).isoformat(),
                "updated_at": (captured_at - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": fills,
    }


def _preview(payload: dict) -> dict:
    return preview_broker_order_lifecycle_export(
        json.dumps(payload),
        source_name="sanitized fixture lifecycle export",
        clock=lambda: NOW,
    )


def _record(repository, preview: dict) -> dict:
    return repository.record(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )


def test_partial_fill_is_persisted_and_resolved_by_both_order_ids(tmp_path) -> None:
    db_path = tmp_path / "lifecycle.db"
    preview = _preview(_export())
    repository = BrokerOrderLifecycleEvidenceRepository(db_path)

    recorded = _record(repository, preview)
    resolved = repository.resolve_order(
        gateway_id="fixture-controlled-gateway-1",
        account_alias="main-cn-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-client-order-1",
    )

    assert preview["validation_status"] == "pass"
    assert preview["ready_to_record"] is True
    assert recorded["validation_status"] == "pass"
    assert recorded["reused"] is False
    assert resolved["status"] == "found"
    assert resolved["order"]["status"] == "partially_filled"
    assert resolved["order"]["cumulative_filled_quantity"] == "40"
    assert resolved["fill_count"] == 1
    assert resolved["does_not_release_submission_interlock"] is True
    assert resolved["does_not_mutate_oms"] is True
    assert resolved["does_not_mutate_production_ledger"] is True

    with sqlite3.connect(db_path) as conn:
        account_ref_hash = conn.execute(
            "SELECT account_ref_hash FROM broker_order_lifecycle_observations"
        ).fetchone()[0]
    assert account_ref_hash != "private-fixture-account-001"
    assert "private-fixture-account-001" not in db_path.read_bytes().decode(
        "utf-8", errors="ignore"
    )


def test_exact_retry_reuses_and_partial_cancel_remains_non_authoritative(
    tmp_path,
) -> None:
    repository = BrokerOrderLifecycleEvidenceRepository(tmp_path / "lifecycle.db")
    partial_preview = _preview(_export())
    first = _record(repository, partial_preview)
    retry = _record(repository, partial_preview)
    cancelled_preview = _preview(
        _export(
            source_sequence=11,
            captured_at=NOW + timedelta(seconds=1),
            status="cancelled",
            filled_quantity="40",
            cancelled_quantity="60",
        )
    )
    cancelled = _record(repository, cancelled_preview)
    resolved = repository.resolve_order(
        gateway_id="fixture-controlled-gateway-1",
        account_alias="main-cn-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-client-order-1",
    )

    assert retry["observation_id"] == first["observation_id"]
    assert retry["reused"] is True
    assert cancelled["validation_status"] == "pass"
    assert resolved["order"]["status"] == "cancelled"
    assert resolved["order"]["cancelled_quantity"] == "60"
    assert resolved["broker_submission_enabled"] is False
    assert resolved["does_not_cancel_broker_order"] is True
    assert resolved["authorizes_execution"] is False


def test_transaction_blocks_sequence_conflict_and_order_identity_drift(
    tmp_path,
) -> None:
    repository = BrokerOrderLifecycleEvidenceRepository(tmp_path / "lifecycle.db")
    _record(repository, _preview(_export()))
    sequence_conflict = _record(
        repository,
        _preview(
            _export(
                source_sequence=10,
                captured_at=NOW + timedelta(seconds=1),
                status="open",
                filled_quantity="0",
            )
        ),
    )
    identity_drift = _record(
        repository,
        _preview(
            _export(
                source_sequence=11,
                captured_at=NOW + timedelta(seconds=2),
                client_order_id="KARK-drifted-client-order",
            )
        ),
    )
    resolved = repository.resolve_order(
        gateway_id="fixture-controlled-gateway-1",
        account_alias="main-cn-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-client-order-1",
    )

    assert sequence_conflict["validation_status"] == "blocked"
    assert "broker_order_lifecycle_source_sequence_evidence_conflict" in (
        sequence_conflict["blockers"]
    )
    assert identity_drift["validation_status"] == "blocked"
    assert "broker_order_lifecycle_order_identity_drift" in identity_drift["blockers"]
    assert resolved["status"] == "blocked"
    assert "broker_order_lifecycle_order_identity_drift" in resolved["blockers"]


def test_transaction_blocks_order_contract_drift_for_same_identities(tmp_path) -> None:
    repository = BrokerOrderLifecycleEvidenceRepository(tmp_path / "lifecycle.db")
    _record(repository, _preview(_export()))
    changed = _export(
        source_sequence=11,
        captured_at=NOW + timedelta(seconds=1),
    )
    changed["orders"][0]["symbol"] = "600000"
    changed["fills"][0]["symbol"] = "600000"

    recorded = _record(repository, _preview(changed))

    assert recorded["validation_status"] == "blocked"
    assert "broker_order_lifecycle_order_contract_drift" in recorded["blockers"]
    assert recorded["does_not_release_submission_interlock"] is True


def test_transaction_blocks_provider_change_for_same_gateway_scope(tmp_path) -> None:
    repository = BrokerOrderLifecycleEvidenceRepository(tmp_path / "lifecycle.db")
    _record(repository, _preview(_export()))
    changed = _export(
        source_sequence=11,
        captured_at=NOW + timedelta(seconds=1),
    )
    changed["provider"] = "different_fixture_provider"

    recorded = _record(repository, _preview(changed))
    resolved = repository.resolve_order(
        gateway_id="fixture-controlled-gateway-1",
        account_alias="main-cn-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-client-order-1",
    )

    assert recorded["validation_status"] == "blocked"
    assert "broker_order_lifecycle_provider_changed" in recorded["blockers"]
    assert resolved["status"] == "blocked"
    assert resolved["provider_contacted"] is False


def test_preview_blocks_credentials_and_inconsistent_fill_totals() -> None:
    credential_payload = _export()
    credential_payload["broker_password"] = "must-never-be-persisted"
    credential_preview = _preview(credential_payload)
    mismatch_payload = _export()
    mismatch_payload["orders"][0]["cumulative_filled_quantity"] = "50"
    mismatch_preview = _preview(mismatch_payload)

    assert credential_preview["validation_status"] == "blocked"
    assert "broker_order_lifecycle_credentials_not_allowed" in (
        credential_preview["blockers"]
    )
    assert mismatch_preview["validation_status"] == "blocked"
    assert "broker_order_lifecycle_fill_sum_mismatch" in mismatch_preview["blockers"]
    assert mismatch_preview["provider_contacted"] is False
    assert mismatch_preview["broker_submission_enabled"] is False


def test_read_only_resolution_does_not_create_unconfigured_database(tmp_path) -> None:
    db_path = tmp_path / "absent.db"
    repository = BrokerOrderLifecycleEvidenceRepository(db_path, ensure_schema=False)

    resolved = repository.resolve_order(
        gateway_id="fixture-controlled-gateway-1",
        account_alias="main-cn-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-client-order-1",
    )

    assert resolved["status"] == "not_configured"
    assert resolved["provider_contacted"] is False
    assert db_path.exists() is False


def test_record_rejects_in_memory_preview_drift_and_sanitizes_local_path(
    tmp_path,
) -> None:
    preview = preview_broker_order_lifecycle_export(
        json.dumps(_export()),
        source_name="/private/operator/broker-export.json",
        clock=lambda: NOW,
    )
    drifted = deepcopy(preview)
    drifted["order"]["status"] = "filled"
    repository = BrokerOrderLifecycleEvidenceRepository(tmp_path / "lifecycle.db")

    with pytest.raises(BrokerOrderLifecycleEvidenceRejected) as exc_info:
        _record(repository, drifted)

    assert "broker_order_lifecycle_preview_fingerprint_drift" in (
        exc_info.value.evidence["blockers"]
    )
    assert preview["source_name"] == "broker local exact-order lifecycle export"
    assert repository.list_observations() == []
