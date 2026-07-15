"""Persisted-only operator projection for broker adapter evidence readiness."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from account_truth.broker_adapter_conformance import (
    BrokerAdapterConformanceRepository,
)
from account_truth.broker_adapter_release import (
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)
from account_truth.broker_order_lifecycle_collector import (
    BrokerOrderLifecycleCollectorRepository,
)

BROKER_ADAPTER_READINESS_SCHEMA_VERSION = "karkinos.broker_adapter_readiness.v1"
_MAX_RELEASES = 50


def build_broker_adapter_readiness(db: Any) -> dict[str, Any]:
    """Project broker adapter evidence without creating schema or contacting providers."""

    path_value = getattr(db, "_path", None)
    if path_value is None:
        return _empty_projection(
            evidence_store_status="unavailable",
            limitation="Database path is unavailable to the read-only evidence projection.",
        )
    return BrokerAdapterReadinessService(Path(path_value)).project()


class BrokerAdapterReadinessService:
    """Read release, conformance, and collector evidence as one operator view."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def project(self) -> dict[str, Any]:
        """Return one fail-closed view from already persisted broker evidence."""

        if not self._path.exists():
            return _empty_projection(evidence_store_status="not_configured")

        try:
            if not self._table_exists("broker_adapter_release_manifests"):
                return _empty_projection(evidence_store_status="not_configured")
            manifests = self._manifest_rows()
            collector_runs = BrokerOrderLifecycleCollectorRepository(
                self._path,
                ensure_schema=False,
            ).list_runs(limit=500)
            releases = [
                self._release_projection(row, collector_runs=collector_runs)
                for row in manifests
            ]
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return {
                **_empty_projection(
                    evidence_store_status="blocked",
                    limitation="Persisted broker adapter evidence could not be verified.",
                ),
                "status": "evidence_attention_required",
                "subsystem_status": "blocked",
                "next_manual_action": "review_broker_adapter_evidence_store",
                "blockers": ["broker_adapter_readiness_projection_failed"],
            }

        if not releases:
            return _empty_projection(evidence_store_status="not_configured")

        status, subsystem_status, next_action = _overall_status(releases)
        return {
            "schema_version": BROKER_ADAPTER_READINESS_SCHEMA_VERSION,
            "status": status,
            "subsystem_status": subsystem_status,
            "evidence_store_status": "available",
            "configured_release_count": len(releases),
            "accepted_release_count": sum(
                item["review_status"] == "accepted" for item in releases
            ),
            "blocked_release_count": sum(
                item["status"] == "blocked" for item in releases
            ),
            "next_manual_action": next_action,
            "latest_release": releases[0],
            "releases": releases,
            "blockers": list(
                dict.fromkeys(
                    blocker
                    for release in releases
                    for blocker in release.get("blockers", [])
                )
            ),
            "limitations": _limitations(),
            **_safety_flags(),
        }

    def _release_projection(
        self,
        row: sqlite3.Row,
        *,
        collector_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        manifest = _json_object(row["manifest_json"])
        release_ref = str(row["release_evidence_ref"])
        persisted_fingerprint = str(row["manifest_fingerprint"])
        preview = preview_broker_adapter_release_manifest(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            source_name="persisted broker adapter release evidence",
        )
        manifest_blockers = [
            *[str(item) for item in preview.get("record_blockers") or []],
            *[str(item) for item in preview.get("blockers") or []],
        ]
        if str(preview.get("manifest_fingerprint") or "") != persisted_fingerprint:
            manifest_blockers.append(
                "broker_adapter_release_manifest_integrity_invalid"
            )

        release_repository = BrokerAdapterReleaseReviewRepository(
            self._path,
            ensure_schema=False,
        )
        conformance = BrokerAdapterConformanceRepository(
            self._path,
            ensure_schema=False,
        ).verify_release_binding(
            release_evidence_ref=release_ref,
            manifest_fingerprint=persisted_fingerprint,
        )
        review = release_repository.get_status(release_ref)
        collection_modes = [
            str(item) for item in manifest.get("collection_modes") or []
        ]
        binding = (
            release_repository.verify_collector_binding(
                {**manifest, "collection_mode": collection_modes[0]}
            )
            if collection_modes
            else {
                "status": "blocked",
                "blockers": ["broker_adapter_release_collection_modes_invalid"],
            }
        )
        latest_run = next(
            (
                run
                for run in collector_runs
                if str(run.get("release_evidence_ref") or "") == release_ref
            ),
            None,
        )
        blockers = list(
            dict.fromkeys(
                [
                    *manifest_blockers,
                    *[str(item) for item in conformance.get("blockers") or []],
                    *[str(item) for item in binding.get("blockers") or []],
                    *(
                        [str(item) for item in latest_run.get("blockers") or []]
                        if latest_run
                        else []
                    ),
                ]
            )
        )
        status, next_action = _release_status(
            review_status=str(review.get("status") or "not_found"),
            binding_status=str(binding.get("status") or "blocked"),
            manifest_blockers=manifest_blockers,
            collector_run=latest_run,
        )
        return {
            "release_evidence_ref": release_ref,
            "manifest_fingerprint": persisted_fingerprint,
            "manifest_status": "blocked" if manifest_blockers else "clear",
            "provider": str(manifest.get("provider") or ""),
            "gateway_id": str(manifest.get("gateway_id") or ""),
            "account_alias": str(manifest.get("account_alias") or ""),
            "collector_id": str(manifest.get("collector_id") or ""),
            "collection_modes": collection_modes,
            "review_status": str(review.get("status") or "not_found"),
            "review_id": str(review.get("review_id") or ""),
            "reviewed_at": review.get("reviewed_at"),
            "conformance_status": str(conformance.get("status") or "blocked"),
            "conformance_run_id": str(conformance.get("run_id") or ""),
            "conformance_report_fingerprint": str(
                conformance.get("report_fingerprint") or ""
            ),
            "collector_status": (
                str(latest_run.get("run_status") or "unknown")
                if latest_run
                else "not_started"
            ),
            "collector_run_id": (
                str(latest_run.get("run_id") or "") if latest_run else ""
            ),
            "collector_updated_at": (
                latest_run.get("updated_at") if latest_run else None
            ),
            "status": status,
            "next_manual_action": next_action,
            "blockers": blockers,
            "does_not_authorize_provider_activation": True,
        }

    def _manifest_rows(self) -> list[sqlite3.Row]:
        with _connect_readonly(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                """
                SELECT * FROM broker_adapter_release_manifests
                ORDER BY id DESC LIMIT ?
                """,
                (_MAX_RELEASES,),
            ).fetchall()

    def _table_exists(self, table: str) -> bool:
        with _connect_readonly(self._path) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            return row is not None


def _release_status(
    *,
    review_status: str,
    binding_status: str,
    manifest_blockers: list[str],
    collector_run: dict[str, Any] | None,
) -> tuple[str, str]:
    if manifest_blockers:
        return "blocked", "review_broker_adapter_manifest_integrity"
    if review_status in {"not_configured", "not_found"}:
        return "review_required", "review_broker_adapter_release_evidence"
    if review_status != "accepted" or binding_status != "clear":
        return "blocked", "review_broker_adapter_release_blockers"
    if collector_run is None:
        return (
            "evidence_ready_not_activated",
            "obtain_explicit_owner_authorization_before_adapter_activation",
        )
    run_status = str(collector_run.get("run_status") or "unknown")
    if run_status in {"recorded", "duplicate"}:
        return "observing_readonly", "continue_readonly_evidence_observation"
    if run_status == "prepared":
        return "review_required", "review_prepared_collector_restart_state"
    return "blocked", "review_collector_evidence_blockers"


def _overall_status(
    releases: list[dict[str, Any]],
) -> tuple[str, str, str]:
    active_blocked = next(
        (
            item
            for item in releases
            if item["status"] == "blocked"
            and item["collector_status"] not in {"not_started", "unknown"}
        ),
        None,
    )
    if active_blocked is not None:
        return (
            "evidence_attention_required",
            "blocked",
            active_blocked["next_manual_action"],
        )
    observing = next(
        (item for item in releases if item["status"] == "observing_readonly"),
        None,
    )
    if observing is not None:
        return "observing_readonly", "pass", observing["next_manual_action"]
    review_required = next(
        (item for item in releases if item["status"] == "review_required"),
        None,
    )
    if review_required is not None:
        return (
            "review_required",
            "manual_action_required",
            review_required["next_manual_action"],
        )
    ready = next(
        (item for item in releases if item["status"] == "evidence_ready_not_activated"),
        None,
    )
    if ready is not None:
        return "evidence_ready_not_activated", "skipped", ready["next_manual_action"]
    blocked = next((item for item in releases if item["status"] == "blocked"), None)
    return (
        "evidence_attention_required",
        "degraded",
        blocked["next_manual_action"] if blocked else "review_broker_adapter_evidence",
    )


def _empty_projection(
    *,
    evidence_store_status: str,
    limitation: str | None = None,
) -> dict[str, Any]:
    limitations = _limitations()
    if limitation:
        limitations = [limitation, *limitations]
    return {
        "schema_version": BROKER_ADAPTER_READINESS_SCHEMA_VERSION,
        "status": "not_configured",
        "subsystem_status": "skipped",
        "evidence_store_status": evidence_store_status,
        "configured_release_count": 0,
        "accepted_release_count": 0,
        "blocked_release_count": 0,
        "next_manual_action": "await_explicit_real_broker_environment_confirmation",
        "latest_release": None,
        "releases": [],
        "blockers": [],
        "limitations": limitations,
        **_safety_flags(),
    }


def _limitations() -> list[str]:
    return [
        "This view reads persisted evidence only and never contacts a provider.",
        "Release and conformance evidence do not register or activate an adapter.",
        "A third-party adapter still requires separate review and explicit owner authorization.",
    ]


def _safety_flags() -> dict[str, bool]:
    return {
        "persisted_facts_only": True,
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


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
