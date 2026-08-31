from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import download_candidate

_SHA = "a" * 40
_REPOSITORY = "imReese/Karkinos"
_PAYLOAD = b"candidate artifact zip"


def _run(
    *, run_id: int, run_attempt: int, created_at: str, updated_at: str
) -> dict[str, object]:
    return {
        "id": run_id,
        "run_attempt": run_attempt,
        "name": "Release Candidate",
        "path": ".github/workflows/candidate.yml@refs/heads/main",
        "head_sha": _SHA,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": _REPOSITORY},
        "head_repository": {"full_name": _REPOSITORY},
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _artifact(*, run_id: int, run_attempt: int, artifact_id: int) -> dict[str, object]:
    return {
        "id": artifact_id,
        "name": f"karkinos-candidate-{_SHA}-{run_id}-{run_attempt}",
        "expired": False,
        "size_in_bytes": len(_PAYLOAD),
        "digest": f"sha256:{hashlib.sha256(_PAYLOAD).hexdigest()}",
        "archive_download_url": (
            f"https://api.github.com/repos/{_REPOSITORY}/actions/artifacts/"
            f"{artifact_id}/zip"
        ),
        "created_at": "2026-08-30T00:02:00Z",
        "updated_at": "2026-08-30T00:02:01Z",
        "workflow_run": {
            "id": run_id,
            "head_sha": _SHA,
            "head_branch": "main",
        },
    }


def _install_successful_api(
    monkeypatch: pytest.MonkeyPatch,
    *,
    initial_runs: list[dict[str, object]],
    selected_run: dict[str, object],
    artifacts: list[dict[str, object]],
    confirmed_artifact: dict[str, object],
    final_runs: list[dict[str, object]] | None = None,
) -> None:
    run_pages = iter((initial_runs, final_runs or initial_runs))
    monkeypatch.setattr(
        download_candidate,
        "_workflow_run_pages",
        lambda **_kwargs: next(run_pages),
    )
    monkeypatch.setattr(
        download_candidate,
        "_successful_workflow_attempts",
        lambda runs, **_kwargs: runs,
    )
    monkeypatch.setattr(
        download_candidate,
        "_artifact_pages",
        lambda **_kwargs: artifacts,
    )

    def request(url: str, _token: str) -> object:
        if "/actions/artifacts/" in url:
            return confirmed_artifact
        if f"/actions/runs/{selected_run['id']}" in url:
            return selected_run
        raise AssertionError(url)

    monkeypatch.setattr(download_candidate, "_request", request)
    monkeypatch.setattr(download_candidate, "_download", lambda *_args: _PAYLOAD)


def test_fetch_selects_latest_successful_rerun_and_ignores_old_attempt_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    independently_queued = _run(
        run_id=102,
        run_attempt=1,
        created_at="2026-08-30T00:00:00Z",
        updated_at="2026-08-30T00:03:00Z",
    )
    latest_rerun = _run(
        run_id=101,
        run_attempt=2,
        created_at="2026-08-30T00:00:00Z",
        updated_at="2026-08-30T00:04:00Z",
    )
    old_attempt = _artifact(run_id=101, run_attempt=1, artifact_id=700)
    selected_artifact = _artifact(run_id=101, run_attempt=2, artifact_id=701)
    _install_successful_api(
        monkeypatch,
        initial_runs=[independently_queued, latest_rerun],
        selected_run=latest_rerun,
        artifacts=[old_attempt, selected_artifact],
        confirmed_artifact=selected_artifact,
    )
    archive = tmp_path / "candidate.zip"
    receipt = tmp_path / "candidate-selection.json"

    assert (
        download_candidate.fetch_candidate(
            repository=_REPOSITORY,
            commit_sha=_SHA,
            output=archive,
            metadata_output=receipt,
            token="secret",
            api_url="https://api.github.com",
        )
        == archive
    )
    assert archive.read_bytes() == _PAYLOAD
    selection = download_candidate.read_candidate_selection(
        receipt,
        expected_repository=_REPOSITORY,
        expected_commit_sha=_SHA,
    )
    assert selection["workflow"]["run_id"] == 101
    assert selection["workflow"]["run_attempt"] == 2
    assert selection["artifact"]["id"] == 701
    assert selection["artifact"]["digest"] == (
        f"sha256:{hashlib.sha256(_PAYLOAD).hexdigest()}"
    )


def test_fetch_rejects_duplicate_artifact_for_selected_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(
        run_id=101,
        run_attempt=2,
        created_at="2026-08-30T00:00:00Z",
        updated_at="2026-08-30T00:04:00Z",
    )
    artifact = _artifact(run_id=101, run_attempt=2, artifact_id=701)
    monkeypatch.setattr(download_candidate, "_workflow_run_pages", lambda **_: [run])
    monkeypatch.setattr(
        download_candidate, "_successful_workflow_attempts", lambda runs, **_: runs
    )
    monkeypatch.setattr(
        download_candidate, "_artifact_pages", lambda **_: [artifact, dict(artifact)]
    )

    with pytest.raises(ValueError, match="candidate_artifact_missing_or_ambiguous"):
        download_candidate.fetch_candidate(
            repository=_REPOSITORY,
            commit_sha=_SHA,
            output=tmp_path / "candidate.zip",
            token="secret",
            api_url="https://api.github.com",
        )


def test_fetch_fails_if_newer_successful_run_appears_during_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected_run = _run(
        run_id=101,
        run_attempt=2,
        created_at="2026-08-30T00:00:00Z",
        updated_at="2026-08-30T00:04:00Z",
    )
    newer_run = _run(
        run_id=103,
        run_attempt=1,
        created_at="2026-08-30T00:04:01Z",
        updated_at="2026-08-30T00:05:00Z",
    )
    artifact = _artifact(run_id=101, run_attempt=2, artifact_id=701)
    _install_successful_api(
        monkeypatch,
        initial_runs=[selected_run],
        selected_run=selected_run,
        artifacts=[artifact],
        confirmed_artifact=artifact,
        final_runs=[selected_run, newer_run],
    )
    archive = tmp_path / "candidate.zip"
    receipt = tmp_path / "candidate-selection.json"

    with pytest.raises(ValueError, match="candidate_artifact_selection_changed"):
        download_candidate.fetch_candidate(
            repository=_REPOSITORY,
            commit_sha=_SHA,
            output=archive,
            metadata_output=receipt,
            token="secret",
            api_url="https://api.github.com",
        )
    assert not archive.exists()
    assert not receipt.exists()


def test_fetch_fails_if_selected_artifact_identity_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(
        run_id=101,
        run_attempt=2,
        created_at="2026-08-30T00:00:00Z",
        updated_at="2026-08-30T00:04:00Z",
    )
    artifact = _artifact(run_id=101, run_attempt=2, artifact_id=701)
    changed = dict(artifact)
    changed["digest"] = "sha256:" + "b" * 64
    _install_successful_api(
        monkeypatch,
        initial_runs=[run],
        selected_run=run,
        artifacts=[artifact],
        confirmed_artifact=changed,
    )

    with pytest.raises(ValueError, match="candidate_artifact_remote_identity_changed"):
        download_candidate.fetch_candidate(
            repository=_REPOSITORY,
            commit_sha=_SHA,
            output=tmp_path / "candidate.zip",
            token="secret",
            api_url="https://api.github.com",
        )


def test_selection_receipt_rejects_attempt_or_artifact_tampering(
    tmp_path: Path,
) -> None:
    run = _run(
        run_id=101,
        run_attempt=2,
        created_at="2026-08-30T00:00:00Z",
        updated_at="2026-08-30T00:04:00Z",
    )
    artifact = _artifact(run_id=101, run_attempt=2, artifact_id=701)
    selection = download_candidate._selection_payload(
        repository=_REPOSITORY,
        commit_sha=_SHA,
        run=run,
        artifact=artifact,
    )
    selection["workflow"]["run_attempt"] = 3
    receipt = tmp_path / "candidate-selection.json"
    receipt.write_text(json.dumps(selection), encoding="utf-8")

    with pytest.raises(ValueError, match="candidate_selection_artifact_invalid"):
        download_candidate.read_candidate_selection(
            receipt,
            expected_repository=_REPOSITORY,
            expected_commit_sha=_SHA,
        )


def test_workflow_run_listing_fails_closed_when_pagination_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            {"total_count": 101, "workflow_runs": [{}] * 100},
            {"total_count": 102, "workflow_runs": [{}]},
        )
    )
    monkeypatch.setattr(download_candidate, "_request", lambda *_args: next(responses))

    with pytest.raises(ValueError, match="candidate_workflow_run_listing_changed"):
        download_candidate._workflow_run_pages(
            api_url="https://api.github.com",
            repository=_REPOSITORY,
            commit_sha=_SHA,
            token="secret",
        )


def test_successful_attempt_remains_selectable_after_a_later_failed_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _run(
        run_id=101,
        run_attempt=3,
        created_at="2026-08-30T00:00:00Z",
        updated_at="2026-08-30T00:06:00Z",
    )
    current["conclusion"] = "failure"
    attempts = {
        1: dict(current, run_attempt=1, updated_at="2026-08-30T00:02:00Z"),
        2: dict(current, run_attempt=2, updated_at="2026-08-30T00:04:00Z"),
        3: current,
    }
    attempts[1]["conclusion"] = "failure"
    attempts[2]["conclusion"] = "success"

    def request(url: str, _token: str) -> object:
        return attempts[int(url.rsplit("/", 1)[1])]

    monkeypatch.setattr(download_candidate, "_request", request)
    successful = download_candidate._successful_workflow_attempts(
        [current],
        api_url="https://api.github.com",
        repository=_REPOSITORY,
        commit_sha=_SHA,
        token="secret",
    )

    assert [(item["id"], item["run_attempt"]) for item in successful] == [(101, 2)]
