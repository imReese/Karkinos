"""Account, return, and incident facts for capital-scaling evidence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
)
from server.services.capital_scaling_evidence_contracts import (
    CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE,
    CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE,
    CAPITAL_SCALING_EVIDENCE_SOURCE,
)
from server.services.capital_scaling_evidence_contracts import (
    DISCONNECT_MARKERS as _DISCONNECT_MARKERS,
)
from server.services.capital_scaling_evidence_contracts import MAX_SOURCE_ROWS
from server.services.capital_scaling_evidence_contracts import (
    POLICY_VIOLATION_GATEWAY_EVENTS as _POLICY_VIOLATION_GATEWAY_EVENTS,
)
from server.services.capital_scaling_evidence_values import (
    decimal_string as _decimal_string,
)
from server.services.capital_scaling_evidence_values import (
    decimal_string_or_none as _decimal_string_or_none,
)
from server.services.capital_scaling_evidence_values import decimal_value as _decimal
from server.services.capital_scaling_evidence_values import fact as _fact
from server.services.capital_scaling_evidence_values import json_object as _json_object
from server.services.capital_scaling_evidence_values import (
    nearest_snapshot as _nearest_snapshot,
)
from server.services.capital_scaling_evidence_values import nested_int as _nested_int
from server.services.capital_scaling_evidence_values import (
    parse_datetime as _parse_datetime,
)


class CapitalScalingFinancialFactsMixin:
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
