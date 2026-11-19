"""Tests for scripts/ci/check_commit_msg.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scripts.ci.check_commit_msg import (
    extract_subject_from_message,
    main,
    validate_commit_subject,
)


def test_original_violating_titles_are_rejected():
    """Verify that the two original violating titles from this task are rejected."""
    # 1. Title 1: 74 chars and contains P0-4C
    orig_1 = (
        "feat(backtest): enforce P0-4C lifecycle isolation and deterministic replay"
    )
    errors_1 = validate_commit_subject(orig_1)
    assert len(errors_1) >= 2
    assert any("exceeds 72 characters (74 > 72)" in err for err in errors_1)
    assert any(
        "forbidden project management / review label 'P0-4C'" in err for err in errors_1
    )

    # 2. Title 2: 73 chars
    orig_2 = "feat(data): support market batch format in reported activity verification"
    errors_2 = validate_commit_subject(orig_2)
    assert len(errors_2) >= 1
    assert any("exceeds 72 characters (73 > 72)" in err for err in errors_2)


def test_corrected_titles_pass():
    """Verify that the user's recommended corrected titles pass cleanly."""
    corr_1 = "feat(backtest): isolate run lifecycle and add deterministic replay"
    assert len(corr_1) == 66
    assert validate_commit_subject(corr_1) == []

    corr_2 = "feat(data): verify reported activity from market batch responses"
    assert len(corr_2) == 64
    assert validate_commit_subject(corr_2) == []


def test_boundary_length_72_passes_73_fails():
    """Verify exact length boundary: 72 chars passes, 73 chars fails."""
    # 72 characters:
    title_72 = (
        "feat(backtest): isolate run lifecycle and add deterministic replay check"
    )
    assert len(title_72) == 72
    assert validate_commit_subject(title_72) == []

    # 73 characters:
    title_73 = (
        "feat(backtest): isolate run lifecycle and add deterministic replay checks"
    )
    assert len(title_73) == 73
    errors_73 = validate_commit_subject(title_73)
    assert any("exceeds 72 characters (73 > 72)" in err for err in errors_73)


def test_short_title_with_management_labels_is_rejected():
    """Verify that titles under 72 chars containing management/review labels are rejected."""
    # P0-4C
    assert any(
        "forbidden" in err
        for err in validate_commit_subject("feat(backtest): support P0-4C rules")
    )
    # Task A
    assert any(
        "forbidden" in err
        for err in validate_commit_subject("fix(jobs): complete Task A queues")
    )
    # CR #1 / CR 1
    assert any(
        "forbidden" in err
        for err in validate_commit_subject("fix(server): address CR #1 review items")
    )
    assert any(
        "forbidden" in err
        for err in validate_commit_subject("fix(server): address CR 1 comments")
    )
    # Checkpoint 1
    assert any(
        "forbidden" in err
        for err in validate_commit_subject("docs(plan): update Checkpoint 1 results")
    )


def test_legitimate_technical_phrases_are_not_rejected():
    """Verify that ordinary technical words like 'execution phase' or 'stage' are not falsely flagged."""
    tech_1 = "feat(execution): record open execution phase and fill timing"
    assert validate_commit_subject(tech_1) == []

    tech_2 = "fix(pipeline): handle second stage data processing"
    assert validate_commit_subject(tech_2) == []

    tech_3 = "refactor(data): parse staged partition manifests"
    assert validate_commit_subject(tech_3) == []


def test_conventional_commits_format_validation():
    """Verify basic Conventional Commits type and structure rules."""
    # Missing type:
    assert any(
        "does not follow Conventional Commits format" in err
        for err in validate_commit_subject("update something")
    )
    # Uppercase subject:
    assert any(
        "does not follow Conventional Commits format" in err
        for err in validate_commit_subject("feat(core): Update something")
    )
    # Invalid type:
    assert any(
        "does not follow Conventional Commits format" in err
        for err in validate_commit_subject("foo(core): update something")
    )
    # Empty subject:
    assert any("cannot be empty" in err for err in validate_commit_subject(""))


def test_cli_reads_commit_msg_file_with_comments(tmp_path: Path):
    """Verify CLI reads real commit message file, ignoring git comment lines."""
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(
        "# Please enter the commit message for your changes.\n"
        "feat(backtest): isolate run lifecycle and add deterministic replay\n"
        "\n"
        "# Lines starting with '#' will be ignored.\n",
        encoding="utf-8",
    )
    assert main([str(msg_file)]) == 0

    # Write invalid message
    msg_file.write_text("invalid commit message\n", encoding="utf-8")
    assert main([str(msg_file)]) == 1
