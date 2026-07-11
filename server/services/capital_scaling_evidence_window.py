"""Persist deterministic scaling evidence windows from existing local facts."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from zoneinfo import ZoneInfo

from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
)

CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_SCHEMA_VERSION = (
    "karkinos.capital_scaling_account_truth_snapshot.v1"
)
CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION = (
    "karkinos.capital_scaling_evidence_window.v1"
)
CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE = (
    "capital_scaling.account_truth_snapshot_recorded"
)
CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE = (
    "capital_scaling_account_truth_snapshot"
)
CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE = "capital_scaling.evidence_window_recorded"
CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE = "capital_scaling_evidence_window"
CAPITAL_SCALING_EVIDENCE_SOURCE = "capital_scaling_evidence_window"

DEFAULT_BOUNDARY_GAP_HOURS = 72
MAX_ACCOUNT_TRUTH_CAPTURE_LAG_SECONDS = 900
MAX_SOURCE_ROWS = 5000

_REAL_EXECUTION_MODES = frozenset({"manual", "controlled_live", "live"})
_POLICY_VIOLATION_GATEWAY_EVENTS = frozenset(
    {"live_submission_rejected", "live_cancel_rejected"}
)
_DISCONNECT_MARKERS = (
    "disconnect",
    "unavailable",
    "timeout",
    "connector_error",
    "connection_error",
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class CapitalScalingEvidenceWindowService:
    """Build audit evidence without mutating execution or account state."""

    def __init__(
        self,
        *,
        db: Any,
        account_truth_provider: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._account_truth_provider = account_truth_provider or (lambda: {})
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.capital_scaling_evidence_status.v1",
            "evidence_contract_status": "read_only_append_only",
            "account_truth_snapshot_recording_enabled": True,
            "evidence_window_recording_enabled": True,
            "accepted_window_input_fields": [
                "review_window_start",
                "review_window_end",
                "max_boundary_gap_hours",
            ],
            "computed_evidence_kinds": [
                "account_truth",
                "after_cost",
                "incident",
                "capacity",
                "operating_sample",
            ],
            "automatic_scale_up_enabled": False,
            "authority_change_enabled": False,
            "broker_submission_enabled": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "limitations": [
                "Account Truth point snapshots must be recorded near both review-window boundaries.",
                "After-cost return uses Modified Dietz over persisted portfolio snapshots and external cash flows.",
                "Capacity evidence requires non-simulated reconciled fills with explicit capacity and liquidity source metadata.",
                "Evidence completeness does not imply favorable performance or authorize scale-up.",
            ],
        }

    def preview_account_truth_snapshot(self) -> dict[str, Any]:
        captured_at = _aware_utc(self._clock())
        try:
            source = self._account_truth_provider() or {}
        except Exception as exc:  # source errors must block, never authorize
            source = {"provider_error": type(exc).__name__}
        sanitized = _sanitized_account_truth_source(source)
        blockers: list[str] = []
        source_at = _parse_datetime(str(sanitized.get("created_at") or ""))
        if not sanitized.get("import_run_id"):
            blockers.append("account_truth_import_run_missing")
        if str(sanitized.get("gate_status") or "") != "pass":
            blockers.append("account_truth_gate_not_pass")
        if str(sanitized.get("data_freshness_status") or "") != "fresh":
            blockers.append("account_truth_data_not_fresh")
        if int(sanitized.get("unresolved_mismatch_count") or 0) != 0:
            blockers.append("account_truth_unresolved_mismatches")
        if source_at is None:
            blockers.append("account_truth_source_timestamp_invalid")
        else:
            capture_lag = (captured_at - source_at).total_seconds()
            if capture_lag < -60:
                blockers.append("account_truth_source_timestamp_in_future")
            elif capture_lag > MAX_ACCOUNT_TRUTH_CAPTURE_LAG_SECONDS:
                blockers.append("account_truth_capture_lag_exceeded")
        source_fingerprint = _fingerprint(sanitized)
        snapshot_id = _fingerprint(
            {
                "schema_version": CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_SCHEMA_VERSION,
                "source_fingerprint": source_fingerprint,
                "source_created_at": sanitized.get("created_at"),
            }
        )
        return {
            "schema_version": CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "status": "clear" if not blockers else "blocked",
            "observed_at": sanitized.get("created_at"),
            "captured_at": captured_at.isoformat(),
            "source_fingerprint": source_fingerprint,
            "account_truth": sanitized,
            "blockers": blockers,
            "persisted": False,
            "reused": False,
            "does_not_mutate_account_truth": True,
            "does_not_issue_capital_authorization": True,
            "does_not_submit_broker_order": True,
        }

    def record_account_truth_snapshot(self) -> dict[str, Any]:
        snapshot = self.preview_account_truth_snapshot()
        snapshot_id = str(snapshot["snapshot_id"])
        existing = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE,
            entity_id=snapshot_id,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        payload = {
            key: value
            for key, value in snapshot.items()
            if key not in {"persisted", "reused"}
        }
        self._db.append_event_sync(
            event_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE,
            timestamp=str(snapshot.get("captured_at") or ""),
            entity_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE,
            entity_id=snapshot_id,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            source_ref=str(
                (snapshot.get("account_truth") or {}).get("import_run_id") or ""
            ),
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE,
            entity_id=snapshot_id,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError(
                "capital scaling Account Truth snapshot was not recorded"
            )
        return _event_response(saved[0], reused=False)

    def list_account_truth_snapshots(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def preview_window(
        self,
        *,
        review_window_start: datetime,
        review_window_end: datetime,
        max_boundary_gap_hours: int = DEFAULT_BOUNDARY_GAP_HOURS,
    ) -> dict[str, Any]:
        start, end, gap_hours = _validated_window(
            review_window_start,
            review_window_end,
            max_boundary_gap_hours=max_boundary_gap_hours,
        )
        account_truth = self._account_truth_fact(
            start=start,
            end=end,
            max_boundary_gap_hours=gap_hours,
        )
        after_cost = self._after_cost_fact(
            start=start,
            end=end,
            max_boundary_gap_hours=gap_hours,
            account_truth=account_truth,
        )
        incident = self._incident_fact(start=start, end=end)
        capacity = self._capacity_fact(start=start, end=end)
        operating_sample = self._operating_sample_fact(
            start=start,
            end=end,
            account_truth=account_truth,
        )
        facts = {
            "account_truth": account_truth,
            "after_cost": after_cost,
            "incident": incident,
            "capacity": capacity,
            "operating_sample": operating_sample,
        }
        identity = {
            "schema_version": CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION,
            "review_window_start": start.isoformat(),
            "review_window_end": end.isoformat(),
            "max_boundary_gap_hours": gap_hours,
            "fact_fingerprints": {
                kind: fact["source_fingerprint"] for kind, fact in facts.items()
            },
        }
        window_id = _fingerprint(identity)
        evidence_refs = [f"{kind}:{window_id}" for kind in facts]
        blockers = list(
            dict.fromkeys(
                f"{kind}:{blocker}"
                for kind, fact in facts.items()
                for blocker in fact.get("blockers") or []
            )
        )
        return {
            "schema_version": CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION,
            "window_id": window_id,
            "review_window_start": start.isoformat(),
            "review_window_end": end.isoformat(),
            "max_boundary_gap_hours": gap_hours,
            "status": "clear" if not blockers else "blocked",
            "facts": facts,
            "evidence_refs": evidence_refs,
            "blockers": blockers,
            "persisted": False,
            "reused": False,
            "automatic_scale_up_enabled": False,
            "authority_change_applied": False,
            "does_not_mutate_account_truth": True,
            "does_not_mutate_oms": True,
            "does_not_mutate_runtime_limits": True,
            "does_not_mutate_production_ledger": True,
            "does_not_submit_or_cancel_broker_order": True,
        }

    def record_window(
        self,
        *,
        review_window_start: datetime,
        review_window_end: datetime,
        max_boundary_gap_hours: int = DEFAULT_BOUNDARY_GAP_HOURS,
    ) -> dict[str, Any]:
        window = self.preview_window(
            review_window_start=review_window_start,
            review_window_end=review_window_end,
            max_boundary_gap_hours=max_boundary_gap_hours,
        )
        window_id = str(window["window_id"])
        existing = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
            entity_id=window_id,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        payload = {
            key: value
            for key, value in window.items()
            if key not in {"persisted", "reused"}
        }
        self._db.append_event_sync(
            event_type=CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
            timestamp=_aware_utc(self._clock()).isoformat(),
            entity_type=CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
            entity_id=window_id,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            source_ref=f"{window['review_window_start']}..{window['review_window_end']}",
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
            entity_id=window_id,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("capital scaling evidence window was not recorded")
        return _event_response(saved[0], reused=False)

    def list_windows(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def _account_truth_fact(
        self,
        *,
        start: datetime,
        end: datetime,
        max_boundary_gap_hours: int,
    ) -> dict[str, Any]:
        rows = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            limit=MAX_SOURCE_ROWS,
        )
        snapshots = []
        for row in rows:
            payload = _json_object(row.get("payload_json"))
            observed_at = _parse_datetime(str(payload.get("observed_at") or ""))
            if observed_at is None:
                continue
            snapshots.append((observed_at, payload))
        start_snapshot = _nearest_snapshot(snapshots, target=start)
        end_snapshot = _nearest_snapshot(snapshots, target=end)
        blockers: list[str] = []
        if len(rows) >= MAX_SOURCE_ROWS:
            blockers.append("account_truth_snapshot_scan_truncated")
        max_gap_seconds = max_boundary_gap_hours * 3600
        if start_snapshot is None:
            blockers.append("start_account_truth_snapshot_missing")
        elif abs((start_snapshot[0] - start).total_seconds()) > max_gap_seconds:
            blockers.append("start_account_truth_boundary_gap_exceeded")
        elif start_snapshot[1].get("status") != "clear":
            blockers.append("start_account_truth_snapshot_not_clear")
        if end_snapshot is None:
            blockers.append("end_account_truth_snapshot_missing")
        elif abs((end_snapshot[0] - end).total_seconds()) > max_gap_seconds:
            blockers.append("end_account_truth_boundary_gap_exceeded")
        elif end_snapshot[1].get("status") != "clear":
            blockers.append("end_account_truth_snapshot_not_clear")
        if (
            start_snapshot is not None
            and end_snapshot is not None
            and start_snapshot[1].get("snapshot_id")
            == end_snapshot[1].get("snapshot_id")
        ):
            blockers.append("distinct_account_truth_boundary_snapshots_required")
        source_refs = [
            f"account_truth_snapshot:{snapshot[1].get('snapshot_id')}"
            for snapshot in (start_snapshot, end_snapshot)
            if snapshot is not None and snapshot[1].get("snapshot_id")
        ]
        metrics = {
            "start_score": _nested_int(start_snapshot, "score"),
            "end_score": _nested_int(end_snapshot, "score"),
            "start_unresolved_mismatch_count": _nested_int(
                start_snapshot, "unresolved_mismatch_count"
            ),
            "end_unresolved_mismatch_count": _nested_int(
                end_snapshot, "unresolved_mismatch_count"
            ),
        }
        return _fact(
            kind="account_truth",
            metrics=metrics,
            blockers=blockers,
            source_refs=source_refs,
            assumptions=[
                "Both review-window boundaries require independently recorded Account Truth snapshots.",
                "A clear snapshot requires pass/fresh/zero-unresolved source evidence captured within 15 minutes of its import.",
            ],
            limitations=[
                "Boundary tolerance is configurable and defaults to 72 hours to cover market closures.",
            ],
        )

    def _after_cost_fact(
        self,
        *,
        start: datetime,
        end: datetime,
        max_boundary_gap_hours: int,
        account_truth: dict[str, Any],
    ) -> dict[str, Any]:
        rows = self._db.list_events_sync(
            event_type="portfolio.snapshot.created",
            entity_type="portfolio",
            entity_id="default",
            source="portfolio_snapshots",
            limit=MAX_SOURCE_ROWS,
        )
        snapshots: list[tuple[datetime, dict[str, Any]]] = []
        for row in rows:
            payload = _json_object(row.get("payload_json"))
            observed_at = _parse_datetime(
                str(payload.get("timestamp") or row.get("timestamp") or "")
            )
            if observed_at is None or observed_at < start or observed_at > end:
                continue
            snapshots.append((observed_at, payload))
        snapshots.sort(key=lambda item: item[0])
        blockers: list[str] = []
        if len(rows) >= MAX_SOURCE_ROWS:
            blockers.append("portfolio_snapshot_scan_truncated")
        if account_truth.get("status") != "clear":
            blockers.append("account_truth_boundary_coverage_not_clear")
        if len(snapshots) < 2:
            blockers.append("portfolio_boundary_snapshots_missing")
            return _fact(
                kind="after_cost",
                metrics={
                    "after_cost_return_pct": None,
                    "net_external_cash_flow": None,
                    "start_total_equity": None,
                    "end_total_equity": None,
                },
                blockers=blockers,
                source_refs=list(account_truth.get("source_refs") or []),
                assumptions=[
                    "After-cost return uses Modified Dietz over account-level total equity.",
                ],
                limitations=[
                    "At least two persisted portfolio snapshots are required inside the review window.",
                ],
            )
        start_at, start_payload = snapshots[0]
        end_at, end_payload = snapshots[-1]
        max_gap_seconds = max_boundary_gap_hours * 3600
        if (start_at - start).total_seconds() > max_gap_seconds:
            blockers.append("start_portfolio_boundary_gap_exceeded")
        if (end - end_at).total_seconds() > max_gap_seconds:
            blockers.append("end_portfolio_boundary_gap_exceeded")
        start_equity = _decimal(start_payload.get("total_equity"))
        end_equity = _decimal(end_payload.get("total_equity"))
        if start_equity is None or start_equity <= 0:
            blockers.append("start_total_equity_invalid")
        if end_equity is None or end_equity < 0:
            blockers.append("end_total_equity_invalid")
        cash_flows: list[tuple[datetime, Decimal, int]] = []
        cash_flow_rows = self._db.get_cash_flows_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(cash_flow_rows) >= MAX_SOURCE_ROWS:
            blockers.append("cash_flow_scan_truncated")
        for row in cash_flow_rows:
            occurred_at = _parse_datetime(str(row.get("timestamp") or ""))
            amount = _decimal(row.get("amount"))
            flow_type = str(row.get("flow_type") or "").lower()
            if occurred_at is None or amount is None:
                blockers.append("cash_flow_fact_invalid")
                continue
            if occurred_at < start_at or occurred_at > end_at:
                continue
            if flow_type == "withdraw":
                amount = -abs(amount)
            elif flow_type == "deposit":
                amount = abs(amount)
            else:
                blockers.append("cash_flow_type_unsupported")
                continue
            cash_flows.append((occurred_at, amount, int(row.get("id") or 0)))
        after_cost_return: Decimal | None = None
        net_flow = sum((item[1] for item in cash_flows), Decimal("0"))
        if start_equity is not None and end_equity is not None:
            duration_seconds = Decimal(str((end_at - start_at).total_seconds()))
            if duration_seconds <= 0:
                blockers.append("portfolio_snapshot_interval_invalid")
            else:
                weighted_flow = sum(
                    (
                        amount
                        * Decimal(str((end_at - occurred_at).total_seconds()))
                        / duration_seconds
                        for occurred_at, amount, _ in cash_flows
                    ),
                    Decimal("0"),
                )
                denominator = start_equity + weighted_flow
                if denominator <= 0:
                    blockers.append("modified_dietz_denominator_not_positive")
                else:
                    after_cost_return = (
                        end_equity - start_equity - net_flow
                    ) / denominator
        source_refs = (
            list(account_truth.get("source_refs") or [])
            + [
                f"portfolio_snapshot:{start_payload.get('snapshot_id')}",
                f"portfolio_snapshot:{end_payload.get('snapshot_id')}",
            ]
            + [f"cash_flow:{row_id}" for _, _, row_id in cash_flows]
        )
        return _fact(
            kind="after_cost",
            metrics={
                "after_cost_return_pct": _decimal_string_or_none(after_cost_return),
                "net_external_cash_flow": _decimal_string(net_flow),
                "start_total_equity": _decimal_string_or_none(start_equity),
                "end_total_equity": _decimal_string_or_none(end_equity),
                "portfolio_snapshot_count": len(snapshots),
                "cash_flow_count": len(cash_flows),
            },
            blockers=blockers,
            source_refs=source_refs,
            assumptions=[
                "Persisted total equity already reflects recorded commissions, taxes, fees, and current valuation inputs.",
                "Modified Dietz removes time-weighted external deposits and withdrawals from account-level return.",
            ],
            limitations=[
                "This is account-level after-cost evidence, not strategy attribution or a profit guarantee.",
                "A clear result still requires the separate scaling thresholds and every other gate.",
            ],
        )

    def _incident_fact(self, *, start: datetime, end: datetime) -> dict[str, Any]:
        blockers: list[str] = []
        critical_alerts: list[dict[str, Any]] = []
        policy_events: list[dict[str, Any]] = []
        disconnect_events: list[dict[str, Any]] = []
        try:
            alerts = self._db.list_automation_alerts_sync(limit=MAX_SOURCE_ROWS)
        except Exception as exc:
            alerts = []
            blockers.append(f"automation_alert_scan_failed:{type(exc).__name__}")
        if len(alerts) >= MAX_SOURCE_ROWS:
            blockers.append("automation_alert_scan_truncated")
        for row in alerts:
            occurred_at = _parse_datetime(str(row.get("created_at") or ""))
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            if str(row.get("severity") or "").lower() == "critical":
                critical_alerts.append(row)
        try:
            gateway_events = self._db.list_broker_gateway_events_sync(
                limit=MAX_SOURCE_ROWS
            )
        except Exception as exc:
            gateway_events = []
            blockers.append(f"gateway_event_scan_failed:{type(exc).__name__}")
        if len(gateway_events) >= MAX_SOURCE_ROWS:
            blockers.append("gateway_event_scan_truncated")
        for row in gateway_events:
            occurred_at = _parse_datetime(str(row.get("created_at") or ""))
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            if str(row.get("event_type") or "") in _POLICY_VIOLATION_GATEWAY_EVENTS:
                policy_events.append(row)
        try:
            soak_rows = self._db.list_events_sync(
                event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
                entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
                source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
                limit=MAX_SOURCE_ROWS,
            )
        except Exception as exc:
            soak_rows = []
            blockers.append(f"broker_soak_scan_failed:{type(exc).__name__}")
        if len(soak_rows) >= MAX_SOURCE_ROWS:
            blockers.append("broker_soak_scan_truncated")
        for row in soak_rows:
            payload = _json_object(row.get("payload_json"))
            occurred_at = _parse_datetime(
                str(payload.get("observed_at") or row.get("timestamp") or "")
            )
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            reason_text = " ".join(
                str(item).lower() for item in payload.get("blockers") or []
            )
            if any(marker in reason_text for marker in _DISCONNECT_MARKERS):
                disconnect_events.append(row)
        return _fact(
            kind="incident",
            metrics={
                "critical_incident_count": len(critical_alerts),
                "policy_violation_count": len(policy_events),
                "broker_disconnect_count": len(disconnect_events),
            },
            blockers=blockers,
            source_refs=[
                *(f"automation_alert:{row.get('id')}" for row in critical_alerts),
                *(f"broker_gateway_event:{row.get('id')}" for row in policy_events),
                *(f"broker_soak_event:{row.get('id')}" for row in disconnect_events),
            ],
            assumptions=[
                "Rejected live submit/cancel attempts count as policy violations even though no broker write occurred.",
                "Critical alerts remain incident evidence even after acknowledgement.",
            ],
            limitations=[
                "Only persisted Karkinos alerts, gateway rejections, and connector observations are counted.",
            ],
        )

    def _capacity_fact(self, *, start: datetime, end: datetime) -> dict[str, Any]:
        blockers: list[str] = []
        qualifying: list[dict[str, Any]] = []
        incomplete_count = 0
        fill_rows = self._db.list_fills_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(fill_rows) >= MAX_SOURCE_ROWS:
            blockers.append("fill_scan_truncated")
        for row in fill_rows:
            occurred_at = _parse_datetime(str(row.get("timestamp") or ""))
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            if str(row.get("execution_mode") or "") not in _REAL_EXECUTION_MODES:
                continue
            source = str(row.get("source") or "").lower()
            if "paper" in source or "simulat" in source:
                continue
            metadata = _json_object(row.get("metadata_json"))
            gross = (_decimal(row.get("fill_price")) or Decimal("0")) * abs(
                _decimal(row.get("fill_quantity")) or Decimal("0")
            )
            capacity_limit = _decimal(metadata.get("capacity_limit_notional"))
            available_liquidity = _decimal(metadata.get("available_liquidity_notional"))
            required = (
                row.get("provider_name"),
                row.get("broker_order_id"),
                metadata.get("account_truth_import_run_id"),
                metadata.get("execution_reconciliation_run_id"),
                metadata.get("capacity_model_ref"),
                metadata.get("market_data_ref"),
            )
            if (
                gross <= 0
                or capacity_limit is None
                or capacity_limit <= 0
                or available_liquidity is None
                or available_liquidity <= 0
                or not all(str(item or "").strip() for item in required)
            ):
                incomplete_count += 1
                continue
            slippage = abs(_decimal(row.get("slippage")) or Decimal("0"))
            qualifying.append(
                {
                    "fill_id": str(row.get("fill_id") or ""),
                    "slippage_bps": slippage / gross * Decimal("10000"),
                    "capacity_utilization_pct": gross / capacity_limit,
                    "liquidity_utilization_pct": gross / available_liquidity,
                    "account_truth_import_run_id": metadata.get(
                        "account_truth_import_run_id"
                    ),
                    "execution_reconciliation_run_id": metadata.get(
                        "execution_reconciliation_run_id"
                    ),
                    "capacity_model_ref": metadata.get("capacity_model_ref"),
                    "market_data_ref": metadata.get("market_data_ref"),
                }
            )
        if not qualifying:
            blockers.append("reconciled_real_fill_capacity_evidence_missing")
        if incomplete_count:
            blockers.append("real_fill_capacity_metadata_incomplete")
        slippages = [item["slippage_bps"] for item in qualifying]
        capacities = [item["capacity_utilization_pct"] for item in qualifying]
        liquidities = [item["liquidity_utilization_pct"] for item in qualifying]
        return _fact(
            kind="capacity",
            metrics={
                "fill_count": len(qualifying),
                "incomplete_fill_count": incomplete_count,
                "average_slippage_bps": _decimal_string_or_none(_average(slippages)),
                "p95_slippage_bps": _decimal_string_or_none(
                    _nearest_rank(slippages, Decimal("0.95"))
                ),
                "capacity_utilization_pct": _decimal_string_or_none(
                    max(capacities) if capacities else None
                ),
                "liquidity_utilization_pct": _decimal_string_or_none(
                    max(liquidities) if liquidities else None
                ),
            },
            blockers=blockers,
            source_refs=[
                ref
                for item in qualifying
                for ref in (
                    f"fill:{item['fill_id']}",
                    f"account_truth_import:{item['account_truth_import_run_id']}",
                    f"execution_reconciliation:{item['execution_reconciliation_run_id']}",
                    str(item["capacity_model_ref"]),
                    str(item["market_data_ref"]),
                )
            ],
            assumptions=[
                "Stored fill slippage is monetary impact; basis points divide it by absolute fill notional.",
                "Capacity and liquidity utilization use the explicit per-fill model limits recorded by the reviewed fill producer.",
            ],
            limitations=[
                "Paper, simulated, unlinked, or metadata-incomplete fills cannot support capital scaling.",
                "Maximum utilization is used instead of averaging away a stressed fill.",
            ],
        )

    def _operating_sample_fact(
        self,
        *,
        start: datetime,
        end: datetime,
        account_truth: dict[str, Any],
    ) -> dict[str, Any]:
        blockers: list[str] = []
        source_refs = list(account_truth.get("source_refs") or [])
        if account_truth.get("status") != "clear":
            blockers.append("account_truth_boundary_coverage_not_clear")

        soak_rows = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=MAX_SOURCE_ROWS,
        )
        if len(soak_rows) >= MAX_SOURCE_ROWS:
            blockers.append("broker_soak_scan_truncated")
        healthy_days: set[str] = set()
        for row in soak_rows:
            payload = _json_object(row.get("payload_json"))
            observed_at = _parse_datetime(
                str(payload.get("observed_at") or row.get("timestamp") or "")
            )
            if observed_at is None or observed_at < start or observed_at > end:
                continue
            trading_day = str(payload.get("trading_day") or "")
            if payload.get("qualifies_for_healthy_soak_day") is True and trading_day:
                healthy_days.add(trading_day)
                source_refs.append(f"broker_soak_event:{row.get('id')}")
        if not healthy_days:
            blockers.append("healthy_broker_soak_trading_days_missing")

        fill_rows = self._db.list_fills_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(fill_rows) >= MAX_SOURCE_ROWS:
            blockers.append("fill_scan_truncated")
        real_fills: list[tuple[dict[str, Any], datetime, dict[str, Any]]] = []
        incomplete_real_fill_count = 0
        for row in fill_rows:
            occurred_at = _parse_datetime(str(row.get("timestamp") or ""))
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            if not _is_real_execution_row(row):
                continue
            metadata = _json_object(row.get("metadata_json"))
            if not _has_reconciled_fill_linkage(row, metadata):
                incomplete_real_fill_count += 1
                continue
            real_fills.append((row, occurred_at, metadata))
            source_refs.append(f"fill:{row.get('fill_id')}")
        if incomplete_real_fill_count:
            blockers.append("real_fill_account_truth_or_reconciliation_link_missing")

        oms_rows = self._db.list_oms_orders_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(oms_rows) >= MAX_SOURCE_ROWS:
            blockers.append("oms_order_scan_truncated")
        fill_order_ids = {str(row.get("order_id") or "") for row, _, _ in real_fills}
        orders: list[tuple[dict[str, Any], datetime, dict[str, Any]]] = []
        for row in oms_rows:
            payload = _json_object(row.get("payload_json"))
            if str(payload.get("execution_mode") or "").lower() == "paper_shadow":
                continue
            created_at = _parse_datetime(str(row.get("created_at") or ""))
            order_id = str(row.get("order_id") or "")
            if created_at is None:
                if order_id in fill_order_ids:
                    blockers.append("oms_order_timestamp_invalid")
                continue
            if not (start <= created_at <= end or order_id in fill_order_ids):
                continue
            orders.append((row, created_at, payload))
            source_refs.append(f"oms_order:{order_id}")
        if not orders:
            blockers.append("real_order_sample_missing")

        order_ids = {str(row.get("order_id") or "") for row, _, _ in orders}
        if any(
            str(row.get("order_id") or "") not in order_ids for row, _, _ in real_fills
        ):
            blockers.append("orphan_real_fill_evidence")
        fills_by_order: dict[
            str, list[tuple[dict[str, Any], datetime, dict[str, Any]]]
        ] = {}
        for item in real_fills:
            fills_by_order.setdefault(str(item[0].get("order_id") or ""), []).append(
                item
            )

        filled_order_count = 0
        rejected_order_count = 0
        partial_fill_count = 0
        cancelled_or_expired_count = 0
        nonterminal_count = 0
        transitions_by_order: dict[str, list[dict[str, Any]]] = {}
        terminal_source_times: dict[str, datetime] = {}
        for row, created_at, _ in orders:
            order_id = str(row.get("order_id") or "")
            transitions = self._db.list_oms_transitions_sync(order_id)
            transitions_by_order[order_id] = transitions
            for transition in transitions:
                if transition.get("id") is not None:
                    source_refs.append(f"oms_transition:{transition.get('id')}")
            effective_status = _effective_terminal_status(row, transitions)
            order_quantity = _decimal(row.get("quantity")) or Decimal("0")
            order_fills = fills_by_order.get(order_id, [])
            filled_quantity = sum(
                (
                    abs(_decimal(fill.get("fill_quantity")) or Decimal("0"))
                    for fill, _, _ in order_fills
                ),
                Decimal("0"),
            )
            if filled_quantity > order_quantity and order_quantity > 0:
                blockers.append("fill_quantity_exceeds_order_quantity")
            transition_partial = any(
                str(item.get("to_status") or "") == "partially_filled"
                for item in transitions
            )
            if transition_partial or (
                order_quantity > 0 and Decimal("0") < filled_quantity < order_quantity
            ):
                partial_fill_count += 1
            if effective_status == "filled" and filled_quantity >= order_quantity > 0:
                filled_order_count += 1
            elif effective_status == "rejected":
                rejected_order_count += 1
            elif effective_status in {"cancelled", "expired"}:
                cancelled_or_expired_count += 1
            else:
                nonterminal_count += 1
            source_times = [created_at]
            source_times.extend(fill_time for _, fill_time, _ in order_fills)
            source_times.extend(
                timestamp
                for transition in transitions
                if (
                    timestamp := _parse_datetime(
                        str(transition.get("transitioned_at") or "")
                    )
                )
                is not None
            )
            terminal_source_times[order_id] = max(source_times)
            sample_day = max(source_times).astimezone(_SHANGHAI).date().isoformat()
            if sample_day not in healthy_days:
                blockers.append("order_day_without_healthy_broker_soak")
        if nonterminal_count:
            blockers.append("nonterminal_real_order_evidence_present")

        reconciliation_rows = self._db.list_execution_reconciliation_runs_sync(
            limit=MAX_SOURCE_ROWS,
            offset=0,
        )
        if len(reconciliation_rows) >= MAX_SOURCE_ROWS:
            blockers.append("execution_reconciliation_scan_truncated")
        reconciliation_runs: list[
            tuple[datetime, dict[str, Any], list[dict[str, Any]]]
        ] = []
        for run in reconciliation_rows:
            run_date = str(run.get("run_date") or "")
            try:
                run_day = datetime.fromisoformat(run_date).date()
            except ValueError:
                continue
            if run_day < start.date() or run_day > end.date():
                continue
            updated_at = _parse_datetime(str(run.get("updated_at") or ""))
            if updated_at is None:
                blockers.append("execution_reconciliation_timestamp_invalid")
                continue
            items = self._db.list_execution_reconciliation_items_sync(
                str(run.get("run_id") or "")
            )
            reconciliation_runs.append((updated_at, run, items))
            source_refs.append(f"execution_reconciliation:{run.get('run_id')}")
        reconciliation_runs.sort(key=lambda item: item[0])
        unresolved_reconciliation_count: int | None = None
        reconciliation_latencies: list[Decimal] = []
        if not reconciliation_runs:
            blockers.append("execution_reconciliation_sample_missing")
        else:
            _, latest_run, latest_items = reconciliation_runs[-1]
            unresolved_reconciliation_count = int(
                latest_run.get("open_item_count") or 0
            )
            latest_item_order_ids = {
                str(item.get("order_id") or "") for item in latest_items
            }
            if not order_ids.issubset(latest_item_order_ids):
                blockers.append("latest_reconciliation_order_coverage_incomplete")
            for order_id in sorted(order_ids):
                source_time = terminal_source_times.get(order_id)
                if source_time is None:
                    blockers.append("order_terminal_source_time_missing")
                    continue
                matched_at: datetime | None = None
                for run_at, _, items in reconciliation_runs:
                    if run_at < source_time:
                        continue
                    item = next(
                        (
                            candidate
                            for candidate in items
                            if str(candidate.get("order_id") or "") == order_id
                        ),
                        None,
                    )
                    if item is None or str(item.get("suggested_action") or "") != (
                        "no_action"
                    ):
                        continue
                    matched_at = run_at
                    break
                if matched_at is None:
                    blockers.append("clear_reconciliation_latency_coverage_missing")
                    continue
                latency = Decimal(str((matched_at - source_time).total_seconds())) / (
                    Decimal("60")
                )
                reconciliation_latencies.append(max(latency, Decimal("0")))
        if orders and not reconciliation_latencies:
            blockers.append("reconciliation_latency_sample_missing")

        paper_rows = self._db.list_orders_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(paper_rows) >= MAX_SOURCE_ROWS:
            blockers.append("paper_shadow_order_scan_truncated")
        paper_sample_count = 0
        paper_shadow_divergence_count = 0
        for row in paper_rows:
            if str(row.get("execution_mode") or "") != "paper_shadow":
                continue
            occurred_at = _parse_datetime(str(row.get("timestamp") or ""))
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            payload = _json_object(row.get("payload_json"))
            divergence_status = str(payload.get("divergence_status") or "")
            paper_sample_count += 1
            if divergence_status not in {"within_expectations", "not_required"}:
                paper_shadow_divergence_count += 1
            source_refs.append(f"paper_shadow_order:{row.get('order_id')}")
        if orders and not paper_sample_count:
            blockers.append("paper_shadow_divergence_sample_missing")

        drawdown, drawdown_blockers, drawdown_refs = self._unitized_drawdown(
            start=start,
            end=end,
        )
        blockers.extend(drawdown_blockers)
        source_refs.extend(drawdown_refs)
        return _fact(
            kind="operating_sample",
            metrics={
                "reviewed_trading_days": len(healthy_days),
                "order_count": len(orders),
                "filled_order_count": filled_order_count,
                "rejected_order_count": rejected_order_count,
                "partial_fill_count": partial_fill_count,
                "cancelled_or_expired_order_count": cancelled_or_expired_count,
                "nonterminal_order_count": nonterminal_count,
                "unresolved_reconciliation_count": unresolved_reconciliation_count,
                "p95_reconciliation_latency_minutes": _decimal_string_or_none(
                    _nearest_rank(reconciliation_latencies, Decimal("0.95"))
                ),
                "reconciliation_latency_coverage_count": len(reconciliation_latencies),
                "paper_shadow_sample_count": paper_sample_count,
                "paper_shadow_divergence_count": paper_shadow_divergence_count,
                "max_drawdown_pct": _decimal_string_or_none(drawdown),
                "incomplete_real_fill_count": incomplete_real_fill_count,
            },
            blockers=blockers,
            source_refs=source_refs,
            assumptions=[
                "The order sample includes non-paper OMS orders created in the window or linked to a reconciled real fill in the window.",
                "Filled orders require persisted real fill quantity at least equal to OMS quantity; rejected means the effective terminal OMS state is rejected.",
                "Reconciliation latency runs from the latest persisted order/fill/transition fact to the first no-action reconciliation item covering that order.",
                "Reviewed trading days are distinct healthy read-only broker-soak trading days.",
                "Drawdown uses cash-flow-unitized portfolio equity rather than raw equity changes.",
            ],
            limitations=[
                "Current reconciliation runs are order-covered, not yet runtime-session or broker-batch identified.",
                "Paper/shadow divergence is counted from persisted paper/shadow order facts.",
                "Cash flows between portfolio snapshots are unitized at the next persisted equity point because no valuation exists at the exact flow time.",
                "Cancelled and expired orders are disclosed separately and are not silently relabeled as broker rejections.",
            ],
        )

    def _unitized_drawdown(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[Decimal | None, list[str], list[str]]:
        blockers: list[str] = []
        source_refs: list[str] = []
        rows = self._db.list_events_sync(
            event_type="portfolio.snapshot.created",
            entity_type="portfolio",
            entity_id="default",
            source="portfolio_snapshots",
            limit=MAX_SOURCE_ROWS,
        )
        if len(rows) >= MAX_SOURCE_ROWS:
            blockers.append("portfolio_snapshot_scan_truncated")
        points: list[tuple[datetime, Decimal, str]] = []
        for row in rows:
            payload = _json_object(row.get("payload_json"))
            observed_at = _parse_datetime(
                str(payload.get("timestamp") or row.get("timestamp") or "")
            )
            equity = _decimal(payload.get("total_equity"))
            if observed_at is None or observed_at < start or observed_at > end:
                continue
            if equity is None or equity <= 0:
                blockers.append("drawdown_equity_point_invalid")
                continue
            points.append(
                (
                    observed_at,
                    equity,
                    f"portfolio_snapshot:{payload.get('snapshot_id')}",
                )
            )
        points.sort(key=lambda item: item[0])
        if len(points) < 2:
            blockers.append("drawdown_equity_series_insufficient")
            return None, blockers, source_refs
        cash_flow_rows = self._db.get_cash_flows_sync(
            limit=MAX_SOURCE_ROWS,
            offset=0,
        )
        if len(cash_flow_rows) >= MAX_SOURCE_ROWS:
            blockers.append("cash_flow_scan_truncated")
        flows: list[tuple[datetime, Decimal, str]] = []
        for row in cash_flow_rows:
            occurred_at = _parse_datetime(str(row.get("timestamp") or ""))
            amount = _decimal(row.get("amount"))
            flow_type = str(row.get("flow_type") or "").lower()
            if occurred_at is None or amount is None:
                blockers.append("drawdown_cash_flow_fact_invalid")
                continue
            if occurred_at <= points[0][0] or occurred_at > points[-1][0]:
                continue
            if flow_type == "deposit":
                amount = abs(amount)
            elif flow_type == "withdraw":
                amount = -abs(amount)
            else:
                blockers.append("drawdown_cash_flow_type_unsupported")
                continue
            flows.append((occurred_at, amount, f"cash_flow:{row.get('id')}"))
        flows.sort(key=lambda item: item[0])
        units = points[0][1]
        unit_prices = [Decimal("1")]
        flow_index = 0
        previous_at = points[0][0]
        for observed_at, equity, _ in points[1:]:
            period_flow = Decimal("0")
            while flow_index < len(flows) and flows[flow_index][0] <= observed_at:
                if flows[flow_index][0] > previous_at:
                    period_flow += flows[flow_index][1]
                flow_index += 1
            pre_flow_equity = equity - period_flow
            if units <= 0 or pre_flow_equity <= 0:
                blockers.append("drawdown_unitization_invalid")
                return None, blockers, source_refs
            unit_price = pre_flow_equity / units
            if unit_price <= 0:
                blockers.append("drawdown_unit_price_invalid")
                return None, blockers, source_refs
            units += period_flow / unit_price
            if units <= 0:
                blockers.append("drawdown_units_not_positive")
                return None, blockers, source_refs
            unit_prices.append(unit_price)
            previous_at = observed_at
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        for unit_price in unit_prices:
            peak = max(peak, unit_price)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - unit_price) / peak)
        source_refs.extend(ref for _, _, ref in points)
        source_refs.extend(ref for _, _, ref in flows)
        return max_drawdown, blockers, source_refs


def _validated_window(
    start: datetime,
    end: datetime,
    *,
    max_boundary_gap_hours: int,
) -> tuple[datetime, datetime, int]:
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("review_window_start must be timezone-aware")
    if end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("review_window_end must be timezone-aware")
    normalized_start = _aware_utc(start)
    normalized_end = _aware_utc(end)
    if normalized_start >= normalized_end:
        raise ValueError("review window start must precede end")
    if (normalized_end - normalized_start).days > 366:
        raise ValueError("review window cannot exceed 366 days")
    gap_hours = int(max_boundary_gap_hours)
    if gap_hours < 1 or gap_hours > 168:
        raise ValueError("max_boundary_gap_hours must be between 1 and 168")
    return normalized_start, normalized_end, gap_hours


def _is_real_execution_row(row: dict[str, Any]) -> bool:
    if str(row.get("execution_mode") or "").strip().lower() not in (
        _REAL_EXECUTION_MODES
    ):
        return False
    source = str(row.get("source") or "").strip().lower()
    return not any(marker in source for marker in ("paper", "shadow", "simulat"))


def _has_reconciled_fill_linkage(
    row: dict[str, Any],
    metadata: dict[str, Any],
) -> bool:
    required = (
        row.get("provider_name"),
        row.get("broker_order_id"),
        metadata.get("account_truth_import_run_id"),
        metadata.get("execution_reconciliation_run_id"),
    )
    return all(str(value or "").strip() for value in required)


def _effective_terminal_status(
    row: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> str:
    status = str(row.get("status") or "").strip().lower()
    terminal_statuses = {"filled", "rejected", "cancelled", "expired"}
    if status in terminal_statuses:
        return status
    if status == "reconciled":
        for transition in reversed(transitions):
            candidate = str(transition.get("to_status") or "").strip().lower()
            if candidate in terminal_statuses:
                return candidate
    return status


def _sanitized_account_truth_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "import_run_id": str(source.get("import_run_id") or ""),
        "created_at": str(source.get("created_at") or ""),
        "schema_version": str(source.get("schema_version") or ""),
        "score": int(source.get("score") or 0),
        "gate_status": str(source.get("gate_status") or "blocked"),
        "cash_status": str(source.get("cash_status") or "blocked"),
        "position_status": str(source.get("position_status") or "blocked"),
        "fee_status": str(source.get("fee_status") or "blocked"),
        "cost_basis_status": str(source.get("cost_basis_status") or "blocked"),
        "data_freshness_status": str(source.get("data_freshness_status") or "missing"),
        "unresolved_mismatch_count": int(source.get("unresolved_mismatch_count") or 0),
        "resolved_review_count": int(source.get("resolved_review_count") or 0),
        "blocking_reasons": [
            str(item) for item in source.get("blocking_reasons") or []
        ],
    }


def _nearest_snapshot(
    snapshots: list[tuple[datetime, dict[str, Any]]],
    *,
    target: datetime,
) -> tuple[datetime, dict[str, Any]] | None:
    if not snapshots:
        return None
    return min(snapshots, key=lambda item: abs((item[0] - target).total_seconds()))


def _nested_int(
    snapshot: tuple[datetime, dict[str, Any]] | None,
    field: str,
) -> int | None:
    if snapshot is None:
        return None
    account_truth = snapshot[1].get("account_truth")
    account_truth = account_truth if isinstance(account_truth, dict) else {}
    value = account_truth.get(field)
    return int(value) if value is not None else None


def _fact(
    *,
    kind: str,
    metrics: dict[str, Any],
    blockers: list[str],
    source_refs: list[str],
    assumptions: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    payload = {
        "schema_version": "karkinos.capital_scaling_evidence_fact.v1",
        "evidence_kind": kind,
        "status": "clear" if not blockers else "blocked",
        "metrics": metrics,
        "blockers": list(dict.fromkeys(blockers)),
        "source_refs": list(dict.fromkeys(ref for ref in source_refs if ref)),
        "assumptions": assumptions,
        "limitations": limitations,
        "does_not_issue_capital_authorization": True,
        "does_not_mutate_runtime_limits": True,
        "does_not_submit_broker_order": True,
    }
    return {**payload, "source_fingerprint": _fingerprint(payload)}


def _average(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _nearest_rank(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(float(percentile * Decimal(len(ordered)))))
    return ordered[rank - 1]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _decimal_string_or_none(value: Decimal | None) -> str | None:
    return _decimal_string(value) if value is not None else None


def _parse_datetime(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **_json_object(row.get("payload_json")),
    }


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


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
