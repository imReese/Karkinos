#!/usr/bin/env python3
"""Provenance-first orchestration for candidate runs and stable updates.

Update and bootstrap perform their read-only local preflights before retrieval.
Other callbacks run only after retrieval, and every callback owns any
short-lived release lock it needs; this module never holds a lock while
contacting GitHub or ``gh``.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from tools import release_fetch

DEFAULT_REPOSITORY = "imReese/Karkinos"
DEFAULT_CANDIDATE_PORT = 18000
DEFAULT_HEALTH_TIMEOUT = 30
MAX_HEALTH_TIMEOUT = 3600

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_STABLE_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_MAX_TOKEN_BYTES = 4096
_GH_AUTH_TIMEOUT_SECONDS = 15

WorkflowResult = object
GhAuthRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ReleaseWorkflowCallbacks:
    """Short, locally locked operations supplied by the release manager."""

    preflight: Callable[[], None]
    stage: Callable[[Path, str], WorkflowResult]
    run_candidate: Callable[[str, int], WorkflowResult]
    discard: Callable[[str], WorkflowResult]
    deploy: Callable[[str, str, int], WorkflowResult]


@dataclass(frozen=True)
class LegacyBootstrapWorkflowCallbacks:
    """Validated one-time migration operations supplied by the controller."""

    preflight: Callable[[], None]
    stage: Callable[[Path, str], WorkflowResult]
    bootstrap: Callable[[str, str, int], WorkflowResult]
    discard: Callable[[str], WorkflowResult]


def _require_repository(repository: str) -> str:
    if repository != DEFAULT_REPOSITORY:
        raise ValueError("release_update_repository_unsupported")
    return repository


def _require_commit_sha(commit_sha: str) -> str:
    if _FULL_SHA.fullmatch(commit_sha) is None:
        raise ValueError("release_update_commit_sha_invalid")
    return commit_sha


def _require_stable_tag(tag: str) -> str:
    if _STABLE_TAG.fullmatch(tag) is None:
        raise ValueError("release_update_stable_tag_invalid")
    return tag


def _require_candidate_port(port: int) -> int:
    if type(port) is not int or port < 1 or port > 65535:
        raise ValueError("release_update_candidate_port_invalid")
    return port


def _require_health_timeout(timeout: object) -> int:
    if type(timeout) is not int or timeout < 1 or timeout > MAX_HEALTH_TIMEOUT:
        raise ValueError("release_update_health_timeout_invalid")
    return timeout


def _require_token(token: str) -> str:
    try:
        encoded = token.encode("utf-8")
    except UnicodeError:
        raise ValueError("release_update_token_invalid") from None
    if (
        not token
        or len(encoded) > _MAX_TOKEN_BYTES
        or token != token.strip()
        or any(character.isspace() or ord(character) < 33 for character in token)
    ):
        raise ValueError("release_update_token_invalid")
    return token


def _gh_auth_environment(environment: Mapping[str, str]) -> dict[str, str]:
    result = dict(environment)
    for name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
    ):
        result.pop(name, None)
    return result


def candidate_token(
    *,
    environment: Mapping[str, str] | None = None,
    runner: GhAuthRunner = subprocess.run,
) -> str:
    """Resolve candidate API auth without putting a token in argv or errors."""
    selected_environment = os.environ if environment is None else environment
    configured = selected_environment.get("GH_TOKEN")
    if configured:
        return _require_token(configured)
    try:
        result = runner(
            ["gh", "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_GH_AUTH_TIMEOUT_SECONDS,
            env=_gh_auth_environment(selected_environment),
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        raise ValueError("release_update_gh_auth_inconclusive") from None
    if result.returncode != 0 or not isinstance(result.stdout, str):
        raise ValueError("release_update_gh_auth_failed")
    try:
        return _require_token(result.stdout.removesuffix("\n"))
    except ValueError:
        raise ValueError("release_update_gh_auth_result_invalid") from None


def _stable_token(
    environment: Mapping[str, str] | None,
    runner: GhAuthRunner = subprocess.run,
) -> str:
    return candidate_token(environment=environment, runner=runner)


def _require_private_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("release_update_download_directory_invalid")
    if stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) != 0o700:
        raise ValueError("release_update_download_directory_permissions_invalid")


def _require_verified_archive(
    result: release_fetch.VerifiedNativeArchive,
    *,
    output_dir: Path,
    repository: str,
    commit_sha: str | None,
    tag: str | None,
) -> release_fetch.VerifiedNativeArchive:
    if not isinstance(result, release_fetch.VerifiedNativeArchive):
        raise ValueError("release_update_fetch_result_invalid")
    expected_source = "github-release" if tag is not None else "actions-candidate"
    if (
        result.source != expected_source
        or result.repository != repository
        or (tag is None and result.tag is not None)
        or (tag is not None and result.tag != tag)
        or (tag is not None and result.version != tag.removeprefix("v"))
        or _FULL_SHA.fullmatch(result.commit_sha) is None
        or (commit_sha is not None and result.commit_sha != commit_sha)
        or result.architecture not in {"arm64", "x86_64"}
    ):
        raise ValueError("release_update_fetch_identity_mismatch")

    expected_output = output_dir.absolute()
    _require_private_directory(expected_output)
    paths = (result.archive, result.checksum, result.candidate_manifest)
    if len({path.name for path in paths}) != len(paths):
        raise ValueError("release_update_fetch_result_invalid")
    if result.checksum.name != f"{result.archive.name}.sha256":
        raise ValueError("release_update_fetch_result_invalid")
    if result.candidate_manifest.name != "candidate-manifest.json":
        raise ValueError("release_update_fetch_result_invalid")
    for path in paths:
        absolute = path.absolute()
        if (
            absolute.parent != expected_output
            or absolute.is_symlink()
            or not absolute.is_file()
        ):
            raise ValueError("release_update_fetch_result_invalid")
    if {path.name for path in expected_output.iterdir()} != {
        path.name for path in paths
    }:
        raise ValueError("release_update_fetch_result_invalid")
    return result


def run_candidate_workflow(
    callbacks: ReleaseWorkflowCallbacks,
    *,
    commit_sha: str,
    port: int = DEFAULT_CANDIDATE_PORT,
    repository: str = DEFAULT_REPOSITORY,
    environment: Mapping[str, str] | None = None,
    gh_auth_runner: GhAuthRunner = subprocess.run,
    temporary_parent: Path | None = None,
) -> WorkflowResult:
    """Fetch, stage, run, and always discard one isolated candidate."""
    repository = _require_repository(repository)
    commit_sha = _require_commit_sha(commit_sha)
    port = _require_candidate_port(port)
    token = candidate_token(environment=environment, runner=gh_auth_runner)

    with tempfile.TemporaryDirectory(
        prefix="karkinos-candidate-fetch-", dir=temporary_parent
    ) as temporary:
        temporary_root = Path(temporary).resolve(strict=True)
        temporary_root.chmod(0o700)
        _require_private_directory(temporary_root)
        output_dir = temporary_root / "verified"
        try:
            fetched = release_fetch.fetch_candidate_native(
                repository=repository,
                commit_sha=commit_sha,
                output_dir=output_dir,
                token=token,
            )
        except Exception:
            raise ValueError("release_update_candidate_fetch_failed") from None
        verified = _require_verified_archive(
            fetched,
            output_dir=output_dir,
            repository=repository,
            commit_sha=commit_sha,
            tag=None,
        )
        staged = False
        try:
            callbacks.stage(verified.archive, commit_sha)
            staged = True
            result = callbacks.run_candidate(commit_sha, port)
        except BaseException:
            if staged:
                try:
                    callbacks.discard(commit_sha)
                except BaseException:
                    pass
            raise
        callbacks.discard(commit_sha)
        return result


def run_stable_update_workflow(
    callbacks: ReleaseWorkflowCallbacks,
    *,
    tag: str,
    confirmation: str,
    health_timeout: int = DEFAULT_HEALTH_TIMEOUT,
    repository: str = DEFAULT_REPOSITORY,
    environment: Mapping[str, str] | None = None,
    gh_auth_runner: GhAuthRunner = subprocess.run,
    temporary_parent: Path | None = None,
) -> WorkflowResult:
    """Fetch an exact stable tag and deploy its attested commit SHA."""
    repository = _require_repository(repository)
    tag = _require_stable_tag(tag)
    required_confirmation = f"UPDATE {tag}"
    if confirmation != required_confirmation:
        raise ValueError(f"release_confirmation_required:{required_confirmation}")
    health_timeout = _require_health_timeout(health_timeout)

    # Validate local update readiness only after the complete operator-facing
    # command contract, but still before auth lookup or remote retrieval.
    callbacks.preflight()
    token = _stable_token(environment, gh_auth_runner)

    with tempfile.TemporaryDirectory(
        prefix="karkinos-stable-fetch-", dir=temporary_parent
    ) as temporary:
        temporary_root = Path(temporary).resolve(strict=True)
        temporary_root.chmod(0o700)
        _require_private_directory(temporary_root)
        output_dir = temporary_root / "verified"
        try:
            fetched = release_fetch.fetch_stable_native(
                repository=repository,
                tag=tag,
                output_dir=output_dir,
                token=token,
            )
        except Exception:
            raise ValueError("release_update_stable_fetch_failed") from None
        verified = _require_verified_archive(
            fetched,
            output_dir=output_dir,
            repository=repository,
            commit_sha=None,
            tag=tag,
        )
        staged = False
        try:
            callbacks.stage(verified.archive, verified.commit_sha)
            staged = True
            return callbacks.deploy(
                verified.commit_sha,
                f"PROMOTE {verified.commit_sha}",
                health_timeout,
            )
        except BaseException:
            if staged:
                try:
                    callbacks.discard(verified.commit_sha)
                except BaseException:
                    # A retained transaction journal deliberately prevents
                    # deletion of the artifact required for exact recovery.
                    pass
            raise


def run_stable_bootstrap_workflow(
    callbacks: LegacyBootstrapWorkflowCallbacks,
    *,
    tag: str,
    confirmation: str,
    health_timeout: int = DEFAULT_HEALTH_TIMEOUT,
    repository: str = DEFAULT_REPOSITORY,
    environment: Mapping[str, str] | None = None,
    gh_auth_runner: GhAuthRunner = subprocess.run,
    local_archive: Path | None = None,
    temporary_parent: Path | None = None,
) -> WorkflowResult:
    """Fetch one stable artifact and atomically replace a validated legacy service."""

    repository = _require_repository(repository)
    tag = _require_stable_tag(tag)
    required_confirmation = f"BOOTSTRAP {tag}"
    if confirmation != required_confirmation:
        raise ValueError(f"release_confirmation_required:{required_confirmation}")
    health_timeout = _require_health_timeout(health_timeout)

    # Validate the local, owner-selected migration topology before contacting
    # GitHub. The transactional bootstrap validates it again under the lock.
    callbacks.preflight()
    token = _stable_token(environment, gh_auth_runner)

    with tempfile.TemporaryDirectory(
        prefix="karkinos-bootstrap-fetch-", dir=temporary_parent
    ) as temporary:
        temporary_root = Path(temporary).resolve(strict=True)
        temporary_root.chmod(0o700)
        _require_private_directory(temporary_root)
        output_dir = temporary_root / "verified"
        try:
            fetched = release_fetch.fetch_stable_native(
                repository=repository,
                tag=tag,
                output_dir=output_dir,
                token=token,
                local_archive=local_archive,
            )
        except Exception:
            raise ValueError("release_update_stable_fetch_failed") from None
        verified = _require_verified_archive(
            fetched,
            output_dir=output_dir,
            repository=repository,
            commit_sha=None,
            tag=tag,
        )
        staged = False
        try:
            callbacks.stage(verified.archive, verified.commit_sha)
            staged = True
            return callbacks.bootstrap(
                verified.commit_sha,
                f"BOOTSTRAP {verified.commit_sha}",
                health_timeout,
            )
        except BaseException:
            if staged:
                try:
                    callbacks.discard(verified.commit_sha)
                except BaseException:
                    pass
            raise
