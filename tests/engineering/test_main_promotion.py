"""Only the current verified dev head may fast-forward main."""

from __future__ import annotations

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest

from tools import promote_dev as promotion

REPOSITORY = "imReese/Karkinos"
MAIN, DEV, OTHER = (letter * 40 for letter in "abc")


class FakeClient(promotion.Client):
    def __init__(self):
        self.repository = REPOSITORY
        self.refs = {"main": MAIN, "dev": DEV}
        self.run = {
            "id": 107,
            "check_suite_id": 207,
            "path": ".github/workflows/ci.yml",
            "head_sha": DEV,
            "head_branch": "dev",
            "event": "push",
            "repository": {"full_name": REPOSITORY},
            "head_repository": {"full_name": REPOSITORY},
            "status": "completed",
            "conclusion": "success",
        }
        self.checks = [
            {
                "id": 307,
                "name": "Promotion Gate",
                "head_sha": DEV,
                "check_suite": {"id": 207},
                "app": {"id": 15368, "slug": "github-actions"},
                "status": "completed",
                "conclusion": "success",
            }
        ]
        self.run_count = 1
        self.ancestor = True
        self.ref_reads = {"main": 0, "dev": 0}
        self.changed_ref = None
        self.check_reads = 0
        self.fail_gate_on_recheck = False
        self.reject_write = False
        self.confirm_write = True
        self.post_write_main = []
        self.post_write_reads = 0
        self.writes = []

    def request(self, path, payload=None):
        parsed = urlsplit(path)
        endpoint = parsed.path.removeprefix(f"/repos/{REPOSITORY}/").lstrip("/")
        query = parse_qs(parsed.query)
        if payload is not None:
            self.writes.append((endpoint, deepcopy(payload)))
            assert endpoint == "git/refs/heads/main"
            if self.reject_write:
                raise promotion.PromotionError("GitHub rejected the update: HTTP 403")
            if self.confirm_write:
                self.refs["main"] = payload["sha"]
            return {"ref": "refs/heads/main", "object": {"sha": payload["sha"]}}
        if endpoint.startswith("git/ref/heads/"):
            branch = endpoint.rsplit("/", 1)[1]
            self.ref_reads[branch] += 1
            sha = self.refs[branch]
            if branch == self.changed_ref and self.ref_reads[branch] > 1:
                sha = OTHER
            if branch == "main" and self.writes:
                self.post_write_reads += 1
                if self.post_write_main:
                    sha = self.post_write_main[0]
                    if len(self.post_write_main) > 1:
                        self.post_write_main.pop(0)
                    if isinstance(sha, Exception):
                        raise sha
            return {
                "ref": f"refs/heads/{branch}",
                "object": {"type": "commit", "sha": sha},
            }
        if endpoint == "actions/workflows/ci.yml/runs":
            assert query["head_sha"] == [DEV]
            assert query["branch"] == ["dev"]
            assert query["event"] == ["push"]
            assert "status" not in query
            return {
                "total_count": self.run_count,
                "workflow_runs": [deepcopy(self.run)] if self.run_count else [],
            }
        if endpoint == "check-suites/207/check-runs":
            self.check_reads += 1
            checks = deepcopy(self.checks)
            if self.fail_gate_on_recheck and self.check_reads > 1:
                checks[0]["conclusion"] = "failure"
            return {"total_count": len(checks), "check_runs": checks}
        if endpoint == f"compare/{MAIN}...{DEV}":
            return {
                "status": "ahead" if self.ancestor else "diverged",
                "merge_base_commit": {"sha": MAIN if self.ancestor else OTHER},
            }
        raise AssertionError(f"Unexpected API request: {path}")


def test_preview_never_writes():
    client = FakeClient()
    promotion.promote(client)
    assert client.writes == []
    assert client.refs["main"] == MAIN


def test_promotes_current_verified_dev_head_with_non_force_update():
    client = FakeClient()
    promotion.promote(client, apply=True)
    assert client.writes == [("git/refs/heads/main", {"sha": DEV, "force": False})]
    assert client.refs["main"] == DEV
    assert client.ref_reads["dev"] >= 2
    assert client.ref_reads["main"] >= 3


def test_already_promoted_main_needs_no_write():
    client = FakeClient()
    client.refs["main"] = DEV
    promotion.promote(client, apply=True)
    assert client.writes == []


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "neutral"])
def test_unsuccessful_gate_blocks_promotion(conclusion):
    client = FakeClient()
    client.checks[0]["conclusion"] = conclusion
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


def test_latest_pending_run_cannot_fall_back_to_an_older_green_run():
    client = FakeClient()
    client.run_count = 2
    client.run.update(status="in_progress", conclusion=None)
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head_sha", OTHER),
        ("head_branch", "feature/untrusted"),
        ("event", "pull_request"),
        ("path", ".github/workflows/unrelated.yml"),
        ("repository", {"full_name": "someone/Karkinos"}),
        ("head_repository", {"full_name": "someone/Karkinos"}),
    ],
)
def test_unrelated_or_untrusted_ci_run_cannot_authorize_promotion(field, value):
    client = FakeClient()
    client.run[field] = value
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Unrelated gate"),
        ("head_sha", OTHER),
        ("check_suite", {"id": 999}),
        ("app", {"id": 999, "slug": "github-actions"}),
        ("app", {"id": 15368, "slug": "untrusted"}),
        ("status", "queued"),
    ],
)
def test_check_identity_and_completion_are_verified(field, value):
    client = FakeClient()
    client.checks[0][field] = value
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


@pytest.mark.parametrize("count", [0, 2])
def test_missing_or_ambiguous_gate_blocks_promotion(count):
    client = FakeClient()
    client.checks = client.checks * count
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


def test_current_dev_without_ci_cannot_use_an_ancestor_gate():
    client = FakeClient()
    client.run_count = 0
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


def test_main_must_be_an_ancestor_of_candidate():
    client = FakeClient()
    client.ancestor = False
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


@pytest.mark.parametrize("branch", ["main", "dev"])
def test_changed_refs_before_write_abort_promotion(branch):
    client = FakeClient()
    client.changed_ref = branch
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


def test_gate_must_still_succeed_before_the_write():
    client = FakeClient()
    client.fail_gate_on_recheck = True
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == []


def test_server_rejection_does_not_attempt_force_or_protection_changes():
    client = FakeClient()
    client.reject_write = True
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.writes == [("git/refs/heads/main", {"sha": DEV, "force": False})]
    assert client.refs["main"] == MAIN


@pytest.fixture
def confirmation_waits(monkeypatch):
    waits = []

    def wait(seconds):
        waits.append(seconds)
        assert len(waits) < 100, "Post-write confirmation must remain bounded"

    monkeypatch.setattr("time.sleep", wait)
    return waits


def test_old_ref_reads_after_write_can_converge_without_another_patch(
    confirmation_waits,
):
    client = FakeClient()
    client.post_write_main = [MAIN, MAIN, DEV]
    result = promotion.promote(client, apply=True)
    assert result["main_updated"] is True
    assert client.post_write_reads == 3
    assert len(confirmation_waits) == 2
    assert client.writes == [("git/refs/heads/main", {"sha": DEV, "force": False})]


def test_successful_http_response_does_not_replace_bounded_post_write_verification(
    confirmation_waits,
):
    client = FakeClient()
    client.confirm_write = False
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert 1 < client.post_write_reads < 100
    assert confirmation_waits
    assert client.writes == [("git/refs/heads/main", {"sha": DEV, "force": False})]


@pytest.mark.parametrize(
    "observed", [OTHER, promotion.PromotionError("GitHub read failed: HTTP 503")]
)
def test_unexpected_ref_or_api_failure_after_write_fails_immediately(
    observed, confirmation_waits
):
    client = FakeClient()
    client.post_write_main = [observed, DEV]
    with pytest.raises(promotion.PromotionError):
        promotion.promote(client, apply=True)
    assert client.post_write_reads == 1
    assert confirmation_waits == []
    assert client.writes == [("git/refs/heads/main", {"sha": DEV, "force": False})]
