"""Persisted source loading for account-qualified strategy promotion."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_qualification import (
    MANUAL_QUALIFICATION_BACKUP,
    manual_qualification_source_id,
    qualification_source_binding,
)
from server.contracts.daily_strategy_artifacts import (
    DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA,
    DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA,
)
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)


def build_normalized_source_daily_strategy_artifact_binding(
    source_artifact: dict[str, Any],
) -> dict[str, Any]:
    """Adapt a verified normalized source into the downstream frozen binding."""

    strategy = _json_object(source_artifact.get("strategy"))
    economic_hypothesis = str(strategy.get("economic_hypothesis") or "").strip()
    risk_impact = str(strategy.get("risk_impact") or "").strip()
    failure_conditions = _nonempty_text_list(strategy.get("failure_conditions"))
    limitations = _nonempty_text_list(strategy.get("limitations"))
    anti_lookahead = _nonempty_text_list(strategy.get("anti_lookahead_assumptions"))
    candidate_id = str(source_artifact.get("candidate_id") or "")
    backup_fingerprint = str(source_artifact.get("backup_artifact_fingerprint") or "")
    strategy_fingerprint = str(
        source_artifact.get("strategy_artifact_fingerprint") or ""
    )
    identities = {
        "run_id": str(source_artifact.get("run_id") or ""),
        "market_date": str(source_artifact.get("market_date") or ""),
        "winner_candidate_id": candidate_id,
        "selection_id": str(source_artifact.get("selection_id") or ""),
        "selection_fingerprint": str(
            source_artifact.get("selection_fingerprint") or ""
        ),
        "backup_id": str(source_artifact.get("backup_id") or ""),
        "backup_artifact_fingerprint": backup_fingerprint,
    }
    if (
        not all(identities.values())
        or not economic_hypothesis
        or not risk_impact
        or not failure_conditions
        or not limitations
        or not anti_lookahead
        or content_fingerprint(strategy) != strategy_fingerprint
    ):
        raise ValueError("qualification_source_operating_constraints_incomplete")
    constraints_core = {
        "schema_version": DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA,
        "candidate_id": candidate_id,
        "strategy_artifact_fingerprint": strategy_fingerprint,
        "source_backup_artifact_fingerprint": backup_fingerprint,
        "economic_hypothesis": economic_hypothesis,
        "risk_impact": risk_impact,
        "failure_conditions": failure_conditions,
        "limitations": limitations,
        "anti_lookahead_assumptions": anti_lookahead,
        "automatic_enforcement_enabled": False,
        "human_review_required": True,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    return {
        "schema_version": DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA,
        **identities,
        "operating_constraints": {
            **constraints_core,
            "evidence_fingerprint": content_fingerprint(constraints_core),
        },
        "source_selection_status": "no_selection",
        "qualification_overlay_required": True,
        "contains_private_account_identifiers": False,
        "contains_broker_export_rows": False,
        "does_not_change_capital_authority": True,
        "authority_effect": "research_only",
    }


def load_qualification_sources(
    path: Path,
    normalized_id: str,
    *,
    proposed_qualification_approval: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Reopen the exact persisted source rows behind one qualified candidate."""

    store = ShadowResearchStore(path)
    qualification_candidate = store.get_qualification_candidate(normalized_id)
    qualification_run = store.get_qualification_run(
        str(qualification_candidate.get("qualification_run_id") or "")
    )
    qualification_approval = (
        dict(proposed_qualification_approval)
        if proposed_qualification_approval is not None
        else store.get_qualification_approval(normalized_id)
    )
    source_candidate_id = str(qualification_candidate.get("source_candidate_id") or "")
    manual_binding = qualification_source_binding(qualification_run)
    if manual_binding is not None:
        from server.persistence.strategy_research import StrategyResearchAuditStore
        from server.services.ai_shadow.ai_shadow_research_qualification_support import (
            freeze_manual_qualification_source,
        )

        frozen = freeze_manual_qualification_source(
            research_store=StrategyResearchAuditStore(path),
            source_binding=manual_binding,
        )
        source_candidate = frozen.source_candidate
        source_artifact = {
            **frozen.verified,
            "critique_artifact": frozen.source_critique["artifact"],
        }
        identity = manual_qualification_source_id(manual_binding)
        if (
            source_candidate_id != identity
            or qualification_run.get("source_run_id") != identity
            or qualification_run.get("source_selection_id")
            != manual_binding["manual_source_refs"]["session_id"]
            or qualification_run.get("source_selection_fingerprint")
            != frozen.source_selection.fingerprint
            or qualification_run.get("source_backup_fingerprint")
            != MANUAL_QUALIFICATION_BACKUP
            or qualification_source_binding(
                qualification_candidate.get("comparison") or {}
            )
            != manual_binding
        ):
            raise ValueError("qualification_manual_source_binding_changed")
        source_binding = {
            "source_kind": "manual_research",
            "source_binding": manual_binding,
            "strategy_artifact_fingerprint": source_artifact[
                "strategy_artifact_fingerprint"
            ],
        }
    else:
        artifacts = DailyStrategyArtifactStore(
            db_path=path,
            backup_root=path.parent / "strategy-research-backups",
        )
        source_candidate = store.get_candidate(source_candidate_id)
        for key in ("baseline_result_id", "candidate_result_id"):
            store.get_qualification_backtest_source(int(source_candidate.get(key) or 0))
        source_artifact = artifacts.require_verified_research_candidate(
            candidate_id=source_candidate_id,
            run_id=str(qualification_run.get("source_run_id") or ""),
        )
        source_binding = build_normalized_source_daily_strategy_artifact_binding(
            source_artifact
        )
    baseline_source = store.get_qualification_backtest_source(
        int(qualification_run.get("baseline_result_id") or 0)
    )
    candidate_source = store.get_qualification_backtest_source(
        int(qualification_candidate.get("candidate_result_id") or 0)
    )
    return (
        qualification_candidate,
        qualification_run,
        qualification_approval,
        source_candidate,
        source_artifact,
        baseline_source,
        candidate_source,
        source_binding,
    )


def _nonempty_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = [str(item).strip() for item in value]
    return normalized if normalized and all(normalized) else []


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


__all__ = [
    "build_normalized_source_daily_strategy_artifact_binding",
    "load_qualification_sources",
]
