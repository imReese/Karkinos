"""Promotion checks exact Dev CI evidence and fast-forward semantics."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from tools import promote_dev as promotion
from tools import verify_release_source_ci as ci

REPO = "imReese/Karkinos"
A, B, C = (letter * 40 for letter in "abc")


class FakeClient:
    def __init__(self):
        self.refs = {"main": A, "dev": B}
        self.state = "success"
        self.attempt = 1
        self.writes: list[tuple[str, dict, str]] = []
        self.skipped_job = False
        self.main_runs: set[tuple[str, str]] = set()

    def ref(self, branch):
        return self.refs[branch]

    def relation(self, base, head):
        if base == head:
            return "identical"
        if (base, head) == (A, B):
            return "ahead"
        return "diverged"

    def workflow(self, filename):
        identities = {
            "dev-ci.yml": (7, "Dev CI"),
            "ci.yml": (8, "CI"),
            "candidate.yml": (9, "Release Candidate"),
        }
        workflow_id, name = identities[filename]
        return {
            "id": workflow_id,
            "name": name,
            "path": f".github/workflows/{filename}",
            "state": "active",
        }

    def workflow_runs(self, *, workflow_id, branch, event, commit_sha):
        if workflow_id == 7 and branch == "dev" and event == "push" and commit_sha == B:
            return {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 107,
                        "run_number": 107,
                        "run_attempt": self.attempt,
                        "workflow_id": 7,
                        "path": ".github/workflows/dev-ci.yml",
                        "head_branch": "dev",
                        "head_sha": B,
                        "event": "push",
                        "repository": {"full_name": REPO},
                        "head_repository": {"full_name": REPO},
                        "html_url": f"https://github.com/{REPO}/actions/runs/107",
                        "status": "in_progress" if self.state == "pending" else "completed",
                        "conclusion": None if self.state == "pending" else self.state,
                    }
                ],
            }
        if branch == "main" and (event, commit_sha) in self.main_runs:
            path = ".github/workflows/ci.yml" if workflow_id == 8 else ".github/workflows/candidate.yml"
            return {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 500 + workflow_id,
                        "run_number": 500 + workflow_id,
                        "run_attempt": 1,
                        "workflow_id": workflow_id,
                        "path": path,
                        "head_branch": "main",
                        "head_sha": commit_sha,
                        "event": event,
                        "repository": {"full_name": REPO},
                        "head_repository": {"full_name": REPO},
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            }
        return {"total_count": 0, "workflow_runs": []}

    def workflow_run_jobs(self, *, run_id):
        assert run_id == 107
        return {
            "total_count": 1,
            "jobs": [
                {
                    "id": 1,
                    "name": "Dev CI gate",
                    "head_sha": B,
                    "status": "completed",
                    "conclusion": "skipped" if self.skipped_job else "success",
                }
            ],
        }

    def write(self, suffix, payload, *, method):
        self.writes.append((suffix, payload, method))
        if method == "PATCH":
            assert suffix == "git/refs/heads/main"
            assert payload == {"sha": B, "force": False}
            self.refs["main"] = B


def test_selects_only_current_green_dev_head():
    client = FakeClient()
    assert promotion.select(client, REPO) == promotion.Selection(A, B, B, 107, 1)
    assert client.writes == []


@pytest.mark.parametrize("state", ["failure", "cancelled", "pending"])
def test_non_green_dev_head_is_not_promoted(state):
    client = FakeClient()
    client.state = state
    assert promotion.select(client, REPO) is None
    assert client.writes == []


def test_main_equal_to_dev_is_noop():
    client = FakeClient()
    client.refs["main"] = B
    assert promotion.select(client, REPO) is None


def test_branch_divergence_fails_closed(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(client, "relation", lambda *_: "diverged")
    with pytest.raises(ci.SourceCIVerificationError, match="must_contain_main"):
        promotion.select(client, REPO)


def test_successful_run_with_skipped_gate_is_rejected():
    client = FakeClient()
    client.skipped_job = True
    with pytest.raises(ci.SourceCIVerificationError, match="required_job_not_success"):
        promotion.select(client, REPO)


def test_apply_revalidates_dev_ci_posts_gate_then_fast_forwards_and_dispatches():
    client = FakeClient()
    selected = promotion.select(client, REPO)
    assert selected is not None

    result = promotion.apply(client, REPO, selected)

    assert client.refs["main"] == B
    assert result["main_updated"] is True
    assert result["dispatched"] == ["ci.yml", "candidate.yml"]
    assert client.writes[0] == (
        f"statuses/{B}",
        {
            "state": "success",
            "context": "Main promotion gate",
            "description": "Exact dev HEAD passed Dev CI",
            "target_url": f"https://github.com/{REPO}/actions/runs/107/attempts/1",
        },
        "POST",
    )
    assert client.writes[1] == (
        "git/refs/heads/main",
        {"sha": B, "force": False},
        "PATCH",
    )
    assert client.writes[2][1] == {
        "ref": "main",
        "inputs": {"commit_sha": B, "base_sha": A},
    }
    assert client.writes[3][1] == {"ref": "main", "inputs": {"commit_sha": B}}


@pytest.mark.parametrize("change", ["main", "dev", "attempt", "ci_failure"])
def test_changed_authorization_stops_before_any_write(change):
    client = FakeClient()
    selected = promotion.select(client, REPO)
    assert selected is not None
    if change == "main":
        client.refs["main"] = C
    elif change == "dev":
        client.refs["dev"] = C
    elif change == "attempt":
        client.attempt = 2
    else:
        client.state = "failure"

    with pytest.raises(ci.SourceCIVerificationError):
        promotion.apply(client, REPO, selected)
    assert client.writes == []


def test_server_rejection_never_falls_back_to_force(monkeypatch):
    client = FakeClient()
    selected = promotion.select(client, REPO)
    assert selected is not None
    calls = []

    def reject(*args, **kwargs):
        calls.append((args, kwargs))
        raise ci.SourceCIVerificationError("promotion_write_rejected:403")

    monkeypatch.setattr(client, "write", reject)
    with pytest.raises(ci.SourceCIVerificationError, match="403"):
        promotion.apply(client, REPO, selected)
    assert len(calls) == 1
    assert calls[0][0][0] == f"statuses/{B}"


def test_existing_main_runs_are_not_automatically_retried():
    client = FakeClient()
    client.refs["main"] = B
    client.main_runs = {("workflow_dispatch", B)}
    assert promotion.ensure_followup(client, REPO, B, A) == []
    assert client.writes == []


def test_schedule_uses_timezone_off_peak_and_no_stale_reusable_ci():
    config = yaml.load(
        Path(".github/workflows/promote-dev.yml").read_text(), Loader=yaml.BaseLoader
    )
    triggers = config["on"]
    schedule = triggers["schedule"]
    assert schedule == [{"cron": "17 2 * * *", "timezone": "Asia/Shanghai"}]
    assert "push" not in triggers
    assert "pull_request" not in triggers

    assert set(config["jobs"]) == {"select", "promote", "repair-followup"}
    assert "full-verification" not in config["jobs"]
    assert "verification-receipt" not in config["jobs"]
    assert "./.github/workflows/ci.yml" not in Path(
        ".github/workflows/promote-dev.yml"
    ).read_text()

    select_job = config["jobs"]["select"]
    assert select_job["permissions"] == {"contents": "read", "actions": "read"}
    promote_job = config["jobs"]["promote"]
    assert promote_job["needs"] == ["select"]
    assert promote_job["permissions"] == {
        "contents": "write",
        "actions": "write",
        "statuses": "write",
    }
    assert config["concurrency"] == {
        "group": "promote-dev-to-main",
        "queue": "max",
    }


def test_repair_followup_requires_trusted_main_context(monkeypatch):
    client = FakeClient()
    monkeypatch.setenv("GITHUB_REF", "refs/heads/dev")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setattr(promotion, "Client", lambda **_: client)
    assert promotion.main(["--repair-followup"]) == 1
