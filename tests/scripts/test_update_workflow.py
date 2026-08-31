from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

from scripts.release import update_workflow
from tools import release_fetch

_SHA = "a" * 40
_OTHER_SHA = "b" * 40
_TAG = "v1.2.3"
_TOKEN = "github_pat_sensitive_value"


def _fetched(
    output_dir: Path,
    *,
    source: str,
    commit_sha: str = _SHA,
    tag: str | None = None,
) -> release_fetch.VerifiedNativeArchive:
    output_dir.mkdir(mode=0o700)
    archive = output_dir / "karkinos-1.2.3-macos-arm64.tar.gz"
    checksum = output_dir / f"{archive.name}.sha256"
    manifest = output_dir / "candidate-manifest.json"
    archive.write_bytes(b"archive")
    checksum.write_text("digest  archive\n", encoding="utf-8")
    manifest.write_text("{}\n", encoding="utf-8")
    for path in (archive, checksum, manifest):
        path.chmod(0o600)
    return release_fetch.VerifiedNativeArchive(
        source=source,
        repository=update_workflow.DEFAULT_REPOSITORY,
        commit_sha=commit_sha,
        version="1.2.3",
        architecture="arm64",
        archive=archive,
        checksum=checksum,
        candidate_manifest=manifest,
        tag=tag,
    )


def _callbacks(
    events: list[tuple[object, ...]],
) -> update_workflow.ReleaseWorkflowCallbacks:
    def preflight() -> None:
        events.append(("preflight",))

    def stage(archive: Path, sha: str) -> object:
        events.append(("stage", archive.exists(), sha, str(archive)))
        return None

    def run_candidate(sha: str, port: int) -> object:
        events.append(("run", sha, port))
        return "ran"

    def discard(sha: str) -> object:
        events.append(("discard", sha))
        return None

    def deploy(sha: str, confirmation: str, timeout: int) -> object:
        events.append(("deploy", sha, confirmation, timeout))
        return "deployed"

    return update_workflow.ReleaseWorkflowCallbacks(
        preflight=preflight,
        stage=stage,
        run_candidate=run_candidate,
        discard=discard,
        deploy=deploy,
    )


def test_candidate_prefers_environment_token_without_gh_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[object, ...]] = []

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        assert kwargs["token"] == _TOKEN
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        assert stat.S_IMODE(output_dir.parent.stat().st_mode) == 0o700
        return _fetched(output_dir, source="actions-candidate")

    def unexpected_runner(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("GH_TOKEN must take precedence")

    monkeypatch.setattr(release_fetch, "fetch_candidate_native", fetch)
    result = update_workflow.run_candidate_workflow(
        _callbacks(events),
        commit_sha=_SHA,
        environment={"GH_TOKEN": _TOKEN},
        gh_auth_runner=unexpected_runner,  # type: ignore[arg-type]
        temporary_parent=tmp_path,
    )

    assert result == "ran"
    assert [event[0] for event in events] == ["stage", "run", "discard"]
    assert events[1] == ("run", _SHA, 18000)
    assert list(tmp_path.iterdir()) == []


def test_candidate_uses_bounded_gh_auth_fallback_without_token_in_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def auth_runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert kwargs["timeout"] == 15
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert "GH_TOKEN" not in environment
        assert _TOKEN not in command
        return subprocess.CompletedProcess(command, 0, stdout=f"{_TOKEN}\n", stderr="")

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        assert kwargs["token"] == _TOKEN
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="actions-candidate")

    monkeypatch.setattr(release_fetch, "fetch_candidate_native", fetch)
    update_workflow.run_candidate_workflow(
        _callbacks([]),
        commit_sha=_SHA,
        environment={"PATH": os.environ.get("PATH", ""), "GH_TOKEN": ""},
        gh_auth_runner=auth_runner,
        temporary_parent=tmp_path,
    )

    assert commands == [["gh", "auth", "token"]]
    assert list(tmp_path.iterdir()) == []


def test_gh_auth_and_fetch_errors_do_not_leak_tokens_or_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_auth(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"attestation stderr contained {_TOKEN}",
        )

    with pytest.raises(ValueError) as auth_error:
        update_workflow.run_candidate_workflow(
            _callbacks([]),
            commit_sha=_SHA,
            environment={},
            gh_auth_runner=failed_auth,
            temporary_parent=tmp_path,
        )
    assert str(auth_error.value) == "release_update_gh_auth_failed"
    assert _TOKEN not in str(auth_error.value)
    assert "attestation stderr" not in str(auth_error.value)

    def failed_fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        raise RuntimeError(f"{kwargs['token']}: attestation stderr")

    monkeypatch.setattr(release_fetch, "fetch_candidate_native", failed_fetch)
    with pytest.raises(ValueError) as fetch_error:
        update_workflow.run_candidate_workflow(
            _callbacks([]),
            commit_sha=_SHA,
            environment={"GH_TOKEN": _TOKEN},
            temporary_parent=tmp_path,
        )
    assert str(fetch_error.value) == "release_update_candidate_fetch_failed"
    assert _TOKEN not in str(fetch_error.value)
    assert "attestation stderr" not in str(fetch_error.value)
    assert list(tmp_path.iterdir()) == []


def test_candidate_discards_stage_and_download_when_run_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[object, ...]] = []

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="actions-candidate")

    def fail_run(sha: str, port: int) -> object:
        events.append(("run", sha, port))
        raise RuntimeError("candidate failed")

    callbacks = update_workflow.ReleaseWorkflowCallbacks(
        preflight=lambda: None,
        stage=lambda archive, sha: events.append(("stage", archive.exists(), sha)),
        run_candidate=fail_run,
        discard=lambda sha: events.append(("discard", sha)),
        deploy=lambda *_args: None,
    )
    monkeypatch.setattr(release_fetch, "fetch_candidate_native", fetch)

    with pytest.raises(RuntimeError, match="candidate failed"):
        update_workflow.run_candidate_workflow(
            callbacks,
            commit_sha=_SHA,
            environment={"GH_TOKEN": _TOKEN},
            temporary_parent=tmp_path,
        )

    assert [event[0] for event in events] == ["stage", "run", "discard"]
    assert list(tmp_path.iterdir()) == []


def test_candidate_cleanup_failure_does_not_mask_run_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="actions-candidate")

    def fail_run(_sha: str, _port: int) -> object:
        raise RuntimeError("candidate failed")

    def fail_discard(_sha: str) -> object:
        raise KeyboardInterrupt("cleanup interrupted")

    callbacks = update_workflow.ReleaseWorkflowCallbacks(
        preflight=lambda: None,
        stage=lambda *_args: None,
        run_candidate=fail_run,
        discard=fail_discard,
        deploy=lambda *_args: None,
    )
    monkeypatch.setattr(release_fetch, "fetch_candidate_native", fetch)

    with pytest.raises(RuntimeError, match="candidate failed"):
        update_workflow.run_candidate_workflow(
            callbacks,
            commit_sha=_SHA,
            environment={"GH_TOKEN": _TOKEN},
            temporary_parent=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("tag", "confirmation"),
    [
        ("v1.2.3-rc.1", "UPDATE v1.2.3-rc.1"),
        (_TAG, "UPDATE v1.2.4"),
    ],
)
def test_stable_validation_stops_before_preflight_and_network(
    tag: str,
    confirmation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []

    def unexpected_fetch(**_kwargs: object) -> release_fetch.VerifiedNativeArchive:
        raise AssertionError("network fetch must not run")

    monkeypatch.setattr(release_fetch, "fetch_stable_native", unexpected_fetch)
    with pytest.raises(ValueError):
        update_workflow.run_stable_update_workflow(
            _callbacks(events), tag=tag, confirmation=confirmation
        )

    assert events == []


@pytest.mark.parametrize("health_timeout", (True, 0, 3601, 1.5))
def test_health_timeout_contract_stops_before_preflight_and_network(
    health_timeout: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        release_fetch,
        "fetch_stable_native",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )

    with pytest.raises(ValueError, match="release_update_health_timeout_invalid"):
        update_workflow.run_stable_update_workflow(
            _callbacks(events),
            tag=_TAG,
            confirmation=f"UPDATE {_TAG}",
            health_timeout=health_timeout,  # type: ignore[arg-type]
        )

    assert events == []


@pytest.mark.parametrize("health_timeout", (1, 3600))
def test_health_timeout_contract_accepts_inclusive_integer_boundaries(
    health_timeout: int,
) -> None:
    assert update_workflow._require_health_timeout(health_timeout) == health_timeout


def test_stable_preflight_failure_stops_before_auth_and_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callbacks = update_workflow.ReleaseWorkflowCallbacks(
        preflight=lambda: (_ for _ in ()).throw(
            ValueError("release_update_requires_current")
        ),
        stage=lambda *_args: (_ for _ in ()).throw(AssertionError("stage")),
        run_candidate=lambda *_args: None,
        discard=lambda *_args: None,
        deploy=lambda *_args: (_ for _ in ()).throw(AssertionError("deploy")),
    )
    monkeypatch.setattr(
        release_fetch,
        "fetch_stable_native",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )

    with pytest.raises(ValueError, match="release_update_requires_current"):
        update_workflow.run_stable_update_workflow(
            callbacks,
            tag=_TAG,
            confirmation=f"UPDATE {_TAG}",
            environment={"GH_TOKEN": " invalid token "},
        )


def test_stable_fetches_exact_tag_then_stages_and_deploys_proven_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[object, ...]] = []

    def auth_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["gh", "auth", "token"]
        return subprocess.CompletedProcess(command, 0, stdout=f"{_TOKEN}\n", stderr="")

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        assert kwargs == {
            "repository": update_workflow.DEFAULT_REPOSITORY,
            "tag": _TAG,
            "output_dir": kwargs["output_dir"],
            "token": _TOKEN,
        }
        events.append(("fetch", _TAG))
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="github-release", tag=_TAG)

    monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)
    result = update_workflow.run_stable_update_workflow(
        _callbacks(events),
        tag=_TAG,
        confirmation=f"UPDATE {_TAG}",
        health_timeout=12,
        environment={},
        gh_auth_runner=auth_runner,
        temporary_parent=tmp_path,
    )

    assert result == "deployed"
    assert [event[0] for event in events] == [
        "preflight",
        "fetch",
        "stage",
        "deploy",
    ]
    assert events[-1] == ("deploy", _SHA, f"PROMOTE {_SHA}", 12)
    assert list(tmp_path.iterdir()) == []


def test_stable_callback_failure_still_removes_temporary_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[object, ...]] = []

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="github-release", tag=_TAG)

    def fail_deploy(sha: str, confirmation: str, timeout: float) -> object:
        events.append(("deploy", sha, confirmation, timeout))
        raise RuntimeError("activation failed")

    callbacks = update_workflow.ReleaseWorkflowCallbacks(
        preflight=lambda: events.append(("preflight",)),
        stage=lambda archive, sha: events.append(("stage", archive.exists(), sha)),
        run_candidate=lambda *_args: None,
        discard=lambda sha: events.append(("discard", sha)),
        deploy=fail_deploy,
    )
    monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)

    with pytest.raises(RuntimeError, match="activation failed"):
        update_workflow.run_stable_update_workflow(
            callbacks,
            tag=_TAG,
            confirmation=f"UPDATE {_TAG}",
            environment={"GH_TOKEN": _TOKEN},
            temporary_parent=tmp_path,
        )

    assert [event[0] for event in events] == [
        "preflight",
        "stage",
        "deploy",
        "discard",
    ]
    assert list(tmp_path.iterdir()) == []


def test_stable_cleanup_failure_does_not_mask_activation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="github-release", tag=_TAG)

    callbacks = update_workflow.ReleaseWorkflowCallbacks(
        preflight=lambda: None,
        stage=lambda *_args: None,
        run_candidate=lambda *_args: None,
        discard=lambda _sha: (_ for _ in ()).throw(
            KeyboardInterrupt("journal retained")
        ),
        deploy=lambda *_args: (_ for _ in ()).throw(RuntimeError("activation failed")),
    )
    monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)

    with pytest.raises(RuntimeError, match="activation failed"):
        update_workflow.run_stable_update_workflow(
            callbacks,
            tag=_TAG,
            confirmation=f"UPDATE {_TAG}",
            environment={"GH_TOKEN": _TOKEN},
            temporary_parent=tmp_path,
        )


def test_stable_bootstrap_preflights_then_uses_proven_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[object, ...]] = []
    local_archive = tmp_path / "installer-download.tar.gz"

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        events.append(("fetch", kwargs["tag"]))
        assert kwargs["local_archive"] == local_archive
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="github-release", tag=_TAG)

    callbacks = update_workflow.LegacyBootstrapWorkflowCallbacks(
        preflight=lambda: events.append(("preflight",)),
        stage=lambda archive, sha: events.append(("stage", archive.exists(), sha)),
        bootstrap=lambda sha, confirmation, timeout: events.append(
            ("bootstrap", sha, confirmation, timeout)
        )
        or "bootstrapped",
        discard=lambda sha: events.append(("discard", sha)),
    )
    monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)

    result = update_workflow.run_stable_bootstrap_workflow(
        callbacks,
        tag=_TAG,
        confirmation=f"BOOTSTRAP {_TAG}",
        health_timeout=14,
        environment={"GH_TOKEN": _TOKEN},
        local_archive=local_archive,
        temporary_parent=tmp_path,
    )

    assert result == "bootstrapped"
    assert [event[0] for event in events] == [
        "preflight",
        "fetch",
        "stage",
        "bootstrap",
    ]
    assert events[-1] == ("bootstrap", _SHA, f"BOOTSTRAP {_SHA}", 14)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("workflow", ("candidate", "stable-update", "bootstrap"))
def test_workflow_resolves_default_temp_parent_symlink(
    workflow: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    physical_parent = tmp_path / "physical"
    physical_parent.mkdir()
    symlink_parent = tmp_path / "temporary-alias"
    symlink_parent.symlink_to(physical_parent, target_is_directory=True)
    monkeypatch.setattr(tempfile, "tempdir", str(symlink_parent))

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        assert output_dir.parent.parent == physical_parent.resolve(strict=True)
        source = "actions-candidate" if workflow == "candidate" else "github-release"
        tag = None if workflow == "candidate" else _TAG
        return _fetched(output_dir, source=source, tag=tag)

    if workflow == "candidate":
        monkeypatch.setattr(release_fetch, "fetch_candidate_native", fetch)
        result = update_workflow.run_candidate_workflow(
            _callbacks([]),
            commit_sha=_SHA,
            environment={"GH_TOKEN": _TOKEN},
        )
        assert result == "ran"
    elif workflow == "stable-update":
        monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)
        result = update_workflow.run_stable_update_workflow(
            _callbacks([]),
            tag=_TAG,
            confirmation=f"UPDATE {_TAG}",
            environment={"GH_TOKEN": _TOKEN},
        )
        assert result == "deployed"
    else:
        callbacks = update_workflow.LegacyBootstrapWorkflowCallbacks(
            preflight=lambda: None,
            stage=lambda *_args: None,
            bootstrap=lambda *_args: "bootstrapped",
            discard=lambda *_args: None,
        )
        monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)
        result = update_workflow.run_stable_bootstrap_workflow(
            callbacks,
            tag=_TAG,
            confirmation=f"BOOTSTRAP {_TAG}",
            environment={"GH_TOKEN": _TOKEN},
            local_archive=tmp_path / "installer-download.tar.gz",
        )
        assert result == "bootstrapped"

    assert list(physical_parent.iterdir()) == []


@pytest.mark.parametrize(
    ("tag", "confirmation"),
    [
        ("v1.2.3-rc.1", "BOOTSTRAP v1.2.3-rc.1"),
        (_TAG, "BOOTSTRAP v1.2.4"),
    ],
)
def test_stable_bootstrap_validation_stops_before_preflight_and_network(
    tag: str,
    confirmation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    callbacks = update_workflow.LegacyBootstrapWorkflowCallbacks(
        preflight=lambda: events.append("preflight"),
        stage=lambda *_args: events.append("stage"),
        bootstrap=lambda *_args: events.append("bootstrap"),
        discard=lambda *_args: events.append("discard"),
    )
    monkeypatch.setattr(
        release_fetch,
        "fetch_stable_native",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )

    with pytest.raises(ValueError):
        update_workflow.run_stable_bootstrap_workflow(
            callbacks,
            tag=tag,
            confirmation=confirmation,
        )

    assert events == []


def test_stable_bootstrap_failure_discards_only_after_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="github-release", tag=_TAG)

    callbacks = update_workflow.LegacyBootstrapWorkflowCallbacks(
        preflight=lambda: events.append("preflight"),
        stage=lambda *_args: events.append("stage"),
        bootstrap=lambda *_args: (_ for _ in ()).throw(RuntimeError("rolled back")),
        discard=lambda *_args: events.append("discard"),
    )
    monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)

    with pytest.raises(RuntimeError, match="rolled back"):
        update_workflow.run_stable_bootstrap_workflow(
            callbacks,
            tag=_TAG,
            confirmation=f"BOOTSTRAP {_TAG}",
            environment={"GH_TOKEN": _TOKEN},
            temporary_parent=tmp_path,
        )

    assert events == ["preflight", "stage", "discard"]
    assert list(tmp_path.iterdir()) == []


def test_stable_bootstrap_cleanup_failure_does_not_mask_bootstrap_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(output_dir, source="github-release", tag=_TAG)

    callbacks = update_workflow.LegacyBootstrapWorkflowCallbacks(
        preflight=lambda: None,
        stage=lambda *_args: None,
        bootstrap=lambda *_args: (_ for _ in ()).throw(
            RuntimeError("bootstrap failed")
        ),
        discard=lambda *_args: (_ for _ in ()).throw(
            KeyboardInterrupt("cleanup interrupted")
        ),
    )
    monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        update_workflow.run_stable_bootstrap_workflow(
            callbacks,
            tag=_TAG,
            confirmation=f"BOOTSTRAP {_TAG}",
            environment={"GH_TOKEN": _TOKEN},
            temporary_parent=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_fetch_identity_mismatch_fails_before_stage_or_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[object, ...]] = []

    def fetch(**kwargs: object) -> release_fetch.VerifiedNativeArchive:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        return _fetched(
            output_dir,
            source="github-release",
            commit_sha=_OTHER_SHA,
            tag="v1.2.4",
        )

    monkeypatch.setattr(release_fetch, "fetch_stable_native", fetch)
    with pytest.raises(ValueError, match="release_update_fetch_identity_mismatch"):
        update_workflow.run_stable_update_workflow(
            _callbacks(events),
            tag=_TAG,
            confirmation=f"UPDATE {_TAG}",
            environment={"GH_TOKEN": _TOKEN},
            temporary_parent=tmp_path,
        )

    assert events == [("preflight",)]
    assert list(tmp_path.iterdir()) == []
