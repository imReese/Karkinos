"""Capacity, operating, and execution facts for scaling evidence."""

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
from server.services.capital_scaling_evidence_contracts import (
    MAX_RUNTIME_ADMISSION_ROWS,
    MAX_SOURCE_ROWS,
)
from server.services.capital_scaling_evidence_contracts import (
    REAL_EXECUTION_MODES as _REAL_EXECUTION_MODES,
)
from server.services.capital_scaling_evidence_contracts import SHANGHAI as _SHANGHAI
from server.services.capital_scaling_evidence_values import average as _average
from server.services.capital_scaling_evidence_values import (
    decimal_string_or_none as _decimal_string_or_none,
)
from server.services.capital_scaling_evidence_values import decimal_value as _decimal
from server.services.capital_scaling_evidence_values import (
    effective_terminal_status as _effective_terminal_status,
)
from server.services.capital_scaling_evidence_values import fact as _fact
from server.services.capital_scaling_evidence_values import (
    has_reconciled_fill_linkage as _has_reconciled_fill_linkage,
)
from server.services.capital_scaling_evidence_values import (
    is_real_execution_row as _is_real_execution_row,
)
from server.services.capital_scaling_evidence_values import json_object as _json_object
from server.services.capital_scaling_evidence_values import (
    nearest_rank as _nearest_rank,
)
from server.services.capital_scaling_evidence_values import (
    parse_datetime as _parse_datetime,
)
from server.services.controlled_session_runtime_rate_limiter import (
    CONTROLLED_SESSION_RATE_ADMISSION_SCHEMA_VERSION,
)
from server.services.execution_batch_reconciliation import (
    EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
    ExecutionBatchReconciliationService,
)


class CapitalScalingExecutionFactsMixin:
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
        unaccepted_sequence_count = 0
        for row in soak_rows:
            payload = _json_object(row.get("payload_json"))
            observed_at = _parse_datetime(
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
                "sample_order_ids": sorted(order_ids),
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

    def _execution_scope_fact(
        self,
        *,
        start: datetime,
        end: datetime,
        operating_sample: dict[str, Any],
    ) -> dict[str, Any]:
        blockers: list[str] = []
        source_refs: list[str] = []
        metrics = operating_sample.get("metrics")
        metrics = metrics if isinstance(metrics, dict) else {}
        sample_order_ids = sorted(
            {
                str(item).strip()
                for item in metrics.get("sample_order_ids") or []
                if str(item).strip()
            }
        )
        sample_order_set = set(sample_order_ids)
        if operating_sample.get("status") != "clear":
            blockers.append("operating_sample_not_clear")
        if not sample_order_ids:
            blockers.append("execution_scope_order_sample_missing")

        admissions_by_order: dict[str, list[str]] = {}
        valid_session_ids: set[str] = set()
        invalid_admission_count = 0
        orphan_admission_count = 0
        admission_rows = self._db.list_controlled_session_rate_admissions_sync(
            limit=MAX_RUNTIME_ADMISSION_ROWS
        )
        if len(admission_rows) >= MAX_RUNTIME_ADMISSION_ROWS:
            blockers.append("runtime_admission_scan_truncated")
        for row in admission_rows:
            order_id = str(row.get("order_id") or "")
            admitted_at = _parse_datetime(str(row.get("admitted_at") or ""))
            if admitted_at is None:
                blockers.append("runtime_admission_timestamp_invalid")
                invalid_admission_count += 1
                continue
            in_window = start <= admitted_at <= end
            if order_id not in sample_order_set and not in_window:
                continue
            admission_id = str(row.get("admission_id") or "")
            source_refs.append(f"controlled_session_rate_admission:{admission_id}")
            if order_id not in sample_order_set:
                orphan_admission_count += 1
                blockers.append(
                    f"runtime_admission_order_missing_from_sample:{order_id}"
                )
                continue

            payload = _json_object(row.get("payload_json"))
            admission_blockers: list[str] = []
            if str(row.get("status") or "") != "admitted":
                admission_blockers.append("status_not_admitted")
            if payload.get("schema_version") != (
                CONTROLLED_SESSION_RATE_ADMISSION_SCHEMA_VERSION
            ):
                admission_blockers.append("schema_invalid")
            for field in (
                "admission_id",
                "session_id",
                "session_fingerprint",
                "reservation_id",
                "authorization_id",
                "account_alias",
                "strategy_id",
                "order_id",
                "request_id",
            ):
                if str(payload.get(field) or "") != str(row.get(field) or ""):
                    admission_blockers.append(f"payload_mismatch:{field}")
            if payload.get("runtime_admission_granted") is not True:
                admission_blockers.append("runtime_admission_not_granted")
            if payload.get("runtime_live_gates_verified") is not True:
                admission_blockers.append("runtime_live_gates_not_verified")
            if payload.get("authorizes_broker_submission") is not False:
                admission_blockers.append("broker_submission_boundary_invalid")

            session_id = str(row.get("session_id") or "")
            session = self._db.get_controlled_session_runtime_session_sync(session_id)
            if not session:
                admission_blockers.append("runtime_session_missing")
            else:
                for field in (
                    "session_fingerprint",
                    "reservation_id",
                    "authorization_id",
                    "account_alias",
                    "strategy_id",
                ):
                    if str(session.get(field) or "") != str(row.get(field) or ""):
                        admission_blockers.append(f"runtime_session_mismatch:{field}")
                admitted_at_epoch_ms = int(row.get("admitted_at_epoch_ms") or -1)
                try:
                    effective_at_epoch_ms = int(session["effective_at_epoch_ms"])
                    expires_at_epoch_ms = int(session["expires_at_epoch_ms"])
                except (KeyError, TypeError, ValueError):
                    admission_blockers.append("runtime_session_window_invalid")
                else:
                    if not (
                        effective_at_epoch_ms
                        <= admitted_at_epoch_ms
                        < expires_at_epoch_ms
                    ):
                        admission_blockers.append(
                            "runtime_admission_outside_session_window"
                        )
            if admission_blockers:
                invalid_admission_count += 1
                blockers.extend(
                    f"runtime_admission_invalid:{order_id}:{reason}"
                    for reason in admission_blockers
                )
                continue
            admissions_by_order.setdefault(order_id, []).append(admission_id)
            valid_session_ids.add(session_id)
            source_refs.append(f"controlled_session_runtime_session:{session_id}")

        batches_by_order: dict[str, list[str]] = {}
        valid_batch_ids: set[str] = set()
        invalid_batch_count = 0
        batch_rows = self._db.list_events_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            limit=MAX_SOURCE_ROWS,
        )
        if len(batch_rows) >= MAX_SOURCE_ROWS:
            blockers.append("execution_batch_scan_truncated")
        batch_service = ExecutionBatchReconciliationService(db=self._db)
        for row in batch_rows:
            payload = _json_object(row.get("payload_json"))
            if str(payload.get("record_status") or "") != "recorded_clear":
                continue
            batch_order_ids = sorted(
                {
                    str(item).strip()
                    for item in payload.get("order_ids") or []
                    if str(item).strip()
                }
            )
            batch_order_set = set(batch_order_ids)
            if not batch_order_set.intersection(sample_order_set):
                continue
            fingerprint = str(
                payload.get("batch_reconciliation_fingerprint")
                or row.get("entity_id")
                or ""
            )
            source_refs.append(f"execution_batch_reconciliation:{fingerprint}")
            if not batch_order_set.issubset(sample_order_set):
                invalid_batch_count += 1
                blockers.append(f"execution_batch_crosses_review_sample:{fingerprint}")
                continue
            resolved = batch_service.resolve_recorded(fingerprint)
            if resolved.get("status") != "pass":
                invalid_batch_count += 1
                blockers.append(f"execution_batch_not_current_clear:{fingerprint}")
                continue
            valid_batch_ids.add(fingerprint)
            for order_id in batch_order_ids:
                batches_by_order.setdefault(order_id, []).append(fingerprint)

        unbound_order_ids: list[str] = []
        for order_id in sample_order_ids:
            admission_ids = sorted(set(admissions_by_order.get(order_id) or []))
            batch_ids = sorted(set(batches_by_order.get(order_id) or []))
            if len(admission_ids) > 1:
                blockers.append(f"runtime_admission_order_scope_ambiguous:{order_id}")
            if len(batch_ids) > 1:
                blockers.append(f"execution_batch_order_scope_ambiguous:{order_id}")
            if not admission_ids and not batch_ids:
                unbound_order_ids.append(order_id)
                blockers.append(f"execution_scope_order_unbound:{order_id}")

        runtime_bound = {
            order_id for order_id, rows in admissions_by_order.items() if rows
        }
        batch_bound = {order_id for order_id, rows in batches_by_order.items() if rows}
        return _fact(
            kind="execution_scope",
            metrics={
                "sampled_order_count": len(sample_order_ids),
                "runtime_session_bound_order_count": len(runtime_bound),
                "exact_batch_bound_order_count": len(batch_bound),
                "dual_bound_order_count": len(runtime_bound.intersection(batch_bound)),
                "unbound_order_count": len(unbound_order_ids),
                "runtime_session_count": len(valid_session_ids),
                "exact_batch_count": len(valid_batch_ids),
                "invalid_runtime_admission_count": invalid_admission_count,
                "orphan_runtime_admission_count": orphan_admission_count,
                "invalid_exact_batch_count": invalid_batch_count,
            },
            blockers=blockers,
            source_refs=source_refs,
            assumptions=[
                "Every sampled real order must bind either one persisted controlled-session admission or one exact current clear batch-reconciliation record.",
                "Historical runtime sessions may be expired or revoked now, but their identity and admission-time window must still match immutable admission evidence.",
                "A batch used for scaling evidence must be wholly contained in the reviewed order sample.",
            ],
            limitations=[
                "A clear execution-scope fact is evidence provenance only and does not issue, renew, resume, or widen runtime authority.",
                "Runtime admissions remain internal and do not authorize broker submission.",
                "Rejected or blocked batch attempts cannot satisfy an order binding.",
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
