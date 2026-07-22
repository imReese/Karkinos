from __future__ import annotations

from dataclasses import replace

import pytest

from server.services.capital_authorization_audit import (
    CapitalAuthorizationAuditService,
)
from server.services.current_per_order_dossier import (
    CurrentPerOrderDossierService,
    resolve_persisted_execution_gateway_verification,
)
from server.services.execution_gateway_verification import (
    EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
    EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
    EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
)
from server.services.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    PER_ORDER_CONFIRMATION_EVENT_TYPE,
    PerOrderConfirmationService,
)
from tests.test_per_order_confirmation import (
    NOW,
    _clear_gateway_verification,
    _operator_approval,
    _ready_environment,
)

pytestmark = pytest.mark.trading_safety


def _persisted_current_service(env: dict) -> CurrentPerOrderDossierService:
    verification = {
        **_clear_gateway_verification(env["order"]),
        "status": "recorded_non_submitting_runtime_verification",
    }
    env["db"].append_event_sync(
        event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
        timestamp=NOW.isoformat(),
        entity_type=EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
        entity_id=str(verification["verification_id"]),
        source=EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
        source_ref=str(verification["verification_fingerprint"]),
        payload=verification,
    )
    dossier_service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        execution_gateway_verification_provider=(
            lambda fingerprint: resolve_persisted_execution_gateway_verification(
                env["db"],
                fingerprint,
                clock=lambda: NOW,
            )
        ),
        account_truth_evidence_provider=env["account_truth_evidence_provider"],
        clock=lambda: NOW,
    )
    return CurrentPerOrderDossierService(
        db=env["db"],
        dossier_service=dossier_service,
    )


def test_current_dossier_resolves_exact_persisted_evidence_without_manual_refs(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    service = _persisted_current_service(env)

    preview = service.preview_current(env["order"]["order_id"])
    candidates = service.list_candidates(limit=10)
    persisted_verification = resolve_persisted_execution_gateway_verification(
        env["db"],
        env["gateway_verification_fingerprint"],
        clock=lambda: NOW,
    )

    resolution = preview["evidence_resolution"]
    assert resolution["status"] == "resolved"
    assert (
        resolution["capital_evaluation_input_fingerprint"]
        == env["evaluation"]["input_fingerprint"]
    )
    assert (
        resolution["prior_batch_reconciliation_fingerprint"]
        == env["batch"]["batch_reconciliation_fingerprint"]
    )
    assert (
        resolution["execution_gateway_verification_fingerprint"]
        == env["gateway_verification_fingerprint"]
    )
    assert preview["review_status"] == "review_ready_non_submitting"
    assert preview["current_evidence_resolved"] is True
    assert preview["provider_contact_performed"] is False
    assert preview["runtime_connector_query_performed"] is False
    assert preview["does_not_mutate_oms"] is True
    assert preview["does_not_mutate_production_ledger"] is True
    assert preview["does_not_change_capital_authority"] is True
    assert preview["broker_submission_enabled"] is False
    assert preview["broker_cancel_enabled"] is False
    assert preview["authorizes_execution"] is False
    assert persisted_verification["status"] == "clear"
    assert persisted_verification["persisted_evidence_only"] is True
    assert persisted_verification["provider_contact_performed"] is False
    assert persisted_verification["runtime_gateway_call_performed"] is False
    assert candidates["candidate_count"] == 1
    assert candidates["candidates"][0]["order_id"] == env["order"]["order_id"]
    assert candidates["candidates"][0]["review_ready"] is True
    assert candidates["selection_contract"] == (
        "canonical_manually_confirmed_oms_orders_only"
    )


def test_current_dossier_uses_newest_matching_evaluation_and_never_falls_back(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    blocked_evaluation = CapitalAuthorizationAuditService(
        db=env["db"],
        clock=lambda: NOW,
    ).record_evaluation(
        policy=replace(env["capital_policy"], enabled=False),
        context=env["capital_context"],
    )
    service = _persisted_current_service(env)

    preview = service.preview_current(env["order"]["order_id"])

    assert (
        preview["evidence_resolution"]["capital_evaluation_input_fingerprint"]
        == blocked_evaluation["input_fingerprint"]
    )
    assert (
        preview["capital_evaluation"]["input_fingerprint"]
        == blocked_evaluation["input_fingerprint"]
    )
    assert "capital_evaluation_not_allowed" in preview["review_blockers"]
    assert preview["review_ready"] is False
    assert preview["authorizes_execution"] is False


def test_current_dossier_rejects_ambiguous_gateway_reference_fail_closed(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    ambiguous_context = replace(
        env["capital_context"],
        evidence_refs=(
            *env["capital_context"].evidence_refs,
            f"execution_gateway_verification:{'9' * 64}",
        ),
    )
    ambiguous_evaluation = CapitalAuthorizationAuditService(
        db=env["db"],
        clock=lambda: NOW,
    ).record_evaluation(
        policy=env["capital_policy"],
        context=ambiguous_context,
    )
    service = _persisted_current_service(env)

    preview = service.preview_current(env["order"]["order_id"])

    assert (
        preview["evidence_resolution"]["capital_evaluation_input_fingerprint"]
        == ambiguous_evaluation["input_fingerprint"]
    )
    assert (
        preview["evidence_resolution"]["execution_gateway_verification_fingerprint"]
        == ""
    )
    assert (
        "current_execution_gateway_verification_ref_ambiguous"
        in preview["review_blockers"]
    )
    assert preview["current_evidence_resolved"] is False
    assert preview["review_ready"] is False
    assert preview["broker_submission_enabled"] is False


def test_current_confirmation_rechecks_resolution_and_records_one_non_authorizing_fact(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    service = _persisted_current_service(env)
    order_id = env["order"]["order_id"]
    oms_before = env["db"].get_oms_order_sync(order_id)
    preview = service.preview_current(order_id)
    approval = _operator_approval(env, preview["dossier_fingerprint"])

    first = service.record_current_confirmation(
        order_id,
        dossier_fingerprint=preview["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    )
    replay = service.record_current_confirmation(
        order_id,
        dossier_fingerprint=preview["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    )

    assert first["status"] == "recorded_verified_identity"
    assert first["authorizes_execution"] is False
    assert first["broker_submission_enabled"] is False
    assert replay["event_id"] == first["event_id"]
    assert replay["reused"] is True
    assert env["db"].get_oms_order_sync(order_id) == oms_before
    assert (
        len(env["db"].list_events_sync(event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE))
        == 1
    )
