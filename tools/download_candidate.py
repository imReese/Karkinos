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
from pathlib import Path
from urllib.parse import urlencode, urlsplit

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024
_MAX_ZIP_MEMBERS = 200_000


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


def _artifact_pages(
    *, api_url: str, repository: str, token: str, name: str
) -> list[object]:
    artifacts: list[object] = []
    page = 1
    expected_total: int | None = None
    max_artifacts = 10_000
    while True:
        query = urlencode({"per_page": 100, "page": page, "name": name})
        listing = _request(
            f"{api_url}/repos/{repository}/actions/artifacts?{query}", token
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
        if len(artifacts) > max_artifacts:
            raise ValueError("candidate_artifact_listing_too_large")
        if len(artifacts) >= total:
            break
        if not values:
            raise ValueError("candidate_artifact_pagination_incomplete")
        page += 1
    if expected_total != len(artifacts):
        raise ValueError("candidate_artifact_pagination_incomplete")
    return artifacts


def fetch_candidate(
    *, repository: str, commit_sha: str, output: Path, token: str, api_url: str
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
    name = f"karkinos-candidate-{commit_sha}"
    matches = [
        item
        for item in _artifact_pages(
            api_url=api_url,
            repository=repository,
            token=token,
            name=name,
        )
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError("candidate_artifact_missing_or_ambiguous")
    artifact = matches[0]
    workflow_run_summary = artifact.get("workflow_run")
    download_url = artifact.get("archive_download_url")
    artifact_digest = artifact.get("digest")
    digest_match = (
        _ARTIFACT_DIGEST.fullmatch(artifact_digest)
        if isinstance(artifact_digest, str)
        else None
    )
    if (
        type(artifact.get("expired")) is not bool
        or artifact.get("expired")
        or not isinstance(artifact.get("id"), int)
        or artifact["id"] <= 0
        or not isinstance(workflow_run_summary, dict)
        or workflow_run_summary.get("head_sha") != commit_sha
        or workflow_run_summary.get("head_branch") != "main"
        or not isinstance(workflow_run_summary.get("id"), int)
        or workflow_run_summary["id"] <= 0
        or not isinstance(download_url, str)
        or digest_match is None
    ):
        raise ValueError("candidate_artifact_expired_or_invalid")
    workflow_run = _request(
        f"{api_url}/repos/{repository}/actions/runs/{workflow_run_summary['id']}",
        token,
    )
    if (
        not isinstance(workflow_run, dict)
        or workflow_run.get("id") != workflow_run_summary["id"]
        or workflow_run.get("name") != "Release Candidate"
        or str(workflow_run.get("path") or "").split("@", 1)[0]
        != ".github/workflows/candidate.yml"
        or workflow_run.get("head_sha") != commit_sha
        or workflow_run.get("head_branch") != "main"
        or workflow_run.get("event") not in {"push", "workflow_dispatch"}
        or workflow_run.get("status") != "completed"
        or workflow_run.get("conclusion") != "success"
        or not isinstance(workflow_run.get("run_attempt"), int)
        or workflow_run["run_attempt"] <= 0
        or not isinstance(workflow_run.get("repository"), dict)
        or workflow_run["repository"].get("full_name") != repository
        or not isinstance(workflow_run.get("head_repository"), dict)
        or workflow_run["head_repository"].get("full_name") != repository
    ):
        raise ValueError("candidate_artifact_workflow_run_invalid")
    _require_https_url(download_url, "candidate_artifact_download_url_invalid")
    _reject_symlink_ancestors(output.parent)
    if os.path.lexists(output):
        raise ValueError("candidate_output_already_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.download-{uuid.uuid4().hex}")
    try:
        payload = _download(download_url, token)
        if hashlib.sha256(payload).hexdigest() != digest_match.group(1):
            raise ValueError("candidate_artifact_download_digest_mismatch")
        with temporary.open("xb") as stream:
            stream.write(payload)
        if os.path.lexists(output):
            raise ValueError("candidate_output_already_exists")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
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
