"""Persist deterministic scaling evidence windows from existing local facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from server.services.capital_scaling_evidence_contracts import (
    CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE,
    CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE,
    CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_SCHEMA_VERSION,
    CAPITAL_SCALING_EVIDENCE_SOURCE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION,
    DEFAULT_BOUNDARY_GAP_HOURS,
    MAX_ACCOUNT_TRUTH_CAPTURE_LAG_SECONDS,
    MAX_SOURCE_ROWS,
)
from server.services.capital_scaling_evidence_values import aware_utc as _aware_utc
from server.services.capital_scaling_evidence_values import (
    event_response as _event_response,
)
from server.services.capital_scaling_evidence_values import fingerprint as _fingerprint
from server.services.capital_scaling_evidence_values import json_object as _json_object
from server.services.capital_scaling_evidence_values import (
    parse_datetime as _parse_datetime,
)
from server.services.capital_scaling_evidence_values import (
    sanitized_account_truth_source as _sanitized_account_truth_source,
)
from server.services.capital_scaling_evidence_values import (
    validated_window as _validated_window,
)
from server.services.capital_scaling_execution_facts import (
    CapitalScalingExecutionFactsMixin,
)
from server.services.capital_scaling_financial_facts import (
    CapitalScalingFinancialFactsMixin,
)


class CapitalScalingEvidenceWindowService(
    CapitalScalingFinancialFactsMixin,
    CapitalScalingExecutionFactsMixin,
):
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
            "schema_version": "karkinos.capital_scaling_evidence_status.v2",
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
                "execution_scope",
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
                "Every operating-sample order must bind one exact clear broker batch or one persisted controlled-session admission.",
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
        execution_scope = self._execution_scope_fact(
            start=start,
            end=end,
            operating_sample=operating_sample,
        )
        facts = {
            "account_truth": account_truth,
            "after_cost": after_cost,
            "incident": incident,
            "capacity": capacity,
            "operating_sample": operating_sample,
            "execution_scope": execution_scope,
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
