"""Operating-sample evidence projection for capital-scaling review windows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
    reviewed_broker_soak_sequence_is_accepted,
)
from server.services.capital_scaling_evidence_contracts import MAX_SOURCE_ROWS, SHANGHAI
from server.services.capital_scaling_evidence_values import (
    decimal_string_or_none,
    decimal_value,
    effective_terminal_status,
    fact,
    has_reconciled_fill_linkage,
    is_real_execution_row,
    json_object,
    nearest_rank,
    parse_datetime,
)


class CapitalScalingOperatingSampleFactMixin:
    """Project persisted operating outcomes without smoothing failure evidence."""

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
        healthy_days = self._healthy_soak_days(
            start=start,
            end=end,
            blockers=blockers,
            source_refs=source_refs,
        )
        sample = self._real_order_sample(
            start=start,
            end=end,
            healthy_days=healthy_days,
            blockers=blockers,
            source_refs=source_refs,
        )
        reconciliation = self._reconciliation_sample(
            start=start,
            end=end,
            order_ids=sample["order_ids"],
            terminal_source_times=sample["terminal_source_times"],
            blockers=blockers,
            source_refs=source_refs,
        )
        paper = self._paper_shadow_sample(
            start=start,
            end=end,
            has_real_orders=bool(sample["orders"]),
            blockers=blockers,
            source_refs=source_refs,
        )
        drawdown, drawdown_blockers, drawdown_refs = self._unitized_drawdown(
            start=start,
            end=end,
        )
        blockers.extend(drawdown_blockers)
        source_refs.extend(drawdown_refs)
        return fact(
            kind="operating_sample",
            metrics={
                "reviewed_trading_days": len(healthy_days),
                "order_count": len(sample["orders"]),
                "filled_order_count": sample["filled_order_count"],
                "rejected_order_count": sample["rejected_order_count"],
                "partial_fill_count": sample["partial_fill_count"],
                "cancelled_or_expired_order_count": sample[
                    "cancelled_or_expired_count"
                ],
                "nonterminal_order_count": sample["nonterminal_count"],
                "unresolved_reconciliation_count": reconciliation["unresolved_count"],
                "p95_reconciliation_latency_minutes": decimal_string_or_none(
                    nearest_rank(reconciliation["latencies"], Decimal("0.95"))
                ),
                "reconciliation_latency_coverage_count": len(
                    reconciliation["latencies"]
                ),
                "paper_shadow_sample_count": paper["sample_count"],
                "paper_shadow_divergence_count": paper["divergence_count"],
                "max_drawdown_pct": decimal_string_or_none(drawdown),
                "incomplete_real_fill_count": sample["incomplete_real_fill_count"],
                "sample_order_ids": sorted(sample["order_ids"]),
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
                "Runtime-session and exact-batch binding is evaluated by the separate execution-scope fact in the same window.",
                "Paper/shadow divergence is counted from persisted paper/shadow order facts.",
                "Cash flows between portfolio snapshots are unitized at the next persisted equity point because no valuation exists at the exact flow time.",
                "Cancelled and expired orders are disclosed separately and are not silently relabeled as broker rejections.",
            ],
        )

    def _healthy_soak_days(
        self,
        *,
        start: datetime,
        end: datetime,
        blockers: list[str],
        source_refs: list[str],
    ) -> set[str]:
        soak_rows = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=MAX_SOURCE_ROWS,
        )
        if len(soak_rows) >= MAX_SOURCE_ROWS:
            blockers.append("broker_soak_scan_truncated")
        healthy_days: set[str] = set()
        unaccepted_sequence_count = 0
        for row in soak_rows:
            payload = json_object(row.get("payload_json"))
            observed_at = parse_datetime(
                str(payload.get("observed_at") or row.get("timestamp") or "")
            )
            if observed_at is None or observed_at < start or observed_at > end:
                continue
            trading_day = str(payload.get("trading_day") or "")
            if payload.get("qualifies_for_healthy_soak_day") is True and trading_day:
                if reviewed_broker_soak_sequence_is_accepted(payload):
                    healthy_days.add(trading_day)
                    source_refs.append(f"broker_soak_event:{row.get('id')}")
                else:
                    unaccepted_sequence_count += 1
        if unaccepted_sequence_count:
            blockers.append("broker_soak_source_sequence_not_accepted")
        if not healthy_days:
            blockers.append("healthy_broker_soak_trading_days_missing")
        return healthy_days

    def _real_order_sample(
        self,
        *,
        start: datetime,
        end: datetime,
        healthy_days: set[str],
        blockers: list[str],
        source_refs: list[str],
    ) -> dict[str, Any]:
        fill_rows = self._db.list_fills_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(fill_rows) >= MAX_SOURCE_ROWS:
            blockers.append("fill_scan_truncated")
        real_fills: list[tuple[dict[str, Any], datetime, dict[str, Any]]] = []
        incomplete_real_fill_count = 0
        for row in fill_rows:
            occurred_at = parse_datetime(str(row.get("timestamp") or ""))
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            if not is_real_execution_row(row):
                continue
            metadata = json_object(row.get("metadata_json"))
            if not has_reconciled_fill_linkage(row, metadata):
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
            payload = json_object(row.get("payload_json"))
            if str(payload.get("execution_mode") or "").lower() == "paper_shadow":
                continue
            created_at = parse_datetime(str(row.get("created_at") or ""))
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
        outcomes = self._order_outcomes(
            orders=orders,
            fills_by_order=fills_by_order,
            healthy_days=healthy_days,
            blockers=blockers,
            source_refs=source_refs,
        )
        return {
            "orders": orders,
            "order_ids": order_ids,
            "incomplete_real_fill_count": incomplete_real_fill_count,
            **outcomes,
        }

    def _order_outcomes(
        self,
        *,
        orders: list[tuple[dict[str, Any], datetime, dict[str, Any]]],
        fills_by_order: dict[
            str, list[tuple[dict[str, Any], datetime, dict[str, Any]]]
        ],
        healthy_days: set[str],
        blockers: list[str],
        source_refs: list[str],
    ) -> dict[str, Any]:
        counts = {
            "filled_order_count": 0,
            "rejected_order_count": 0,
            "partial_fill_count": 0,
            "cancelled_or_expired_count": 0,
            "nonterminal_count": 0,
        }
        terminal_source_times: dict[str, datetime] = {}
        for row, created_at, _ in orders:
            order_id = str(row.get("order_id") or "")
            transitions = self._db.list_oms_transitions_sync(order_id)
            for transition in transitions:
                if transition.get("id") is not None:
                    source_refs.append(f"oms_transition:{transition.get('id')}")
            effective_status = effective_terminal_status(row, transitions)
            order_quantity = decimal_value(row.get("quantity")) or Decimal("0")
            order_fills = fills_by_order.get(order_id, [])
            filled_quantity = sum(
                (
                    abs(decimal_value(fill.get("fill_quantity")) or Decimal("0"))
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
                counts["partial_fill_count"] += 1
            if effective_status == "filled" and filled_quantity >= order_quantity > 0:
                counts["filled_order_count"] += 1
            elif effective_status == "rejected":
                counts["rejected_order_count"] += 1
            elif effective_status in {"cancelled", "expired"}:
                counts["cancelled_or_expired_count"] += 1
            else:
                counts["nonterminal_count"] += 1
            source_times = [created_at]
            source_times.extend(fill_time for _, fill_time, _ in order_fills)
            source_times.extend(
                timestamp
                for transition in transitions
                if (
                    timestamp := parse_datetime(
                        str(transition.get("transitioned_at") or "")
                    )
                )
                is not None
            )
            terminal_source_times[order_id] = max(source_times)
            sample_day = max(source_times).astimezone(SHANGHAI).date().isoformat()
            if sample_day not in healthy_days:
                blockers.append("order_day_without_healthy_broker_soak")
        if counts["nonterminal_count"]:
            blockers.append("nonterminal_real_order_evidence_present")
        return {**counts, "terminal_source_times": terminal_source_times}

    def _reconciliation_sample(
        self,
        *,
        start: datetime,
        end: datetime,
        order_ids: set[str],
        terminal_source_times: dict[str, datetime],
        blockers: list[str],
        source_refs: list[str],
    ) -> dict[str, Any]:
        rows = self._db.list_execution_reconciliation_runs_sync(
            limit=MAX_SOURCE_ROWS,
            offset=0,
        )
        if len(rows) >= MAX_SOURCE_ROWS:
            blockers.append("execution_reconciliation_scan_truncated")
        runs: list[tuple[datetime, dict[str, Any], list[dict[str, Any]]]] = []
        for run in rows:
            try:
                run_day = datetime.fromisoformat(str(run.get("run_date") or "")).date()
            except ValueError:
                continue
            if run_day < start.date() or run_day > end.date():
                continue
            updated_at = parse_datetime(str(run.get("updated_at") or ""))
            if updated_at is None:
                blockers.append("execution_reconciliation_timestamp_invalid")
                continue
            items = self._db.list_execution_reconciliation_items_sync(
                str(run.get("run_id") or "")
            )
            runs.append((updated_at, run, items))
            source_refs.append(f"execution_reconciliation:{run.get('run_id')}")
        runs.sort(key=lambda item: item[0])
        unresolved_count: int | None = None
        latencies: list[Decimal] = []
        if not runs:
            blockers.append("execution_reconciliation_sample_missing")
        else:
            _, latest_run, latest_items = runs[-1]
            unresolved_count = int(latest_run.get("open_item_count") or 0)
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
                matched_at = self._first_clear_reconciliation(
                    order_id=order_id,
                    source_time=source_time,
                    runs=runs,
                )
                if matched_at is None:
                    blockers.append("clear_reconciliation_latency_coverage_missing")
                    continue
                latency = Decimal(str((matched_at - source_time).total_seconds())) / (
                    Decimal("60")
                )
                latencies.append(max(latency, Decimal("0")))
        if order_ids and not latencies:
            blockers.append("reconciliation_latency_sample_missing")
        return {"unresolved_count": unresolved_count, "latencies": latencies}

    @staticmethod
    def _first_clear_reconciliation(
        *,
        order_id: str,
        source_time: datetime,
        runs: list[tuple[datetime, dict[str, Any], list[dict[str, Any]]]],
    ) -> datetime | None:
        for run_at, _, items in runs:
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
            if item is not None and str(item.get("suggested_action") or "") == (
                "no_action"
            ):
                return run_at
        return None

    def _paper_shadow_sample(
        self,
        *,
        start: datetime,
        end: datetime,
        has_real_orders: bool,
        blockers: list[str],
        source_refs: list[str],
    ) -> dict[str, int]:
        rows = self._db.list_orders_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(rows) >= MAX_SOURCE_ROWS:
            blockers.append("paper_shadow_order_scan_truncated")
        sample_count = 0
        divergence_count = 0
        for row in rows:
            if str(row.get("execution_mode") or "") != "paper_shadow":
                continue
            occurred_at = parse_datetime(str(row.get("timestamp") or ""))
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            payload = json_object(row.get("payload_json"))
            sample_count += 1
            if str(payload.get("divergence_status") or "") not in {
                "within_expectations",
                "not_required",
            }:
                divergence_count += 1
            source_refs.append(f"paper_shadow_order:{row.get('order_id')}")
        if has_real_orders and not sample_count:
            blockers.append("paper_shadow_divergence_sample_missing")
        return {"sample_count": sample_count, "divergence_count": divergence_count}

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
            payload = json_object(row.get("payload_json"))
            observed_at = parse_datetime(
                str(payload.get("timestamp") or row.get("timestamp") or "")
            )
            equity = decimal_value(payload.get("total_equity"))
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
        flows = self._drawdown_cash_flows(points=points, blockers=blockers)
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

    def _drawdown_cash_flows(
        self,
        *,
        points: list[tuple[datetime, Decimal, str]],
        blockers: list[str],
    ) -> list[tuple[datetime, Decimal, str]]:
        rows = self._db.get_cash_flows_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(rows) >= MAX_SOURCE_ROWS:
            blockers.append("cash_flow_scan_truncated")
        flows: list[tuple[datetime, Decimal, str]] = []
        for row in rows:
            occurred_at = parse_datetime(str(row.get("timestamp") or ""))
            amount = decimal_value(row.get("amount"))
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
        return flows
