#!/usr/bin/env python3
"""Fetch one provenance-verified native Karkinos release artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from tools import download_candidate, release_artifact
from tools.release_candidate import (
    sha256,
    verify_candidate_manifest,
    verify_candidate_manifest_metadata,
)

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_SEMVER_TAG = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?$"
)
_ASSET_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_CHECKSUM_BYTES = 4096
_MAX_NATIVE_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_RELEASE_ASSETS = 1000
_MAX_ATTESTATION_OUTPUT_BYTES = 8 * 1024 * 1024
_ATTESTATION_TIMEOUT_SECONDS = 120
_ATTESTATION_ATTEMPTS = 3
_ATTESTATION_RETRY_SECONDS = 2
_CANDIDATE_SIGNER_WORKFLOW = ".github/workflows/candidate.yml"
_STABLE_SIGNER_WORKFLOW = ".github/workflows/release.yml"
_BOOTSTRAP_INSTALLER_ASSET = "bootstrap_installer.sh"

AttestationRunner = Callable[..., subprocess.CompletedProcess[str]]
AttestationSleeper = Callable[[float], None]


class _ReadableResponse(Protocol):
    headers: Any

    def read(self, size: int) -> bytes: ...


@dataclass(frozen=True)
class VerifiedNativeArchive:
    """One selected native archive ready for ``manage_release stage``."""

    source: str
    repository: str
    commit_sha: str
    version: str
    architecture: str
    archive: Path
    checksum: Path
    candidate_manifest: Path
    tag: str | None = None


def current_macos_architecture() -> str:
    """Return the native package architecture for the current macOS host."""
    if platform.system() != "Darwin":
        raise ValueError("release_fetch_macos_required")
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    raise ValueError("release_fetch_architecture_unsupported")


def verify_github_attestation(
    archive: Path,
    *,
    repository: str,
    commit_sha: str,
    signer_workflow: str = _CANDIDATE_SIGNER_WORKFLOW,
    source_ref: str | None = None,
    token: str = "",
    runner: AttestationRunner = subprocess.run,
    sleeper: AttestationSleeper = time.sleep,
) -> list[dict[str, Any]]:
    """Require GitHub's signed candidate-workflow provenance for an archive."""
    _validate_repository(repository)
    _validate_commit_sha(commit_sha)
    if signer_workflow not in {
        _CANDIDATE_SIGNER_WORKFLOW,
        _STABLE_SIGNER_WORKFLOW,
    }:
        raise ValueError("release_attestation_signer_workflow_invalid")
    if source_ref is not None and (
        not source_ref.startswith("refs/tags/")
        or _SEMVER_TAG.fullmatch(source_ref.removeprefix("refs/tags/")) is None
    ):
        raise ValueError("release_attestation_source_ref_invalid")
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("release_attestation_artifact_invalid")
    command = [
        "gh",
        "attestation",
        "verify",
        str(archive),
        "--repo",
        repository,
        "--signer-workflow",
        f"{repository}/{signer_workflow}",
        "--source-digest",
        commit_sha,
    ]
    if source_ref is not None:
        command.extend(["--source-ref", source_ref])
    command.extend(["--deny-self-hosted-runners", "--format", "json"])
    environment = os.environ.copy()
    if token:
        environment["GH_TOKEN"] = token
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(_ATTESTATION_ATTEMPTS):
        try:
            result = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=_ATTESTATION_TIMEOUT_SECONDS,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise ValueError("release_attestation_verifier_unavailable") from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            if attempt + 1 == _ATTESTATION_ATTEMPTS:
                raise ValueError(
                    "release_attestation_verification_inconclusive"
                ) from exc
        else:
            if result.returncode == 0:
                break
            if attempt + 1 == _ATTESTATION_ATTEMPTS:
                raise ValueError("release_attestation_verification_failed")
        sleeper(_ATTESTATION_RETRY_SECONDS * (2**attempt))
    if result is None or result.returncode != 0:
        raise ValueError("release_attestation_verification_inconclusive")
    output = result.stdout
    if not isinstance(output, str) or len(output.encode("utf-8")) > (
        _MAX_ATTESTATION_OUTPUT_BYTES
    ):
        raise ValueError("release_attestation_result_invalid")
    try:
        payload = json.loads(output)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("release_attestation_result_invalid") from exc
    if (
        not isinstance(payload, list)
        or not payload
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("attestation"), dict)
            or not item["attestation"]
            or not isinstance(item.get("verificationResult"), dict)
            or not item["verificationResult"]
            for item in payload
        )
    ):
        raise ValueError("release_attestation_result_invalid")
    return payload


def _validate_repository(repository: str) -> str:
    if _REPOSITORY.fullmatch(repository) is None:
        raise ValueError("release_fetch_repository_invalid")
    return repository


def _validate_commit_sha(commit_sha: str) -> str:
    if _FULL_SHA.fullmatch(commit_sha) is None:
        raise ValueError("release_fetch_commit_sha_invalid")
    return commit_sha


def _api_root(api_url: str) -> str:
    return download_candidate._require_https_url(
        api_url.rstrip("/"), "release_fetch_api_url_invalid"
    )


def _request_headers(*, token: str, accept: str) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "karkinos-release-fetcher/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_bounded(
    response: _ReadableResponse, *, maximum: int, expected_size: int | None
) -> bytes:
    headers = getattr(response, "headers", None)
    declared_text = headers.get("Content-Length") if headers is not None else None
    declared_size: int | None = None
    if declared_text is not None:
        try:
            declared_size = int(declared_text)
        except (TypeError, ValueError) as exc:
            raise ValueError("release_fetch_content_length_invalid") from exc
        if declared_size < 0 or declared_size > maximum:
            raise ValueError("release_fetch_payload_too_large")
    if expected_size is not None:
        if expected_size < 0 or expected_size > maximum:
            raise ValueError("release_fetch_asset_size_invalid")
        if declared_size is not None and declared_size != expected_size:
            raise ValueError("release_fetch_content_length_mismatch")
    chunks: list[bytes] = []
    total = 0
    while total <= maximum:
        chunk = response.read(min(1024 * 1024, maximum + 1 - total))
        if not chunk:
            payload = b"".join(chunks)
            if declared_size is not None and len(payload) != declared_size:
                raise ValueError("release_fetch_content_length_mismatch")
            if expected_size is not None and len(payload) != expected_size:
                raise ValueError("release_fetch_asset_size_mismatch")
            return payload
        if not isinstance(chunk, bytes):
            raise ValueError("release_fetch_response_invalid")
        chunks.append(chunk)
        total += len(chunk)
    raise ValueError("release_fetch_payload_too_large")


def _https_get(
    url: str,
    *,
    token: str,
    accept: str,
    maximum: int,
    expected_size: int | None = None,
    timeout: float,
) -> bytes:
    download_candidate._require_https_url(url, "release_fetch_url_invalid")
    request = urllib.request.Request(
        url,
        headers=_request_headers(token=token, accept=accept),
    )
    try:
        with download_candidate._SAFE_OPENER.open(request, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                raise ValueError("release_fetch_status_unexpected")
            return _read_bounded(response, maximum=maximum, expected_size=expected_size)
    except ValueError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError("release_fetch_request_inconclusive") from exc


def _github_json(
    path: str, *, repository: str, token: str, api_url: str
) -> dict[str, Any]:
    if not path.startswith("/") or "\x00" in path:
        raise ValueError("release_fetch_api_path_invalid")
    payload = _https_get(
        f"{_api_root(api_url)}{path}",
        token=token,
        accept="application/vnd.github+json",
        maximum=_MAX_JSON_BYTES,
        timeout=30,
    )
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("release_fetch_api_response_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("release_fetch_api_response_invalid")
    return value


def _resolve_tag_commit(*, repository: str, tag: str, token: str, api_url: str) -> str:
    ref = _github_json(
        f"/repos/{repository}/git/ref/tags/{quote(tag, safe='')}",
        repository=repository,
        token=token,
        api_url=api_url,
    )
    if ref.get("ref") != f"refs/tags/{tag}" or not isinstance(ref.get("object"), dict):
        raise ValueError("release_fetch_tag_ref_invalid")
    target = ref["object"]
    seen: set[str] = set()
    for depth in range(8):
        object_type = target.get("type")
        object_sha = target.get("sha")
        if not isinstance(object_sha, str) or _FULL_SHA.fullmatch(object_sha) is None:
            raise ValueError("release_fetch_tag_target_invalid")
        if object_sha in seen:
            raise ValueError("release_fetch_tag_cycle")
        seen.add(object_sha)
        if object_type == "commit":
            return object_sha
        if object_type != "tag":
            raise ValueError("release_fetch_tag_target_invalid")
        tag_object = _github_json(
            f"/repos/{repository}/git/tags/{object_sha}",
            repository=repository,
            token=token,
            api_url=api_url,
        )
        if tag_object.get("sha") != object_sha or not isinstance(
            tag_object.get("object"), dict
        ):
            raise ValueError("release_fetch_tag_object_invalid")
        if depth == 0 and tag_object.get("tag") != tag:
            raise ValueError("release_fetch_tag_object_invalid")
        target = tag_object["object"]
    raise ValueError("release_fetch_tag_depth_exceeded")


def _release_assets(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = release.get("assets")
    if not isinstance(values, list) or len(values) > _MAX_RELEASE_ASSETS:
        raise ValueError("release_fetch_assets_invalid")
    assets: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("release_fetch_assets_invalid")
        name = item["name"]
        if name in assets:
            raise ValueError("release_fetch_asset_ambiguous")
        asset_id = item.get("id")
        size = item.get("size")
        digest = item.get("digest")
        if (
            not name
            or "/" in name
            or "\\" in name
            or type(asset_id) is not int
            or asset_id <= 0
            or type(size) is not int
            or size < 0
            or size > _MAX_NATIVE_ARCHIVE_BYTES
            or item.get("state") != "uploaded"
            or not isinstance(digest, str)
            or _ASSET_DIGEST.fullmatch(digest) is None
        ):
            raise ValueError("release_fetch_asset_invalid")
        assets[name] = item
    return assets


def _published_release_assets(
    release: dict[str, Any], *, tag: str
) -> dict[str, dict[str, Any]]:
    if (
        type(release.get("id")) is not int
        or release["id"] <= 0
        or release.get("tag_name") != tag
        or release.get("draft") is not False
        or release.get("prerelease") is not False
        or not isinstance(release.get("published_at"), str)
        or not release["published_at"]
    ):
        raise ValueError("release_fetch_release_invalid")
    return _release_assets(release)


def _published_release_identity(
    release: dict[str, Any], assets: dict[str, dict[str, Any]]
) -> tuple[object, ...]:
    return (
        release["id"],
        release["tag_name"],
        release["published_at"],
        tuple(
            sorted(
                (
                    name,
                    asset["id"],
                    asset["size"],
                    asset["state"],
                    asset["digest"],
                )
                for name, asset in assets.items()
            )
        ),
    )


def _download_release_asset(
    asset: dict[str, Any],
    *,
    repository: str,
    token: str,
    api_url: str,
    maximum: int,
) -> bytes:
    payload = _https_get(
        f"{_api_root(api_url)}/repos/{repository}/releases/assets/{asset['id']}",
        token=token,
        accept="application/octet-stream",
        maximum=maximum,
        expected_size=asset["size"],
        timeout=120,
    )
    expected = _ASSET_DIGEST.fullmatch(asset["digest"])
    if expected is None or hashlib.sha256(payload).hexdigest() != expected.group(1):
        raise ValueError("release_fetch_asset_digest_mismatch")
    return payload


def _require_new_output(output_dir: Path) -> Path:
    output = output_dir.expanduser().absolute()
    download_candidate._reject_symlink_ancestors(output.parent)
    if os.path.lexists(output):
        raise ValueError("release_fetch_output_already_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _selected_artifact(manifest: dict[str, Any], architecture: str) -> dict[str, str]:
    matches = [
        item
        for item in manifest["native_artifacts"]
        if item.get("architecture") == architecture
    ]
    if len(matches) != 1:
        raise ValueError("release_fetch_native_artifact_missing_or_ambiguous")
    return matches[0]


def _publish_selected(
    *,
    output: Path,
    source: str,
    repository: str,
    commit_sha: str,
    version: str,
    architecture: str,
    manifest_path: Path,
    archive_path: Path,
    checksum_path: Path,
    tag: str | None,
) -> VerifiedNativeArchive:
    staging = output.parent / f".{output.name}.verified-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        for source_path, name in (
            (manifest_path, "candidate-manifest.json"),
            (archive_path, archive_path.name),
            (checksum_path, checksum_path.name),
        ):
            if source_path.is_symlink() or not source_path.is_file():
                raise ValueError("release_fetch_verified_file_invalid")
            destination = staging / name
            shutil.copyfile(source_path, destination)
            destination.chmod(0o600)
        if os.path.lexists(output):
            raise ValueError("release_fetch_output_already_exists")
        os.replace(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    archive = output / archive_path.name
    checksum = output / checksum_path.name
    candidate_manifest = output / "candidate-manifest.json"
    return VerifiedNativeArchive(
        source=source,
        repository=repository,
        commit_sha=commit_sha,
        version=version,
        architecture=architecture,
        archive=archive,
        checksum=checksum,
        candidate_manifest=candidate_manifest,
        tag=tag,
    )


def fetch_candidate_native(
    *,
    repository: str,
    commit_sha: str,
    output_dir: Path,
    token: str,
    api_url: str = "https://api.github.com",
    architecture: str | None = None,
    attestation_runner: AttestationRunner = subprocess.run,
) -> VerifiedNativeArchive:
    """Fetch and verify an exact successful, tag-free Actions candidate."""
    _validate_repository(repository)
    _validate_commit_sha(commit_sha)
    if not token:
        raise ValueError("release_fetch_token_missing")
    selected_architecture = architecture or current_macos_architecture()
    if selected_architecture not in {"arm64", "x86_64"}:
        raise ValueError("release_fetch_architecture_unsupported")
    output = _require_new_output(output_dir)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.candidate-", dir=output.parent
    ) as temporary:
        work = Path(temporary)
        actions_archive = download_candidate.fetch_candidate(
            repository=repository,
            commit_sha=commit_sha,
            output=work / "candidate-actions.zip",
            token=token,
            api_url=_api_root(api_url),
            metadata_output=work / "candidate-selection.json",
        )
        selection = download_candidate.read_candidate_selection(
            work / "candidate-selection.json",
            expected_repository=repository,
            expected_commit_sha=commit_sha,
        )
        selection_workflow = selection["workflow"]
        assert isinstance(selection_workflow, dict)
        bundle = work / "bundle"
        download_candidate._safe_zip_extract(actions_archive.read_bytes(), bundle)
        manifest_path = bundle / "candidate-manifest.json"
        artifact_dir = bundle / "candidate-artifacts"
        manifest = verify_candidate_manifest(
            manifest_path,
            artifact_dir=artifact_dir,
            expected_commit_sha=commit_sha,
            expected_candidate_workflow_run_id=int(selection_workflow["run_id"]),
            expected_candidate_workflow_run_attempt=int(
                selection_workflow["run_attempt"]
            ),
            expected_candidate_workflow_event=str(selection_workflow["event"]),
            expected_image_reference=f"ghcr.io/{repository.lower()}",
        )
        bundle_entries = {path.name for path in bundle.iterdir()}
        if bundle_entries != {"candidate-manifest.json", "candidate-artifacts"}:
            raise ValueError("release_fetch_candidate_bundle_invalid")
        selected = _selected_artifact(manifest, selected_architecture)
        archive_path = artifact_dir / selected["filename"]
        checksum_path = artifact_dir / f"{selected['filename']}.sha256"
        verify_github_attestation(
            archive_path,
            repository=repository,
            commit_sha=commit_sha,
            token=token,
            runner=attestation_runner,
        )
        return _publish_selected(
            output=output,
            source="actions-candidate",
            repository=repository,
            commit_sha=commit_sha,
            version=manifest["version"],
            architecture=selected_architecture,
            manifest_path=manifest_path,
            archive_path=archive_path,
            checksum_path=checksum_path,
            tag=None,
        )


def fetch_stable_native(
    *,
    repository: str,
    tag: str,
    output_dir: Path,
    token: str = "",
    api_url: str = "https://api.github.com",
    architecture: str | None = None,
    local_archive: Path | None = None,
    attestation_runner: AttestationRunner = subprocess.run,
) -> VerifiedNativeArchive:
    """Acquire one published stable Release and prove tag, bytes, and provenance."""
    _validate_repository(repository)
    match = _SEMVER_TAG.fullmatch(tag)
    if match is None:
        raise ValueError("release_fetch_tag_invalid")
    if match.group(4) is not None:
        raise ValueError("release_fetch_tag_not_stable")
    selected_architecture = architecture or current_macos_architecture()
    if selected_architecture not in {"arm64", "x86_64"}:
        raise ValueError("release_fetch_architecture_unsupported")
    api_url = _api_root(api_url)
    release = _github_json(
        f"/repos/{repository}/releases/tags/{quote(tag, safe='')}",
        repository=repository,
        token=token,
        api_url=api_url,
    )
    assets = _published_release_assets(release, tag=tag)
    release_identity = _published_release_identity(release, assets)
    commit_sha = _resolve_tag_commit(
        repository=repository,
        tag=tag,
        token=token,
        api_url=api_url,
    )
    manifest_asset = assets.get("candidate-manifest.json")
    if manifest_asset is None:
        raise ValueError("release_fetch_candidate_manifest_missing")
    selection_asset = assets.get("candidate-selection.json")
    if selection_asset is None:
        raise ValueError("release_fetch_candidate_selection_missing")
    output = _require_new_output(output_dir)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.release-", dir=output.parent
    ) as temporary:
        work = Path(temporary)
        manifest_path = work / "candidate-manifest.json"
        manifest_path.write_bytes(
            _download_release_asset(
                manifest_asset,
                repository=repository,
                token=token,
                api_url=api_url,
                maximum=_MAX_JSON_BYTES,
            )
        )
        selection_path = work / "candidate-selection.json"
        selection_path.write_bytes(
            _download_release_asset(
                selection_asset,
                repository=repository,
                token=token,
                api_url=api_url,
                maximum=_MAX_JSON_BYTES,
            )
        )
        # Establish the tag-to-manifest identity before consulting the
        # candidate selection receipt so drift reports the earliest boundary.
        verify_candidate_manifest_metadata(
            manifest_path,
            expected_commit_sha=commit_sha,
            expected_version=tag.removeprefix("v"),
            expected_image_reference=f"ghcr.io/{repository.lower()}",
        )
        selection = download_candidate.read_candidate_selection(
            selection_path,
            expected_repository=repository,
            expected_commit_sha=commit_sha,
        )
        selection_workflow = selection["workflow"]
        assert isinstance(selection_workflow, dict)
        manifest = verify_candidate_manifest_metadata(
            manifest_path,
            expected_commit_sha=commit_sha,
            expected_version=tag.removeprefix("v"),
            expected_candidate_workflow_run_id=int(selection_workflow["run_id"]),
            expected_candidate_workflow_run_attempt=int(
                selection_workflow["run_attempt"]
            ),
            expected_candidate_workflow_event=str(selection_workflow["event"]),
            expected_image_reference=f"ghcr.io/{repository.lower()}",
        )
        expected_asset_names = {
            "candidate-manifest.json",
            "candidate-selection.json",
        }
        for item in manifest["native_artifacts"]:
            expected_asset_names.add(item["filename"])
            expected_asset_names.add(f"{item['filename']}.sha256")
        actual_asset_names = set(assets)
        expected_with_installer = expected_asset_names | {_BOOTSTRAP_INSTALLER_ASSET}
        if actual_asset_names not in (expected_asset_names, expected_with_installer):
            raise ValueError("release_fetch_release_asset_set_invalid")
        checksum_payloads: dict[str, bytes] = {}
        for item in manifest["native_artifacts"]:
            archive_asset = assets.get(item["filename"])
            checksum_name = f"{item['filename']}.sha256"
            checksum_asset = assets.get(checksum_name)
            if archive_asset is None or checksum_asset is None:
                raise ValueError("release_fetch_native_asset_missing")
            if archive_asset["digest"] != f"sha256:{item['sha256']}":
                raise ValueError("release_fetch_asset_manifest_digest_mismatch")
            checksum_payload = _download_release_asset(
                checksum_asset,
                repository=repository,
                token=token,
                api_url=api_url,
                maximum=_MAX_CHECKSUM_BYTES,
            )
            try:
                checksum_fields = checksum_payload.decode("utf-8").strip().split()
            except UnicodeError as exc:
                raise ValueError("release_fetch_checksum_file_invalid") from exc
            if checksum_fields != [item["sha256"], item["filename"]]:
                raise ValueError("release_fetch_checksum_file_invalid")
            checksum_payloads[checksum_name] = checksum_payload
        selected = _selected_artifact(manifest, selected_architecture)
        archive_asset = assets.get(selected["filename"])
        checksum_asset = assets.get(f"{selected['filename']}.sha256")
        if archive_asset is None or checksum_asset is None:
            raise ValueError("release_fetch_native_asset_missing")
        archive_path = work / selected["filename"]
        checksum_path = work / f"{selected['filename']}.sha256"
        if local_archive is None:
            archive_path.write_bytes(
                _download_release_asset(
                    archive_asset,
                    repository=repository,
                    token=token,
                    api_url=api_url,
                    maximum=_MAX_NATIVE_ARCHIVE_BYTES,
                )
            )
        else:
            if (
                not local_archive.is_absolute()
                or ".." in local_archive.parts
                or local_archive.name != selected["filename"]
            ):
                raise ValueError("release_fetch_local_archive_invalid")
            download_candidate._reject_symlink_ancestors(local_archive)
            if local_archive.is_symlink() or not local_archive.is_file():
                raise ValueError("release_fetch_local_archive_invalid")
            local_stat = local_archive.stat(follow_symlinks=False)
            if local_stat.st_size != archive_asset["size"]:
                raise ValueError("release_fetch_local_archive_size_mismatch")
            shutil.copyfile(local_archive, archive_path)
            archive_path.chmod(0o600)
        checksum_path.write_bytes(checksum_payloads[checksum_path.name])
        if sha256(archive_path) != selected["sha256"]:
            raise ValueError("release_fetch_candidate_checksum_mismatch")
        release_artifact.validate_archive(
            archive_path,
            expected_commit_sha=commit_sha,
            expected_architecture=selected_architecture,
            expected_version=manifest["version"],
        )
        verify_github_attestation(
            manifest_path,
            repository=repository,
            commit_sha=commit_sha,
            signer_workflow=_STABLE_SIGNER_WORKFLOW,
            source_ref=f"refs/tags/{tag}",
            token=token,
            runner=attestation_runner,
        )
        verify_github_attestation(
            selection_path,
            repository=repository,
            commit_sha=commit_sha,
            signer_workflow=_STABLE_SIGNER_WORKFLOW,
            source_ref=f"refs/tags/{tag}",
            token=token,
            runner=attestation_runner,
        )
        verify_github_attestation(
            archive_path,
            repository=repository,
            commit_sha=commit_sha,
            token=token,
            runner=attestation_runner,
        )
        verify_github_attestation(
            archive_path,
            repository=repository,
            commit_sha=commit_sha,
            signer_workflow=_STABLE_SIGNER_WORKFLOW,
            source_ref=f"refs/tags/{tag}",
            token=token,
            runner=attestation_runner,
        )
        confirmed_release = _github_json(
            f"/repos/{repository}/releases/tags/{quote(tag, safe='')}",
            repository=repository,
            token=token,
            api_url=api_url,
        )
        confirmed_assets = _published_release_assets(confirmed_release, tag=tag)
        confirmed_commit_sha = _resolve_tag_commit(
            repository=repository,
            tag=tag,
            token=token,
            api_url=api_url,
        )
        if (
            confirmed_commit_sha != commit_sha
            or _published_release_identity(confirmed_release, confirmed_assets)
            != release_identity
        ):
            raise ValueError("release_fetch_remote_identity_changed")
        return _publish_selected(
            output=output,
            source="github-release",
            repository=repository,
            commit_sha=commit_sha,
            version=manifest["version"],
            architecture=selected_architecture,
            manifest_path=manifest_path,
            archive_path=archive_path,
            checksum_path=checksum_path,
            tag=tag,
        )


def _result_json(result: VerifiedNativeArchive) -> str:
    payload = asdict(result)
    for field in ("archive", "checksum", "candidate_manifest"):
        payload[field] = str(payload[field])
    return json.dumps(payload, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", "imReese/Karkinos"),
    )
    parser.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    candidate = subparsers.add_parser("candidate")
    candidate.add_argument("--commit-sha", required=True)
    candidate.add_argument("--output-dir", type=Path, required=True)
    stable = subparsers.add_parser("stable")
    stable.add_argument("--tag", required=True)
    stable.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN", "")
    try:
        if args.command == "candidate":
            result = fetch_candidate_native(
                repository=args.repository,
                commit_sha=args.commit_sha,
                output_dir=args.output_dir,
                token=token,
                api_url=args.api_url,
            )
        else:
            result = fetch_stable_native(
                repository=args.repository,
                tag=args.tag,
                output_dir=args.output_dir,
                token=token,
                api_url=args.api_url,
            )
        print(_result_json(result))
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
