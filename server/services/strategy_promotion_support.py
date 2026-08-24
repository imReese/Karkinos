"""Evidence adapters and value helpers for strategy promotion."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from analytics.dataset_snapshot import verify_backtest_dataset_snapshot_replay
from analytics.strategy_advancement_gate import (
    is_valid_passed_strategy_advancement_gate,
)
from server.ai_runtime.contracts import content_fingerprint
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
    build_daily_strategy_promotion_binding,
)

STRATEGY_PROMOTION_SCHEMA_VERSION = "karkinos.strategy_promotion_pipeline.v1"
AI_SHADOW_STRATEGY_PREFIX = "ai_formula_shadow:"
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
        return None


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


resolve_ai_shadow_daily_strategy_artifact_binding = (
    _resolve_ai_shadow_daily_strategy_artifact_binding
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
