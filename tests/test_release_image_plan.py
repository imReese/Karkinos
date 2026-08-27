from __future__ import annotations

import pytest

from tools.release_image_plan import build_release_image_plan

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
