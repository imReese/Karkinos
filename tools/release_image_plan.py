#!/usr/bin/env python3
"""Build the fail-closed tag and image plan for an official release."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

_SEMVER_TAG = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?$"
)
_PHASE_ORDER = {"alpha": 0, "beta": 1, "rc": 2, None: 3}
_MISSING_MANIFEST_MARKERS = (
    "manifest unknown",
    "no such manifest",
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _inspect_registry(image_tag: str, *, raw: bool = False):
    if not image_tag or any(character.isspace() for character in image_tag):
        raise ValueError("release_image_tag_invalid")
    try:
        command = ["docker", "buildx", "imagetools", "inspect"]
        if raw:
            command.append("--raw")
        command.append(image_tag)
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"immutable_release_image_tag_preflight_inconclusive:{image_tag}"
        ) from exc


def _registry_digest(image_tag: str, result) -> str:
    matches = re.findall(
        r"^Digest:\s+(sha256:[0-9a-f]{64})\s*$",
        result.stdout,
        re.MULTILINE,
    )
    if len(matches) != 1 or not _DIGEST.fullmatch(matches[0]):
        raise RuntimeError(
            f"immutable_release_image_tag_digest_unavailable:{image_tag}"
        )
    return matches[0]


def assert_registry_image_tag_absent(image_tag: str) -> None:
    """Reject an image reference unless the registry proves it is missing."""
    result = _inspect_registry(image_tag, raw=True)
    if result.returncode == 0:
        raise ValueError(f"immutable_release_image_tag_already_exists:{image_tag}")

    failure = f"{result.stdout}\n{result.stderr}".lower()
    image_not_found = f"{image_tag.lower()}: not found" in failure
    if not image_not_found and not any(
        marker in failure for marker in _MISSING_MANIFEST_MARKERS
    ):
        raise RuntimeError(
            f"immutable_release_image_tag_preflight_inconclusive:{image_tag}"
        )


@dataclass(frozen=True)
class ReleaseImagePlan:
    tag: str
    version: str
    image: str
    immutable_image_tags: tuple[str, ...]
    image_tags: tuple[str, ...]
    is_prerelease: bool


def build_release_image_plan(
    *,
    tag: str,
    repository: str,
    commit_sha: str,
    server_version: str,
    web_version: str,
    lock_version: str,
    existing_tags: Sequence[str],
) -> ReleaseImagePlan:
    current_key = _semver_key(tag)
    version = tag.removeprefix("v")
    if any(
        candidate != version
        for candidate in (server_version, web_version, lock_version)
    ):
        raise ValueError("release_tag_and_package_versions_must_match")
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise ValueError("release_commit_sha_must_be_full_lowercase_sha1")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("release_repository_identity_invalid")

    previous_stable_keys = []
    for existing in existing_tags:
        if existing == tag or _SEMVER_TAG.fullmatch(existing) is None:
            continue
        existing_key = _semver_key(existing)
        if existing_key[3] == _PHASE_ORDER[None]:
            previous_stable_keys.append(existing_key)

    image = f"ghcr.io/{repository.lower()}"
    immutable_image_tags = (f"{image}:{tag}", f"{image}:sha-{commit_sha}")
    image_tags = list(immutable_image_tags)
    is_prerelease = current_key[3] != _PHASE_ORDER[None]
    is_newest_stable = not previous_stable_keys or current_key > max(
        previous_stable_keys
    )
    if not is_prerelease and is_newest_stable:
        major, minor, _patch = current_key[:3]
        image_tags.extend(
            (f"{image}:latest", f"{image}:v{major}", f"{image}:v{major}.{minor}")
        )
    return ReleaseImagePlan(
        tag=tag,
        version=version,
        image=image,
        immutable_image_tags=immutable_image_tags,
        image_tags=tuple(image_tags),
        is_prerelease=is_prerelease,
    )


def assert_registry_image_tag_compatible(image_tag: str, expected_digest: str) -> None:
    """Allow a missing tag or the same immutable digest, never another digest."""
    if _DIGEST.fullmatch(expected_digest) is None:
        raise ValueError("release_image_digest_invalid")
    result = _inspect_registry(image_tag)
    if result.returncode != 0:
        failure = f"{result.stdout}\n{result.stderr}".lower()
        image_not_found = f"{image_tag.lower()}: not found" in failure
        if image_not_found or any(
            marker in failure for marker in _MISSING_MANIFEST_MARKERS
        ):
            return
        raise RuntimeError(
            f"immutable_release_image_tag_preflight_inconclusive:{image_tag}"
        )
    if _registry_digest(image_tag, result) != expected_digest:
        raise ValueError(f"immutable_release_image_tag_digest_conflict:{image_tag}")


def assert_immutable_image_tags_absent(plan: ReleaseImagePlan) -> None:
    """Reject a release when either immutable registry tag may already exist."""

    for image_tag in plan.immutable_image_tags:
        assert_registry_image_tag_absent(image_tag)


def assert_immutable_image_tags_compatible(
    plan: ReleaseImagePlan, expected_digest: str
) -> None:
    """Preflight immutable tags for safe first publish or exact-digest retry."""
    for image_tag in plan.immutable_image_tags:
        assert_registry_image_tag_compatible(image_tag, expected_digest)


def _semver_key(tag: str) -> tuple[int, int, int, int, int]:
    match = _SEMVER_TAG.fullmatch(tag)
    if match is None:
        raise ValueError("release_tag_must_be_strict_semver")
    major, minor, patch, phase, phase_number = match.groups()
    try:
        return (
            int(major),
            int(minor),
            int(patch),
            _PHASE_ORDER[phase],
            int(phase_number or 0),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError("release_tag_must_be_strict_semver") from exc


def _read_server_version(path: Path) -> str:
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"\s*$',
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise ValueError("server_version_not_found")
    return match.group(1)


def _read_json_version(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("web_version_not_found") from exc
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("web_version_not_found")
    return version


def _git_tags(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "tag", "--list", "v*"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _append_github_outputs(path: Path, plan: ReleaseImagePlan) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"tag={plan.tag}\n")
        output.write(f"version={plan.version}\n")
        output.write(f"image={plan.image}\n")
        output.write(f"is_prerelease={str(plan.is_prerelease).lower()}\n")
        output.write("tags<<EOF\n")
        output.writelines(f"{tag}\n" for tag in plan.image_tags)
        output.write("EOF\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--verify-immutable-image-tags-absent",
        action="store_true",
    )
    parser.add_argument(
        "--verify-immutable-image-tags-compatible",
        action="store_true",
    )
    parser.add_argument("--expected-image-digest")
    args = parser.parse_args()
    try:
        repo_root = args.repo_root.resolve()
        plan = build_release_image_plan(
            tag=args.tag,
            repository=args.repository,
            commit_sha=args.commit_sha,
            server_version=_read_server_version(repo_root / "server/__init__.py"),
            web_version=_read_json_version(repo_root / "web/package.json"),
            lock_version=_read_json_version(repo_root / "web/package-lock.json"),
            existing_tags=_git_tags(repo_root),
        )
        if (
            args.verify_immutable_image_tags_absent
            and args.verify_immutable_image_tags_compatible
        ):
            raise ValueError("release_image_tag_preflight_modes_conflict")
        if args.verify_immutable_image_tags_absent:
            assert_immutable_image_tags_absent(plan)
        if args.verify_immutable_image_tags_compatible:
            if args.expected_image_digest is None:
                raise ValueError("release_image_digest_required")
            assert_immutable_image_tags_compatible(plan, args.expected_image_digest)
        if args.github_output is not None:
            _append_github_outputs(args.github_output, plan)
        else:
            print(json.dumps(asdict(plan), sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
