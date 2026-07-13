from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from server.db import AppDatabase
from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
)
from server.services.capital_scaling_evidence_resolution import (
    CapitalScalingEvidenceResolver,
)
from server.services.capital_scaling_evidence_window import (
    CAPITAL_SCALING_EVIDENCE_SOURCE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
    CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION,
)
from server.services.capital_scaling_review import (
    CapitalScalingEvidence,
    CapitalScalingReview,
    CapitalScalingTier,
    CapitalScalingTierLimits,
)
from server.services.capital_scaling_review_audit import (
    CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
    CapitalScalingReviewAuditService,
)

NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
SOAK_ID = "a" * 64
RECONCILIATION_ID = "execution-reconciliation:2026-07-02"
PAPER_SHADOW_ID = "shadow:2026-07-02:abc123"
RISK_ID = "risk-decision-1"
WINDOW_ID = "f" * 64


def _evidence(*, refs: tuple[str, ...] | None = None) -> CapitalScalingEvidence:
    return CapitalScalingEvidence(
        review_window_start=NOW - timedelta(days=35),
        review_window_end=NOW,
        reviewed_trading_days=25,
        order_count=100,
        filled_order_count=98,
        rejected_order_count=1,
        partial_fill_count=4,
        critical_incident_count=0,
        policy_violation_count=0,
        unresolved_reconciliation_count=0,
        p95_reconciliation_latency_minutes=Decimal("15"),
        average_slippage_bps=Decimal("5"),
        p95_slippage_bps=Decimal("12"),
        after_cost_return_pct=Decimal("0.08"),
        max_drawdown_pct=Decimal("0.02"),
        capacity_utilization_pct=Decimal("0.60"),
        liquidity_utilization_pct=Decimal("0.50"),
        paper_shadow_divergence_count=0,
        broker_disconnect_count=0,
        evidence_refs=refs
        or (
            "account_truth:account-window",
            f"broker_soak:{SOAK_ID}",
            f"execution_reconciliation:{RECONCILIATION_ID}",
            f"paper_shadow:{PAPER_SHADOW_ID}",
            "after_cost:execution-quality",
            f"risk:{RISK_ID}",
            "incident:operations-window",
            "capacity:liquidity-window",
            "operating_sample:review-window",
        ),
    )


def _db_with_resolvable_sources(tmp_path) -> AppDatabase:
    db = AppDatabase(tmp_path / "capital-scaling-resolution.db")
    db.init_sync()
    observed_at = (NOW - timedelta(days=1)).isoformat()
    db.append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
        timestamp=observed_at,
        entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
        entity_id=SOAK_ID,
        source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
        source_ref="qmt-local",
        payload={
            "schema_version": "karkinos.broker_connector_soak_observation.v1",
            "observation_id": SOAK_ID,
            "observed_at": observed_at,
            "trading_day": "2026-07-09",
            "soak_status": "healthy",
            "snapshot_fingerprint": "b" * 64,
            "blockers": [],
            "account_id": "must-not-be-returned",
        },
    )
    db.upsert_execution_reconciliation_run_sync(
        run_id=RECONCILIATION_ID,
        run_date="2026-07-02",
        status="clear",
        item_count=2,
        open_item_count=0,
        payload={"schema_version": "karkinos.execution_reconciliation.v1"},
        items=[],
    )
    db.upsert_paper_shadow_run_sync(
        run_id=PAPER_SHADOW_ID,
        plan_date="2026-07-02",
        input_fingerprint="c" * 64,
        status="within_expectations",
        order_intent_count=2,
        simulated_order_count=2,
        simulated_fill_count=2,
        divergence_status="within_expectations",
        next_manual_review_step="review_manual_confirmation",
        payload={"schema_version": "karkinos.paper_shadow_run.v1"},
    )
    risk_at = (NOW - timedelta(days=2)).isoformat()
    db.append_event_sync(
        event_type="risk.signal.recorded",
        timestamp=risk_at,
        entity_type="risk_signal",
        entity_id=RISK_ID,
        source="risk_decisions",
        source_ref=RISK_ID,
        payload={
            "decision": {
                "decision_id": RISK_ID,
                "timestamp": risk_at,
                "passed": True,
                "severity": "info",
            }
        },
    )
    return db


def _computed_fact(kind: str, metrics: dict) -> dict:
    payload = {
        "schema_version": "karkinos.capital_scaling_evidence_fact.v1",
        "evidence_kind": kind,
        "status": "clear",
        "metrics": metrics,
        "blockers": [],
        "source_refs": [f"synthetic_source:{kind}"],
        "assumptions": [],
        "limitations": [],
        "does_not_issue_capital_authorization": True,
        "does_not_mutate_runtime_limits": True,
        "does_not_submit_broker_order": True,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        **payload,
        "source_fingerprint": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }


def _record_computed_window(db: AppDatabase) -> None:
    db.append_event_sync(
        event_type=CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
        timestamp=NOW.isoformat(),
        entity_type=CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
        entity_id=WINDOW_ID,
        source=CAPITAL_SCALING_EVIDENCE_SOURCE,
        source_ref="synthetic-deterministic-window",
        payload={
            "schema_version": CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION,
            "window_id": WINDOW_ID,
            "review_window_start": (NOW - timedelta(days=35)).isoformat(),
            "review_window_end": NOW.isoformat(),
            "facts": {
                "account_truth": _computed_fact("account_truth", {}),
                "after_cost": _computed_fact(
                    "after_cost", {"after_cost_return_pct": "0.08"}
                ),
                "incident": _computed_fact(
                    "incident",
                    {
                        "critical_incident_count": 0,
                        "policy_violation_count": 0,
                        "broker_disconnect_count": 0,
                    },
                ),
                "capacity": _computed_fact(
                    "capacity",
                    {
                        "fill_count": 98,
                        "average_slippage_bps": "5",
                        "p95_slippage_bps": "12",
                        "capacity_utilization_pct": "0.6",
                        "liquidity_utilization_pct": "0.5",
                    },
                ),
                "operating_sample": _computed_fact(
                    "operating_sample",
                    {
                        "reviewed_trading_days": 25,
                        "order_count": 100,
                        "filled_order_count": 98,
                        "rejected_order_count": 1,
                        "partial_fill_count": 4,
                        "unresolved_reconciliation_count": 0,
                        "p95_reconciliation_latency_minutes": "15",
                        "paper_shadow_divergence_count": 0,
                        "max_drawdown_pct": "0.02",
                    },
                ),
                "execution_scope": _computed_fact(
                    "execution_scope",
                    {
                        "sampled_order_count": 100,
                        "runtime_session_bound_order_count": 0,
                        "exact_batch_bound_order_count": 100,
                        "dual_bound_order_count": 0,
                        "unbound_order_count": 0,
                        "runtime_session_count": 0,
                        "exact_batch_count": 5,
                        "invalid_runtime_admission_count": 0,
                        "orphan_runtime_admission_count": 0,
                        "invalid_exact_batch_count": 0,
                    },
                ),
            },
        },
    )


def _resolved_refs() -> tuple[str, ...]:
    return (
        f"account_truth:{WINDOW_ID}",
        f"broker_soak:{SOAK_ID}",
        f"execution_reconciliation:{RECONCILIATION_ID}",
        f"paper_shadow:{PAPER_SHADOW_ID}",
        f"after_cost:{WINDOW_ID}",
        f"risk:{RISK_ID}",
        f"incident:{WINDOW_ID}",
        f"capacity:{WINDOW_ID}",
        f"operating_sample:{WINDOW_ID}",
        f"execution_scope:{WINDOW_ID}",
    )


def test_resolver_links_direct_refs_and_blocks_missing_computed_window_sources(
    tmp_path,
) -> None:
    db = _db_with_resolvable_sources(tmp_path)

    resolution = CapitalScalingEvidenceResolver(db=db).resolve(evidence=_evidence())

    assert resolution["resolution_status"] == "blocked_unresolved_sources"
    assert resolution["resolved_clear_kinds"] == [
        "broker_soak",
        "execution_reconciliation",
        "paper_shadow",
        "risk",
    ]
    assert resolution["unsupported_evidence_kinds"] == []
    assert "persisted_evidence_source_not_found:after_cost:execution-quality" in (
        resolution["blockers"]
    )
    assert "persisted_evidence_kind_not_clear:account_truth" in resolution["blockers"]
    assert "persisted_evidence_kind_not_clear:capacity" in resolution["blockers"]
    assert "persisted_evidence_kind_not_clear:operating_sample" in (
        resolution["blockers"]
    )
    assert "persisted_evidence_kind_not_clear:execution_scope" in (
        resolution["blockers"]
    )
    assert resolution["all_required_sources_resolved_clear"] is False
    assert len(resolution["resolution_fingerprint"]) == 64
    serialized = json.dumps(resolution, sort_keys=True)
    assert "must-not-be-returned" not in serialized
    assert "account_id" not in serialized


def test_resolver_fails_closed_for_non_clear_or_out_of_window_source(tmp_path) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-resolution.db")
    db.init_sync()
    old_at = (NOW - timedelta(days=90)).isoformat()
    db.append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
        timestamp=old_at,
        entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
        entity_id=SOAK_ID,
        source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
        source_ref="qmt-local",
        payload={
            "observation_id": SOAK_ID,
            "observed_at": old_at,
            "soak_status": "blocked",
            "trading_day": "2026-04-01",
            "snapshot_fingerprint": "d" * 64,
            "blockers": ["connector_unavailable"],
        },
    )

    resolution = CapitalScalingEvidenceResolver(db=db).resolve(
        evidence=_evidence(refs=(f"broker_soak:{SOAK_ID}",))
    )

    ref = resolution["references"][0]
    assert ref["resolution_status"] == "resolved_blocked"
    assert (
        f"persisted_evidence_outside_review_window:broker_soak:{SOAK_ID}"
        in ref["blockers"]
    )
    assert (
        f"persisted_evidence_source_not_clear:broker_soak:{SOAK_ID}" in ref["blockers"]
    )


def test_legacy_v1_window_cannot_satisfy_execution_scope(tmp_path) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-resolution.db")
    db.init_sync()
    legacy_window_id = "e" * 64
    db.append_event_sync(
        event_type=CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE,
        timestamp=NOW.isoformat(),
        entity_type=CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE,
        entity_id=legacy_window_id,
        source=CAPITAL_SCALING_EVIDENCE_SOURCE,
        source_ref="legacy-v1-window",
        payload={
            "schema_version": "karkinos.capital_scaling_evidence_window.v1",
            "window_id": legacy_window_id,
            "review_window_start": (NOW - timedelta(days=35)).isoformat(),
            "review_window_end": NOW.isoformat(),
            "facts": {
                "execution_scope": _computed_fact(
                    "execution_scope",
                    {"sampled_order_count": 100, "unbound_order_count": 0},
                )
            },
        },
    )

    resolution = CapitalScalingEvidenceResolver(db=db).resolve(
        evidence=_evidence(refs=(f"execution_scope:{legacy_window_id}",))
    )

    assert "persisted_evidence_window_schema_invalid:execution_scope" in (
        resolution["blockers"]
    )
    assert resolution["all_required_sources_resolved_clear"] is False
    assert resolution["resolution_status"] == "blocked_unresolved_sources"


def test_resolver_accepts_computed_window_facts_and_rejects_metric_mismatch(
    tmp_path,
) -> None:
    db = _db_with_resolvable_sources(tmp_path)
    _record_computed_window(db)
    refs = _resolved_refs()
    evidence = _evidence(refs=refs)

    resolved = CapitalScalingEvidenceResolver(db=db).resolve(evidence=evidence)
    mismatched = CapitalScalingEvidenceResolver(db=db).resolve(
        evidence=replace(evidence, average_slippage_bps=Decimal("6"))
    )
    sample_mismatched = CapitalScalingEvidenceResolver(db=db).resolve(
        evidence=replace(evidence, max_drawdown_pct=Decimal("0.03"))
    )

    assert resolved["resolution_status"] == "resolved_clear"
    assert resolved["all_required_sources_resolved_clear"] is True
    assert resolved["resolved_clear_kinds"] == sorted(
        [
            "account_truth",
            "broker_soak",
            "execution_reconciliation",
            "paper_shadow",
            "after_cost",
            "risk",
            "incident",
            "capacity",
            "operating_sample",
            "execution_scope",
        ]
    )
    assert (
        "persisted_evidence_metric_mismatch:capacity:average_slippage_bps"
        in mismatched["blockers"]
    )
    assert mismatched["resolution_status"] == "blocked_unresolved_sources"
    assert (
        "persisted_evidence_metric_mismatch:operating_sample:max_drawdown_pct"
        in sample_mismatched["blockers"]
    )
    assert sample_mismatched["resolution_status"] == "blocked_unresolved_sources"


def test_all_resolved_sources_only_allow_a_separate_new_authorization_request(
    tmp_path,
) -> None:
    db = _db_with_resolvable_sources(tmp_path)
    _record_computed_window(db)
    limits = CapitalScalingTierLimits(
        max_authorized_capital=Decimal("10000"),
        max_order_value=Decimal("2000"),
        max_daily_turnover=Decimal("20000"),
        max_daily_loss=Decimal("500"),
        max_drawdown_pct=Decimal("0.05"),
    )
    review = CapitalScalingReview(
        current_tier=CapitalScalingTier(
            tier_id="pilot-1",
            policy_version="pilot-1-v1",
            limits=limits,
        ),
        proposed_tier=CapitalScalingTier(
            tier_id="pilot-2",
            policy_version="pilot-2-v1",
            limits=replace(
                limits,
                max_authorized_capital=Decimal("20000"),
                max_order_value=Decimal("3000"),
            ),
        ),
        evidence=_evidence(refs=_resolved_refs()),
    )
    service = CapitalScalingReviewAuditService(db=db, clock=lambda: NOW)

    evaluation = service.record_evaluation(review=review)
    decision = service.record_review_decision(
        evaluation_fingerprint=evaluation["evaluation_fingerprint"],
        chosen_action="request_new_authorization_for_scale_up",
        operator_label="local-owner",
        acknowledgement=CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
    )

    assert evaluation["evidence_source_resolution_status"] == "resolved_clear"
    assert evaluation["decision"]["eligible_for_scale_up_review"] is True
    assert evaluation["decision"]["recommended_action"] == (
        "request_new_authorization_for_scale_up"
    )
    assert decision["requests_new_authorization"] is True
    assert decision["new_authorization_issued"] is False
    assert decision["authority_change_applied"] is False
    assert decision["broker_submission_enabled"] is False


def test_resolution_fingerprint_is_deterministic_and_source_sensitive(
    tmp_path,
) -> None:
    db = _db_with_resolvable_sources(tmp_path)
    resolver = CapitalScalingEvidenceResolver(db=db)

    first = resolver.resolve(evidence=_evidence())
    rerun = resolver.resolve(evidence=_evidence())
    later_at = (NOW - timedelta(hours=1)).isoformat()
    db.append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
        timestamp=later_at,
        entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
        entity_id=SOAK_ID,
        source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
        source_ref="qmt-local",
        payload={
            "observation_id": SOAK_ID,
            "observed_at": later_at,
            "soak_status": "blocked",
            "trading_day": "2026-07-10",
            "snapshot_fingerprint": "e" * 64,
            "blockers": ["schema_drift"],
        },
    )
    changed = resolver.resolve(evidence=_evidence())

    assert first["resolution_fingerprint"] == rerun["resolution_fingerprint"]
    assert first["resolution_fingerprint"] != changed["resolution_fingerprint"]
    broker_soak = next(
        row for row in changed["references"] if row["evidence_kind"] == "broker_soak"
    )
    assert broker_soak["resolution_status"] == "resolved_blocked"
