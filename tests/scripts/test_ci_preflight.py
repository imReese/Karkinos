"""Exercise Python quality scope and the split dev/main CI contracts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "karkinos_python_quality", ROOT / "scripts/ci/check_python_quality.py"
)
assert SPEC is not None and SPEC.loader is not None
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def write(root, name, content="value = 1\n"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(root):
    git(root, "add", "--all")
    git(root, "commit", "-qm", "Synthetic CI fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "CI Test")
    git(tmp_path, "config", "user.email", "ci-test@example.invalid")
    write(tmp_path, "original.py")
    write(tmp_path, "deleted.py")
    write(tmp_path, "README.md", "# Fixture\n")
    commit(tmp_path)
    return tmp_path


def test_committed_scope_handles_add_modify_delete_rename_and_unusual_paths(repository):
    base = git(repository, "rev-parse", "HEAD")
    write(repository, "original.py", "value = 2\n")
    (repository / "deleted.py").unlink()
    write(repository, "added file.py")
    write(repository, "line\nbreak.py")
    write(repository, "README.md", "# Changed\n")
    head = commit(repository)
    assert quality.python_files(repository, base=base, head=head) == [
        "added file.py",
        "line\nbreak.py",
        "original.py",
    ]
    git(repository, "mv", "added file.py", "renamed.py")
    new_head = commit(repository)
    assert quality.python_files(repository, base=head, head=new_head) == ["renamed.py"]


def test_local_scope_includes_staged_unstaged_and_untracked_files(repository):
    write(repository, "original.py", "value = 3\n")
    write(repository, "staged.py")
    git(repository, "add", "staged.py")
    write(repository, "untracked.py")
    write(repository, ".gitignore", "ignored.py\n")
    write(repository, "ignored.py")
    assert quality.python_files(repository, base="HEAD", head=None) == [
        "original.py",
        "staged.py",
        "untracked.py",
    ]


@pytest.mark.parametrize("base", [None, "", "0" * 40])
def test_initial_push_checks_root_commit_files(repository, base):
    assert quality.python_files(repository, base=base, head="HEAD") == [
        "deleted.py",
        "original.py",
    ]


def test_all_local_files_exclude_local_deletions(repository):
    (repository / "deleted.py").unlink()
    write(repository, "untracked.py")
    assert quality.python_files(repository, base=None, head=None) == [
        "original.py",
        "untracked.py",
    ]


def test_docs_only_diff_is_empty_but_bad_base_is_an_error(repository):
    base = git(repository, "rev-parse", "HEAD")
    write(repository, "README.md", "# Documentation only\n")
    head = commit(repository)
    assert quality.python_files(repository, base=base, head=head) == []
    with pytest.raises(subprocess.CalledProcessError):
        quality.python_files(repository, base="nonexistent-base", head=head)
    with pytest.raises(ValueError, match="does_not_match_checkout"):
        quality.python_files(repository, base=None, head=base)


def test_main_fails_closed_on_unavailable_revision(repository, monkeypatch):
    monkeypatch.setattr(quality, "REPO_ROOT", repository)
    monkeypatch.setattr(quality, "run_checks", lambda *_: pytest.fail("scope failed"))
    assert quality.main(["--base", "nonexistent-base", "--head", "HEAD"]) == 1


@pytest.mark.parametrize("failure_index", range(5))
def test_quality_failure_keeps_other_checks(tmp_path, monkeypatch, failure_index):
    calls = []

    def run(command, **kwargs):
        assert kwargs["cwd"] == tmp_path
        assert kwargs["timeout"] == quality.CHECK_TIMEOUT_SECONDS
        calls.append(command)
        return subprocess.CompletedProcess(
            command, int(len(calls) - 1 == failure_index)
        )

    monkeypatch.setattr(quality.subprocess, "run", run)
    assert quality.run_checks(tmp_path, ["name with spaces.py"]) == 1
    assert len(calls) == 5
    assert [command[2] for command in calls[:4]] == ["ruff", "black", "isort", "mypy"]
    assert calls[4][-1] == "tools/check_python_architecture.py"


def workflow(path):
    return yaml.load((ROOT / path).read_text(), Loader=yaml.BaseLoader)


def test_full_ci_allows_main_and_temporary_dev_bootstrap_pushes():
    config = workflow(".github/workflows/ci.yml")
    assert set(config["on"]) == {"push", "workflow_dispatch", "workflow_call"}
    assert config["on"]["push"] == {"branches": ["main", "dev"]}
    jobs = config["jobs"]
    for name in (
        "backend",
        "frontend",
        "trading-safety",
        "dependency-audit",
        "docker-runtime",
        "browser-safety",
        "repository-acceptance-audit",
    ):
        assert name in jobs
    assert set(jobs["repository-acceptance-audit"]["needs"]) == {
        "backend",
        "frontend",
        "trading-safety",
    }
    assert jobs["code-ci-gate"]["if"] == "always()"
    assert set(jobs["code-ci-gate"]["needs"]) == set(jobs) - {"code-ci-gate"}


def test_dev_ci_is_incremental_and_dev_only():
    config = workflow(".github/workflows/dev-ci.yml")
    assert set(config["on"]) == {"pull_request", "push"}
    assert config["on"]["push"] == {"branches": ["dev"]}
    jobs = config["jobs"]
    assert "changes" in jobs
    assert "backend" in jobs
    assert "browser-safety" not in jobs
    assert "repository-acceptance-audit" not in jobs
    for name in (
        "backend",
        "frontend",
        "trading-safety",
        "dependency-audit",
        "docker-runtime",
    ):
        assert "if" in jobs[name]
    assert jobs["code-ci-gate"]["if"] == "always()"
    assert set(jobs["code-ci-gate"]["needs"]) == set(jobs) - {"code-ci-gate"}


def test_both_ci_workflows_are_read_only_and_fail_closed():
    for path in (".github/workflows/ci.yml", ".github/workflows/dev-ci.yml"):
        config = workflow(path)
        assert config["permissions"] == {"contents": "read"}
        for job in config["jobs"].values():
            assert 0 < int(job["timeout-minutes"]) <= 20
            assert "continue-on-error" not in job
            for step in job["steps"]:
                assert "continue-on-error" not in step
                if step.get("uses", "").startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] == "false"


@pytest.mark.parametrize("branch", ["main", "dev"])
def test_long_lived_branch_policy_templates_block_history_loss(branch):
    policy = json.loads((ROOT / f".github/rulesets/{branch}.json").read_text())
    assert policy["target"] == "branch"
    assert policy["enforcement"] == "active"
    assert policy["conditions"] == {
        "ref_name": {"include": [f"refs/heads/{branch}"], "exclude": []}
    }
    assert policy["bypass_actors"] == []
    types = {rule["type"] for rule in policy["rules"]}
    assert {"deletion", "non_fast_forward"} <= types


def test_main_policy_template_requires_code_ci_gate():
    policy = json.loads((ROOT / ".github/rulesets/main.json").read_text())
    rules = {rule["type"]: rule for rule in policy["rules"]}
    checks = rules["required_status_checks"]["parameters"]
    assert checks["strict_required_status_checks_policy"] is True
    assert checks["required_status_checks"] == [
        {"context": "Main promotion gate", "integration_id": 15368}
    ]


def test_dependabot_version_updates_target_persistent_dev():
    config = yaml.load(
        (ROOT / ".github/dependabot.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert all(entry["target-branch"] == "dev" for entry in config["updates"])
