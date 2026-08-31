#!/usr/bin/env python3
"""Create and verify the candidate manifest reused by stable promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

CANDIDATE_SCHEMA = "karkinos.release_candidate.v2"
_TOOLCHAIN = {
    "python": "3.12.13",
    "node": "24.20.0",
    "uv": "0.11.28",
}
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_REFERENCE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+$")
_CANDIDATE_IMAGE_REFERENCE = re.compile(
    r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+:"
    r"candidate-sha-(?P<commit_sha>[0-9a-f]{40})-"
    r"run-[1-9][0-9]*-attempt-[1-9][0-9]*$"
)
_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?$"
)
_NATIVE_NAME = re.compile(r"^karkinos-[0-9A-Za-z.+-]+-macos-(arm64|x86_64)\.tar\.gz$")


def _regular_directory(path: Path, error: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(error)
    return path


def _regular_file(path: Path, error: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(error)
    return path


def sha256(path: Path) -> str:
    _regular_file(path, "candidate_fingerprint_source_invalid")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version(repo_root: Path) -> str:
    namespace: dict[str, Any] = {}
    source = _regular_file(
        repo_root / "server/__init__.py", "candidate_version_source_invalid"
    )
    exec(source.read_text(encoding="utf-8"), namespace)
    value = namespace.get("__version__")
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        raise ValueError("candidate_version_invalid")
    return value


def _require_identity(commit_sha: str, image_digest: str) -> None:
    if _FULL_SHA.fullmatch(commit_sha) is None:
        raise ValueError("candidate_commit_sha_invalid")
    if _DIGEST.fullmatch(image_digest) is None:
        raise ValueError("candidate_image_digest_invalid")


def _positive_run_identity(run_id: object, run_attempt: object) -> bool:
    return (
        type(run_id) is int
        and run_id > 0
        and type(run_attempt) is int
        and run_attempt > 0
    )


def _candidate_image_tag(commit_sha: str, run_id: int, run_attempt: int) -> str:
    return f"candidate-sha-{commit_sha}-run-{run_id}-attempt-{run_attempt}"


def verify_candidate_image_metadata(
    metadata_path: Path,
    *,
    image_reference: str,
    image_digest: str,
    commit_sha: str,
    version: str,
) -> dict[str, Any]:
    """Verify both runtime platforms from a remote Buildx inspection."""
    _require_identity(commit_sha, image_digest)
    reference_match = _CANDIDATE_IMAGE_REFERENCE.fullmatch(image_reference)
    if reference_match is None or reference_match.group("commit_sha") != commit_sha:
        raise ValueError("candidate_image_reference_invalid")
    if _VERSION.fullmatch(version) is None:
        raise ValueError("candidate_image_version_invalid")
    _regular_file(metadata_path, "candidate_image_metadata_invalid")
    try:
        if metadata_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("candidate_image_metadata_too_large")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate_image_metadata_invalid") from exc
    if not isinstance(metadata, dict) or metadata.get("name") != image_reference:
        raise ValueError("candidate_image_metadata_invalid")
    manifest = metadata.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("digest") != image_digest:
        raise ValueError("candidate_image_digest_mismatch")
    images = metadata.get("image")
    expected_platforms = {
        "linux/amd64": "amd64",
        "linux/arm64": "arm64",
    }
    if not isinstance(images, dict) or set(images) != set(expected_platforms):
        raise ValueError("candidate_image_platforms_invalid")
    for platform_name, architecture in expected_platforms.items():
        image = images.get(platform_name)
        if (
            not isinstance(image, dict)
            or image.get("os") != "linux"
            or image.get("architecture") != architecture
        ):
            raise ValueError("candidate_image_platforms_invalid")
        config = image.get("config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if (
            not isinstance(labels, dict)
            or labels.get("org.opencontainers.image.version") != version
            or labels.get("org.opencontainers.image.revision") != commit_sha
        ):
            raise ValueError("candidate_image_labels_mismatch")
    return {
        "commit_sha": commit_sha,
        "digest": image_digest,
        "image_reference": image_reference,
        "platforms": sorted(expected_platforms),
        "version": version,
    }


def build_candidate_manifest(
    *,
    repo_root: Path,
    artifact_dir: Path,
    commit_sha: str,
    version: str,
    source_ci_run_id: int,
    source_ci_run_attempt: int,
    candidate_workflow_run_id: int,
    candidate_workflow_run_attempt: int,
    candidate_workflow_event: str,
    image_workflow_run_id: int,
    image_workflow_run_attempt: int,
    image_reference: str,
    image_digest: str,
) -> dict[str, Any]:
    _require_identity(commit_sha, image_digest)
    _regular_directory(artifact_dir, "candidate_native_artifacts_invalid")
    _regular_directory(repo_root, "candidate_source_root_invalid")
    if version != _version(repo_root):
        raise ValueError("candidate_version_source_mismatch")
    if not _positive_run_identity(source_ci_run_id, source_ci_run_attempt):
        raise ValueError("candidate_source_ci_identity_invalid")
    if not _positive_run_identity(
        candidate_workflow_run_id, candidate_workflow_run_attempt
    ) or candidate_workflow_event not in {"push", "workflow_dispatch"}:
        raise ValueError("candidate_workflow_identity_invalid")
    if (
        not _positive_run_identity(image_workflow_run_id, image_workflow_run_attempt)
        or image_workflow_run_id != candidate_workflow_run_id
        or image_workflow_run_attempt > candidate_workflow_run_attempt
    ):
        raise ValueError("candidate_image_workflow_identity_invalid")
    if _IMAGE_REFERENCE.fullmatch(image_reference) is None:
        raise ValueError("candidate_image_reference_invalid")
    candidate_image_tag = _candidate_image_tag(
        commit_sha, image_workflow_run_id, image_workflow_run_attempt
    )

    from tools.release_artifact import validate_archive

    artifacts: list[dict[str, str]] = []
    archives = sorted(artifact_dir.glob("*.tar.gz"))
    if not archives:
        raise ValueError("candidate_native_artifacts_missing")
    for archive in archives:
        match = _NATIVE_NAME.fullmatch(archive.name)
        if match is None:
            raise ValueError("candidate_native_artifact_name_invalid")
        architecture = match.group(1)
        expected_filename = f"karkinos-{version}-macos-{architecture}.tar.gz"
        if archive.name != expected_filename:
            raise ValueError("candidate_native_artifact_name_invalid")
        _regular_file(archive, "candidate_native_artifact_invalid")
        checksum_path = archive.with_name(archive.name + ".sha256")
        if checksum_path.is_symlink() or not checksum_path.is_file():
            raise ValueError("candidate_native_artifact_checksum_missing")
        checksum_text = checksum_path.read_text(encoding="utf-8").strip().split()
        if len(checksum_text) != 2 or checksum_text[1] != archive.name:
            raise ValueError("candidate_native_artifact_checksum_file_invalid")
        digest = checksum_text[0]
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256(archive) != digest:
            raise ValueError("candidate_native_artifact_checksum_mismatch")
        validate_archive(
            archive,
            expected_commit_sha=commit_sha,
            expected_architecture=architecture,
            expected_version=version,
        )
        artifacts.append(
            {
                "architecture": architecture,
                "filename": archive.name,
                "sha256": digest,
            }
        )
    architectures = [item["architecture"] for item in artifacts]
    if set(architectures) != {"arm64", "x86_64"} or len(architectures) != 2:
        raise ValueError("candidate_native_architectures_incomplete")
    expected_files = {item["filename"] for item in artifacts} | {
        f"{item['filename']}.sha256" for item in artifacts
    }
    entries = list(artifact_dir.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("candidate_native_artifact_set_invalid")
    actual_files = {path.name for path in entries}
    if actual_files != expected_files:
        raise ValueError("candidate_native_artifact_set_invalid")

    return {
        "schema_version": CANDIDATE_SCHEMA,
        "commit_sha": commit_sha,
        "version": version,
        "source_ci": {
            "workflow": "CI",
            "workflow_path": ".github/workflows/ci.yml",
            "event": "push",
            "branch": "main",
            "run_id": source_ci_run_id,
            "run_attempt": source_ci_run_attempt,
        },
        "candidate_workflow": {
            "workflow": "Release Candidate",
            "workflow_path": ".github/workflows/candidate.yml",
            "event": candidate_workflow_event,
            "branch": "main",
            "run_id": candidate_workflow_run_id,
            "run_attempt": candidate_workflow_run_attempt,
        },
        "image": {
            "reference": image_reference,
            "digest": image_digest,
            "workflow_run_id": image_workflow_run_id,
            "workflow_run_attempt": image_workflow_run_attempt,
            "candidate_tag": candidate_image_tag,
            "candidate_reference": f"{image_reference}:{candidate_image_tag}",
        },
        "native_artifacts": artifacts,
        "source_fingerprints": {
            "pyproject": sha256(repo_root / "pyproject.toml"),
            "uv_lock": sha256(repo_root / "uv.lock"),
            "web_package": sha256(repo_root / "web/package.json"),
            "web_lock": sha256(repo_root / "web/package-lock.json"),
            "candidate_workflow": sha256(repo_root / ".github/workflows/candidate.yml"),
            "dockerfile": sha256(repo_root / "Dockerfile"),
        },
        "toolchain": dict(_TOOLCHAIN),
        "promotion": {
            "method": "digest_and_bytes_only",
            "rebuild_forbidden": True,
            "stable_environment_required": True,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    _regular_file(path, "candidate_manifest_invalid")
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("candidate_manifest_too_large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate_manifest_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("candidate_manifest_invalid")
    return value


def verify_candidate_manifest(
    manifest_path: Path,
    *,
    artifact_dir: Path,
    expected_commit_sha: str,
    expected_version: str | None = None,
    expected_source_ci_run_id: int | None = None,
    expected_source_ci_run_attempt: int | None = None,
    expected_candidate_workflow_run_id: int | None = None,
    expected_candidate_workflow_run_attempt: int | None = None,
    expected_candidate_workflow_event: str | None = None,
    expected_image_reference: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    _regular_directory(artifact_dir, "candidate_manifest_native_artifacts_invalid")
    if repo_root is not None:
        _regular_directory(repo_root, "candidate_source_root_invalid")
    manifest = verify_candidate_manifest_metadata(
        manifest_path,
        expected_commit_sha=expected_commit_sha,
        expected_version=expected_version,
        expected_source_ci_run_id=expected_source_ci_run_id,
        expected_source_ci_run_attempt=expected_source_ci_run_attempt,
        expected_candidate_workflow_run_id=expected_candidate_workflow_run_id,
        expected_candidate_workflow_run_attempt=expected_candidate_workflow_run_attempt,
        expected_candidate_workflow_event=expected_candidate_workflow_event,
        expected_image_reference=expected_image_reference,
    )
    version = manifest["version"]
    artifacts = manifest["native_artifacts"]

    from tools.release_artifact import validate_archive

    for item in artifacts:
        filename = item["filename"]
        digest = item["sha256"]
        architecture = item["architecture"]
        archive = _regular_file(
            artifact_dir / filename, "candidate_manifest_native_artifact_invalid"
        )
        if sha256(archive) != digest:
            raise ValueError("candidate_manifest_native_artifact_checksum_mismatch")
        checksum_path = artifact_dir / (filename + ".sha256")
        if checksum_path.is_symlink() or not checksum_path.is_file():
            raise ValueError("candidate_manifest_native_artifact_checksum_file_invalid")
        checksum_fields = checksum_path.read_text(encoding="utf-8").strip().split()
        if checksum_fields != [digest, filename]:
            raise ValueError("candidate_manifest_native_artifact_checksum_file_invalid")
        validate_archive(
            archive,
            expected_commit_sha=expected_commit_sha,
            expected_architecture=architecture,
            expected_version=version,
        )
    expected_files = {str(item["filename"]) for item in artifacts} | {
        f"{item['filename']}.sha256" for item in artifacts
    }
    entries = list(artifact_dir.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("candidate_manifest_native_artifact_set_invalid")
    actual_files = {path.name for path in entries}
    if actual_files != expected_files:
        raise ValueError("candidate_manifest_native_artifact_set_invalid")
    if repo_root is not None:
        fingerprint_files = (
            ("pyproject", "pyproject.toml"),
            ("uv_lock", "uv.lock"),
            ("web_package", "web/package.json"),
            ("web_lock", "web/package-lock.json"),
            ("candidate_workflow", ".github/workflows/candidate.yml"),
            ("dockerfile", "Dockerfile"),
        )
        fingerprints = manifest["source_fingerprints"]
        for field, filename in fingerprint_files:
            expected = fingerprints[field]
            source = repo_root / filename
            if (
                source.is_symlink()
                or not source.is_file()
                or sha256(source) != expected
            ):
                raise ValueError("candidate_manifest_source_fingerprint_mismatch")
    return manifest


def verify_candidate_manifest_metadata(
    manifest_path: Path,
    *,
    expected_commit_sha: str,
    expected_version: str | None = None,
    expected_source_ci_run_id: int | None = None,
    expected_source_ci_run_attempt: int | None = None,
    expected_candidate_workflow_run_id: int | None = None,
    expected_candidate_workflow_run_attempt: int | None = None,
    expected_candidate_workflow_event: str | None = None,
    expected_image_reference: str | None = None,
) -> dict[str, Any]:
    """Validate candidate identity and inventory without reading artifact bytes."""
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != CANDIDATE_SCHEMA:
        raise ValueError("candidate_manifest_schema_unsupported")
    commit_sha = manifest.get("commit_sha")
    if (
        commit_sha != expected_commit_sha
        or _FULL_SHA.fullmatch(str(commit_sha)) is None
    ):
        raise ValueError("candidate_manifest_commit_sha_mismatch")
    version = manifest.get("version")
    if (
        not isinstance(version, str)
        or _VERSION.fullmatch(version) is None
        or (expected_version is not None and version != expected_version)
    ):
        raise ValueError("candidate_manifest_version_mismatch")
    source_ci = manifest.get("source_ci")
    if (
        not isinstance(source_ci, dict)
        or source_ci.get("workflow") != "CI"
        or source_ci.get("workflow_path") != ".github/workflows/ci.yml"
        or source_ci.get("event") != "push"
        or source_ci.get("branch") != "main"
    ):
        raise ValueError("candidate_manifest_source_ci_invalid")
    for field in ("run_id", "run_attempt"):
        if type(source_ci.get(field)) is not int or source_ci[field] <= 0:
            raise ValueError("candidate_manifest_source_ci_invalid")
    if (
        expected_source_ci_run_id is not None
        and source_ci["run_id"] != expected_source_ci_run_id
    ):
        raise ValueError("candidate_manifest_source_ci_run_mismatch")
    if (
        expected_source_ci_run_attempt is not None
        and source_ci["run_attempt"] != expected_source_ci_run_attempt
    ):
        raise ValueError("candidate_manifest_source_ci_attempt_mismatch")
    candidate_workflow = manifest.get("candidate_workflow")
    if (
        not isinstance(candidate_workflow, dict)
        or candidate_workflow.get("workflow") != "Release Candidate"
        or candidate_workflow.get("workflow_path") != ".github/workflows/candidate.yml"
        or candidate_workflow.get("event") not in {"push", "workflow_dispatch"}
        or candidate_workflow.get("branch") != "main"
        or not _positive_run_identity(
            candidate_workflow.get("run_id"), candidate_workflow.get("run_attempt")
        )
    ):
        raise ValueError("candidate_manifest_workflow_invalid")
    if (
        expected_candidate_workflow_run_id is not None
        and candidate_workflow["run_id"] != expected_candidate_workflow_run_id
    ):
        raise ValueError("candidate_manifest_workflow_run_mismatch")
    if (
        expected_candidate_workflow_run_attempt is not None
        and candidate_workflow["run_attempt"] != expected_candidate_workflow_run_attempt
    ):
        raise ValueError("candidate_manifest_workflow_attempt_mismatch")
    if (
        expected_candidate_workflow_event is not None
        and candidate_workflow["event"] != expected_candidate_workflow_event
    ):
        raise ValueError("candidate_manifest_workflow_event_mismatch")
    image = manifest.get("image")
    if (
        not isinstance(image, dict)
        or not isinstance(image.get("reference"), str)
        or not isinstance(image.get("digest"), str)
        or _IMAGE_REFERENCE.fullmatch(str(image.get("reference"))) is None
    ):
        raise ValueError("candidate_manifest_image_invalid")
    _require_identity(expected_commit_sha, image["digest"])
    if (
        expected_image_reference is not None
        and image["reference"] != expected_image_reference
    ):
        raise ValueError("candidate_manifest_image_reference_mismatch")
    if (
        not _positive_run_identity(
            image.get("workflow_run_id"), image.get("workflow_run_attempt")
        )
        or image["workflow_run_id"] != candidate_workflow["run_id"]
        or image["workflow_run_attempt"] > candidate_workflow["run_attempt"]
    ):
        raise ValueError("candidate_manifest_image_workflow_invalid")
    expected_candidate_tag = _candidate_image_tag(
        expected_commit_sha,
        image["workflow_run_id"],
        image["workflow_run_attempt"],
    )
    if (
        image.get("candidate_tag") != expected_candidate_tag
        or image.get("candidate_reference")
        != f"{image['reference']}:{expected_candidate_tag}"
    ):
        raise ValueError("candidate_manifest_image_tag_invalid")

    artifacts = manifest.get("native_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("candidate_manifest_native_artifacts_invalid")
    architectures: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValueError("candidate_manifest_native_artifacts_invalid")
        filename = item.get("filename")
        digest = item.get("sha256")
        architecture = item.get("architecture")
        if (
            not isinstance(filename, str)
            or not isinstance(digest, str)
            or not isinstance(architecture, str)
        ):
            raise ValueError("candidate_manifest_native_artifacts_invalid")
        filename_match = _NATIVE_NAME.fullmatch(filename)
        expected_filename = f"karkinos-{version}-macos-{architecture}.tar.gz"
        if (
            filename_match is None
            or filename != expected_filename
            or architecture not in {"arm64", "x86_64"}
            or filename_match.group(1) != architecture
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("candidate_manifest_native_artifacts_invalid")
        if architecture in architectures:
            raise ValueError("candidate_manifest_duplicate_architecture")
        architectures.add(architecture)
    if architectures != {"arm64", "x86_64"}:
        raise ValueError("candidate_manifest_architectures_incomplete")
    fingerprints = manifest.get("source_fingerprints")
    if not isinstance(fingerprints, dict):
        raise ValueError("candidate_manifest_source_fingerprints_invalid")
    fingerprint_files = (
        ("pyproject", "pyproject.toml"),
        ("uv_lock", "uv.lock"),
        ("web_package", "web/package.json"),
        ("web_lock", "web/package-lock.json"),
        ("candidate_workflow", ".github/workflows/candidate.yml"),
        ("dockerfile", "Dockerfile"),
    )
    for field, _filename in fingerprint_files:
        expected = fingerprints.get(field)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("candidate_manifest_source_fingerprints_invalid")
    if manifest.get("toolchain") != _TOOLCHAIN:
        raise ValueError("candidate_manifest_toolchain_mismatch")
    if manifest.get("promotion") != {
        "method": "digest_and_bytes_only",
        "rebuild_forbidden": True,
        "stable_environment_required": True,
    }:
        raise ValueError("candidate_manifest_promotion_policy_invalid")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--repo-root", type=Path, default=Path("."))
    build.add_argument("--artifact-dir", type=Path, required=True)
    build.add_argument("--commit-sha", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--source-ci-run-id", type=int, required=True)
    build.add_argument("--source-ci-run-attempt", type=int, required=True)
    build.add_argument("--candidate-workflow-run-id", type=int, required=True)
    build.add_argument("--candidate-workflow-run-attempt", type=int, required=True)
    build.add_argument(
        "--candidate-workflow-event",
        choices=("push", "workflow_dispatch"),
        required=True,
    )
    build.add_argument("--image-workflow-run-id", type=int, required=True)
    build.add_argument("--image-workflow-run-attempt", type=int, required=True)
    build.add_argument("--image-reference", required=True)
    build.add_argument("--image-digest", required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--artifact-dir", type=Path, required=True)
    verify.add_argument("--commit-sha", required=True)
    verify.add_argument("--version")
    verify.add_argument("--source-ci-run-id", type=int)
    verify.add_argument("--source-ci-run-attempt", type=int)
    verify.add_argument("--candidate-selection", type=Path)
    verify.add_argument("--repository")
    verify.add_argument("--image-reference")
    verify.add_argument("--repo-root", type=Path)
    verify_image = subparsers.add_parser("verify-image-metadata")
    verify_image.add_argument("--metadata", type=Path, required=True)
    verify_image.add_argument("--image-reference", required=True)
    verify_image.add_argument("--image-digest", required=True)
    verify_image.add_argument("--commit-sha", required=True)
    verify_image.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            payload = build_candidate_manifest(
                repo_root=args.repo_root.expanduser().absolute(),
                artifact_dir=args.artifact_dir.expanduser().absolute(),
                commit_sha=args.commit_sha,
                version=args.version,
                source_ci_run_id=args.source_ci_run_id,
                source_ci_run_attempt=args.source_ci_run_attempt,
                candidate_workflow_run_id=args.candidate_workflow_run_id,
                candidate_workflow_run_attempt=args.candidate_workflow_run_attempt,
                candidate_workflow_event=args.candidate_workflow_event,
                image_workflow_run_id=args.image_workflow_run_id,
                image_workflow_run_attempt=args.image_workflow_run_attempt,
                image_reference=args.image_reference,
                image_digest=args.image_digest,
            )
            output = args.output.expanduser().absolute()
            if output.exists() or output.is_symlink():
                raise ValueError("candidate_manifest_output_already_exists")
            for ancestor in (output.parent, *output.parent.parents):
                if ancestor.is_symlink():
                    raise ValueError("candidate_manifest_output_symlink_unsupported")
                if ancestor.parent == ancestor:
                    break
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif args.command == "verify-image-metadata":
            payload = verify_candidate_image_metadata(
                args.metadata.expanduser().absolute(),
                image_reference=args.image_reference,
                image_digest=args.image_digest,
                commit_sha=args.commit_sha,
                version=args.version,
            )
        else:
            expected_candidate_run_id: int | None = None
            expected_candidate_run_attempt: int | None = None
            expected_candidate_event: str | None = None
            if args.candidate_selection is not None:
                if not args.repository:
                    raise ValueError("candidate_selection_repository_missing")
                from tools.download_candidate import read_candidate_selection

                selection = read_candidate_selection(
                    args.candidate_selection.expanduser().absolute(),
                    expected_repository=args.repository,
                    expected_commit_sha=args.commit_sha,
                )
                workflow = selection["workflow"]
                assert isinstance(workflow, dict)
                expected_candidate_run_id = workflow["run_id"]
                expected_candidate_run_attempt = workflow["run_attempt"]
                expected_candidate_event = workflow["event"]
            payload = verify_candidate_manifest(
                args.manifest.expanduser().absolute(),
                artifact_dir=args.artifact_dir.expanduser().absolute(),
                expected_commit_sha=args.commit_sha,
                expected_version=args.version,
                expected_source_ci_run_id=args.source_ci_run_id,
                expected_source_ci_run_attempt=args.source_ci_run_attempt,
                expected_candidate_workflow_run_id=expected_candidate_run_id,
                expected_candidate_workflow_run_attempt=(
                    expected_candidate_run_attempt
                ),
                expected_candidate_workflow_event=expected_candidate_event,
                expected_image_reference=args.image_reference,
                repo_root=(
                    args.repo_root.expanduser().absolute() if args.repo_root else None
                ),
            )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, tarfile.TarError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
