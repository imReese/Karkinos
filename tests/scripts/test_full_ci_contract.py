from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> dict:
    return yaml.load(
        (ROOT / ".github" / "workflows" / name).read_text(), Loader=yaml.BaseLoader
    )


def _identity_step() -> dict:
    return next(
        step
        for step in _workflow("ci.yml")["jobs"]["python-quality"]["steps"]
        if step.get("name") == "Verify exact checkout identity"
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "CI Test")
    _git(tmp_path, "config", "user.email", "ci-test@example.invalid")
    (tmp_path / "fixture.txt").write_text("base\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "Base fixture")
    base = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "fixture.txt").write_text("candidate\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "Candidate fixture")
    candidate = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "--detach", base)
    (tmp_path / "fixture.txt").write_text("unrelated branch\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "Diverged fixture")
    diverged = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "--detach", candidate)
    return tmp_path, {"base": base, "candidate": candidate, "diverged": diverged}


def _run_identity(repository, **overrides: str) -> subprocess.CompletedProcess:
    root, commits = repository
    env = {
        **os.environ,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_SHA": commits["candidate"],
        "EXPECTED_SHA": commits["candidate"],
        "EXPECTED_BASE": commits["base"],
        "PRE_PROMOTION": "false",
        **{key: commits.get(value, value) for key, value in overrides.items()},
    }
    return subprocess.run(
        ["bash", "-c", _identity_step()["run"]],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"GITHUB_EVENT_NAME": "workflow_dispatch"},
        {
            "GITHUB_REF": "refs/heads/dev",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
        },
        {"EXPECTED_BASE": "0" * 40},
        {
            "GITHUB_EVENT_NAME": "schedule",
            "GITHUB_SHA": "base",
            "PRE_PROMOTION": "true",
        },
    ],
)
def test_identity_accepts_exact_main_dev_dispatch_and_reusable_candidate(
    repository, overrides
):
    result = _run_identity(repository, **overrides)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "overrides",
    [
        {"EXPECTED_SHA": "main"},
        {"EXPECTED_SHA": "base"},
        {"GITHUB_SHA": "base"},
        {"EXPECTED_BASE": "main"},
        {"EXPECTED_BASE": "f" * 40},
        {"EXPECTED_BASE": "diverged"},
        {"GITHUB_REF": "refs/heads/dev"},
        {
            "GITHUB_REF": "refs/heads/feature",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
        },
        {
            "GITHUB_REF": "refs/tags/v0.0.0",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
        },
        {
            "GITHUB_REF": "refs/heads/dev",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_SHA": "base",
        },
        {
            "GITHUB_REF": "refs/heads/dev",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "PRE_PROMOTION": "true",
        },
    ],
)
def test_identity_rejects_wrong_checkout_event_ref_and_base(repository, overrides):
    result = _run_identity(repository, **overrides)
    assert result.returncode != 0


def _run_gate(tmp_path: Path, results: dict) -> tuple[subprocess.CompletedProcess, str]:
    gate = _workflow("ci.yml")["jobs"]["code-ci-gate"]
    output = tmp_path / "github-output"
    output.write_text("existing=preserved\n")
    result = subprocess.run(
        [sys.executable, "-c", gate["steps"][-1]["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "RESULTS": json.dumps(results),
            "GITHUB_OUTPUT": str(output),
            "CI_COMMIT_SHA": "c" * 40,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output.read_text()


def _successful_jobs() -> dict:
    gate = _workflow("ci.yml")["jobs"]["code-ci-gate"]
    return {name: {"result": "success"} for name in gate["needs"]}


def test_full_gate_writes_candidate_identity_only_after_every_job_succeeds(tmp_path):
    result, output = _run_gate(tmp_path, _successful_jobs())
    assert result.returncode == 0, result.stderr
    assert output == f"existing=preserved\nverified_sha={'c' * 40}\n"


@pytest.mark.parametrize("name", _successful_jobs())
@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped"])
def test_full_gate_never_emits_verified_sha_for_an_unsuccessful_job(
    tmp_path, name, state
):
    results = _successful_jobs()
    results[name]["result"] = state
    result, output = _run_gate(tmp_path, results)
    assert result.returncode != 0
    assert name in result.stderr
    assert output == "existing=preserved\n"


def test_full_ci_checkout_and_reusable_outputs_bind_the_exact_candidate():
    workflow = _workflow("ci.yml")
    assert workflow["env"]["CI_COMMIT_SHA"] == "${{ inputs.commit_sha || github.sha }}"
    jobs = workflow["jobs"]
    for name, job in jobs.items():
        checkouts = [
            step
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        ]
        if name != "code-ci-gate":
            assert checkouts, name
        for checkout in checkouts:
            assert checkout["with"]["ref"] == "${{ env.CI_COMMIT_SHA }}"
            assert checkout["with"]["persist-credentials"] == "false"
    gate = jobs["code-ci-gate"]
    assert set(gate["needs"]) == set(jobs) - {"code-ci-gate"}
    assert gate["if"] == "always()"
    assert gate["outputs"]["verified_sha"] == "${{ steps.gate.outputs.verified_sha }}"
    assert workflow["on"]["workflow_call"]["outputs"]["verified_sha"]["value"] == (
        "${{ jobs.code-ci-gate.outputs.verified_sha }}"
    )
    caller = _workflow("promote-dev.yml")["jobs"]["full-verification"]
    assert caller["uses"] == "./.github/workflows/ci.yml"
    assert caller["with"] == {
        "commit_sha": "${{ needs.select.outputs.commit_sha }}",
        "base_sha": "${{ needs.select.outputs.previous_main }}",
        "pre_promotion": "true",
    }


def test_every_full_ci_uv_operation_preserves_the_lockfile():
    workflow = _workflow("ci.yml")
    operations = set()
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            env = {
                **workflow.get("env", {}),
                **job.get("env", {}),
                **step.get("env", {}),
            }
            for line in step.get("run", "").replace("\\\n", " ").splitlines():
                match = re.search(r"\buv\s+(sync|run|export)\b", line)
                if match is None:
                    continue
                tokens = shlex.split(line[match.start() :])
                operations.add(tokens[1])
                assert "--frozen" not in tokens
                assert "--no-locked" not in tokens
                assert env.get("UV_FROZEN", "false") == "false"
                assert "--locked" in tokens or env.get("UV_LOCKED") == "true", line
    assert operations == {"sync", "run", "export"}
