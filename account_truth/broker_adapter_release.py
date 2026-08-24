"""Broker-neutral adapter release review evidence and collector binding gates."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from account_truth.broker_adapter_conformance import (
    BrokerAdapterConformanceRepository,
)
from account_truth.broker_adapter_release_manifest import (
    BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION,
    BROKER_ADAPTER_RELEASE_PREVIEW_SCHEMA_VERSION,
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION,
)
from account_truth.broker_adapter_release_manifest import (
    EXPECTED_BOUNDARIES as _EXPECTED_BOUNDARIES,
)
from account_truth.broker_adapter_release_manifest import (
    LIVE_COLLECTION_MODES as _LIVE_COLLECTION_MODES,
)
from account_truth.broker_adapter_release_manifest import (
    MAX_BROKER_ADAPTER_RELEASE_MANIFEST_BYTES,
)
from account_truth.broker_adapter_release_manifest import (
    REVIEW_DECISIONS as _REVIEW_DECISIONS,
)
from account_truth.broker_adapter_release_manifest import fingerprint as _fingerprint
from account_truth.broker_adapter_release_manifest import json_object as _json_object
from account_truth.broker_adapter_release_manifest import json_text as _json
from account_truth.broker_adapter_release_manifest import (
    manifest_core as _manifest_core,
)
from account_truth.broker_adapter_release_manifest import normalize_id as _id
from account_truth.broker_adapter_release_manifest import (
    preview_broker_adapter_release_manifest,
)
from account_truth.broker_adapter_release_manifest import (
    preview_integrity_blockers as _preview_integrity_blockers,
)
from account_truth.broker_adapter_release_manifest import rejection as _rejection
from account_truth.broker_adapter_release_manifest import row_text as _row_text
from account_truth.broker_adapter_release_manifest import safety_flags as _safety_flags
from account_truth.broker_adapter_release_manifest import timestamp as _timestamp
from account_truth.broker_adapter_release_manifest import (
    verification_blocked as _verification_blocked,
)

__all__ = [
    "BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION",
    "BROKER_ADAPTER_RELEASE_PREVIEW_SCHEMA_VERSION",
    "BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT",
    "BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION",
    "MAX_BROKER_ADAPTER_RELEASE_MANIFEST_BYTES",
    "BrokerAdapterReleaseRejected",
    "BrokerAdapterReleaseReviewRepository",
    "preview_broker_adapter_release_manifest",
]


class BrokerAdapterReleaseRejected(ValueError):
    """Raised when release evidence cannot be safely reviewed or recorded."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


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
