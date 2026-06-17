from __future__ import annotations

from pathlib import Path

from analytics.acceptance_audit import (
    build_acceptance_audit,
    build_research_evidence_acceptance_audit,
    build_strategy_lab_acceptance_audit,
)


def test_acceptance_audit_has_evidence_for_every_goal_checkbox() -> None:
    audit = build_acceptance_audit()

    assert audit.required_count == 13
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_goal_acceptance_checkboxes_match_acceptance_audit() -> None:
    audit = build_acceptance_audit()
    goal_text = Path("docs/KARKINOS_GOAL.md").read_text()

    assert audit.is_complete is True
    assert "* [ ]" not in goal_text.split("## North Star Metric", 1)[0]
    for criterion in audit.criteria:
        assert criterion.checkbox_text in goal_text


def test_strategy_lab_acceptance_audit_has_evidence_for_every_goal_checkbox() -> None:
    audit = build_strategy_lab_acceptance_audit()

    assert audit.required_count == 14
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_strategy_lab_goal_acceptance_checkboxes_match_audit() -> None:
    audit = build_strategy_lab_acceptance_audit()
    goal_text = Path("docs/KARKINOS_GOAL.md").read_text()
    strategy_lab_acceptance = goal_text.split(
        "### Acceptance Criteria for v0.4", 1
    )[1].split("## Target for v0.5", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in strategy_lab_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in goal_text


def test_research_evidence_acceptance_audit_has_evidence_for_every_goal_checkbox() -> (
    None
):
    audit = build_research_evidence_acceptance_audit()

    assert audit.required_count == 12
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_research_evidence_goal_acceptance_checkboxes_match_audit() -> None:
    audit = build_research_evidence_acceptance_audit()
    goal_text = Path("docs/KARKINOS_GOAL.md").read_text()
    research_evidence_acceptance = goal_text.split(
        "### Acceptance Criteria for v0.5", 1
    )[1].split("<!-- codex-progress:start -->", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in research_evidence_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in goal_text
