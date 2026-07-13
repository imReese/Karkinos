"""Persisted broker lifecycle evidence views with no provider side effects."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from account_truth.broker_order_lifecycle_collector import (
    BrokerOrderLifecycleCollectorRepository,
)

BROKER_LIFECYCLE_EVIDENCE_HEALTH_SCHEMA_VERSION = (
    "karkinos.broker_lifecycle_evidence_health.v1"
)
BROKER_LIFECYCLE_EVIDENCE_QUERY_SCHEMA_VERSION = (
    "karkinos.broker_lifecycle_evidence_query.v1"
)


class BrokerLifecycleEvidenceViewService:
    """Project explicit collector runs without contacting an edge adapter."""

    def __init__(
        self,
        *,
        db: Any,
        broker_connectors: list[Any] | None = None,
    ) -> None:
        self._db = db
        self._broker_connectors = broker_connectors or []

    def list_health(self) -> list[dict[str, Any]]:
        runs, store_status = self._persisted_runs()
        runs_by_gateway = _latest_scope_runs_by_gateway(runs)
        health: list[dict[str, Any]] = []
        emitted_gateway_ids: set[str] = set()

        for connector in self._broker_connectors:
            connector_id = _connector_id(connector)
            gateway_id = str(
                getattr(connector, "gateway_id", "") or connector_id
            ).strip()
            health.append(
                _health_payload(
                    gateway_id=gateway_id,
                    connector=connector,
                    scope_runs=runs_by_gateway.get(gateway_id, []),
                    store_status=store_status,
                )
            )
            emitted_gateway_ids.add(gateway_id)

        for gateway_id in sorted(runs_by_gateway):
            if gateway_id in emitted_gateway_ids:
                continue
            health.append(
                _health_payload(
                    gateway_id=gateway_id,
                    connector=None,
                    scope_runs=runs_by_gateway[gateway_id],
                    store_status=store_status,
                )
            )
        return health

    def query(self, connector_id: str) -> dict[str, Any]:
        normalized_connector_id = str(connector_id or "").strip()
        if not normalized_connector_id:
            raise KeyError("Connector id is required")
        health = next(
            (
                item
                for item in self.list_health()
                if str(item.get("connector_id") or "") == normalized_connector_id
            ),
            None,
        )
        if health is None:
            raise KeyError(
                f"Broker lifecycle evidence scope not found: {normalized_connector_id}"
            )
        status = str(health["status"])
        if status == "collector_evidence_clear":
            query_status = "persisted_evidence_clear"
        elif status == "collector_evidence_missing":
            query_status = "explicit_ingestion_required"
        else:
            query_status = "persisted_evidence_not_clear"
        return {
            "schema_version": BROKER_LIFECYCLE_EVIDENCE_QUERY_SCHEMA_VERSION,
            "status": query_status,
            "query_scope": "persisted_broker_order_lifecycle_evidence",
            "connector_id": normalized_connector_id,
            "provider": health.get("provider"),
            "gateway_id": health.get("gateway_id"),
            "collector_health": health,
            "latest_collector_runs": health["latest_collector_runs"],
            "account_facts_included": False,
            "provider_contact_performed": False,
            "reads_persisted_facts_only": True,
            "explicit_ingestion_required": True,
            "broker_submission_enabled": False,
            "can_submit_orders": False,
            "can_cancel_orders": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_fills": True,
            "does_not_mutate_production_ledger": True,
            "does_not_mutate_risk_state": True,
            "does_not_mutate_kill_switch": True,
            "does_not_mutate_capital_authority": True,
            "limitations": [
                "This query reads persisted broker order lifecycle collector runs only.",
                "Provider contact is allowed only through a separately reviewed and explicitly started ingestion boundary.",
                "Account cash and positions remain available only from persisted account-fact endpoints.",
                "No order is submitted or cancelled and no execution authority is granted.",
            ],
        }

    def _persisted_runs(self) -> tuple[list[dict[str, Any]], str]:
        db_path = getattr(self._db, "_path", None)
        if db_path is None:
            return [], "unavailable"
        try:
            runs = BrokerOrderLifecycleCollectorRepository(
                Path(db_path),
                ensure_schema=False,
            ).list_runs(limit=500)
        except Exception:  # pragma: no cover - defensive persisted-fact boundary
            return [], "unavailable"
        return runs, "available" if runs else "empty"


def _latest_scope_runs_by_gateway(
    runs: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    latest_by_scope: dict[str, dict[str, Any]] = {}
    for run in runs:
        scope_key = str(run.get("scope_key") or "").strip()
        if scope_key and scope_key not in latest_by_scope:
            latest_by_scope[scope_key] = run
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in latest_by_scope.values():
        gateway_id = str(run.get("gateway_id") or "").strip()
        if gateway_id:
            grouped[gateway_id].append(run)
    return {
        gateway_id: sorted(
            scope_runs,
            key=lambda item: (
                str(item.get("observed_at") or ""),
                str(item.get("run_id") or ""),
            ),
            reverse=True,
        )
        for gateway_id, scope_runs in grouped.items()
    }


def _health_payload(
    *,
    gateway_id: str,
    connector: Any | None,
    scope_runs: list[dict[str, Any]],
    store_status: str,
) -> dict[str, Any]:
    registered = connector is not None
    enabled = bool(getattr(connector, "enabled", True)) if registered else False
    connector_id = _connector_id(connector) if registered else gateway_id
    connector_type = (
        str(getattr(connector, "connector_type", "") or "edge_adapter")
        if registered
        else "unregistered_edge_adapter"
    )
    blockers = _collector_blockers(scope_runs)
    if store_status == "unavailable":
        status = "collector_evidence_unavailable"
        blockers.append("broker_lifecycle_evidence_store_unavailable")
    elif not scope_runs and registered and not enabled:
        status = "disabled"
    elif not scope_runs:
        status = "collector_evidence_missing"
        blockers.append("broker_lifecycle_collector_evidence_missing")
    elif any(str(run.get("run_status") or "") == "prepared" for run in scope_runs):
        status = "collector_evidence_pending"
    elif blockers:
        status = "collector_evidence_blocked"
    else:
        status = "collector_evidence_clear"
    blockers = list(dict.fromkeys(blockers))
    latest_run = scope_runs[0] if scope_runs else {}
    provider_values = sorted(
        {
            str(run.get("provider") or "")
            for run in scope_runs
            if str(run.get("provider") or "")
        }
    )
    return {
        "schema_version": BROKER_LIFECYCLE_EVIDENCE_HEALTH_SCHEMA_VERSION,
        "connector_id": connector_id,
        "connector_type": connector_type,
        "gateway_id": gateway_id,
        "provider": provider_values[0] if len(provider_values) == 1 else None,
        "providers": provider_values,
        "registered": registered,
        "registration_status": (
            "registered_enabled"
            if registered and enabled
            else "registered_disabled" if registered else "not_registered"
        ),
        "enabled": enabled,
        "status": status,
        "message": _health_message(status),
        "blockers": blockers,
        "evidence_store_status": store_status,
        "evidence_source": "persisted_broker_order_lifecycle_collector_runs",
        "capability_scope": "persisted_broker_order_lifecycle_evidence",
        "capabilities": {
            "can_read_health": bool(scope_runs),
            "can_query_lifecycle_evidence": bool(scope_runs),
            "can_read_account": False,
            "can_read_cash": False,
            "can_read_positions": False,
            "can_read_orders": False,
            "can_read_fills": False,
            "can_preview_orders": False,
            "can_export_tickets": False,
            "can_dry_run_orders": False,
            "can_submit_orders": False,
            "can_cancel_orders": False,
        },
        "account_aliases": sorted(
            {
                str(run.get("account_alias") or "")
                for run in scope_runs
                if str(run.get("account_alias") or "")
            }
        ),
        "scope_count": len(scope_runs),
        "collector_run_ids": [str(run.get("run_id") or "") for run in scope_runs],
        "latest_collector_runs": [_collector_run_summary(run) for run in scope_runs],
        "last_heartbeat_at": latest_run.get("observed_at"),
        "last_error": _health_message(status) if blockers else None,
        "latest_source_contact_status": latest_run.get("source_contact_status"),
        "provider_contact_performed": False,
        "reads_persisted_facts_only": True,
        "explicit_ingestion_required": True,
        "third_party_adapter_review_required": True,
        "default_registered": False,
        "requires_credentials": False,
        "stores_credentials": False,
        "submitted_to_broker": False,
        "can_submit_orders": False,
        "can_cancel_orders": False,
        "limitations": [
            "Health is derived only from persisted collector-run evidence.",
            "This read does not call an edge adapter or contact a provider.",
            "An adapter requires separate review, explicit registration, and user authorization.",
            "Collector evidence does not mutate OMS, fills, ledger, risk, kill switch, or capital authority.",
        ],
    }


def _collector_blockers(scope_runs: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for run in scope_runs:
        run_status = str(run.get("run_status") or "")
        if run_status not in {"recorded", "duplicate"}:
            blockers.append(f"broker_lifecycle_collector_run_{run_status or 'unknown'}")
        if str(run.get("validation_status") or "") != "pass":
            blockers.append("broker_lifecycle_collector_validation_not_passed")
        if str(run.get("batch_status") or "") != "complete":
            blockers.append("broker_lifecycle_collector_batch_not_complete")
        if str(run.get("connection_status") or "") not in {
            "connected",
            "not_applicable",
        }:
            blockers.append("broker_lifecycle_collector_connection_not_clear")
        if str(run.get("source_contact_status") or "") not in {
            "not_contacted",
            "read_only_contact",
        }:
            blockers.append("broker_lifecycle_collector_source_contact_unknown")
        if str(run.get("release_review_status") or "") != "reviewed":
            blockers.append("broker_lifecycle_collector_release_not_reviewed")
        if not str(run.get("adapter_authorization_ref") or "").strip():
            blockers.append("broker_lifecycle_collector_adapter_authorization_missing")
        blockers.extend(str(item) for item in run.get("blockers") or [])
    return list(dict.fromkeys(blockers))


def _collector_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": str(run.get("schema_version") or ""),
        "run_id": str(run.get("run_id") or ""),
        "collector_id": str(run.get("collector_id") or ""),
        "deployment_id": str(run.get("deployment_id") or ""),
        "release_evidence_ref": str(run.get("release_evidence_ref") or ""),
        "release_review_status": str(run.get("release_review_status") or ""),
        "adapter_authorization_ref": str(run.get("adapter_authorization_ref") or ""),
        "provider": str(run.get("provider") or ""),
        "gateway_id": str(run.get("gateway_id") or ""),
        "account_alias": str(run.get("account_alias") or ""),
        "collection_mode": str(run.get("collection_mode") or ""),
        "source_contact_status": str(run.get("source_contact_status") or ""),
        "connection_status": str(run.get("connection_status") or ""),
        "batch_status": str(run.get("batch_status") or ""),
        "cursor_previous": int(run.get("cursor_previous") or 0),
        "cursor_current": int(run.get("cursor_current") or 0),
        "captured_at": str(run.get("captured_at") or ""),
        "observed_at": str(run.get("observed_at") or ""),
        "event_count": int(run.get("event_count") or 0),
        "run_status": str(run.get("run_status") or ""),
        "validation_status": str(run.get("validation_status") or ""),
        "blockers": [str(item) for item in run.get("blockers") or []],
        "lifecycle_observation_id": str(run.get("lifecycle_observation_id") or ""),
        "persisted": bool(run.get("persisted")),
    }


def _connector_id(connector: Any | None) -> str:
    if connector is None:
        return ""
    return str(
        getattr(connector, "connector_id", "")
        or getattr(connector, "__class__", type(connector)).__name__
    ).strip()


def _health_message(status: str) -> str:
    return {
        "collector_evidence_clear": (
            "Latest persisted broker lifecycle collector evidence is clear."
        ),
        "collector_evidence_pending": (
            "A persisted collector batch is prepared but not committed."
        ),
        "collector_evidence_blocked": (
            "Persisted collector evidence is blocked or incomplete."
        ),
        "collector_evidence_missing": (
            "No persisted collector evidence exists; run explicit ingestion first."
        ),
        "collector_evidence_unavailable": (
            "Persisted collector evidence store is unavailable."
        ),
        "disabled": "Edge-adapter registration is disabled and was not queried.",
    }.get(status, status)
