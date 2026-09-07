"""Promotion checks real verifier contracts, not just YAML keywords."""

from __future__ import annotations

import pytest
import yaml

from tools import promote_dev as promotion
from tools import verify_release_source_ci as ci

REPO = "imReese/Karkinos"
A, B, C = (letter * 40 for letter in "abc")


class FakeClient:
    def __init__(self):
        self.refs = {"main": A, "dev": C}
        self.states = {B: "success", C: "failure"}
        self.attempt = 1
        self.writes = []
        self.skipped_job = False

    def ref(self, branch):
        return self.refs[branch]

    def relation(self, base, head):
        if base == head:
            return "identical"
        return "ahead" if base < head else "behind"

    def parent(self, sha):
        return {C: B, B: A, A: None}[sha]

    def workflow(self, filename):
        return {
            "id": 7 if filename == "ci.yml" else 8,
            "name": "CI" if filename == "ci.yml" else "Release Candidate",
            "path": f".github/workflows/{filename}",
            "state": "active",
        }

    def workflow_runs(self, *, workflow_id, branch, event, commit_sha):
        state = self.states.get(commit_sha) if branch == "dev" else None
        if state is None:
            return {"total_count": 0, "workflow_runs": []}
        run = {
            "id": 100 + ord(commit_sha[0]),
            "run_number": ord(commit_sha[0]),
            "run_attempt": self.attempt,
            "workflow_id": workflow_id,
            "path": ".github/workflows/ci.yml",
            "head_branch": branch,
            "head_sha": commit_sha,
            "event": event,
            "repository": {"full_name": REPO},
            "head_repository": {"full_name": REPO},
            "html_url": "https://github.com/imReese/Karkinos/actions/runs/198",
            "status": "in_progress" if state == "pending" else "completed",
            "conclusion": None if state == "pending" else state,
        }
        return {"total_count": 1, "workflow_runs": [run]}

    def workflow_run_jobs(self, *, run_id):
        sha = B if run_id == 100 + ord("b") else C
        jobs = [
            {
                "id": index + 1,
                "name": name,
                "head_sha": sha,
                "status": "completed",
                "conclusion": "skipped" if self.skipped_job else "success",
            }
            for index, name in enumerate(promotion.REQUIRED_JOBS)
        ]
        return {"total_count": len(jobs), "jobs": jobs}

    def write(self, suffix, payload, *, method):
        self.writes.append((suffix, payload, method))
        if method == "PATCH":
            assert suffix == "git/refs/heads/main"
            assert payload["force"] is False
            self.refs["main"] = payload["sha"]


def test_selects_latest_green_first_parent_without_including_failed_tip():
    client = FakeClient()
    result = promotion.select(client, REPO)
    assert result == promotion.Selection(A, C, B, 198, 1)
    assert client.writes == []


@pytest.mark.parametrize("state", ["failure", "cancelled", "pending", "skipped", None])
def test_non_success_tip_never_enters_main(state):
    client = FakeClient()
    client.states[C] = state
    selected = promotion.select(client, REPO)
    assert selected.commit_sha == B


def test_current_tip_is_selected_when_latest_ci_succeeds():
    client = FakeClient()
    client.states[C] = "success"
    assert promotion.select(client, REPO).commit_sha == C


def test_no_new_green_commit_does_not_write():
    client = FakeClient()
    client.states.clear()
    assert promotion.select(client, REPO) is None
    client.refs["main"] = C
    assert promotion.select(client, REPO) is None
    assert client.writes == []


def test_branch_divergence_stops_instead_of_merging(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(client, "relation", lambda *_: "diverged")
    with pytest.raises(ci.SourceCIVerificationError, match="must_contain_main"):
        promotion.select(client, REPO)
    assert client.writes == []


def test_successful_run_with_skipped_required_job_is_rejected():
    client = FakeClient()
    client.skipped_job = True
    with pytest.raises(ci.SourceCIVerificationError, match="required_job_not_success"):
        promotion.select(client, REPO)
    assert client.writes == []


def test_ref_update_is_exact_fast_forward_and_dispatches_main_ci_and_candidate():
    client = FakeClient()
    selected = promotion.select(client, REPO)
    result = promotion.apply(client, REPO, selected)
    assert client.refs == {"main": B, "dev": C}
    assert result["main_updated"] is True
    assert result["dispatched"] == ["ci.yml", "candidate.yml"]
    assert client.writes[0] == (
        "git/refs/heads/main",
        {"sha": B, "force": False},
        "PATCH",
    )
    assert client.writes[1][1] == {
        "ref": "main",
        "inputs": {"commit_sha": B, "base_sha": A},
    }
    assert client.writes[2][1] == {"ref": "main", "inputs": {"commit_sha": B}}


def test_retry_after_ref_write_repairs_dispatch_without_rewriting_history():
    client = FakeClient()
    selected = promotion.select(client, REPO)
    client.refs["main"] = B
    result = promotion.apply(client, REPO, selected)
    assert result["main_updated"] is False
    assert all(method == "POST" for _, _, method in client.writes)


@pytest.mark.parametrize("change", ["main", "dev", "attempt", "ci_failure"])
def test_changed_authorization_stops_before_any_write(change):
    client = FakeClient()
    selected = promotion.select(client, REPO)
    if change == "main":
        client.refs["main"] = C
    elif change == "dev":
        client.refs["dev"] = B
    elif change == "attempt":
        client.attempt = 2
    else:
        client.states[B] = "failure"
    with pytest.raises(ci.SourceCIVerificationError):
        promotion.apply(client, REPO, selected)
    assert client.writes == []


def test_server_rejection_never_falls_back_to_force_or_dispatch(monkeypatch):
    client = FakeClient()
    selected = promotion.select(client, REPO)
    calls = []

    def reject(*args, **kwargs):
        calls.append((args, kwargs))
        raise ci.SourceCIVerificationError("promotion_write_rejected:403")

    monkeypatch.setattr(client, "write", reject)
    with pytest.raises(ci.SourceCIVerificationError, match="403"):
        promotion.apply(client, REPO, selected)
    assert len(calls) == 1
    assert calls[0][0][1]["force"] is False


def test_history_bound_fails_explicitly(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(promotion, "MAX_COMMITS", 1)
    with pytest.raises(ci.SourceCIVerificationError, match="history_limit"):
        promotion.select(client, REPO)


def test_api_failure_is_not_mistaken_for_a_failed_candidate(monkeypatch):
    client = FakeClient()

    def fail(*args, **kwargs):
        raise ci.SourceCIVerificationError("api_inconclusive")

    monkeypatch.setattr(client, "workflow_runs", fail)
    with pytest.raises(ci.SourceCIVerificationError, match="api_inconclusive"):
        promotion.select(client, REPO)


def test_explicit_dispatch_participates_in_latest_main_ci_selection():
    client = FakeClient()
    old = client.workflow_runs(workflow_id=7, branch="dev", event="push", commit_sha=B)[
        "workflow_runs"
    ][0]
    old["head_branch"] = "main"
    newer = {
        **old,
        "event": "workflow_dispatch",
        "id": 500,
        "run_number": 500,
        "conclusion": "failure",
    }
    selected = ci.select_latest_exact_run(
        {"total_count": 2, "workflow_runs": [old, newer]},
        repository=REPO,
        workflow_id=7,
        workflow_path=".github/workflows/ci.yml",
        branch="main",
        event=("push", "workflow_dispatch"),
        commit_sha=B,
    )
    assert selected["id"] == 500
    assert selected["conclusion"] == "failure"


def test_invalid_sha_and_wrong_workflow_ref_cannot_write(monkeypatch):
    with pytest.raises(ci.SourceCIVerificationError, match="invalid_sha"):
        promotion.checked_sha("main")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/dev")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    assert promotion.main(["--apply"]) == 1


def test_schedule_has_no_pr_permission_and_never_executes_dev():
    from pathlib import Path

    config = yaml.load(
        Path(".github/workflows/promote-dev.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert config["on"]["schedule"] == [{"cron": "0 18 * * *"}]
    job = config["jobs"]["promote"]
    assert job["permissions"] == {"contents": "write", "actions": "write"}
    assert "refs/heads/main" in job["if"]
    checkout = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] == "false"
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert all("pull-request" not in step.get("run", "") for step in job["steps"])


@pytest.mark.parametrize(
    "method,status,accepted",
    [
        ("PATCH", 200, True),
        ("PATCH", 204, False),
        ("POST", 200, True),
        ("POST", 204, True),
        ("POST", 202, False),
    ],
)
def test_http_write_handles_versioned_dispatch_responses(
    monkeypatch, method, status, accepted
):
    class Response:
        def __init__(self):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    requests = []

    def request(req, timeout):
        assert timeout == 30
        requests.append(req)
        return Response()

    monkeypatch.setattr(ci, "urlopen", request)
    client = promotion.Client(
        api_url="https://api.github.com",
        repository=REPO,
        token="fixture-not-a-credential",
        api_version="2022-11-28",
    )
    suffix = (
        "git/refs/heads/main"
        if method == "PATCH"
        else "actions/workflows/ci.yml/dispatches"
    )
    if accepted:
        client.write(suffix, {}, method=method)
    else:
        with pytest.raises(ci.SourceCIVerificationError, match="write_status_invalid"):
            client.write(suffix, {}, method=method)
    assert len(requests) == 1
    assert requests[0].get_method() == method
