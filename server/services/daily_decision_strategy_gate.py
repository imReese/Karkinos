"""Persisted strategy gate binding for daily candidate evidence."""

from __future__ import annotations

from typing import Any

from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION,
    DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA_VERSION,
    DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA_VERSION,
)
from server.services.daily_decision_evidence_identity import fingerprint_json
from server.services.daily_decision_evidence_values import is_sha256, object_dict


def resolve_strategy_gate_binding(
    *,
    candidate: dict[str, Any],
    plan_date: str,
    expected_strategy_ref: str | None,
    expected_advancement_ref: str | None,
    expected_fee_review_ref: str | None,
    action_id: Any,
) -> tuple[dict[str, Any], list[str]]:
    return build_daily_candidate_strategy_gate_binding(
        candidate=candidate,
        plan_date=plan_date,
        expected_strategy_ref=expected_strategy_ref,
        expected_advancement_ref=expected_advancement_ref,
        expected_fee_review_ref=expected_fee_review_ref,
        action_id=action_id,
    )


def build_daily_candidate_strategy_gate_binding(
    *,
    candidate: dict[str, Any],
    plan_date: str,
    expected_strategy_ref: str | None,
    expected_advancement_ref: str | None,
    expected_fee_review_ref: str | None,
    action_id: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Build one replayable current-strategy binding for a daily ticket."""

    blockers: list[str] = []
    strategy = object_dict(object_dict(candidate.get("evidence")).get("strategy"))
    strategy_id = str(strategy.get("strategy_id") or "")
    if not strategy_id or expected_strategy_ref != f"strategy:{strategy_id}":
        blockers.append("strategy_identity_mismatch")
    gate = object_dict(strategy.get("order_generation_gate"))
    if gate.get("schema_version") != "karkinos.strategy_order_generation_gate.v1":
        blockers.append("strategy_order_generation_contract_invalid")
    if gate.get("status") != "pass" or gate.get("blockers") not in ([], None):
        blockers.append("strategy_order_generation_gate_not_pass")
    if str(gate.get("as_of_date") or "") != plan_date:
        blockers.append("strategy_order_generation_date_mismatch")
    expected_gate_boundaries = {
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "paper_shadow_evaluation_only": True,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
    }
    for field, expected in expected_gate_boundaries.items():
        if gate.get(field) is not expected:
            blockers.append(f"strategy_order_generation_{field}_invalid")

    promotion = object_dict(gate.get("promotion"))
    if promotion.get("status") != "pass":
        blockers.append("strategy_promotion_not_pass")
    if promotion.get("stage") != "paper_shadow":
        blockers.append("strategy_promotion_stage_invalid")
    if promotion.get("gate_status") != "paper_shadow_enabled":
        blockers.append("strategy_paper_shadow_gate_not_enabled")
    if promotion.get("live_like_enabled") is not False:
        blockers.append("strategy_live_like_boundary_invalid")
    if not str(promotion.get("human_reviewer") or "").strip():
        blockers.append("strategy_human_reviewer_missing")
    if promotion.get("human_review_note_recorded") is not True:
        blockers.append("strategy_human_review_note_missing")
    comparison_fingerprint = str(promotion.get("comparison_fingerprint") or "")
    if not is_sha256(comparison_fingerprint):
        blockers.append("strategy_comparison_fingerprint_invalid")
    human_approval_id = str(promotion.get("human_approval_id") or "")
    if not human_approval_id:
        blockers.append("strategy_human_approval_missing")
    daily_strategy_artifact_binding = object_dict(
        promotion.get("daily_strategy_artifact_binding")
    )
    strategy_operating_constraints: dict[str, Any] = {}
    if strategy_id.startswith("ai_formula_shadow:"):
        if daily_strategy_artifact_binding.get("schema_version") != (
            DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA_VERSION
        ):
            blockers.append("strategy_daily_artifact_binding_contract_invalid")
        for field in (
            "run_id",
            "market_date",
            "winner_candidate_id",
            "selection_id",
            "backup_id",
        ):
            if not str(daily_strategy_artifact_binding.get(field) or "").strip():
                blockers.append(f"strategy_daily_artifact_{field}_missing")
        for field in (
            "selection_fingerprint",
            "backup_artifact_fingerprint",
        ):
            if not is_sha256(daily_strategy_artifact_binding.get(field)):
                blockers.append(f"strategy_daily_artifact_{field}_invalid")
        if daily_strategy_artifact_binding.get("winner_candidate_id") != (
            strategy_id.removeprefix("ai_formula_shadow:")
        ):
            blockers.append("strategy_daily_artifact_candidate_mismatch")
        if (
            daily_strategy_artifact_binding.get("contains_private_account_identifiers")
            is not False
            or daily_strategy_artifact_binding.get("contains_broker_export_rows")
            is not False
            or daily_strategy_artifact_binding.get("does_not_change_capital_authority")
            is not True
            or daily_strategy_artifact_binding.get("authority_effect")
            != "research_only"
        ):
            blockers.append("strategy_daily_artifact_authority_boundary_invalid")
        strategy_operating_constraints = object_dict(
            daily_strategy_artifact_binding.get("operating_constraints")
        )
        blockers.extend(
            daily_candidate_strategy_operating_constraints_blockers(
                strategy_operating_constraints,
                expected_candidate_id=strategy_id.removeprefix("ai_formula_shadow:"),
                expected_backup_fingerprint=str(
                    daily_strategy_artifact_binding.get("backup_artifact_fingerprint")
                    or ""
                ),
            )
        )

    advancement_fingerprint = str(
        promotion.get("strategy_advancement_gate_fingerprint") or ""
    )
    if not is_sha256(advancement_fingerprint):
        blockers.append("strategy_advancement_fingerprint_invalid")
    if expected_advancement_ref != f"strategy_advancement:{advancement_fingerprint}":
        blockers.append("strategy_advancement_ref_mismatch")
    fee_binding = object_dict(promotion.get("fee_schedule_binding"))
    fee_review_fingerprint = str(
        fee_binding.get("fee_schedule_review_fingerprint") or ""
    )
    if not is_sha256(fee_review_fingerprint):
        blockers.append("reviewed_fee_schedule_fingerprint_invalid")
    if expected_fee_review_ref != (f"reviewed_fee_schedule:{fee_review_fingerprint}"):
        blockers.append("reviewed_fee_schedule_ref_mismatch")

    dataset_replay = object_dict(promotion.get("dataset_replay"))
    dataset_replay_fingerprint = str(dataset_replay.get("evidence_fingerprint") or "")
    if dataset_replay.get("status") != "pass" or dataset_replay.get("blockers") not in (
        [],
        None,
    ):
        blockers.append("strategy_frozen_dataset_replay_not_pass")
    if not is_sha256(dataset_replay_fingerprint):
        blockers.append("strategy_frozen_dataset_replay_fingerprint_invalid")
    if dataset_replay.get("persisted_market_bars_only") is not True:
        blockers.append("strategy_frozen_dataset_not_persisted_only")
    if dataset_replay.get("provider_contacted") is not False:
        blockers.append("strategy_frozen_dataset_provider_boundary_invalid")
    if dataset_replay.get("baseline_manifest_matches_candidate") is not True:
        blockers.append("strategy_frozen_dataset_baseline_mismatch")
    baseline_snapshot_id = str(dataset_replay.get("baseline_snapshot_id") or "")
    candidate_snapshot_id = str(dataset_replay.get("candidate_snapshot_id") or "")
    if not baseline_snapshot_id or not candidate_snapshot_id:
        blockers.append("strategy_frozen_dataset_snapshot_identity_missing")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        return {}, blockers
    binding = {
        "schema_version": DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION,
        "action_id": action_id,
        "strategy_ref": expected_strategy_ref,
        "strategy_advancement_ref": expected_advancement_ref,
        "reviewed_fee_schedule_ref": expected_fee_review_ref,
        "comparison_fingerprint": comparison_fingerprint,
        "human_approval_id": human_approval_id,
        "dataset_replay_fingerprint": dataset_replay_fingerprint,
        "baseline_snapshot_id": baseline_snapshot_id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "paper_shadow_evaluation_only": True,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    if daily_strategy_artifact_binding:
        binding["daily_strategy_artifact_binding"] = daily_strategy_artifact_binding
    if strategy_operating_constraints:
        binding["strategy_operating_constraints"] = strategy_operating_constraints
    return binding, []


def daily_candidate_strategy_operating_constraints_blockers(
    value: dict[str, Any],
    *,
    expected_candidate_id: str,
    expected_backup_fingerprint: str,
) -> list[str]:
    blockers: list[str] = []
    if value.get("schema_version") != (
        DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA_VERSION
    ):
        blockers.append("strategy_operating_constraints_contract_invalid")
    if value.get("candidate_id") != expected_candidate_id:
        blockers.append("strategy_operating_constraints_candidate_mismatch")
    if value.get("source_backup_artifact_fingerprint") != (expected_backup_fingerprint):
        blockers.append("strategy_operating_constraints_backup_mismatch")
    for field in (
        "strategy_artifact_fingerprint",
        "source_backup_artifact_fingerprint",
        "evidence_fingerprint",
    ):
        if not is_sha256(value.get(field)):
            blockers.append(f"strategy_operating_constraints_{field}_invalid")
    for field in ("economic_hypothesis", "risk_impact"):
        if not str(value.get(field) or "").strip():
            blockers.append(f"strategy_operating_constraints_{field}_missing")
    for field in (
        "failure_conditions",
        "limitations",
        "anti_lookahead_assumptions",
    ):
        items = value.get(field)
        if (
            not isinstance(items, list)
            or not items
            or any(not str(item).strip() for item in items)
        ):
            blockers.append(f"strategy_operating_constraints_{field}_invalid")
    expected_boundaries = {
        "automatic_enforcement_enabled": False,
        "human_review_required": True,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_boundaries.items():
        if value.get(field) is not expected:
            blockers.append(f"strategy_operating_constraints_{field}_invalid")
    stable = {key: item for key, item in value.items() if key != "evidence_fingerprint"}
    if value.get("evidence_fingerprint") != fingerprint_json(stable):
        blockers.append("strategy_operating_constraints_fingerprint_mismatch")
    return list(dict.fromkeys(blockers))
