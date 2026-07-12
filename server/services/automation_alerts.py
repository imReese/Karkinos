"""Structured alerts for controlled automation operations."""

from __future__ import annotations

import json
from typing import Any

AUTOMATION_ALERT_SCHEMA_VERSION = "karkinos.automation_alert.v1"
_FAILED_AUTOMATION_RUN_STATUSES = {
    "failed",
    "paper_shadow_failed",
    "scheduler_failed",
}
_STALE_MARKET_DATA_STATUSES = {
    "cache",
    "confirmed_nav_missing",
    "estimated",
    "missing",
    "partial",
    "stale",
}
_ACCOUNT_TRUTH_ALERT_STATUSES = {
    "blocked",
    "degraded",
    "failed",
    "fail",
    "mismatch",
    "warning",
}
_PAPER_SHADOW_DIVERGENCE_STATUSES = {
    "diverged",
    "failed",
    "review_required",
}
_RUNTIME_CONNECTOR_DEGRADED_STATUSES = {
    "connection_failed",
    "degraded",
    "disconnected",
    "error",
    "failed",
    "heartbeat_stale",
    "runtime_degraded",
    "runtime_unavailable",
    "stale",
    "unavailable",
}


class AutomationAlertService:
    """Generate and manage automation alerts."""

    def __init__(
        self,
        *,
        db: Any,
        trading_controls: Any | None,
        broker_connectors: list[Any] | None = None,
        connector_health: list[Any] | None = None,
        trading_plan: dict[str, Any] | None = None,
        market_health: dict[str, Any] | None = None,
        account_truth: dict[str, Any] | None = None,
        paper_shadow_run: dict[str, Any] | None = None,
    ) -> None:
        self._db = db
        self._trading_controls = trading_controls
        self._broker_connectors = broker_connectors or []
        self._connector_health = [
            row for item in connector_health or [] if (row := _object_dict(item))
        ]
        self._trading_plan = trading_plan if isinstance(trading_plan, dict) else None
        self._market_health = _object_dict(market_health)
        self._account_truth = _object_dict(account_truth)
        self._paper_shadow_run = _object_dict(paper_shadow_run)

    def scan(self) -> dict[str, Any]:
        alerts: list[dict[str, Any]] = []
        alerts.extend(self._scan_kill_switch())
        alerts.extend(self._scan_execution_reconciliation())
        alerts.extend(self._scan_blocked_automation_runs())
        alerts.extend(self._scan_connector_health())
        alerts.extend(self._scan_daily_plan_risk_blockers())
        alerts.extend(self._scan_market_data_health())
        alerts.extend(self._scan_account_truth())
        alerts.extend(self._scan_paper_shadow_divergence())
        open_alerts = self.list_alerts(status="open")
        return {
            "schema_version": "karkinos.automation_alert_scan.v1",
            "generated_alert_count": len(alerts),
            "open_alert_count": len(open_alerts),
            "alerts": open_alerts,
        }

    def list_alerts(self, *, status: str | None = None) -> list[dict[str, Any]]:
        return [
            self._normalize_alert(row)
            for row in self._db.list_automation_alerts_sync(status=status)
        ]

    def acknowledge(self, alert_id: int, *, actor: str | None = None) -> dict[str, Any]:
        return self._normalize_alert(
            self._db.acknowledge_automation_alert_sync(
                alert_id=alert_id,
                actor=actor,
            )
        )

    def _scan_kill_switch(self) -> list[dict[str, Any]]:
        snapshot = self._kill_switch_snapshot()
        if snapshot is None or not bool(
            getattr(snapshot, "kill_switch_enabled", False)
        ):
            return []
        alert = self._db.upsert_automation_alert_sync(
            alert_key="kill_switch:enabled",
            severity="critical",
            category="trading_control",
            title="Global kill switch is enabled",
            detail=str(getattr(snapshot, "reason", "") or "Trading is paused."),
            source="trading_controls",
            source_ref="kill_switch",
            payload={
                "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                "updated_at": getattr(snapshot, "updated_at", ""),
            },
        )
        return [self._normalize_alert(alert)]

    def _scan_execution_reconciliation(self) -> list[dict[str, Any]]:
        rows = self._db.list_execution_reconciliation_open_items_sync(limit=100)
        alerts: list[dict[str, Any]] = []
        for item in rows:
            item_status = str(item.get("item_status") or "unknown")
            order_id = str(item.get("order_id") or "")
            if not order_id:
                continue
            item_payload = _json_object(item.get("payload_json"))
            manual_execution_summary = _object_dict(
                item_payload.get("manual_execution_evidence_summary")
            )
            controlled_submission_summary = _object_dict(
                item_payload.get("controlled_submission_evidence_summary")
            )
            title = "Execution reconciliation requires review"
            detail = str(item.get("detail") or item_status)
            severity = "warning"
            payload = {
                "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                "item_status": item_status,
                "suggested_action": item.get("suggested_action"),
                "gateway_event_count": item.get("gateway_event_count"),
                "requires_manual_review": True,
            }
            if controlled_submission_summary:
                severity = (
                    "critical"
                    if item_status
                    in {
                        "controlled_submission_unknown",
                        "controlled_submission_unknown_broker_evidence_available",
                        "controlled_submission_evidence_mismatch",
                        "controlled_submission_broker_evidence_mismatch",
                        "controlled_rejection_broker_evidence_conflict",
                    }
                    else "warning"
                )
                title = (
                    "Controlled broker submission outcome is unknown"
                    if "unknown" in item_status
                    else "Controlled broker submission requires reconciliation"
                )
                payload.update(
                    {
                        "controlled_submission_evidence_summary": (
                            controlled_submission_summary
                        ),
                        "blocks_new_submissions": (
                            controlled_submission_summary.get("new_submissions_blocked")
                            is True
                        ),
                        "recovery_resubmission_enabled": False,
                        "does_not_mutate_production_ledger": True,
                    }
                )
            elif manual_execution_summary:
                title = "Manual execution evidence requires reconciliation review"
                detail = (
                    f"{detail} no broker order was submitted; OMS and "
                    "production ledger remain unchanged."
                )
                payload.update(
                    {
                        "manual_execution_evidence_summary": manual_execution_summary,
                        "does_not_submit_broker_order": (
                            manual_execution_summary.get("submitted_to_broker") is False
                        ),
                        "does_not_mutate_oms": (
                            manual_execution_summary.get("does_not_mutate_oms") is True
                        ),
                        "does_not_mutate_production_ledger": (
                            manual_execution_summary.get(
                                "does_not_mutate_production_ledger"
                            )
                            is True
                        ),
                    }
                )
            alert = self._db.upsert_automation_alert_sync(
                alert_key=f"execution_reconciliation:{order_id}:{item_status}",
                severity=severity,
                category="execution_reconciliation",
                title=title,
                detail=detail,
                source="execution_reconciliation",
                source_ref=order_id,
                payload=payload,
            )
            alerts.append(self._normalize_alert(alert))
        return alerts

    def _scan_blocked_automation_runs(self) -> list[dict[str, Any]]:
        rows = self._db.list_automation_runs_sync(limit=20)
        alerts: list[dict[str, Any]] = []
        for run in rows:
            status = str(run.get("status") or "")
            run_id = str(run.get("run_id") or "")
            if status == "blocked_by_kill_switch":
                alert = self._db.upsert_automation_alert_sync(
                    alert_key=f"automation_run:{run_id}:{status}",
                    severity="warning",
                    category="automation_run",
                    title="Automation run was blocked",
                    detail=f"Automation run {run_id} ended with {status}.",
                    source="automation_runs",
                    source_ref=run_id,
                    payload={
                        "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                        "run_status": status,
                        "run_type": run.get("run_type"),
                        "suggested_action": "resolve_kill_switch",
                        "requires_manual_review": True,
                    },
                )
                alerts.append(self._normalize_alert(alert))
                continue
            if status in _FAILED_AUTOMATION_RUN_STATUSES:
                payload = _json_object(run.get("payload_json"))
                limitations = _json_list(payload.get("limitations"))
                retry_state = _json_object(payload.get("retry_state"))
                paper_shadow_mode = (
                    str(run.get("execution_mode") or "") == "paper_shadow"
                )
                detail_parts = [f"Automation run {run_id} ended with {status}."]
                detail_parts.extend(limitations)
                alert = self._db.upsert_automation_alert_sync(
                    alert_key=f"automation_run:{run_id}:{status}",
                    severity="warning",
                    category="automation_run",
                    title=(
                        "Paper/shadow automation run failed"
                        if str(run.get("execution_mode") or "") == "paper_shadow"
                        else "Automation run failed"
                    ),
                    detail=" ".join(detail_parts),
                    source="automation_runs",
                    source_ref=run_id,
                    payload={
                        "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                        "run_status": status,
                        "run_type": run.get("run_type"),
                        "execution_mode": run.get("execution_mode"),
                        "input_fingerprint": payload.get("input_fingerprint"),
                        "idempotency_key": payload.get("idempotency_key"),
                        "input_snapshot": _json_object(payload.get("input_snapshot")),
                        "retry_state": payload.get("retry_state"),
                        "suggested_action": _automation_run_suggested_action(
                            status=status,
                            run_type=run.get("run_type"),
                            execution_mode=run.get("execution_mode"),
                        ),
                        "requires_manual_review": True,
                        "retry_recommended": bool(retry_state.get("retryable")),
                        "limitations": limitations,
                        "does_not_submit_broker_order": bool(
                            payload.get(
                                "does_not_submit_broker_order",
                                paper_shadow_mode,
                            )
                        ),
                        "does_not_mutate_production_ledger": bool(
                            payload.get(
                                "does_not_mutate_production_ledger",
                                paper_shadow_mode,
                            )
                        ),
                    },
                )
                alerts.append(self._normalize_alert(alert))
        return alerts

    def _scan_connector_health(self) -> list[dict[str, Any]]:
        health_rows = list(self._connector_health)
        if self._broker_connectors:
            from server.services.broker_gateway import BrokerGatewayService

            health_rows.extend(
                BrokerGatewayService(
                    db=self._db,
                    broker_connectors=self._broker_connectors,
                ).list_connector_health()
            )
        alerts: list[dict[str, Any]] = []
        for health in health_rows:
            connector_id = str(health.get("connector_id") or "")
            status = str(health.get("status") or "")
            if not connector_id or (
                status != "configuration_incomplete"
                and status not in _RUNTIME_CONNECTOR_DEGRADED_STATUSES
            ):
                continue
            capabilities = _json_object(health.get("capabilities"))
            alert = self._db.upsert_automation_alert_sync(
                alert_key=f"broker_connector:{connector_id}:{status}",
                severity="warning",
                category="broker_connector_health",
                title="Broker connector health requires review",
                detail=str(health.get("message") or status),
                source="broker_gateway",
                source_ref=connector_id,
                payload={
                    "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                    "connector_id": connector_id,
                    "connector_type": health.get("connector_type"),
                    "connector_status": status,
                    "enabled": bool(health.get("enabled")),
                    "capability_scope": health.get("capability_scope"),
                    "can_read_health": bool(capabilities.get("can_read_health")),
                    "can_read_account": bool(capabilities.get("can_read_account")),
                    "can_read_cash": bool(capabilities.get("can_read_cash")),
                    "can_read_positions": bool(capabilities.get("can_read_positions")),
                    "can_read_orders": bool(capabilities.get("can_read_orders")),
                    "can_read_fills": bool(capabilities.get("can_read_fills")),
                    "can_preview_orders": bool(capabilities.get("can_preview_orders")),
                    "can_export_tickets": bool(capabilities.get("can_export_tickets")),
                    "can_dry_run_orders": bool(capabilities.get("can_dry_run_orders")),
                    "can_submit_orders": bool(capabilities.get("can_submit_orders")),
                    "can_cancel_orders": bool(capabilities.get("can_cancel_orders")),
                    "requires_credentials": bool(health.get("requires_credentials")),
                    "stores_credentials": bool(health.get("stores_credentials")),
                    "submitted_to_broker": bool(health.get("submitted_to_broker")),
                    "last_heartbeat_at": health.get("last_heartbeat_at"),
                    "last_error": health.get("last_error"),
                    "limitations": _json_list(health.get("limitations")),
                    "requires_manual_review": True,
                    "does_not_submit_broker_order": True,
                },
            )
            alerts.append(self._normalize_alert(alert))
        return alerts

    def _scan_daily_plan_risk_blockers(self) -> list[dict[str, Any]]:
        plan = self._trading_plan
        if not plan:
            return []
        plan_date = str(plan.get("plan_date") or "unknown")
        risk_items = [
            item
            for item in _json_list(plan.get("blocker_summary"))
            if isinstance(item, dict)
            and str(item.get("target") or "") == "risk"
            and str(item.get("category") or "") in {"risk", "risk_blocked"}
        ]
        risk_reasons: list[str] = []
        risk_blocker_count = 0
        for item in risk_items:
            reasons = [
                str(reason)
                for reason in _json_list(item.get("reasons"))
                if str(reason).strip()
            ]
            risk_reasons.extend(reasons)
            if any(reason != "awaiting_risk_gate" for reason in reasons):
                risk_blocker_count += _int(item.get("count"), default=1)
        risk_reasons = _dedupe(risk_reasons)
        if not risk_blocker_count or not any(
            reason != "awaiting_risk_gate" for reason in risk_reasons
        ):
            return []
        detail = "Daily trading plan has risk blockers requiring review."
        if risk_reasons:
            detail = f"{detail} Reasons: {', '.join(risk_reasons)}."
        alert = self._db.upsert_automation_alert_sync(
            alert_key=f"daily_trading_plan:{plan_date}:risk_blocked",
            severity="warning",
            category="risk_gate",
            title="Daily trading plan is blocked by risk",
            detail=detail,
            source="daily_trading_plan",
            source_ref=plan_date,
            payload={
                "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                "plan_date": plan_date,
                "conclusion_status": plan.get("conclusion_status"),
                "blocked_count": _int(plan.get("blocked_count")),
                "risk_blocker_count": risk_blocker_count,
                "risk_reasons": risk_reasons,
                "broker_submission_enabled": bool(
                    plan.get("broker_submission_enabled", False)
                ),
                "does_not_submit_broker_order": True,
                "requires_manual_review": True,
            },
        )
        return [self._normalize_alert(alert)]

    def _scan_paper_shadow_divergence(self) -> list[dict[str, Any]]:
        run = self._paper_shadow_run
        if not run:
            return []
        payload = _json_object(run.get("payload_json"))
        divergence_summary = _object_dict(run.get("divergence_summary")) or (
            _object_dict(payload.get("divergence_summary"))
        )
        run_id = str(run.get("run_id") or payload.get("run_id") or "")
        if not run_id:
            return []
        status = str(run.get("status") or payload.get("status") or "unknown")
        divergence_status = str(
            run.get("divergence_status")
            or payload.get("divergence_status")
            or divergence_summary.get("status")
            or status
        )
        missing_simulation_count = _int(
            divergence_summary.get("missing_simulation_count")
        )
        diverged_order_count = _int(divergence_summary.get("diverged_order_count"))
        if (
            status not in _PAPER_SHADOW_DIVERGENCE_STATUSES
            and divergence_status not in _PAPER_SHADOW_DIVERGENCE_STATUSES
            and missing_simulation_count <= 0
            and diverged_order_count <= 0
        ):
            return []
        next_step = str(
            run.get("next_manual_review_step")
            or divergence_summary.get("next_manual_review_step")
            or payload.get("next_manual_review_step")
            or "review_shadow_divergence"
        )
        limitations = _json_list(run.get("limitations"))
        if not limitations:
            limitations = _json_list(run.get("limitations_json"))
        if not limitations:
            limitations = _json_list(payload.get("limitations"))
        evidence_refs = _json_list(run.get("evidence_refs"))
        if not evidence_refs:
            evidence_refs = _json_list(payload.get("evidence_refs"))
        detail_parts = [
            f"Paper/shadow run {run_id} is {divergence_status}.",
            f"Next step: {next_step}.",
        ]
        if diverged_order_count:
            detail_parts.append(f"Diverged orders: {diverged_order_count}.")
        if missing_simulation_count:
            detail_parts.append(f"Missing simulations: {missing_simulation_count}.")
        detail_parts.extend(str(item) for item in limitations if str(item).strip())
        alert = self._db.upsert_automation_alert_sync(
            alert_key=f"paper_shadow_run:{run_id}:{divergence_status}",
            severity="warning",
            category="paper_shadow_divergence",
            title="Paper/shadow divergence requires review",
            detail=" ".join(detail_parts),
            source="paper_shadow_run",
            source_ref=run_id,
            payload={
                "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                "run_id": run_id,
                "plan_date": run.get("plan_date") or payload.get("plan_date"),
                "status": status,
                "divergence_status": divergence_status,
                "order_intent_count": _int(run.get("order_intent_count")),
                "simulated_order_count": _int(run.get("simulated_order_count")),
                "simulated_fill_count": _int(run.get("simulated_fill_count")),
                "missing_simulation_count": missing_simulation_count,
                "diverged_order_count": diverged_order_count,
                "next_manual_review_step": next_step,
                "evidence_refs": evidence_refs,
                "limitations": limitations,
                "does_not_submit_broker_order": True,
                "does_not_mutate_production_ledger": True,
                "requires_manual_review": True,
            },
        )
        return [self._normalize_alert(alert)]

    def _scan_account_truth(self) -> list[dict[str, Any]]:
        account_truth = self._account_truth
        if not account_truth:
            return []
        gate_status = str(account_truth.get("gate_status") or "unknown")
        unresolved_count = _int(account_truth.get("unresolved_mismatch_count"))
        required_actions = [
            str(action)
            for action in _json_list(account_truth.get("required_actions"))
            if str(action).strip()
        ]
        blocking_reasons = [
            str(reason)
            for reason in _json_list(account_truth.get("blocking_reasons"))
            if str(reason).strip()
        ]
        if (
            gate_status not in _ACCOUNT_TRUTH_ALERT_STATUSES
            and unresolved_count <= 0
            and not blocking_reasons
        ):
            return []
        source_ref = str(
            account_truth.get("latest_report_id")
            or account_truth.get("report_id")
            or account_truth.get("import_run_id")
            or "latest"
        )
        detail_parts = [
            f"Account truth gate is {gate_status}.",
            f"Unresolved mismatches: {unresolved_count}.",
        ]
        if blocking_reasons:
            detail_parts.append(f"Reasons: {', '.join(blocking_reasons)}.")
        if required_actions:
            detail_parts.append(f"Next actions: {', '.join(required_actions)}.")
        alert = self._db.upsert_automation_alert_sync(
            alert_key=f"account_truth:{source_ref}:{gate_status}",
            severity="warning",
            category="account_truth",
            title="Account truth requires review",
            detail=" ".join(detail_parts),
            source="account_truth",
            source_ref=source_ref,
            payload={
                "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                "gate_status": gate_status,
                "score": _int(account_truth.get("score")),
                "cash_status": account_truth.get("cash_status"),
                "position_status": account_truth.get("position_status"),
                "fee_status": account_truth.get("fee_status"),
                "cost_basis_status": account_truth.get("cost_basis_status"),
                "data_freshness_status": account_truth.get("data_freshness_status"),
                "unresolved_mismatch_count": unresolved_count,
                "resolved_review_count": _int(
                    account_truth.get("resolved_review_count")
                ),
                "required_actions": required_actions,
                "blocking_reasons": blocking_reasons,
                "limitations": _json_list(account_truth.get("limitations")),
                "does_not_submit_broker_order": True,
                "does_not_mutate_production_ledger": True,
                "requires_manual_review": True,
            },
        )
        return [self._normalize_alert(alert)]

    def _scan_market_data_health(self) -> list[dict[str, Any]]:
        health = self._market_health
        if not health:
            return []
        source_health = str(health.get("source_health") or "unknown")
        stale_symbols_count = _int(health.get("stale_symbols_count"))
        stale_symbols_sample = [
            str(symbol)
            for symbol in _json_list(health.get("stale_symbols_sample"))
            if str(symbol).strip()
        ]
        persistent_cache_status = str(
            health.get("persistent_cache_status") or "unknown"
        )
        provider_status = str(health.get("provider_status") or "unknown")
        provider_error = str(
            health.get("provider_last_error") or health.get("last_refresh_error") or ""
        )
        is_stale = (
            source_health in _STALE_MARKET_DATA_STATUSES
            or stale_symbols_count > 0
            or persistent_cache_status == "missing"
        )
        if not is_stale:
            return []
        source_ref = str(
            health.get("latest_quote_timestamp")
            or health.get("latest_persistent_quote_timestamp")
            or health.get("last_refresh_attempt")
            or "unknown"
        )
        detail_parts = [f"Market data health is {source_health}."]
        if stale_symbols_sample:
            detail_parts.append(f"Stale symbols: {', '.join(stale_symbols_sample)}.")
        if provider_error:
            detail_parts.append(f"Provider error: {provider_error}.")
        next_action = health.get("next_action")
        if next_action:
            detail_parts.append(f"Next action: {next_action}.")
        alert = self._db.upsert_automation_alert_sync(
            alert_key=f"market_data:{source_ref}:stale",
            severity="warning",
            category="market_data",
            title="Market data freshness requires review",
            detail=" ".join(detail_parts),
            source="market_data",
            source_ref=source_ref,
            payload={
                "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
                "source_health": source_health,
                "provider_name": health.get("provider_name"),
                "provider_status": provider_status,
                "provider_last_error": provider_error or None,
                "next_action": next_action,
                "cache_age_seconds": health.get("cache_age_seconds"),
                "latest_quote_timestamp": health.get("latest_quote_timestamp"),
                "last_refresh_attempt": health.get("last_refresh_attempt"),
                "last_refresh_error": health.get("last_refresh_error"),
                "stale_symbols_count": stale_symbols_count,
                "stale_symbols_sample": stale_symbols_sample,
                "persistent_cache_status": persistent_cache_status,
                "does_not_submit_broker_order": True,
                "requires_manual_review": True,
            },
        )
        return [self._normalize_alert(alert)]

    def _kill_switch_snapshot(self) -> Any | None:
        if self._trading_controls is None:
            return None
        snapshot = getattr(self._trading_controls, "snapshot", None)
        return snapshot() if callable(snapshot) else None

    def _normalize_alert(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("payload_json")
        return {
            **row,
            "schema_version": AUTOMATION_ALERT_SCHEMA_VERSION,
            "payload": _json_object(payload),
        }


def _automation_run_suggested_action(
    *,
    status: Any,
    run_type: Any,
    execution_mode: Any,
) -> str:
    normalized_run_type = str(run_type or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    normalized_execution_mode = str(execution_mode or "").strip().lower()
    if normalized_run_type == "market_session":
        return "inspect_scheduler_failure"
    if (
        normalized_execution_mode == "paper_shadow"
        or "paper_shadow" in normalized_status
    ):
        return "inspect_failed_paper_shadow_run"
    return "inspect_failed_automation_run"


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    object_value = _object_dict(value)
    if object_value:
        return object_value
    if value in {None, ""}:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _object_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in {None, ""}:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
