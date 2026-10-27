"""Stateful strategy promotion pipeline."""

from __future__ import annotations

from typing import Any

from server.services.account.reviewed_fee_schedule import (
    active_review_matches_fee_evidence,
)
from server.services.research.strategy_promotion_support import (
    AI_SHADOW_STRATEGY_PREFIX,
    STRATEGY_PROMOTION_SCHEMA_VERSION,
    resolve_human_ai_shadow_strategy_promotion_binding,
)
from server.services.research.strategy_promotion_support import (
    ai_shadow_readiness_binding_blockers as _ai_shadow_readiness_binding_blockers,
)
from server.services.research.strategy_promotion_support import (
    int_or_none as _int_or_none,
)
from server.services.research.strategy_promotion_support import (
    is_promotable as _is_promotable,
)
from server.services.research.strategy_promotion_support import json_list as _json_list
from server.services.research.strategy_promotion_support import (
    json_object as _json_object,
)
from server.services.research.strategy_promotion_support import (
    lifecycle_metadata as _lifecycle_metadata,
)
from server.services.research.strategy_promotion_support import (
    missing_requirements as _missing_requirements,
)
from server.services.research.strategy_promotion_support import (
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
STRATEGY_REINSTATE_CONFIRMATION = (
    "reinstate_verified_strategy_to_paper_shadow_without_execution_or_capital_authority"
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
        if strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
            from server.services.research.research_final_evaluation import (
                require_new_publication_final_evaluation,
            )

            require_new_publication_final_evaluation(
                self._db,
                int(readiness.get("backtest_result_id") or 0),
                expected_candidate_id=strategy_id.removeprefix(
                    AI_SHADOW_STRATEGY_PREFIX
                ),
            )
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

    def evaluate_and_request_promotion(
        self,
        strategy_id: str,
        *,
        target_stage: str,
        readiness: dict[str, Any],
        actor: str,
        confirmation: str,
        review_note: str,
    ) -> dict[str, Any]:
        """Validate the human command before recording its readiness review."""
        if str(target_stage) == "paper_shadow":
            _validated_paper_shadow_review(
                strategy_id,
                readiness=readiness,
                actor=actor,
                confirmation=confirmation,
                review_note=review_note,
            )
            self.evaluate_readiness(readiness, actor=actor)
        return self.request_promotion(
            strategy_id,
            target_stage=target_stage,
            readiness=readiness,
            actor=actor,
            confirmation=confirmation,
            review_note=review_note,
        )

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
        normalized_actor, normalized_review_note = _validated_paper_shadow_review(
            strategy_id,
            readiness=readiness,
            actor=actor,
            confirmation=confirmation,
            review_note=review_note,
        )
        _require_ai_shadow_readiness_binding(self._db, readiness)
        if strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
            from server.services.research.research_final_evaluation import (
                require_new_publication_final_evaluation,
            )

            require_new_publication_final_evaluation(
                self._db,
                int(readiness.get("backtest_result_id") or 0),
                expected_candidate_id=strategy_id.removeprefix(
                    AI_SHADOW_STRATEGY_PREFIX
                ),
            )
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
        current_payload = _json_object(current.get("payload_json")) if current else {}
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
        if "readiness" in current_payload:
            payload["readiness"] = current_payload["readiness"]
        if "human_review" in current_payload:
            payload["historical_human_review"] = current_payload["human_review"]
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

    def reinstate_promoted_strategy(
        self,
        strategy_id: str,
        *,
        actor: str,
        reason: str,
        confirmation: str,
        readiness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reinstate a previously verified strategy back to paper_shadow.

        Ensures that when experimental challengers are withdrawn, the system can
        cleanly and safely fall back to an incumbent verified champion strategy
        without creating a void or bypassing advancement gates.
        """
        strategy_id = str(strategy_id or "").strip()
        if not strategy_id:
            raise ValueError("strategy_id is required")
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("reinstatement reason is required")
        normalized_actor = str(actor or "").strip()
        if not normalized_actor:
            raise ValueError("reinstatement reviewer is required")
        if normalized_actor.startswith(("automation:", "policy:")):
            raise ValueError("automated_decision_cannot_create_human_approval")
        if confirmation != STRATEGY_REINSTATE_CONFIRMATION:
            raise ValueError("reinstatement requires exact human confirmation")

        current = self._db.get_strategy_promotion_state_sync(strategy_id)
        if current is None:
            raise ValueError(
                f"cannot reinstate strategy {strategy_id}: no historical promotion record found"
            )
        from_stage = str(current["stage"])
        if from_stage == "paper_shadow":
            raise ValueError(f"strategy {strategy_id} is already in paper_shadow")

        current_payload = _json_object(current.get("payload_json"))
        effective_readiness = readiness or current_payload.get("readiness")
        if not isinstance(effective_readiness, dict):
            raise ValueError(
                f"cannot reinstate strategy {strategy_id}: missing verified readiness binding"
            )
        if strategy_id != _strategy_id(effective_readiness):
            raise ValueError("readiness strategy_id does not match promotion target")

        _require_ai_shadow_readiness_binding(self._db, effective_readiness)
        if strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
            from server.services.research.research_final_evaluation import (
                require_new_publication_final_evaluation,
            )

            require_new_publication_final_evaluation(
                self._db,
                int(effective_readiness.get("backtest_result_id") or 0),
                expected_candidate_id=strategy_id.removeprefix(
                    AI_SHADOW_STRATEGY_PREFIX
                ),
            )
        missing = _missing_requirements(effective_readiness)
        if missing or not _is_promotable(effective_readiness):
            raise ValueError(
                "missing readiness requirements for reinstatement: "
                + ", ".join(missing or ["unknown"])
            )
        payload = {
            "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
            "readiness": effective_readiness,
            "human_review": {
                "reviewer": normalized_actor,
                "review_note": f"Reinstated to paper_shadow: {reason}",
                "confirmation_recorded": True,
                "strategy_advancement_gate_fingerprint": (
                    _strategy_advancement_gate_fingerprint(effective_readiness)
                ),
            },
            "reinstatement": {
                "reinstated_by": normalized_actor,
                "reinstated_reason": reason,
                "reinstated_from_stage": from_stage,
            },
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_change_capital_authority": True,
        }
        if "human_review" in current_payload:
            payload["historical_human_review"] = current_payload["human_review"]
        state = self._db.upsert_strategy_promotion_state_sync(
            strategy_id=strategy_id,
            stage="paper_shadow",
            gate_status="paper_shadow_enabled",
            live_like_enabled=False,
            missing_requirements=[],
            backtest_result_id=_int_or_none(
                effective_readiness.get("backtest_result_id")
            ),
            payload=payload,
        )
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type="reinstated_to_paper_shadow",
            from_stage=from_stage,
            to_stage="paper_shadow",
            actor=normalized_actor,
            payload={
                "manual_confirmation_required": True,
                "manual_confirmation_recorded": True,
                "reviewer": normalized_actor,
                "review_note": f"Reinstated to paper_shadow: {reason}",
                "reinstated_from_stage": from_stage,
                "strategy_advancement_gate_fingerprint": (
                    _strategy_advancement_gate_fingerprint(effective_readiness)
                ),
                "live_like_enabled": False,
                "broker_submission_enabled": False,
                "does_not_change_capital_authority": True,
            },
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


def _validated_paper_shadow_review(
    strategy_id: str,
    *,
    readiness: dict[str, Any],
    actor: str,
    confirmation: str,
    review_note: str,
) -> tuple[str, str]:
    normalized_actor = str(actor or "").strip()
    if not normalized_actor:
        raise ValueError("paper/shadow promotion reviewer is required")
    if normalized_actor.startswith(("automation:", "policy:")):
        raise ValueError("automated_decision_cannot_create_human_approval")
    if confirmation != STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION:
        raise ValueError("paper/shadow promotion requires exact human confirmation")
    normalized_review_note = str(review_note or "").strip()
    if not normalized_review_note:
        raise ValueError("paper/shadow promotion review note is required")
    if strategy_id != _strategy_id(readiness):
        raise ValueError("readiness strategy_id does not match promotion target")
    return normalized_actor, normalized_review_note


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
    state_reader = getattr(db, "get_strategy_promotion_state_sync", None)
    state = state_reader(normalized_strategy_id) if callable(state_reader) else None
    state = state if isinstance(state, dict) else {}
    payload = _json_object(state.get("payload_json"))
    if payload.get("decision_source") == "policy":
        from server.services.decision.recommendation_publication import (
            resolve_policy_publication_binding,
        )

        return resolve_policy_publication_binding(db, state)
    return resolve_human_ai_shadow_strategy_promotion_binding(db, strategy_id)


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
        if not promotion.get("normalized_research"):
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
