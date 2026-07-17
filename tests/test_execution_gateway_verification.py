from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from server.db import AppDatabase
from server.services.execution_gateway_verification import (
    EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
    ExecutionGatewayVerificationRejected,
    ExecutionGatewayVerificationService,
)

NOW = datetime(2026, 7, 11, 1, 30, tzinfo=timezone.utc)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class FakeExecutionGateway:
    gateway_id = "fixture-execution-1"
    evidence_connector_id = "fixture-readonly-1"
    account_alias = "primary-review"
    account_binding_status = "verified"

    def __init__(self) -> None:
        self.capabilities = {
            "can_cancel_orders": True,
            "can_dry_run_orders": True,
            "can_query_fills": True,
            "can_query_orders": True,
            "can_submit_orders": True,
            "supports_idempotent_client_order_id": True,
        }
        self.health_status = "healthy"
        self.health_captured_at = NOW
        self.health_source_fingerprint = "b" * 64
        self.dry_run_status = "accepted"
        self.dry_run_submitted = False
        self.dry_run_broker_order_id = ""
        self.dry_run_side_effect_count = 0
        self.dry_run_calls = 0
        self.submit_calls = 0
        self.cancel_calls = 0

    def get_health(self) -> dict:
        return {
            "status": self.health_status,
            "captured_at": self.health_captured_at.isoformat(),
            "source_fingerprint": self.health_source_fingerprint,
            "private_session": "must_not_be_returned",
        }

    def dry_run_order(self, order: dict) -> dict:
        self.dry_run_calls += 1
        return {
            "status": self.dry_run_status,
            "order_fingerprint": order["order_fingerprint"],
            "client_order_id": order["client_order_id"],
            "payload_fingerprint": _fingerprint(order),
            "submitted": self.dry_run_submitted,
            "broker_order_id": self.dry_run_broker_order_id,
            "side_effect_count": self.dry_run_side_effect_count,
            "private_payload": "must_not_be_returned",
        }


def _order_contract() -> dict:
    return {
        "symbol": "510300.SH",
        "side": "buy",
        "asset_class": "fund",
        "quantity": "100",
        "order_type": "limit",
        "limit_price": "4",
    }


def _service(tmp_path, gateway: FakeExecutionGateway, current_time: list[datetime]):
    db = AppDatabase(tmp_path / "execution-gateway-verification.db")
    db.init_sync()
    return db, ExecutionGatewayVerificationService(
        db=db,
        gateways=[gateway],
        clock=lambda: current_time[0],
    )


def _preview(service: ExecutionGatewayVerificationService) -> dict:
    return service.preview(
        gateway_id="fixture-execution-1",
        evidence_connector_id="fixture-readonly-1",
        account_alias="primary-review",
        order_id="OMS-1",
        order_fingerprint="a" * 64,
        order_contract=_order_contract(),
    )


def test_gateway_verification_preview_is_ready_and_strictly_non_submitting(
    tmp_path,
) -> None:
    gateway = FakeExecutionGateway()
    db, service = _service(tmp_path, gateway, [NOW])

    preview = _preview(service)

    assert preview["review_status"] == "ready_to_record"
    assert preview["review_ready"] is True
    assert preview["blockers"] == []
    assert preview["capabilities"]["can_submit_orders"] is True
    assert preview["health"]["freshness_status"] == "fresh"
    assert preview["dry_run"]["submitted"] is False
    assert preview["dry_run"]["broker_order_id"] == ""
    assert preview["dry_run"]["side_effect_count"] == 0
    assert preview["runtime_execution_authority"] == "disabled"
    assert preview["broker_submission_enabled"] is False
    assert preview["authorizes_execution"] is False
    assert gateway.submit_calls == 0
    assert gateway.cancel_calls == 0
    assert (
        db.list_events_sync(event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE) == []
    )
    assert "must_not_be_returned" not in json.dumps(preview)


def test_gateway_verification_record_reuses_and_resolves_current_evidence(
    tmp_path,
) -> None:
    gateway = FakeExecutionGateway()
    current_time = [NOW]
    db, service = _service(tmp_path, gateway, current_time)
    preview = _preview(service)

    first = service.record(
        gateway_id="fixture-execution-1",
        evidence_connector_id="fixture-readonly-1",
        account_alias="primary-review",
        order_id="OMS-1",
        order_fingerprint="a" * 64,
        order_contract=_order_contract(),
        verification_fingerprint=preview["verification_fingerprint"],
        acknowledgement=EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    )
    rerun = service.record(
        gateway_id="fixture-execution-1",
        evidence_connector_id="fixture-readonly-1",
        account_alias="primary-review",
        order_id="OMS-1",
        order_fingerprint="a" * 64,
        order_contract=_order_contract(),
        verification_fingerprint=preview["verification_fingerprint"],
        acknowledgement=EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    )
    current_time[0] = NOW + timedelta(seconds=5)
    resolved = service.resolve(preview["verification_fingerprint"])

    assert first["status"] == "recorded_non_submitting_runtime_verification"
    assert first["runtime_gateway_verified"] is True
    assert first["broker_submission_enabled"] is False
    assert rerun["event_id"] == first["event_id"]
    assert rerun["reused"] is True
    assert (
        len(db.list_events_sync(event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE))
        == 1
    )
    assert resolved["status"] == "clear"
    assert resolved["runtime_gateway_verified"] is True
    assert resolved["runtime_verification_status"] == (
        "verified_non_submitting_dry_run"
    )
    assert resolved["order_contract"] == _order_contract()
    assert resolved["authorizes_execution"] is False
    assert gateway.submit_calls == 0
    assert gateway.cancel_calls == 0


def test_gateway_verification_source_drift_and_expiry_fail_closed(tmp_path) -> None:
    gateway = FakeExecutionGateway()
    current_time = [NOW]
    _, service = _service(tmp_path, gateway, current_time)
    preview = _preview(service)
    service.record(
        gateway_id="fixture-execution-1",
        evidence_connector_id="fixture-readonly-1",
        account_alias="primary-review",
        order_id="OMS-1",
        order_fingerprint="a" * 64,
        order_contract=_order_contract(),
        verification_fingerprint=preview["verification_fingerprint"],
        acknowledgement=EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    )

    gateway.health_source_fingerprint = "c" * 64
    drifted = service.resolve(preview["verification_fingerprint"])
    gateway.health_source_fingerprint = "b" * 64
    current_time[0] = NOW + timedelta(seconds=301)
    expired = service.resolve(preview["verification_fingerprint"])

    assert drifted["status"] == "blocked"
    assert drifted["blockers"] == ["verification_source_changed"]
    assert expired["status"] == "blocked"
    assert expired["blockers"] == ["verification_expired"]


def test_gateway_capability_account_and_dry_run_side_effects_fail_closed(
    tmp_path,
) -> None:
    gateway = FakeExecutionGateway()
    gateway.capabilities["supports_idempotent_client_order_id"] = False
    gateway.account_binding_status = "unverified"
    _, service = _service(tmp_path, gateway, [NOW])

    blocked = _preview(service)

    assert (
        "execution_gateway_capability_missing:supports_idempotent_client_order_id"
        in blocked["blockers"]
    )
    assert "connector_account_binding_not_verified" in blocked["blockers"]
    assert blocked["dry_run"]["status"] == "not_run"

    gateway.capabilities["supports_idempotent_client_order_id"] = True
    gateway.account_binding_status = "verified"
    gateway.dry_run_submitted = True
    gateway.dry_run_broker_order_id = "unexpected-broker-order"
    gateway.dry_run_side_effect_count = 1
    unsafe = _preview(service)

    assert "execution_gateway_dry_run_submitted_order" in unsafe["blockers"]
    assert "execution_gateway_dry_run_returned_broker_order_id" in unsafe["blockers"]
    assert "execution_gateway_dry_run_reported_side_effects" in unsafe["blockers"]
    assert unsafe["broker_submission_enabled"] is False


def test_rejected_gateway_verification_is_audited_without_private_details(
    tmp_path,
) -> None:
    gateway = FakeExecutionGateway()
    db, service = _service(tmp_path, gateway, [NOW])
    gateway.health_status = "degraded"
    preview = _preview(service)

    with pytest.raises(ExecutionGatewayVerificationRejected) as exc_info:
        service.record(
            gateway_id="fixture-execution-1",
            evidence_connector_id="fixture-readonly-1",
            account_alias="primary-review",
            order_id="OMS-1",
            order_fingerprint="a" * 64,
            order_contract=_order_contract(),
            verification_fingerprint=preview["verification_fingerprint"],
            acknowledgement=EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
        )

    evidence = exc_info.value.evidence
    assert evidence["status"] == "rejected"
    assert evidence["rejection_reasons"] == ["gateway_verification_blocked"]
    assert evidence["authorizes_execution"] is False
    assert "must_not_be_returned" not in json.dumps(evidence)
    assert (
        len(db.list_events_sync(event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE))
        == 1
    )


def test_gateway_verification_status_defaults_closed_without_registration(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "execution-gateway-verification.db")
    db.init_sync()
    service = ExecutionGatewayVerificationService(db=db, gateways=[], clock=lambda: NOW)

    status = service.get_status()

    assert status["registered_gateway_count"] == 0
    assert status["runtime_gateway_available"] is False
    assert status["production_gateway_registered"] is False
    assert status["runtime_execution_authority"] == "disabled"
    assert status["broker_submission_enabled"] is False
