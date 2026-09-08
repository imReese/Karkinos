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
        "tests/server/conftest.py",
    ],
)
def test_source_and_shared_test_changes_run_backend_and_safety(tmp_path, path) -> None:
    scope = classifier.classify_paths(tmp_path, [path])
    assert scope["backend"] is True
    assert scope["trading"] is True
    assert scope["backend_tests"] == ["tests"]


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_automation_control.py",
        "tests/server/test_account_truth_gate.py",
        "tests/test_paper_shadow_run_service.py",
        "tests/test_execution_batch_reconciliation.py",
        "tests/test_strategy_broker_boundary.py",
        "tests/data/test_market_data.py",
        "tests/data/test_中文\nfixture.py",
    ],
)
def test_test_only_changes_select_actual_files_and_schedule_safety(tmp_path, path):
    test_file = tmp_path / path
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_example():\n    assert True\n")
    scope = classifier.classify_paths(tmp_path, [path])
    assert scope["backend_tests"] == [path]
    assert scope["backend"] is True
    assert scope["trading"] is True
    assert scope["frontend"] is False


@pytest.mark.parametrize(
    "reference",
    [
        "from tests.data.test_shared import removed_helper\n",
        "import tests.data.test_shared\n",
        "from tests.data import test_shared\n",
        "from .test_shared import fixture\n",
        "from . import test_shared\n",
        "pytest_plugins = ['tests.data.test_shared']\n",
        "fixture_path = 'tests/data/test_shared.py'\n",
    ],
)
def test_shared_test_imports_and_references_broaden_backend(tmp_path, reference):
    tests = tmp_path / "tests" / "data"
    tests.mkdir(parents=True)
    # The imported helper may have been removed by this change.
    (tests / "test_shared.py").write_text("def test_local():\n    assert True\n")
    (tests / "test_consumer.py").write_text(reference)
    scope = classifier.classify_paths(tmp_path, ["tests/data/test_shared.py"])
    assert scope["backend_tests"] == ["tests"]
    assert scope["trading"] is True


def test_unreferenced_test_keeps_its_narrow_scope(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_local.py").write_text(
        "module_name = 'tests.test_local'\ndef test_local():\n    assert True\n"
    )
    (tests / "test_other.py").write_text("from core.types import Symbol\n")
    assert classifier.classify_paths(tmp_path, ["tests/test_local.py"])[
        "backend_tests"
    ] == ["tests/test_local.py"]


def test_shared_non_test_fixture_changes_broaden_backend(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "fixtures.py").write_text("value = 1\n")
    (tests / "test_consumer.py").write_text("from .fixtures import value\n")
    assert classifier.classify_paths(tmp_path, ["tests/fixtures.py"])[
        "backend_tests"
    ] == ["tests"]


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "pytest.ini",
        "Dockerfile",
        ".github/workflows/dev-ci.yml",
        "scripts/ci/classify_dev_changes.py",
        "tests/fixtures/ledger.json",
        "new_package/calculation.rs",
        "server/assets/research_prompt.md",
        "strategy/prompts/analysis.md",
        "runtime_template.md",
    ],
)
def test_unknown_or_global_configuration_broadens_all_checks(tmp_path, path) -> None:
    scope = classifier.classify_paths(tmp_path, [path])
    assert all(scope[check] is True for check in classifier.CHECKS)
    assert scope["backend_tests"] == ["tests"]


def test_deleted_test_or_mixed_source_diff_broadens_backend(tmp_path) -> None:
    path = "tests/test_changed.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / path).write_text("def test_example():\n    assert True\n")
    for paths in ([path, "core/types.py"], [path, "tests/test_deleted.py"]):
        assert classifier.classify_paths(tmp_path, paths)["backend_tests"] == ["tests"]


def test_frontend_dependencies_and_docs_have_explicit_scopes(tmp_path) -> None:
    web = classifier.classify_paths(tmp_path, ["web/package-lock.json"])
    assert web["frontend"] is True
    assert web["dependencies"] is True
    assert web["backend"] is False
    for paths in (
        [],
        ["README.md", "docs/usage.md", "LICENSE"],
        ["scripts/README.md", "strategy/extensions/README.md"],
        sorted(classifier.DOCUMENTATION_FILES),
    ):
        scope = classifier.classify_paths(tmp_path, paths)
        assert all(scope[check] is False for check in classifier.CHECKS)
        assert scope["backend_tests"] == []


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
    with pytest.raises(subprocess.CalledProcessError):
        classifier.changed_paths(repository, base="missing-ref", head="HEAD")


def test_non_ancestor_base_is_rejected(repository):
    base = _git(repository, "rev-parse", "HEAD")
    (repository / "README.md").write_text("# Other branch\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Other branch")
    other = _git(repository, "rev-parse", "HEAD")
    _git(repository, "checkout", "--detach", base)
    with pytest.raises(subprocess.CalledProcessError):
        classifier.changed_paths(repository, base=other, head="HEAD")


def test_cli_writes_complete_explicit_outputs_and_fails_on_bad_identity(
    repository, monkeypatch
):
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
    assert json.loads(fields["backend_tests"]) == []
    before = output.read_bytes()
    assert (
        classifier.main(
            ["--base", "missing-ref", "--head", "HEAD", "--github-output", str(output)]
        )
        == 1
    )
    assert output.read_bytes() == before
