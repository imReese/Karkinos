"""Evidence adapters and value helpers for strategy promotion."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from analytics.dataset_snapshot import verify_backtest_dataset_snapshot_replay
from analytics.normalized_research_gate import (
    build_normalized_research_advancement_gate,
    estimated_fee_evidence_valid,
    is_valid_passed_normalized_research_advancement_gate,
)
from analytics.research_account_capital_evidence import (
    is_valid_passed_research_account_capital_evidence,
)
from analytics.strategy_advancement_gate import (
    build_strategy_advancement_gate,
    is_valid_passed_strategy_advancement_gate,
    strategy_advancement_backtest_view,
)
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
)
from server.contracts.ai_shadow_research_qualification import (
    SHADOW_RESEARCH_QUALIFICATION_TARGET_STAGE,
    qualification_candidate_fingerprint,
    qualification_formula_semantic_fingerprint,
)
from server.contracts.daily_strategy_artifacts import (
    DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA,
)
from server.projections.valuation_snapshot import ledger_identity_from_rows
from server.services.account.reviewed_fee_schedule import (
    active_review_matches_fee_evidence,
)
from server.services.account.valuation_snapshot import valuation_snapshot_from_row
from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
    build_daily_strategy_promotion_binding,
)
from server.services.strategy_promotion_qualification_source import (
    build_normalized_source_daily_strategy_artifact_binding as _build_normalized_source_daily_strategy_artifact_binding,
)
from server.services.strategy_promotion_qualification_source import (
    load_qualification_sources,
)

STRATEGY_PROMOTION_SCHEMA_VERSION = "karkinos.strategy_promotion_pipeline.v1"
AI_SHADOW_STRATEGY_PREFIX = "ai_formula_shadow:"
AI_SHADOW_QUALIFICATION_READINESS_SCHEMA = (
    "karkinos.ai.shadow_research_qualification_promotion_readiness.v1"
)
AI_SHADOW_QUALIFICATION_BINDING_SCHEMA = (
    "karkinos.ai.shadow_research_qualification_promotion_binding.v1"
)
STRATEGY_PROMOTION_LIFECYCLE_STAGES = (
    "research",
    "paper_shadow",
    "shadow",
    "manual_confirmation",
    "controlled_bridge_pilot",
    "paused",
    "retired",
)


def _resolve_ai_shadow_daily_strategy_artifact_binding(
    db: Any,
    *,
    candidate_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    database_path = getattr(db, "_path", None)
    if database_path is None or not candidate_id or not run_id:
        return None
    path = Path(database_path)
    artifacts = DailyStrategyArtifactStore(
        db_path=path,
        backup_root=path.parent / "strategy-research-backups",
    )
    try:
        verified = artifacts.require_verified_winner(
            candidate_id=candidate_id,
            run_id=run_id,
        )
        return build_daily_strategy_promotion_binding(verified)
    except (DailyStrategyArtifactRejected, OSError, ValueError):
        try:
            verified_candidate = artifacts.require_verified_research_candidate(
                candidate_id=candidate_id,
                run_id=run_id,
            )
            return _build_normalized_source_daily_strategy_artifact_binding(
                verified_candidate
            )
        except (DailyStrategyArtifactRejected, OSError, ValueError):
            return None


def _qualification_source_candidate_matches(
    qualification_candidate: Mapping[str, Any],
    qualification_run: Mapping[str, Any],
    source_candidate: Mapping[str, Any],
    source_artifact: Mapping[str, Any],
    source_comparison: Mapping[str, Any],
) -> bool:
    """Bind the qualified formula back to its immutable normalized research source."""
    return (
        source_candidate.get("run_id") == qualification_run.get("source_run_id")
        and source_candidate.get("draft_id")
        == qualification_candidate.get("source_draft_id")
        and source_candidate.get("status") == "evaluated_research_only"
        and source_candidate.get("recommendation") == "formula_research_candidate"
        and source_comparison.get("research_capital_mode") == "normalized_notional"
        and source_comparison.get("account_qualification_status") == "not_evaluated"
        and content_fingerprint(source_comparison)
        == source_artifact.get("source_comparison_fingerprint")
    )


def _resolve_ai_shadow_qualification_promotion_evidence(
    db: Any,
    qualification_candidate_id: str,
    *,
    proposed_qualification_approval: Mapping[str, Any] | None = None,
    require_human_approval: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Re-open every persisted source behind one qualified paper/shadow winner."""

    database_path = getattr(db, "_path", None)
    normalized_id = str(qualification_candidate_id or "").strip()
    if database_path is None or not normalized_id:
        return {}, ["ai_shadow_qualification_candidate_identity_missing"]
    path = Path(database_path)
    try:
        (
            qualification_candidate,
            qualification_run,
            qualification_approval,
            source_candidate,
            source_artifact,
            baseline_source,
            candidate_source,
            daily_binding,
        ) = load_qualification_sources(
            path,
            normalized_id,
            proposed_qualification_approval=proposed_qualification_approval,
        )
    except (LookupError, OSError, TypeError, ValueError) as exc:
        return {}, [
            "ai_shadow_qualification_evidence_unavailable:" + type(exc).__name__
        ]

    blockers: list[str] = []
    source_candidate_id = str(qualification_candidate.get("source_candidate_id") or "")
    selection = _json_object(qualification_run.get("selection"))
    comparison = _json_object(qualification_candidate.get("comparison"))
    source_comparison = _json_object(source_candidate.get("comparison"))
    source_strategy = _json_object(source_artifact.get("strategy"))
    qualification_fingerprint = qualification_candidate_fingerprint(
        qualification_candidate
    )
    try:
        account_record = CanonicalEvidenceRepository(path).get(
            str(qualification_run.get("account_evidence_reference") or "")
        )
    except (LookupError, OSError, TypeError, ValueError):
        account_record = None
    if (
        account_record is None
        or account_record.tool_name != "account_state_projection.read"
        or account_record.status != "complete"
        or account_record.authoritative is not True
        or account_record.persisted_facts_only is not True
        or account_record.record_fingerprint
        != qualification_run.get("account_evidence_fingerprint")
        or account_record.valuation_snapshot_id
        != qualification_run.get("valuation_snapshot_id")
        or int(account_record.ledger_cutoff_id)
        != int(qualification_run.get("ledger_cutoff_id") or 0)
        or account_record.ledger_fingerprint
        != qualification_run.get("ledger_fingerprint")
    ):
        blockers.append("ai_shadow_qualification_account_evidence_drift")

    try:
        valuation_row = db.get_valuation_snapshot_sync(
            str(qualification_run.get("valuation_snapshot_id") or "")
        )
        valuation = (
            valuation_snapshot_from_row(dict(valuation_row))
            if isinstance(valuation_row, Mapping)
            else None
        )
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        valuation = None
    if (
        not isinstance(valuation, Mapping)
        or valuation.get("status") != "complete"
        or valuation.get("snapshot_id")
        != qualification_run.get("valuation_snapshot_id")
        or valuation.get("ledger_fingerprint")
        != qualification_run.get("ledger_fingerprint")
        or int(valuation.get("ledger_cutoff_id") or 0)
        != int(qualification_run.get("ledger_cutoff_id") or 0)
    ):
        blockers.append("ai_shadow_qualification_valuation_identity_drift")
    try:
        cutoff = int(qualification_run.get("ledger_cutoff_id") or 0)
        ledger_rows = [
            dict(row)
            for row in db.get_all_ledger_entries_sync()
            if int(row.get("id") or 0) <= cutoff
        ]
        ledger_identity = ledger_identity_from_rows(ledger_rows)
    except (AttributeError, TypeError, ValueError):
        ledger_identity = {}
    if int(ledger_identity.get("ledger_cutoff_id") or 0) != int(
        qualification_run.get("ledger_cutoff_id") or 0
    ) or ledger_identity.get("ledger_fingerprint") != qualification_run.get(
        "ledger_fingerprint"
    ):
        blockers.append("ai_shadow_qualification_ledger_identity_drift")
    if (
        qualification_run.get("status") != "completed"
        or selection.get("status") != "winner_selected"
        or selection.get("winner_qualification_candidate_id") != normalized_id
    ):
        blockers.append("ai_shadow_qualification_winner_not_completed")
    if (
        qualification_candidate.get("status") != "qualified"
        or qualification_candidate.get("recommendation") != "paper_shadow_review"
    ):
        blockers.append("ai_shadow_qualification_candidate_not_approvable")
    if require_human_approval and (
        not isinstance(qualification_approval, dict)
        or qualification_approval.get("qualification_candidate_id") != normalized_id
        or qualification_approval.get("qualification_run_id")
        != qualification_candidate.get("qualification_run_id")
        or qualification_approval.get("target_stage")
        != SHADOW_RESEARCH_QUALIFICATION_TARGET_STAGE
        or qualification_approval.get("qualification_candidate_fingerprint")
        != qualification_fingerprint
        or qualification_approval.get("manual_confirmation_recorded") is not True
    ):
        blockers.append("ai_shadow_qualification_human_approval_invalid")
    from server.contracts.recommendation_publication import legacy_automated_approval

    if require_human_approval and legacy_automated_approval(qualification_approval):
        blockers.append(
            "ai_shadow_qualification_automated_record_is_not_human_approval"
        )
    if not require_human_approval:
        qualification_approval = None
    if not _qualification_source_candidate_matches(
        qualification_candidate,
        qualification_run,
        source_candidate,
        source_artifact,
        source_comparison,
    ):
        blockers.append("ai_shadow_qualification_source_candidate_drift")
    try:
        current_source_semantic_fingerprint = (
            qualification_formula_semantic_fingerprint(source_strategy)
        )
    except ValueError:
        current_source_semantic_fingerprint = None
    if (
        source_artifact.get("candidate_id") != source_candidate_id
        or source_artifact.get("draft_id")
        != qualification_candidate.get("source_draft_id")
        or source_artifact.get("formula_fingerprint")
        != qualification_candidate.get("source_formula_fingerprint")
        or source_strategy.get("formula_fingerprint")
        != qualification_candidate.get("source_formula_fingerprint")
        or current_source_semantic_fingerprint
        != qualification_candidate.get("source_formula_semantic_fingerprint")
        or current_source_semantic_fingerprint
        != qualification_candidate.get("qualified_formula_semantic_fingerprint")
    ):
        blockers.append("ai_shadow_qualification_source_formula_drift")

    baseline_fingerprint = content_fingerprint(baseline_source)
    candidate_fingerprint = content_fingerprint(candidate_source)
    candidate_metrics = _json_object(candidate_source.get("metrics"))
    candidate_dataset = _json_object(candidate_metrics.get("dataset_snapshot"))
    if (
        comparison.get("research_capital_mode") != "account_bound"
        or comparison.get("account_qualification_status") != "passed"
        or comparison.get("baseline_source_fingerprint") != baseline_fingerprint
        or comparison.get("candidate_source_fingerprint") != candidate_fingerprint
    ):
        blockers.append("ai_shadow_qualification_backtest_comparison_drift")
    if candidate_metrics.get("formula_fingerprint") != qualification_candidate.get(
        "qualified_formula_fingerprint"
    ) or candidate_dataset.get("snapshot_id") != source_artifact.get(
        "dataset_snapshot_id"
    ):
        blockers.append("ai_shadow_qualification_backtest_formula_or_dataset_drift")

    critique = _json_object(source_comparison.get("deepseek_critique"))
    try:
        current_gate = build_strategy_advancement_gate(
            baseline=strategy_advancement_backtest_view(baseline_source),
            candidate=strategy_advancement_backtest_view(candidate_source),
            critique_evidence={
                "status": "completed" if critique else "missing",
                "critique_id": source_candidate.get("critique_id"),
                "artifact_fingerprint": (
                    content_fingerprint(critique) if critique else None
                ),
            },
        ).to_json_dict()
    except (TypeError, ValueError, OverflowError):
        current_gate = {}
    comparison_gate = _json_object(comparison.get("promotion_gate"))
    if not is_valid_passed_strategy_advancement_gate(
        current_gate
    ) or content_fingerprint(current_gate) != content_fingerprint(comparison_gate):
        blockers.append("ai_shadow_qualification_advancement_gate_drift")

    fee_evidence = _json_object(candidate_metrics.get("fee_component_evidence"))
    fee_schedule_binding = {
        "fee_schedule_fingerprint": fee_evidence.get("fee_schedule_fingerprint"),
        **_json_object(fee_evidence.get("fee_schedule_binding")),
    }
    if fee_evidence.get("cost_model_reference") != qualification_run.get(
        "reviewed_cost_model_reference"
    ) or fee_evidence.get("fee_schedule_fingerprint") != qualification_run.get(
        "reviewed_fee_schedule_fingerprint"
    ):
        blockers.append("ai_shadow_qualification_reviewed_fee_binding_drift")
    blockers.extend(
        f"ai_shadow_qualification_{blocker}"
        for blocker in active_review_matches_fee_evidence(db, fee_schedule_binding)
    )

    capital_evidence = _json_object(candidate_metrics.get("account_capital_constraint"))
    if (
        not is_valid_passed_research_account_capital_evidence(
            capital_evidence,
            expected_initial_cash=qualification_run.get("initial_cash_text"),
            expected_valuation_snapshot_id=qualification_run.get(
                "valuation_snapshot_id"
            ),
            expected_ledger_cutoff_id=qualification_run.get("ledger_cutoff_id"),
        )
        or capital_evidence.get("account_state_record_fingerprint")
        != qualification_run.get("account_evidence_fingerprint")
        or capital_evidence.get("account_truth_source_fingerprint")
        != qualification_run.get("account_truth_source_fingerprint")
        or capital_evidence.get("account_truth_scope_fingerprint")
        != qualification_run.get("account_truth_scope_fingerprint")
    ):
        blockers.append("ai_shadow_qualification_account_truth_binding_drift")

    replay_binding = {
        "baseline_metrics_json": baseline_source["metrics"],
        "candidate_metrics_json": candidate_source["metrics"],
    }
    dataset_replay = _dataset_replay_evidence_from_binding(db, replay_binding)
    if dataset_replay.get("status") != "pass":
        blockers.append("ai_shadow_qualification_dataset_replay_not_reproducible")

    qualification_binding_core = {
        "schema_version": AI_SHADOW_QUALIFICATION_BINDING_SCHEMA,
        "qualification_run_id": qualification_run.get("qualification_run_id"),
        "qualification_candidate_id": normalized_id,
        "qualification_approval_id": (
            qualification_approval.get("qualification_approval_id")
            if isinstance(qualification_approval, dict)
            else None
        ),
        "qualification_candidate_fingerprint": qualification_fingerprint,
        "qualification_input_fingerprint": qualification_run.get("input_fingerprint"),
        "qualification_selection_fingerprint": qualification_run.get(
            "selection_fingerprint"
        ),
        "source_run_id": qualification_run.get("source_run_id"),
        "source_candidate_id": source_candidate_id,
        "source_draft_id": qualification_candidate.get("source_draft_id"),
        "source_selection_id": qualification_run.get("source_selection_id"),
        "source_selection_fingerprint": qualification_run.get(
            "source_selection_fingerprint"
        ),
        "source_backup_fingerprint": qualification_run.get("source_backup_fingerprint"),
        "source_artifact_fingerprint": source_artifact.get("evidence_fingerprint"),
        "source_comparison_fingerprint": source_artifact.get(
            "source_comparison_fingerprint"
        ),
        "source_formula_fingerprint": qualification_candidate.get(
            "source_formula_fingerprint"
        ),
        "qualified_formula_fingerprint": qualification_candidate.get(
            "qualified_formula_fingerprint"
        ),
        "formula_semantic_fingerprint": current_source_semantic_fingerprint,
        "baseline_result_id": qualification_run.get("baseline_result_id"),
        "candidate_result_id": qualification_candidate.get("candidate_result_id"),
        "baseline_source_fingerprint": baseline_fingerprint,
        "candidate_source_fingerprint": candidate_fingerprint,
        "comparison_fingerprint": qualification_candidate.get("comparison_fingerprint"),
        "strategy_advancement_gate_fingerprint": current_gate.get(
            "evidence_fingerprint"
        ),
        "dataset_snapshot_id": source_artifact.get("dataset_snapshot_id"),
        "dataset_replay_fingerprint": dataset_replay.get("evidence_fingerprint"),
        "valuation_snapshot_id": qualification_run.get("valuation_snapshot_id"),
        "valuation_snapshot_fingerprint": qualification_run.get(
            "valuation_snapshot_fingerprint"
        ),
        "ledger_cutoff_id": qualification_run.get("ledger_cutoff_id"),
        "ledger_fingerprint": qualification_run.get("ledger_fingerprint"),
        "account_evidence_fingerprint": qualification_run.get(
            "account_evidence_fingerprint"
        ),
        "account_truth_source_fingerprint": qualification_run.get(
            "account_truth_source_fingerprint"
        ),
        "account_truth_scope_fingerprint": qualification_run.get(
            "account_truth_scope_fingerprint"
        ),
        "reviewed_cost_model_reference": qualification_run.get(
            "reviewed_cost_model_reference"
        ),
        "reviewed_fee_schedule_fingerprint": qualification_run.get(
            "reviewed_fee_schedule_fingerprint"
        ),
        "contains_private_account_values": False,
        "contains_account_reference": False,
        "contains_private_comparison": False,
        "provider_contact_performed": False,
        "paper_shadow_only": True,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
    }
    qualification_binding = {
        **qualification_binding_core,
        "evidence_fingerprint": content_fingerprint(qualification_binding_core),
    }
    blockers = list(dict.fromkeys(blockers))
    return {
        "status": "pass" if not blockers else "blocked",
        "source_candidate_id": source_candidate_id,
        "qualification_candidate_id": normalized_id,
        "qualification_run_id": qualification_run.get("qualification_run_id"),
        "qualification_approval_id": qualification_binding.get(
            "qualification_approval_id"
        ),
        "backtest_result_id": qualification_candidate.get("candidate_result_id"),
        "comparison_fingerprint": qualification_candidate.get("comparison_fingerprint"),
        "strategy_advancement_gate": current_gate,
        "daily_strategy_artifact_binding": daily_binding,
        "qualification_binding": qualification_binding,
        "fee_schedule_binding": fee_schedule_binding,
        "dataset_replay": dataset_replay,
        "blockers": blockers,
    }, blockers


def _ai_shadow_qualification_readiness_binding_blockers(
    db: Any,
    readiness: dict[str, Any],
) -> list[str]:
    qualification_candidate_id = str(
        readiness.get("qualification_candidate_id") or ""
    ).strip()
    evidence, blockers = _resolve_ai_shadow_qualification_promotion_evidence(
        db,
        qualification_candidate_id,
    )
    blockers = list(blockers)
    source_candidate_id = str(evidence.get("source_candidate_id") or "")
    expected_strategy_id = AI_SHADOW_STRATEGY_PREFIX + source_candidate_id
    exact_matches = (
        ("strategy_id", expected_strategy_id, "strategy_identity"),
        ("candidate_id", source_candidate_id, "source_candidate"),
        ("qualification_run_id", evidence.get("qualification_run_id"), "run"),
        (
            "qualification_binding",
            evidence.get("qualification_binding"),
            "binding",
        ),
        (
            "daily_strategy_artifact_binding",
            evidence.get("daily_strategy_artifact_binding"),
            "source_artifact_binding",
        ),
        (
            "comparison_fingerprint",
            evidence.get("comparison_fingerprint"),
            "comparison",
        ),
        (
            "human_approval_id",
            evidence.get("qualification_approval_id"),
            "human_approval",
        ),
    )
    if readiness.get("schema_version") != AI_SHADOW_QUALIFICATION_READINESS_SCHEMA:
        blockers.append("ai_shadow_qualification_readiness_schema_invalid")
    if not qualification_candidate_id:
        blockers.append("ai_shadow_qualification_candidate_identity_missing")
    for field, expected, blocker_name in exact_matches:
        if readiness.get(field) != expected:
            blockers.append(f"ai_shadow_qualification_{blocker_name}_mismatch")
    if int(readiness.get("backtest_result_id") or 0) != int(
        evidence.get("backtest_result_id") or 0
    ):
        blockers.append("ai_shadow_qualification_backtest_mismatch")
    readiness_gate = _json_object(readiness.get("strategy_advancement_gate"))
    evidence_gate = _json_object(evidence.get("strategy_advancement_gate"))
    if not is_valid_passed_strategy_advancement_gate(
        readiness_gate
    ) or content_fingerprint(readiness_gate) != content_fingerprint(evidence_gate):
        blockers.append("ai_shadow_qualification_advancement_gate_mismatch")
    if (
        readiness.get("promotion_status") != "promotable_for_paper_review"
        or readiness.get("is_promotable") is not True
        or readiness.get("missing_requirements") != []
    ):
        blockers.append("ai_shadow_qualification_readiness_not_promotable")
    if (
        readiness.get("live_like_enabled") is not False
        or readiness.get("broker_submission_enabled") is not False
        or readiness.get("does_not_create_order") is not True
        or readiness.get("does_not_authorize_execution") is not True
        or readiness.get("does_not_change_capital_authority") is not True
    ):
        blockers.append("ai_shadow_qualification_authority_boundary_invalid")
    return list(dict.fromkeys(blockers))


def _ai_shadow_fee_schedule_binding(db: Any, candidate_id: str) -> dict[str, Any]:
    reader = getattr(db, "get_ai_shadow_strategy_promotion_binding_sync", None)
    binding = reader(candidate_id) if callable(reader) and candidate_id else None
    if not isinstance(binding, dict):
        return {}
    metrics = _json_object(binding.get("candidate_metrics_json"))
    fee_evidence = _json_object(metrics.get("fee_component_evidence"))
    schedule_binding = _json_object(fee_evidence.get("fee_schedule_binding"))
    return {
        "fee_schedule_fingerprint": fee_evidence.get("fee_schedule_fingerprint"),
        **schedule_binding,
    }


def _ai_shadow_dataset_replay_evidence(
    db: Any,
    candidate_id: str,
) -> dict[str, Any]:
    reader = getattr(db, "get_ai_shadow_strategy_promotion_binding_sync", None)
    binding = reader(candidate_id) if callable(reader) and candidate_id else None
    if not isinstance(binding, dict):
        return _missing_dataset_replay_evidence("dataset_replay_binding_missing")
    return _dataset_replay_evidence_from_binding(db, binding)


def _dataset_replay_evidence_from_binding(
    db: Any,
    binding: dict[str, Any],
) -> dict[str, Any]:
    baseline_metrics = _json_object(binding.get("baseline_metrics_json"))
    candidate_metrics = _json_object(binding.get("candidate_metrics_json"))
    baseline_snapshot = _json_object(baseline_metrics.get("dataset_snapshot"))
    candidate_snapshot = _json_object(candidate_metrics.get("dataset_snapshot"))
    root = _strategy_dataset_store_root(db)
    if root is None:
        return _missing_dataset_replay_evidence("dataset_replay_store_root_missing")
    replay = verify_backtest_dataset_snapshot_replay(
        candidate_snapshot,
        store_root=root,
        research_root=(
            Path(db.path).resolve().parent / "research"
            if getattr(db, "path", None) is not None
            else None
        ),
    )
    replay_core = dict(replay)
    replay_core.pop("evidence_fingerprint", None)
    manifest_matches = bool(baseline_snapshot) and content_fingerprint(
        baseline_snapshot
    ) == content_fingerprint(candidate_snapshot)
    blockers = list(replay_core.get("blockers") or [])
    if not manifest_matches:
        blockers.append("baseline_candidate_dataset_manifest_mismatch")
    replay_core.update(
        {
            "status": "pass" if not blockers else "blocked",
            "blockers": list(dict.fromkeys(blockers)),
            "baseline_manifest_matches_candidate": manifest_matches,
            "baseline_snapshot_id": baseline_snapshot.get("snapshot_id"),
            "candidate_snapshot_id": candidate_snapshot.get("snapshot_id"),
        }
    )
    return {
        **replay_core,
        "evidence_fingerprint": content_fingerprint(replay_core),
    }


def _strategy_dataset_store_root(db: Any) -> Path | None:
    configured = str(os.environ.get("KARKINOS_DATA_DIR") or "").strip()
    if configured:
        return Path(configured)
    database_path = getattr(db, "_path", None)
    if database_path is None:
        return None
    return Path(database_path).parent


def _missing_dataset_replay_evidence(blocker: str) -> dict[str, Any]:
    core = {
        "schema_version": "karkinos.dataset_snapshot_replay.v1",
        "status": "blocked",
        "snapshot_id": None,
        "manifest_symbol_count": 0,
        "verified_symbol_count": 0,
        "blockers": [blocker],
        "persisted_market_bars_only": True,
        "parquet_fallback_used": False,
        "provider_contacted": False,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def _binding_backtest_source(binding: dict[str, Any], prefix: str) -> dict[str, Any]:
    result_id = binding.get(
        "baseline_result_id" if prefix == "baseline" else "candidate_result_id"
    )
    return {
        "id": int(result_id or 0),
        "initial_cash": binding.get(f"{prefix}_initial_cash"),
        "final_equity": binding.get(f"{prefix}_final_equity"),
        "total_return": binding.get(f"{prefix}_total_return"),
        "sharpe": binding.get(f"{prefix}_sharpe"),
        "max_drawdown": binding.get(f"{prefix}_max_drawdown"),
        "equity_curve": _json_list(binding.get(f"{prefix}_equity_curve_json")),
        "metrics": _json_object(binding.get(f"{prefix}_metrics_json")),
        "cost_summary": _json_object(binding.get(f"{prefix}_cost_summary_json")),
    }


def _missing_requirements(readiness: dict[str, Any]) -> list[str]:
    value = readiness.get("missing_requirements") or []
    missing = [str(item) for item in value]
    strategy_id = str(readiness.get("strategy_id") or "").strip()
    if not strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
        if not is_valid_passed_strategy_advancement_gate(
            _strategy_advancement_gate(readiness)
        ):
            missing.append("strategy_advancement_gate_not_passed")
        missing.append("evidence_owned_candidate_approval_missing")
    return list(dict.fromkeys(missing))


def _strategy_advancement_gate(readiness: dict[str, Any]) -> Any:
    return readiness.get("strategy_advancement_gate") or readiness.get("promotion_gate")


def _strategy_advancement_gate_fingerprint(readiness: dict[str, Any]) -> str | None:
    gate = _strategy_advancement_gate(readiness)
    if not isinstance(gate, dict):
        return None
    fingerprint = str(gate.get("evidence_fingerprint") or "").strip()
    return fingerprint or None


def _is_promotable(readiness: dict[str, Any]) -> bool:
    return bool(readiness.get("is_promotable")) and not _missing_requirements(readiness)


def _lifecycle_metadata(stage: str) -> dict[str, Any]:
    return {
        "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
        "stage": stage,
        "supported_stages": list(STRATEGY_PROMOTION_LIFECYCLE_STAGES),
        "audit_only": True,
        "does_not_authorize_execution": True,
        "broker_submission_enabled": False,
        "manual_confirmation_required_for_live_like": True,
        "disabled_stages": ["controlled_bridge_pilot", "live_like"],
        "terminal": stage == "retired",
        "allowed_operator_actions": _allowed_lifecycle_actions(stage),
    }


def _allowed_lifecycle_actions(stage: str) -> list[str]:
    if stage == "retired":
        return ["review_history"]
    if stage == "paused":
        return ["review_readiness", "retire"]
    return ["review_readiness", "pause", "retire"]


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in {None, ""}:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in {None, ""}:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resolve_human_ai_shadow_strategy_promotion_binding(
    db: Any,
    strategy_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """Re-open a human-approved strategy against its canonical approval facts."""

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
    from server.contracts.recommendation_publication import legacy_automated_approval

    if legacy_automated_approval(human_review):
        return {
            "status": "blocked",
            "strategy_id": normalized_strategy_id,
            "decision_source": "legacy_ungranted",
        }, ["legacy_automated_publication_has_no_grant"]
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
    qualification_candidate_id = str(
        readiness.get("qualification_candidate_id") or ""
    ).strip()
    qualification_evidence: dict[str, Any] = {}
    if qualification_candidate_id:
        qualification_evidence, _ = _resolve_ai_shadow_qualification_promotion_evidence(
            db,
            qualification_candidate_id,
        )
    fee_schedule_binding = (
        _json_object(qualification_evidence.get("fee_schedule_binding"))
        if qualification_candidate_id
        else _ai_shadow_fee_schedule_binding(db, candidate_id)
    )
    dataset_replay = (
        _json_object(qualification_evidence.get("dataset_replay"))
        if qualification_candidate_id
        else _ai_shadow_dataset_replay_evidence(db, candidate_id)
    )
    daily_strategy_artifact_binding = readiness.get("daily_strategy_artifact_binding")
    daily_strategy_artifact_binding = (
        dict(daily_strategy_artifact_binding)
        if isinstance(daily_strategy_artifact_binding, dict)
        else {}
    )
    reader = getattr(db, "get_ai_shadow_strategy_promotion_binding_sync", None)
    raw_binding = reader(candidate_id) if callable(reader) and candidate_id else None
    if human_review.get("forward_review") is not None:
        from server.services.decision.forward_paper_review import (
            verify_forward_paper_review,
        )

        try:
            verify_forward_paper_review(
                db,
                human_review["forward_review"],
                source_result_id=int(
                    (raw_binding or {}).get("candidate_result_id") or 0
                ),
                exact_current=False,
            )
        except (ValueError, LookupError, TypeError, KeyError):
            blockers.append("ai_shadow_strategy_forward_review_binding_invalid")
    normalized_research = (
        isinstance(raw_binding, dict)
        and raw_binding.get("research_run_capital_mode")
        == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
    )
    return {
        "status": "pass" if not blockers else "blocked",
        "decision_source": "human",
        "strategy_id": normalized_strategy_id,
        "candidate_id": candidate_id,
        "stage": state.get("stage"),
        "gate_status": state.get("gate_status"),
        "backtest_result_id": state.get("backtest_result_id"),
        "comparison_fingerprint": readiness.get("comparison_fingerprint"),
        "human_approval_id": readiness.get("human_approval_id"),
        "qualification_candidate_id": qualification_candidate_id or None,
        "qualification_run_id": readiness.get("qualification_run_id"),
        "qualification_binding": _json_object(readiness.get("qualification_binding")),
        "human_reviewer": human_review.get("reviewer"),
        "forward_review": human_review.get("forward_review"),
        "human_review_note_recorded": bool(
            str(human_review.get("review_note") or "").strip()
        ),
        "strategy_advancement_gate_fingerprint": gate_fingerprint,
        "daily_strategy_artifact_binding": daily_strategy_artifact_binding,
        "fee_schedule_binding": fee_schedule_binding,
        "dataset_replay": dataset_replay,
        "live_like_enabled": bool(state.get("live_like_enabled")),
        "normalized_research": normalized_research,
    }, blockers


def _ai_shadow_readiness_binding_blockers(
    db: Any,
    readiness: dict[str, Any],
) -> list[str]:
    strategy_id = str(readiness.get("strategy_id") or "").strip()
    if not strategy_id.startswith(AI_SHADOW_STRATEGY_PREFIX):
        return []
    if (
        readiness.get("schema_version") == AI_SHADOW_QUALIFICATION_READINESS_SCHEMA
        or str(readiness.get("qualification_candidate_id") or "").strip()
    ):
        return _ai_shadow_qualification_readiness_binding_blockers(db, readiness)
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
    normalized_research = (
        binding.get("research_run_capital_mode")
        == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
    )
    if normalized_research:
        if not is_valid_passed_normalized_research_advancement_gate(comparison_gate):
            blockers.append("ai_shadow_strategy_advancement_gate_invalid")
    else:
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
    if not normalized_research:
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
    else:
        if not estimated_fee_evidence_valid(
            strategy_advancement_backtest_view(candidate_source)
        ):
            blockers.append("ai_shadow_candidate_estimated_fee_evidence_invalid")
    if (
        binding.get("research_run_status") != "completed"
        or int(binding.get("research_run_baseline_result_id") or 0)
        != int(binding.get("baseline_result_id") or 0)
        or binding.get("research_run_session_id") != binding.get("session_id")
    ):
        blockers.append("ai_shadow_research_run_binding_drift")
    if not normalized_research:
        research_context_id = str(binding.get("research_run_context_id") or "").strip()
        research_valuation_id = str(
            binding.get("research_run_valuation_snapshot_id") or ""
        ).strip()
        if (
            binding.get("research_run_capital_mode")
            != SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND
            or not research_context_id
            or research_context_id != research_valuation_id
            or int(binding.get("research_run_ledger_cutoff_id") or 0) <= 0
        ):
            blockers.append("ai_shadow_research_context_not_account_bound")
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
        or (
            not normalized_research
            and binding.get("formula_backtest_cost_model_reference")
            != candidate_fee_evidence.get("cost_model_reference")
        )
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
    critique_evidence = {
        "status": binding.get("critique_status"),
        "critique_id": binding.get("critique_id"),
        "artifact_fingerprint": (
            content_fingerprint(critique_artifact) if critique_artifact else None
        ),
    }
    if normalized_research:
        try:
            current_gate = build_normalized_research_advancement_gate(
                baseline=strategy_advancement_backtest_view(baseline_source),
                candidate=strategy_advancement_backtest_view(candidate_source),
                critique_evidence=critique_evidence,
            ).to_json_dict()
        except (TypeError, ValueError, OverflowError):
            current_gate = None
        if not is_valid_passed_normalized_research_advancement_gate(
            current_gate
        ) or content_fingerprint(current_gate) != content_fingerprint(comparison_gate):
            blockers.append(
                "ai_shadow_strategy_advancement_gate_current_source_mismatch"
            )
    else:
        try:
            current_gate = build_strategy_advancement_gate(
                baseline=strategy_advancement_backtest_view(baseline_source),
                candidate=strategy_advancement_backtest_view(candidate_source),
                critique_evidence=critique_evidence,
            ).to_json_dict()
        except (TypeError, ValueError, OverflowError):
            current_gate = None
        if not is_valid_passed_strategy_advancement_gate(
            current_gate
        ) or content_fingerprint(current_gate) != content_fingerprint(comparison_gate):
            blockers.append(
                "ai_shadow_strategy_advancement_gate_current_source_mismatch"
            )
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
    if normalized_research:
        if not is_valid_passed_normalized_research_advancement_gate(
            readiness_gate
        ) or content_fingerprint(readiness_gate) != content_fingerprint(
            comparison_gate
        ):
            blockers.append("ai_shadow_readiness_strategy_advancement_gate_mismatch")
    else:
        if not is_valid_passed_strategy_advancement_gate(
            readiness_gate
        ) or content_fingerprint(readiness_gate) != content_fingerprint(
            comparison_gate
        ):
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


resolve_ai_shadow_daily_strategy_artifact_binding = (
    _resolve_ai_shadow_daily_strategy_artifact_binding
)
build_normalized_source_daily_strategy_artifact_binding = (
    _build_normalized_source_daily_strategy_artifact_binding
)
resolve_ai_shadow_qualification_promotion_evidence = (
    _resolve_ai_shadow_qualification_promotion_evidence
)
ai_shadow_qualification_readiness_binding_blockers = (
    _ai_shadow_qualification_readiness_binding_blockers
)
ai_shadow_fee_schedule_binding = _ai_shadow_fee_schedule_binding
ai_shadow_dataset_replay_evidence = _ai_shadow_dataset_replay_evidence
dataset_replay_evidence_from_binding = _dataset_replay_evidence_from_binding
strategy_dataset_store_root = _strategy_dataset_store_root
missing_dataset_replay_evidence = _missing_dataset_replay_evidence
binding_backtest_source = _binding_backtest_source
missing_requirements = _missing_requirements
strategy_advancement_gate = _strategy_advancement_gate
strategy_advancement_gate_fingerprint = _strategy_advancement_gate_fingerprint
is_promotable = _is_promotable
lifecycle_metadata = _lifecycle_metadata
allowed_lifecycle_actions = _allowed_lifecycle_actions
int_or_none = _int_or_none
json_list = _json_list
json_object = _json_object

ai_shadow_readiness_binding_blockers = _ai_shadow_readiness_binding_blockers
