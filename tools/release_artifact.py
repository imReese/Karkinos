"""Shared helpers for immutable Karkinos native release artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable

MANIFEST_NAME = "release.json"
NATIVE_ARTIFACT_SCHEMA = "karkinos.native_release.v1"
_RELEASE_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?$"
)
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 200_000
_MAX_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024


def canonical_json(payload: object) -> bytes:
    """Encode a JSON value in the stable form used by release manifests."""
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _iter_payload_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path == root / MANIFEST_NAME:
            continue
        # Check symlinks before is_dir(): a symlink to a directory must be
        # rejected, not silently omitted from the integrity inventory.
        if path.is_symlink():
            yield path
            continue
        if path.is_dir():
            continue
        yield path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_checksums(root: Path) -> dict[str, str]:
    """Return a path-addressed SHA-256 inventory for every regular payload file."""
    checksums: dict[str, str] = {}
    for path in _iter_payload_files(root):
        if path.is_symlink():
            raise ValueError("release_manifest_symlink_unsupported")
        if not path.is_file():
            raise ValueError("release_manifest_payload_file_invalid")
        checksums[path.relative_to(root).as_posix()] = _file_sha256(path)
    return checksums


def payload_fingerprint(root: Path) -> str:
    """Hash every release payload path and its bytes, excluding release.json."""
    digest = hashlib.sha256()
    for relative_name, checksum in payload_checksums(root).items():
        relative = relative_name.encode("utf-8")
        digest.update(relative)
        digest.update(b"\0file\0")
        digest.update(bytes.fromhex(checksum))
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_archive_member_path(root: Path, member: tarfile.TarInfo) -> Path:
    root = root.resolve()
    name = member.name
    relative = Path(name)
    if (
        not name
        or "\x00" in name
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in name
    ):
        raise ValueError("release_archive_path_unsafe")
    if (
        member.issym()
        or member.islnk()
        or member.isdev()
        or not (member.isdir() or member.isreg())
    ):
        raise ValueError("release_archive_member_unsupported")
    destination = (root / relative).resolve()
    if destination != root and root not in destination.parents:
        raise ValueError("release_archive_path_escape")
    return destination


def validate_archive(
    archive: Path,
    *,
    expected_commit_sha: str | None = None,
    expected_architecture: str | None = None,
    expected_version: str | None = None,
) -> dict[str, object]:
    """Validate a native archive without trusting archive-provided links."""
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("release_archive_invalid")
    try:
        archive_size = archive.stat().st_size
    except OSError as exc:
        raise ValueError("release_archive_invalid") from exc
    if archive_size > _MAX_ARCHIVE_BYTES:
        raise ValueError("release_archive_too_large")
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if len(members) > _MAX_ARCHIVE_MEMBERS:
            raise ValueError("release_archive_member_count_too_large")
        if not members:
            raise ValueError("release_archive_empty")
        roots = {Path(member.name).parts[0] for member in members if member.name}
        if len(roots) != 1 or not roots:
            raise ValueError("release_archive_root_invalid")
        root_name = next(iter(roots))
        if root_name in {"", ".", ".."}:
            raise ValueError("release_archive_root_invalid")
        total_size = 0
        for member in members:
            if member.isreg():
                total_size += member.size
                if member.size < 0 or total_size > _MAX_EXTRACTED_BYTES:
                    raise ValueError("release_archive_extracted_size_too_large")
        with tempfile.TemporaryDirectory(
            prefix="karkinos-archive-verify-"
        ) as temporary:
            destination = Path(temporary).resolve()
            seen: set[str] = set()
            for member in members:
                target = _safe_archive_member_path(destination, member)
                canonical_name = target.relative_to(destination).as_posix()
                if canonical_name in seen:
                    raise ValueError("release_archive_duplicate_path")
                seen.add(canonical_name)
                if member.isdir():
                    if target.exists() and not target.is_dir():
                        raise ValueError("release_archive_path_conflict")
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ValueError("release_archive_duplicate_path")
                payload = source.extractfile(member)
                if payload is None:
                    raise ValueError("release_archive_payload_missing")
                with target.open("xb") as output:
                    shutil.copyfileobj(payload, output)
                target.chmod(member.mode & 0o777 or 0o600)
            extracted = destination / root_name
            if not extracted.is_dir():
                raise ValueError("release_archive_root_missing")
            return validate_manifest(
                extracted,
                expected_commit_sha=expected_commit_sha,
                expected_architecture=expected_architecture,
                expected_version=expected_version,
            )


def read_manifest(root: Path) -> dict[str, object]:
    """Read and minimally type-check a native release manifest."""
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("release_manifest_invalid")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("release_manifest_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("release_manifest_invalid")
    return value


def validate_manifest(
    root: Path,
    *,
    expected_commit_sha: str | None = None,
    expected_architecture: str | None = None,
    expected_version: str | None = None,
) -> dict[str, object]:
    """Validate identity, layout, and content fingerprint of a package."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError("release_root_invalid")
    manifest = read_manifest(root)
    if manifest.get("schema_version") != NATIVE_ARTIFACT_SCHEMA:
        raise ValueError("release_manifest_schema_unsupported")
    if manifest.get("artifact_kind") != "macos-native":
        raise ValueError("release_manifest_artifact_kind_invalid")

    commit_sha = manifest.get("commit_sha")
    if (
        not isinstance(commit_sha, str)
        or len(commit_sha) != 40
        or any(character not in "0123456789abcdef" for character in commit_sha)
    ):
        raise ValueError("release_manifest_commit_sha_invalid")
    if expected_commit_sha is not None and commit_sha != expected_commit_sha:
        raise ValueError("release_manifest_commit_sha_mismatch")

    version = manifest.get("version")
    if not isinstance(version, str) or _RELEASE_VERSION.fullmatch(version) is None:
        raise ValueError("release_manifest_version_invalid")
    if expected_version is not None and version != expected_version:
        raise ValueError("release_manifest_version_mismatch")
    architecture = manifest.get("architecture")
    if architecture not in {"arm64", "x86_64"}:
        raise ValueError("release_manifest_architecture_invalid")
    if expected_architecture is not None and architecture != expected_architecture:
        raise ValueError("release_manifest_architecture_mismatch")

    if manifest.get("runtime") != "python3.12":
        raise ValueError("release_manifest_runtime_invalid")
    if manifest.get("mutable_state") != "~/Library/Application Support/Karkinos":
        raise ValueError("release_manifest_mutable_state_invalid")
    entrypoint = manifest.get("entrypoint")
    entrypoint_path = root / "bin" / "karkinos"
    if entrypoint != "bin/karkinos" or not entrypoint_path.is_file():
        raise ValueError("release_manifest_entrypoint_invalid")
    if entrypoint_path.is_symlink() or not (entrypoint_path.stat().st_mode & 0o111):
        raise ValueError("release_manifest_entrypoint_not_executable")
    required_files = (
        root / "app" / "server" / "__init__.py",
        root / "app" / "web" / "dist" / "index.html",
        root / "runtime" / "bin" / "python3.12",
    )
    if any(not path.is_file() or path.is_symlink() for path in required_files):
        raise ValueError("release_manifest_payload_incomplete")
    forbidden_names = {
        ".env",
        "config.json",
        "broker_statement.csv",
        "secret.py",
        "app.db",
        "runtime.sqlite",
    }
    forbidden_root_dirs = {
        "data",
        "config",
        "logs",
        "exports",
        "screenshots",
        "reports",
    }
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ValueError("release_manifest_symlink_unsupported")
        if path.name in forbidden_names or (
            relative.parts and relative.parts[0] in forbidden_root_dirs
        ):
            raise ValueError("release_manifest_private_payload")
        if not path.is_dir() and not path.is_file():
            raise ValueError("release_manifest_payload_file_invalid")

    expected_checksums = manifest.get("file_checksums")
    if (
        not isinstance(expected_checksums, dict)
        or not expected_checksums
        or any(
            not isinstance(name, str)
            or not isinstance(checksum, str)
            or not re.fullmatch(r"[0-9a-f]{64}", checksum)
            for name, checksum in expected_checksums.items()
        )
    ):
        raise ValueError("release_manifest_file_checksums_invalid")
    actual_checksums = payload_checksums(root)
    if expected_checksums != actual_checksums:
        raise ValueError("release_manifest_file_checksum_mismatch")
    expected_fingerprint = manifest.get("payload_fingerprint")
    if (
        not isinstance(expected_fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint) is None
    ):
        raise ValueError("release_manifest_payload_fingerprint_invalid")
    if payload_fingerprint(root) != expected_fingerprint:
        raise ValueError("release_manifest_payload_fingerprint_mismatch")
    return manifest
