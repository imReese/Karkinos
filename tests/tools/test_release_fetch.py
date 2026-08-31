from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import urllib.error
import zipfile
from pathlib import Path

import pytest

from server import __version__
from tools import release_artifact, release_fetch
from tools.release_candidate import build_candidate_manifest

_SHA = "a" * 40
_OTHER_SHA = "b" * 40
_REPOSITORY = "imReese/Karkinos"
_CANDIDATE_RUN_ID = 456
_CANDIDATE_RUN_ATTEMPT = 2


def _native_archive(
    tmp_path: Path, *, architecture: str, commit_sha: str = _SHA
) -> Path:
    root = tmp_path / f"Karkinos-{__version__}-macos-{architecture}"
    (root / "bin").mkdir(parents=True)
    launcher = root / "bin" / "karkinos"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    (root / "app" / "server").mkdir(parents=True)
    (root / "app" / "server" / "__init__.py").write_text(
        f'__version__ = "{__version__}"\n', encoding="utf-8"
    )
    (root / "app" / "server" / "__main__.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    (root / "app" / "server" / "app.py").write_text(
        "def create_app():\n    return None\n", encoding="utf-8"
    )
    (root / "app" / "web" / "dist").mkdir(parents=True)
    (root / "app" / "web" / "dist" / "index.html").write_text(
        "<!doctype html>\n", encoding="utf-8"
    )
    (root / "runtime" / "bin").mkdir(parents=True)
    runtime = root / "runtime" / "bin" / "python3.12"
    runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime.chmod(0o755)
    for relative_name in release_artifact.REQUIRED_RELEASE_CONTROL_FILES:
        control_file = root / relative_name
        control_file.parent.mkdir(parents=True, exist_ok=True)
        control_file.write_text(f"fixture:{relative_name}\n", encoding="utf-8")
    for relative_name in release_artifact.REQUIRED_RELEASE_CONTROL_EXECUTABLES:
        (root / relative_name).chmod(0o755)
    manifest: dict[str, object] = {
        "schema_version": release_artifact.NATIVE_ARTIFACT_SCHEMA,
        "artifact_kind": "macos-native",
        "release_control_protocol": release_artifact.RELEASE_CONTROL_PROTOCOL,
        "version": __version__,
        "commit_sha": commit_sha,
        "architecture": architecture,
        "entrypoint": "bin/karkinos",
        "runtime": "python3.12",
        "mutable_state": "~/Library/Application Support/Karkinos",
    }
    manifest["file_checksums"] = release_artifact.payload_checksums(root)
    manifest["payload_fingerprint"] = release_artifact.payload_fingerprint(root)
    (root / "release.json").write_bytes(release_artifact.canonical_json(manifest))
    archive = tmp_path / f"karkinos-{__version__}-macos-{architecture}.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(root, arcname=root.name)
    return archive


def _candidate_bundle(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    artifact_dir = tmp_path / "candidate-artifacts"
    artifact_dir.mkdir(parents=True)
    assets: dict[str, bytes] = {}
    for architecture in ("arm64", "x86_64"):
        archive = _native_archive(tmp_path / architecture, architecture=architecture)
        destination = artifact_dir / archive.name
        destination.write_bytes(archive.read_bytes())
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        checksum = f"{digest}  {destination.name}\n".encode()
        (artifact_dir / f"{destination.name}.sha256").write_bytes(checksum)
        assets[destination.name] = destination.read_bytes()
        assets[f"{destination.name}.sha256"] = checksum
    manifest = build_candidate_manifest(
        repo_root=Path("."),
        artifact_dir=artifact_dir,
        commit_sha=_SHA,
        version=__version__,
        source_ci_run_id=123,
        source_ci_run_attempt=2,
        candidate_workflow_run_id=_CANDIDATE_RUN_ID,
        candidate_workflow_run_attempt=_CANDIDATE_RUN_ATTEMPT,
        candidate_workflow_event="push",
        image_workflow_run_id=_CANDIDATE_RUN_ID,
        image_workflow_run_attempt=1,
        image_reference="ghcr.io/imreese/karkinos",
        image_digest="sha256:" + "c" * 64,
    )
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assets[manifest_path.name] = manifest_path.read_bytes()
    return manifest_path, assets


def _actions_zip(tmp_path: Path) -> bytes:
    manifest_path, _assets = _candidate_bundle(tmp_path)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.write(manifest_path, "candidate-manifest.json")
        for path in sorted((tmp_path / "candidate-artifacts").iterdir()):
            archive.write(path, f"candidate-artifacts/{path.name}")
    return payload.getvalue()


def _candidate_selection(archive_payload: bytes = b"candidate-actions") -> bytes:
    return (
        json.dumps(
            {
                "schema_version": "karkinos.candidate_artifact_selection.v1",
                "repository": _REPOSITORY,
                "commit_sha": _SHA,
                "workflow": {
                    "name": "Release Candidate",
                    "path": ".github/workflows/candidate.yml",
                    "event": "push",
                    "branch": "main",
                    "run_id": _CANDIDATE_RUN_ID,
                    "run_attempt": _CANDIDATE_RUN_ATTEMPT,
                    "completed_at": "2026-08-30T00:00:00Z",
                },
                "artifact": {
                    "id": 789,
                    "name": (
                        f"karkinos-candidate-{_SHA}-{_CANDIDATE_RUN_ID}-"
                        f"{_CANDIDATE_RUN_ATTEMPT}"
                    ),
                    "digest": (f"sha256:{hashlib.sha256(archive_payload).hexdigest()}"),
                    "size_in_bytes": len(archive_payload),
                },
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _attestation_result(
    command: list[str], **kwargs
) -> subprocess.CompletedProcess[str]:
    assert command[:3] == ["gh", "attestation", "verify"]
    assert command[command.index("--repo") + 1] == _REPOSITORY
    signer = command[command.index("--signer-workflow") + 1]
    assert signer in {
        f"{_REPOSITORY}/.github/workflows/candidate.yml",
        f"{_REPOSITORY}/.github/workflows/release.yml",
    }
    assert command[command.index("--source-digest") + 1] == _SHA
    if signer.endswith("/release.yml"):
        assert command[command.index("--source-ref") + 1] == (
            f"refs/tags/v{__version__}"
        )
    else:
        assert "--source-ref" not in command
    assert command[-3:] == ["--deny-self-hosted-runners", "--format", "json"]
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["env"]["GH_TOKEN"] == "sensitive-token"
    assert "sensitive-token" not in command
    return subprocess.CompletedProcess(
        command,
        0,
        stdout=json.dumps(
            [
                {
                    "attestation": {"bundle": "verified"},
                    "verificationResult": {"statement": "verified"},
                }
            ]
        ),
        stderr="",
    )


def _release_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[int, bytes]]:
    manifest_path, payloads = _candidate_bundle(tmp_path)
    payloads["candidate-selection.json"] = _candidate_selection()
    assets: list[dict[str, object]] = []
    downloads: dict[int, bytes] = {}
    for asset_id, (name, payload) in enumerate(sorted(payloads.items()), start=100):
        assets.append(
            {
                "id": asset_id,
                "name": name,
                "size": len(payload),
                "state": "uploaded",
                "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            }
        )
        downloads[asset_id] = payload
    assert manifest_path.name == "candidate-manifest.json"
    return (
        {
            "id": 99,
            "tag_name": f"v{__version__}",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-08-30T00:00:00Z",
            "assets": assets,
        },
        downloads,
    )


def test_fetch_candidate_selects_current_architecture_after_full_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _actions_zip(tmp_path / "source")

    def fake_fetch_candidate(**kwargs) -> Path:
        output = kwargs["output"]
        output.write_bytes(payload)
        kwargs["metadata_output"].write_bytes(_candidate_selection(payload))
        assert kwargs["commit_sha"] == _SHA
        return output

    monkeypatch.setattr(
        release_fetch.download_candidate, "fetch_candidate", fake_fetch_candidate
    )
    result = release_fetch.fetch_candidate_native(
        repository=_REPOSITORY,
        commit_sha=_SHA,
        output_dir=tmp_path / "verified",
        token="sensitive-token",
        architecture="arm64",
        attestation_runner=_attestation_result,
    )

    assert result.source == "actions-candidate"
    assert result.commit_sha == _SHA
    assert result.architecture == "arm64"
    assert result.archive.name == f"karkinos-{__version__}-macos-arm64.tar.gz"
    assert {path.name for path in result.archive.parent.iterdir()} == {
        "candidate-manifest.json",
        result.archive.name,
        result.checksum.name,
    }
    release_artifact.validate_archive(
        result.archive,
        expected_commit_sha=_SHA,
        expected_architecture="arm64",
        expected_version=__version__,
    )


def test_fetch_stable_binds_release_tag_asset_digests_and_native_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, downloads = _release_fixture(tmp_path / "source")
    installer_payload = b"#!/usr/bin/env bash\nexit 0\n"
    installer_id = 999
    release_assets = release["assets"]
    assert isinstance(release_assets, list)
    release_assets.append(
        {
            "id": installer_id,
            "name": "bootstrap_installer.sh",
            "size": len(installer_payload),
            "state": "uploaded",
            "digest": f"sha256:{hashlib.sha256(installer_payload).hexdigest()}",
        }
    )
    downloads[installer_id] = installer_payload
    requested_assets: list[int] = []

    def fake_json(path: str, **_kwargs) -> dict[str, object]:
        if "/releases/tags/" in path:
            return release
        if "/git/ref/tags/" in path:
            return {
                "ref": f"refs/tags/v{__version__}",
                "object": {"type": "commit", "sha": _SHA},
            }
        raise AssertionError(path)

    def fake_https(url: str, **kwargs) -> bytes:
        asset_id = int(url.rsplit("/", 1)[1])
        requested_assets.append(asset_id)
        payload = downloads[asset_id]
        assert kwargs["expected_size"] == len(payload)
        return payload

    monkeypatch.setattr(release_fetch, "_github_json", fake_json)
    monkeypatch.setattr(release_fetch, "_https_get", fake_https)
    attestation_commands: list[list[str]] = []

    def attest(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        attestation_commands.append(command)
        return _attestation_result(command, **kwargs)

    result = release_fetch.fetch_stable_native(
        repository=_REPOSITORY,
        tag=f"v{__version__}",
        output_dir=tmp_path / "verified",
        token="sensitive-token",
        architecture="x86_64",
        attestation_runner=attest,
    )

    assert result.source == "github-release"
    assert result.tag == f"v{__version__}"
    assert result.commit_sha == _SHA
    assert result.archive.name == f"karkinos-{__version__}-macos-x86_64.tar.gz"
    assert result.checksum.read_text(encoding="utf-8").split()[1] == (
        result.archive.name
    )
    assert [
        command[command.index("--signer-workflow") + 1]
        for command in attestation_commands
    ] == [
        f"{_REPOSITORY}/.github/workflows/release.yml",
        f"{_REPOSITORY}/.github/workflows/release.yml",
        f"{_REPOSITORY}/.github/workflows/candidate.yml",
        f"{_REPOSITORY}/.github/workflows/release.yml",
    ]
    assert Path(attestation_commands[0][3]).name == "candidate-manifest.json"
    assert Path(attestation_commands[1][3]).name == "candidate-selection.json"
    assert installer_id not in requested_assets


def test_fetch_stable_rechecks_tag_and_release_after_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, downloads = _release_fixture(tmp_path / "source")
    tag_reads = 0

    def fake_json(path: str, **_kwargs) -> dict[str, object]:
        nonlocal tag_reads
        if "/releases/tags/" in path:
            return release
        if "/git/ref/tags/" in path:
            tag_reads += 1
            return {
                "ref": f"refs/tags/v{__version__}",
                "object": {
                    "type": "commit",
                    "sha": _SHA if tag_reads == 1 else _OTHER_SHA,
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(release_fetch, "_github_json", fake_json)
    monkeypatch.setattr(
        release_fetch,
        "_https_get",
        lambda url, **_kwargs: downloads[int(url.rsplit("/", 1)[1])],
    )

    with pytest.raises(ValueError, match="release_fetch_remote_identity_changed"):
        release_fetch.fetch_stable_native(
            repository=_REPOSITORY,
            tag=f"v{__version__}",
            output_dir=tmp_path / "verified",
            token="sensitive-token",
            architecture="arm64",
            attestation_runner=_attestation_result,
        )

    assert tag_reads == 2
    assert not (tmp_path / "verified").exists()


@pytest.mark.parametrize("field", ("draft", "prerelease"))
def test_fetch_stable_rejects_draft_or_prerelease_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    release, _downloads = _release_fixture(tmp_path / field)
    release[field] = True
    monkeypatch.setattr(
        release_fetch, "_github_json", lambda *_args, **_kwargs: release
    )

    with pytest.raises(ValueError, match="release_fetch_release_invalid"):
        release_fetch.fetch_stable_native(
            repository=_REPOSITORY,
            tag=f"v{__version__}",
            output_dir=tmp_path / "verified",
            architecture="arm64",
        )


def test_fetch_stable_rejects_tag_manifest_commit_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, downloads = _release_fixture(tmp_path / "source")

    def fake_json(path: str, **_kwargs) -> dict[str, object]:
        if "/releases/tags/" in path:
            return release
        return {
            "ref": f"refs/tags/v{__version__}",
            "object": {"type": "commit", "sha": _OTHER_SHA},
        }

    monkeypatch.setattr(release_fetch, "_github_json", fake_json)
    monkeypatch.setattr(
        release_fetch,
        "_https_get",
        lambda url, **_kwargs: downloads[int(url.rsplit("/", 1)[1])],
    )

    with pytest.raises(ValueError, match="candidate_manifest_commit_sha_mismatch"):
        release_fetch.fetch_stable_native(
            repository=_REPOSITORY,
            tag=f"v{__version__}",
            output_dir=tmp_path / "verified",
            architecture="arm64",
        )


def test_fetch_stable_rejects_github_asset_digest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, downloads = _release_fixture(tmp_path / "source")
    manifest_asset = next(
        item for item in release["assets"] if item["name"] == "candidate-manifest.json"
    )
    manifest_asset["digest"] = "sha256:" + "d" * 64

    def fake_json(path: str, **_kwargs) -> dict[str, object]:
        if "/releases/tags/" in path:
            return release
        return {
            "ref": f"refs/tags/v{__version__}",
            "object": {"type": "commit", "sha": _SHA},
        }

    monkeypatch.setattr(release_fetch, "_github_json", fake_json)
    monkeypatch.setattr(
        release_fetch,
        "_https_get",
        lambda url, **_kwargs: downloads[int(url.rsplit("/", 1)[1])],
    )

    with pytest.raises(ValueError, match="release_fetch_asset_digest_mismatch"):
        release_fetch.fetch_stable_native(
            repository=_REPOSITORY,
            tag=f"v{__version__}",
            output_dir=tmp_path / "verified",
            architecture="arm64",
        )
    assert not (tmp_path / "verified").exists()


def test_fetch_stable_rejects_missing_or_ambiguous_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, _downloads = _release_fixture(tmp_path / "source")
    release["assets"].append(dict(release["assets"][0]))

    def fake_json(path: str, **_kwargs) -> dict[str, object]:
        if "/releases/tags/" in path:
            return release
        return {
            "ref": f"refs/tags/v{__version__}",
            "object": {"type": "commit", "sha": _SHA},
        }

    monkeypatch.setattr(release_fetch, "_github_json", fake_json)

    with pytest.raises(ValueError, match="release_fetch_asset_ambiguous"):
        release_fetch.fetch_stable_native(
            repository=_REPOSITORY,
            tag=f"v{__version__}",
            output_dir=tmp_path / "verified",
            architecture="arm64",
        )


def test_fetch_stable_rejects_missing_selected_checksum_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, downloads = _release_fixture(tmp_path / "source")
    missing_name = f"karkinos-{__version__}-macos-arm64.tar.gz.sha256"
    release["assets"] = [
        item for item in release["assets"] if item["name"] != missing_name
    ]

    def fake_json(path: str, **_kwargs) -> dict[str, object]:
        if "/releases/tags/" in path:
            return release
        return {
            "ref": f"refs/tags/v{__version__}",
            "object": {"type": "commit", "sha": _SHA},
        }

    monkeypatch.setattr(release_fetch, "_github_json", fake_json)
    monkeypatch.setattr(
        release_fetch,
        "_https_get",
        lambda url, **_kwargs: downloads[int(url.rsplit("/", 1)[1])],
    )

    with pytest.raises(ValueError, match="release_fetch_release_asset_set_invalid"):
        release_fetch.fetch_stable_native(
            repository=_REPOSITORY,
            tag=f"v{__version__}",
            output_dir=tmp_path / "verified",
            architecture="arm64",
        )


@pytest.mark.parametrize(
    ("result", "error"),
    (
        (
            subprocess.CompletedProcess([], 1, stdout="", stderr="private"),
            "release_attestation_verification_failed",
        ),
        (
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            "release_attestation_result_invalid",
        ),
        (
            subprocess.CompletedProcess([], 0, stdout="[]", stderr=""),
            "release_attestation_result_invalid",
        ),
        (
            subprocess.CompletedProcess([], 0, stdout="{}", stderr=""),
            "release_attestation_result_invalid",
        ),
    ),
)
def test_attestation_verification_fails_closed_without_exposing_output(
    tmp_path: Path,
    result: subprocess.CompletedProcess[str],
    error: str,
) -> None:
    archive = tmp_path / "native.tar.gz"
    archive.write_bytes(b"archive")

    with pytest.raises(ValueError, match=error) as captured:
        release_fetch.verify_github_attestation(
            archive,
            repository=_REPOSITORY,
            commit_sha=_SHA,
            token="sensitive-token",
            runner=lambda *_args, **_kwargs: result,
        )
    assert "private" not in str(captured.value)
    assert "sensitive-token" not in str(captured.value)


def test_attestation_verification_requires_gh(tmp_path: Path) -> None:
    archive = tmp_path / "native.tar.gz"
    archive.write_bytes(b"archive")

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("gh")

    with pytest.raises(ValueError, match="release_attestation_verifier_unavailable"):
        release_fetch.verify_github_attestation(
            archive,
            repository=_REPOSITORY,
            commit_sha=_SHA,
            runner=missing,
        )


def test_fetch_rejects_non_https_and_unbounded_payloads() -> None:
    with pytest.raises(ValueError, match="release_fetch_url_invalid"):
        release_fetch._https_get(
            "http://api.github.com/private",
            token="sensitive-token",
            accept="application/json",
            maximum=1,
            timeout=1,
        )

    class Response:
        headers = {"Content-Length": "2"}

        def read(self, _size: int) -> bytes:
            return b""

    with pytest.raises(ValueError, match="release_fetch_payload_too_large"):
        release_fetch._read_bounded(Response(), maximum=1, expected_size=None)


def test_fetch_network_and_auth_failures_are_bounded_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingOpener:
        def open(self, request, *, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "sensitive-token denied",
                {},
                None,
            )

    monkeypatch.setattr(
        release_fetch.download_candidate, "_SAFE_OPENER", FailingOpener()
    )
    with pytest.raises(ValueError, match="release_fetch_request_inconclusive") as error:
        release_fetch._https_get(
            "https://api.github.com/repos/imReese/Karkinos/releases/tags/v0.3.1",
            token="sensitive-token",
            accept="application/json",
            maximum=1024,
            timeout=1,
        )
    assert "sensitive-token" not in str(error.value)


def test_current_architecture_requires_supported_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_fetch.platform, "system", lambda: "Linux")
    with pytest.raises(ValueError, match="release_fetch_macos_required"):
        release_fetch.current_macos_architecture()
