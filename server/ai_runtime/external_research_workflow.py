"""Immutable workflow definition for human-started external research."""

from __future__ import annotations

from datetime import datetime, timezone

from server.contracts.external_research import (
    EXTERNAL_BACKTEST_REPORT_DEFINITION,
    EXTERNAL_BACKTEST_REPORT_ROLE,
    EXTERNAL_REPORT_STAGE_ID,
)

from .contracts import (
    ArtifactKind,
    StageDefinition,
    WorkflowDefinition,
    WorkflowStatus,
)

TERMINAL_WORKFLOW_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.PARTIAL,
        WorkflowStatus.FAILED,
        WorkflowStatus.BLOCKED,
    }
)


def external_report_workflow_definition(model_id: str) -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id=EXTERNAL_BACKTEST_REPORT_DEFINITION,
        name="Human-started external review of one saved backtest evidence record",
        stages=(
            StageDefinition(
                stage_id=EXTERNAL_REPORT_STAGE_ID,
                role_id=EXTERNAL_BACKTEST_REPORT_ROLE,
                model_id=model_id,
                output_kind=ArtifactKind.REPORT,
            ),
        ),
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "TERMINAL_WORKFLOW_STATUSES",
    "external_report_workflow_definition",
    "utc_now",
]
