from __future__ import annotations

from copy import deepcopy

import pytest

from tools.verify_release_source_ci import (
    GitHubActionsClient,
    SourceCIVerificationError,
    select_latest_exact_run,
    validate_workflow_identity,
    verify_required_jobs,
    wait_for_verified_source_ci,
)

_SHA = "a" * 40
_REPOSITORY = "imReese/Karkinos"
_WORKFLOW_ID = 17
_WORKFLOW_PATH = ".github/workflows/ci.yml"
_REQUIRED_JOBS = ("Code CI gate", "Repository acceptance audit")


def _workflow_payload(**overrides):
    payload = {
        "id": _WORKFLOW_ID,
        "name": "CI",
        "path": _WORKFLOW_PATH,
        "state": "active",
    }
    payload.update(overrides)
    return payload


def _run(**overrides):
    payload = {
        "id": 101,
        "run_number": 33,
        "run_attempt": 2,
        "workflow_id": _WORKFLOW_ID,
        "path": _WORKFLOW_PATH,
        "head_branch": "main",
        "head_sha": _SHA,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.example/actions/runs/101",
        "repository": {"full_name": _REPOSITORY},
        "head_repository": {"full_name": _REPOSITORY},
    }
    payload.update(overrides)
    return payload


def _runs(*runs):
    return {"total_count": len(runs), "workflow_runs": list(runs)}


def _job(name: str, job_id: int, **overrides):
    payload = {
        "id": job_id,
        "name": name,
        "head_sha": _SHA,
        "status": "completed",
        "conclusion": "success",
    }
    payload.update(overrides)
    return payload


def _jobs(*jobs):
    return {"total_count": len(jobs), "jobs": list(jobs)}


class _FakeClient:
    def __init__(self, *, workflow=None, runs=None, jobs=None):
        self.workflow_payload = workflow or _workflow_payload()
        self.runs_payload = runs or _runs(_run())
        self.jobs_payload = jobs or _jobs(
            _job("Code CI gate", 201),
            _job("Repository acceptance audit", 202),
        )
        self.requested_run_id: int | None = None

    def workflow(self, workflow_file: str):
        assert workflow_file == "ci.yml"
        return self.workflow_payload

    def workflow_runs(self, **kwargs):
        assert kwargs == {
            "workflow_id": _WORKFLOW_ID,
            "branch": "main",
            "event": "push",
            "commit_sha": _SHA,
        }
        return self.runs_payload

    def workflow_run_jobs(self, *, run_id: int):
        self.requested_run_id = run_id
        return self.jobs_payload


def _wait(client: _FakeClient):
    return wait_for_verified_source_ci(
        client,
        repository=_REPOSITORY,
        workflow_file="ci.yml",
        workflow_name="CI",
        workflow_path=_WORKFLOW_PATH,
        branch="main",
        event="push",
        commit_sha=_SHA,
        required_job_names=_REQUIRED_JOBS,
        timeout_seconds=0,
        poll_interval_seconds=1,
    )


def test_api_client_requires_a_token() -> None:
    with pytest.raises(SourceCIVerificationError, match="token_missing"):
        GitHubActionsClient(
            api_url="https://api.github.example",
            repository=_REPOSITORY,
            token="",
            api_version="2026-03-10",
        )


def test_api_request_failure_is_inconclusive_and_closed(monkeypatch) -> None:
    def fail_request(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(
        "tools.verify_release_source_ci.urlopen",
        fail_request,
    )
    client = GitHubActionsClient(
        api_url="https://api.github.example",
        repository=_REPOSITORY,
        token="test-token",
        api_version="2026-03-10",
    )

    with pytest.raises(SourceCIVerificationError, match="request_inconclusive"):
        client.workflow("ci.yml")


def test_exact_successful_main_run_and_required_jobs_are_accepted() -> None:
    client = _FakeClient()

    result = _wait(client)

    assert result.commit_sha == _SHA
    assert result.run_id == 101
    assert result.run_attempt == 2
    assert result.required_job_ids == (201, 202)
    assert client.requested_run_id == 101


def test_latest_successful_job_results_allow_partial_rerun_evidence() -> None:
    jobs = _jobs(
        _job("Code CI gate", 301, run_attempt=2),
        _job("Repository acceptance audit", 202, run_attempt=1),
    )

    result = _wait(_FakeClient(jobs=jobs))

    assert result.run_attempt == 2
    assert result.required_job_ids == (301, 202)


def test_polling_can_observe_missing_pending_then_stable_success() -> None:
    class SequencedClient(_FakeClient):
        def __init__(self):
            super().__init__()
            self.payloads = iter(
                (
                    _runs(),
                    _runs(_run(status="queued", conclusion=None)),
                    _runs(_run()),
                    _runs(_run()),
                )
            )

        def workflow_runs(self, **kwargs):
            return next(self.payloads)

    result = wait_for_verified_source_ci(
        SequencedClient(),
        repository=_REPOSITORY,
        workflow_file="ci.yml",
        workflow_name="CI",
        workflow_path=_WORKFLOW_PATH,
        branch="main",
        event="push",
        commit_sha=_SHA,
        required_job_names=_REQUIRED_JOBS,
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )

    assert result.run_id == 101


def test_run_snapshot_change_is_rechecked_before_acceptance() -> None:
    class ChangingClient(_FakeClient):
        def __init__(self):
            super().__init__()
            self.payloads = iter(
                (
                    _runs(_run()),
                    _runs(_run(status="queued", conclusion=None, run_attempt=3)),
                    _runs(_run(run_attempt=3)),
                    _runs(_run(run_attempt=3)),
                )
            )

        def workflow_runs(self, **kwargs):
            return next(self.payloads)

    result = wait_for_verified_source_ci(
        ChangingClient(),
        repository=_REPOSITORY,
        workflow_file="ci.yml",
        workflow_name="CI",
        workflow_path=_WORKFLOW_PATH,
        branch="main",
        event="push",
        commit_sha=_SHA,
        required_job_names=_REQUIRED_JOBS,
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )

    assert result.run_attempt == 3


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("id", 0, "workflow_id_invalid"),
        ("name", "Release", "workflow_name_mismatch"),
        ("path", ".github/workflows/other.yml", "workflow_path_mismatch"),
        ("state", "disabled_manually", "workflow_not_active"),
    ),
)
def test_workflow_identity_mismatch_fails_closed(field, value, error) -> None:
    payload = _workflow_payload(**{field: value})

    with pytest.raises(SourceCIVerificationError, match=error):
        validate_workflow_identity(
            payload, expected_name="CI", expected_path=_WORKFLOW_PATH
        )


@pytest.mark.parametrize(
    ("overrides", "error"),
    (
        ({"workflow_id": 18}, "run_identity_mismatch"),
        ({"head_branch": "feature"}, "run_identity_mismatch"),
        ({"head_sha": "b" * 40}, "run_identity_mismatch"),
        ({"event": "workflow_dispatch"}, "run_identity_mismatch"),
        ({"path": ".github/workflows/other.yml"}, "run_path_mismatch"),
        (
            {"repository": {"full_name": "other/repository"}},
            "run_repository_mismatch",
        ),
        (
            {"head_repository": {"full_name": "fork/repository"}},
            "run_head_repository_mismatch",
        ),
    ),
)
def test_run_identity_mismatch_fails_closed(overrides, error) -> None:
    with pytest.raises(SourceCIVerificationError, match=error):
        select_latest_exact_run(
            _runs(_run(**overrides)),
            repository=_REPOSITORY,
            workflow_id=_WORKFLOW_ID,
            workflow_path=_WORKFLOW_PATH,
            branch="main",
            event="push",
            commit_sha=_SHA,
        )


def test_latest_exact_run_is_selected_deterministically() -> None:
    older = _run(id=100, run_number=32, run_attempt=1)
    latest = _run(id=102, run_number=34, run_attempt=1)

    selected = select_latest_exact_run(
        _runs(older, latest),
        repository=_REPOSITORY,
        workflow_id=_WORKFLOW_ID,
        workflow_path=_WORKFLOW_PATH,
        branch="main",
        event="push",
        commit_sha=_SHA,
    )

    assert selected is latest


@pytest.mark.parametrize("conclusion", ("failure", "cancelled", "skipped", None))
def test_non_successful_source_run_fails_closed(conclusion) -> None:
    client = _FakeClient(runs=_runs(_run(conclusion=conclusion)))

    with pytest.raises(SourceCIVerificationError, match="run_not_success"):
        _wait(client)


def test_missing_or_pending_source_run_times_out_closed() -> None:
    with pytest.raises(SourceCIVerificationError, match="timeout:missing"):
        _wait(_FakeClient(runs=_runs()))

    with pytest.raises(SourceCIVerificationError, match="timeout:queued"):
        _wait(_FakeClient(runs=_runs(_run(status="queued", conclusion=None))))


@pytest.mark.parametrize(
    ("jobs", "error"),
    (
        (
            _jobs(_job("Repository acceptance audit", 202)),
            "required_job_missing:Code CI gate",
        ),
        (
            _jobs(
                _job("Code CI gate", 201),
                _job("Code CI gate", 203),
                _job("Repository acceptance audit", 202),
            ),
            "required_job_ambiguous:Code CI gate",
        ),
        (
            _jobs(
                _job("Code CI gate", 201, conclusion="failure"),
                _job("Repository acceptance audit", 202),
            ),
            "required_job_not_success:Code CI gate",
        ),
        (
            _jobs(
                _job("Code CI gate", 201, head_sha="b" * 40),
                _job("Repository acceptance audit", 202),
            ),
            "required_job_sha_mismatch:Code CI gate",
        ),
    ),
)
def test_required_job_evidence_failure_is_closed(jobs, error) -> None:
    with pytest.raises(SourceCIVerificationError, match=error):
        verify_required_jobs(
            deepcopy(jobs),
            required_job_names=_REQUIRED_JOBS,
            commit_sha=_SHA,
        )


@pytest.mark.parametrize(
    "payload",
    (
        {"total_count": 1, "workflow_runs": []},
        {"total_count": 1, "jobs": []},
    ),
)
def test_incomplete_api_pagination_fails_closed(payload) -> None:
    if "workflow_runs" in payload:
        with pytest.raises(SourceCIVerificationError, match="pagination_incomplete"):
            select_latest_exact_run(
                payload,
                repository=_REPOSITORY,
                workflow_id=_WORKFLOW_ID,
                workflow_path=_WORKFLOW_PATH,
                branch="main",
                event="push",
                commit_sha=_SHA,
            )
    else:
        with pytest.raises(SourceCIVerificationError, match="pagination_incomplete"):
            verify_required_jobs(
                payload,
                required_job_names=_REQUIRED_JOBS,
                commit_sha=_SHA,
            )
