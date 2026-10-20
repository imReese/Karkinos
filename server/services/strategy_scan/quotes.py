"""Clean domain interface for daily candidate quote freeze."""

from __future__ import annotations

from server.services.strategy_scan.daily_candidate_quote_freeze import (
    DAILY_CANDIDATE_QUOTE_FREEZE_SCHEMA_VERSION,
    DailyCandidateQuoteFreezeService,
)

__all__ = [
    "DAILY_CANDIDATE_QUOTE_FREEZE_SCHEMA_VERSION",
    "DailyCandidateQuoteFreezeService",
]
