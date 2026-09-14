from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tools import download_candidate

_SHA = "a" * 40
_REPOSITORY = "imReese/Karkinos"
_PAYLOAD = b"candidate artifact zip"


def _run(run_id: int = 101, **overrides) -> dict[str, object]:
    return {
        "id": run_id,
        "name": "Release Candidate",
        "path": ".github/workflows/candidate.yml@refs/heads/main",
        "head_sha": _SHA,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": _REPOSITORY},
        "head_repository": {"full_name": _REPOSITORY},
        "updated_at": "2026-08-30T00:04:00Z",
        **overrides,
    }


def _artifact(run_id: int = 101, **overrides) -> dict[str, object]:
    return {
        "id": 701,
        "name": f"karkinos-candidate-{_SHA}",
        "expired": False,
        "size_in_bytes": len(_PAYLOAD),
        "digest": f"sha256:{hashlib.sha256(_PAYLOAD).hexdigest()}",
        "workflow_run": {
            "id": run_id,
            "head_sha": _SHA,
            "head_branch": "main",
        },
        **overrides,
    }


def _install_api(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runs: list[dict[str, object]] | None = None,
    artifacts: list[dict[str, object]] | None = None,
    payload: bytes = _PAYLOAD,
) -> list[str]:
    calls: list[str] = []

    def request(url: str, token: str) -> object:
        assert token == "test-token"
        calls.append(url)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/actions/workflows/candidate.yml/runs"):
            assert query["head_sha"] == [_SHA]
            assert query["branch"] == ["main"]
            values = runs if runs is not None else [_run()]
            return {"total_count": len(values), "workflow_runs": values}
        if "/actions/runs/" in parsed.path and parsed.path.endswith("/artifacts"):
            assert query["name"] == [f"karkinos-candidate-{_SHA}"]
            values = artifacts if artifacts is not None else [_artifact()]
            return {"total_count": len(values), "artifacts": values}
        raise AssertionError(url)

    def download(url: str, token: str) -> bytes:
        assert token == "test-token"
        assert url == (
            f"https://api.github.com/repos/{_REPOSITORY}/actions/artifacts/701/zip"
        )
        return payload

    monkeypatch.setattr(download_candidate, "_request", request)
    monkeypatch.setattr(download_candidate, "_download", download)
    return calls


def _fetch(output: Path) -> Path:
    return download_candidate.fetch_candidate(
        repository=_REPOSITORY,
        commit_sha=_SHA,
        output=output,
        token="test-token",
        api_url="https://api.github.com",
    )


def test_fetch_downloads_exact_sha_bundle_without_persisting_actions_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_api(
        monkeypatch,
        runs=[
            _run(updated_at="2026-08-30T00:03:00Z"),
            _run(102, event="workflow_run"),
            _run(103, conclusion="failure", updated_at="2026-08-30T00:05:00Z"),
        ],
        artifacts=[
            _artifact(
                102,
                archive_download_url="https://untrusted.example/token-collector",
            )
        ],
    )
    archive = tmp_path / "candidate.zip"
    assert _fetch(archive) == archive
    assert archive.read_bytes() == _PAYLOAD
    assert list(tmp_path.iterdir()) == [archive]
    assert "/actions/runs/102/artifacts?" in calls[1]
    assert len(calls) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"head_sha": "b" * 40},
        {"head_branch": "dev"},
        {"path": ".github/workflows/other.yml"},
        {"repository": {"full_name": "other/Karkinos"}},
        {"head_repository": {"full_name": "other/Karkinos"}},
        {"event": "pull_request"},
    ],
)
def test_fetch_rejects_unrelated_workflow_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict
) -> None:
    _install_api(monkeypatch, runs=[_run(**{"event": "workflow_run", **overrides})])
    with pytest.raises(ValueError, match="candidate_artifact_workflow_run_invalid"):
        _fetch(tmp_path / "candidate.zip")
    assert not list(tmp_path.iterdir())


def test_fetch_does_not_recover_historical_attempts_of_an_unsuccessful_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_api(monkeypatch, runs=[_run(conclusion="failure", run_attempt=3)])
    with pytest.raises(ValueError, match="candidate_successful_workflow_run_missing"):
        _fetch(tmp_path / "candidate.zip")


@pytest.mark.parametrize("artifacts", [[], [_artifact(), _artifact()]])
def test_fetch_requires_one_matching_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifacts: list[dict]
) -> None:
    _install_api(monkeypatch, artifacts=artifacts)
    with pytest.raises(ValueError, match="candidate_artifact_missing_or_ambiguous"):
        _fetch(tmp_path / "candidate.zip")


@pytest.mark.parametrize(
    "overrides",
    [
        {"expired": True},
        {"size_in_bytes": download_candidate._MAX_ARCHIVE_BYTES + 1},
        {"digest": "invalid"},
        {"workflow_run": {"id": 102, "head_sha": _SHA, "head_branch": "main"}},
        {"workflow_run": {"id": 101, "head_sha": "b" * 40, "head_branch": "main"}},
    ],
)
def test_fetch_rejects_expired_or_unbound_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict
) -> None:
    _install_api(monkeypatch, artifacts=[_artifact(**overrides)])
    with pytest.raises(ValueError, match="candidate_artifact_expired_or_invalid"):
        _fetch(tmp_path / "candidate.zip")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (_PAYLOAD[:-1], "candidate_artifact_download_size_mismatch"),
        (b"x" * len(_PAYLOAD), "candidate_artifact_download_digest_mismatch"),
    ],
)
def test_fetch_rejects_damaged_download_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes, error: str
) -> None:
    _install_api(monkeypatch, payload=payload)
    with pytest.raises(ValueError, match=error):
        _fetch(tmp_path / "candidate.zip")
    assert not list(tmp_path.iterdir())


def _legacy_selection() -> dict:
    return {
        "schema_version": "karkinos.candidate_artifact_selection.v1",
        "repository": _REPOSITORY,
        "commit_sha": _SHA,
        "workflow": {
            "name": "Release Candidate",
            "path": ".github/workflows/candidate.yml",
            "event": "push",
            "branch": "main",
            "run_id": 101,
            "run_attempt": 2,
            "completed_at": "2026-08-30T00:04:00Z",
        },
        "artifact": {
            "id": 701,
            "name": f"karkinos-candidate-{_SHA}-101-2",
            "digest": f"sha256:{hashlib.sha256(_PAYLOAD).hexdigest()}",
            "size_in_bytes": len(_PAYLOAD),
        },
    }


def test_legacy_selection_reader_preserves_published_v2_release_compatibility(
    tmp_path: Path,
) -> None:
    selection = _legacy_selection()
    receipt = tmp_path / "candidate-selection.json"
    receipt.write_text(json.dumps(selection), encoding="utf-8")
    assert (
        download_candidate.read_candidate_selection(
            receipt, expected_repository=_REPOSITORY, expected_commit_sha=_SHA
        )
        == selection
    )
    selection["workflow"]["run_attempt"] = 3
    receipt.write_text(json.dumps(selection), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_selection_artifact_invalid"):
        download_candidate.read_candidate_selection(
            receipt, expected_repository=_REPOSITORY, expected_commit_sha=_SHA
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
            token="test-token",
        )


def test_download_redirect_keeps_tokens_on_the_api_origin_only() -> None:
    handler = download_candidate._SafeRedirectHandler()
    request = urllib.request.Request(
        "https://api.github.com/artifacts/701/zip",
        headers={"Authorization": "Bearer test-token"},
    )
    same_origin = handler.redirect_request(
        request, None, 302, "", {}, "https://api.github.com/download/701"
    )
    assert same_origin.get_header("Authorization") == "Bearer test-token"
    cross_origin = handler.redirect_request(
        request, None, 302, "", {}, "https://storage.example/download/701"
    )
    assert cross_origin.get_header("Authorization") is None
    with pytest.raises(ValueError, match="candidate_artifact_redirect_invalid"):
        handler.redirect_request(
            request, None, 302, "", {}, "http://storage.example/download/701"
        )
