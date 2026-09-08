"""The main shortcut requires immutable source and successful trusted evidence."""

from __future__ import annotations

import copy
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import ci_reuse as reuse

REPOSITORY = "imReese/Karkinos"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


@pytest.fixture
def source(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "CI fixture")
    git(tmp_path, "config", "user.email", "ci@example.invalid")
    for name in (reuse.PROMOTION_PATH, ".github/workflows/ci.yml", "tools/ci_reuse.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("trusted policy\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "trusted main")
    old = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "source.py").write_text("candidate source\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "candidate")
    candidate = git(tmp_path, "rev-parse", "HEAD")
    env = {
        "CI_COMMIT_SHA": candidate,
        "CI_BASE_SHA": old,
        "CI_PRE_PROMOTION": "false",
        "CI_FORCE_FULL": "false",
        "GITHUB_SHA": candidate,
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "CI_PROMOTION_RUN_ID": "900",
        "CI_PROMOTION_RUN_ATTEMPT": "1",
    }
    return tmp_path, old, candidate, env


class FakeClient:
    def __init__(self, workflow_sha, candidate):
        self.workflow_payload = {
            "id": 7,
            "name": "Promote verified dev",
            "path": reuse.PROMOTION_PATH,
            "state": "active",
        }
        self.run = {
            "id": 900,
            "run_attempt": 1,
            "workflow_id": 7,
            "path": reuse.PROMOTION_PATH,
            "head_branch": "main",
            "head_sha": workflow_sha,
            "repository": {"full_name": REPOSITORY},
            "head_repository": {"full_name": REPOSITORY},
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        completed = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        names = [
            "Full pre-promotion verification / " + name for name in reuse.FULL_JOB_NAMES
        ]
        names.append("Verified source " + candidate)
        self.jobs = [
            {
                "id": index + 1,
                "run_id": 900,
                "name": name,
                "head_sha": workflow_sha,
                "status": "completed",
                "conclusion": "success",
                "completed_at": completed,
            }
            for index, name in enumerate(names)
        ]
        self.reads = 0

    def workflow(self, filename):
        assert filename == "promote-dev.yml"
        return copy.deepcopy(self.workflow_payload)

    def workflow_run(self, run_id):
        assert run_id == 900
        self.reads += 1
        return copy.deepcopy(self.run)

    def attempt_jobs(self, run_id, run_attempt):
        assert (run_id, run_attempt) == (900, 1)
        return {"total_count": len(self.jobs), "jobs": copy.deepcopy(self.jobs)}


def verified(source, client=None, **kwargs):
    root, old, candidate, env = source
    return reuse.verify_reuse(
        client or FakeClient(old, candidate),
        reuse.validate_context(env, root),
        root,
        900,
        1,
        wait_seconds=0,
        **kwargs,
    )


def test_success_binds_target_caller_policy_run_and_attempt(source):
    root, old, candidate, env = source
    client = FakeClient(old, candidate)
    result = reuse.decide(env, root, client)
    assert result == {
        "mode": "reuse",
        "reason": "verified_promotion_attempt",
        "commit_sha": candidate,
        "source_run_id": 900,
        "source_run_attempt": 1,
        "source_workflow_sha": old,
        "policy_fingerprint": reuse.policy_fingerprint(root, candidate),
    }
    assert client.reads == 2


@pytest.mark.parametrize(
    "key,value",
    [
        ("id", 901),
        ("workflow_id", 8),
        ("run_attempt", 2),
        ("path", ".github/workflows/dev-ci.yml"),
        ("head_branch", "dev"),
        ("repository", {"full_name": "attacker/Karkinos"}),
        ("head_repository", {"full_name": "attacker/Karkinos"}),
        ("event", "pull_request"),
        ("status", "cancelled"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("conclusion", "skipped"),
        ("head_sha", "not-a-sha"),
    ],
)
def test_wrong_or_incomplete_run_never_reuses(source, key, value):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    client.run[key] = value
    with pytest.raises(reuse.ReuseError):
        verified(source, client)


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "skipped", "sha", "run", "id", "receipt"]
)
def test_job_evidence_is_complete_unique_target_bound_and_successful(source, mutation):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    if mutation == "missing":
        client.jobs.pop(0)
    elif mutation == "duplicate":
        client.jobs.append(client.jobs[0])
    elif mutation == "skipped":
        client.jobs[0]["conclusion"] = "skipped"
    elif mutation == "sha":
        client.jobs[0]["head_sha"] = candidate
    elif mutation == "run":
        client.jobs[0]["run_id"] = 901
    elif mutation == "id":
        client.jobs[0]["id"] = client.jobs[1]["id"]
    else:
        client.jobs[-1]["name"] = "Verified source " + old
    with pytest.raises(reuse.ci.SourceCIVerificationError):
        verified(source, client)


@pytest.mark.parametrize("name", reuse.FULL_JOB_NAMES)
def test_every_full_job_is_required_even_with_green_aggregate(source, name):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    for job in client.jobs:
        if job["name"] == "Full pre-promotion verification / " + name:
            job["conclusion"] = "failure"
    with pytest.raises(reuse.ci.SourceCIVerificationError):
        verified(source, client)


@pytest.mark.parametrize("offset", [-1, 24 * 3600 + 1])
def test_future_and_expired_completion_times_fail(source, offset):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    client.jobs[0]["completed_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=offset)
    ).isoformat()
    with pytest.raises(reuse.ReuseError, match="expired"):
        verified(source, client)


@pytest.mark.parametrize("timestamp", [None, "2026-01-01", "bad"])
def test_missing_or_ambiguous_timestamps_fail(source, timestamp):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    client.jobs[0]["completed_at"] = timestamp
    with pytest.raises(reuse.ReuseError, match="timestamp"):
        verified(source, client)


def test_rerun_or_state_change_during_validation_fails(source, monkeypatch):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    original = client.workflow_run

    def changed(run_id):
        result = original(run_id)
        if client.reads > 1:
            result["run_attempt"] = 2
        return result

    monkeypatch.setattr(client, "workflow_run", changed)
    with pytest.raises(reuse.ReuseError, match="changed_during"):
        verified(source, client)


def test_partial_attempt_and_incomplete_pagination_fail(source, monkeypatch):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    monkeypatch.setattr(
        client,
        "attempt_jobs",
        lambda *_: {"total_count": len(client.jobs), "jobs": client.jobs[:1]},
    )
    with pytest.raises(reuse.ci.SourceCIVerificationError, match="pagination"):
        verified(source, client)
    monkeypatch.setattr(
        client, "attempt_jobs", lambda *_: {"total_count": 1, "jobs": client.jobs[:1]}
    )
    with pytest.raises(reuse.ci.SourceCIVerificationError, match="missing"):
        verified(source, client)


@pytest.mark.parametrize("repository_key", ["repository", "head_repository"])
def test_unrelated_repository_activity_does_not_invalidate_run(
    source, monkeypatch, repository_key
):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    original = client.workflow_run

    def updated_repository(run_id):
        result = original(run_id)
        if client.reads > 1:
            result[repository_key]["pushed_at"] = "2026-09-08T12:00:00Z"
            result[repository_key]["open_issues_count"] = 99
        return result

    monkeypatch.setattr(client, "workflow_run", updated_repository)
    assert verified(source, client).commit_sha == candidate


@pytest.mark.parametrize(
    "identity,value", [("full_name", "attacker/Karkinos"), ("id", 888)]
)
def test_repository_identity_change_still_invalidates_run(
    source, monkeypatch, identity, value
):
    _, old, candidate, _ = source
    client = FakeClient(old, candidate)
    original = client.workflow_run

    def changed_identity(run_id):
        result = original(run_id)
        if client.reads > 1:
            result["head_repository"][identity] = value
        return result

    monkeypatch.setattr(client, "workflow_run", changed_identity)
    with pytest.raises(reuse.ReuseError, match="changed_during"):
        verified(source, client)


def test_recheck_rejects_changed_source_or_policy(source):
    with pytest.raises(reuse.ReuseError, match="source_workflow_changed"):
        verified(source, expected_workflow_sha="f" * 40)
    with pytest.raises(reuse.ReuseError, match="expected_policy_changed"):
        verified(source, expected_policy_fingerprint="f" * 64)


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/actions/check/action.yml",
        "scripts/ci/new.py",
        "tools/promote_dev_incremental.py",
        "tools/ci_reuse.py",
        "tools/verify_release_source_ci.py",
        "analytics/acceptance_audit_verification.py",
        "pyproject.toml",
        "uv.lock",
        "web/package-lock.json",
        "web/vite.config.ts",
        "Dockerfile",
        "tests/conftest.py",
    ],
)
def test_policy_changes_require_fresh_full_run(source, path):
    root, old, candidate, env = source
    before = reuse.policy_fingerprint(root, candidate)
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("changed rules\n")
    assert reuse.policy_fingerprint(root, candidate) == before
    git(root, "add", ".")
    git(root, "commit", "-qm", "policy changed")
    new = git(root, "rev-parse", "HEAD")
    env.update(CI_COMMIT_SHA=new, GITHUB_SHA=new)
    result = reuse.decide(env, root, FakeClient(old, new))
    assert result["mode"] == "full"
    assert result["reason"] == "ci_reuse_policy_changed"


def test_policy_includes_file_mode_and_rejects_symlinks(source):
    root, _, candidate, _ = source
    path = root / "tools/ci_reuse.py"
    path.chmod(0o755)
    git(root, "add", ".")
    git(root, "commit", "-qm", "mode changed")
    assert reuse.policy_fingerprint(
        root, git(root, "rev-parse", "HEAD")
    ) != reuse.policy_fingerprint(root, candidate)
    path.unlink()
    path.symlink_to("other.py")
    git(root, "add", ".")
    git(root, "commit", "-qm", "symlink")
    with pytest.raises(reuse.ReuseError, match="not_regular"):
        reuse.policy_fingerprint(root, git(root, "rev-parse", "HEAD"))


def test_old_workflow_without_receipt_policy_falls_back_full(source):
    root, old, candidate, env = source
    git(root, "rm", "tools/ci_reuse.py")
    git(root, "commit", "-qm", "missing policy")
    new = git(root, "rev-parse", "HEAD")
    env.update(CI_COMMIT_SHA=new, GITHUB_SHA=new)
    assert reuse.decide(env, root, FakeClient(old, new))["mode"] == "full"


@pytest.mark.parametrize(
    "field,value",
    [
        ("CI_COMMIT_SHA", "main"),
        ("CI_BASE_SHA", "x"),
        ("GITHUB_SHA", "f" * 40),
        ("GITHUB_REF", "refs/heads/topic"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("CI_FORCE_FULL", "yes"),
        ("GITHUB_REPOSITORY", "bad\nrepo"),
    ],
)
def test_invalid_local_identity_fails_instead_of_falling_back(source, field, value):
    root, _, _, env = source
    env[field] = value
    with pytest.raises(reuse.ReuseError):
        reuse.decide(env, root)


@pytest.mark.parametrize(
    "mode", ["force", "dev", "missing", "partial", "invalid", "unavailable", "pre"]
)
def test_safe_full_modes_and_missing_evidence(source, mode, monkeypatch):
    root, old, candidate, env = source
    client = FakeClient(old, candidate)
    if mode == "force":
        env["CI_FORCE_FULL"] = "true"
    elif mode == "dev":
        env["GITHUB_REF"] = "refs/heads/dev"
    elif mode == "missing":
        env.pop("CI_PROMOTION_RUN_ID")
        env.pop("CI_PROMOTION_RUN_ATTEMPT")
    elif mode == "partial":
        env.pop("CI_PROMOTION_RUN_ATTEMPT")
    elif mode == "invalid":
        env["CI_PROMOTION_RUN_ID"] = "900\ninjected=true"
    elif mode == "pre":
        git(root, "checkout", "--detach", old)
        env.update(GITHUB_SHA=old, CI_PRE_PROMOTION="true")
    else:

        def unavailable(*_):
            raise reuse.ci.SourceCIVerificationError("api_unavailable:private detail")

        monkeypatch.setattr(client, "workflow", unavailable)
    result = reuse.decide(env, root, client)
    assert result["mode"] == "full"
    assert "private" not in result["reason"]
    assert client.reads == 0


def gate_results(mode):
    result = {
        name: {
            "result": (
                "skipped"
                if mode == "reuse" and name in reuse.REUSED_JOBS
                else "success"
            )
        }
        for name in set(reuse.REUSED_JOBS)
        | set(reuse.FRESH_JOBS)
        | {"verification-plan"}
    }
    result["verification-plan"]["outputs"] = {"mode": mode}
    result["repository-acceptance-audit"]["outputs"] = {"evidence_rechecked": "true"}
    return result


@pytest.mark.parametrize("mode", ["full", "reuse"])
def test_gate_requires_exact_dependencies_and_expected_results(mode):
    result = gate_results(mode)
    reuse.require_gate_results(result)
    for name in tuple(result):
        for status in ("failure", "cancelled", "success", "skipped"):
            if status == result[name]["result"]:
                continue
            changed = copy.deepcopy(result)
            changed[name]["result"] = status
            with pytest.raises(reuse.ReuseError):
                reuse.require_gate_results(changed)
    result.pop("backend")
    with pytest.raises(reuse.ReuseError, match="dependencies"):
        reuse.require_gate_results(result)


@pytest.mark.parametrize("bad", [None, {}, "true", {"evidence_rechecked": "false"}])
def test_reuse_gate_needs_audit_recheck_even_if_all_other_statuses_pass(bad):
    result = gate_results("reuse")
    result["repository-acceptance-audit"]["outputs"] = bad
    with pytest.raises(reuse.ReuseError, match="not_rechecked"):
        reuse.require_gate_results(result)


def test_gate_mode_cannot_be_missing_unknown_or_passed_as_a_top_level_hint():
    result = gate_results("full")
    result["verification-plan"]["outputs"] = {"mode": "unknown"}
    with pytest.raises(reuse.ReuseError, match="mode_missing"):
        reuse.require_gate_results(result)
    result["mode"] = "reuse"
    with pytest.raises(reuse.ReuseError, match="dependencies"):
        reuse.require_gate_results(result)


def test_cli_gate_emits_identity_only_after_success(source, monkeypatch):
    root, _, candidate, env = source
    output = root / "output"
    summary = root / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("CI_COMMIT_SHA", candidate)
    result = gate_results("reuse")
    result["verification-plan"]["outputs"]["commit_sha"] = candidate
    monkeypatch.setenv("RESULTS", json.dumps(result))
    assert reuse.main(["gate"]) == 0
    assert output.read_text() == "verified_sha=" + candidate + "\n"
    expected_summary = f"CI verification: `verified`.\nCommit: `{candidate}`.\n"
    assert summary.read_text() == expected_summary
    output.unlink()
    monkeypatch.setenv("RESULTS", "{}")
    assert reuse.main(["gate"]) == 1
    assert not output.exists()
    assert summary.read_text() == expected_summary


def test_gate_cannot_emit_a_different_sha_than_the_validated_plan(source, monkeypatch):
    root, old, candidate, _ = source
    output = root / "output"
    summary = root / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("CI_COMMIT_SHA", candidate)
    result = gate_results("full")
    result["verification-plan"]["outputs"]["commit_sha"] = old
    monkeypatch.setenv("RESULTS", json.dumps(result))
    assert reuse.main(["gate"]) == 1
    assert not output.exists()
    assert not summary.exists()


@pytest.mark.parametrize("missing", ["SOURCE_WORKFLOW_SHA", "POLICY_FINGERPRINT", None])
def test_verify_cli_requires_pinned_plan_and_never_falls_back(
    source, monkeypatch, missing
):
    root, old, candidate, env = source
    client = FakeClient(old, candidate)
    env.update(
        SOURCE_WORKFLOW_SHA=old,
        POLICY_FINGERPRINT=reuse.policy_fingerprint(root, candidate),
    )
    if missing:
        env.pop(missing)
        monkeypatch.delenv(missing, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    output = root / "output"
    summary = root / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(reuse, "REPO_ROOT", root)
    monkeypatch.setattr(reuse, "_client", lambda _: client)
    if missing:
        assert reuse.main(["verify"]) == 1
        assert not output.exists()
        assert not summary.exists()
        assert client.reads == 0
    else:
        assert reuse.main(["verify"]) == 0
        assert "evidence_rechecked=true\n" in output.read_text()
        expected_summary = (
            f"CI verification: `reuse`.\nCommit: `{candidate}`.\n"
            "Evidence: [trusted promotion attempt]"
            f"(https://github.com/{REPOSITORY}/actions/runs/900/attempts/1).\n"
        )
        assert summary.read_text() == expected_summary
        output.unlink()
        client.run["run_attempt"] = 2
        assert reuse.main(["verify"]) == 1
        assert not output.exists()
        assert summary.read_text() == expected_summary


def test_pending_dispatch_finishes_within_bounded_wait(source, monkeypatch):
    root, old, candidate, env = source
    client = FakeClient(old, candidate)
    original = client.workflow_run
    sleeps = []

    def pending_once(run_id):
        result = original(run_id)
        if client.reads == 1:
            result.update(status="in_progress", conclusion=None)
        return result

    monkeypatch.setattr(client, "workflow_run", pending_once)
    monkeypatch.setattr(
        reuse,
        "time",
        SimpleNamespace(monotonic=reuse.time.monotonic, sleep=sleeps.append),
    )
    result = reuse.verify_reuse(client, reuse.validate_context(env, root), root, 900, 1)
    assert result.commit_sha == candidate
    assert sleeps == [2]
    assert client.reads == 3


def test_metadata_workflow_id_and_fork_cannot_authorize_reuse(source):
    root, old, candidate, env = source
    client = FakeClient(old, candidate)
    client.workflow_payload["name"] = "Fake promoter"
    assert reuse.decide(env, root, client)["mode"] == "full"
    env["GITHUB_REPOSITORY"] = "attacker/Karkinos"
    assert reuse.decide(env, root, FakeClient(old, candidate))["mode"] == "full"


def test_same_sha_cannot_fake_a_pre_promotion_execution(source):
    _, _, candidate, _ = source
    with pytest.raises(reuse.ReuseError, match="not_previous_main"):
        verified(source, FakeClient(candidate, candidate))


def test_client_uses_exact_attempt_endpoint(monkeypatch):
    client = reuse.Client(
        api_url="https://api.github.com",
        repository=REPOSITORY,
        token="fixture",
        api_version="2022-11-28",
    )
    calls = []
    monkeypatch.setattr(client, "_get_json", lambda *args: calls.append(args) or {})
    client.attempt_jobs(900, 2)
    assert calls == [
        (f"/repos/{REPOSITORY}/actions/runs/900/attempts/2/jobs", {"per_page": "100"})
    ]
