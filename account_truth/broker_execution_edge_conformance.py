"""Provider-neutral, deterministic execution-edge conformance evidence.

This contract validates Karkinos' execution-edge protocol with a local fixture.
It never loads a provider SDK, registers an adapter, or contacts a real broker.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from account_truth.broker_execution_edge_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from account_truth.broker_execution_edge_values import boolean_object as _boolean_object
from account_truth.broker_execution_edge_values import (
    contains_sensitive_key as _contains_sensitive_key,
)
from account_truth.broker_execution_edge_values import fingerprint as _fingerprint
from account_truth.broker_execution_edge_values import identifier as _id
from account_truth.broker_execution_edge_values import json_object as _json_object
from account_truth.broker_execution_edge_values import json_value as _json
from account_truth.broker_execution_edge_values import (
    reference_object as _reference_object,
)
from account_truth.broker_execution_edge_values import (
    reject_unknown_fields as _reject_unknown_fields,
)
from account_truth.broker_execution_edge_values import string_list as _string_list

BROKER_EXECUTION_EDGE_MANIFEST_SCHEMA_VERSION = (
    "karkinos.broker_execution_edge_manifest.v1"
)
BROKER_EXECUTION_EDGE_MANIFEST_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_execution_edge_manifest_preview.v1"
)
BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION = (
    "karkinos.broker_execution_edge_conformance_result.v1"
)
BROKER_EXECUTION_EDGE_CONFORMANCE_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_execution_edge_conformance_preview.v1"
)
BROKER_EXECUTION_EDGE_CONFORMANCE_REPORT_SCHEMA_VERSION = (
    "karkinos.broker_execution_edge_conformance_report.v1"
)
BROKER_EXECUTION_EDGE_CONFORMANCE_SUITE_VERSION = (
    "karkinos.broker_execution_edge_conformance_suite.v1"
)
BROKER_EXECUTION_EDGE_CONFORMANCE_FIXTURE_KIND = "deterministic_local"
BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT = (
    "record_local_execution_edge_conformance_without_provider_contact_or_authority"
)
MAX_BROKER_EXECUTION_EDGE_MANIFEST_BYTES = 512 * 1024

_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "execution_edge_ref",
        "adapter_ref",
        "adapter_version",
        "provider",
        "gateway_id",
        "account_alias",
        "deployment_fingerprint",
        "capabilities",
        "boundaries",
        "review_refs",
        "limitations",
    }
)
_CAPABILITY_FIELDS = frozenset(
    {
        "can_dry_run_orders",
        "can_submit_orders",
        "can_query_orders",
        "can_cancel_orders",
        "supports_idempotent_client_order_id",
    }
)
_EXPECTED_BOUNDARIES = {
    "runtime_auth_material_external": True,
    "default_registered": False,
    "production_enabled": False,
    "strategy_imports_adapter": False,
    "ai_imports_adapter": False,
    "core_imports_provider_sdk": False,
    "writes_oms": False,
    "writes_production_ledger": False,
    "writes_risk_state": False,
    "writes_kill_switch": False,
    "writes_capital_authority": False,
}
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "execution_edge_ref",
        "manifest_fingerprint",
        "suite_version",
        "fixture_kind",
        "scenarios",
        "provider_contacted",
        "adapter_registered",
        "production_broker_contacted",
        "real_order_side_effect_count",
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
    "capability_contract_default_closed": "pass",
    "dry_run_no_side_effect": "pass",
    "submit_exact_identity": "accepted",
    "submit_definitive_rejection": "rejected",
    "duplicate_submit_idempotent": "reused",
    "concurrent_submit_idempotent": "reused",
    "submit_timeout_classified_unknown": "unknown",
    "unknown_query_same_identity": "resolved",
    "unknown_not_found_no_resubmit": "blocked",
    "restart_query_recovery": "resolved",
    "cancel_requires_separate_exact_command": "blocked",
    "cancel_exact_identity": "cancelled",
    "duplicate_cancel_idempotent": "reused",
    "partial_fill_cancel_race": "partial_cancelled",
    "disconnect_query_fail_closed": "blocked",
}
_OBSERVED_STATUSES = frozenset(
    {
        "pass",
        "accepted",
        "rejected",
        "reused",
        "unknown",
        "resolved",
        "blocked",
        "cancelled",
        "partial_cancelled",
        "unexpected",
    }
)


class BrokerExecutionEdgeConformanceRejected(ValueError):
    """Raised when execution-edge evidence cannot be safely persisted."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def preview_broker_execution_edge_manifest(
    content: str | bytes,
    *,
    source_name: str = "",
) -> dict[str, Any]:
    """Validate one non-authorizing execution-edge declaration."""

    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    record_blockers: list[str] = []
    blockers: list[str] = []
    data: dict[str, Any] = {}
    if len(raw) > MAX_BROKER_EXECUTION_EDGE_MANIFEST_BYTES:
        record_blockers.append("broker_execution_edge_manifest_too_large")
    else:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            record_blockers.append("broker_execution_edge_manifest_json_invalid")
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                record_blockers.append("broker_execution_edge_manifest_not_object")

    if _contains_sensitive_key(data):
        record_blockers.append("broker_execution_edge_auth_material_not_allowed")
    _reject_unknown_fields(
        data,
        _MANIFEST_FIELDS,
        "manifest",
        record_blockers,
    )
    if str(data.get("schema_version") or "") != (
        BROKER_EXECUTION_EDGE_MANIFEST_SCHEMA_VERSION
    ):
        record_blockers.append("broker_execution_edge_manifest_schema_unsupported")

    identities = {
        field: _id(data.get(field), field, record_blockers)
        for field in (
            "execution_edge_ref",
            "adapter_ref",
            "adapter_version",
            "provider",
            "gateway_id",
            "account_alias",
        )
    }
    identities["provider"] = identities["provider"].lower()
    deployment_fingerprint = str(data.get("deployment_fingerprint") or "").lower()
    if not _FINGERPRINT_PATTERN.fullmatch(deployment_fingerprint):
        record_blockers.append("broker_execution_edge_deployment_fingerprint_invalid")

    capabilities = _boolean_object(
        data.get("capabilities"),
        allowed=_CAPABILITY_FIELDS,
        field="capabilities",
        blockers=record_blockers,
    )
    boundaries = _boolean_object(
        data.get("boundaries"),
        allowed=frozenset(_EXPECTED_BOUNDARIES),
        field="boundaries",
        blockers=record_blockers,
    )
    review_refs = _reference_object(data.get("review_refs"), record_blockers)
    limitations = _string_list(data.get("limitations"), record_blockers)
    for capability in _CAPABILITY_FIELDS:
        if capabilities and capabilities.get(capability) is not True:
            blockers.append(f"broker_execution_edge_capability_missing:{capability}")
    for boundary, expected in _EXPECTED_BOUNDARIES.items():
        if boundaries and boundaries.get(boundary) is not expected:
            blockers.append(f"broker_execution_edge_boundary_violation:{boundary}")

    unique_record_blockers = list(dict.fromkeys(record_blockers))
    unique_blockers = list(dict.fromkeys([*record_blockers, *blockers]))
    core = {
        "schema_version": BROKER_EXECUTION_EDGE_MANIFEST_SCHEMA_VERSION,
        **identities,
        "deployment_fingerprint": deployment_fingerprint,
        "capabilities": capabilities,
        "boundaries": boundaries,
        "review_refs": review_refs,
        "limitations": limitations,
    }
    recordable = bool(
        not unique_record_blockers
        and all(identities.values())
        and deployment_fingerprint
        and capabilities
        and boundaries
        and review_refs
    )
    return {
        **core,
        "schema_version": BROKER_EXECUTION_EDGE_MANIFEST_PREVIEW_SCHEMA_VERSION,
        "manifest_fingerprint": _fingerprint(core),
        "file_fingerprint": hashlib.sha256(raw).hexdigest(),
        "source_name": Path(str(source_name or "")).name[:128],
        "validation_status": "pass" if not unique_blockers else "blocked",
        "recordable": recordable,
        "blockers": unique_blockers,
        "record_blockers": unique_record_blockers,
        **_safety_flags(),
    }


def preview_broker_execution_edge_conformance_result(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one deterministic execution-edge fixture result."""

    data = dict(value)
    record_blockers: list[str] = []
    blockers: list[str] = []
    if _contains_sensitive_key(data):
        record_blockers.append("broker_execution_edge_auth_material_not_allowed")
    _reject_unknown_fields(data, _RESULT_FIELDS, "result", record_blockers)
    if str(data.get("schema_version") or "") != (
        BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION
    ):
        record_blockers.append("broker_execution_edge_result_schema_unsupported")
    run_id = _id(data.get("run_id"), "run_id", record_blockers)
    execution_edge_ref = _id(
        data.get("execution_edge_ref"),
        "execution_edge_ref",
        record_blockers,
    )
    manifest_fingerprint = str(data.get("manifest_fingerprint") or "").lower()
    if not _FINGERPRINT_PATTERN.fullmatch(manifest_fingerprint):
        record_blockers.append("broker_execution_edge_manifest_fingerprint_invalid")
    suite_version = str(data.get("suite_version") or "")
    if suite_version != BROKER_EXECUTION_EDGE_CONFORMANCE_SUITE_VERSION:
        record_blockers.append("broker_execution_edge_suite_unsupported")
    fixture_kind = str(data.get("fixture_kind") or "")
    if fixture_kind != BROKER_EXECUTION_EDGE_CONFORMANCE_FIXTURE_KIND:
        record_blockers.append("broker_execution_edge_fixture_kind_invalid")
    for field in (
        "provider_contacted",
        "adapter_registered",
        "production_broker_contacted",
    ):
        if data.get(field) is not False:
            record_blockers.append(f"broker_execution_edge_{field}_invalid")
    if (
        type(data.get("real_order_side_effect_count")) is not int
        or data.get("real_order_side_effect_count") != 0
    ):
        record_blockers.append(
            "broker_execution_edge_real_order_side_effect_count_invalid"
        )
    scenarios = _normalize_scenarios(data.get("scenarios"), record_blockers, blockers)
    unique_record_blockers = list(dict.fromkeys(record_blockers))
    unique_blockers = list(dict.fromkeys([*record_blockers, *blockers]))
    core = {
        "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "execution_edge_ref": execution_edge_ref,
        "manifest_fingerprint": manifest_fingerprint,
        "suite_version": suite_version,
        "fixture_kind": fixture_kind,
        "scenarios": scenarios,
        "provider_contacted": False,
        "adapter_registered": False,
        "production_broker_contacted": False,
        "real_order_side_effect_count": 0,
    }
    recordable = bool(
        not unique_record_blockers
        and run_id
        and execution_edge_ref
        and manifest_fingerprint
        and len(scenarios) == len(_EXPECTED_SCENARIO_STATUSES)
    )
    return {
        **core,
        "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_PREVIEW_SCHEMA_VERSION,
        "report_fingerprint": _fingerprint(core),
        "validation_status": "passed" if not unique_blockers else "blocked",
        "recordable": recordable,
        "blockers": unique_blockers,
        "record_blockers": unique_record_blockers,
        **_safety_flags(),
    }


class BrokerExecutionEdgeConformanceRepository:
    """Persist append-only local reports and verify exact manifest binding."""

    def __init__(self, path: str | Path, *, ensure_schema: bool = True) -> None:
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
        if acknowledgement != BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT:
            raise BrokerExecutionEdgeConformanceRejected(
                "execution-edge conformance acknowledgement mismatch",
                evidence=_rejection(
                    preview,
                    ["broker_execution_edge_acknowledgement_mismatch"],
                ),
            )
        if str(preview.get("schema_version") or "") != (
            BROKER_EXECUTION_EDGE_CONFORMANCE_PREVIEW_SCHEMA_VERSION
        ) or not bool(preview.get("recordable")):
            raise BrokerExecutionEdgeConformanceRejected(
                "execution-edge conformance preview is not recordable",
                evidence=_rejection(
                    preview,
                    [
                        "broker_execution_edge_preview_not_recordable",
                        *[str(item) for item in preview.get("record_blockers") or []],
                    ],
                ),
            )
        integrity_blockers = _preview_integrity_blockers(preview)
        if integrity_blockers:
            raise BrokerExecutionEdgeConformanceRejected(
                "execution-edge conformance preview integrity invalid",
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
                SELECT * FROM broker_execution_edge_conformance_reports
                WHERE run_id = ? LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["report_fingerprint"]) != report_fingerprint:
                    conn.rollback()
                    raise BrokerExecutionEdgeConformanceRejected(
                        "execution-edge conformance run id conflict",
                        evidence=_rejection(
                            preview,
                            ["broker_execution_edge_run_id_conflict"],
                        ),
                    )
                conn.commit()
                return self._report_response(existing, reused=True)
            conn.execute(
                """
                INSERT INTO broker_execution_edge_conformance_reports (
                    run_id, execution_edge_ref, manifest_fingerprint,
                    suite_version, fixture_kind, validation_status,
                    report_fingerprint, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(preview["execution_edge_ref"]),
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
                SELECT * FROM broker_execution_edge_conformance_reports
                WHERE run_id = ? LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            conn.commit()
        if saved is None:
            raise RuntimeError("execution-edge conformance report was not persisted")
        return self._report_response(saved, reused=False)

    def verify_manifest_binding(
        self,
        *,
        execution_edge_ref: str,
        manifest_fingerprint: str,
    ) -> dict[str, Any]:
        edge_ref = str(execution_edge_ref or "").strip()
        expected_manifest = str(manifest_fingerprint or "").strip().lower()
        if not self._path.exists() or not self._table_exists():
            return _verification_blocked(
                edge_ref,
                ["broker_execution_edge_report_not_found"],
            )
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM broker_execution_edge_conformance_reports
                WHERE execution_edge_ref = ? ORDER BY id DESC LIMIT 1
                """,
                (edge_ref,),
            ).fetchone()
        if row is None:
            return _verification_blocked(
                edge_ref,
                ["broker_execution_edge_report_not_found"],
            )
        report_core = _json_object(row["report_json"])
        canonical = preview_broker_execution_edge_conformance_result(report_core)
        blockers: list[str] = []
        if str(row["report_fingerprint"]) != _fingerprint(report_core):
            blockers.append("broker_execution_edge_report_integrity_invalid")
        for field in (
            "run_id",
            "execution_edge_ref",
            "manifest_fingerprint",
            "suite_version",
            "fixture_kind",
        ):
            if str(row[field]) != str(report_core.get(field) or ""):
                blockers.append(f"broker_execution_edge_row_drift:{field}")
        if canonical.get("record_blockers"):
            blockers.append("broker_execution_edge_report_structure_invalid")
        if str(row["validation_status"]) != str(
            canonical.get("validation_status") or ""
        ):
            blockers.append("broker_execution_edge_status_integrity_invalid")
        if str(row["manifest_fingerprint"]) != expected_manifest:
            blockers.append("broker_execution_edge_manifest_mismatch")
        if str(row["validation_status"]) != "passed":
            blockers.extend(str(item) for item in canonical.get("blockers") or [])
            blockers.append("broker_execution_edge_latest_report_not_passed")
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_REPORT_SCHEMA_VERSION,
            "status": "clear" if not unique_blockers else "blocked",
            "run_id": str(row["run_id"]),
            "execution_edge_ref": edge_ref,
            "manifest_fingerprint": str(row["manifest_fingerprint"]),
            "report_fingerprint": str(row["report_fingerprint"]),
            "validation_status": str(row["validation_status"]),
            "blockers": unique_blockers,
            **_safety_flags(),
        }

    def get_latest(self, execution_edge_ref: str) -> dict[str, Any]:
        edge_ref = str(execution_edge_ref or "").strip()
        if not self._path.exists() or not self._table_exists():
            return {
                "status": "not_configured",
                "execution_edge_ref": edge_ref,
                **_safety_flags(),
            }
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM broker_execution_edge_conformance_reports
                WHERE execution_edge_ref = ? ORDER BY id DESC LIMIT 1
                """,
                (edge_ref,),
            ).fetchone()
        if row is None:
            return {
                "status": "not_found",
                "execution_edge_ref": edge_ref,
                **_safety_flags(),
            }
        return self._report_response(row, reused=False)

    def _report_response(
        self,
        row: sqlite3.Row,
        *,
        reused: bool,
    ) -> dict[str, Any]:
        canonical = preview_broker_execution_edge_conformance_result(
            _json_object(row["report_json"])
        )
        return {
            **canonical,
            "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_REPORT_SCHEMA_VERSION,
            "status": str(row["validation_status"]),
            "persisted": True,
            "reused": reused,
            "created_at": str(row["created_at"]),
        }

    def _table_exists(self) -> bool:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute("""
                SELECT 1 FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'broker_execution_edge_conformance_reports'
                """).fetchone()
            return row is not None

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS broker_execution_edge_conformance_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    execution_edge_ref TEXT NOT NULL,
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

                CREATE INDEX IF NOT EXISTS idx_broker_execution_edge_conf_latest
                ON broker_execution_edge_conformance_reports(
                    execution_edge_ref, id DESC
                );
                """)
            conn.commit()


def _normalize_scenarios(
    value: Any,
    record_blockers: list[str],
    blockers: list[str],
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        record_blockers.append("broker_execution_edge_scenarios_invalid")
        return []
    normalized: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict):
            record_blockers.append("broker_execution_edge_scenario_invalid")
            continue
        _reject_unknown_fields(item, _SCENARIO_FIELDS, "scenario", record_blockers)
        scenario = str(item.get("scenario") or "").strip()
        if scenario not in _EXPECTED_SCENARIO_STATUSES:
            record_blockers.append(
                f"broker_execution_edge_scenario_unsupported:{scenario or 'missing'}"
            )
            continue
        if scenario in normalized:
            record_blockers.append(
                f"broker_execution_edge_scenario_duplicate:{scenario}"
            )
            continue
        expected = str(item.get("expected_status") or "").strip()
        if expected != _EXPECTED_SCENARIO_STATUSES[scenario]:
            record_blockers.append(
                f"broker_execution_edge_expected_status_invalid:{scenario}"
            )
        observed = str(item.get("observed_status") or "").strip()
        if observed not in _OBSERVED_STATUSES:
            record_blockers.append(
                f"broker_execution_edge_observed_status_invalid:{scenario}"
            )
        fingerprint = str(item.get("evidence_fingerprint") or "").lower()
        if not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            record_blockers.append(
                f"broker_execution_edge_evidence_fingerprint_invalid:{scenario}"
            )
        normalized[scenario] = {
            "scenario": scenario,
            "expected_status": _EXPECTED_SCENARIO_STATUSES[scenario],
            "observed_status": observed,
            "evidence_fingerprint": fingerprint,
        }
        if observed != _EXPECTED_SCENARIO_STATUSES[scenario]:
            blockers.append(f"broker_execution_edge_scenario_failed:{scenario}")
    for scenario in _EXPECTED_SCENARIO_STATUSES:
        if scenario not in normalized:
            record_blockers.append(f"broker_execution_edge_scenario_missing:{scenario}")
    return [
        normalized[name] for name in _EXPECTED_SCENARIO_STATUSES if name in normalized
    ]


def _result_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION,
        "run_id": str(value.get("run_id") or ""),
        "execution_edge_ref": str(value.get("execution_edge_ref") or ""),
        "manifest_fingerprint": str(value.get("manifest_fingerprint") or ""),
        "suite_version": str(value.get("suite_version") or ""),
        "fixture_kind": str(value.get("fixture_kind") or ""),
        "scenarios": [dict(item) for item in value.get("scenarios") or []],
        "provider_contacted": bool(value.get("provider_contacted")),
        "adapter_registered": bool(value.get("adapter_registered")),
        "production_broker_contacted": bool(value.get("production_broker_contacted")),
        "real_order_side_effect_count": int(
            value.get("real_order_side_effect_count") or 0
        ),
    }


def _preview_integrity_blockers(preview: Mapping[str, Any]) -> list[str]:
    canonical = preview_broker_execution_edge_conformance_result(_result_core(preview))
    blockers: list[str] = []
    for field in (
        "report_fingerprint",
        "validation_status",
        "recordable",
        "blockers",
        "record_blockers",
    ):
        if preview.get(field) != canonical.get(field):
            blockers.append(f"broker_execution_edge_preview_drift:{field}")
    for field, expected in _safety_flags().items():
        if preview.get(field) is not expected:
            blockers.append(f"broker_execution_edge_safety_drift:{field}")
    return list(dict.fromkeys(blockers))


def _verification_blocked(edge_ref: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_REPORT_SCHEMA_VERSION,
        "status": "blocked",
        "run_id": "",
        "execution_edge_ref": edge_ref,
        "manifest_fingerprint": "",
        "report_fingerprint": "",
        "validation_status": "blocked",
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _rejection(preview: Mapping[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_REPORT_SCHEMA_VERSION,
        "status": "rejected",
        "run_id": str(preview.get("run_id") or ""),
        "execution_edge_ref": str(preview.get("execution_edge_ref") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "deterministic_local": True,
        "provider_contacted": False,
        "adapter_registered": False,
        "default_registered": False,
        "production_broker_contacted": False,
        "broker_submission_enabled": False,
        "broker_cancellation_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "authorizes_execution": False,
    }


__all__ = [
    "BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT",
    "BROKER_EXECUTION_EDGE_CONFORMANCE_FIXTURE_KIND",
    "BROKER_EXECUTION_EDGE_CONFORMANCE_PREVIEW_SCHEMA_VERSION",
    "BROKER_EXECUTION_EDGE_CONFORMANCE_REPORT_SCHEMA_VERSION",
    "BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION",
    "BROKER_EXECUTION_EDGE_CONFORMANCE_SUITE_VERSION",
    "BROKER_EXECUTION_EDGE_MANIFEST_PREVIEW_SCHEMA_VERSION",
    "BROKER_EXECUTION_EDGE_MANIFEST_SCHEMA_VERSION",
    "BrokerExecutionEdgeConformanceRejected",
    "BrokerExecutionEdgeConformanceRepository",
    "preview_broker_execution_edge_conformance_result",
    "preview_broker_execution_edge_manifest",
]
