"""Evidence gathering and aggregation ports for daily decision evidence.

Canonical subpackage module in server.services.decision.evidence.
"""

from __future__ import annotations

from server.services.decision.daily_decision_evidence_collection import (
    collect_daily_decision_evidence,
)

__all__ = [
    "collect_daily_decision_evidence",
]
