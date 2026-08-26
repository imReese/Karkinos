"""Runtime-session and exact-batch provenance for capital-scaling evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from server.services.capital_scaling_evidence_contracts import (
    MAX_RUNTIME_ADMISSION_ROWS,
    MAX_SOURCE_ROWS,
)
from server.services.capital_scaling_evidence_values import (
    fact,
    json_object,
    parse_datetime,
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


class CapitalScalingExecutionScopeFactMixin:
    """Verify persisted runtime and batch bindings without issuing authority."""

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
        admissions = self._runtime_admissions(
            start=start,
            end=end,
            sample_order_set=sample_order_set,
            blockers=blockers,
            source_refs=source_refs,
        )
        batches = self._exact_batches(
            sample_order_set=sample_order_set,
            blockers=blockers,
            source_refs=source_refs,
        )
        unbound_order_ids: list[str] = []
        for order_id in sample_order_ids:
            admission_ids = sorted(set(admissions["by_order"].get(order_id) or []))
            batch_ids = sorted(set(batches["by_order"].get(order_id) or []))
            if len(admission_ids) > 1:
                blockers.append(f"runtime_admission_order_scope_ambiguous:{order_id}")
            if len(batch_ids) > 1:
                blockers.append(f"execution_batch_order_scope_ambiguous:{order_id}")
            if not admission_ids and not batch_ids:
                unbound_order_ids.append(order_id)
                blockers.append(f"execution_scope_order_unbound:{order_id}")
        runtime_bound = {
            order_id for order_id, rows in admissions["by_order"].items() if rows
        }
        batch_bound = {
            order_id for order_id, rows in batches["by_order"].items() if rows
        }
        return fact(
            kind="execution_scope",
            metrics={
                "sampled_order_count": len(sample_order_ids),
                "runtime_session_bound_order_count": len(runtime_bound),
                "exact_batch_bound_order_count": len(batch_bound),
                "dual_bound_order_count": len(runtime_bound.intersection(batch_bound)),
                "unbound_order_count": len(unbound_order_ids),
                "runtime_session_count": len(admissions["session_ids"]),
                "exact_batch_count": len(batches["batch_ids"]),
                "invalid_runtime_admission_count": admissions["invalid_count"],
                "orphan_runtime_admission_count": admissions["orphan_count"],
                "invalid_exact_batch_count": batches["invalid_count"],
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

    def _runtime_admissions(
        self,
        *,
        start: datetime,
        end: datetime,
        sample_order_set: set[str],
        blockers: list[str],
        source_refs: list[str],
    ) -> dict[str, Any]:
        by_order: dict[str, list[str]] = {}
        valid_session_ids: set[str] = set()
        invalid_count = 0
        orphan_count = 0
        rows = self._db.list_controlled_session_rate_admissions_sync(
            limit=MAX_RUNTIME_ADMISSION_ROWS
        )
        if len(rows) >= MAX_RUNTIME_ADMISSION_ROWS:
            blockers.append("runtime_admission_scan_truncated")
        for row in rows:
            order_id = str(row.get("order_id") or "")
            admitted_at = parse_datetime(str(row.get("admitted_at") or ""))
            if admitted_at is None:
                blockers.append("runtime_admission_timestamp_invalid")
                invalid_count += 1
                continue
            in_window = start <= admitted_at <= end
            if order_id not in sample_order_set and not in_window:
                continue
            admission_id = str(row.get("admission_id") or "")
            source_refs.append(f"controlled_session_rate_admission:{admission_id}")
            if order_id not in sample_order_set:
                orphan_count += 1
                blockers.append(
                    f"runtime_admission_order_missing_from_sample:{order_id}"
                )
                continue
            admission_blockers, session_id = self._validate_runtime_admission(row)
            if admission_blockers:
                invalid_count += 1
                blockers.extend(
                    f"runtime_admission_invalid:{order_id}:{reason}"
                    for reason in admission_blockers
                )
                continue
            by_order.setdefault(order_id, []).append(admission_id)
            valid_session_ids.add(session_id)
            source_refs.append(f"controlled_session_runtime_session:{session_id}")
        return {
            "by_order": by_order,
            "session_ids": valid_session_ids,
            "invalid_count": invalid_count,
            "orphan_count": orphan_count,
        }

    def _validate_runtime_admission(
        self,
        row: dict[str, Any],
    ) -> tuple[list[str], str]:
        payload = json_object(row.get("payload_json"))
        blockers: list[str] = []
        if str(row.get("status") or "") != "admitted":
            blockers.append("status_not_admitted")
        if payload.get("schema_version") != (
            CONTROLLED_SESSION_RATE_ADMISSION_SCHEMA_VERSION
        ):
            blockers.append("schema_invalid")
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
                blockers.append(f"payload_mismatch:{field}")
        if payload.get("runtime_admission_granted") is not True:
            blockers.append("runtime_admission_not_granted")
        if payload.get("runtime_live_gates_verified") is not True:
            blockers.append("runtime_live_gates_not_verified")
        if payload.get("authorizes_broker_submission") is not False:
            blockers.append("broker_submission_boundary_invalid")
        session_id = str(row.get("session_id") or "")
        session = self._db.get_controlled_session_runtime_session_sync(session_id)
        if not session:
            blockers.append("runtime_session_missing")
            return blockers, session_id
        for field in (
            "session_fingerprint",
            "reservation_id",
            "authorization_id",
            "account_alias",
            "strategy_id",
        ):
            if str(session.get(field) or "") != str(row.get(field) or ""):
                blockers.append(f"runtime_session_mismatch:{field}")
        admitted_at_epoch_ms = int(row.get("admitted_at_epoch_ms") or -1)
        try:
            effective_at_epoch_ms = int(session["effective_at_epoch_ms"])
            expires_at_epoch_ms = int(session["expires_at_epoch_ms"])
        except (KeyError, TypeError, ValueError):
            blockers.append("runtime_session_window_invalid")
        else:
            if not (
                effective_at_epoch_ms <= admitted_at_epoch_ms < expires_at_epoch_ms
            ):
                blockers.append("runtime_admission_outside_session_window")
        return blockers, session_id

    def _exact_batches(
        self,
        *,
        sample_order_set: set[str],
        blockers: list[str],
        source_refs: list[str],
    ) -> dict[str, Any]:
        by_order: dict[str, list[str]] = {}
        valid_batch_ids: set[str] = set()
        invalid_count = 0
        rows = self._db.list_events_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            limit=MAX_SOURCE_ROWS,
        )
        if len(rows) >= MAX_SOURCE_ROWS:
            blockers.append("execution_batch_scan_truncated")
        service = ExecutionBatchReconciliationService(db=self._db)
        for row in rows:
            payload = json_object(row.get("payload_json"))
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
                invalid_count += 1
                blockers.append(f"execution_batch_crosses_review_sample:{fingerprint}")
                continue
            resolved = service.resolve_recorded(fingerprint)
            if resolved.get("status") != "pass":
                invalid_count += 1
                blockers.append(f"execution_batch_not_current_clear:{fingerprint}")
                continue
            valid_batch_ids.add(fingerprint)
            for order_id in batch_order_ids:
                by_order.setdefault(order_id, []).append(fingerprint)
        return {
            "by_order": by_order,
            "batch_ids": valid_batch_ids,
            "invalid_count": invalid_count,
        }
