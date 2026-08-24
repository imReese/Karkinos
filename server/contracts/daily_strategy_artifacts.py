"""Stable contracts for privacy-minimized daily strategy artifacts."""

from __future__ import annotations

DAILY_STRATEGY_SELECTION_SCHEMA = "karkinos.ai.daily_strategy_selection.v1"
DAILY_STRATEGY_BACKUP_SCHEMA = "karkinos.ai.daily_strategy_backup.v1"
DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA = "karkinos.ai.daily_strategy_backup_receipt.v1"
DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA = (
    "karkinos.ai.daily_strategy_promotion_binding.v2"
)
DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA = (
    "karkinos.ai.strategy_operating_constraints.v1"
)

COMPLETE_CANDIDATE_STATUSES = frozenset({"awaiting_human_approval", "research_blocked"})
DRAFT_BACKUP_FIELDS = (
    "draft_id",
    "economic_hypothesis",
    "risk_impact",
    "failure_conditions",
    "limitations",
    "anti_lookahead_assumptions",
    "formula_ast",
    "formula_fingerprint",
    "parameter_values",
    "parameter_ranges",
    "selected_universe",
    "dataset_snapshot_id",
    "test_window",
    "frequency",
    "cost_model_reference",
    "iteration_context",
    "iteration_context_fingerprint",
    "validation",
)


class DailyStrategyArtifactRejected(ValueError):
    """Fail-closed daily selection or backup rejection."""


class DailyStrategyBackupUnreadable(OSError):
    """The content-addressed backup could not be read as canonical JSON."""


class DailyStrategyBackupMismatch(ValueError):
    """The local backup no longer matches its persisted fingerprint."""


__all__ = [
    "COMPLETE_CANDIDATE_STATUSES",
    "DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA",
    "DAILY_STRATEGY_BACKUP_SCHEMA",
    "DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA",
    "DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA",
    "DAILY_STRATEGY_SELECTION_SCHEMA",
    "DRAFT_BACKUP_FIELDS",
    "DailyStrategyArtifactRejected",
    "DailyStrategyBackupMismatch",
    "DailyStrategyBackupUnreadable",
]
