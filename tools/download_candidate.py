#!/usr/bin/env python3
"""Fetch one immutable candidate bundle from GitHub Actions."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024
_MAX_ZIP_MEMBERS = 200_000
_MAX_ACTIONS_RECORDS = 10_000
_MAX_WORKFLOW_ATTEMPTS = 100
_CANDIDATE_WORKFLOW_NAME = "Release Candidate"
_CANDIDATE_WORKFLOW_PATH = ".github/workflows/candidate.yml"
_SELECTION_SCHEMA = "karkinos.candidate_artifact_selection.v1"


def _endpoint(url: str) -> tuple[str, int]:
    parsed = urlsplit(url)
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 0)
    except ValueError as exc:
        raise ValueError("candidate_artifact_url_invalid") from exc
    return parsed.hostname or "", port


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow only HTTPS redirects and never leak API tokens cross-origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_https_url(newurl, "candidate_artifact_redirect_invalid")
        old_host, old_port = _endpoint(req.full_url)
        new_host, new_port = _endpoint(newurl)
        request_headers = dict(req.headers)
        if (old_host.lower(), old_port) != (new_host.lower(), new_port):
            request_headers.pop("Authorization", None)
            request_headers.pop("authorization", None)
        return urllib.request.Request(
            newurl,
            data=req.data,
            headers=request_headers,
            origin_req_host=req.origin_req_host,
            unverifiable=True,
            method=req.get_method(),
        )


_SAFE_OPENER = urllib.request.build_opener(_SafeRedirectHandler())


def _require_https_url(url: str, error: str) -> str:
    if "\x00" in url:
        raise ValueError(error)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(error)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(error) from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(error)
    return url


def _open(request: urllib.request.Request, *, timeout: float):
    try:
        return _SAFE_OPENER.open(request, timeout=timeout)
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError("candidate_artifact_request_inconclusive") from exc


def _content_length(response) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate_artifact_content_length_invalid") from exc
    if parsed < 0 or parsed > _MAX_ARCHIVE_BYTES:
        raise ValueError("candidate_artifact_too_large")
    return parsed


def _read_limited(response) -> bytes:
    declared_size = _content_length(response)
    if declared_size is not None and declared_size > _MAX_ARCHIVE_BYTES:
        raise ValueError("candidate_artifact_too_large")
    chunks: list[bytes] = []
    total = 0
    while total <= _MAX_ARCHIVE_BYTES:
        chunk = response.read(min(1024 * 1024, _MAX_ARCHIVE_BYTES + 1 - total))
        if not chunk:
            payload = b"".join(chunks)
            if declared_size is not None and len(payload) != declared_size:
                raise ValueError("candidate_artifact_content_length_mismatch")
            return payload
        chunks.append(chunk)
        total += len(chunk)
    raise ValueError("candidate_artifact_too_large")


def _request(url: str, token: str) -> object:
    _require_https_url(url, "candidate_artifact_api_url_invalid")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "karkinos-release-candidate-fetcher/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with _open(request, timeout=60) as response:
            if getattr(response, "status", 200) != 200:
                raise ValueError("candidate_artifact_api_status_unexpected")
            return json.loads(_read_limited(response).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("candidate_artifact_request_inconclusive") from exc


def _download(url: str, token: str) -> bytes:
    _require_https_url(url, "candidate_artifact_download_url_invalid")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "karkinos-release-candidate-fetcher/1",
        },
    )
    try:
        with _open(request, timeout=120) as response:
            if getattr(response, "status", 200) != 200:
                raise ValueError("candidate_artifact_download_status_unexpected")
            return _read_limited(response)
    except ValueError:
        raise


def _reject_symlink_ancestors(path: Path) -> None:
    """Reject an output path that would write through an existing symlink."""
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError("candidate_artifact_output_symlink_unsupported")
        if ancestor.parent == ancestor:
            break


def _safe_zip_extract(payload: bytes, destination: Path) -> None:
    if len(payload) > _MAX_ARCHIVE_BYTES:
        raise ValueError("candidate_artifact_too_large")
    _reject_symlink_ancestors(destination.parent)
    if os.path.lexists(destination):
        raise ValueError("candidate_artifact_output_already_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.extract-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) > _MAX_ZIP_MEMBERS:
                raise ValueError("candidate_artifact_member_count_too_large")
            if not members:
                raise ValueError("candidate_artifact_empty")
            if any(
                member.file_size < 0 or member.compress_size < 0 for member in members
            ):
                raise ValueError("candidate_artifact_size_invalid")
            if sum(member.file_size for member in members) > _MAX_EXTRACTED_BYTES:
                raise ValueError("candidate_artifact_too_large")
            seen: set[str] = set()
            for member in members:
                relative = Path(member.filename)
                if (
                    not member.filename
                    or "\x00" in member.filename
                    or relative.is_absolute()
                    or ".." in relative.parts
                    or "\\" in member.filename
                ):
                    raise ValueError("candidate_artifact_path_unsafe")
                target = (staging / relative).resolve()
                if staging not in target.parents and target != staging:
                    raise ValueError("candidate_artifact_path_escape")
                canonical_name = target.relative_to(staging).as_posix()
                if canonical_name in seen:
                    raise ValueError("candidate_artifact_duplicate_path")
                seen.add(canonical_name)
                mode = (member.external_attr >> 16) & 0o170000
                if stat.S_ISLNK(mode):
                    raise ValueError("candidate_artifact_symlink_unsupported")
                if member.is_dir():
                    if mode not in {0, 0o040000}:
                        raise ValueError("candidate_artifact_member_unsupported")
                    if target.exists() and not target.is_dir():
                        raise ValueError("candidate_artifact_path_conflict")
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if mode not in {0, 0o100000}:
                    raise ValueError("candidate_artifact_member_unsupported")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ValueError("candidate_artifact_duplicate_path")
                with archive.open(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
        os.replace(staging, destination)
    except zipfile.BadZipFile as exc:
        raise ValueError("candidate_artifact_zip_invalid") from exc
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _workflow_run_pages(
    *, api_url: str, repository: str, commit_sha: str, token: str
) -> list[object]:
    runs: list[object] = []
    page = 1
    expected_total: int | None = None
    while True:
        query = urlencode(
            {
                "branch": "main",
                "head_sha": commit_sha,
                "per_page": 100,
                "page": page,
            }
        )
        listing = _request(
            f"{api_url}/repos/{repository}/actions/workflows/candidate.yml/runs?{query}",
            token,
        )
        if not isinstance(listing, dict):
            raise ValueError("candidate_workflow_run_listing_invalid")
        values = listing.get("workflow_runs")
        total = listing.get("total_count")
        if not isinstance(values, list) or type(total) is not int or total < 0:
            raise ValueError("candidate_workflow_run_listing_invalid")
        if expected_total is None:
            expected_total = total
        elif expected_total != total:
            raise ValueError("candidate_workflow_run_listing_changed")
        runs.extend(values)
        if len(runs) > _MAX_ACTIONS_RECORDS:
            raise ValueError("candidate_workflow_run_listing_too_large")
        if len(runs) >= total:
            break
        if not values:
            raise ValueError("candidate_workflow_run_pagination_incomplete")
        page += 1
    if expected_total != len(runs):
        raise ValueError("candidate_workflow_run_pagination_incomplete")
    return runs


def _artifact_pages(
    *, api_url: str, repository: str, token: str, run_id: int, name: str
) -> list[object]:
    artifacts: list[object] = []
    page = 1
    expected_total: int | None = None
    while True:
        query = urlencode({"per_page": 100, "page": page, "name": name})
        listing = _request(
            f"{api_url}/repos/{repository}/actions/runs/{run_id}/artifacts?{query}",
            token,
        )
        if not isinstance(listing, dict):
            raise ValueError("candidate_artifact_listing_invalid")
        values = listing.get("artifacts")
        total = listing.get("total_count")
        if not isinstance(values, list) or not isinstance(total, int) or total < 0:
            raise ValueError("candidate_artifact_listing_invalid")
        if expected_total is None:
            expected_total = total
        elif expected_total != total:
            raise ValueError("candidate_artifact_listing_changed")
        artifacts.extend(values)
        if len(artifacts) > _MAX_ACTIONS_RECORDS:
            raise ValueError("candidate_artifact_listing_too_large")
        if len(artifacts) >= total:
            break
        if not values:
            raise ValueError("candidate_artifact_pagination_incomplete")
        page += 1
    if expected_total != len(artifacts):
        raise ValueError("candidate_artifact_pagination_incomplete")
    return artifacts


def _timestamp(value: object, error: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(error)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(error) from exc
    if parsed.tzinfo is None:
        raise ValueError(error)
    return parsed


def _workflow_run_identity(
    run: object, *, repository: str, commit_sha: str, require_success: bool = True
) -> tuple[object, ...]:
    if not isinstance(run, dict):
        raise ValueError("candidate_artifact_workflow_run_invalid")
    run_id = run.get("id")
    run_attempt = run.get("run_attempt")
    path = run.get("path")
    repository_summary = run.get("repository")
    head_repository = run.get("head_repository")
    status = run.get("status")
    conclusion = run.get("conclusion")
    if (
        type(run_id) is not int
        or run_id <= 0
        or type(run_attempt) is not int
        or run_attempt <= 0
        or run.get("name") != _CANDIDATE_WORKFLOW_NAME
        or not isinstance(path, str)
        or path.split("@", 1)[0] != _CANDIDATE_WORKFLOW_PATH
        or run.get("head_sha") != commit_sha
        or run.get("head_branch") != "main"
        or run.get("event") not in {"push", "workflow_dispatch"}
        or not isinstance(status, str)
        or (conclusion is not None and not isinstance(conclusion, str))
        or not isinstance(repository_summary, dict)
        or repository_summary.get("full_name") != repository
        or not isinstance(head_repository, dict)
        or head_repository.get("full_name") != repository
    ):
        raise ValueError("candidate_artifact_workflow_run_invalid")
    if require_success and (status != "completed" or conclusion != "success"):
        raise ValueError("candidate_artifact_workflow_run_invalid")
    created_at = _timestamp(
        run.get("created_at"), "candidate_artifact_workflow_run_invalid"
    )
    updated_at = _timestamp(
        run.get("updated_at"), "candidate_artifact_workflow_run_invalid"
    )
    if updated_at < created_at:
        raise ValueError("candidate_artifact_workflow_run_invalid")
    return (
        run_id,
        run_attempt,
        run["event"],
        run["head_sha"],
        run["head_branch"],
        status,
        conclusion,
        path,
        created_at,
        updated_at,
    )


def _successful_workflow_attempts(
    runs: list[object],
    *,
    api_url: str,
    repository: str,
    commit_sha: str,
    token: str,
) -> list[object]:
    successful: list[object] = []
    seen_run_ids: set[int] = set()
    for run in runs:
        summary_identity = _workflow_run_identity(
            run,
            repository=repository,
            commit_sha=commit_sha,
            require_success=False,
        )
        run_id = summary_identity[0]
        run_attempt = summary_identity[1]
        assert isinstance(run_id, int)
        assert isinstance(run_attempt, int)
        if run_id in seen_run_ids:
            raise ValueError("candidate_workflow_run_listing_ambiguous")
        seen_run_ids.add(run_id)
        if run_attempt > _MAX_WORKFLOW_ATTEMPTS:
            raise ValueError("candidate_workflow_run_attempts_too_many")
        for attempt in range(1, run_attempt + 1):
            attempt_run = _request(
                f"{api_url}/repos/{repository}/actions/runs/{run_id}/attempts/{attempt}",
                token,
            )
            attempt_identity = _workflow_run_identity(
                attempt_run,
                repository=repository,
                commit_sha=commit_sha,
                require_success=False,
            )
            if attempt_identity[0] != run_id or attempt_identity[1] != attempt:
                raise ValueError("candidate_artifact_workflow_run_invalid")
            if attempt_identity[5:7] == ("completed", "success"):
                successful.append(attempt_run)
    return successful


def _select_workflow_run(
    runs: list[object], *, repository: str, commit_sha: str
) -> dict[str, object]:
    matches: list[tuple[tuple[object, ...], dict[str, object]]] = []
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("candidate_workflow_run_listing_invalid")
        if run.get("head_sha") != commit_sha:
            raise ValueError("candidate_workflow_run_listing_invalid")
        identity = _workflow_run_identity(
            run, repository=repository, commit_sha=commit_sha
        )
        matches.append((identity, run))
    if not matches:
        raise ValueError("candidate_successful_workflow_run_missing")
    # Completion time makes a later rerun win even though its run id is unchanged.
    # Run id and attempt are deterministic tie-breakers for independently queued runs.
    return max(matches, key=lambda item: (item[0][-1], item[0][0], item[0][1]))[1]


def _artifact_identity(
    artifact: object,
    *,
    expected_name: str,
    expected_run_id: int,
    commit_sha: str,
) -> tuple[object, ...]:
    if not isinstance(artifact, dict):
        raise ValueError("candidate_artifact_expired_or_invalid")
    workflow_run = artifact.get("workflow_run")
    digest = artifact.get("digest")
    digest_match = (
        _ARTIFACT_DIGEST.fullmatch(digest) if isinstance(digest, str) else None
    )
    download_url = artifact.get("archive_download_url")
    artifact_id = artifact.get("id")
    size = artifact.get("size_in_bytes")
    if (
        artifact.get("name") != expected_name
        or type(artifact.get("expired")) is not bool
        or artifact.get("expired")
        or type(artifact_id) is not int
        or artifact_id <= 0
        or type(size) is not int
        or size <= 0
        or size > _MAX_ARCHIVE_BYTES
        or not isinstance(workflow_run, dict)
        or workflow_run.get("head_sha") != commit_sha
        or workflow_run.get("head_branch") != "main"
        or workflow_run.get("id") != expected_run_id
        or not isinstance(download_url, str)
        or digest_match is None
    ):
        raise ValueError("candidate_artifact_expired_or_invalid")
    _require_https_url(download_url, "candidate_artifact_download_url_invalid")
    created_at = _timestamp(
        artifact.get("created_at"), "candidate_artifact_expired_or_invalid"
    )
    updated_at = _timestamp(
        artifact.get("updated_at"), "candidate_artifact_expired_or_invalid"
    )
    if updated_at < created_at:
        raise ValueError("candidate_artifact_expired_or_invalid")
    return (
        artifact_id,
        expected_name,
        digest,
        size,
        download_url,
        created_at,
        updated_at,
        expected_run_id,
        commit_sha,
    )


def _selection_payload(
    *,
    repository: str,
    commit_sha: str,
    run: dict[str, object],
    artifact: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": _SELECTION_SCHEMA,
        "repository": repository,
        "commit_sha": commit_sha,
        "workflow": {
            "name": _CANDIDATE_WORKFLOW_NAME,
            "path": _CANDIDATE_WORKFLOW_PATH,
            "event": run["event"],
            "branch": "main",
            "run_id": run["id"],
            "run_attempt": run["run_attempt"],
            "completed_at": run["updated_at"],
        },
        "artifact": {
            "id": artifact["id"],
            "name": artifact["name"],
            "digest": artifact["digest"],
            "size_in_bytes": artifact["size_in_bytes"],
        },
    }


def read_candidate_selection(
    path: Path, *, expected_repository: str, expected_commit_sha: str
) -> dict[str, object]:
    """Validate a persisted GitHub Actions run/artifact selection receipt."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("candidate_selection_invalid")
    try:
        selection = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate_selection_invalid") from exc
    if (
        not isinstance(selection, dict)
        or set(selection)
        != {"schema_version", "repository", "commit_sha", "workflow", "artifact"}
        or selection.get("schema_version") != _SELECTION_SCHEMA
        or selection.get("repository") != expected_repository
        or selection.get("commit_sha") != expected_commit_sha
    ):
        raise ValueError("candidate_selection_invalid")
    workflow = selection.get("workflow")
    artifact = selection.get("artifact")
    if not isinstance(workflow, dict) or set(workflow) != {
        "name",
        "path",
        "event",
        "branch",
        "run_id",
        "run_attempt",
        "completed_at",
    }:
        raise ValueError("candidate_selection_workflow_invalid")
    if (
        workflow.get("name") != _CANDIDATE_WORKFLOW_NAME
        or workflow.get("path") != _CANDIDATE_WORKFLOW_PATH
        or workflow.get("event") not in {"push", "workflow_dispatch"}
        or workflow.get("branch") != "main"
        or type(workflow.get("run_id")) is not int
        or workflow["run_id"] <= 0
        or type(workflow.get("run_attempt")) is not int
        or workflow["run_attempt"] <= 0
    ):
        raise ValueError("candidate_selection_workflow_invalid")
    _timestamp(workflow.get("completed_at"), "candidate_selection_workflow_invalid")
    expected_name = (
        f"karkinos-candidate-{expected_commit_sha}-"
        f"{workflow['run_id']}-{workflow['run_attempt']}"
    )
    if not isinstance(artifact, dict) or set(artifact) != {
        "id",
        "name",
        "digest",
        "size_in_bytes",
    }:
        raise ValueError("candidate_selection_artifact_invalid")
    if (
        type(artifact.get("id")) is not int
        or artifact["id"] <= 0
        or artifact.get("name") != expected_name
        or not isinstance(artifact.get("digest"), str)
        or _ARTIFACT_DIGEST.fullmatch(artifact["digest"]) is None
        or type(artifact.get("size_in_bytes")) is not int
        or artifact["size_in_bytes"] <= 0
        or artifact["size_in_bytes"] > _MAX_ARCHIVE_BYTES
    ):
        raise ValueError("candidate_selection_artifact_invalid")
    return selection


def fetch_candidate(
    *,
    repository: str,
    commit_sha: str,
    output: Path,
    token: str,
    api_url: str,
    metadata_output: Path | None = None,
) -> Path:
    if _FULL_SHA.fullmatch(commit_sha) is None:
        raise ValueError("candidate_commit_sha_invalid")
    if not token:
        raise ValueError("candidate_artifact_token_missing")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("candidate_repository_invalid")
    api_url = _require_https_url(
        api_url.rstrip("/"), "candidate_artifact_api_url_invalid"
    )
    output = output.expanduser().absolute()
    workflow_runs = _successful_workflow_attempts(
        _workflow_run_pages(
            api_url=api_url,
            repository=repository,
            commit_sha=commit_sha,
            token=token,
        ),
        api_url=api_url,
        repository=repository,
        commit_sha=commit_sha,
        token=token,
    )
    selected_run = _select_workflow_run(
        workflow_runs, repository=repository, commit_sha=commit_sha
    )
    selected_run_identity = _workflow_run_identity(
        selected_run, repository=repository, commit_sha=commit_sha
    )
    run_id = selected_run["id"]
    run_attempt = selected_run["run_attempt"]
    assert isinstance(run_id, int)
    assert isinstance(run_attempt, int)
    name = f"karkinos-candidate-{commit_sha}-{run_id}-{run_attempt}"
    matches = [
        item
        for item in _artifact_pages(
            api_url=api_url,
            repository=repository,
            token=token,
            run_id=run_id,
            name=name,
        )
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError("candidate_artifact_missing_or_ambiguous")
    artifact = matches[0]
    artifact_identity = _artifact_identity(
        artifact,
        expected_name=name,
        expected_run_id=run_id,
        commit_sha=commit_sha,
    )
    workflow_run = _request(
        f"{api_url}/repos/{repository}/actions/runs/{run_id}/attempts/{run_attempt}",
        token,
    )
    if (
        _workflow_run_identity(
            workflow_run, repository=repository, commit_sha=commit_sha
        )
        != selected_run_identity
    ):
        raise ValueError("candidate_artifact_workflow_run_invalid")
    download_url = artifact["archive_download_url"]
    artifact_digest = artifact["digest"]
    assert isinstance(download_url, str)
    assert isinstance(artifact_digest, str)
    digest_match = _ARTIFACT_DIGEST.fullmatch(artifact_digest)
    assert digest_match is not None
    _require_https_url(download_url, "candidate_artifact_download_url_invalid")
    _reject_symlink_ancestors(output.parent)
    if os.path.lexists(output):
        raise ValueError("candidate_output_already_exists")
    resolved_metadata: Path | None = None
    if metadata_output is not None:
        resolved_metadata = metadata_output.expanduser().absolute()
        if resolved_metadata == output:
            raise ValueError("candidate_selection_output_invalid")
        _reject_symlink_ancestors(resolved_metadata.parent)
        if os.path.lexists(resolved_metadata):
            raise ValueError("candidate_selection_output_already_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    if resolved_metadata is not None:
        resolved_metadata.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.download-{uuid.uuid4().hex}")
    metadata_temporary = (
        resolved_metadata.with_name(
            f".{resolved_metadata.name}.selection-{uuid.uuid4().hex}"
        )
        if resolved_metadata is not None
        else None
    )
    try:
        payload = _download(download_url, token)
        if len(payload) != artifact["size_in_bytes"]:
            raise ValueError("candidate_artifact_download_size_mismatch")
        if hashlib.sha256(payload).hexdigest() != digest_match.group(1):
            raise ValueError("candidate_artifact_download_digest_mismatch")
        confirmed_artifact = _request(
            f"{api_url}/repos/{repository}/actions/artifacts/{artifact['id']}", token
        )
        if (
            _artifact_identity(
                confirmed_artifact,
                expected_name=name,
                expected_run_id=run_id,
                commit_sha=commit_sha,
            )
            != artifact_identity
        ):
            raise ValueError("candidate_artifact_remote_identity_changed")
        confirmed_run = _request(
            f"{api_url}/repos/{repository}/actions/runs/{run_id}/attempts/{run_attempt}",
            token,
        )
        if (
            _workflow_run_identity(
                confirmed_run, repository=repository, commit_sha=commit_sha
            )
            != selected_run_identity
        ):
            raise ValueError("candidate_artifact_workflow_run_changed")
        latest_run = _select_workflow_run(
            _successful_workflow_attempts(
                _workflow_run_pages(
                    api_url=api_url,
                    repository=repository,
                    commit_sha=commit_sha,
                    token=token,
                ),
                api_url=api_url,
                repository=repository,
                commit_sha=commit_sha,
                token=token,
            ),
            repository=repository,
            commit_sha=commit_sha,
        )
        if (
            _workflow_run_identity(
                latest_run, repository=repository, commit_sha=commit_sha
            )
            != selected_run_identity
        ):
            raise ValueError("candidate_artifact_selection_changed")
        with temporary.open("xb") as stream:
            stream.write(payload)
        if metadata_temporary is not None:
            selection = _selection_payload(
                repository=repository,
                commit_sha=commit_sha,
                run=selected_run,
                artifact=artifact,
            )
            metadata_temporary.write_text(
                json.dumps(selection, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            read_candidate_selection(
                metadata_temporary,
                expected_repository=repository,
                expected_commit_sha=commit_sha,
            )
        if os.path.lexists(output):
            raise ValueError("candidate_output_already_exists")
        if resolved_metadata is not None and os.path.lexists(resolved_metadata):
            raise ValueError("candidate_selection_output_already_exists")
        os.replace(temporary, output)
        if resolved_metadata is not None and metadata_temporary is not None:
            try:
                os.replace(metadata_temporary, resolved_metadata)
            except BaseException:
                output.unlink(missing_ok=True)
                raise
    finally:
        temporary.unlink(missing_ok=True)
        if metadata_temporary is not None:
            metadata_temporary.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch = subparsers.add_parser(
        "fetch", help="download one candidate Actions artifact"
    )
    fetch.add_argument("--repository", required=True)
    fetch.add_argument("--commit-sha", required=True)
    fetch.add_argument("--output", type=Path, required=True)
    fetch.add_argument("--metadata-output", type=Path)
    fetch.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    fetch.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    extract = subparsers.add_parser(
        "extract", help="safely extract an Actions artifact zip"
    )
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "extract":
            archive = args.archive.expanduser().absolute()
            if archive.is_symlink() or not archive.is_file():
                raise ValueError("candidate_artifact_archive_invalid")
            if archive.stat().st_size > _MAX_ARCHIVE_BYTES:
                raise ValueError("candidate_artifact_too_large")
            output = args.output.expanduser().absolute()
            _safe_zip_extract(archive.read_bytes(), output)
            print(
                json.dumps(
                    {"status": "extracted", "directory": str(args.output.resolve())},
                    sort_keys=True,
                )
            )
            return 0
        output = fetch_candidate(
            repository=args.repository,
            commit_sha=args.commit_sha,
            output=args.output.expanduser().absolute(),
            token=args.token,
            api_url=args.api_url,
            metadata_output=(
                args.metadata_output.expanduser().absolute()
                if args.metadata_output is not None
                else None
            ),
        )
        print(
            json.dumps({"status": "downloaded", "archive": str(output)}, sort_keys=True)
        )
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
