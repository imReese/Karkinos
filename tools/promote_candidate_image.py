#!/usr/bin/env python3
"""Promote a candidate OCI manifest by digest without rebuilding source."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_REFERENCE = re.compile(
    r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+(?::[A-Za-z0-9_.-]+)?$"
)
_CANDIDATE_REFERENCE = re.compile(
    r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+:candidate-sha-[0-9a-f]{40}$"
)


def _inspect(reference: str) -> str:
    try:
        result = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", reference],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("candidate_image_inspection_inconclusive") from exc
    if result.returncode != 0:
        raise ValueError("candidate_image_missing")
    matches = re.findall(
        r"^Digest:\s+(sha256:[0-9a-f]{64})\s*$", result.stdout, re.MULTILINE
    )
    if len(matches) != 1:
        raise ValueError("candidate_image_digest_unavailable")
    return matches[0]


def _assert_compatible(reference: str, expected_digest: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", reference],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("stable_image_tag_preflight_inconclusive") from exc
    if result.returncode != 0:
        failure = f"{result.stdout}\n{result.stderr}".lower()
        if any(
            marker in failure
            for marker in ("manifest unknown", "not found", "no such manifest")
        ):
            return False
        raise ValueError("stable_image_tag_preflight_inconclusive")
    matches = re.findall(
        r"^Digest:\s+(sha256:[0-9a-f]{64})\s*$",
        result.stdout,
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise ValueError("stable_image_tag_digest_unavailable")
    if matches[0] != expected_digest:
        raise ValueError(f"stable_image_tag_digest_conflict:{reference}")
    return True


def _create(source: str, target: str) -> None:
    try:
        result = subprocess.run(
            ["docker", "buildx", "imagetools", "create", "--tag", target, source],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("stable_image_promotion_inconclusive") from exc
    if result.returncode != 0:
        raise ValueError("stable_image_promotion_failed")


def _require_image_reference(reference: str, error: str) -> None:
    if _IMAGE_REFERENCE.fullmatch(reference) is None:
        raise ValueError(error)


def promote(
    *,
    candidate_reference: str,
    expected_digest: str,
    targets: list[str],
    immutable_targets: list[str] | None = None,
) -> None:
    if _CANDIDATE_REFERENCE.fullmatch(candidate_reference) is None:
        raise ValueError("candidate_image_reference_invalid")
    if not _DIGEST.fullmatch(expected_digest):
        raise ValueError("candidate_image_digest_invalid")
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("stable_image_targets_invalid")
    immutable = set(immutable_targets or [])
    if not immutable.issubset(set(targets)):
        raise ValueError("stable_image_immutable_targets_invalid")
    candidate_base = candidate_reference.rsplit(":", 1)[0]
    if any(target.rsplit(":", 1)[0] != candidate_base for target in targets):
        raise ValueError("stable_image_target_repository_mismatch")
    if _inspect(candidate_reference) != expected_digest:
        raise ValueError("candidate_image_digest_mismatch")
    source = f"{candidate_reference}@{expected_digest}"
    existing_immutable: set[str] = set()
    for target in targets:
        _require_image_reference(target, "stable_image_target_invalid")
        if target in immutable and _assert_compatible(target, expected_digest):
            existing_immutable.add(target)
    for target in targets:
        if target in existing_immutable:
            continue
        _create(source, target)
        if _inspect(target) != expected_digest:
            raise ValueError(f"stable_image_digest_mismatch:{target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-reference", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--target", action="append", required=True)
    parser.add_argument("--immutable-target", action="append", default=[])
    args = parser.parse_args()
    try:
        promote(
            candidate_reference=args.candidate_reference,
            expected_digest=args.digest,
            targets=args.target,
            immutable_targets=args.immutable_target,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("stable image promotion completed by digest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
