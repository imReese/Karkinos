"""Exercise CI scope selection, independent checks and the actual final gate."""

from __future__ import annotations

import importlib.util
import json
import os
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
        exit_code = int(len(calls) - 1 == failure_index)
        return subprocess.CompletedProcess(command, exit_code)

    monkeypatch.setattr(quality.subprocess, "run", run)
    assert quality.run_checks(tmp_path, ["name with spaces.py"]) == 1
    assert len(calls) == 5
    assert [command[2] for command in calls[:4]] == ["ruff", "black", "isort", "mypy"]
    assert calls[4][-1] == "tools/check_python_architecture.py"
    assert all(command[-2:] == ["--", "name with spaces.py"] for command in calls[:3])


@pytest.mark.parametrize(
    "error",
    [OSError("unavailable"), subprocess.TimeoutExpired("check", 1)],
)
def test_unavailable_or_timed_out_check_cannot_pass(tmp_path, monkeypatch, error):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise error
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(quality.subprocess, "run", run)
    assert quality.run_checks(tmp_path, ["example.py"]) == 1
    assert len(calls) == 5


def test_empty_python_diff_still_checks_types_and_architecture(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(quality.subprocess, "run", run)
    assert quality.run_checks(tmp_path, []) == 0
    assert calls == [
        [sys.executable, "-m", "mypy"],
        [sys.executable, "tools/check_python_architecture.py"],
    ]


def workflow():
    # BaseLoader preserves YAML's `on` key instead of treating it as a boolean.
    return yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader
    )


def test_expensive_jobs_require_all_preflight_checks():
    jobs = workflow()["jobs"]
    preflight = {"python-quality", "repository-contracts", "hygiene", "secret-scan"}
    for name in preflight:
        assert not jobs[name].get("needs")
    for name in (
        "backend",
        "frontend",
        "trading-safety",
        "dependency-audit",
        "docker-runtime",
        "browser-safety",
    ):
        assert set(jobs[name]["needs"]) == preflight
        assert "if" not in jobs[name]
    assert set(jobs["code-ci-gate"]["needs"]) == set(jobs) - {"code-ci-gate"}
    assert jobs["code-ci-gate"]["if"] == "always()"
    assert jobs["code-ci-gate"]["name"] == "Code CI gate"
    assert jobs["repository-acceptance-audit"]["name"] == "Repository acceptance audit"
    assert set(jobs["repository-acceptance-audit"]["needs"]) == {
        "backend",
        "frontend",
        "trading-safety",
    }


def test_docs_consumers_and_ci_contracts_run_before_backend():
    jobs = workflow()["jobs"]
    steps = jobs["repository-contracts"]["steps"]
    command = next(
        step["run"] for step in steps if step["name"] == "Run repository contract tests"
    )
    for path in (
        "tests/scripts/test_docs_health.py",
        "tests/strategy/test_strategy_docs.py",
        "tests/scripts/test_ci_preflight.py",
        "tests/test_ci_workflow.py",
        "tests/test_ci_safety_workflow.py",
        "tests/scripts/test_scripts_inventory.py",
    ):
        assert path in command
    quality_step = next(
        step
        for step in jobs["python-quality"]["steps"]
        if step["name"] == "Check changed Python files and stable boundaries"
    )
    assert "scripts/ci/check_python_quality.py" in quality_step["run"]
    assert '--base "${BASE_SHA}" --head "${GITHUB_SHA}"' in quality_step["run"]


def test_no_path_exemptions_or_hidden_failures_and_checkouts_are_read_only():
    config = workflow()
    assert set(config["on"]) == {"pull_request", "push"}
    assert config["on"]["push"] == {"branches": ["main", "dev"]}
    assert config["permissions"] == {"contents": "read"}
    assert (
        config["concurrency"]["cancel-in-progress"]
        == "${{ github.event_name == 'pull_request' }}"
    )
    assert "${{ github.ref }}" in config["concurrency"]["group"]
    assert "github.sha" in config["concurrency"]["group"]
    for job in config["jobs"].values():
        assert 0 < int(job["timeout-minutes"]) <= 20
        assert "continue-on-error" not in job
        for step in job["steps"]:
            assert "continue-on-error" not in step
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] == "false"


def run_gate(tmp_path, results):
    gate = workflow()["jobs"]["code-ci-gate"]["steps"][0]
    assert gate["env"]["CI_JOB_RESULTS"] == "${{ toJSON(needs) }}"
    assert gate["shell"] == "python"
    return subprocess.run(
        [sys.executable, "-c", gate["run"]],
        env={
            **os.environ,
            "CI_JOB_RESULTS": json.dumps(results),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_actual_gate_requires_success_and_writes_all_results(tmp_path):
    results = {
        name: {"result": "success"}
        for name in workflow()["jobs"]["code-ci-gate"]["needs"]
    }
    result = run_gate(tmp_path, results)
    assert result.returncode == 0, result.stderr
    summary = (tmp_path / "summary.md").read_text()
    assert all(name in summary for name in results)


@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", "unknown", None])
def test_actual_gate_rejects_non_success_results(tmp_path, state):
    results = {
        "backend": {"result": "success"},
        "repository-contracts": {"result": state},
    }
    result = run_gate(tmp_path, results)
    assert result.returncode != 0
    assert "repository-contracts" in result.stderr
    assert "backend" in (tmp_path / "summary.md").read_text()


@pytest.mark.parametrize("results", [{}, [], {"backend": {}}, {"backend": None}])
def test_actual_gate_rejects_absent_results(tmp_path, results):
    assert run_gate(tmp_path, results).returncode != 0


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
    assert "required_linear_history" not in types


def test_main_policy_template_requires_reviewed_current_ci_and_merge_commits():
    policy = json.loads((ROOT / ".github/rulesets/main.json").read_text())
    rules = {rule["type"]: rule for rule in policy["rules"]}
    review = rules["pull_request"]["parameters"]
    assert review["allowed_merge_methods"] == ["merge"]
    assert review["required_review_thread_resolution"] is True
    assert review["required_approving_review_count"] == 0
    assert review["require_last_push_approval"] is False
    checks = rules["required_status_checks"]["parameters"]
    assert checks["strict_required_status_checks_policy"] is True
    assert checks["do_not_enforce_on_create"] is False
    assert checks["required_status_checks"] == [
        {"context": workflow()["jobs"]["code-ci-gate"]["name"], "integration_id": 15368}
    ]


def test_dev_policy_template_permits_normal_pushes_to_start_ci():
    policy = json.loads((ROOT / ".github/rulesets/dev.json").read_text())
    assert {rule["type"] for rule in policy["rules"]} == {
        "deletion",
        "non_fast_forward",
    }


def test_dependabot_version_updates_target_persistent_dev():
    config = yaml.load(
        (ROOT / ".github/dependabot.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert {entry["package-ecosystem"] for entry in config["updates"]} == {
        "uv",
        "npm",
        "github-actions",
        "docker",
    }
    assert all(entry["target-branch"] == "dev" for entry in config["updates"])
