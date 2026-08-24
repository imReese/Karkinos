"""Stateful strategy promotion pipeline."""

from __future__ import annotations

from typing import Any

from analytics.research_account_capital_evidence import (
    is_valid_passed_research_account_capital_evidence,
)
from analytics.strategy_advancement_gate import (
    build_strategy_advancement_gate,
    is_valid_passed_strategy_advancement_gate,
    strategy_advancement_backtest_view,
)
from server.ai_runtime.contracts import content_fingerprint
from server.services.reviewed_fee_schedule import active_review_matches_fee_evidence
from server.services.strategy_promotion_support import (
    AI_SHADOW_STRATEGY_PREFIX,
    STRATEGY_PROMOTION_LIFECYCLE_STAGES,
    STRATEGY_PROMOTION_SCHEMA_VERSION,
)
from server.services.strategy_promotion_support import (
    ai_shadow_dataset_replay_evidence as _ai_shadow_dataset_replay_evidence,
)
from server.services.strategy_promotion_support import (
    ai_shadow_fee_schedule_binding as _ai_shadow_fee_schedule_binding,
)
from server.services.strategy_promotion_support import (
    binding_backtest_source as _binding_backtest_source,
)
from server.services.strategy_promotion_support import (
    dataset_replay_evidence_from_binding as _dataset_replay_evidence_from_binding,
)
from server.services.strategy_promotion_support import int_or_none as _int_or_none
from server.services.strategy_promotion_support import is_promotable as _is_promotable
from server.services.strategy_promotion_support import json_list as _json_list
from server.services.strategy_promotion_support import json_object as _json_object
from server.services.strategy_promotion_support import (
    lifecycle_metadata as _lifecycle_metadata,
)
from server.services.strategy_promotion_support import (
    missing_requirements as _missing_requirements,
)
from server.services.strategy_promotion_support import (
    resolve_ai_shadow_daily_strategy_artifact_binding as _resolve_ai_shadow_daily_strategy_artifact_binding,
)
from server.services.strategy_promotion_support import (
    strategy_advancement_gate_fingerprint as _strategy_advancement_gate_fingerprint,
)

STRATEGY_ORDER_GENERATION_GATE_SCHEMA_VERSION = (
    "karkinos.strategy_order_generation_gate.v1"
)
STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION = (
    "approve_evidence_bound_strategy_for_paper_shadow_only_without_"
    "execution_or_capital_authority"
)
STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION = (
    "pause_or_retire_strategy_without_execution_or_capital_authority"
)

_AUDIT_ONLY_LIFECYCLE_TRANSITIONS = {
    "paused": "lifecycle_paused",
    "retired": "lifecycle_retired",
}


class StrategyPromotionPipeline:
    """Persist strategy promotion stage decisions with safety gates."""

    def __init__(self, *, db: Any) -> None:
        self._db = db

    def evaluate_readiness(
        self,
        readiness: dict[str, Any],
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        strategy_id = _strategy_id(readiness)
        _require_ai_shadow_readiness_binding(self._db, readiness)
        missing = _missing_requirements(readiness)
        promotable = _is_promotable(readiness)
        state = self._db.upsert_strategy_promotion_state_sync(
            strategy_id=strategy_id,
            stage="research",
            gate_status="paper_shadow_ready" if promotable else "blocked",
            live_like_enabled=False,
            missing_requirements=missing,
            backtest_result_id=_int_or_none(readiness.get("backtest_result_id")),
            payload={
                "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
                "readiness": readiness,
            },
        )
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type="readiness_evaluated",
            from_stage=None,
            to_stage="research",
            actor=actor,
            payload={"missing_requirements": missing, "is_promotable": promotable},
        )
        return self._normalize_state(state)

    def request_promotion(
        self,
        strategy_id: str,
        *,
        target_stage: str,
        readiness: dict[str, Any],
        actor: str,
        confirmation: str,
        review_note: str,
    ) -> dict[str, Any]:
        target_stage = str(target_stage)
        if target_stage == "live_like":
            self._record_rejected_live_like(strategy_id, actor=actor)
            raise ValueError("live-like promotion is disabled by default")
        if target_stage != "paper_shadow":
            raise ValueError(f"unsupported promotion target: {target_stage}")
        normalized_actor = str(actor or "").strip()
        if not normalized_actor:
            raise ValueError("paper/shadow promotion reviewer is required")
        if confirmation != STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION:
            raise ValueError("paper/shadow promotion requires exact human confirmation")
        normalized_review_note = str(review_note or "").strip()
        if not normalized_review_note:
            raise ValueError("paper/shadow promotion review note is required")
        if strategy_id != _strategy_id(readiness):
            raise ValueError("readiness strategy_id does not match promotion target")
        _require_ai_shadow_readiness_binding(self._db, readiness)
        missing = _missing_requirements(readiness)
        if missing or not _is_promotable(readiness):
            raise ValueError(
                "missing readiness requirements: " + ", ".join(missing or ["unknown"])
            )
        current = self._db.get_strategy_promotion_state_sync(strategy_id)
        from_stage = str(current["stage"]) if current else "research"
        state = self._db.upsert_strategy_promotion_state_sync(
            strategy_id=strategy_id,
            stage="paper_shadow",
            gate_status="paper_shadow_enabled",
            live_like_enabled=False,
            missing_requirements=[],
            backtest_result_id=_int_or_none(readiness.get("backtest_result_id")),
            payload={
                "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
                "readiness": readiness,
                "human_review": {
                    "reviewer": normalized_actor,
                    "review_note": normalized_review_note,
                    "confirmation_recorded": True,
                    "strategy_advancement_gate_fingerprint": (
                        _strategy_advancement_gate_fingerprint(readiness)
                    ),
                },
                "live_like_enabled": False,
                "broker_submission_enabled": False,
                "does_not_change_capital_authority": True,
            },
        )
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type="promoted_to_paper_shadow",
            from_stage=from_stage,
            to_stage="paper_shadow",
            actor=normalized_actor,
            payload={
                "manual_confirmation_required": True,
                "manual_confirmation_recorded": True,
                "reviewer": normalized_actor,
                "review_note": normalized_review_note,
                "strategy_advancement_gate_fingerprint": (
                    _strategy_advancement_gate_fingerprint(readiness)
                ),
                "live_like_enabled": False,
                "broker_submission_enabled": False,
                "does_not_change_capital_authority": True,
            },
        )
        return self._normalize_state(state)

    def request_lifecycle_transition(
        self,
        strategy_id: str,
        *,
        target_stage: str,
        reason: str,
        actor: str,
        confirmation: str,
    ) -> dict[str, Any]:
        target_stage = str(target_stage)
        strategy_id = str(strategy_id).strip()
        if not strategy_id:
            raise ValueError("strategy_id is required")
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("lifecycle transition reason is required")
        normalized_actor = str(actor or "").strip()
        if not normalized_actor:
            raise ValueError("lifecycle transition reviewer is required")
        if confirmation != STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION:
            raise ValueError("lifecycle transition requires exact human confirmation")
        if target_stage == "controlled_bridge_pilot":
            self._record_rejected_controlled_bridge_pilot(
                strategy_id,
                reason=reason,
                actor=normalized_actor,
            )
            raise ValueError("controlled bridge pilot is disabled by default")
        if target_stage not in _AUDIT_ONLY_LIFECYCLE_TRANSITIONS:
            raise ValueError(f"unsupported lifecycle target: {target_stage}")

        current = self._db.get_strategy_promotion_state_sync(strategy_id)
        from_stage = str(current["stage"]) if current else "research"
        missing_requirements = (
            _json_list(current.get("missing_requirements_json")) if current else []
        )
        backtest_result_id = (
            _int_or_none(current.get("backtest_result_id")) if current else None
        )
        payload = {
            "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
            "reason": reason,
            "from_stage": from_stage,
            "to_stage": target_stage,
            "manual_confirmation_required": True,
            "manual_confirmation_recorded": True,
            "reviewer": normalized_actor,
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_submit_broker_orders": True,
            "does_not_mutate_production_ledger": True,
        }
        state = self._db.upsert_strategy_promotion_state_sync(
            strategy_id=strategy_id,
            stage=target_stage,
            gate_status=target_stage,
            live_like_enabled=False,
            missing_requirements=missing_requirements,
            backtest_result_id=backtest_result_id,
            payload=payload,
        )
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type=_AUDIT_ONLY_LIFECYCLE_TRANSITIONS[target_stage],
            from_stage=from_stage,
            to_stage=target_stage,
            actor=normalized_actor,
            payload=payload,
        )
        return self._normalize_state(state)

    def list_states(self) -> list[dict[str, Any]]:
        return [
            self._normalize_state(row)
            for row in self._db.list_strategy_promotion_states_sync()
        ]

    def list_events(self, strategy_id: str) -> list[dict[str, Any]]:
        return self._db.list_strategy_promotion_events_sync(strategy_id)

    def _record_rejected_live_like(
        self,
        strategy_id: str,
        *,
        actor: str | None,
    ) -> None:
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type="live_like_promotion_rejected",
            from_stage=None,
            to_stage="live_like_blocked",
            actor=actor,
            payload={
                "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
                "reason": "live-like promotion is disabled by default",
            },
        )

    def _record_rejected_controlled_bridge_pilot(
        self,
        strategy_id: str,
        *,
        reason: str,
        actor: str | None,
    ) -> None:
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type="controlled_bridge_pilot_rejected",
            from_stage=None,
            to_stage="controlled_bridge_pilot_blocked",
            actor=actor,
            payload={
                "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
                "reason": reason,
                "controlled_bridge_pilot_enabled": False,
                "live_like_enabled": False,
                "broker_submission_enabled": False,
                "does_not_submit_broker_orders": True,
            },
        )

    def _normalize_state(self, row: dict[str, Any]) -> dict[str, Any]:
        missing = _json_list(row.get("missing_requirements_json"))
        payload = _json_object(row.get("payload_json"))
        return {
            **row,
            "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
            "live_like_enabled": bool(row.get("live_like_enabled")),
            "missing_requirements": missing,
            "payload": payload,
            "lifecycle": _lifecycle_metadata(str(row.get("stage") or "research")),
        }


def _strategy_id(readiness: dict[str, Any]) -> str:
    strategy_id = str(readiness.get("strategy_id") or "").strip()
    if not strategy_id:
        raise ValueError("readiness strategy_id is required")
    return strategy_id


def resolve_ai_shadow_strategy_promotion_binding(
    db: Any,
    strategy_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """Re-resolve one reserved strategy against its canonical approval facts."""

    normalized_strategy_id = str(strategy_id or "").strip()
    if not normalized_strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
        return {
            "status": "not_required",
            "strategy_id": normalized_strategy_id,
        }, []
    candidate_id = normalized_strategy_id.removeprefix(AI_SHADOW_STRATEGY_PREFIX)
    state_reader = getattr(db, "get_strategy_promotion_state_sync", None)
    state = state_reader(normalized_strategy_id) if callable(state_reader) else None
    state = state if isinstance(state, dict) else {}
    payload = _json_object(state.get("payload_json"))
    readiness = _json_object(payload.get("readiness"))
    human_review = _json_object(payload.get("human_review"))
    readiness_for_validation = {
        **readiness,
        "strategy_id": readiness.get("strategy_id") or normalized_strategy_id,
    }
    blockers = _ai_shadow_readiness_binding_blockers(db, readiness_for_validation)
    if not candidate_id:
        blockers.append("ai_shadow_candidate_id_missing")
    if readiness.get("strategy_id") != normalized_strategy_id:
        blockers.append("ai_shadow_strategy_state_readiness_mismatch")
    if state.get("stage") != "paper_shadow":
        blockers.append("ai_shadow_strategy_not_in_paper_shadow")
    if state.get("gate_status") != "paper_shadow_enabled":
        blockers.append("ai_shadow_strategy_gate_not_enabled")
    if bool(state.get("live_like_enabled")):
        blockers.append("ai_shadow_strategy_live_like_must_remain_disabled")
    if int(state.get("backtest_result_id") or 0) != int(
        readiness.get("backtest_result_id") or 0
    ):
        blockers.append("ai_shadow_strategy_backtest_state_mismatch")
    gate_fingerprint = _strategy_advancement_gate_fingerprint(readiness)
    if not str(human_review.get("reviewer") or "").strip():
        blockers.append("ai_shadow_strategy_human_reviewer_missing")
    if not str(human_review.get("review_note") or "").strip():
        blockers.append("ai_shadow_strategy_human_review_note_missing")
    if human_review.get("confirmation_recorded") is not True:
        blockers.append("ai_shadow_strategy_human_confirmation_missing")
    if (
        not gate_fingerprint
        or human_review.get("strategy_advancement_gate_fingerprint") != gate_fingerprint
    ):
        blockers.append("ai_shadow_strategy_human_review_gate_mismatch")
    blockers = list(dict.fromkeys(blockers))
    fee_schedule_binding = _ai_shadow_fee_schedule_binding(db, candidate_id)
    dataset_replay = _ai_shadow_dataset_replay_evidence(db, candidate_id)
    daily_strategy_artifact_binding = readiness.get("daily_strategy_artifact_binding")
    daily_strategy_artifact_binding = (
        dict(daily_strategy_artifact_binding)
        if isinstance(daily_strategy_artifact_binding, dict)
        else {}
    )
    return {
        "status": "pass" if not blockers else "blocked",
        "strategy_id": normalized_strategy_id,
        "candidate_id": candidate_id,
        "stage": state.get("stage"),
        "gate_status": state.get("gate_status"),
        "backtest_result_id": state.get("backtest_result_id"),
        "comparison_fingerprint": readiness.get("comparison_fingerprint"),
        "human_approval_id": readiness.get("human_approval_id"),
        "human_reviewer": human_review.get("reviewer"),
        "human_review_note_recorded": bool(
            str(human_review.get("review_note") or "").strip()
        ),
        "strategy_advancement_gate_fingerprint": gate_fingerprint,
        "daily_strategy_artifact_binding": daily_strategy_artifact_binding,
        "fee_schedule_binding": fee_schedule_binding,
        "dataset_replay": dataset_replay,
        "live_like_enabled": bool(state.get("live_like_enabled")),
    }, blockers


def resolve_strategy_promotion_binding(
    db: Any,
    strategy_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve current evidence-owned promotion facts for one strategy."""

    normalized_strategy_id = str(strategy_id or "").strip()
    if normalized_strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
        return resolve_ai_shadow_strategy_promotion_binding(
            db,
            normalized_strategy_id,
        )
    state_reader = getattr(db, "get_strategy_promotion_state_sync", None)
    state = state_reader(normalized_strategy_id) if callable(state_reader) else None
    if not isinstance(state, dict):
        return {
            "status": "blocked",
            "strategy_id": normalized_strategy_id,
            "stage": None,
            "gate_status": "missing",
            "backtest_result_id": None,
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_change_capital_authority": True,
            "evidence_owner": None,
        }, [
            (
                "strategy_id_missing"
                if not normalized_strategy_id
                else "strategy_promotion_evidence_missing"
            )
        ]

    return {
        "status": "blocked",
        "strategy_id": normalized_strategy_id,
        "stage": state.get("stage"),
        "gate_status": state.get("gate_status"),
        "backtest_result_id": state.get("backtest_result_id"),
        "live_like_enabled": bool(state.get("live_like_enabled")),
        "broker_submission_enabled": False,
        "does_not_change_capital_authority": True,
        "evidence_owner": None,
    }, ["strategy_promotion_source_not_evidence_owned"]


def resolve_strategy_order_generation_gate(
    db: Any,
    strategy_id: str,
    *,
    as_of_date: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Fail closed before a strategy can enter paper/shadow or ticketing.

    This is a read-only evidence resolver.  Passing it permits only downstream
    paper/shadow evaluation; it is not an order, execution, or capital grant.
    """

    promotion, promotion_blockers = resolve_strategy_promotion_binding(
        db,
        strategy_id,
    )
    blockers = list(promotion_blockers)
    if promotion.get("status") != "pass":
        blockers.append("strategy_promotion_not_passing")
    if promotion.get("stage") != "paper_shadow":
        blockers.append("strategy_not_promoted_to_paper_shadow")
    if promotion.get("gate_status") != "paper_shadow_enabled":
        blockers.append("strategy_paper_shadow_gate_not_enabled")
    if bool(promotion.get("live_like_enabled")):
        blockers.append("strategy_live_like_must_remain_disabled")

    normalized_strategy_id = str(strategy_id or "").strip()
    if normalized_strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
        fee_schedule_binding = promotion.get("fee_schedule_binding")
        fee_schedule_binding = (
            fee_schedule_binding if isinstance(fee_schedule_binding, dict) else {}
        )
        blockers.extend(
            f"strategy_{blocker}"
            for blocker in active_review_matches_fee_evidence(
                db,
                fee_schedule_binding,
                as_of_date=as_of_date,
            )
        )

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": STRATEGY_ORDER_GENERATION_GATE_SCHEMA_VERSION,
        "status": "pass" if not blockers else "blocked",
        "strategy_id": normalized_strategy_id,
        "as_of_date": str(as_of_date or "") or None,
        "promotion": promotion,
        "blockers": blockers,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "paper_shadow_evaluation_only": True,
        "manual_ticket_requires_current_paper_shadow": True,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
    }, blockers


def _require_ai_shadow_readiness_binding(db: Any, readiness: dict[str, Any]) -> None:
    blockers = _ai_shadow_readiness_binding_blockers(db, readiness)
    if blockers:
        raise ValueError(
            "reserved AI shadow readiness binding invalid: " + ", ".join(blockers)
        )


def _ai_shadow_readiness_binding_blockers(
    db: Any,
    readiness: dict[str, Any],
) -> list[str]:
    strategy_id = str(readiness.get("strategy_id") or "").strip()
    if not strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
        return []
    candidate_id = strategy_id.removeprefix(AI_SHADOW_STRATEGY_PREFIX)
    reader = getattr(db, "get_ai_shadow_strategy_promotion_binding_sync", None)
    binding = reader(candidate_id) if callable(reader) and candidate_id else None
    if not isinstance(binding, dict):
        return ["ai_shadow_candidate_approval_binding_missing"]

    current_daily_strategy_artifact_binding = (
        _resolve_ai_shadow_daily_strategy_artifact_binding(
            db,
            candidate_id=candidate_id,
            run_id=str(binding.get("run_id") or ""),
        )
    )
    comparison = _json_object(binding.get("comparison_json"))
    expected_candidate_fingerprint = content_fingerprint(
        {
            "candidate_id": candidate_id,
            "comparison": comparison,
            "candidate_result_id": binding.get("candidate_result_id"),
            "critique_id": binding.get("critique_id"),
        }
    )
    blockers: list[str] = []
    readiness_daily_strategy_artifact_binding = readiness.get(
        "daily_strategy_artifact_binding"
    )
    if not isinstance(readiness_daily_strategy_artifact_binding, dict):
        blockers.append("ai_shadow_readiness_daily_strategy_artifact_binding_missing")
    if current_daily_strategy_artifact_binding is None:
        blockers.append("ai_shadow_daily_strategy_artifact_not_verified")
    elif (
        not isinstance(readiness_daily_strategy_artifact_binding, dict)
        or readiness_daily_strategy_artifact_binding
        != current_daily_strategy_artifact_binding
    ):
        blockers.append("ai_shadow_readiness_daily_strategy_artifact_binding_mismatch")
    if binding.get("candidate_id") != candidate_id:
        blockers.append("ai_shadow_candidate_identity_mismatch")
    if binding.get("candidate_status") != "awaiting_human_approval":
        blockers.append("ai_shadow_candidate_status_not_approvable")
    if binding.get("recommendation") != "paper_shadow_review":
        blockers.append("ai_shadow_candidate_recommendation_not_approvable")
    if binding.get("promotion_status") not in {
        "paper_shadow_approval_recorded",
        "paper_shadow_approved",
    }:
        blockers.append("ai_shadow_human_approval_not_recorded")
    if binding.get("target_stage") != "paper_shadow":
        blockers.append("ai_shadow_approval_target_invalid")
    comparison_gate = comparison.get("promotion_gate")
    if not is_valid_passed_strategy_advancement_gate(comparison_gate):
        blockers.append("ai_shadow_strategy_advancement_gate_invalid")
    baseline_source = _binding_backtest_source(binding, "baseline")
    candidate_source = _binding_backtest_source(binding, "candidate")
    if comparison.get("baseline_source_fingerprint") != content_fingerprint(
        baseline_source
    ):
        blockers.append("ai_shadow_baseline_source_drift")
    if comparison.get("candidate_source_fingerprint") != content_fingerprint(
        candidate_source
    ):
        blockers.append("ai_shadow_candidate_source_drift")
    candidate_metrics = _json_object(binding.get("candidate_metrics_json"))
    dataset_replay = _dataset_replay_evidence_from_binding(db, binding)
    if dataset_replay.get("status") != "pass":
        blockers.append("ai_shadow_dataset_replay_not_reproducible")
    candidate_fee_evidence = _json_object(
        candidate_metrics.get("fee_component_evidence")
    )
    blockers.extend(
        f"ai_shadow_{blocker}"
        for blocker in active_review_matches_fee_evidence(
            db,
            {
                **candidate_fee_evidence,
                **_json_object(candidate_fee_evidence.get("fee_schedule_binding")),
            },
        )
    )
    if (
        binding.get("research_run_status") != "completed"
        or int(binding.get("research_run_baseline_result_id") or 0)
        != int(binding.get("baseline_result_id") or 0)
        or binding.get("research_run_session_id") != binding.get("session_id")
    ):
        blockers.append("ai_shadow_research_run_binding_drift")
    candidate_capital_evidence = _json_object(
        candidate_metrics.get("account_capital_constraint")
    )
    if not is_valid_passed_research_account_capital_evidence(
        candidate_capital_evidence,
        expected_initial_cash=binding.get("candidate_initial_cash"),
        expected_valuation_snapshot_id=binding.get(
            "research_run_valuation_snapshot_id"
        ),
        expected_ledger_cutoff_id=binding.get("research_run_ledger_cutoff_id"),
    ):
        blockers.append("ai_shadow_research_account_capital_binding_drift")
    candidate_dataset = _json_object(candidate_metrics.get("dataset_snapshot"))
    if (
        binding.get("formula_backtest_status") != "completed"
        or int(binding.get("canonical_backtest_result_id") or 0)
        != int(binding.get("candidate_result_id") or 0)
        or binding.get("formula_backtest_session_id") != binding.get("session_id")
        or binding.get("formula_backtest_draft_id") != binding.get("draft_id")
        or binding.get("formula_backtest_formula_fingerprint")
        != candidate_metrics.get("formula_fingerprint")
        or binding.get("formula_backtest_dataset_snapshot_id")
        != candidate_dataset.get("snapshot_id")
        or binding.get("formula_backtest_cost_model_reference")
        != candidate_fee_evidence.get("cost_model_reference")
        or binding.get("backtest_evidence_fingerprint")
        != content_fingerprint(candidate_metrics.get("research_evidence_bundle"))
    ):
        blockers.append("ai_shadow_canonical_backtest_binding_drift")
    critique_artifact = _json_object(binding.get("critique_artifact_json"))
    if (
        binding.get("critique_status") != "completed"
        or binding.get("critique_session_id") != binding.get("session_id")
        or binding.get("critique_draft_id") != binding.get("draft_id")
        or binding.get("critique_backtest_run_id") != binding.get("backtest_run_id")
        or binding.get("critique_artifact_fingerprint")
        != content_fingerprint(critique_artifact)
        or content_fingerprint(comparison.get("deepseek_critique"))
        != content_fingerprint(critique_artifact)
    ):
        blockers.append("ai_shadow_critique_source_drift")
    try:
        current_gate = build_strategy_advancement_gate(
            baseline=strategy_advancement_backtest_view(baseline_source),
            candidate=strategy_advancement_backtest_view(candidate_source),
            critique_evidence={
                "status": binding.get("critique_status"),
                "critique_id": binding.get("critique_id"),
                "artifact_fingerprint": (
                    content_fingerprint(critique_artifact)
                    if critique_artifact
                    else None
                ),
            },
        ).to_json_dict()
    except (TypeError, ValueError, OverflowError):
        current_gate = None
    if not is_valid_passed_strategy_advancement_gate(
        current_gate
    ) or content_fingerprint(current_gate) != content_fingerprint(comparison_gate):
        blockers.append("ai_shadow_strategy_advancement_gate_current_source_mismatch")
    if binding.get("candidate_fingerprint") != expected_candidate_fingerprint:
        blockers.append("ai_shadow_candidate_approval_fingerprint_mismatch")
    if readiness.get("schema_version") != (
        "karkinos.ai.shadow_research_promotion_readiness.v1"
    ):
        blockers.append("ai_shadow_readiness_schema_invalid")
    if readiness.get("candidate_id") != candidate_id:
        blockers.append("ai_shadow_readiness_candidate_mismatch")
    if readiness.get("critique_id") != binding.get("critique_id"):
        blockers.append("ai_shadow_readiness_critique_mismatch")
    if int(readiness.get("backtest_result_id") or 0) != int(
        binding.get("candidate_result_id") or 0
    ):
        blockers.append("ai_shadow_readiness_backtest_mismatch")
    if readiness.get("comparison_fingerprint") != content_fingerprint(comparison):
        blockers.append("ai_shadow_readiness_comparison_mismatch")
    if readiness.get("human_approval_id") != binding.get("promotion_id"):
        blockers.append("ai_shadow_readiness_human_approval_mismatch")
    readiness_gate = readiness.get("strategy_advancement_gate")
    if not is_valid_passed_strategy_advancement_gate(
        readiness_gate
    ) or content_fingerprint(readiness_gate) != content_fingerprint(comparison_gate):
        blockers.append("ai_shadow_readiness_strategy_advancement_gate_mismatch")
    if (
        readiness.get("promotion_status") != "promotable_for_paper_review"
        or readiness.get("is_promotable") is not True
        or readiness.get("missing_requirements") != []
    ):
        blockers.append("ai_shadow_readiness_not_promotable")
    if (
        readiness.get("live_like_enabled") is not False
        or readiness.get("broker_submission_enabled") is not False
    ):
        blockers.append("ai_shadow_readiness_authority_boundary_invalid")
    return list(dict.fromkeys(blockers))
