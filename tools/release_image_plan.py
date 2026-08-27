#!/usr/bin/env python3
"""Build the fail-closed tag and image plan for an official release."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

_SEMVER_TAG = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?$"
)
_PHASE_ORDER = {"alpha": 0, "beta": 1, "rc": 2, None: 3}


@dataclass(frozen=True)
class ReleaseImagePlan:
    tag: str
    version: str
    image: str
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

    previous_keys = [
        _semver_key(existing)
        for existing in existing_tags
        if existing != tag and _SEMVER_TAG.fullmatch(existing)
    ]
    if previous_keys and current_key <= max(previous_keys):
        raise ValueError("release_tag_must_be_strictly_newer_than_existing_semver_tags")

    image = f"ghcr.io/{repository.lower()}"
    image_tags = [f"{image}:{tag}", f"{image}:sha-{commit_sha}"]
    is_prerelease = current_key[3] != _PHASE_ORDER[None]
    if not is_prerelease:
        major, minor, _patch = current_key[:3]
        image_tags.extend(
            (f"{image}:latest", f"{image}:v{major}", f"{image}:v{major}.{minor}")
        )
    return ReleaseImagePlan(
        tag=tag,
        version=version,
        image=image,
        image_tags=tuple(image_tags),
        is_prerelease=is_prerelease,
    )


def _semver_key(tag: str) -> tuple[int, int, int, int, int]:
    match = _SEMVER_TAG.fullmatch(tag)
    if match is None:
        raise ValueError("release_tag_must_be_strict_semver")
    major, minor, patch, phase, phase_number = match.groups()
    return (
        int(major),
        int(minor),
        int(patch),
        _PHASE_ORDER[phase],
        int(phase_number or 0),
    )


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
    payload = json.loads(path.read_text(encoding="utf-8"))
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
    args = parser.parse_args()
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
    if args.github_output is not None:
        _append_github_outputs(args.github_output, plan)
    else:
        print(json.dumps(asdict(plan), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
