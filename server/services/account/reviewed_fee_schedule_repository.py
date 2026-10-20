"""Repository adapter for persisted fee schedule reviews.

Backward-compatible facade for server.services.account.fees.repository.
"""

from __future__ import annotations

from server.services.account.fees.repository import (
    ReviewedFeeScheduleReviewRepository,
)

__all__ = [
    "ReviewedFeeScheduleReviewRepository",
]
