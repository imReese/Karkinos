"""Service composition and runtime adapter wiring for daily decision evidence.

Canonical subpackage module in server.services.decision.evidence.
"""

from __future__ import annotations

from server.services.decision.daily_decision_evidence_composition import (
    bind_promoted_strategy_scan,
    build_daily_decision_evidence_automation_service,
    promoted_scan_cache_key,
    promoted_strategy_state_cache_identity,
)

__all__ = [
    "bind_promoted_strategy_scan",
    "build_daily_decision_evidence_automation_service",
    "promoted_scan_cache_key",
    "promoted_strategy_state_cache_identity",
]
