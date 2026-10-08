"""Read the exact isolated paper-book interval selected for human review."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from server.contracts.ai_shadow_research_qualification import (
    ShadowResearchQualificationRejected,
)


def verify_forward_paper_review(
    db: Any,
    reference: Mapping[str, Any],
    *,
    source_result_id: int,
    exact_current: bool = True,
) -> dict[str, Any]:
    """Bind human review to a frozen interval of the isolated simulated book.

    New approvals compare the current version under the database write lock.
    Later ordinary settlement retains the reviewed immutable prefix; it never
    rewrites the interval or broadens the approval's financial scope.
    """
    from analytics.paper_performance import paper_book_performance
    from server.persistence.research_paper_books import ResearchPaperBooksRepository

    version = reference.get("input_version")
    if type(version) is not int or version < 1 or not getattr(db, "_path", None):
        raise ShadowResearchQualificationRejected(
            "forward_paper_review_identity_invalid"
        )
    book = ResearchPaperBooksRepository(
        db._path, clock=lambda: datetime.now(timezone.utc)
    ).get(str(reference.get("observation_id") or ""))
    if (
        book is None
        or book["id"] != reference.get("book_id")
        or book.get("source", {}).get("source_result_id") != source_result_id
        or book["version"] < version
        or (exact_current and book["version"] != version)
    ):
        raise ShadowResearchQualificationRejected(
            "forward_paper_review_source_or_version_mismatch"
        )
    prefix = [step for step in book["steps"] if step["book_version"] <= version]
    frozen = {
        **book,
        "version": version,
        "steps": prefix,
        "last_settled_session": prefix[-1]["session"] if prefix else None,
        "state": prefix[-1]["projection"] if prefix else book["state"],
        "fills": [
            item for step in prefix for item in step["projection"].get("fills", [])
        ],
        "attempts": [
            item for step in prefix for item in step["projection"].get("attempts", [])
        ],
    }
    performance = paper_book_performance(frozen)
    if (
        performance.get("status") != "measured"
        or not performance.get("accepted_publication_count")
        or performance.get("outcome_fingerprint")
        != reference.get("outcome_fingerprint")
        or performance.get("evaluation_start") != reference.get("evaluation_start")
        or performance.get("through_session") != reference.get("through_session")
    ):
        raise ShadowResearchQualificationRejected(
            "forward_paper_review_outcome_or_interval_mismatch"
        )
    return {
        "schema_version": "karkinos.forward_paper_review.v1",
        **{
            key: reference[key]
            for key in (
                "observation_id",
                "book_id",
                "input_version",
                "outcome_fingerprint",
                "evaluation_start",
                "through_session",
            )
        },
        "source_result_id": source_result_id,
        "purpose": "supplementary_simulation_outcome_review",
        "account_authority": False,
        "does_not_replace_independent_final_evaluation": True,
    }
