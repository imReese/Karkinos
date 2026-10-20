"""Corporate action processing and scheduled dataset adjustment jobs.

Canonical module in server.services.research.
"""

from __future__ import annotations

from server.services.research.research_corporate_action_jobs import (
    CORPORATE_ACTION_DAY_JOB,
    DIVIDEND_DESCRIPTOR,
    CorporateActionDayService,
    ensure_dataset_corporate_actions,
    require_corporate_action_job_permission,
)

__all__ = [
    "CORPORATE_ACTION_DAY_JOB",
    "CorporateActionDayService",
    "DIVIDEND_DESCRIPTOR",
    "ensure_dataset_corporate_actions",
    "require_corporate_action_job_permission",
]
