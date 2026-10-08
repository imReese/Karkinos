"""A human reviews one source, immutable paper version and measured interval."""

from datetime import datetime, timezone

import pytest

from server.services.forward_paper_review import (
    verify_forward_paper_review,
)
from tests.server.test_research_observations_journey import journey as journey
from tests.server.test_research_paper_books import (
    DAYS,
    bound_dataset,
    prepare_trade,
    settle,
)
from tests.server.test_research_paper_books import paper as paper


def test_review_rejects_wrong_source_version_and_outcome_but_preserves_old_prefix(
    paper, tmp_path
):
    client, service, current, observation, path = paper
    _, first, _, _, closes, _ = prepare_trade(paper, tmp_path)
    performance = first["performance"]
    reference = {
        "observation_id": observation["id"],
        "book_id": first["id"],
        "input_version": first["version"],
        "outcome_fingerprint": performance["outcome_fingerprint"],
        "evaluation_start": performance["evaluation_start"],
        "through_session": performance["through_session"],
    }
    source = first["source"]["source_result_id"]
    binding = verify_forward_paper_review(
        service.db, reference, source_result_id=source
    )
    assert binding["account_authority"] is False
    assert binding["does_not_replace_independent_final_evaluation"] is True
    with pytest.raises(ValueError, match="source_or_version_mismatch"):
        verify_forward_paper_review(service.db, reference, source_result_id=source + 1)
    with pytest.raises(ValueError, match="outcome_or_interval_mismatch"):
        verify_forward_paper_review(
            service.db,
            {**reference, "outcome_fingerprint": "0" * 64},
            source_result_id=source,
        )
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    closes[DAYS[6]] = "11"
    second, _ = settle(
        client,
        path,
        first["version"],
        bound_dataset(tmp_path, count=7, now=current[0], closes=closes),
    )
    assert second["version"] > first["version"]
    with pytest.raises(ValueError, match="source_or_version_mismatch"):
        verify_forward_paper_review(service.db, reference, source_result_id=source)
    assert (
        verify_forward_paper_review(
            service.db, binding, source_result_id=source, exact_current=False
        )
        == binding
    )
