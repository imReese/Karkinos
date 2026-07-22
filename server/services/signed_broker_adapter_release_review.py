"""Signed operator review for one provider-neutral read-only adapter release.

This boundary turns the existing append-only manifest review into a no-database-
editing operator journey.  It never registers an adapter, contacts a provider,
or grants execution or capital authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_adapter_conformance import (
    BrokerAdapterConformanceRepository,
)
from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION,
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION,
    BrokerAdapterReleaseRejected,
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)
from server.services.operator_approval import resolve_operator_approval_with_proof

SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_DOSSIER_SCHEMA_VERSION = (
    "karkinos.signed_broker_adapter_release_review_dossier.v1"
)
SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_STATUS_SCHEMA_VERSION = (
    "karkinos.signed_broker_adapter_release_review_status.v1"
)
SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_LIST_SCHEMA_VERSION = (
    "karkinos.signed_broker_adapter_release_review_list.v1"
)
SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ACTION = "review_broker_adapter_release"
SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ARTIFACT_TYPE = (
    "broker_adapter_release_review_dossier"
)

_DECISIONS = frozenset({"accepted", "rejected", "revoked"})
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class SignedBrokerAdapterReleaseReviewRejected(ValueError):
    """Raised when a signed adapter release review fails closed."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class SignedBrokerAdapterReleaseReviewService:
    """Preview and append signed adapter decisions without provider side effects."""

    def __init__(
        self,
        *,
        db: Any,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._path = _database_path(db)
        self._trusted_operator_identities = tuple(trusted_operator_identities or ())
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        manifest_count, review_count = self._counts()
        return {
            "schema_version": (
                SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_STATUS_SCHEMA_VERSION
            ),
            "contract_status": "signed_provider_neutral_adapter_review",
            "recorded_manifest_count": manifest_count,
            "recorded_review_count": review_count,
            "supported_decisions": sorted(_DECISIONS),
            "operator_signature_required": True,
            "review_store_available": self._path is not None,
            **_safety_flags(),
        }

    def list_releases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if (
            self._path is None
            or not self._path.exists()
            or not self._table_exists("broker_adapter_release_manifests")
        ):
            return []
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM broker_adapter_release_manifests
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            manifest = _json_object(row["manifest_json"])
            preview = preview_broker_adapter_release_manifest(
                _json(manifest),
                source_name=str(row["source_name"]),
            )
            blockers: list[str] = []
            if str(row["manifest_fingerprint"]) != str(
                preview.get("manifest_fingerprint") or ""
            ):
                blockers.append("broker_adapter_release_manifest_integrity_invalid")
            blockers.extend(str(item) for item in preview.get("record_blockers") or [])
            current = self._latest_review(
                str(row["release_evidence_ref"]),
            )
            results.append(
                {
                    "schema_version": (
                        SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_LIST_SCHEMA_VERSION
                    ),
                    "release_evidence_ref": str(row["release_evidence_ref"]),
                    "manifest_fingerprint": str(row["manifest_fingerprint"]),
                    "manifest": _manifest_from_preview(preview),
                    "current_review": current,
                    "blockers": list(dict.fromkeys(blockers)),
                    "reviewable": not blockers,
                    **_safety_flags(),
                }
            )
        return results

    def preview_dossier(
        self,
        *,
        manifest: Mapping[str, Any],
        source_name: str,
        review_id: str,
        decision: str,
        reviewed_at: str,
        reason_ref: str,
    ) -> dict[str, Any]:
        return self._build_dossier(
            manifest=manifest,
            source_name=source_name,
            review_id=review_id,
            decision=decision,
            reviewed_at=reviewed_at,
            reason_ref=reason_ref,
        )

    def record_review(
        self,
        *,
        manifest: Mapping[str, Any],
        source_name: str,
        review_id: str,
        decision: str,
        reviewed_at: str,
        reason_ref: str,
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        inputs = {
            "manifest": dict(manifest),
            "source_name": str(source_name or ""),
            "review_id": str(review_id or ""),
            "decision": str(decision or ""),
            "reviewed_at": str(reviewed_at or ""),
            "reason_ref": str(reason_ref or ""),
        }
        existing = self._existing_review(inputs["review_id"])
        if existing is not None:
            return self._resolve_exact_retry(
                row=existing,
                inputs=inputs,
                dossier_fingerprint=dossier_fingerprint,
                operator_label=operator_label,
                operator_approval_id=operator_approval_id,
                operator_proof_signature_base64=operator_proof_signature_base64,
                acknowledgement=acknowledgement,
            )

        dossier = self._build_dossier(**inputs)
        blockers = list(dossier["review_blockers"])
        if str(dossier_fingerprint or "") != dossier["dossier_fingerprint"]:
            blockers.append("signed_broker_adapter_review_dossier_fingerprint_mismatch")
        if acknowledgement != BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT:
            blockers.append("signed_broker_adapter_review_acknowledgement_mismatch")
        normalized_operator = str(operator_label or "").strip()
        if not _ID_PATTERN.fullmatch(normalized_operator):
            blockers.append("signed_broker_adapter_review_operator_invalid")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=str(operator_approval_id or ""),
            proof_signature_base64=str(operator_proof_signature_base64 or ""),
            expected_action=SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ACTION,
            expected_artifact_type=(SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ARTIFACT_TYPE),
            expected_artifact_fingerprint=dossier["dossier_fingerprint"],
            clock=self._clock,
        )
        blockers.extend(approval_blockers)
        if approval and normalized_operator != str(approval.get("operator_id") or ""):
            blockers.append("signed_broker_adapter_review_operator_mismatch")
        if blockers:
            self._raise_rejected(
                "signed broker adapter review rejected",
                dossier=dossier,
                blockers=blockers,
            )
        if self._path is None:
            self._raise_rejected(
                "broker adapter review store unavailable",
                dossier=dossier,
                blockers=["signed_broker_adapter_review_store_unavailable"],
            )

        conformance = _mapping(dossier.get("conformance"))
        current = _mapping(dossier.get("current_review"))
        canonical_preview = preview_broker_adapter_release_manifest(
            _json(inputs["manifest"]),
            source_name=inputs["source_name"],
        )
        try:
            result = BrokerAdapterReleaseReviewRepository(self._path).record_review(
                canonical_preview,
                review_id=inputs["review_id"],
                decision=inputs["decision"],
                reviewer_ref=f"operator_approval:{operator_approval_id}",
                reviewed_at=inputs["reviewed_at"],
                reason_ref=inputs["reason_ref"],
                acknowledgement=acknowledgement,
                expected_conformance_run_id=(
                    str(conformance.get("run_id") or "")
                    if inputs["decision"] == "accepted"
                    else None
                ),
                expected_conformance_report_fingerprint=(
                    str(conformance.get("report_fingerprint") or "")
                    if inputs["decision"] == "accepted"
                    else None
                ),
                expected_latest_review_fingerprint=str(
                    current.get("review_fingerprint") or ""
                ),
            )
        except BrokerAdapterReleaseRejected as exc:
            self._raise_rejected(
                "signed broker adapter review transaction rejected",
                dossier=dossier,
                blockers=[str(item) for item in exc.evidence.get("blockers") or []],
            )
        return {
            **result,
            "dossier_fingerprint": dossier["dossier_fingerprint"],
            "operator_id": str(approval.get("operator_id") or ""),
            "operator_key_id": str(approval.get("key_id") or ""),
            "operator_public_key_fingerprint": str(
                approval.get("public_key_fingerprint") or ""
            ),
            "operator_approval_id": str(operator_approval_id),
            "operator_identity_verified": True,
            **_safety_flags(),
        }

    def _build_dossier(
        self,
        *,
        manifest: Mapping[str, Any],
        source_name: str,
        review_id: str,
        decision: str,
        reviewed_at: str,
        reason_ref: str,
    ) -> dict[str, Any]:
        preview = preview_broker_adapter_release_manifest(
            _json(dict(manifest)),
            source_name=str(source_name or ""),
        )
        normalized_decision = str(decision or "").strip().lower()
        normalized_review_id = str(review_id or "").strip()
        normalized_reason = str(reason_ref or "").strip()
        normalized_reviewed_at = _normalized_timestamp(reviewed_at)
        blockers = [str(item) for item in preview.get("record_blockers") or []]
        if normalized_decision not in _DECISIONS:
            blockers.append("signed_broker_adapter_review_decision_invalid")
        if not _ID_PATTERN.fullmatch(normalized_review_id):
            blockers.append("signed_broker_adapter_review_id_invalid")
        if not _ID_PATTERN.fullmatch(normalized_reason):
            blockers.append("signed_broker_adapter_review_reason_ref_invalid")
        if normalized_reviewed_at is None:
            blockers.append("signed_broker_adapter_reviewed_at_invalid")
        release_ref = str(preview.get("release_evidence_ref") or "")
        current = self._latest_review(release_ref)
        conformance = (
            self._conformance(preview)
            if normalized_decision == "accepted"
            else {
                "status": "not_required",
                "run_id": "",
                "report_fingerprint": "",
                "blockers": [],
            }
        )

        if normalized_decision == "accepted":
            blockers.extend(str(item) for item in preview.get("blockers") or [])
            blockers.extend(str(item) for item in conformance.get("blockers") or [])
            if current.get("status") == "revoked":
                blockers.append("broker_adapter_release_revoked_requires_new_release")
            blockers.extend(
                str(item) for item in current.get("integrity_blockers") or []
            )
        elif normalized_decision == "revoked":
            if current.get("status") != "accepted":
                blockers.append("broker_adapter_release_revoke_without_acceptance")
            if str(current.get("manifest_fingerprint") or "") != str(
                preview.get("manifest_fingerprint") or ""
            ):
                blockers.append("broker_adapter_release_review_manifest_mismatch")

        unique_blockers = list(dict.fromkeys(blockers))
        core = {
            "schema_version": (
                SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_DOSSIER_SCHEMA_VERSION
            ),
            "action": SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ACTION,
            "review_id": normalized_review_id,
            "decision": normalized_decision,
            "reviewed_at": (
                normalized_reviewed_at
                if normalized_reviewed_at is not None
                else str(reviewed_at or "")
            ),
            "reason_ref": normalized_reason,
            "manifest": _manifest_from_preview(preview),
            "manifest_fingerprint": str(preview.get("manifest_fingerprint") or ""),
            "manifest_evidence": {
                "file_fingerprint": str(preview.get("file_fingerprint") or ""),
                "source_name": str(preview.get("source_name") or ""),
                "validation_status": str(preview.get("validation_status") or ""),
                "recordable": preview.get("recordable") is True,
                "blockers": [str(item) for item in preview.get("blockers") or []],
                "record_blockers": [
                    str(item) for item in preview.get("record_blockers") or []
                ],
            },
            "current_review": current,
            "conformance": conformance,
        }
        dossier_fingerprint = _fingerprint(core)
        return {
            **core,
            "dossier_fingerprint": dossier_fingerprint,
            "generated_at": _aware_utc(self._clock()).isoformat(),
            "review_status": (
                "ready_for_signature" if not unique_blockers else "blocked"
            ),
            "review_ready": not unique_blockers,
            "review_blockers": unique_blockers,
            "required_operator_approval": {
                "action": SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ACTION,
                "artifact_type": (SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ARTIFACT_TYPE),
                "artifact_fingerprint": dossier_fingerprint,
            },
            **_safety_flags(),
        }

    def _conformance(self, preview: Mapping[str, Any]) -> dict[str, Any]:
        release_ref = str(preview.get("release_evidence_ref") or "")
        if self._path is None:
            return {
                "status": "blocked",
                "run_id": "",
                "report_fingerprint": "",
                "blockers": ["broker_adapter_conformance_store_unavailable"],
            }
        return BrokerAdapterConformanceRepository(
            self._path,
            ensure_schema=False,
        ).verify_release_binding(
            release_evidence_ref=release_ref,
            manifest_fingerprint=str(preview.get("manifest_fingerprint") or ""),
        )

    def _latest_review(self, release_evidence_ref: str) -> dict[str, Any]:
        release_ref = str(release_evidence_ref or "").strip()
        if (
            self._path is None
            or not self._path.exists()
            or not self._table_exists("broker_adapter_release_review_events")
        ):
            return {
                "status": "not_configured",
                "release_evidence_ref": release_ref,
                "review_fingerprint": "",
                "integrity_blockers": [],
            }
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM broker_adapter_release_review_events
                WHERE release_evidence_ref = ? ORDER BY id DESC LIMIT 1
                """,
                (release_ref,),
            ).fetchone()
        if row is None:
            return {
                "status": "not_found",
                "release_evidence_ref": release_ref,
                "review_fingerprint": "",
                "integrity_blockers": [],
            }
        return self._review_row(row, reused=False)

    def _existing_review(self, review_id: str) -> sqlite3.Row | None:
        normalized = str(review_id or "").strip()
        if (
            self._path is None
            or not self._path.exists()
            or not self._table_exists("broker_adapter_release_review_events")
        ):
            return None
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                """
                SELECT * FROM broker_adapter_release_review_events
                WHERE review_id = ? LIMIT 1
                """,
                (normalized,),
            ).fetchone()

    def _resolve_exact_retry(
        self,
        *,
        row: sqlite3.Row,
        inputs: dict[str, Any],
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = preview_broker_adapter_release_manifest(
            _json(inputs["manifest"]),
            source_name=inputs["source_name"],
        )
        blockers: list[str] = []
        if acknowledgement != BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT:
            blockers.append("signed_broker_adapter_review_acknowledgement_mismatch")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=str(operator_approval_id or ""),
            proof_signature_base64=str(operator_proof_signature_base64 or ""),
            expected_action=SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ACTION,
            expected_artifact_type=(SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ARTIFACT_TYPE),
            expected_artifact_fingerprint=str(dossier_fingerprint or ""),
            clock=self._clock,
        )
        blockers.extend(approval_blockers)
        normalized_operator = str(operator_label or "").strip()
        if approval and normalized_operator != str(approval.get("operator_id") or ""):
            blockers.append("signed_broker_adapter_review_operator_mismatch")
        normalized_reviewed_at = _normalized_timestamp(inputs["reviewed_at"])
        expected = {
            "review_id": inputs["review_id"],
            "release_evidence_ref": str(preview.get("release_evidence_ref") or ""),
            "manifest_fingerprint": str(preview.get("manifest_fingerprint") or ""),
            "decision": str(inputs["decision"] or "").strip().lower(),
            "reviewer_ref": f"operator_approval:{operator_approval_id}",
            "reviewed_at": normalized_reviewed_at or "",
            "reason_ref": str(inputs["reason_ref"] or "").strip(),
        }
        for field, value in expected.items():
            if str(row[field]) != str(value):
                blockers.append(f"signed_broker_adapter_review_retry_drift:{field}")
        response = self._review_row(row, reused=True)
        blockers.extend(response["integrity_blockers"])
        if blockers:
            self._raise_rejected(
                "signed broker adapter review retry rejected",
                dossier={
                    "dossier_fingerprint": str(dossier_fingerprint or ""),
                    "review_id": inputs["review_id"],
                },
                blockers=blockers,
            )
        return {
            **response,
            "dossier_fingerprint": str(dossier_fingerprint),
            "operator_id": str(approval.get("operator_id") or ""),
            "operator_key_id": str(approval.get("key_id") or ""),
            "operator_public_key_fingerprint": str(
                approval.get("public_key_fingerprint") or ""
            ),
            "operator_approval_id": str(operator_approval_id),
            "operator_identity_verified": True,
            **_safety_flags(),
        }

    def _review_row(self, row: sqlite3.Row, *, reused: bool) -> dict[str, Any]:
        expected_fingerprint = _review_fingerprint(row)
        actual_fingerprint = str(row["review_fingerprint"])
        integrity_blockers = (
            []
            if actual_fingerprint == expected_fingerprint
            else ["broker_adapter_release_review_integrity_invalid"]
        )
        return {
            "schema_version": BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION,
            "status": str(row["decision"]),
            "review_id": str(row["review_id"]),
            "release_evidence_ref": str(row["release_evidence_ref"]),
            "manifest_fingerprint": str(row["manifest_fingerprint"]),
            "decision": str(row["decision"]),
            "reviewer_ref": str(row["reviewer_ref"]),
            "reviewed_at": str(row["reviewed_at"]),
            "reason_ref": str(row["reason_ref"]),
            "conformance_run_id": _row_text(row, "conformance_run_id"),
            "conformance_report_fingerprint": _row_text(
                row,
                "conformance_report_fingerprint",
            ),
            "review_fingerprint": actual_fingerprint,
            "integrity_blockers": integrity_blockers,
            "persisted": True,
            "reused": reused,
            "created_at": str(row["created_at"]),
        }

    def _counts(self) -> tuple[int, int]:
        if self._path is None or not self._path.exists():
            return 0, 0
        with sqlite3.connect(self._path) as conn:
            manifests = (
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM broker_adapter_release_manifests"
                    ).fetchone()[0]
                )
                if self._table_exists("broker_adapter_release_manifests")
                else 0
            )
            reviews = (
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM broker_adapter_release_review_events"
                    ).fetchone()[0]
                )
                if self._table_exists("broker_adapter_release_review_events")
                else 0
            )
        return manifests, reviews

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

    def _raise_rejected(
        self,
        message: str,
        *,
        dossier: Mapping[str, Any],
        blockers: list[str],
    ) -> None:
        payload = {
            "schema_version": (
                SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_DOSSIER_SCHEMA_VERSION
            ),
            "status": "rejected",
            "review_id": str(dossier.get("review_id") or ""),
            "dossier_fingerprint": str(dossier.get("dossier_fingerprint") or ""),
            "blockers": list(dict.fromkeys(str(item) for item in blockers)),
            **_safety_flags(),
        }
        try:
            attempt_id = _fingerprint(payload)
            existing = self._db.list_events_sync(
                event_type="broker_adapter_release.signed_review_rejected",
                entity_type="broker_adapter_release_review_rejection",
                entity_id=attempt_id,
                source="signed_broker_adapter_release_review",
                limit=1,
            )
            if not existing:
                self._db.append_event_sync(
                    event_type="broker_adapter_release.signed_review_rejected",
                    timestamp=_aware_utc(self._clock()).isoformat(),
                    entity_type="broker_adapter_release_review_rejection",
                    entity_id=attempt_id,
                    source="signed_broker_adapter_release_review",
                    source_ref=payload["dossier_fingerprint"] or payload["review_id"],
                    payload={"attempt_id": attempt_id, **payload},
                )
        except Exception:
            pass
        raise SignedBrokerAdapterReleaseReviewRejected(message, evidence=payload)


def _manifest_from_preview(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION,
        "release_evidence_ref": str(value.get("release_evidence_ref") or ""),
        "collector_id": str(value.get("collector_id") or ""),
        "deployment_id": str(value.get("deployment_id") or ""),
        "collector_version": str(value.get("collector_version") or ""),
        "deployment_fingerprint": str(value.get("deployment_fingerprint") or ""),
        "provider": str(value.get("provider") or ""),
        "gateway_id": str(value.get("gateway_id") or ""),
        "account_alias": str(value.get("account_alias") or ""),
        "adapter_authorization_ref": str(value.get("adapter_authorization_ref") or ""),
        "collection_modes": list(value.get("collection_modes") or []),
        "capabilities": _mapping(value.get("capabilities")),
        "boundaries": _mapping(value.get("boundaries")),
        "review_refs": _mapping(value.get("review_refs")),
        "limitations": list(value.get("limitations") or []),
    }


def _review_fingerprint(row: sqlite3.Row) -> str:
    return _fingerprint(
        {
            "review_id": str(row["review_id"]),
            "release_evidence_ref": str(row["release_evidence_ref"]),
            "manifest_fingerprint": str(row["manifest_fingerprint"]),
            "decision": str(row["decision"]),
            "reviewer_ref": str(row["reviewer_ref"]),
            "reviewed_at": str(row["reviewed_at"]),
            "reason_ref": str(row["reason_ref"]),
            "conformance_run_id": _row_text(row, "conformance_run_id"),
            "conformance_report_fingerprint": _row_text(
                row,
                "conformance_report_fingerprint",
            ),
        }
    )


def _row_text(row: sqlite3.Row, field: str) -> str:
    return str(row[field]) if field in row.keys() else ""


def _normalized_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _database_path(db: Any) -> Path | None:
    value = getattr(db, "_path", None)
    return Path(value) if value is not None else None


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


def _safety_flags() -> dict[str, bool]:
    return {
        "provider_contact_performed": False,
        "adapter_registered": False,
        "broker_submission_enabled": False,
        "broker_cancellation_enabled": False,
        "capital_authority_changed": False,
        "authorizes_execution": False,
        "stores_broker_credentials": False,
        "strategy_direct_adapter_access_allowed": False,
        "ai_direct_adapter_access_allowed": False,
    }


__all__ = [
    "SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ACTION",
    "SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ARTIFACT_TYPE",
    "SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_DOSSIER_SCHEMA_VERSION",
    "SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_LIST_SCHEMA_VERSION",
    "SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_STATUS_SCHEMA_VERSION",
    "SignedBrokerAdapterReleaseReviewRejected",
    "SignedBrokerAdapterReleaseReviewService",
]
