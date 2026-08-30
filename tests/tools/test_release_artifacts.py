from __future__ import annotations

import hashlib
import io
import json
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools import download_candidate, release_artifact
from tools.release_candidate import build_candidate_manifest, verify_candidate_manifest

_SHA = "a" * 40
_VERSION = "0.3.1"


def _native_tree(
    root: Path, *, commit_sha: str = _SHA, architecture: str = "arm64"
) -> Path:
    root.mkdir(parents=True)
    (root / "bin").mkdir()
    launcher = root / "bin" / "karkinos"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    (root / "app" / "server").mkdir(parents=True)
    (root / "app" / "server" / "__init__.py").write_text(
        '__version__ = "0.3.1"\n', encoding="utf-8"
    )
    (root / "app" / "web" / "dist").mkdir(parents=True)
    (root / "app" / "web" / "dist" / "index.html").write_text(
        "<!doctype html>\n", encoding="utf-8"
    )
    (root / "runtime" / "bin").mkdir(parents=True)
    runtime_python = root / "runtime" / "bin" / "python3.12"
    runtime_python.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime_python.chmod(0o755)
    manifest: dict[str, object] = {
        "schema_version": release_artifact.NATIVE_ARTIFACT_SCHEMA,
        "artifact_kind": "macos-native",
        "version": _VERSION,
        "commit_sha": commit_sha,
        "architecture": architecture,
        "entrypoint": "bin/karkinos",
        "runtime": "python3.12",
        "mutable_state": "~/Library/Application Support/Karkinos",
    }
    manifest["file_checksums"] = release_artifact.payload_checksums(root)
    manifest["payload_fingerprint"] = release_artifact.payload_fingerprint(root)
    (root / "release.json").write_bytes(release_artifact.canonical_json(manifest))
    return root


def _archive(
    path: Path, root: Path, members: list[tuple[tarfile.TarInfo, bytes]] | None = None
) -> Path:
    with tarfile.open(path, "w:gz") as output:
        if members is None:
            output.add(root, arcname=root.name)
        else:
            for member, payload in members:
                output.addfile(member, io.BytesIO(payload))
    return path


def test_native_manifest_and_archive_are_bound_to_identity(tmp_path: Path) -> None:
    root = _native_tree(tmp_path / "Karkinos-0.3.1-macos-arm64")
    assert (
        release_artifact.validate_manifest(
            root,
            expected_commit_sha=_SHA,
            expected_architecture="arm64",
            expected_version=_VERSION,
        )["payload_fingerprint"]
        == json.loads((root / "release.json").read_text())["payload_fingerprint"]
    )

    archive = _archive(tmp_path / "native.tar.gz", root)
    assert (
        release_artifact.validate_archive(
            archive,
            expected_commit_sha=_SHA,
            expected_architecture="arm64",
            expected_version=_VERSION,
        )["commit_sha"]
        == _SHA
    )


@pytest.mark.parametrize(
    "member_name",
    ("Karkinos-0.3.1-macos-arm64/../escape", "/absolute"),
)
def test_native_archive_rejects_unsafe_paths(tmp_path: Path, member_name: str) -> None:
    info = tarfile.TarInfo(member_name)
    info.size = 1
    archive = _archive(
        tmp_path / "unsafe.tar.gz",
        tmp_path / "unused",
        members=[(info, b"x")],
    )
    with pytest.raises(ValueError, match="release_archive_(path_unsafe|root_invalid)"):
        release_artifact.validate_archive(archive)


def test_native_archive_rejects_symlink_and_extraction_bomb(
    tmp_path: Path, monkeypatch
) -> None:
    link = tarfile.TarInfo("Karkinos-0.3.1-macos-arm64/bin/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "/tmp/private"
    symlink_archive = _archive(
        tmp_path / "symlink.tar.gz",
        tmp_path / "unused",
        members=[(link, b"")],
    )
    with pytest.raises(ValueError, match="release_archive_member_unsupported"):
        release_artifact.validate_archive(symlink_archive)

    monkeypatch.setattr(release_artifact, "_MAX_EXTRACTED_BYTES", 1)
    bomb = tarfile.TarInfo("Karkinos-0.3.1-macos-arm64/payload")
    bomb.size = 2
    bomb_archive = _archive(
        tmp_path / "bomb.tar.gz",
        tmp_path / "unused",
        members=[(bomb, b"xx")],
    )
    with pytest.raises(ValueError, match="release_archive_extracted_size_too_large"):
        release_artifact.validate_archive(bomb_archive)


def test_candidate_zip_extract_rejects_symlink_and_traversal(tmp_path: Path) -> None:
    traversal = io.BytesIO()
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape", b"x")
    with pytest.raises(ValueError, match="candidate_artifact_path_unsafe"):
        download_candidate._safe_zip_extract(traversal.getvalue(), tmp_path / "out")

    symlink = io.BytesIO()
    with zipfile.ZipFile(symlink, "w") as archive:
        info = zipfile.ZipInfo("bundle/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/private")
    with pytest.raises(ValueError, match="candidate_artifact_symlink_unsupported"):
        download_candidate._safe_zip_extract(symlink.getvalue(), tmp_path / "symlink")


def test_candidate_manifest_round_trip_binds_artifact_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    artifact_dir = tmp_path / "candidate-artifacts"
    artifact_dir.mkdir()
    monkeypatch.setattr(
        release_artifact,
        "validate_archive",
        lambda *args, **kwargs: {},
    )
    for architecture in ("arm64", "x86_64"):
        filename = f"karkinos-{_VERSION}-macos-{architecture}.tar.gz"
        archive = artifact_dir / filename
        archive.write_bytes(f"{architecture}\n".encode())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (artifact_dir / f"{filename}.sha256").write_text(
            f"{digest}  {filename}\n", encoding="utf-8"
        )

    manifest = build_candidate_manifest(
        repo_root=Path("."),
        artifact_dir=artifact_dir,
        commit_sha=_SHA,
        version=_VERSION,
        source_ci_run_id=123,
        source_ci_run_attempt=2,
        image_reference="ghcr.io/imreese/karkinos",
        image_digest="sha256:" + "b" * 64,
    )
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    verified = verify_candidate_manifest(
        manifest_path,
        artifact_dir=artifact_dir,
        expected_commit_sha=_SHA,
        expected_version=_VERSION,
        expected_source_ci_run_id=123,
        expected_source_ci_run_attempt=2,
        expected_image_reference="ghcr.io/imreese/karkinos",
        repo_root=Path("."),
    )
    assert verified["image"]["digest"] == "sha256:" + "b" * 64
