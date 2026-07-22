"""Broker-neutral adapter release review evidence and collector binding gates."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from account_truth.broker_adapter_conformance import (
    BrokerAdapterConformanceRepository,
)

BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION = (
    "karkinos.broker_adapter_release_manifest.v1"
)
BROKER_ADAPTER_RELEASE_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_adapter_release_preview.v1"
)
BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION = (
    "karkinos.broker_adapter_release_review.v1"
)
BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT = (
    "review_broker_adapter_release_without_registration_or_execution_authority"
)
MAX_BROKER_ADAPTER_RELEASE_MANIFEST_BYTES = 512 * 1024

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "release_evidence_ref",
        "collector_id",
        "deployment_id",
        "collector_version",
        "deployment_fingerprint",
        "provider",
        "gateway_id",
        "account_alias",
        "adapter_authorization_ref",
        "collection_modes",
        "capabilities",
        "boundaries",
        "review_refs",
        "limitations",
    }
)
_CAPABILITY_FIELDS = frozenset(
    {
        "can_read_account",
        "can_read_cash",
        "can_read_positions",
        "can_read_orders",
        "can_read_fills",
        "can_read_market_session",
        "can_read_heartbeat",
        "can_submit_orders",
        "can_cancel_orders",
    }
)
_EXPECTED_BOUNDARIES = {
    "runtime_auth_material_external": True,
    "strategy_imports_adapter": False,
    "ai_imports_adapter": False,
    "core_imports_provider_sdk": False,
    "writes_oms": False,
    "writes_production_ledger": False,
    "writes_risk_state": False,
    "writes_kill_switch": False,
    "writes_capital_authority": False,
    "default_registered": False,
}
_BOUNDARY_FIELDS = frozenset(_EXPECTED_BOUNDARIES)
_REVIEW_REF_FIELDS = frozenset(
    {
        "adapter_adr",
        "capability_matrix",
        "threat_model",
        "deployment_runbook",
        "rollback_runbook",
        "privacy_review",
    }
)
_LIVE_COLLECTION_MODES = frozenset({"callback", "poll"})
_REVIEW_DECISIONS = frozenset({"accepted", "rejected", "revoked"})
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
)


class BrokerAdapterReleaseRejected(ValueError):
    """Raised when release evidence cannot be safely reviewed or recorded."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def preview_broker_adapter_release_manifest(
    content: str | bytes,
    *,
    source_name: str = "",
) -> dict[str, Any]:
    """Normalize one manifest without registering an adapter or contacting a broker."""

    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    record_blockers: list[str] = []
    blockers: list[str] = []
    text = ""
    if len(raw) > MAX_BROKER_ADAPTER_RELEASE_MANIFEST_BYTES:
        record_blockers.append("broker_adapter_release_manifest_too_large")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            record_blockers.append("broker_adapter_release_manifest_not_utf8")

    data: dict[str, Any] = {}
    if not record_blockers:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            record_blockers.append("broker_adapter_release_manifest_json_invalid")
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                record_blockers.append("broker_adapter_release_manifest_not_object")

    if _contains_sensitive_key(data):
        record_blockers.append("broker_adapter_release_auth_material_not_allowed")
    _reject_unknown_fields(data, _MANIFEST_FIELDS, "manifest", record_blockers)

    schema_version = str(data.get("schema_version") or "")
    if schema_version != BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION:
        record_blockers.append("broker_adapter_release_manifest_schema_unsupported")

    identities = {
        field: _id(data.get(field), field, record_blockers)
        for field in (
            "release_evidence_ref",
            "collector_id",
            "deployment_id",
            "collector_version",
            "provider",
            "gateway_id",
            "account_alias",
            "adapter_authorization_ref",
        )
    }
    identities["provider"] = identities["provider"].lower()
    deployment_fingerprint = (
        str(data.get("deployment_fingerprint") or "").strip().lower()
    )
    if not _FINGERPRINT_PATTERN.fullmatch(deployment_fingerprint):
        record_blockers.append("broker_adapter_release_deployment_fingerprint_invalid")

    collection_modes = _string_list(
        data.get("collection_modes"),
        field="collection_modes",
        blockers=record_blockers,
    )
    collection_modes = sorted(dict.fromkeys(item.lower() for item in collection_modes))
    if not collection_modes or any(
        item not in _LIVE_COLLECTION_MODES for item in collection_modes
    ):
        record_blockers.append("broker_adapter_release_collection_modes_invalid")

    capabilities = _boolean_object(
        data.get("capabilities"),
        allowed=_CAPABILITY_FIELDS,
        field="capabilities",
        blockers=record_blockers,
    )
    boundaries = _boolean_object(
        data.get("boundaries"),
        allowed=_BOUNDARY_FIELDS,
        field="boundaries",
        blockers=record_blockers,
    )
    review_refs = _reference_object(data.get("review_refs"), record_blockers)
    limitations = _string_list(
        data.get("limitations", []),
        field="limitations",
        blockers=record_blockers,
        allow_empty=True,
    )

    if capabilities and (
        capabilities.get("can_submit_orders") is not False
        or capabilities.get("can_cancel_orders") is not False
    ):
        blockers.append("broker_adapter_release_write_capability_present")
    for field, expected in _EXPECTED_BOUNDARIES.items():
        if boundaries and boundaries.get(field) is not expected:
            blockers.append(f"broker_adapter_release_boundary_violation:{field}")

    unique_record_blockers = list(dict.fromkeys(record_blockers))
    unique_blockers = list(dict.fromkeys([*record_blockers, *blockers]))
    core = {
        "schema_version": BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION,
        **identities,
        "deployment_fingerprint": deployment_fingerprint,
        "collection_modes": collection_modes,
        "capabilities": capabilities,
        "boundaries": boundaries,
        "review_refs": review_refs,
        "limitations": limitations,
    }
    manifest_fingerprint = _fingerprint(core)
    recordable = bool(
        not unique_record_blockers
        and all(str(value or "") for value in identities.values())
        and deployment_fingerprint
        and collection_modes
        and capabilities
        and boundaries
        and review_refs
    )
    return {
        **core,
        "schema_version": BROKER_ADAPTER_RELEASE_PREVIEW_SCHEMA_VERSION,
        "manifest_fingerprint": manifest_fingerprint,
        "file_fingerprint": hashlib.sha256(raw).hexdigest(),
        "source_name": _sanitized_source_name(source_name),
        "validation_status": "pass" if not unique_blockers else "blocked",
        "recordable": recordable,
        "blockers": unique_blockers,
        "record_blockers": unique_record_blockers,
        **_safety_flags(),
    }


class BrokerAdapterReleaseReviewRepository:
    """Persist append-only human reviews and verify exact collector bindings."""

    def __init__(
        self,
        path: str | Path,
        *,
        ensure_schema: bool = True,
    ) -> None:
        self._path = Path(path)
        if ensure_schema:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    def record_review(
        self,
        preview: dict[str, Any],
        *,
        review_id: str,
        decision: str,
        reviewer_ref: str,
        reviewed_at: str,
        reason_ref: str,
        acknowledgement: str,
        expected_conformance_run_id: str | None = None,
        expected_conformance_report_fingerprint: str | None = None,
        expected_latest_review_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """Append one explicit review decision without registering the adapter."""

        if acknowledgement != BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT:
            raise BrokerAdapterReleaseRejected(
                "adapter release review acknowledgement mismatch",
                evidence=_rejection(
                    preview,
                    ["broker_adapter_release_review_acknowledgement_mismatch"],
                ),
            )
        if str(
            preview.get("schema_version") or ""
        ) != BROKER_ADAPTER_RELEASE_PREVIEW_SCHEMA_VERSION or not bool(
            preview.get("recordable")
        ):
            raise BrokerAdapterReleaseRejected(
                "adapter release preview is not recordable",
                evidence=_rejection(
                    preview,
                    [
                        "broker_adapter_release_preview_not_recordable",
                        *[str(item) for item in preview.get("record_blockers") or []],
                    ],
                ),
            )
        integrity_blockers = _preview_integrity_blockers(preview)
        if integrity_blockers:
            raise BrokerAdapterReleaseRejected(
                "adapter release preview integrity invalid",
                evidence=_rejection(preview, integrity_blockers),
            )

        normalized_review_id = _required_id(review_id, "review_id")
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in _REVIEW_DECISIONS:
            raise BrokerAdapterReleaseRejected(
                "adapter release review decision invalid",
                evidence=_rejection(
                    preview,
                    ["broker_adapter_release_review_decision_invalid"],
                ),
            )
        normalized_reviewer = _required_id(reviewer_ref, "reviewer_ref")
        normalized_reason = _required_id(reason_ref, "reason_ref")
        normalized_reviewed_at = _timestamp(reviewed_at)
        if not normalized_reviewed_at:
            raise BrokerAdapterReleaseRejected(
                "adapter release reviewed_at invalid",
                evidence=_rejection(
                    preview,
                    ["broker_adapter_release_reviewed_at_invalid"],
                ),
            )
        if normalized_decision == "accepted" and preview.get("blockers"):
            raise BrokerAdapterReleaseRejected(
                "blocked adapter release cannot be accepted",
                evidence=_rejection(
                    preview,
                    [
                        "broker_adapter_release_acceptance_blocked",
                        *[str(item) for item in preview.get("blockers") or []],
                    ],
                ),
            )

        release_ref = str(preview["release_evidence_ref"])
        manifest_fingerprint = str(preview["manifest_fingerprint"])
        conformance_run_id = ""
        conformance_report_fingerprint = ""
        if normalized_decision == "accepted":
            conformance = BrokerAdapterConformanceRepository(
                self._path,
                ensure_schema=False,
            ).verify_release_binding(
                release_evidence_ref=release_ref,
                manifest_fingerprint=manifest_fingerprint,
            )
            if conformance.get("blockers"):
                raise BrokerAdapterReleaseRejected(
                    "adapter release conformance evidence is blocked",
                    evidence=_rejection(
                        preview,
                        [
                            "broker_adapter_release_conformance_blocked",
                            *[str(item) for item in conformance.get("blockers") or []],
                        ],
                    ),
                )
            conformance_run_id = str(conformance["run_id"])
            conformance_report_fingerprint = str(conformance["report_fingerprint"])
            if (
                expected_conformance_run_id is not None
                and str(expected_conformance_run_id) != conformance_run_id
            ):
                raise BrokerAdapterReleaseRejected(
                    "adapter release conformance changed after review preview",
                    evidence=_rejection(
                        preview,
                        ["broker_adapter_release_conformance_run_drift"],
                    ),
                )
            if (
                expected_conformance_report_fingerprint is not None
                and str(expected_conformance_report_fingerprint)
                != conformance_report_fingerprint
            ):
                raise BrokerAdapterReleaseRejected(
                    "adapter release conformance changed after review preview",
                    evidence=_rejection(
                        preview,
                        ["broker_adapter_release_conformance_fingerprint_drift"],
                    ),
                )
        manifest_payload = _manifest_core(preview)
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            manifest = conn.execute(
                """
                SELECT * FROM broker_adapter_release_manifests
                WHERE release_evidence_ref = ? LIMIT 1
                """,
                (release_ref,),
            ).fetchone()
            if manifest is not None and str(manifest["manifest_fingerprint"]) != (
                manifest_fingerprint
            ):
                conn.rollback()
                raise BrokerAdapterReleaseRejected(
                    "release evidence ref was reused with a different manifest",
                    evidence=_rejection(
                        preview,
                        ["broker_adapter_release_evidence_ref_conflict"],
                    ),
                )
            if manifest is None:
                conn.execute(
                    """
                    INSERT INTO broker_adapter_release_manifests (
                        release_evidence_ref, manifest_fingerprint,
                        file_fingerprint, source_name, manifest_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_ref,
                        manifest_fingerprint,
                        str(preview["file_fingerprint"]),
                        str(preview["source_name"]),
                        _json(manifest_payload),
                        now,
                    ),
                )

            existing_review = conn.execute(
                """
                SELECT * FROM broker_adapter_release_review_events
                WHERE review_id = ? LIMIT 1
                """,
                (normalized_review_id,),
            ).fetchone()
            expected_review_fingerprint = _fingerprint(
                {
                    "review_id": normalized_review_id,
                    "release_evidence_ref": release_ref,
                    "manifest_fingerprint": manifest_fingerprint,
                    "decision": normalized_decision,
                    "reviewer_ref": normalized_reviewer,
                    "reviewed_at": normalized_reviewed_at,
                    "reason_ref": normalized_reason,
                    "conformance_run_id": conformance_run_id,
                    "conformance_report_fingerprint": conformance_report_fingerprint,
                }
            )
            if existing_review is not None:
                if str(existing_review["review_fingerprint"]) != (
                    expected_review_fingerprint
                ):
                    conn.rollback()
                    raise BrokerAdapterReleaseRejected(
                        "adapter release review id conflict",
                        evidence=_rejection(
                            preview,
                            ["broker_adapter_release_review_id_conflict"],
                        ),
                    )
                conn.commit()
                return self._review_response(existing_review, reused=True)

            latest = conn.execute(
                """
                SELECT * FROM broker_adapter_release_review_events
                WHERE release_evidence_ref = ? ORDER BY id DESC LIMIT 1
                """,
                (release_ref,),
            ).fetchone()
            actual_latest_review_fingerprint = (
                str(latest["review_fingerprint"]) if latest is not None else ""
            )
            if (
                expected_latest_review_fingerprint is not None
                and str(expected_latest_review_fingerprint)
                != actual_latest_review_fingerprint
            ):
                conn.rollback()
                raise BrokerAdapterReleaseRejected(
                    "adapter release review changed after signed preview",
                    evidence=_rejection(
                        preview,
                        ["broker_adapter_release_latest_review_drift"],
                    ),
                )
            if (
                latest is not None
                and str(latest["decision"]) == "revoked"
                and normalized_decision == "accepted"
            ):
                conn.rollback()
                raise BrokerAdapterReleaseRejected(
                    "revoked adapter release cannot be resumed",
                    evidence=_rejection(
                        preview,
                        ["broker_adapter_release_revoked_requires_new_release"],
                    ),
                )
            if normalized_decision == "revoked" and (
                latest is None or str(latest["decision"]) != "accepted"
            ):
                conn.rollback()
                raise BrokerAdapterReleaseRejected(
                    "only an accepted adapter release can be revoked",
                    evidence=_rejection(
                        preview,
                        ["broker_adapter_release_revoke_without_acceptance"],
                    ),
                )

            conn.execute(
                """
                INSERT INTO broker_adapter_release_review_events (
                    review_id, release_evidence_ref, manifest_fingerprint,
                    decision, reviewer_ref, reviewed_at, reason_ref,
                    conformance_run_id, conformance_report_fingerprint,
                    review_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_review_id,
                    release_ref,
                    manifest_fingerprint,
                    normalized_decision,
                    normalized_reviewer,
                    normalized_reviewed_at,
                    normalized_reason,
                    conformance_run_id,
                    conformance_report_fingerprint,
                    expected_review_fingerprint,
                    now,
                ),
            )
            saved = conn.execute(
                """
                SELECT * FROM broker_adapter_release_review_events
                WHERE review_id = ? LIMIT 1
                """,
                (normalized_review_id,),
            ).fetchone()
            conn.commit()
        if saved is None:
            raise RuntimeError("adapter release review was not persisted")
        return self._review_response(saved, reused=False)

    def verify_collector_binding(
        self,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Verify the latest accepted review for one live collector batch."""

        collection_mode = str(value.get("collection_mode") or "").strip().lower()
        if collection_mode not in _LIVE_COLLECTION_MODES:
            return {
                "status": "not_required",
                "review_id": "",
                "release_evidence_ref": str(value.get("release_evidence_ref") or ""),
                "manifest_fingerprint": "",
                "blockers": [],
                **_safety_flags(),
            }
        release_ref = str(value.get("release_evidence_ref") or "").strip()
        if (
            not self._path.exists()
            or not self._table_exists("broker_adapter_release_manifests")
            or not self._table_exists("broker_adapter_release_review_events")
        ):
            return _verification_blocked(
                release_ref,
                ["broker_adapter_release_review_not_found"],
            )

        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            manifest = conn.execute(
                """
                SELECT * FROM broker_adapter_release_manifests
                WHERE release_evidence_ref = ? LIMIT 1
                """,
                (release_ref,),
            ).fetchone()
            review = conn.execute(
                """
                SELECT * FROM broker_adapter_release_review_events
                WHERE release_evidence_ref = ? ORDER BY id DESC LIMIT 1
                """,
                (release_ref,),
            ).fetchone()
        if manifest is None or review is None:
            return _verification_blocked(
                release_ref,
                ["broker_adapter_release_review_not_found"],
            )

        manifest_payload = _json_object(manifest["manifest_json"])
        blockers: list[str] = []
        manifest_fingerprint = str(manifest["manifest_fingerprint"])
        if manifest_fingerprint != _fingerprint(manifest_payload):
            blockers.append("broker_adapter_release_manifest_integrity_invalid")
        if str(review["manifest_fingerprint"]) != manifest_fingerprint:
            blockers.append("broker_adapter_release_review_manifest_mismatch")
        if str(review["review_fingerprint"]) != _fingerprint(
            {
                "review_id": str(review["review_id"]),
                "release_evidence_ref": str(review["release_evidence_ref"]),
                "manifest_fingerprint": str(review["manifest_fingerprint"]),
                "decision": str(review["decision"]),
                "reviewer_ref": str(review["reviewer_ref"]),
                "reviewed_at": str(review["reviewed_at"]),
                "reason_ref": str(review["reason_ref"]),
                "conformance_run_id": _row_text(review, "conformance_run_id"),
                "conformance_report_fingerprint": _row_text(
                    review,
                    "conformance_report_fingerprint",
                ),
            }
        ):
            blockers.append("broker_adapter_release_review_integrity_invalid")
        if str(review["decision"]) != "accepted":
            blockers.append("broker_adapter_release_review_not_accepted")

        for field in (
            "release_evidence_ref",
            "collector_id",
            "deployment_id",
            "collector_version",
            "deployment_fingerprint",
            "provider",
            "gateway_id",
            "account_alias",
            "adapter_authorization_ref",
        ):
            if str(manifest_payload.get(field) or "") != str(value.get(field) or ""):
                blockers.append(f"broker_adapter_release_manifest_drift:{field}")

        approved_modes = {
            str(item).lower() for item in manifest_payload.get("collection_modes") or []
        }
        if collection_mode not in approved_modes:
            blockers.append("broker_adapter_release_collection_mode_not_approved")
        capabilities = _json_object(manifest_payload.get("capabilities"))
        for capability in ("can_read_orders", "can_read_fills"):
            if capabilities.get(capability) is not True:
                blockers.append(
                    f"broker_adapter_release_capability_missing:{capability}"
                )
        if (
            capabilities.get("can_submit_orders") is not False
            or capabilities.get("can_cancel_orders") is not False
        ):
            blockers.append("broker_adapter_release_write_capability_present")
        boundaries = _json_object(manifest_payload.get("boundaries"))
        for field, expected in _EXPECTED_BOUNDARIES.items():
            if boundaries.get(field) is not expected:
                blockers.append(f"broker_adapter_release_boundary_invalid:{field}")

        conformance_run_id = ""
        conformance_report_fingerprint = ""
        if str(review["decision"]) == "accepted":
            conformance = BrokerAdapterConformanceRepository(
                self._path,
                ensure_schema=False,
            ).verify_release_binding(
                release_evidence_ref=release_ref,
                manifest_fingerprint=manifest_fingerprint,
            )
            blockers.extend(str(item) for item in conformance.get("blockers") or [])
            conformance_run_id = str(conformance.get("run_id") or "")
            conformance_report_fingerprint = str(
                conformance.get("report_fingerprint") or ""
            )
            if not _row_text(review, "conformance_run_id") or not _row_text(
                review,
                "conformance_report_fingerprint",
            ):
                blockers.append("broker_adapter_release_conformance_binding_missing")
            elif (
                _row_text(review, "conformance_run_id") != conformance_run_id
                or _row_text(review, "conformance_report_fingerprint")
                != conformance_report_fingerprint
            ):
                blockers.append("broker_adapter_release_conformance_review_drift")

        unique_blockers = list(dict.fromkeys(blockers))
        return {
            "status": "clear" if not unique_blockers else "blocked",
            "review_id": str(review["review_id"]),
            "release_evidence_ref": release_ref,
            "manifest_fingerprint": manifest_fingerprint,
            "conformance_run_id": conformance_run_id,
            "conformance_report_fingerprint": conformance_report_fingerprint,
            "blockers": unique_blockers,
            **_safety_flags(),
        }

    def get_status(self, release_evidence_ref: str) -> dict[str, Any]:
        """Read the latest review decision without creating schema or provider I/O."""

        release_ref = str(release_evidence_ref or "").strip()
        if not self._path.exists() or not self._table_exists(
            "broker_adapter_release_review_events"
        ):
            return {
                "status": "not_configured",
                "release_evidence_ref": release_ref,
                **_safety_flags(),
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
                **_safety_flags(),
            }
        return self._review_response(row, reused=False)

    def _review_response(
        self,
        row: sqlite3.Row,
        *,
        reused: bool,
    ) -> dict[str, Any]:
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
            "review_fingerprint": str(row["review_fingerprint"]),
            "persisted": True,
            "reused": reused,
            "created_at": str(row["created_at"]),
            **_safety_flags(),
        }

    def _table_exists(self, table: str) -> bool:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            return row is not None

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS broker_adapter_release_manifests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    release_evidence_ref TEXT NOT NULL UNIQUE,
                    manifest_fingerprint TEXT NOT NULL,
                    file_fingerprint TEXT NOT NULL,
                    source_name TEXT NOT NULL DEFAULT '',
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS broker_adapter_release_review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id TEXT NOT NULL UNIQUE,
                    release_evidence_ref TEXT NOT NULL,
                    manifest_fingerprint TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN (
                        'accepted', 'rejected', 'revoked'
                    )),
                    reviewer_ref TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    reason_ref TEXT NOT NULL,
                    conformance_run_id TEXT NOT NULL DEFAULT '',
                    conformance_report_fingerprint TEXT NOT NULL DEFAULT '',
                    review_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_broker_adapter_release_review_latest
                ON broker_adapter_release_review_events(
                    release_evidence_ref, id DESC
                );
                """)
            columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(broker_adapter_release_review_events)"
                ).fetchall()
            }
            for name in (
                "conformance_run_id",
                "conformance_report_fingerprint",
            ):
                if name not in columns:
                    conn.execute(
                        "ALTER TABLE broker_adapter_release_review_events "
                        f"ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
                    )
            conn.commit()


def _manifest_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION,
        "release_evidence_ref": str(value.get("release_evidence_ref") or ""),
        "collector_id": str(value.get("collector_id") or ""),
        "deployment_id": str(value.get("deployment_id") or ""),
        "collector_version": str(value.get("collector_version") or ""),
        "provider": str(value.get("provider") or ""),
        "gateway_id": str(value.get("gateway_id") or ""),
        "account_alias": str(value.get("account_alias") or ""),
        "adapter_authorization_ref": str(value.get("adapter_authorization_ref") or ""),
        "deployment_fingerprint": str(value.get("deployment_fingerprint") or ""),
        "collection_modes": list(value.get("collection_modes") or []),
        "capabilities": dict(value.get("capabilities") or {}),
        "boundaries": dict(value.get("boundaries") or {}),
        "review_refs": dict(value.get("review_refs") or {}),
        "limitations": list(value.get("limitations") or []),
    }


def _preview_integrity_blockers(preview: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    manifest_core = _manifest_core(preview)
    if str(preview.get("manifest_fingerprint") or "") != _fingerprint(manifest_core):
        blockers.append("broker_adapter_release_preview_fingerprint_drift")
    canonical = preview_broker_adapter_release_manifest(_json(manifest_core))
    for field in ("recordable", "validation_status", "blockers", "record_blockers"):
        if preview.get(field) != canonical.get(field):
            blockers.append(f"broker_adapter_release_preview_validation_drift:{field}")
    for field, expected in _safety_flags().items():
        if preview.get(field) is not expected:
            blockers.append(f"broker_adapter_release_preview_safety_drift:{field}")
    return list(dict.fromkeys(blockers))


def _verification_blocked(
    release_ref: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "review_id": "",
        "release_evidence_ref": release_ref,
        "manifest_fingerprint": "",
        "conformance_run_id": "",
        "conformance_report_fingerprint": "",
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _rejection(preview: Mapping[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION,
        "status": "rejected",
        "release_evidence_ref": str(preview.get("release_evidence_ref") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "explicit_review_required": True,
        "provider_contacted": False,
        "adapter_registered": False,
        "default_registered": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "authorizes_execution": False,
    }


def _boolean_object(
    value: Any,
    *,
    allowed: frozenset[str],
    field: str,
    blockers: list[str],
) -> dict[str, bool]:
    if not isinstance(value, dict):
        blockers.append(f"broker_adapter_release_{field}_invalid")
        return {}
    _reject_unknown_fields(value, allowed, field, blockers)
    result: dict[str, bool] = {}
    for name in sorted(allowed):
        item = value.get(name)
        if not isinstance(item, bool):
            blockers.append(f"broker_adapter_release_{field}_{name}_invalid")
            continue
        result[name] = item
    return result


def _reference_object(value: Any, blockers: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        blockers.append("broker_adapter_release_review_refs_invalid")
        return {}
    _reject_unknown_fields(value, _REVIEW_REF_FIELDS, "review_refs", blockers)
    return {
        field: _id(value.get(field), f"review_refs_{field}", blockers)
        for field in sorted(_REVIEW_REF_FIELDS)
    }


def _string_list(
    value: Any,
    *,
    field: str,
    blockers: list[str],
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        blockers.append(f"broker_adapter_release_{field}_invalid")
        return []
    result = [str(item).strip() for item in value]
    if (
        (not allow_empty and not result)
        or len(result) > 50
        or any(not item or len(item) > 256 for item in result)
    ):
        blockers.append(f"broker_adapter_release_{field}_invalid")
    return result[:50]


def _id(value: Any, field: str, blockers: list[str]) -> str:
    normalized = str(value or "").strip()
    if not _ID_PATTERN.fullmatch(normalized):
        blockers.append(f"broker_adapter_release_{field}_invalid")
    return normalized


def _required_id(value: Any, field: str) -> str:
    blockers: list[str] = []
    normalized = _id(value, field, blockers)
    if blockers:
        raise BrokerAdapterReleaseRejected(
            f"adapter release {field} invalid",
            evidence={
                "schema_version": BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION,
                "status": "rejected",
                "blockers": blockers,
                **_safety_flags(),
            },
        )
    return normalized


def _timestamp(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return ""
    return parsed.astimezone(UTC).isoformat()


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
            or _contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    prefix: str,
    blockers: list[str],
) -> None:
    for key in sorted(set(value) - allowed):
        blockers.append(f"broker_adapter_release_{prefix}_field_unsupported:{key}")


def _sanitized_source_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or "/" in name or "\\" in name:
        return "broker adapter release manifest"
    return name[:128]


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_text(row: sqlite3.Row, field: str) -> str:
    return str(row[field]) if field in row.keys() else ""
