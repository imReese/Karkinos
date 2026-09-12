"""Promotion protects exact-SHA verification and fast-forward semantics."""

from __future__ import annotations

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
        self.dev_state = "success"
        self.full_state = "missing"
        self.dev_attempt = 1
        self.full_attempt = 1
        self.writes: list[tuple[str, dict, str]] = []

    def ref(self, branch):
        return self.refs[branch]

    def relation(self, base, head):
        if base == head:
            return "identical"
        if (base, head) == (A, B):
            return "ahead"
        return "diverged"

    def workflow(self, filename):
        assert filename == "ci.yml"
        return {
            "id": 7,
            "name": "CI",
            "path": ".github/workflows/ci.yml",
            "state": "active",
        }

    def workflow_runs(self, *, workflow_id, branch, event, commit_sha):
        assert workflow_id == 7
        if branch != "dev" or commit_sha != B:
            return {"total_count": 0, "workflow_runs": []}
        if event == "push":
            state = self.dev_state
            run_id = 107
            attempt = self.dev_attempt
        elif event == "workflow_dispatch":
            state = self.full_state
            run_id = 207
            attempt = self.full_attempt
            if state == "missing":
                return {"total_count": 0, "workflow_runs": []}
        else:
            return {"total_count": 0, "workflow_runs": []}
        return {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": run_id,
                    "run_number": run_id,
                    "run_attempt": attempt,
                    "workflow_id": 7,
                    "path": ".github/workflows/ci.yml",
                    "head_branch": "dev",
                    "head_sha": B,
                    "event": event,
                    "repository": {"full_name": REPO},
                    "head_repository": {"full_name": REPO},
                    "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
                    "status": "in_progress" if state == "pending" else "completed",
                    "conclusion": None if state == "pending" else state,
                }
            ],
        }

    def workflow_run_jobs(self, *, run_id):
        if run_id == 107:
            name = "Dev CI gate"
            state = self.dev_state
        elif run_id == 207:
            name = "Full CI gate"
            state = self.full_state
        else:
            raise AssertionError(run_id)
        return {
            "total_count": 1,
            "jobs": [
                {
                    "id": run_id + 1,
                    "name": name,
                    "head_sha": B,
                    "status": "completed",
                    "conclusion": state,
                }
            ],
        }

    def write(self, suffix, payload, *, method):
        self.writes.append((suffix, payload, method))
        if suffix == "actions/workflows/ci.yml/dispatches":
            assert method == "POST"
            assert payload == {
                "ref": "dev",
                "inputs": {"mode": "full", "commit_sha": B, "base_sha": A},
            }
            self.full_state = "success"
        elif suffix == "git/refs/heads/main":
            assert method == "PATCH"
            assert payload == {"sha": B, "force": False}
            self.refs["main"] = B


def test_selects_only_current_green_dev_head():
    client = FakeClient()
    assert promotion.select(client, REPO) == promotion.Selection(A, B, B, 107, 1)
    assert client.writes == []


@pytest.mark.parametrize("state", ["failure", "cancelled", "pending"])
def test_non_green_dev_head_is_not_promoted(state):
    client = FakeClient()
    client.dev_state = state
    assert promotion.select(client, REPO) is None
    assert client.writes == []


def test_workflow_run_identity_is_bound_to_the_selected_dev_ci_attempt():
    client = FakeClient()
    with pytest.raises(ci.SourceCIVerificationError, match="trigger_run_changed"):
        promotion.select(client, REPO, expected_run_id=999, expected_run_attempt=1)
    with pytest.raises(ci.SourceCIVerificationError, match="trigger_attempt_changed"):
        promotion.select(client, REPO, expected_run_id=107, expected_run_attempt=2)


def test_branch_divergence_fails_closed(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(client, "relation", lambda *_: "diverged")
    with pytest.raises(ci.SourceCIVerificationError, match="must_contain_main"):
        promotion.select(client, REPO)


def test_missing_full_ci_is_dispatched_against_dev_before_any_main_write():
    client = FakeClient()
    selected = promotion.select(client, REPO)
    assert selected is not None
    full = promotion.ensure_full_ci(client, REPO, selected, timeout_seconds=1)
    assert full.commit_sha == B
    assert client.refs["main"] == A
    assert client.writes == [
        (
            "actions/workflows/ci.yml/dispatches",
            {
                "ref": "dev",
                "inputs": {"mode": "full", "commit_sha": B, "base_sha": A},
            },
            "POST",
        )
    ]


def test_failed_existing_full_ci_is_not_silently_replaced():
    client = FakeClient()
    client.full_state = "failure"
    selected = promotion.select(client, REPO)
    assert selected is not None
    with pytest.raises(ci.SourceCIVerificationError, match="run_not_success"):
        promotion.ensure_full_ci(client, REPO, selected, timeout_seconds=1)
    assert client.writes == []


def test_apply_requires_full_ci_then_posts_gate_and_non_force_fast_forwards():
    client = FakeClient()
    client.full_state = "success"
    selected = promotion.select(client, REPO)
    assert selected is not None
    full = promotion.ensure_full_ci(client, REPO, selected, timeout_seconds=1)

    result = promotion.apply(client, REPO, selected, full=full)

    assert result["main_updated"] is True
    assert result["full_ci_run_id"] == 207
    assert client.refs["main"] == B
    assert client.writes == [
        (
            f"statuses/{B}",
            {
                "state": "success",
                "context": "Main promotion gate",
                "description": "Exact dev HEAD passed complete Full CI",
                "target_url": f"https://github.com/{REPO}/actions/runs/207",
            },
            "POST",
        ),
        ("git/refs/heads/main", {"sha": B, "force": False}, "PATCH"),
    ]


@pytest.mark.parametrize("change", ["main", "dev", "dev_attempt", "full_attempt"])
def test_changed_authorization_stops_before_promotion_write(change):
    client = FakeClient()
    client.full_state = "success"
    selected = promotion.select(client, REPO)
    assert selected is not None
    full = promotion.ensure_full_ci(client, REPO, selected, timeout_seconds=1)
    client.writes.clear()
    if change == "main":
        client.refs["main"] = C
    elif change == "dev":
        client.refs["dev"] = C
    elif change == "dev_attempt":
        client.dev_attempt = 2
    else:
        client.full_attempt = 2

    with pytest.raises(ci.SourceCIVerificationError):
        promotion.apply(client, REPO, selected, full=full)
    assert client.writes == []


def test_server_rejection_never_falls_back_to_force(monkeypatch):
    client = FakeClient()
    client.full_state = "success"
    selected = promotion.select(client, REPO)
    assert selected is not None
    full = promotion.ensure_full_ci(client, REPO, selected, timeout_seconds=1)
    calls = []

    def reject(*args, **kwargs):
        calls.append((args, kwargs))
        raise ci.SourceCIVerificationError("promotion_write_rejected:403")

    monkeypatch.setattr(client, "write", reject)
    with pytest.raises(ci.SourceCIVerificationError, match="403"):
        promotion.apply(client, REPO, selected, full=full)
    assert len(calls) == 1
    assert calls[0][0][0] == f"statuses/{B}"


def test_privileged_promotion_is_event_driven_and_never_checks_out_dev():
    config = yaml.load(
        Path(".github/workflows/promote-dev.yml").read_text(), Loader=yaml.BaseLoader
    )
    triggers = config["on"]
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert triggers["workflow_run"] == {"workflows": ["CI"], "types": ["completed"]}
    assert "schedule" not in triggers

    text = Path(".github/workflows/promote-dev.yml").read_text()
    assert "ref: ${{ github.sha }}" in text
    assert "ref: dev" not in text
    assert "repair-followup" not in text
    assert "candidate.yml" not in text

    select_job = config["jobs"]["select"]
    assert select_job["permissions"] == {"contents": "read", "actions": "read"}
    promote_job = config["jobs"]["promote"]
    assert promote_job["permissions"] == {
        "contents": "write",
        "actions": "write",
        "statuses": "write",
    }
