"""A manual final source reuses the genuine five-ref/critique resolver."""

from types import SimpleNamespace

import pytest

from server.services.research.research_final_evaluation import (
    manual_final_research_source,
)
from tests.ai_runtime.test_karkinos_capture_source import native_exploratory_report  # noqa: F401
from tests.ai_runtime.test_research_simulation_source import lineage  # noqa: F401


def test_manual_source_requires_real_critique_and_keeps_ready_nonqualified(
    lineage, monkeypatch, tmp_path
):
    store = lineage.service._research_store
    store._path = tmp_path / "unused-read-only.db"
    monkeypatch.setattr(
        "server.services.research.factory.build_strategy_research_read_service",
        lambda _db: lineage.service,
    )
    source = manual_final_research_source(research_store=store, source=lineage.source)
    assert source.manual_source_refs["critique_id"] == lineage.source.critique_id
    assert source.source_selection == lineage.selection
    assert not hasattr(source, "source_candidate")
    assert not hasattr(source, "research_candidate_qualified")
    lineage.rows["replay"][lineage.critique["workflow_id"]] = SimpleNamespace(
        valid=False
    )
    with pytest.raises(ValueError, match="source_not_ready"):
        manual_final_research_source(research_store=store, source=lineage.source)
