from __future__ import annotations

import subprocess

import pytest

from tools import release_image_plan
from tools.release_image_plan import (
    assert_immutable_image_tags_absent,
    build_release_image_plan,
)

_SHA = "a" * 40


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


def test_out_of_order_release_cannot_move_stable_aliases_backwards() -> None:
    with pytest.raises(ValueError, match="strictly_newer"):
        _plan("v0.3.1", existing_tags=("v0.2.3", "v0.4.0"))


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


def test_registry_preflight_allows_fresh_immutable_tags(monkeypatch) -> None:
    inspected: list[list[str]] = []

    def missing_manifest(command, **kwargs):
        inspected.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"ERROR: {command[-1]}: not found\n",
        )

    monkeypatch.setattr(release_image_plan.subprocess, "run", missing_manifest)

    plan = _plan("v0.3.0")
    assert_immutable_image_tags_absent(plan)

    assert inspected == [
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            "--raw",
            "ghcr.io/imreese/karkinos:v0.3.0",
        ],
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            "--raw",
            f"ghcr.io/imreese/karkinos:sha-{_SHA}",
        ],
    ]


def test_registry_preflight_rejects_existing_version_tag(monkeypatch) -> None:
    def existing_manifest(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(release_image_plan.subprocess, "run", existing_manifest)

    with pytest.raises(ValueError, match="immutable_release_image_tag_already_exists"):
        assert_immutable_image_tags_absent(_plan("v0.3.0"))


def test_registry_preflight_rejects_existing_sha_tag(monkeypatch) -> None:
    results = iter(
        (
            subprocess.CompletedProcess((), 1, stdout="", stderr="manifest unknown"),
            subprocess.CompletedProcess((), 0, stdout="{}", stderr=""),
        )
    )

    monkeypatch.setattr(
        release_image_plan.subprocess,
        "run",
        lambda command, **kwargs: next(results),
    )

    with pytest.raises(ValueError, match=f"sha-{_SHA}"):
        assert_immutable_image_tags_absent(_plan("v0.3.0"))


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
        assert_immutable_image_tags_absent(_plan("v0.3.0"))


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
        assert_immutable_image_tags_absent(_plan("v0.3.0"))
