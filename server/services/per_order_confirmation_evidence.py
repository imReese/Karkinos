"""Fail-closed evidence bindings for per-order confirmation dossiers."""

from __future__ import annotations

from typing import Any, Callable

from server.services import per_order_confirmation_values as values
from server.services.broker_adapter_readiness import (
    BROKER_ADAPTER_READINESS_SCHEMA_VERSION,
    build_broker_adapter_readiness,
)


def read_broker_adapter_readiness(db: Any) -> dict[str, Any]:
    """Read the canonical persisted-only projection and fail closed on defects."""

    try:
        readiness = build_broker_adapter_readiness(db)
    except Exception:  # Defensive boundary: an unreadable gate must never pass.
        return {}
    return readiness if isinstance(readiness, dict) else {}


def resolve_broker_adapter_release_binding(
    readiness: dict[str, Any],
    *,
    expected_collector_id: str,
    expected_gateway_id: str,
    expected_account_alias: str,
) -> tuple[dict[str, Any], list[str]]:
    """Bind the newest exact-scope release that remains safe for observation."""

    blockers: list[str] = []
    expected_scope = {
        "collector_id": str(expected_collector_id or ""),
        "gateway_id": str(expected_gateway_id or ""),
        "account_alias": str(expected_account_alias or ""),
    }
    for field, value in expected_scope.items():
        if not value:
            blockers.append(f"broker_adapter_release_expected_{field}_missing")

    if (
        str(readiness.get("schema_version") or "")
        != BROKER_ADAPTER_READINESS_SCHEMA_VERSION
    ):
        blockers.append("broker_adapter_readiness_schema_invalid")
    if str(readiness.get("evidence_store_status") or "") != "available":
        blockers.append("broker_adapter_readiness_evidence_store_unavailable")

    required_safety = {
        "persisted_facts_only": True,
        "provider_contacted": False,
        "adapter_registered": False,
        "default_registered": False,
        "broker_submission_enabled": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "authorizes_execution": False,
    }
    source_safety = {field: readiness.get(field) for field in required_safety}
    for field, expected in required_safety.items():
        if readiness.get(field) is not expected:
            blockers.append(f"broker_adapter_readiness_boundary_invalid:{field}")

    releases_value = readiness.get("releases")
    releases = releases_value if isinstance(releases_value, list) else []
    if not isinstance(releases_value, list):
        blockers.append("broker_adapter_readiness_releases_invalid")
    if any(not isinstance(item, dict) for item in releases):
        blockers.append("broker_adapter_readiness_release_item_invalid")
    exact_matches = [
        item
        for item in releases
        if isinstance(item, dict)
        and str(item.get("collector_id") or "") == expected_scope["collector_id"]
        and str(item.get("gateway_id") or "") == expected_scope["gateway_id"]
        and str(item.get("account_alias") or "") == expected_scope["account_alias"]
    ]
    selected = exact_matches[0] if exact_matches else None
    if selected is None:
        blockers.append("broker_adapter_release_scope_not_found")

    release: dict[str, Any] | None = None
    if selected is not None:
        release_blockers_value = selected.get("blockers")
        release_blockers = (
            [str(item) for item in release_blockers_value]
            if isinstance(release_blockers_value, list)
            else []
        )
        if not isinstance(release_blockers_value, list):
            blockers.append("broker_adapter_release_blockers_invalid")
        elif release_blockers:
            blockers.append("broker_adapter_release_has_blockers")
        if not str(selected.get("release_evidence_ref") or ""):
            blockers.append("broker_adapter_release_evidence_ref_invalid")
        if not values.FINGERPRINT_PATTERN.fullmatch(
            str(selected.get("manifest_fingerprint") or "")
        ):
            blockers.append("broker_adapter_release_manifest_fingerprint_invalid")
        if str(selected.get("manifest_status") or "") != "clear":
            blockers.append("broker_adapter_release_manifest_not_clear")
        if not str(selected.get("provider") or ""):
            blockers.append("broker_adapter_release_provider_missing")
        if str(selected.get("review_status") or "") != "accepted":
            blockers.append("broker_adapter_release_review_not_accepted")
        if not str(selected.get("review_id") or ""):
            blockers.append("broker_adapter_release_review_id_missing")
        if str(selected.get("conformance_status") or "") != "clear":
            blockers.append("broker_adapter_release_conformance_not_clear")
        if not str(selected.get("conformance_run_id") or ""):
            blockers.append("broker_adapter_release_conformance_run_id_missing")
        if not values.FINGERPRINT_PATTERN.fullmatch(
            str(selected.get("conformance_report_fingerprint") or "")
        ):
            blockers.append("broker_adapter_release_conformance_fingerprint_invalid")
        if str(selected.get("collector_status") or "") not in {
            "recorded",
            "duplicate",
        }:
            blockers.append("broker_adapter_release_collector_not_recorded")
        if not str(selected.get("collector_run_id") or ""):
            blockers.append("broker_adapter_release_collector_run_id_missing")
        if not str(selected.get("collector_updated_at") or ""):
            blockers.append("broker_adapter_release_collector_updated_at_missing")
        if str(selected.get("status") or "") != "observing_readonly":
            blockers.append("broker_adapter_release_not_observing_readonly")
        if selected.get("does_not_authorize_provider_activation") is not True:
            blockers.append("broker_adapter_release_activation_boundary_invalid")
        release = {
            "release_evidence_ref": str(selected.get("release_evidence_ref") or ""),
            "manifest_fingerprint": str(selected.get("manifest_fingerprint") or ""),
            "manifest_status": str(selected.get("manifest_status") or ""),
            "provider": str(selected.get("provider") or ""),
            "gateway_id": str(selected.get("gateway_id") or ""),
            "account_alias": str(selected.get("account_alias") or ""),
            "collector_id": str(selected.get("collector_id") or ""),
            "collection_modes": [
                str(item) for item in selected.get("collection_modes") or []
            ],
            "review_status": str(selected.get("review_status") or ""),
            "review_id": str(selected.get("review_id") or ""),
            "reviewed_at": selected.get("reviewed_at"),
            "conformance_status": str(selected.get("conformance_status") or ""),
            "conformance_run_id": str(selected.get("conformance_run_id") or ""),
            "conformance_report_fingerprint": str(
                selected.get("conformance_report_fingerprint") or ""
            ),
            "collector_status": str(selected.get("collector_status") or ""),
            "collector_run_id": str(selected.get("collector_run_id") or ""),
            "collector_updated_at": selected.get("collector_updated_at"),
            "status": str(selected.get("status") or ""),
            "release_blockers": release_blockers,
            "does_not_authorize_provider_activation": bool(
                selected.get("does_not_authorize_provider_activation")
            ),
        }

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": "karkinos.per_order_broker_adapter_release_binding.v1",
        "status": "pass" if not blockers else "blocked",
        "source_schema_version": str(readiness.get("schema_version") or ""),
        "expected_scope": expected_scope,
        "matching_release_count": len(exact_matches),
        "release": release,
        "source_safety": source_safety,
        "blockers": blockers,
        "persisted_evidence_only": readiness.get("persisted_facts_only") is True,
        "provider_contact_performed": bool(readiness.get("provider_contacted")),
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }, blockers


def resolve_signed_soak_promotion(
    provider: Callable[[str], dict[str, Any]] | None,
    *,
    connector_id: str,
) -> dict[str, Any]:
    if not connector_id:
        return values.missing_signed_soak_promotion(["connector_id_missing"])
    if provider is None:
        return values.missing_signed_soak_promotion(
            ["signed_promotion_evidence_provider_unavailable"]
        )
    try:
        raw = provider(connector_id) or {}
    except Exception:
        return values.missing_signed_soak_promotion(
            ["signed_promotion_evidence_provider_failed"]
        )
    if not isinstance(raw, dict):
        return values.missing_signed_soak_promotion(
            ["signed_promotion_evidence_invalid"]
        )

    operational = (
        raw.get("operational_evidence")
        if isinstance(raw.get("operational_evidence"), dict)
        else {}
    )
    account_truth = (
        raw.get("account_truth_evidence")
        if isinstance(raw.get("account_truth_evidence"), dict)
        else {}
    )
    acceptance = (
        raw.get("acceptance") if isinstance(raw.get("acceptance"), dict) else {}
    )
    dossier_fingerprint = str(raw.get("dossier_fingerprint") or "")
    operational_source_fingerprint = str(operational.get("source_fingerprint") or "")
    account_truth_source_fingerprint = str(
        account_truth.get("source_fingerprint") or ""
    )
    acceptance_id = str(acceptance.get("acceptance_id") or "")
    blockers = [str(item) for item in raw.get("promotion_blockers") or []]
    if str(raw.get("connector_id") or "") != connector_id:
        blockers.append("signed_promotion_connector_mismatch")
    if operational.get("status") != "clear":
        blockers.append("signed_promotion_operational_evidence_not_clear")
    if int(operational.get("selected_trading_day_count") or 0) != 20:
        blockers.append("signed_promotion_trading_day_count_invalid")
    if account_truth.get("status") != "clear":
        blockers.append("signed_promotion_account_truth_not_clear")
    for name, fingerprint in (
        ("dossier", dossier_fingerprint),
        ("operational_source", operational_source_fingerprint),
        ("account_truth_source", account_truth_source_fingerprint),
    ):
        if not values.FINGERPRINT_PATTERN.fullmatch(fingerprint):
            blockers.append(f"signed_promotion_{name}_fingerprint_invalid")
    if acceptance.get("status") != "recorded_verified_owner_acceptance":
        blockers.append("signed_promotion_owner_acceptance_missing")
    if not values.FINGERPRINT_PATTERN.fullmatch(acceptance_id):
        blockers.append("signed_promotion_acceptance_id_invalid")
    if acceptance.get("operator_identity_verified") is not True:
        blockers.append("signed_promotion_owner_identity_unverified")
    if acceptance.get("authorizes_execution") is not False:
        blockers.append("signed_promotion_acceptance_authority_boundary_invalid")
    if raw.get("owner_acceptance_recorded") is not True:
        blockers.append("signed_promotion_owner_acceptance_flag_invalid")
    if raw.get("account_truth_reconciliation_linked") is not True:
        blockers.append("signed_promotion_account_truth_linkage_flag_invalid")
    if raw.get("promotion_ready") is not True:
        blockers.append("signed_promotion_not_ready")
    if raw.get("authorizes_execution") is not False:
        blockers.append("signed_promotion_authority_boundary_invalid")
    if raw.get("broker_submission_enabled") is not False:
        blockers.append("signed_promotion_submission_boundary_invalid")

    unique_blockers = list(dict.fromkeys(blockers))
    ready = not unique_blockers
    return {
        "schema_version": "karkinos.per_order_broker_soak_promotion_binding.v1",
        "status": "ready" if ready else "blocked",
        "connector_id": connector_id,
        "dossier_fingerprint": dossier_fingerprint,
        "operational_source_fingerprint": operational_source_fingerprint,
        "account_truth_source_fingerprint": account_truth_source_fingerprint,
        "acceptance_id": acceptance_id,
        "acceptance_recorded_at": str(acceptance.get("recorded_at") or ""),
        "operator_label": str(acceptance.get("operator_label") or ""),
        "promotion_ready": ready,
        "owner_acceptance_recorded": ready,
        "account_truth_reconciliation_linked": ready,
        "blockers": unique_blockers,
        "authorizes_execution": False,
        "broker_submission_enabled": False,
    }
