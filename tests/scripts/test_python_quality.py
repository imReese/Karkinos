from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import check_python_quality as quality


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "CI Test")
    _git(tmp_path, "config", "user.email", "ci-test@example.invalid")
    (tmp_path / "example.py").write_text("VALUE = 1\n")
    (tmp_path / "README.md").write_text("# fixture\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_python_files_tracks_committed_python_changes(repository: Path) -> None:
    base = _git(repository, "rev-parse", "HEAD")
    (repository / "example.py").write_text("VALUE = 2\n")
    (repository / "new.py").write_text("NEW = True\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "change")

    assert quality.python_files(repository, base=base, head="HEAD") == [
        "example.py",
        "new.py",
    ]


def test_python_files_ignores_documentation_only_changes(repository: Path) -> None:
    base = _git(repository, "rev-parse", "HEAD")
    (repository / "README.md").write_text("# changed\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "docs")

    assert quality.python_files(repository, base=base, head="HEAD") == []


def test_python_files_rejects_bad_or_mismatched_revisions(repository: Path) -> None:
    head = _git(repository, "rev-parse", "HEAD")
    with pytest.raises(subprocess.CalledProcessError):
        quality.python_files(repository, base="missing-ref", head="HEAD")

    (repository / "example.py").write_text("VALUE = 3\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "new head")
    with pytest.raises(ValueError, match="head_does_not_match_checkout"):
        quality.python_files(repository, base=head, head=head)


def test_run_checks_runs_stable_boundaries_without_changed_python(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert quality.run_checks(tmp_path, []) == 0
    assert calls == [
        [quality.sys.executable, "-m", "mypy"],
        [quality.sys.executable, "tools/check_python_architecture.py"],
    ]


def test_run_checks_reports_failure_but_runs_all_checks(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        code = 1 if "ruff" in command else 0
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(subprocess, "run", run)
    assert quality.run_checks(tmp_path, ["example.py"]) == 1
    assert len(calls) == 5
