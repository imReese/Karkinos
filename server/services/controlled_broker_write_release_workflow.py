"""Application workflow for signed controlled broker write releases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from server.contracts.controlled_broker_write_release import (
    CONTROLLED_BROKER_WRITE_RELEASE_FINGERPRINT_PATTERN,
    CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION,
    CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
    ControlledBrokerWriteReleaseRejected,
)
from server.persistence.controlled_broker_write_releases import (
    ControlledBrokerWriteReleaseReadRejected,
    ControlledBrokerWriteReleaseRepository,
    ControlledBrokerWriteReleaseUowRejected,
    ReleaseIssueWrite,
    ReleaseRevocationWrite,
)
from server.services.controlled_broker_write_release_dossier import (
    ControlledBrokerWriteReleaseDossierBuilder,
)
from server.services.controlled_broker_write_release_policy import (
    aware_utc,
    blocked_resolution,
    build_revocation_preview,
    canonical_json,
    fingerprint,
    json_object,
    mapping,
    operator_identity_blockers,
    parse_timestamp,
    release_request_blockers,
    release_row_response,
    revocation_row_response,
)


class ControlledBrokerWriteReleaseWorkflow:
    """Coordinate policy, evidence sources, signatures, and atomic persistence."""

    def __init__(
        self,
        *,
        db: Any,
        repository: ControlledBrokerWriteReleaseRepository | None,
        dossier_builder: ControlledBrokerWriteReleaseDossierBuilder,
        trusted_operator_identities: tuple[Any, ...],
        clock: Callable[[], datetime],
        approval_resolver: Callable[..., tuple[dict[str, Any] | None, list[str]]],
        proof_resolver: Callable[..., tuple[dict[str, Any] | None, list[str]]],
    ) -> None:
        self._db = db
        self._repository = repository
        self._dossier_builder = dossier_builder
        self._trusted_operator_identities = trusted_operator_identities
        self._clock = clock
        self._approval_resolver = approval_resolver
        self._proof_resolver = proof_resolver

    def preview_dossier(self, **inputs: Any) -> dict[str, Any]:
        return self._dossier_builder.build(**inputs, issuance=True)

    def record_release(
        self,
        *,
        execution_edge_manifest: Mapping[str, Any],
        readonly_release_evidence_ref: str,
        soak_acceptance_id: str,
        effective_at: str,
        expires_at: str,
        owner_review_refs: Mapping[str, Any],
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        inputs = {
            "execution_edge_manifest": dict(execution_edge_manifest),
            "readonly_release_evidence_ref": str(readonly_release_evidence_ref or ""),
            "soak_acceptance_id": str(soak_acceptance_id or ""),
            "effective_at": str(effective_at or ""),
            "expires_at": str(expires_at or ""),
            "owner_review_refs": dict(owner_review_refs),
        }
        initial = self._dossier_builder.build(**inputs, issuance=True)
        input_blockers = release_request_blockers(
            dossier=initial,
            dossier_fingerprint=dossier_fingerprint,
            operator_label=operator_label,
            acknowledgement=acknowledgement,
        )
        if input_blockers:
            self._raise_rejected(
                "broker write release rejected", initial, input_blockers
            )
        if self._repository is None:
            self._raise_rejected(
                "broker write release evidence store unavailable",
                initial,
                ["controlled_broker_write_release_store_unavailable"],
            )

        def prepare() -> ReleaseIssueWrite:
            dossier = self._dossier_builder.build(**inputs, issuance=True)
            blockers = release_request_blockers(
                dossier=dossier,
                dossier_fingerprint=dossier_fingerprint,
                operator_label=operator_label,
                acknowledgement=acknowledgement,
            )
            approval, approval_blockers = self._proof_resolver(
                db=self._db,
                trusted_identities=self._trusted_operator_identities,
                approval_id=str(operator_approval_id or ""),
                proof_signature_base64=str(operator_proof_signature_base64 or ""),
                expected_action="issue_controlled_broker_write_release",
                expected_artifact_type="controlled_broker_write_release_dossier",
                expected_artifact_fingerprint=dossier["dossier_fingerprint"],
                clock=self._clock,
            )
            blockers.extend(approval_blockers)
            normalized_label = str(operator_label or "").strip()
            if approval and normalized_label != str(approval.get("operator_id") or ""):
                blockers.append("controlled_broker_write_release_operator_mismatch")
            unique_blockers = tuple(dict.fromkeys(blockers))
            payload = (
                self._release_payload(inputs=inputs, dossier=dossier, approval=approval)
                if approval and not unique_blockers
                else None
            )
            scope = mapping(dossier.get("scope"))
            return ReleaseIssueWrite(
                evidence=dossier,
                blockers=unique_blockers,
                gateway_id=str(scope.get("gateway_id") or ""),
                account_alias=str(scope.get("account_alias") or ""),
                payload=payload,
                evidence_fingerprint=fingerprint(payload) if payload else "",
                payload_json=canonical_json(payload) if payload else "",
                created_at=aware_utc(self._clock()).isoformat(),
                active_at=aware_utc(self._clock()),
            )

        try:
            row, reused = self._repository.issue_release(prepare)
        except ControlledBrokerWriteReleaseUowRejected as exc:
            self._raise_rejected(
                "broker write release transaction rejected",
                exc.evidence,
                exc.blockers,
            )
        return release_row_response(row, reused=reused)

    def preview_revocation(
        self, *, release_evidence_id: str, reason_code: str
    ) -> dict[str, Any]:
        release_row, revocation_row, read_blockers = self._load_rows(
            str(release_evidence_id or "").strip().lower()
        )
        return build_revocation_preview(
            release_evidence_id=release_evidence_id,
            reason_code=reason_code,
            release_row=release_row,
            revocation_row=revocation_row,
            read_blockers=read_blockers,
        )

    def revoke_release(
        self,
        *,
        release_evidence_id: str,
        reason_code: str,
        revocation_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview_revocation(
            release_evidence_id=release_evidence_id,
            reason_code=reason_code,
        )
        blockers = self._revocation_request_blockers(
            preview=preview,
            revocation_fingerprint=revocation_fingerprint,
            operator_label=operator_label,
            acknowledgement=acknowledgement,
        )
        _, existing, _ = self._load_rows(preview["release_evidence_id"])
        if existing is not None and not blockers:
            return revocation_row_response(existing, reused=True)
        if blockers:
            self._raise_rejected(
                "broker write release revocation rejected", preview, blockers
            )
        if self._repository is None:
            self._raise_rejected(
                "broker write release revocation store unavailable",
                preview,
                ["controlled_broker_write_release_store_unavailable"],
            )

        def prepare(
            release_row: dict[str, Any] | None,
            revocation_row: dict[str, Any] | None,
        ) -> ReleaseRevocationWrite:
            current = build_revocation_preview(
                release_evidence_id=release_evidence_id,
                reason_code=reason_code,
                release_row=release_row,
                revocation_row=revocation_row,
            )
            current_blockers = list(current["blockers"])
            if str(revocation_fingerprint or "") != current["revocation_fingerprint"]:
                current_blockers.append(
                    "controlled_broker_write_release_revocation_fingerprint_mismatch"
                )
            approval, approval_blockers = self._proof_resolver(
                db=self._db,
                trusted_identities=self._trusted_operator_identities,
                approval_id=str(operator_approval_id or ""),
                proof_signature_base64=str(operator_proof_signature_base64 or ""),
                expected_action="revoke_controlled_broker_write_release",
                expected_artifact_type="controlled_broker_write_release_revocation",
                expected_artifact_fingerprint=current["revocation_fingerprint"],
                clock=self._clock,
            )
            current_blockers.extend(approval_blockers)
            normalized_label = str(operator_label or "").strip()
            if approval and normalized_label != str(approval.get("operator_id") or ""):
                current_blockers.append(
                    "controlled_broker_write_release_operator_mismatch"
                )
            unique_blockers = tuple(dict.fromkeys(current_blockers))
            payload = (
                self._revocation_payload(current=current, approval=approval)
                if approval and not unique_blockers
                else None
            )
            return ReleaseRevocationWrite(
                evidence=current,
                blockers=unique_blockers,
                payload=payload,
                revocation_id=(
                    fingerprint(
                        {
                            "domain": "karkinos.controlled_broker_write_release.revocation_id.v1",
                            "revocation_fingerprint": current["revocation_fingerprint"],
                        }
                    )
                    if payload
                    else ""
                ),
                payload_json=canonical_json(payload) if payload else "",
                created_at=aware_utc(self._clock()).isoformat(),
            )

        try:
            row, reused = self._repository.revoke_release(
                preview["release_evidence_id"], prepare
            )
        except ControlledBrokerWriteReleaseUowRejected as exc:
            self._raise_rejected(
                "broker write release revocation transaction rejected",
                exc.evidence,
                exc.blockers,
            )
        return revocation_row_response(row, reused=reused)

    def resolve_release_evidence(self, release_evidence_id: str) -> dict[str, Any]:
        release_id = str(release_evidence_id or "").strip().lower()
        blockers: list[str] = []
        if not CONTROLLED_BROKER_WRITE_RELEASE_FINGERPRINT_PATTERN.fullmatch(
            release_id
        ):
            blockers.append("controlled_broker_write_release_id_invalid")
        release_row, revocation_row, read_blockers = self._load_rows(release_id)
        blockers.extend(read_blockers)
        if release_row is None:
            return blocked_resolution(
                release_id,
                [*blockers, "controlled_broker_write_release_not_found"],
            )
        payload = json_object(release_row.get("payload_json"))
        if str(release_row.get("evidence_fingerprint") or "") != fingerprint(payload):
            blockers.append("controlled_broker_write_release_integrity_invalid")
        if str(payload.get("release_evidence_id") or "") != release_id:
            blockers.append("controlled_broker_write_release_identity_mismatch")
        inputs = mapping(payload.get("dossier_inputs"))
        dossier = self._dossier_builder.build(
            execution_edge_manifest=mapping(inputs.get("execution_edge_manifest")),
            readonly_release_evidence_ref=str(
                inputs.get("readonly_release_evidence_ref") or ""
            ),
            soak_acceptance_id=str(inputs.get("soak_acceptance_id") or ""),
            effective_at=str(inputs.get("effective_at") or ""),
            expires_at=str(inputs.get("expires_at") or ""),
            owner_review_refs=mapping(inputs.get("owner_review_refs")),
            issuance=False,
        )
        blockers.extend(dossier["review_blockers"])
        if dossier["dossier_fingerprint"] != str(
            payload.get("dossier_fingerprint") or ""
        ):
            blockers.append("controlled_broker_write_release_source_drift")
        blockers.extend(
            self._release_binding_blockers(
                row=release_row,
                payload=payload,
                dossier=dossier,
                release_evidence_id=release_id,
            )
        )
        blockers.extend(
            self._revocation_integrity_blockers(
                release_id=release_id,
                release_row=release_row,
                revocation_row=revocation_row,
            )
        )
        return self._resolution_response(
            release_id=release_id,
            release_row=release_row,
            payload=payload,
            dossier=dossier,
            revocation_row=revocation_row,
            blockers=list(dict.fromkeys(blockers)),
        )

    def list_release_ids(self, *, limit: int) -> list[str]:
        if self._repository is None:
            return []
        try:
            return self._repository.list_release_ids(limit=limit)
        except ControlledBrokerWriteReleaseReadRejected:
            return []

    def _load_rows(
        self, release_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
        if self._repository is None:
            return None, None, []
        try:
            return (
                self._repository.get_release_row(release_id),
                self._repository.get_revocation_row(release_id),
                [],
            )
        except ControlledBrokerWriteReleaseReadRejected:
            return (
                None,
                None,
                ["controlled_broker_write_release_store_unavailable"],
            )

    @staticmethod
    def _release_payload(
        *,
        inputs: Mapping[str, Any],
        dossier: Mapping[str, Any],
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        release_evidence_id = fingerprint(
            {
                "domain": "karkinos.controlled_broker_write_release.id.v1",
                "dossier_fingerprint": dossier["dossier_fingerprint"],
            }
        )
        return {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
            "release_evidence_id": release_evidence_id,
            "dossier_inputs": dict(inputs),
            "dossier_fingerprint": dossier["dossier_fingerprint"],
            "execution_edge_ref": dossier["execution_edge"]["execution_edge_ref"],
            "execution_edge_manifest_fingerprint": dossier["execution_edge"][
                "manifest_fingerprint"
            ],
            "readonly_release_evidence_ref": dossier["readonly_adapter_release"][
                "release_evidence_ref"
            ],
            "readonly_release_manifest_fingerprint": dossier[
                "readonly_adapter_release"
            ]["manifest_fingerprint"],
            "soak_acceptance_id": dossier["soak_promotion"]["acceptance_id"],
            "soak_dossier_fingerprint": dossier["soak_promotion"][
                "dossier_fingerprint"
            ],
            "provider": dossier["scope"]["provider"],
            "gateway_id": dossier["scope"]["gateway_id"],
            "account_alias": dossier["scope"]["account_alias"],
            "operator_id": str(approval.get("operator_id") or ""),
            "operator_key_id": str(approval.get("key_id") or ""),
            "operator_public_key_fingerprint": str(
                approval.get("public_key_fingerprint") or ""
            ),
            "operator_approval_id": str(approval.get("approval_id") or ""),
            "operator_identity_verified": True,
            "effective_at": dossier["effective_at"],
            "expires_at": dossier["expires_at"],
            "execution_mode": "manual_each_order",
            "automatic_execution_allowed": False,
            "strategy_direct_submission_allowed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        }

    @staticmethod
    def _revocation_payload(
        *, current: Mapping[str, Any], approval: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            **{
                key: current[key]
                for key in (
                    "schema_version",
                    "release_evidence_id",
                    "release_evidence_fingerprint",
                    "reason_code",
                    "revocation_fingerprint",
                )
            },
            "operator_id": str(approval.get("operator_id") or ""),
            "operator_key_id": str(approval.get("key_id") or ""),
            "operator_approval_id": str(approval.get("approval_id") or ""),
            "operator_identity_verified": True,
            "resume_enabled": False,
            "broker_contact_performed": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "capital_authority_changed": False,
        }

    @staticmethod
    def _revocation_request_blockers(
        *,
        preview: Mapping[str, Any],
        revocation_fingerprint: str,
        operator_label: str,
        acknowledgement: str,
    ) -> list[str]:
        blockers = list(preview.get("blockers") or [])
        if (
            acknowledgement
            != CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT
        ):
            blockers.append(
                "controlled_broker_write_release_revocation_acknowledgement_mismatch"
            )
        if str(revocation_fingerprint or "") != preview.get("revocation_fingerprint"):
            blockers.append(
                "controlled_broker_write_release_revocation_fingerprint_mismatch"
            )
        if not CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN.fullmatch(
            str(operator_label or "").strip()
        ):
            blockers.append("controlled_broker_write_release_operator_invalid")
        return list(dict.fromkeys(blockers))

    def _release_binding_blockers(
        self,
        *,
        row: Mapping[str, Any],
        payload: Mapping[str, Any],
        dossier: Mapping[str, Any],
        release_evidence_id: str,
    ) -> list[str]:
        blockers = operator_identity_blockers(
            payload, self._trusted_operator_identities
        )
        dossier_fingerprint = str(dossier.get("dossier_fingerprint") or "")
        expected_release_id = fingerprint(
            {
                "domain": "karkinos.controlled_broker_write_release.id.v1",
                "dossier_fingerprint": dossier_fingerprint,
            }
        )
        if release_evidence_id != expected_release_id:
            blockers.append("controlled_broker_write_release_id_binding_invalid")
        blockers.extend(self._payload_binding_blockers(payload, dossier))
        blockers.extend(self._row_binding_blockers(row, payload, release_evidence_id))
        approval_clock = parse_timestamp(payload.get("effective_at")) or aware_utc(
            self._clock()
        )
        approval, approval_blockers = self._approval_resolver(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=str(payload.get("operator_approval_id") or ""),
            expected_action="issue_controlled_broker_write_release",
            expected_artifact_type="controlled_broker_write_release_dossier",
            expected_artifact_fingerprint=dossier_fingerprint,
            clock=lambda: approval_clock,
        )
        blockers.extend(
            f"controlled_broker_write_release_{item}" for item in approval_blockers
        )
        if approval and any(
            (
                str(approval.get("operator_id") or "")
                != str(payload.get("operator_id") or ""),
                str(approval.get("key_id") or "")
                != str(payload.get("operator_key_id") or ""),
                str(approval.get("public_key_fingerprint") or "")
                != str(payload.get("operator_public_key_fingerprint") or ""),
            )
        ):
            blockers.append("controlled_broker_write_release_approval_binding_invalid")
        return list(dict.fromkeys(blockers))

    @staticmethod
    def _payload_binding_blockers(
        payload: Mapping[str, Any], dossier: Mapping[str, Any]
    ) -> list[str]:
        scope = mapping(dossier.get("scope"))
        edge = mapping(dossier.get("execution_edge"))
        readonly = mapping(dossier.get("readonly_adapter_release"))
        soak = mapping(dossier.get("soak_promotion"))
        expected = {
            "dossier_fingerprint": str(dossier.get("dossier_fingerprint") or ""),
            "execution_edge_ref": str(edge.get("execution_edge_ref") or ""),
            "execution_edge_manifest_fingerprint": str(
                edge.get("manifest_fingerprint") or ""
            ),
            "readonly_release_evidence_ref": str(
                readonly.get("release_evidence_ref") or ""
            ),
            "readonly_release_manifest_fingerprint": str(
                readonly.get("manifest_fingerprint") or ""
            ),
            "soak_acceptance_id": str(soak.get("acceptance_id") or ""),
            "soak_dossier_fingerprint": str(soak.get("dossier_fingerprint") or ""),
            "provider": str(scope.get("provider") or ""),
            "gateway_id": str(scope.get("gateway_id") or ""),
            "account_alias": str(scope.get("account_alias") or ""),
            "effective_at": str(dossier.get("effective_at") or ""),
            "expires_at": str(dossier.get("expires_at") or ""),
        }
        return [
            f"controlled_broker_write_release_payload_binding_invalid:{field}"
            for field, value in expected.items()
            if str(payload.get(field) or "") != value
        ]

    @staticmethod
    def _row_binding_blockers(
        row: Mapping[str, Any],
        payload: Mapping[str, Any],
        release_evidence_id: str,
    ) -> list[str]:
        expected = {
            "release_evidence_id": release_evidence_id,
            "gateway_id": str(payload.get("gateway_id") or ""),
            "account_alias": str(payload.get("account_alias") or ""),
            "provider": str(payload.get("provider") or ""),
            "effective_at": str(payload.get("effective_at") or ""),
            "expires_at": str(payload.get("expires_at") or ""),
            "operator_id": str(payload.get("operator_id") or ""),
            "operator_key_id": str(payload.get("operator_key_id") or ""),
            "operator_approval_id": str(payload.get("operator_approval_id") or ""),
        }
        return [
            f"controlled_broker_write_release_row_binding_invalid:{field}"
            for field, value in expected.items()
            if str(row.get(field) or "") != value
        ]

    @staticmethod
    def _revocation_integrity_blockers(
        *,
        release_id: str,
        release_row: Mapping[str, Any],
        revocation_row: Mapping[str, Any] | None,
    ) -> list[str]:
        if revocation_row is None:
            return []
        payload = json_object(release_row.get("payload_json"))
        revocation_payload = json_object(revocation_row.get("payload_json"))
        expected = fingerprint(
            {
                "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION,
                "action": "revoke_controlled_broker_write_release",
                "release_evidence_id": release_id,
                "release_evidence_fingerprint": str(
                    payload.get("evidence_fingerprint")
                    or release_row.get("evidence_fingerprint")
                    or ""
                ),
                "reason_code": str(revocation_row.get("reason_code") or ""),
            }
        )
        if str(revocation_row.get("revocation_fingerprint") or "") != expected:
            return ["controlled_broker_write_release_revocation_integrity_invalid"]
        if str(revocation_payload.get("release_evidence_id") or "") != release_id:
            return ["controlled_broker_write_release_revocation_identity_mismatch"]
        return ["controlled_broker_write_release_revoked"]

    @staticmethod
    def _resolution_response(
        *,
        release_id: str,
        release_row: Mapping[str, Any],
        payload: Mapping[str, Any],
        dossier: Mapping[str, Any],
        revocation_row: Mapping[str, Any] | None,
        blockers: list[str],
    ) -> dict[str, Any]:
        owner_refs = mapping(dossier.get("owner_review_refs"))
        clear = not blockers
        return {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
            "status": "current_clear_signed_release" if clear else "blocked",
            "release_evidence_id": release_id,
            "evidence_fingerprint": str(release_row.get("evidence_fingerprint") or ""),
            "provider": str(payload.get("provider") or ""),
            "gateway_id": str(payload.get("gateway_id") or ""),
            "account_alias": str(payload.get("account_alias") or ""),
            "execution_edge_ref": str(payload.get("execution_edge_ref") or ""),
            "readonly_release_evidence_ref": str(
                payload.get("readonly_release_evidence_ref") or ""
            ),
            "soak_acceptance_id": str(payload.get("soak_acceptance_id") or ""),
            "operator_id": str(payload.get("operator_id") or ""),
            "operator_identity_verified": clear,
            "execution_mode": "manual_each_order",
            "automatic_execution_allowed": False,
            "strategy_direct_submission_allowed": False,
            "broker_agreement_reviewed": bool(
                owner_refs.get("broker_agreement_review")
            ),
            "connector_tested": bool(owner_refs.get("provider_acceptance_test_report")),
            "program_trading_reporting_reviewed": bool(
                owner_refs.get("program_trading_reporting_review")
            ),
            "risk_controls_reviewed": bool(owner_refs.get("risk_controls_review")),
            "effective_at": str(payload.get("effective_at") or ""),
            "expires_at": str(payload.get("expires_at") or ""),
            "blockers": blockers,
            "revoked": revocation_row is not None,
            "provider_contact_performed": False,
            "adapter_registered": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        }

    def _raise_rejected(
        self,
        message: str,
        evidence: Mapping[str, Any],
        blockers: list[str],
    ) -> None:
        payload = {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
            "status": "rejected",
            "dossier_fingerprint": str(evidence.get("dossier_fingerprint") or ""),
            "release_evidence_id": str(evidence.get("release_evidence_id") or ""),
            "blockers": list(dict.fromkeys(str(item) for item in blockers)),
            "provider_contact_performed": False,
            "adapter_registered": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "capital_authority_changed": False,
        }
        try:
            attempt_id = fingerprint(payload)
            existing = self._db.list_events_sync(
                event_type="controlled_broker.write_release_rejected",
                entity_type="controlled_broker_write_release_rejection",
                entity_id=attempt_id,
                source="controlled_broker_write_release",
                limit=1,
            )
            if not existing:
                self._db.append_event_sync(
                    event_type="controlled_broker.write_release_rejected",
                    timestamp=aware_utc(self._clock()).isoformat(),
                    entity_type="controlled_broker_write_release_rejection",
                    entity_id=attempt_id,
                    source="controlled_broker_write_release",
                    source_ref=payload["dossier_fingerprint"]
                    or payload["release_evidence_id"],
                    payload={"attempt_id": attempt_id, **payload},
                )
        except Exception:
            pass
        raise ControlledBrokerWriteReleaseRejected(message, evidence=payload)


__all__ = ["ControlledBrokerWriteReleaseWorkflow"]
