"""Unified account-plan paper/shadow simulation orchestration.

Backward-compatible facade for server.services.account.paper_shadow.
"""

from __future__ import annotations

from server.services.account.paper_shadow import (
    decision_plan,
    orchestrate_account_paper_shadow,
)

__all__ = [
    "decision_plan",
    "orchestrate_account_paper_shadow",
]
