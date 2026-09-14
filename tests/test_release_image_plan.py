from __future__ import annotations

import subprocess

import pytest

from tools import release_image_plan
from tools.release_image_plan import (
    assert_immutable_image_tags_compatible,
    build_release_image_plan,
)

_SHA = "a" * 40
_DIGEST = "sha256:" + "b" * 64


def _plan(tag: str, *, existing_tags: tuple[str, ...] = ("v0.2.3",)):
    version = tag.removeprefix("v")
    return build_release_image_plan(
        tag=tag,
        repository="imReese/Karkinos",
        commit_sha=_SHA,
        server_version=version,
        web_version=version,
        lock_version=version,
        existing_tags=existing_tags,
    )


def test_stable_release_emits_immutable_and_monotonic_aliases() -> None:
    plan = _plan("v0.3.0")

    assert plan.is_prerelease is False
    assert plan.image == "ghcr.io/imreese/karkinos"
    assert plan.immutable_image_tags == (
        "ghcr.io/imreese/karkinos:v0.3.0",
        f"ghcr.io/imreese/karkinos:sha-{_SHA}",
    )
    assert plan.image_tags == (
        "ghcr.io/imreese/karkinos:v0.3.0",
        f"ghcr.io/imreese/karkinos:sha-{_SHA}",
        "ghcr.io/imreese/karkinos:latest",
        "ghcr.io/imreese/karkinos:v0",
        "ghcr.io/imreese/karkinos:v0.3",
    )


def test_prerelease_never_emits_stable_aliases() -> None:
    plan = _plan("v0.3.0-rc.1")

    assert plan.is_prerelease is True
    assert plan.image_tags == (
        "ghcr.io/imreese/karkinos:v0.3.0-rc.1",
        f"ghcr.io/imreese/karkinos:sha-{_SHA}",
    )


@pytest.mark.parametrize(
    "tag",
    ("v0.3", "v0.3.0-preview.1", "v00.3.0", "release-v0.3.0"),
)
def test_non_semver_release_tags_fail_closed(tag: str) -> None:
    with pytest.raises(ValueError, match="strict_semver"):
        _plan(tag)


def test_out_of_order_release_only_emits_immutable_tags() -> None:
    plan = _plan("v0.3.1", existing_tags=("v0.2.3", "v0.4.0"))

    assert plan.image_tags == plan.immutable_image_tags


def test_higher_prerelease_does_not_block_newest_stable_aliases() -> None:
    plan = _plan(
        "v0.3.1",
        existing_tags=("v0.2.3", "v0.4.0-rc.1"),
    )

    assert plan.image_tags[-3:] == (
        "ghcr.io/imreese/karkinos:latest",
        "ghcr.io/imreese/karkinos:v0",
        "ghcr.io/imreese/karkinos:v0.3",
    )


def test_release_versions_must_match_exactly() -> None:
    with pytest.raises(ValueError, match="versions_must_match"):
        build_release_image_plan(
            tag="v0.3.0",
            repository="imReese/Karkinos",
            commit_sha=_SHA,
            server_version="0.3.0",
            web_version="0.3.1",
            lock_version="0.3.0",
            existing_tags=("v0.2.3",),
        )


@pytest.mark.parametrize("already_published", [False, True])
def test_registry_preflight_allows_missing_or_same_digest_tags(
    monkeypatch, already_published: bool
) -> None:
    inspected: list[str] = []

    def inspect_manifest(command, **kwargs):
        inspected.append(command[-1])
        if already_published:
            return subprocess.CompletedProcess(
                command, 0, stdout=f"Digest: {_DIGEST}\n", stderr=""
            )
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"ERROR: {command[-1]}: not found\n",
        )

    monkeypatch.setattr(release_image_plan.subprocess, "run", inspect_manifest)

    plan = _plan("v0.3.0")
    assert_immutable_image_tags_compatible(plan, _DIGEST)

    assert inspected == list(plan.immutable_image_tags)


@pytest.mark.parametrize("conflicting_tag", [0, 1])
def test_registry_preflight_rejects_conflicting_version_or_sha_tag(
    monkeypatch, conflicting_tag: int
) -> None:
    plan = _plan("v0.3.0")

    def inspect_manifest(command, **kwargs):
        digest = (
            "sha256:" + "c" * 64
            if command[-1] == plan.immutable_image_tags[conflicting_tag]
            else _DIGEST
        )
        return subprocess.CompletedProcess(
            command, 0, stdout=f"Digest: {digest}\n", stderr=""
        )

    monkeypatch.setattr(release_image_plan.subprocess, "run", inspect_manifest)

    with pytest.raises(ValueError, match="immutable_release_image_tag_digest_conflict"):
        assert_immutable_image_tags_compatible(plan, _DIGEST)


@pytest.mark.parametrize(
    "failure",
    (
        "request canceled while waiting for connection",
        "unauthorized: authentication required",
        "unexpected status from registry endpoint: 404 Not Found",
        "",
    ),
)
def test_registry_preflight_fails_closed_when_lookup_is_inconclusive(
    monkeypatch, failure: str
) -> None:
    def inconclusive(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=failure)

    monkeypatch.setattr(release_image_plan.subprocess, "run", inconclusive)

    with pytest.raises(RuntimeError, match="preflight_inconclusive"):
        assert_immutable_image_tags_compatible(_plan("v0.3.0"), _DIGEST)


@pytest.mark.parametrize(
    "failure",
    (
        subprocess.TimeoutExpired(("docker", "buildx"), timeout=30),
        OSError("docker unavailable"),
    ),
)
def test_registry_preflight_fails_closed_when_inspector_cannot_run(
    monkeypatch, failure: BaseException
) -> None:
    def failed_inspector(command, **kwargs):
        raise failure

    monkeypatch.setattr(release_image_plan.subprocess, "run", failed_inspector)

    with pytest.raises(RuntimeError, match="preflight_inconclusive"):
        assert_immutable_image_tags_compatible(_plan("v0.3.0"), _DIGEST)
