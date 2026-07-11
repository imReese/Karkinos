"""Resolve capital-scaling evidence references to persisted source facts."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
)
from server.services.capital_scaling_evidence_window import (
    CAPITAL_SCALING_EVIDENCE_SOURCE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION,
)
from server.services.capital_scaling_review import CapitalScalingEvidence

CAPITAL_SCALING_EVIDENCE_RESOLUTION_SCHEMA_VERSION = (
    "karkinos.capital_scaling_evidence_resolution.v1"
)

REQUIRED_CAPITAL_SCALING_EVIDENCE_KINDS = (
    "account_truth",
    "broker_soak",
    "execution_reconciliation",
    "paper_shadow",
    "after_cost",
    "risk",
    "incident",
    "capacity",
    "operating_sample",
)

RESOLVABLE_CAPITAL_SCALING_EVIDENCE_KINDS = (
    "account_truth",
    "broker_soak",
    "execution_reconciliation",
    "paper_shadow",
    "after_cost",
    "risk",
    "incident",
    "capacity",
    "operating_sample",
)

UNSUPPORTED_CAPITAL_SCALING_EVIDENCE_KINDS = tuple(
    kind
    for kind in REQUIRED_CAPITAL_SCALING_EVIDENCE_KINDS
    if kind not in RESOLVABLE_CAPITAL_SCALING_EVIDENCE_KINDS
)


class CapitalScalingEvidenceResolver:
    """Resolve sanitized evidence references without changing trading state."""

    def __init__(self, *, db: Any) -> None:
        self._db = db

    def resolve(self, *, evidence: CapitalScalingEvidence) -> dict[str, Any]:
        refs = tuple(
            dict.fromkeys(str(item).strip() for item in evidence.evidence_refs)
        )
        refs = tuple(item for item in refs if item)
        rows = [self._resolve_ref(ref=ref, evidence=evidence) for ref in refs]
        resolved_clear_kinds = {
            str(row.get("evidence_kind") or "")
            for row in rows
            if row.get("resolution_status") == "resolved_clear"
        }
        blockers: list[str] = []
        for row in rows:
            blockers.extend(str(item) for item in row.get("blockers") or [])
        for kind in REQUIRED_CAPITAL_SCALING_EVIDENCE_KINDS:
            if kind not in resolved_clear_kinds:
                blockers.append(f"persisted_evidence_kind_not_clear:{kind}")
        blockers = list(dict.fromkeys(blockers))
        resolution_payload = {
            "schema_version": CAPITAL_SCALING_EVIDENCE_RESOLUTION_SCHEMA_VERSION,
            "required_evidence_kinds": list(REQUIRED_CAPITAL_SCALING_EVIDENCE_KINDS),
            "resolvable_evidence_kinds": list(
                RESOLVABLE_CAPITAL_SCALING_EVIDENCE_KINDS
            ),
            "unsupported_evidence_kinds": list(
                UNSUPPORTED_CAPITAL_SCALING_EVIDENCE_KINDS
            ),
            "resolved_clear_kinds": sorted(resolved_clear_kinds),
            "reference_count": len(rows),
            "resolved_clear_count": sum(
                row.get("resolution_status") == "resolved_clear" for row in rows
            ),
            "references": rows,
            "blockers": blockers,
            "all_required_sources_resolved_clear": not blockers,
            "does_not_issue_capital_authorization": True,
            "does_not_mutate_runtime_limits": True,
            "does_not_submit_broker_order": True,
        }
        resolution_fingerprint = _fingerprint(resolution_payload)
        return {
            **resolution_payload,
            "resolution_status": (
                "resolved_clear" if not blockers else "blocked_unresolved_sources"
            ),
            "resolution_fingerprint": resolution_fingerprint,
        }

    def _resolve_ref(
        self,
        *,
        ref: str,
        evidence: CapitalScalingEvidence,
    ) -> dict[str, Any]:
        kind, separator, identifier = ref.partition(":")
        kind = kind.strip()
        identifier = identifier.strip()
        base = {
            "evidence_ref": ref,
            "evidence_kind": kind,
            "source_identifier": identifier,
            "source_recorded_at": None,
            "source_fingerprint": None,
        }
        if not separator or not kind or not identifier:
            return {
                **base,
                "resolution_status": "invalid_reference",
                "blockers": [f"persisted_evidence_ref_invalid:{ref}"],
            }
        if kind not in REQUIRED_CAPITAL_SCALING_EVIDENCE_KINDS:
            return {
                **base,
                "resolution_status": "unsupported_reference_kind",
                "blockers": [f"persisted_evidence_kind_unknown:{kind}"],
            }
        if kind in UNSUPPORTED_CAPITAL_SCALING_EVIDENCE_KINDS:
            return {
                **base,
                "resolution_status": "unsupported_source_kind",
                "blockers": [f"persisted_evidence_source_unsupported:{kind}"],
            }
        if kind in {
            "account_truth",
            "after_cost",
            "incident",
            "capacity",
            "operating_sample",
        }:
            return self._resolve_evidence_window_fact(
                base=base,
                identifier=identifier,
                evidence=evidence,
            )
        if kind == "broker_soak":
            return self._resolve_broker_soak(
                base=base,
                identifier=identifier,
                evidence=evidence,
            )
        if kind == "execution_reconciliation":
            return self._resolve_execution_reconciliation(
                base=base,
                identifier=identifier,
                evidence=evidence,
            )
        if kind == "paper_shadow":
            return self._resolve_paper_shadow(
                base=base,
                identifier=identifier,
                evidence=evidence,
            )
        return self._resolve_risk(
            base=base,
            identifier=identifier,
            evidence=evidence,
        )

    def _resolve_evidence_window_fact(
        self,
        *,
        base: dict[str, Any],
        identifier: str,
        evidence: CapitalScalingEvidence,
    ) -> dict[str, Any]:
        rows = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
            entity_id=identifier,
            source=CAPITAL_SCALING_EVIDENCE_SOURCE,
            limit=1,
        )
        if not rows:
            return _not_found(base)
        row = rows[0]
        payload = _json_object(row.get("payload_json"))
        kind = str(base["evidence_kind"])
        facts = payload.get("facts")
        facts = facts if isinstance(facts, dict) else {}
        fact = facts.get(kind)
        fact = fact if isinstance(fact, dict) else {}
        blockers: list[str] = []
        if (
            payload.get("schema_version")
            != CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION
        ):
            blockers.append(f"persisted_evidence_window_schema_invalid:{kind}")
        if str(payload.get("window_id") or "") != identifier:
            blockers.append(f"persisted_evidence_window_id_mismatch:{kind}")
        if not _same_timestamp(
            payload.get("review_window_start"), evidence.review_window_start
        ) or not _same_timestamp(
            payload.get("review_window_end"), evidence.review_window_end
        ):
            blockers.append(f"persisted_evidence_window_mismatch:{kind}")
        if fact.get("schema_version") != "karkinos.capital_scaling_evidence_fact.v1":
            blockers.append(f"persisted_evidence_fact_schema_invalid:{kind}")
        if str(fact.get("evidence_kind") or "") != kind:
            blockers.append(f"persisted_evidence_fact_kind_mismatch:{kind}")
        stored_fingerprint = str(fact.get("source_fingerprint") or "")
        fingerprint_payload = dict(fact)
        fingerprint_payload.pop("source_fingerprint", None)
        if not stored_fingerprint or stored_fingerprint != _fingerprint(
            fingerprint_payload
        ):
            blockers.append(f"persisted_evidence_fact_fingerprint_invalid:{kind}")
        if str(fact.get("status") or "") != "clear":
            blockers.append(
                f"persisted_evidence_source_not_clear:{base['evidence_ref']}"
            )
        blockers.extend(_metric_mismatch_blockers(kind, fact, evidence))
        return _resolved_row(
            base,
            recorded_at=str(row.get("timestamp") or ""),
            source_payload={
                "window_id": identifier,
                "evidence_kind": kind,
                "status": fact.get("status"),
                "source_fingerprint": stored_fingerprint,
                "metrics": fact.get("metrics") or {},
            },
            source_fingerprint=stored_fingerprint or None,
            blockers=blockers,
        )

    def _resolve_broker_soak(
        self,
        *,
        base: dict[str, Any],
        identifier: str,
        evidence: CapitalScalingEvidence,
    ) -> dict[str, Any]:
        rows = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=identifier,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            return _not_found(base)
        row = rows[0]
        payload = _json_object(row.get("payload_json"))
        recorded_at = str(payload.get("observed_at") or row.get("timestamp") or "")
        blockers = _time_blockers(
            recorded_at,
            start=evidence.review_window_start,
            end=evidence.review_window_end,
            ref=str(base["evidence_ref"]),
        )
        if str(payload.get("soak_status") or "") != "healthy":
            blockers.append(
                f"persisted_evidence_source_not_clear:{base['evidence_ref']}"
            )
        return _resolved_row(
            base,
            recorded_at=recorded_at,
            source_payload={
                "observation_id": payload.get("observation_id"),
                "soak_status": payload.get("soak_status"),
                "trading_day": payload.get("trading_day"),
                "snapshot_fingerprint": payload.get("snapshot_fingerprint"),
                "blockers": payload.get("blockers") or [],
            },
            blockers=blockers,
        )

    def _resolve_execution_reconciliation(
        self,
        *,
        base: dict[str, Any],
        identifier: str,
        evidence: CapitalScalingEvidence,
    ) -> dict[str, Any]:
        row = self._db.get_execution_reconciliation_run_sync(identifier)
        if not row:
            return _not_found(base)
        run_date = str(row.get("run_date") or "")
        blockers = _date_blockers(
            run_date,
            start=evidence.review_window_start,
            end=evidence.review_window_end,
            ref=str(base["evidence_ref"]),
        )
        if (
            str(row.get("status") or "") != "clear"
            or int(row.get("open_item_count") or 0) != 0
        ):
            blockers.append(
                f"persisted_evidence_source_not_clear:{base['evidence_ref']}"
            )
        return _resolved_row(
            base,
            recorded_at=str(row.get("updated_at") or run_date),
            source_payload={
                "run_id": row.get("run_id"),
                "run_date": run_date,
                "status": row.get("status"),
                "item_count": row.get("item_count"),
                "open_item_count": row.get("open_item_count"),
            },
            blockers=blockers,
        )

    def _resolve_paper_shadow(
        self,
        *,
        base: dict[str, Any],
        identifier: str,
        evidence: CapitalScalingEvidence,
    ) -> dict[str, Any]:
        row = self._db.get_paper_shadow_run_sync(identifier)
        if not row:
            return _not_found(base)
        plan_date = str(row.get("plan_date") or "")
        blockers = _date_blockers(
            plan_date,
            start=evidence.review_window_start,
            end=evidence.review_window_end,
            ref=str(base["evidence_ref"]),
        )
        if (
            str(row.get("status") or "") != "within_expectations"
            or str(row.get("divergence_status") or "") != "within_expectations"
        ):
            blockers.append(
                f"persisted_evidence_source_not_clear:{base['evidence_ref']}"
            )
        return _resolved_row(
            base,
            recorded_at=str(row.get("updated_at") or plan_date),
            source_payload={
                "run_id": row.get("run_id"),
                "plan_date": plan_date,
                "input_fingerprint": row.get("input_fingerprint"),
                "status": row.get("status"),
                "divergence_status": row.get("divergence_status"),
                "simulated_order_count": row.get("simulated_order_count"),
                "simulated_fill_count": row.get("simulated_fill_count"),
            },
            blockers=blockers,
        )

    def _resolve_risk(
        self,
        *,
        base: dict[str, Any],
        identifier: str,
        evidence: CapitalScalingEvidence,
    ) -> dict[str, Any]:
        rows = self._db.list_events_sync(
            event_type="risk.signal.recorded",
            entity_type="risk_signal",
            entity_id=identifier,
            source="risk_decisions",
            limit=1,
        )
        if not rows:
            return _not_found(base)
        row = rows[0]
        payload = _json_object(row.get("payload_json"))
        decision = payload.get("decision")
        decision = decision if isinstance(decision, dict) else {}
        recorded_at = str(decision.get("timestamp") or row.get("timestamp") or "")
        blockers = _time_blockers(
            recorded_at,
            start=evidence.review_window_start,
            end=evidence.review_window_end,
            ref=str(base["evidence_ref"]),
        )
        if decision.get("passed") is not True:
            blockers.append(
                f"persisted_evidence_source_not_clear:{base['evidence_ref']}"
            )
        return _resolved_row(
            base,
            recorded_at=recorded_at,
            source_payload={
                "decision_id": decision.get("decision_id"),
                "timestamp": recorded_at,
                "passed": decision.get("passed"),
                "severity": decision.get("severity"),
            },
            blockers=blockers,
        )


def _not_found(base: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "resolution_status": "source_not_found",
        "blockers": [f"persisted_evidence_source_not_found:{base['evidence_ref']}"],
    }


def _resolved_row(
    base: dict[str, Any],
    *,
    recorded_at: str,
    source_payload: dict[str, Any],
    blockers: list[str],
    source_fingerprint: str | None = None,
) -> dict[str, Any]:
    return {
        **base,
        "source_recorded_at": recorded_at or None,
        "source_fingerprint": source_fingerprint or _fingerprint(source_payload),
        "resolution_status": "resolved_clear" if not blockers else "resolved_blocked",
        "blockers": list(dict.fromkeys(blockers)),
    }


def _metric_mismatch_blockers(
    kind: str,
    fact: dict[str, Any],
    evidence: CapitalScalingEvidence,
) -> list[str]:
    metrics = fact.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    expected: dict[str, Any] = {}
    if kind == "after_cost":
        expected = {"after_cost_return_pct": evidence.after_cost_return_pct}
    elif kind == "incident":
        expected = {
            "critical_incident_count": evidence.critical_incident_count,
            "policy_violation_count": evidence.policy_violation_count,
            "broker_disconnect_count": evidence.broker_disconnect_count,
        }
    elif kind == "capacity":
        expected = {
            "average_slippage_bps": evidence.average_slippage_bps,
            "p95_slippage_bps": evidence.p95_slippage_bps,
            "capacity_utilization_pct": evidence.capacity_utilization_pct,
            "liquidity_utilization_pct": evidence.liquidity_utilization_pct,
        }
    elif kind == "operating_sample":
        expected = {
            "reviewed_trading_days": evidence.reviewed_trading_days,
            "order_count": evidence.order_count,
            "filled_order_count": evidence.filled_order_count,
            "rejected_order_count": evidence.rejected_order_count,
            "partial_fill_count": evidence.partial_fill_count,
            "unresolved_reconciliation_count": (
                evidence.unresolved_reconciliation_count
            ),
            "p95_reconciliation_latency_minutes": (
                evidence.p95_reconciliation_latency_minutes
            ),
            "paper_shadow_divergence_count": (evidence.paper_shadow_divergence_count),
            "max_drawdown_pct": evidence.max_drawdown_pct,
        }
    blockers: list[str] = []
    for field, expected_value in expected.items():
        actual = metrics.get(field)
        if isinstance(expected_value, int):
            try:
                matches = int(actual) == expected_value
            except (TypeError, ValueError):
                matches = False
        else:
            matches = _decimal_equal(actual, expected_value)
        if not matches:
            blockers.append(f"persisted_evidence_metric_mismatch:{kind}:{field}")
    if kind == "capacity":
        try:
            fill_count = int(metrics.get("fill_count"))
        except (TypeError, ValueError):
            fill_count = -1
        if fill_count < evidence.filled_order_count:
            blockers.append("persisted_evidence_fill_coverage_insufficient:capacity")
    return blockers


def _decimal_equal(actual: Any, expected: Any) -> bool:
    try:
        return Decimal(str(actual)) == Decimal(str(expected))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _same_timestamp(actual: Any, expected: datetime) -> bool:
    parsed = _parse_datetime(str(actual or ""))
    return parsed == _aware_utc(expected) if parsed is not None else False


def _time_blockers(
    value: str,
    *,
    start: datetime,
    end: datetime,
    ref: str,
) -> list[str]:
    parsed = _parse_datetime(value)
    if parsed is None:
        return [f"persisted_evidence_timestamp_invalid:{ref}"]
    if parsed < _aware_utc(start) or parsed > _aware_utc(end):
        return [f"persisted_evidence_outside_review_window:{ref}"]
    return []


def _date_blockers(
    value: str,
    *,
    start: datetime,
    end: datetime,
    ref: str,
) -> list[str]:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return [f"persisted_evidence_date_invalid:{ref}"]
    parsed_at = datetime.combine(parsed, time.min, tzinfo=timezone.utc)
    start_date = _aware_utc(start).date()
    end_date = _aware_utc(end).date()
    if parsed_at.date() < start_date or parsed_at.date() > end_date:
        return [f"persisted_evidence_outside_review_window:{ref}"]
    return []


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
        return None
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
