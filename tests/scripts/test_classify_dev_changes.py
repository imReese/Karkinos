from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ci import classify_dev_changes as classifier


@pytest.mark.parametrize(
    "path",
    [
        "core/types.py",
        "domain/portfolio_accounting.py",
        "data/market_data.py",
        "backtest/engine.py",
        "server/services/portfolio_read_snapshot.py",
        "tests/conftest.py",
    ],
)
def test_python_changes_run_backend_and_trading_safety(tmp_path, path) -> None:
    scope = classifier.classify_paths(tmp_path, [path])
    assert scope["backend"] is True
    assert scope["trading"] is True


def test_server_python_changes_also_run_docker(tmp_path) -> None:
    scope = classifier.classify_paths(tmp_path, ["server/runtime.py"])
    assert scope["backend"] is True
    assert scope["trading"] is True
    assert scope["docker"] is True


def test_frontend_dependencies_have_explicit_scope(tmp_path) -> None:
    scope = classifier.classify_paths(tmp_path, ["web/package-lock.json"])
    assert scope["frontend"] is True
    assert scope["dependencies"] is True
    assert scope["backend"] is False


@pytest.mark.parametrize("path", ["pyproject.toml", "uv.lock"])
def test_python_dependency_metadata_runs_backend_dependency_and_docker(tmp_path, path):
    scope = classifier.classify_paths(tmp_path, [path])
    assert scope["backend"] is True
    assert scope["trading"] is True
    assert scope["dependencies"] is True
    assert scope["docker"] is True


def test_workflow_changes_run_every_incremental_domain(tmp_path) -> None:
    scope = classifier.classify_paths(tmp_path, [".github/workflows/ci.yml"])
    assert all(scope[check] is True for check in classifier.CHECKS)


def test_dependabot_change_runs_dependency_and_workflow_security(tmp_path) -> None:
    scope = classifier.classify_paths(tmp_path, [".github/dependabot.yml"])
    assert scope["dependencies"] is True
    assert scope["workflow"] is True
    assert scope["backend"] is False


@pytest.mark.parametrize(
    "path",
    [
        "scripts/ci/check_python_quality.py",
        "tests/fixtures/ledger.json",
        "new_package/calculation.rs",
        "server/assets/research_prompt.md",
        "runtime_template.md",
    ],
)
def test_unknown_or_global_changes_fail_safe_to_all_checks(tmp_path, path) -> None:
    scope = classifier.classify_paths(tmp_path, [path])
    assert all(scope[check] is True for check in classifier.CHECKS)


def test_docs_only_change_runs_no_expensive_domain(tmp_path) -> None:
    for paths in (
        [],
        ["README.md", "docs/usage.md", "LICENSE"],
        ["scripts/README.md", "strategy/extensions/README.md"],
        sorted(classifier.DOCUMENTATION_FILES),
    ):
        scope = classifier.classify_paths(tmp_path, paths)
        assert all(scope[check] is False for check in classifier.CHECKS)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "CI Test")
    _git(tmp_path, "config", "user.email", "ci-test@example.invalid")
    (tmp_path / "README.md").write_text("# Fixture\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "Base fixture")
    return tmp_path


def test_exact_diff_preserves_unusual_paths_and_binds_resolved_base(repository):
    base = _git(repository, "rev-parse", "HEAD")
    path = "tests/test_中文\nfixture.py"
    (repository / "tests").mkdir()
    (repository / path).write_text("def test_example():\n    assert True\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Test fixture")
    assert classifier.changed_paths(repository, base=base, head="HEAD") == (
        base,
        [path],
    )
    with pytest.raises(ValueError, match="head_does_not_match_checkout"):
        classifier.changed_paths(repository, base=base, head=base)


def test_non_ancestor_base_is_rejected(repository):
    base = _git(repository, "rev-parse", "HEAD")
    (repository / "README.md").write_text("# Other branch\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Other branch")
    other = _git(repository, "rev-parse", "HEAD")
    _git(repository, "checkout", "--detach", base)
    with pytest.raises(subprocess.CalledProcessError):
        classifier.changed_paths(repository, base=other, head="HEAD")


def test_cli_writes_complete_outputs_and_fails_on_bad_identity(repository, monkeypatch):
    monkeypatch.setattr(classifier, "REPO_ROOT", repository)
    output = repository / "outputs"
    assert (
        classifier.main(
            ["--base", "HEAD", "--head", "HEAD", "--github-output", str(output)]
        )
        == 0
    )
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert fields["base_sha"] == _git(repository, "rev-parse", "HEAD")
    assert all(fields[check] == "false" for check in classifier.CHECKS)
    before = output.read_bytes()
    assert (
        classifier.main(
            ["--base", "missing-ref", "--head", "HEAD", "--github-output", str(output)]
        )
        == 1
    )
    assert output.read_bytes() == before
