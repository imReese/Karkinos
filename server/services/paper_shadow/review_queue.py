"""Human review queue projection for paper shadow execution runs.

Canonical module in server.services.paper_shadow.
"""

from __future__ import annotations

from server.services.paper_shadow.paper_shadow_review_queue import (
    build_paper_shadow_review_queue,
)

__all__ = [
    "build_paper_shadow_review_queue",
]
