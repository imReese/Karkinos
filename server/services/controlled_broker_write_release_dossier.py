"""Evidence-source assembly for controlled broker write-release dossiers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from server.contracts.controlled_broker_write_release import (
    CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION,
    CONTROLLED_BROKER_WRITE_RELEASE_FINGERPRINT_PATTERN,
    CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN,
)
from server.services.controlled_broker_write_release_policy import (
    aware_utc,
    blocked_source,
    canonical_json,
    fingerprint,
    mapping,
    normalize_owner_review_refs,
    normalize_release_window,
)


class ControlledBrokerWriteReleaseDossierBuilder:
    """Build one deterministic dossier from persisted, non-authorizing evidence."""

    def __init__(
        self,
        *,
        db: Any,
        db_path: Path | None,
        soak_promotion_provider_factory: Callable[
            [], Callable[[str], dict[str, Any]] | None
        ],
        clock: Callable[[], datetime],
        manifest_previewer: Callable[..., dict[str, Any]],
        conformance_repository_factory: Callable[[Path], Any],
        readonly_readiness_provider: Callable[[Any], dict[str, Any]],
    ) -> None:
        self._db = db
        self._path = db_path
        self._soak_promotion_provider_factory = soak_promotion_provider_factory
        self._clock = clock
        self._manifest_previewer = manifest_previewer
        self._conformance_repository_factory = conformance_repository_factory
        self._readonly_readiness_provider = readonly_readiness_provider

    def build(
        self,
        *,
        execution_edge_manifest: Mapping[str, Any],
        readonly_release_evidence_ref: str,
        soak_acceptance_id: str,
        effective_at: str,
        expires_at: str,
        owner_review_refs: Mapping[str, Any],
        issuance: bool,
    ) -> dict[str, Any]:
        now = aware_utc(self._clock())
        blockers: list[str] = []
        edge = self._manifest_previewer(
            canonical_json(dict(execution_edge_manifest)),
            source_name="persisted owner-selected execution edge manifest",
        )
        blockers.extend(str(item) for item in edge.get("record_blockers") or [])
        blockers.extend(str(item) for item in edge.get("blockers") or [])
        if (
            edge.get("recordable") is not True
            or edge.get("validation_status") != "pass"
        ):
            blockers.append("controlled_broker_write_release_execution_edge_blocked")

        conformance = self._execution_edge_conformance(edge)
        blockers.extend(str(item) for item in conformance.get("blockers") or [])
        if conformance.get("status") != "clear":
            blockers.append("controlled_broker_write_release_conformance_not_clear")

        readonly = self._readonly_release(readonly_release_evidence_ref)
        blockers.extend(str(item) for item in readonly.get("blockers") or [])
        if readonly.get("status") != "observing_readonly":
            blockers.append(
                "controlled_broker_write_release_readonly_release_not_observing"
            )
        scope = self._build_scope(edge, readonly, blockers)
        soak = self._soak_promotion(scope["connector_id"])
        acceptance = self._validate_soak(
            soak=soak,
            scope=scope,
            soak_acceptance_id=soak_acceptance_id,
            blockers=blockers,
        )
        normalized_refs, review_ref_blockers = normalize_owner_review_refs(
            owner_review_refs
        )
        blockers.extend(review_ref_blockers)
        normalized_effective, normalized_expires, time_blockers = (
            normalize_release_window(
                effective_at,
                expires_at,
                now=now,
                issuance=issuance,
            )
        )
        blockers.extend(time_blockers)
        core = self._build_core(
            edge=edge,
            conformance=conformance,
            readonly=readonly,
            soak=soak,
            acceptance=acceptance,
            scope=scope,
            owner_review_refs=normalized_refs,
            effective_at=normalized_effective,
            expires_at=normalized_expires,
        )
        unique_blockers = list(dict.fromkeys(blockers))
        dossier_fingerprint = fingerprint(core)
        return {
            **core,
            "dossier_fingerprint": dossier_fingerprint,
            "generated_at": now.isoformat(),
            "review_status": (
                "ready_for_signature" if not unique_blockers else "blocked"
            ),
            "review_ready": not unique_blockers,
            "review_blockers": unique_blockers,
            "required_operator_approval": {
                "action": "issue_controlled_broker_write_release",
                "artifact_type": "controlled_broker_write_release_dossier",
                "artifact_fingerprint": dossier_fingerprint,
            },
            "provider_contact_performed": False,
            "adapter_registered": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "capital_authority_changed": False,
        }

    @staticmethod
    def _build_scope(
        edge: Mapping[str, Any],
        readonly: Mapping[str, Any],
        blockers: list[str],
    ) -> dict[str, str]:
        scope = {
            "provider": str(edge.get("provider") or ""),
            "gateway_id": str(edge.get("gateway_id") or ""),
            "account_alias": str(edge.get("account_alias") or ""),
            "connector_id": str(readonly.get("collector_id") or ""),
        }
        for field in ("provider", "gateway_id", "account_alias"):
            if str(readonly.get(field) or "") != scope[field]:
                blockers.append(
                    f"controlled_broker_write_release_readonly_scope_mismatch:{field}"
                )
        return scope

    @staticmethod
    def _validate_soak(
        *,
        soak: Mapping[str, Any],
        scope: Mapping[str, str],
        soak_acceptance_id: str,
        blockers: list[str],
    ) -> dict[str, Any]:
        blockers.extend(str(item) for item in soak.get("promotion_blockers") or [])
        acceptance = mapping(soak.get("acceptance"))
        normalized_acceptance = str(soak_acceptance_id or "").strip().lower()
        if not CONTROLLED_BROKER_WRITE_RELEASE_FINGERPRINT_PATTERN.fullmatch(
            normalized_acceptance
        ):
            blockers.append(
                "controlled_broker_write_release_soak_acceptance_id_invalid"
            )
        checks = (
            (soak.get("promotion_ready") is True, "soak_not_promoted"),
            (
                str(soak.get("connector_id") or "") == scope["connector_id"],
                "soak_connector_mismatch",
            ),
            (
                str(soak.get("account_alias") or "") == scope["account_alias"],
                "soak_account_mismatch",
            ),
            (
                str(acceptance.get("acceptance_id") or "") == normalized_acceptance,
                "soak_acceptance_mismatch",
            ),
            (
                acceptance.get("operator_identity_verified") is True,
                "soak_operator_unverified",
            ),
            (
                acceptance.get("authorizes_execution") is False,
                "soak_boundary_invalid",
            ),
            (
                soak.get("broker_submission_enabled") is False,
                "soak_submission_boundary_invalid",
            ),
            (
                soak.get("account_truth_reconciliation_linked") is True,
                "account_truth_not_linked",
            ),
        )
        blockers.extend(
            f"controlled_broker_write_release_{suffix}"
            for passed, suffix in checks
            if not passed
        )
        return acceptance

    @staticmethod
    def _build_core(
        *,
        edge: Mapping[str, Any],
        conformance: Mapping[str, Any],
        readonly: Mapping[str, Any],
        soak: Mapping[str, Any],
        acceptance: Mapping[str, Any],
        scope: Mapping[str, str],
        owner_review_refs: Mapping[str, str],
        effective_at: str,
        expires_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION,
            "execution_edge": {
                "execution_edge_ref": str(edge.get("execution_edge_ref") or ""),
                "adapter_ref": str(edge.get("adapter_ref") or ""),
                "adapter_version": str(edge.get("adapter_version") or ""),
                "manifest_fingerprint": str(edge.get("manifest_fingerprint") or ""),
                "deployment_fingerprint": str(edge.get("deployment_fingerprint") or ""),
                "capabilities": mapping(edge.get("capabilities")),
                "boundaries": mapping(edge.get("boundaries")),
                "review_refs": mapping(edge.get("review_refs")),
            },
            "execution_edge_conformance": {
                "run_id": str(conformance.get("run_id") or ""),
                "report_fingerprint": str(conformance.get("report_fingerprint") or ""),
                "manifest_fingerprint": str(
                    conformance.get("manifest_fingerprint") or ""
                ),
                "status": str(conformance.get("status") or "blocked"),
            },
            "readonly_adapter_release": {
                key: readonly.get(key)
                for key in (
                    "release_evidence_ref",
                    "manifest_fingerprint",
                    "provider",
                    "gateway_id",
                    "account_alias",
                    "collector_id",
                    "review_id",
                    "conformance_run_id",
                    "conformance_report_fingerprint",
                    "collector_run_id",
                    "status",
                )
            },
            "soak_promotion": {
                "connector_id": str(soak.get("connector_id") or ""),
                "account_alias": str(soak.get("account_alias") or ""),
                "dossier_fingerprint": str(soak.get("dossier_fingerprint") or ""),
                "acceptance_id": str(acceptance.get("acceptance_id") or ""),
                "account_truth_source_fingerprint": str(
                    mapping(soak.get("account_truth_evidence")).get(
                        "source_fingerprint"
                    )
                    or ""
                ),
                "operational_source_fingerprint": str(
                    mapping(soak.get("operational_evidence")).get("source_fingerprint")
                    or ""
                ),
                "promotion_ready": soak.get("promotion_ready") is True,
            },
            "scope": dict(scope),
            "owner_review_refs": dict(owner_review_refs),
            "effective_at": effective_at,
            "expires_at": expires_at,
            "execution_mode": "manual_each_order",
            "automatic_execution_allowed": False,
            "strategy_direct_submission_allowed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        }

    def _execution_edge_conformance(self, edge: Mapping[str, Any]) -> dict[str, Any]:
        if self._path is None:
            return blocked_source("broker_execution_edge_store_unavailable")
        try:
            return self._conformance_repository_factory(
                self._path
            ).verify_manifest_binding(
                execution_edge_ref=str(edge.get("execution_edge_ref") or ""),
                manifest_fingerprint=str(edge.get("manifest_fingerprint") or ""),
            )
        except Exception:
            return blocked_source("broker_execution_edge_source_failed")

    def _readonly_release(self, release_evidence_ref: str) -> dict[str, Any]:
        release_ref = str(release_evidence_ref or "").strip()
        if not CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN.fullmatch(release_ref):
            return blocked_source("broker_adapter_release_ref_invalid")
        try:
            readiness = self._readonly_readiness_provider(self._db)
        except Exception:
            return blocked_source("broker_adapter_readiness_source_failed")
        matches = [
            item
            for item in readiness.get("releases") or []
            if isinstance(item, dict)
            and str(item.get("release_evidence_ref") or "") == release_ref
        ]
        if len(matches) != 1:
            return blocked_source(
                "broker_adapter_release_not_found"
                if not matches
                else "broker_adapter_release_ambiguous"
            )
        selected = dict(matches[0])
        exact_scope = [
            item
            for item in readiness.get("releases") or []
            if isinstance(item, dict)
            and all(
                str(item.get(field) or "") == str(selected.get(field) or "")
                for field in ("provider", "gateway_id", "account_alias", "collector_id")
            )
        ]
        if not exact_scope or str(
            exact_scope[0].get("release_evidence_ref") or ""
        ) != str(selected.get("release_evidence_ref") or ""):
            return blocked_source("broker_adapter_release_not_latest_for_scope")
        return selected

    def _soak_promotion(self, connector_id: str) -> dict[str, Any]:
        if not CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN.fullmatch(
            str(connector_id or "")
        ):
            return {
                "promotion_ready": False,
                "promotion_blockers": ["broker_soak_connector_id_invalid"],
            }
        provider = self._soak_promotion_provider_factory()
        if not callable(provider):
            return {
                "promotion_ready": False,
                "promotion_blockers": ["broker_soak_promotion_provider_unavailable"],
            }
        try:
            value = provider(connector_id) or {}
        except Exception:
            return {
                "promotion_ready": False,
                "promotion_blockers": ["broker_soak_promotion_source_failed"],
            }
        if isinstance(value, dict):
            return value
        return {
            "promotion_ready": False,
            "promotion_blockers": ["broker_soak_promotion_source_invalid"],
        }


__all__ = ["ControlledBrokerWriteReleaseDossierBuilder"]
