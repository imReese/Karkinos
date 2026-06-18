from __future__ import annotations

from pathlib import Path

from analytics.acceptance_audit import (
    build_acceptance_audit,
    build_account_truth_acceptance_audit,
    build_account_truth_review_acceptance_audit,
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
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    profit_discipline_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.2", 1
    )[1].split("## v0.3", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in profit_discipline_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in profit_discipline_acceptance


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
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    strategy_lab_acceptance = roadmap_text.split("### Acceptance Criteria for v0.4", 1)[
        1
    ].split("## Target for v0.5", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in strategy_lab_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in strategy_lab_acceptance


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
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    research_evidence_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.5", 1
    )[1].split("## Target for v0.6", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in research_evidence_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in research_evidence_acceptance


def test_account_truth_acceptance_audit_has_evidence_for_every_completed_checkbox() -> (
    None
):
    audit = build_account_truth_acceptance_audit()

    assert audit.required_count == 15
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_account_truth_goal_completed_checkboxes_match_audit() -> None:
    audit = build_account_truth_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    account_truth_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.6", 1
    )[1].split("## Target for v0.7", 1)[0]

    assert audit.is_complete is True
    for criterion in audit.criteria:
        assert criterion.checkbox_text in account_truth_acceptance

    completed_checkboxes = [
        line
        for line in account_truth_acceptance.splitlines()
        if line.startswith("* [x]")
    ]
    assert audit.required_count == len(completed_checkboxes)


def test_account_truth_review_acceptance_audit_has_evidence_for_every_completed_checkbox() -> (
    None
):
    audit = build_account_truth_review_acceptance_audit()

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


def test_account_truth_review_goal_checkboxes_match_audit() -> None:
    audit = build_account_truth_review_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    account_truth_review_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.7", 1
    )[1].split("## Future Candidate Milestones", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in account_truth_review_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in account_truth_review_acceptance

    completed_checkboxes = [
        line
        for line in account_truth_review_acceptance.splitlines()
        if line.startswith("* [x]")
    ]
    assert audit.required_count == len(completed_checkboxes)
