"""Signed, expiring capability release for one reviewed broker execution edge.

The release is necessary but never sufficient for an order submission.  It binds
persisted adapter, soak, conformance, and owner-review evidence; per-order capital,
risk, account, operator, and gateway checks remain separate mandatory gates.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_execution_edge_conformance import (
    BrokerExecutionEdgeConformanceRepository,
    preview_broker_execution_edge_manifest,
)
from server.services.broker_adapter_readiness import build_broker_adapter_readiness
from server.services.operator_approval import (
    resolve_operator_approval,
    resolve_operator_approval_with_proof,
)

CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION = (
    "karkinos.controlled_broker_write_release_dossier.v1"
)
CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION = (
    "karkinos.controlled_broker_write_release.v1"
)
CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_broker_write_release_status.v1"
)
CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION = (
    "karkinos.controlled_broker_write_release_revocation.v1"
)
CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT = "issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority"
CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT = (
    "revoke_exact_broker_write_release_without_resume_or_broker_action"
)
CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS = 12 * 60 * 60
CONTROLLED_BROKER_WRITE_RELEASE_ISSUE_CLOCK_SKEW_SECONDS = 5 * 60

_RELEASE_TABLE = "controlled_broker_write_releases"
_REVOCATION_TABLE = "controlled_broker_write_release_revocations"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_OWNER_REVIEW_REF_FIELDS = (
    "broker_agreement_review",
    "account_permissions_review",
    "program_trading_reporting_review",
    "provider_acceptance_test_report",
    "deployment_authorization",
    "risk_controls_review",
    "rollback_drill_review",
)
_REVOCATION_REASONS = frozenset(
    {
        "adapter_or_deployment_changed",
        "incident_or_anomaly",
        "owner_disabled",
        "provider_scope_changed",
        "regulatory_or_permission_change",
        "scheduled_expiry_superseded",
    }
)


class ControlledBrokerWriteReleaseRejected(ValueError):
    """Raised when an issue or revocation attempt fails closed."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledBrokerWriteReleaseService:
    """Own append-only write-edge releases without registering an adapter."""

    def __init__(
        self,
        *,
        db: Any,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        soak_promotion_provider: Callable[[str], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._path = _database_path(db)
        self._trusted_operator_identities = tuple(trusted_operator_identities or ())
        self._soak_promotion_provider = soak_promotion_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def __call__(self, release_evidence_id: str) -> dict[str, Any]:
        return self.resolve_release_evidence(release_evidence_id)

    def get_status(self) -> dict[str, Any]:
        releases = self.list_releases(limit=100)
        active = [
            item
            for item in releases
            if item.get("status") == "current_clear_signed_release"
        ]
        return {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "active_expiring_manual_each_order_release"
                if active
                else "default_closed_waiting_for_signed_write_release"
            ),
            "recorded_release_count": len(releases),
            "active_release_count": len(active),
            "active_release_ids": [
                str(item.get("release_evidence_id") or "") for item in active
            ],
            "maximum_release_seconds": CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS,
            "supported_revocation_reasons": sorted(_REVOCATION_REASONS),
            "release_provider_available": bool(active),
            "default_registered": False,
            "gateway_registered": False,
            "broker_contact_performed": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "automatic_execution_allowed": False,
            "strategy_direct_submission_allowed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        }

    def preview_dossier(
        self,
        *,
        execution_edge_manifest: Mapping[str, Any],
        readonly_release_evidence_ref: str,
        soak_acceptance_id: str,
        effective_at: str,
        expires_at: str,
        owner_review_refs: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._build_dossier(
            execution_edge_manifest=execution_edge_manifest,
            readonly_release_evidence_ref=readonly_release_evidence_ref,
            soak_acceptance_id=soak_acceptance_id,
            effective_at=effective_at,
            expires_at=expires_at,
            owner_review_refs=owner_review_refs,
            issuance=True,
        )

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
        initial = self._build_dossier(**inputs, issuance=True)
        input_blockers = self._release_request_blockers(
            dossier=initial,
            dossier_fingerprint=dossier_fingerprint,
            operator_label=operator_label,
            acknowledgement=acknowledgement,
        )
        if input_blockers:
            self._raise_rejected(
                "broker write release rejected", initial, input_blockers
            )

        self._ensure_schema()
        if self._path is None:
            self._raise_rejected(
                "broker write release evidence store unavailable",
                initial,
                ["controlled_broker_write_release_store_unavailable"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            dossier = self._build_dossier(**inputs, issuance=True)
            blockers = self._release_request_blockers(
                dossier=dossier,
                dossier_fingerprint=dossier_fingerprint,
                operator_label=operator_label,
                acknowledgement=acknowledgement,
            )
            approval, approval_blockers = resolve_operator_approval_with_proof(
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
            blockers.extend(self._active_scope_conflicts(conn, dossier=dossier))
            blockers = list(dict.fromkeys(blockers))
            if blockers:
                conn.rollback()
                self._raise_rejected(
                    "broker write release transaction rejected",
                    dossier,
                    blockers,
                )

            release_evidence_id = _fingerprint(
                {
                    "domain": "karkinos.controlled_broker_write_release.id.v1",
                    "dossier_fingerprint": dossier["dossier_fingerprint"],
                }
            )
            payload = {
                "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
                "release_evidence_id": release_evidence_id,
                "dossier_inputs": inputs,
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
            evidence_fingerprint = _fingerprint(payload)
            existing = conn.execute(
                f"SELECT * FROM {_RELEASE_TABLE} WHERE release_evidence_id = ?",
                (release_evidence_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["evidence_fingerprint"]) != evidence_fingerprint:
                    conn.rollback()
                    self._raise_rejected(
                        "broker write release id conflict",
                        dossier,
                        ["controlled_broker_write_release_id_conflict"],
                    )
                conn.commit()
                return self._row_response(existing, reused=True)
            now = _aware_utc(self._clock()).isoformat()
            conn.execute(
                f"""
                INSERT INTO {_RELEASE_TABLE} (
                    release_evidence_id, evidence_fingerprint, gateway_id,
                    account_alias, provider, effective_at, expires_at,
                    operator_id, operator_key_id, operator_approval_id,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release_evidence_id,
                    evidence_fingerprint,
                    payload["gateway_id"],
                    payload["account_alias"],
                    payload["provider"],
                    payload["effective_at"],
                    payload["expires_at"],
                    payload["operator_id"],
                    payload["operator_key_id"],
                    payload["operator_approval_id"],
                    _json(payload),
                    now,
                ),
            )
            saved = conn.execute(
                f"SELECT * FROM {_RELEASE_TABLE} WHERE release_evidence_id = ?",
                (release_evidence_id,),
            ).fetchone()
            conn.commit()
        if saved is None:
            raise RuntimeError("broker write release was not persisted")
        return self._row_response(saved, reused=False)

    def preview_revocation(
        self,
        *,
        release_evidence_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        release_id = str(release_evidence_id or "").strip().lower()
        reason = str(reason_code or "").strip().lower()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(release_id):
            blockers.append("controlled_broker_write_release_id_invalid")
        if reason not in _REVOCATION_REASONS:
            blockers.append("controlled_broker_write_release_revocation_reason_invalid")
        row = self._release_row(release_id)
        if row is None:
            blockers.append("controlled_broker_write_release_not_found")
        stored = self._row_response(row, reused=False) if row is not None else {}
        existing = self._revocation_row(release_id)
        core = {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION,
            "action": "revoke_controlled_broker_write_release",
            "release_evidence_id": release_id,
            "release_evidence_fingerprint": str(
                stored.get("evidence_fingerprint") or ""
            ),
            "reason_code": reason,
        }
        revocation_fingerprint = _fingerprint(core)
        if existing is not None and str(existing["revocation_fingerprint"]) != (
            revocation_fingerprint
        ):
            blockers.append("controlled_broker_write_release_already_revoked")
        return {
            **core,
            "revocation_fingerprint": revocation_fingerprint,
            "status": (
                "already_revoked"
                if existing is not None
                else ("ready_for_signature" if not blockers else "blocked")
            ),
            "ready": not blockers and existing is None,
            "blockers": list(dict.fromkeys(blockers)),
            "required_operator_approval": {
                "action": "revoke_controlled_broker_write_release",
                "artifact_type": "controlled_broker_write_release_revocation",
                "artifact_fingerprint": revocation_fingerprint,
            },
            "broker_contact_performed": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "capital_authority_changed": False,
            "resume_enabled": False,
        }

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
        blockers = list(preview["blockers"])
        if (
            acknowledgement
            != CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT
        ):
            blockers.append(
                "controlled_broker_write_release_revocation_acknowledgement_mismatch"
            )
        if str(revocation_fingerprint or "") != preview["revocation_fingerprint"]:
            blockers.append(
                "controlled_broker_write_release_revocation_fingerprint_mismatch"
            )
        normalized_label = str(operator_label or "").strip()
        if not _ID_PATTERN.fullmatch(normalized_label):
            blockers.append("controlled_broker_write_release_operator_invalid")
        existing = self._revocation_row(preview["release_evidence_id"])
        if existing is not None and not blockers:
            return self._revocation_response(existing, reused=True)
        if blockers:
            self._raise_rejected(
                "broker write release revocation rejected", preview, blockers
            )

        self._ensure_schema()
        if self._path is None:
            self._raise_rejected(
                "broker write release revocation store unavailable",
                preview,
                ["controlled_broker_write_release_store_unavailable"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            current = self.preview_revocation(
                release_evidence_id=release_evidence_id,
                reason_code=reason_code,
            )
            blockers = list(current["blockers"])
            if str(revocation_fingerprint or "") != current["revocation_fingerprint"]:
                blockers.append(
                    "controlled_broker_write_release_revocation_fingerprint_mismatch"
                )
            approval, approval_blockers = resolve_operator_approval_with_proof(
                db=self._db,
                trusted_identities=self._trusted_operator_identities,
                approval_id=str(operator_approval_id or ""),
                proof_signature_base64=str(operator_proof_signature_base64 or ""),
                expected_action="revoke_controlled_broker_write_release",
                expected_artifact_type="controlled_broker_write_release_revocation",
                expected_artifact_fingerprint=current["revocation_fingerprint"],
                clock=self._clock,
            )
            blockers.extend(approval_blockers)
            if approval and normalized_label != str(approval.get("operator_id") or ""):
                blockers.append("controlled_broker_write_release_operator_mismatch")
            existing = conn.execute(
                f"SELECT * FROM {_REVOCATION_TABLE} WHERE release_evidence_id = ?",
                (current["release_evidence_id"],),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["revocation_fingerprint"])
                    != current["revocation_fingerprint"]
                ):
                    blockers.append("controlled_broker_write_release_already_revoked")
                if not blockers:
                    conn.commit()
                    return self._revocation_response(existing, reused=True)
            blockers = list(dict.fromkeys(blockers))
            if blockers:
                conn.rollback()
                self._raise_rejected(
                    "broker write release revocation transaction rejected",
                    current,
                    blockers,
                )
            payload = {
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
            now = _aware_utc(self._clock()).isoformat()
            conn.execute(
                f"""
                INSERT INTO {_REVOCATION_TABLE} (
                    revocation_id, release_evidence_id, revocation_fingerprint,
                    reason_code, operator_id, operator_key_id,
                    operator_approval_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _fingerprint(
                        {
                            "domain": "karkinos.controlled_broker_write_release.revocation_id.v1",
                            "revocation_fingerprint": current["revocation_fingerprint"],
                        }
                    ),
                    current["release_evidence_id"],
                    current["revocation_fingerprint"],
                    current["reason_code"],
                    payload["operator_id"],
                    payload["operator_key_id"],
                    payload["operator_approval_id"],
                    _json(payload),
                    now,
                ),
            )
            saved = conn.execute(
                f"SELECT * FROM {_REVOCATION_TABLE} WHERE release_evidence_id = ?",
                (current["release_evidence_id"],),
            ).fetchone()
            conn.commit()
        if saved is None:
            raise RuntimeError("broker write release revocation was not persisted")
        return self._revocation_response(saved, reused=False)

    def resolve_release_evidence(self, release_evidence_id: str) -> dict[str, Any]:
        release_id = str(release_evidence_id or "").strip().lower()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(release_id):
            blockers.append("controlled_broker_write_release_id_invalid")
        row = self._release_row(release_id)
        if row is None:
            return self._blocked_resolution(
                release_id,
                [*blockers, "controlled_broker_write_release_not_found"],
            )
        payload = _json_object(row["payload_json"])
        if str(row["evidence_fingerprint"]) != _fingerprint(
            {key: value for key, value in payload.items()}
        ):
            blockers.append("controlled_broker_write_release_integrity_invalid")
        if str(payload.get("release_evidence_id") or "") != release_id:
            blockers.append("controlled_broker_write_release_identity_mismatch")
        inputs = _mapping(payload.get("dossier_inputs"))
        dossier = self._build_dossier(
            execution_edge_manifest=_mapping(inputs.get("execution_edge_manifest")),
            readonly_release_evidence_ref=str(
                inputs.get("readonly_release_evidence_ref") or ""
            ),
            soak_acceptance_id=str(inputs.get("soak_acceptance_id") or ""),
            effective_at=str(inputs.get("effective_at") or ""),
            expires_at=str(inputs.get("expires_at") or ""),
            owner_review_refs=_mapping(inputs.get("owner_review_refs")),
            issuance=False,
        )
        blockers.extend(dossier["review_blockers"])
        if dossier["dossier_fingerprint"] != str(
            payload.get("dossier_fingerprint") or ""
        ):
            blockers.append("controlled_broker_write_release_source_drift")
        blockers.extend(
            self._release_binding_blockers(
                row=row,
                payload=payload,
                dossier=dossier,
                release_evidence_id=release_id,
            )
        )
        revocation = self._revocation_row(release_id)
        if revocation is not None:
            revocation_payload = _json_object(revocation["payload_json"])
            if str(revocation["revocation_fingerprint"]) != _fingerprint(
                {
                    "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION,
                    "action": "revoke_controlled_broker_write_release",
                    "release_evidence_id": release_id,
                    "release_evidence_fingerprint": str(
                        payload.get("evidence_fingerprint")
                        or row["evidence_fingerprint"]
                    ),
                    "reason_code": str(revocation["reason_code"]),
                }
            ):
                blockers.append(
                    "controlled_broker_write_release_revocation_integrity_invalid"
                )
            elif str(revocation_payload.get("release_evidence_id") or "") != release_id:
                blockers.append(
                    "controlled_broker_write_release_revocation_identity_mismatch"
                )
            else:
                blockers.append("controlled_broker_write_release_revoked")
        blockers = list(dict.fromkeys(blockers))
        owner_refs = _mapping(dossier.get("owner_review_refs"))
        clear = not blockers
        return {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
            "status": "current_clear_signed_release" if clear else "blocked",
            "release_evidence_id": release_id,
            "evidence_fingerprint": str(row["evidence_fingerprint"]),
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
            "revoked": revocation is not None,
            "provider_contact_performed": False,
            "adapter_registered": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        }

    def list_releases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if (
            self._path is None
            or not self._path.exists()
            or not self._table_exists(_RELEASE_TABLE)
        ):
            return []
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT release_evidence_id FROM {_RELEASE_TABLE} ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [
            self.resolve_release_evidence(str(row["release_evidence_id"]))
            for row in rows
        ]

    def get_release(self, release_evidence_id: str) -> dict[str, Any]:
        return self.resolve_release_evidence(release_evidence_id)

    def _build_dossier(
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
        now = _aware_utc(self._clock())
        blockers: list[str] = []
        manifest_value = dict(execution_edge_manifest)
        edge = preview_broker_execution_edge_manifest(
            _json(manifest_value),
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

        soak = self._soak_promotion(scope["connector_id"])
        blockers.extend(str(item) for item in soak.get("promotion_blockers") or [])
        acceptance = _mapping(soak.get("acceptance"))
        normalized_acceptance = str(soak_acceptance_id or "").strip().lower()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_acceptance):
            blockers.append(
                "controlled_broker_write_release_soak_acceptance_id_invalid"
            )
        if soak.get("promotion_ready") is not True:
            blockers.append("controlled_broker_write_release_soak_not_promoted")
        if str(soak.get("connector_id") or "") != scope["connector_id"]:
            blockers.append("controlled_broker_write_release_soak_connector_mismatch")
        if str(soak.get("account_alias") or "") != scope["account_alias"]:
            blockers.append("controlled_broker_write_release_soak_account_mismatch")
        if str(acceptance.get("acceptance_id") or "") != normalized_acceptance:
            blockers.append("controlled_broker_write_release_soak_acceptance_mismatch")
        if acceptance.get("operator_identity_verified") is not True:
            blockers.append("controlled_broker_write_release_soak_operator_unverified")
        if acceptance.get("authorizes_execution") is not False:
            blockers.append("controlled_broker_write_release_soak_boundary_invalid")
        if soak.get("broker_submission_enabled") is not False:
            blockers.append(
                "controlled_broker_write_release_soak_submission_boundary_invalid"
            )
        if soak.get("account_truth_reconciliation_linked") is not True:
            blockers.append("controlled_broker_write_release_account_truth_not_linked")

        normalized_refs, review_ref_blockers = _owner_review_refs(owner_review_refs)
        blockers.extend(review_ref_blockers)
        normalized_effective, normalized_expires, time_blockers = _release_window(
            effective_at,
            expires_at,
            now=now,
            issuance=issuance,
        )
        blockers.extend(time_blockers)
        core = {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION,
            "execution_edge": {
                "execution_edge_ref": str(edge.get("execution_edge_ref") or ""),
                "adapter_ref": str(edge.get("adapter_ref") or ""),
                "adapter_version": str(edge.get("adapter_version") or ""),
                "manifest_fingerprint": str(edge.get("manifest_fingerprint") or ""),
                "deployment_fingerprint": str(edge.get("deployment_fingerprint") or ""),
                "capabilities": _mapping(edge.get("capabilities")),
                "boundaries": _mapping(edge.get("boundaries")),
                "review_refs": _mapping(edge.get("review_refs")),
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
                    _mapping(soak.get("account_truth_evidence")).get(
                        "source_fingerprint"
                    )
                    or ""
                ),
                "operational_source_fingerprint": str(
                    _mapping(soak.get("operational_evidence")).get("source_fingerprint")
                    or ""
                ),
                "promotion_ready": soak.get("promotion_ready") is True,
            },
            "scope": scope,
            "owner_review_refs": normalized_refs,
            "effective_at": normalized_effective,
            "expires_at": normalized_expires,
            "execution_mode": "manual_each_order",
            "automatic_execution_allowed": False,
            "strategy_direct_submission_allowed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        }
        unique_blockers = list(dict.fromkeys(blockers))
        dossier_fingerprint = _fingerprint(core)
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

    def _execution_edge_conformance(self, edge: Mapping[str, Any]) -> dict[str, Any]:
        if self._path is None:
            return _blocked_source("broker_execution_edge_store_unavailable")
        try:
            return BrokerExecutionEdgeConformanceRepository(
                self._path,
                ensure_schema=False,
            ).verify_manifest_binding(
                execution_edge_ref=str(edge.get("execution_edge_ref") or ""),
                manifest_fingerprint=str(edge.get("manifest_fingerprint") or ""),
            )
        except Exception:
            return _blocked_source("broker_execution_edge_source_failed")

    def _readonly_release(self, release_evidence_ref: str) -> dict[str, Any]:
        release_ref = str(release_evidence_ref or "").strip()
        if not _ID_PATTERN.fullmatch(release_ref):
            return _blocked_source("broker_adapter_release_ref_invalid")
        try:
            readiness = build_broker_adapter_readiness(self._db)
        except Exception:
            return _blocked_source("broker_adapter_readiness_source_failed")
        matches = [
            item
            for item in readiness.get("releases") or []
            if isinstance(item, dict)
            and str(item.get("release_evidence_ref") or "") == release_ref
        ]
        if len(matches) != 1:
            return _blocked_source(
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
                for field in (
                    "provider",
                    "gateway_id",
                    "account_alias",
                    "collector_id",
                )
            )
        ]
        if not exact_scope or str(
            exact_scope[0].get("release_evidence_ref") or ""
        ) != str(selected.get("release_evidence_ref") or ""):
            return _blocked_source("broker_adapter_release_not_latest_for_scope")
        return selected

    def _soak_promotion(self, connector_id: str) -> dict[str, Any]:
        if not _ID_PATTERN.fullmatch(str(connector_id or "")):
            return {
                "promotion_ready": False,
                "promotion_blockers": ["broker_soak_connector_id_invalid"],
            }
        if not callable(self._soak_promotion_provider):
            return {
                "promotion_ready": False,
                "promotion_blockers": ["broker_soak_promotion_provider_unavailable"],
            }
        try:
            value = self._soak_promotion_provider(connector_id) or {}
        except Exception:
            return {
                "promotion_ready": False,
                "promotion_blockers": ["broker_soak_promotion_source_failed"],
            }
        return (
            value
            if isinstance(value, dict)
            else {
                "promotion_ready": False,
                "promotion_blockers": ["broker_soak_promotion_source_invalid"],
            }
        )

    def _release_request_blockers(
        self,
        *,
        dossier: dict[str, Any],
        dossier_fingerprint: str,
        operator_label: str,
        acknowledgement: str,
    ) -> list[str]:
        blockers = list(dossier.get("review_blockers") or [])
        if str(dossier_fingerprint or "") != dossier["dossier_fingerprint"]:
            blockers.append(
                "controlled_broker_write_release_dossier_fingerprint_mismatch"
            )
        if acknowledgement != CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT:
            blockers.append("controlled_broker_write_release_acknowledgement_mismatch")
        if not _ID_PATTERN.fullmatch(str(operator_label or "").strip()):
            blockers.append("controlled_broker_write_release_operator_invalid")
        return list(dict.fromkeys(blockers))

    def _active_scope_conflicts(
        self,
        conn: sqlite3.Connection,
        *,
        dossier: Mapping[str, Any],
    ) -> list[str]:
        scope = _mapping(dossier.get("scope"))
        rows = conn.execute(
            f"""
            SELECT release_evidence_id, expires_at, payload_json
            FROM {_RELEASE_TABLE}
            WHERE gateway_id = ? AND account_alias = ?
            ORDER BY id DESC
            """,
            (scope.get("gateway_id"), scope.get("account_alias")),
        ).fetchall()
        now = _aware_utc(self._clock())
        for row in rows:
            existing_payload = _json_object(row["payload_json"])
            if str(existing_payload.get("dossier_fingerprint") or "") == str(
                dossier.get("dossier_fingerprint") or ""
            ):
                continue
            revoked = conn.execute(
                f"SELECT 1 FROM {_REVOCATION_TABLE} WHERE release_evidence_id = ?",
                (row["release_evidence_id"],),
            ).fetchone()
            expiry = _parse_timestamp(row["expires_at"])
            if revoked is None and expiry is not None and now < expiry:
                return ["controlled_broker_write_release_active_scope_conflict"]
        return []

    def _operator_identity_blockers(self, payload: Mapping[str, Any]) -> list[str]:
        operator_id = str(payload.get("operator_id") or "")
        key_id = str(payload.get("operator_key_id") or "")
        expected_fingerprint = str(payload.get("operator_public_key_fingerprint") or "")
        for identity in self._trusted_operator_identities:
            read = (
                identity.get
                if isinstance(identity, dict)
                else lambda key, default=None: getattr(identity, key, default)
            )
            if (
                str(read("operator_id", "") or "") == operator_id
                and str(read("key_id", "") or "") == key_id
            ):
                if read("enabled", False) is not True:
                    return ["controlled_broker_write_release_operator_disabled"]
                try:
                    public_key = base64.b64decode(
                        str(read("public_key_base64", "") or ""),
                        validate=True,
                    )
                except Exception:
                    return ["controlled_broker_write_release_operator_key_invalid"]
                if hashlib.sha256(public_key).hexdigest() != expected_fingerprint:
                    return ["controlled_broker_write_release_operator_key_changed"]
                return []
        return ["controlled_broker_write_release_operator_not_trusted"]

    def _release_binding_blockers(
        self,
        *,
        row: sqlite3.Row,
        payload: Mapping[str, Any],
        dossier: Mapping[str, Any],
        release_evidence_id: str,
    ) -> list[str]:
        blockers = self._operator_identity_blockers(payload)
        dossier_fingerprint = str(dossier.get("dossier_fingerprint") or "")
        expected_release_id = _fingerprint(
            {
                "domain": "karkinos.controlled_broker_write_release.id.v1",
                "dossier_fingerprint": dossier_fingerprint,
            }
        )
        if release_evidence_id != expected_release_id:
            blockers.append("controlled_broker_write_release_id_binding_invalid")

        scope = _mapping(dossier.get("scope"))
        execution_edge = _mapping(dossier.get("execution_edge"))
        readonly = _mapping(dossier.get("readonly_adapter_release"))
        soak = _mapping(dossier.get("soak_promotion"))
        expected_payload = {
            "dossier_fingerprint": dossier_fingerprint,
            "execution_edge_ref": str(execution_edge.get("execution_edge_ref") or ""),
            "execution_edge_manifest_fingerprint": str(
                execution_edge.get("manifest_fingerprint") or ""
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
        for field, expected in expected_payload.items():
            if str(payload.get(field) or "") != expected:
                blockers.append(
                    f"controlled_broker_write_release_payload_binding_invalid:{field}"
                )

        expected_row = {
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
        for field, expected in expected_row.items():
            if str(row[field]) != expected:
                blockers.append(
                    f"controlled_broker_write_release_row_binding_invalid:{field}"
                )

        approval_clock = _parse_timestamp(payload.get("effective_at")) or _aware_utc(
            self._clock()
        )
        approval, approval_blockers = resolve_operator_approval(
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
        if approval and (
            str(approval.get("operator_id") or "")
            != str(payload.get("operator_id") or "")
            or str(approval.get("key_id") or "")
            != str(payload.get("operator_key_id") or "")
            or str(approval.get("public_key_fingerprint") or "")
            != str(payload.get("operator_public_key_fingerprint") or "")
        ):
            blockers.append("controlled_broker_write_release_approval_binding_invalid")
        return list(dict.fromkeys(blockers))

    def _row_response(self, row: sqlite3.Row, *, reused: bool) -> dict[str, Any]:
        payload = _json_object(row["payload_json"])
        return {
            **payload,
            "status": "recorded_expiring_manual_each_order_release",
            "evidence_fingerprint": str(row["evidence_fingerprint"]),
            "created_at": str(row["created_at"]),
            "persisted": True,
            "reused": reused,
            "broker_contact_performed": False,
            "adapter_registered": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
        }

    def _revocation_response(
        self,
        row: sqlite3.Row,
        *,
        reused: bool,
    ) -> dict[str, Any]:
        return {
            **_json_object(row["payload_json"]),
            "revocation_id": str(row["revocation_id"]),
            "status": "revoked",
            "created_at": str(row["created_at"]),
            "persisted": True,
            "reused": reused,
        }

    def _blocked_resolution(
        self,
        release_evidence_id: str,
        blockers: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
            "status": "blocked",
            "release_evidence_id": release_evidence_id,
            "evidence_fingerprint": "",
            "operator_identity_verified": False,
            "execution_mode": "manual_each_order",
            "automatic_execution_allowed": False,
            "strategy_direct_submission_allowed": False,
            "broker_agreement_reviewed": False,
            "connector_tested": False,
            "program_trading_reporting_reviewed": False,
            "risk_controls_reviewed": False,
            "blockers": list(dict.fromkeys(blockers)),
            "provider_contact_performed": False,
            "adapter_registered": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        }

    def _release_row(self, release_evidence_id: str) -> sqlite3.Row | None:
        if (
            self._path is None
            or not self._path.exists()
            or not self._table_exists(_RELEASE_TABLE)
        ):
            return None
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                f"SELECT * FROM {_RELEASE_TABLE} WHERE release_evidence_id = ?",
                (release_evidence_id,),
            ).fetchone()

    def _revocation_row(self, release_evidence_id: str) -> sqlite3.Row | None:
        if (
            self._path is None
            or not self._path.exists()
            or not self._table_exists(_REVOCATION_TABLE)
        ):
            return None
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                f"SELECT * FROM {_REVOCATION_TABLE} WHERE release_evidence_id = ?",
                (release_evidence_id,),
            ).fetchone()

    def _table_exists(self, table: str) -> bool:
        if self._path is None or not self._path.exists():
            return False
        with sqlite3.connect(self._path) as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                is not None
            )

    def _ensure_schema(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS {_RELEASE_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    release_evidence_id TEXT NOT NULL UNIQUE,
                    evidence_fingerprint TEXT NOT NULL,
                    gateway_id TEXT NOT NULL,
                    account_alias TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    operator_key_id TEXT NOT NULL,
                    operator_approval_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_controlled_broker_write_release_scope
                ON {_RELEASE_TABLE}(gateway_id, account_alias, id DESC);

                CREATE TABLE IF NOT EXISTS {_REVOCATION_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    revocation_id TEXT NOT NULL UNIQUE,
                    release_evidence_id TEXT NOT NULL UNIQUE,
                    revocation_fingerprint TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    operator_key_id TEXT NOT NULL,
                    operator_approval_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(release_evidence_id)
                        REFERENCES {_RELEASE_TABLE}(release_evidence_id)
                );
                """)
            conn.commit()

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
            attempt_id = _fingerprint(payload)
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
                    timestamp=_aware_utc(self._clock()).isoformat(),
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


def _owner_review_refs(value: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    raw = dict(value)
    blockers: list[str] = []
    unknown = sorted(set(raw) - set(_OWNER_REVIEW_REF_FIELDS))
    blockers.extend(
        f"controlled_broker_write_release_owner_review_ref_unsupported:{key}"
        for key in unknown
    )
    normalized: dict[str, str] = {}
    for field in _OWNER_REVIEW_REF_FIELDS:
        item = str(raw.get(field) or "").strip()
        normalized[field] = item
        if not _ID_PATTERN.fullmatch(item):
            blockers.append(
                f"controlled_broker_write_release_owner_review_ref_invalid:{field}"
            )
    return normalized, blockers


def _release_window(
    effective_at: str,
    expires_at: str,
    *,
    now: datetime,
    issuance: bool,
) -> tuple[str, str, list[str]]:
    effective = _parse_timestamp(effective_at)
    expires = _parse_timestamp(expires_at)
    blockers: list[str] = []
    if effective is None or expires is None:
        blockers.append("controlled_broker_write_release_window_invalid")
    elif expires <= effective:
        blockers.append("controlled_broker_write_release_window_invalid")
    else:
        duration = int((expires - effective).total_seconds())
        if duration > CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS:
            blockers.append("controlled_broker_write_release_window_too_wide")
        if now < effective:
            blockers.append("controlled_broker_write_release_not_effective")
        if now >= expires:
            blockers.append("controlled_broker_write_release_expired")
        if issuance and now - effective > timedelta(
            seconds=CONTROLLED_BROKER_WRITE_RELEASE_ISSUE_CLOCK_SKEW_SECONDS
        ):
            blockers.append("controlled_broker_write_release_effective_at_too_old")
    return (
        effective.isoformat() if effective is not None else str(effective_at or ""),
        expires.isoformat() if expires is not None else str(expires_at or ""),
        blockers,
    )


def _database_path(db: Any) -> Path | None:
    value = getattr(db, "_path", None)
    return Path(value) if value is not None else None


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _blocked_source(blocker: str) -> dict[str, Any]:
    return {"status": "blocked", "blockers": [blocker]}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


__all__ = [
    "CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS",
    "CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION",
    "ControlledBrokerWriteReleaseRejected",
    "ControlledBrokerWriteReleaseService",
]
