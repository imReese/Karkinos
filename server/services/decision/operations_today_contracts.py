"""Stable status sets for the read-only Operations projection."""

from __future__ import annotations

BLOCKING_MARKET_STATUSES = frozenset({"blocked", "error", "missing", "unavailable"})
DEGRADED_MARKET_STATUSES = frozenset({"partial", "stale", "estimated", "unknown"})
BLOCKING_ACCOUNT_STATUSES = frozenset({"blocked", "fail", "failed", "missing"})
PASS_STATUSES = frozenset({"pass", "passed", "live", "fresh", "complete", "healthy"})
STALE_ONLY_ACCOUNT_TRUTH_BLOCKERS = frozenset(
    {
        "account_truth_snapshot_stale",
        "account_truth_gate_not_pass:degraded",
    }
)
PAPER_SHADOW_MODE = "paper_shadow"
PAPER_SHADOW_SOURCE = "paper_shadow_daily"
