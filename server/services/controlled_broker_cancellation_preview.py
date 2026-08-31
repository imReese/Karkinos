"""Read-only preview workflows for exact broker cancellation and recovery."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from server.contracts.controlled_broker_cancellation import (
    CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS,
    CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION,
    CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION,
    CONTROLLED_BROKER_CANCELLATION_STATUS_SCHEMA_VERSION,
    FINGERPRINT_PATTERN,
    ID_PATTERN,
    cancellation_aware_utc,
    cancellation_fingerprint,
    cancellation_mapping,
)
from server.projections.controlled_broker_cancellation import (
    controlled_broker_cancellation_safety_flags,
)
from server.services.controlled_broker_cancellation_policy import (
    controlled_broker_cancellation_capabilities,
    controlled_broker_cancellation_gateway_health,
)

GatewayResolver = Callable[[str], tuple[Any | None, list[str]]]
ReleaseResolver = Callable[..., dict[str, Any]]


def build_controlled_broker_cancellation_status(
    *,
    gateways: list[Any] | tuple[Any, ...],
    release_evidence_provider: Callable[[str], dict[str, Any]] | None,
    trusted_operator_identities: list[Any] | tuple[Any, ...],
    store: Any | None,
) -> dict[str, Any]:
    """Build the default-closed capability status without initializing schema."""

    gateway_ids = [
        str(getattr(item, "gateway_id", "") or "")
        for item in gateways
        if str(getattr(item, "gateway_id", "") or "")
    ]
    duplicates = sorted(
        item for item in set(gateway_ids) if gateway_ids.count(item) > 1
    )
    ready = bool(
        gateway_ids
        and not duplicates
        and callable(release_evidence_provider)
        and trusted_operator_identities
        and store is not None
    )
    return {
        "schema_version": CONTROLLED_BROKER_CANCELLATION_STATUS_SCHEMA_VERSION,
        "contract_status": (
            "signed_exact_cancellation_available"
            if ready
            else "disabled_waiting_for_explicit_write_gateway_and_release_evidence"
        ),
        "registered_gateway_ids": sorted(set(gateway_ids)),
        "duplicate_gateway_ids": duplicates,
        "release_evidence_provider_configured": callable(release_evidence_provider),
        "trusted_operator_signature_configured": bool(trusted_operator_identities),
        "audit_store_configured": store is not None,
        "audit_schema_available": bool(store is not None and store.schema_available()),
        "default_broker_cancellation_enabled": False,
        "automatic_cancellation_enabled": False,
        "strategy_direct_cancellation_enabled": False,
        "ai_direct_cancellation_enabled": False,
        "cancellation_retry_enabled": False,
        "query_only_recovery_enabled": True,
        "minimum_query_wait_seconds": (
            CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS
        ),
        "kill_switch_behavior": (
            "does_not_block_separately_signed_risk_reducing_cancellation"
        ),
        "safety": controlled_broker_cancellation_safety_flags(),
    }


def build_controlled_broker_cancellation_preview(
    *,
    db: Any,
    ticket_service: Any,
    gateway_resolver: GatewayResolver,
    release_resolver: ReleaseResolver,
    trusted_operator_identities: list[Any] | tuple[Any, ...],
    store: Any | None,
    clock: Callable[[], datetime],
    submit_intent_id: str,
) -> dict[str, Any]:
    """Bind current persisted order evidence to one exact cancel fingerprint."""

    now = cancellation_aware_utc(clock())
    normalized = str(submit_intent_id or "").strip().lower()
    blockers: list[str] = []
    if not FINGERPRINT_PATTERN.fullmatch(normalized):
        blockers.append("controlled_broker_cancel_submit_intent_id_invalid")

    try:
        ticket = ticket_service.preview(submit_intent_id=normalized)
    except Exception:
        ticket = {
            "ready": False,
            "blockers": ["controlled_broker_cancel_ticket_source_failed"],
        }
    blockers.extend(str(item) for item in ticket.get("blockers") or [])
    intent = (
        db.get_controlled_broker_submit_intent_sync(normalized)
        if FINGERPRINT_PATTERN.fullmatch(normalized)
        else None
    ) or {}
    if not intent:
        blockers.append("controlled_broker_cancel_submit_intent_not_found")

    identity = cancellation_mapping(ticket.get("identity"))
    gateway_id = str(identity.get("gateway_id") or "")
    account_alias = str(identity.get("account_alias") or "")
    gateway, gateway_blockers = gateway_resolver(gateway_id)
    blockers.extend(gateway_blockers)
    capabilities, capability_blockers = controlled_broker_cancellation_capabilities(
        gateway
    )
    blockers.extend(capability_blockers)
    health, health_blockers = controlled_broker_cancellation_gateway_health(
        gateway,
        now=now,
    )
    blockers.extend(health_blockers)

    release_evidence_id = str(intent.get("release_evidence_id") or "")
    release = release_resolver(
        release_evidence_id,
        expected_gateway_id=gateway_id,
        expected_account_alias=account_alias,
        now=now,
    )
    blockers.extend(str(item) for item in release.get("blockers") or [])
    operator_id = str(intent.get("operator_id") or "")
    if not ID_PATTERN.fullmatch(operator_id):
        blockers.append("controlled_broker_cancel_operator_identity_invalid")
    if not trusted_operator_identities:
        blockers.append("controlled_broker_cancel_operator_signature_unconfigured")
    if store is None:
        blockers.append("controlled_broker_cancel_audit_store_unavailable")

    cancel_core = {
        "schema_version": CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION,
        "action": "cancel_exact_controlled_broker_order",
        "submit_intent_id": normalized,
        "submit_fingerprint": str(intent.get("submit_fingerprint") or ""),
        "ticket_fingerprint": str(ticket.get("ticket_fingerprint") or ""),
        "order_id": str(ticket.get("order_id") or ""),
        "order_fingerprint": str(ticket.get("order_fingerprint") or ""),
        "provider": str(ticket.get("provider") or ""),
        "identity": identity,
        "order": cancellation_mapping(ticket.get("order")),
        "lifecycle_evidence": cancellation_mapping(ticket.get("lifecycle_evidence")),
        "release_evidence_id": release_evidence_id,
        "release_evidence_fingerprint": str(release.get("evidence_fingerprint") or ""),
        "gateway_health_source_fingerprint": str(
            health.get("source_fingerprint") or ""
        ),
        "operator_id": operator_id,
    }
    cancel_fingerprint = cancellation_fingerprint(cancel_core)
    cancel_command_id = cancellation_fingerprint(
        {
            "domain": "karkinos.controlled_broker_cancellation.command_id.v1",
            "cancel_fingerprint": cancel_fingerprint,
        }
    )
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        **cancel_core,
        "cancel_command_id": cancel_command_id,
        "cancel_fingerprint": cancel_fingerprint,
        "generated_at": now.isoformat(),
        "status": "ready_for_final_signature" if not unique_blockers else "blocked",
        "ready": not unique_blockers,
        "blockers": unique_blockers,
        "gateway_capabilities": capabilities,
        "gateway_health": health,
        "release_evidence": release,
        "required_operator_approval": {
            "action": "cancel_exact_controlled_broker_order",
            "artifact_type": "controlled_broker_cancellation",
            "artifact_fingerprint": cancel_fingerprint,
        },
        "required_acknowledgement": CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
        "broker_cancel_performed": False,
        "cancellation_proven": False,
        "safety": controlled_broker_cancellation_safety_flags(),
        "limitations": [
            "Preview reads persisted lifecycle evidence and cached gateway health only.",
            "A gateway response is audit telemetry, not canonical lifecycle or Account Truth.",
            "Only newer explicitly ingested lifecycle evidence can prove cancellation.",
            "The kill switch blocks new submissions but does not silently create cancellation authority.",
        ],
    }


def build_controlled_broker_cancellation_recovery_preview(
    *,
    db: Any,
    ticket_service: Any,
    gateway_resolver: GatewayResolver,
    release_resolver: ReleaseResolver,
    trusted_operator_identities: list[Any] | tuple[Any, ...],
    store: Any | None,
    clock: Callable[[], datetime],
    cancel_command_id: str,
) -> dict[str, Any]:
    """Bind one query-only recovery claim to the persisted cancel command."""

    now = cancellation_aware_utc(clock())
    normalized = str(cancel_command_id or "").strip().lower()
    blockers: list[str] = []
    if not FINGERPRINT_PATTERN.fullmatch(normalized):
        blockers.append("controlled_broker_cancel_command_id_invalid")
    command = store.get(normalized) if store is not None else None
    if command is None:
        blockers.append("controlled_broker_cancel_recovery_command_not_found")
        command = {}
    source_preview = (
        build_controlled_broker_cancellation_preview(
            db=db,
            ticket_service=ticket_service,
            gateway_resolver=gateway_resolver,
            release_resolver=release_resolver,
            trusted_operator_identities=trusted_operator_identities,
            store=store,
            clock=clock,
            submit_intent_id=str(command.get("submit_intent_id") or ""),
        )
        if command
        else {}
    )
    blockers.extend(str(item) for item in source_preview.get("blockers") or [])
    if command and str(source_preview.get("cancel_fingerprint") or "") != str(
        command.get("cancel_fingerprint") or ""
    ):
        blockers.append("controlled_broker_cancel_recovery_source_drift")
    previous_epoch_ms = max(
        int(command.get("prepared_at_epoch_ms") or 0),
        int(command.get("last_query_at_epoch_ms") or 0),
    )
    elapsed_seconds = max(0, int(now.timestamp()) - previous_epoch_ms // 1000)
    wait_remaining = max(
        0,
        CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS - elapsed_seconds,
    )
    if command and wait_remaining:
        blockers.append("controlled_broker_cancel_recovery_query_wait_required")
    gateway, gateway_blockers = gateway_resolver(str(command.get("gateway_id") or ""))
    blockers.extend(gateway_blockers)
    capabilities, capability_blockers = controlled_broker_cancellation_capabilities(
        gateway
    )
    blockers.extend(capability_blockers)
    health, health_blockers = controlled_broker_cancellation_gateway_health(
        gateway,
        now=now,
    )
    blockers.extend(health_blockers)
    release = release_resolver(
        str(command.get("release_evidence_id") or ""),
        expected_gateway_id=str(command.get("gateway_id") or ""),
        expected_account_alias=str(command.get("account_alias") or ""),
        now=now,
    )
    blockers.extend(str(item) for item in release.get("blockers") or [])
    query_sequence = int(command.get("query_count") or 0) + 1
    recovery_core = {
        "schema_version": CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION,
        "action": "query_exact_broker_cancellation_outcome",
        "cancel_command_id": normalized,
        "cancel_fingerprint": str(command.get("cancel_fingerprint") or ""),
        "submit_intent_id": str(command.get("submit_intent_id") or ""),
        "order_id": str(command.get("order_id") or ""),
        "gateway_id": str(command.get("gateway_id") or ""),
        "account_alias": str(command.get("account_alias") or ""),
        "broker_order_id": str(command.get("broker_order_id") or ""),
        "client_order_id": str(command.get("client_order_id") or ""),
        "lifecycle_evidence_fingerprint": str(
            cancellation_mapping(source_preview.get("lifecycle_evidence")).get(
                "evidence_fingerprint"
            )
            or ""
        ),
        "release_evidence_fingerprint": str(release.get("evidence_fingerprint") or ""),
        "gateway_health_source_fingerprint": str(
            health.get("source_fingerprint") or ""
        ),
        "operator_id": str(command.get("operator_id") or ""),
        "query_sequence": query_sequence,
    }
    recovery_fingerprint = cancellation_fingerprint(recovery_core)
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        **recovery_core,
        "recovery_fingerprint": recovery_fingerprint,
        "generated_at": now.isoformat(),
        "status": "ready_for_query_signature" if not unique_blockers else "blocked",
        "ready": not unique_blockers,
        "blockers": unique_blockers,
        "recovery_wait_remaining_seconds": wait_remaining,
        "gateway_capabilities": capabilities,
        "gateway_health": health,
        "release_evidence": release,
        "source_preview": source_preview,
        "required_operator_approval": {
            "action": "query_exact_broker_cancellation_outcome",
            "artifact_type": "controlled_broker_cancellation_recovery",
            "artifact_fingerprint": recovery_fingerprint,
        },
        "required_acknowledgement": (
            CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT
        ),
        "query_only": True,
        "recancel_enabled": False,
        "cancellation_proven": False,
        "safety": controlled_broker_cancellation_safety_flags(),
    }
