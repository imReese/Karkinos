"""Provider-neutral deterministic broker adapter conformance evidence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION = (
    "karkinos.broker_adapter_conformance_result.v1"
)
BROKER_ADAPTER_CONFORMANCE_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_adapter_conformance_preview.v1"
)
BROKER_ADAPTER_CONFORMANCE_REPORT_SCHEMA_VERSION = (
    "karkinos.broker_adapter_conformance_report.v1"
)
BROKER_ADAPTER_CONFORMANCE_SUITE_VERSION = (
    "karkinos.broker_adapter_conformance_suite.v1"
)
BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT = "record_deterministic_broker_adapter_conformance_without_provider_contact_or_execution_authority"
BROKER_ADAPTER_CONFORMANCE_FIXTURE_KIND = "deterministic_local"

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "release_evidence_ref",
        "manifest_fingerprint",
        "suite_version",
        "fixture_kind",
        "scenarios",
        "provider_contacted",
        "adapter_registered",
        "broker_write_contacted",
    }
)
_SCENARIO_FIELDS = frozenset(
    {
        "scenario",
        "expected_status",
        "observed_status",
        "evidence_fingerprint",
    }
)
_EXPECTED_SCENARIO_STATUSES = {
    "healthy_snapshot": "healthy",
    "disconnected_snapshot": "blocked",
    "stale_snapshot": "blocked",
    "permission_limited_snapshot": "blocked",
    "incomplete_snapshot": "blocked",
    "snapshot_schema_drift": "blocked",
    "lifecycle_idempotent_replay": "reused",
    "lifecycle_duplicate": "duplicate",
    "lifecycle_out_of_order": "blocked",
    "lifecycle_disconnect": "blocked",
    "lifecycle_partial_batch": "blocked",
    "lifecycle_restart_replay": "recorded_and_reused",
}
_OBSERVED_STATUSES = frozenset(
    {
        "healthy",
        "blocked",
        "reused",
        "duplicate",
        "recorded_and_reused",
        "unexpected",
    }
)
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
)


class BrokerAdapterConformanceRejected(ValueError):
    """Raised when conformance evidence is malformed or cannot be recorded."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def preview_broker_adapter_conformance_result(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize a deterministic fixture result without provider or broker I/O."""

    data = dict(value)
    record_blockers: list[str] = []
    blockers: list[str] = []
    if _contains_sensitive_key(data):
        record_blockers.append("broker_adapter_conformance_auth_material_not_allowed")
    _reject_unknown_fields(data, _RESULT_FIELDS, "result", record_blockers)

    if str(data.get("schema_version") or "") != (
        BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION
    ):
        record_blockers.append("broker_adapter_conformance_schema_unsupported")
    run_id = _id(data.get("run_id"), "run_id", record_blockers)
    release_ref = _id(
        data.get("release_evidence_ref"),
        "release_evidence_ref",
        record_blockers,
    )
    manifest_fingerprint = str(data.get("manifest_fingerprint") or "").lower()
    if not _FINGERPRINT_PATTERN.fullmatch(manifest_fingerprint):
        record_blockers.append(
            "broker_adapter_conformance_manifest_fingerprint_invalid"
        )
    suite_version = str(data.get("suite_version") or "")
    if suite_version != BROKER_ADAPTER_CONFORMANCE_SUITE_VERSION:
        record_blockers.append("broker_adapter_conformance_suite_unsupported")
    fixture_kind = str(data.get("fixture_kind") or "")
    if fixture_kind != BROKER_ADAPTER_CONFORMANCE_FIXTURE_KIND:
        record_blockers.append("broker_adapter_conformance_fixture_kind_invalid")

    for field in (
        "provider_contacted",
        "adapter_registered",
        "broker_write_contacted",
    ):
        if data.get(field) is not False:
            record_blockers.append(f"broker_adapter_conformance_{field}_invalid")

    scenarios = _normalize_scenarios(data.get("scenarios"), record_blockers, blockers)
    unique_record_blockers = list(dict.fromkeys(record_blockers))
    unique_blockers = list(dict.fromkeys([*record_blockers, *blockers]))
    core = {
        "schema_version": BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "release_evidence_ref": release_ref,
        "manifest_fingerprint": manifest_fingerprint,
        "suite_version": suite_version,
        "fixture_kind": fixture_kind,
        "scenarios": scenarios,
        "provider_contacted": False,
        "adapter_registered": False,
        "broker_write_contacted": False,
    }
    report_fingerprint = _fingerprint(core)
    recordable = bool(
        not unique_record_blockers
        and run_id
        and release_ref
        and manifest_fingerprint
        and len(scenarios) == len(_EXPECTED_SCENARIO_STATUSES)
    )
    return {
        **core,
        "schema_version": BROKER_ADAPTER_CONFORMANCE_PREVIEW_SCHEMA_VERSION,
        "report_fingerprint": report_fingerprint,
        "validation_status": "passed" if not unique_blockers else "blocked",
        "recordable": recordable,
        "blockers": unique_blockers,
        "record_blockers": unique_record_blockers,
        **_safety_flags(),
    }


class BrokerAdapterConformanceRepository:
    """Persist append-only fixture reports and resolve an exact release binding."""

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

    def record_report(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Append one local deterministic report, including failed reports."""

        if acknowledgement != BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT:
            raise BrokerAdapterConformanceRejected(
                "broker adapter conformance acknowledgement mismatch",
                evidence=_rejection(
                    preview,
                    ["broker_adapter_conformance_acknowledgement_mismatch"],
                ),
            )
        if str(preview.get("schema_version") or "") != (
            BROKER_ADAPTER_CONFORMANCE_PREVIEW_SCHEMA_VERSION
        ) or not bool(preview.get("recordable")):
            raise BrokerAdapterConformanceRejected(
                "broker adapter conformance preview is not recordable",
                evidence=_rejection(
                    preview,
                    [
                        "broker_adapter_conformance_preview_not_recordable",
                        *[str(item) for item in preview.get("record_blockers") or []],
                    ],
                ),
            )
        integrity_blockers = _preview_integrity_blockers(preview)
        if integrity_blockers:
            raise BrokerAdapterConformanceRejected(
                "broker adapter conformance preview integrity invalid",
                evidence=_rejection(preview, integrity_blockers),
            )

        report_core = _result_core(preview)
        run_id = str(preview["run_id"])
        report_fingerprint = str(preview["report_fingerprint"])
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT * FROM broker_adapter_conformance_reports
                WHERE run_id = ? LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["report_fingerprint"]) != report_fingerprint:
                    conn.rollback()
                    raise BrokerAdapterConformanceRejected(
                        "broker adapter conformance run id conflict",
                        evidence=_rejection(
                            preview,
                            ["broker_adapter_conformance_run_id_conflict"],
                        ),
                    )
                conn.commit()
                return self._report_response(existing, reused=True)

            conn.execute(
                """
                INSERT INTO broker_adapter_conformance_reports (
                    run_id, release_evidence_ref, manifest_fingerprint,
                    suite_version, fixture_kind, validation_status,
                    report_fingerprint, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(preview["release_evidence_ref"]),
                    str(preview["manifest_fingerprint"]),
                    str(preview["suite_version"]),
                    str(preview["fixture_kind"]),
                    str(preview["validation_status"]),
                    report_fingerprint,
                    _json(report_core),
                    now,
                ),
            )
            saved = conn.execute(
                """
                SELECT * FROM broker_adapter_conformance_reports
                WHERE run_id = ? LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            conn.commit()
        if saved is None:
            raise RuntimeError("broker adapter conformance report was not persisted")
        return self._report_response(saved, reused=False)

    def verify_release_binding(
        self,
        *,
        release_evidence_ref: str,
        manifest_fingerprint: str,
    ) -> dict[str, Any]:
        """Resolve the latest report for a release; any drift or failure blocks."""

        release_ref = str(release_evidence_ref or "").strip()
        expected_manifest = str(manifest_fingerprint or "").strip().lower()
        if not self._path.exists() or not self._table_exists(
            "broker_adapter_conformance_reports"
        ):
            return _verification_blocked(
                release_ref,
                ["broker_adapter_conformance_report_not_found"],
            )
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM broker_adapter_conformance_reports
                WHERE release_evidence_ref = ? ORDER BY id DESC LIMIT 1
                """,
                (release_ref,),
            ).fetchone()
        if row is None:
            return _verification_blocked(
                release_ref,
                ["broker_adapter_conformance_report_not_found"],
            )

        report_core = _json_object(row["report_json"])
        canonical = preview_broker_adapter_conformance_result(report_core)
        blockers: list[str] = []
        if str(row["report_fingerprint"]) != _fingerprint(report_core):
            blockers.append("broker_adapter_conformance_report_integrity_invalid")
        for field in (
            "run_id",
            "release_evidence_ref",
            "manifest_fingerprint",
            "suite_version",
            "fixture_kind",
        ):
            if str(row[field]) != str(report_core.get(field) or ""):
                blockers.append(f"broker_adapter_conformance_row_drift:{field}")
        if canonical.get("record_blockers"):
            blockers.append("broker_adapter_conformance_report_structure_invalid")
        if str(row["validation_status"]) != str(
            canonical.get("validation_status") or ""
        ):
            blockers.append("broker_adapter_conformance_status_integrity_invalid")
        if str(row["manifest_fingerprint"]) != expected_manifest:
            blockers.append("broker_adapter_conformance_manifest_mismatch")
        if str(row["validation_status"]) != "passed":
            blockers.extend(str(item) for item in canonical.get("blockers") or [])
            blockers.append("broker_adapter_conformance_latest_report_not_passed")

        unique_blockers = list(dict.fromkeys(blockers))
        return {
            "schema_version": BROKER_ADAPTER_CONFORMANCE_REPORT_SCHEMA_VERSION,
            "status": "clear" if not unique_blockers else "blocked",
            "run_id": str(row["run_id"]),
            "release_evidence_ref": release_ref,
            "manifest_fingerprint": str(row["manifest_fingerprint"]),
            "report_fingerprint": str(row["report_fingerprint"]),
            "validation_status": str(row["validation_status"]),
            "blockers": unique_blockers,
            **_safety_flags(),
        }

    def get_latest(self, release_evidence_ref: str) -> dict[str, Any]:
        """Read the latest report without creating a database or contacting a provider."""

        release_ref = str(release_evidence_ref or "").strip()
        if not self._path.exists() or not self._table_exists(
            "broker_adapter_conformance_reports"
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
                SELECT * FROM broker_adapter_conformance_reports
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
        return self._report_response(row, reused=False)

    def _report_response(
        self,
        row: sqlite3.Row,
        *,
        reused: bool,
    ) -> dict[str, Any]:
        report_core = _json_object(row["report_json"])
        canonical = preview_broker_adapter_conformance_result(report_core)
        return {
            **canonical,
            "schema_version": BROKER_ADAPTER_CONFORMANCE_REPORT_SCHEMA_VERSION,
            "status": str(row["validation_status"]),
            "persisted": True,
            "reused": reused,
            "created_at": str(row["created_at"]),
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
                CREATE TABLE IF NOT EXISTS broker_adapter_conformance_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    release_evidence_ref TEXT NOT NULL,
                    manifest_fingerprint TEXT NOT NULL,
                    suite_version TEXT NOT NULL,
                    fixture_kind TEXT NOT NULL CHECK(fixture_kind = 'deterministic_local'),
                    validation_status TEXT NOT NULL CHECK(validation_status IN (
                        'passed', 'blocked'
                    )),
                    report_fingerprint TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_broker_adapter_conformance_latest
                ON broker_adapter_conformance_reports(
                    release_evidence_ref, id DESC
                );
                """)
            conn.commit()


def _normalize_scenarios(
    value: Any,
    record_blockers: list[str],
    blockers: list[str],
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        record_blockers.append("broker_adapter_conformance_scenarios_invalid")
        return []
    normalized: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict):
            record_blockers.append("broker_adapter_conformance_scenario_invalid")
            continue
        _reject_unknown_fields(item, _SCENARIO_FIELDS, "scenario", record_blockers)
        scenario = str(item.get("scenario") or "").strip()
        if scenario not in _EXPECTED_SCENARIO_STATUSES:
            record_blockers.append(
                f"broker_adapter_conformance_scenario_unsupported:{scenario or 'missing'}"
            )
            continue
        if scenario in normalized:
            record_blockers.append(
                f"broker_adapter_conformance_scenario_duplicate:{scenario}"
            )
            continue
        expected = str(item.get("expected_status") or "").strip()
        if expected != _EXPECTED_SCENARIO_STATUSES[scenario]:
            record_blockers.append(
                f"broker_adapter_conformance_expected_status_invalid:{scenario}"
            )
        observed = str(item.get("observed_status") or "").strip()
        if observed not in _OBSERVED_STATUSES:
            record_blockers.append(
                f"broker_adapter_conformance_observed_status_invalid:{scenario}"
            )
        evidence_fingerprint = str(item.get("evidence_fingerprint") or "").lower()
        if not _FINGERPRINT_PATTERN.fullmatch(evidence_fingerprint):
            record_blockers.append(
                f"broker_adapter_conformance_evidence_fingerprint_invalid:{scenario}"
            )
        normalized[scenario] = {
            "scenario": scenario,
            "expected_status": _EXPECTED_SCENARIO_STATUSES[scenario],
            "observed_status": observed,
            "evidence_fingerprint": evidence_fingerprint,
        }
        if observed != _EXPECTED_SCENARIO_STATUSES[scenario]:
            blockers.append(f"broker_adapter_conformance_scenario_failed:{scenario}")

    for scenario in _EXPECTED_SCENARIO_STATUSES:
        if scenario not in normalized:
            record_blockers.append(
                f"broker_adapter_conformance_scenario_missing:{scenario}"
            )
    return [
        normalized[name] for name in _EXPECTED_SCENARIO_STATUSES if name in normalized
    ]


def _result_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION,
        "run_id": str(value.get("run_id") or ""),
        "release_evidence_ref": str(value.get("release_evidence_ref") or ""),
        "manifest_fingerprint": str(value.get("manifest_fingerprint") or ""),
        "suite_version": str(value.get("suite_version") or ""),
        "fixture_kind": str(value.get("fixture_kind") or ""),
        "scenarios": [dict(item) for item in value.get("scenarios") or []],
        "provider_contacted": bool(value.get("provider_contacted")),
        "adapter_registered": bool(value.get("adapter_registered")),
        "broker_write_contacted": bool(value.get("broker_write_contacted")),
    }


def _preview_integrity_blockers(preview: Mapping[str, Any]) -> list[str]:
    canonical = preview_broker_adapter_conformance_result(_result_core(preview))
    blockers: list[str] = []
    for field in (
        "report_fingerprint",
        "validation_status",
        "recordable",
        "blockers",
        "record_blockers",
    ):
        if preview.get(field) != canonical.get(field):
            blockers.append(f"broker_adapter_conformance_preview_drift:{field}")
    for field, expected in _safety_flags().items():
        if preview.get(field) is not expected:
            blockers.append(f"broker_adapter_conformance_safety_drift:{field}")
    return list(dict.fromkeys(blockers))


def _verification_blocked(
    release_ref: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ADAPTER_CONFORMANCE_REPORT_SCHEMA_VERSION,
        "status": "blocked",
        "run_id": "",
        "release_evidence_ref": release_ref,
        "manifest_fingerprint": "",
        "report_fingerprint": "",
        "validation_status": "blocked",
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _rejection(preview: Mapping[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ADAPTER_CONFORMANCE_REPORT_SCHEMA_VERSION,
        "status": "rejected",
        "run_id": str(preview.get("run_id") or ""),
        "release_evidence_ref": str(preview.get("release_evidence_ref") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "deterministic_local": True,
        "provider_contacted": False,
        "adapter_registered": False,
        "default_registered": False,
        "broker_write_contacted": False,
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


def _id(value: Any, field: str, blockers: list[str]) -> str:
    normalized = str(value or "").strip()
    if not _ID_PATTERN.fullmatch(normalized):
        blockers.append(f"broker_adapter_conformance_{field}_invalid")
    return normalized


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
        blockers.append(f"broker_adapter_conformance_{prefix}_field_unsupported:{key}")


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


__all__ = [
    "BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT",
    "BROKER_ADAPTER_CONFORMANCE_FIXTURE_KIND",
    "BROKER_ADAPTER_CONFORMANCE_PREVIEW_SCHEMA_VERSION",
    "BROKER_ADAPTER_CONFORMANCE_REPORT_SCHEMA_VERSION",
    "BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION",
    "BROKER_ADAPTER_CONFORMANCE_SUITE_VERSION",
    "BrokerAdapterConformanceRejected",
    "BrokerAdapterConformanceRepository",
    "preview_broker_adapter_conformance_result",
]
