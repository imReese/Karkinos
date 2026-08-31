from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools import (
    build_macos_candidate,
    download_candidate,
    promote_candidate_image,
    release_artifact,
)
from tools.build_macos_candidate import (
    RELEASE_CONTROL_DIRECTORIES,
    RELEASE_CONTROL_FILES,
    _copy_release_control_plane,
    _write_control_launcher,
    _write_launcher,
)
from tools.release_candidate import (
    build_candidate_manifest,
    verify_candidate_image_metadata,
    verify_candidate_manifest,
)

_SHA = "a" * 40
_VERSION = "0.3.2"


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
        '__version__ = "0.3.2"\n', encoding="utf-8"
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
    runtime_python = root / "runtime" / "bin" / "python3.12"
    runtime_python.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime_python.chmod(0o755)
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


def _generated_launcher_tree(root: Path) -> Path:
    release = _native_tree(root)
    for relative_directory in RELEASE_CONTROL_DIRECTORIES:
        for source in Path(relative_directory).rglob("*"):
            if not source.is_file() or "__pycache__" in source.parts:
                continue
            destination = release / "app" / source
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for relative_file in RELEASE_CONTROL_FILES:
        destination = release / "app" / relative_file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(relative_file, destination)
    (release / "app" / "server" / "__main__.py").write_text(
        """from __future__ import annotations

import json
import os
import sys
from pathlib import Path

env_file = Path(os.environ["KARKINOS_ENV_FILE"])
if not env_file.is_file():
    raise SystemExit(78)
Path(os.environ["KARKINOS_TEST_CAPTURE_PATH"]).write_text(
    json.dumps(
        {
            "artifact_fingerprint": os.environ["KARKINOS_ARTIFACT_FINGERPRINT"],
            "config_path": os.environ["KARKINOS_CONFIG_PATH"],
            "data_dir": os.environ["KARKINOS_DATA_DIR"],
            "dont_write_bytecode": sys.dont_write_bytecode,
            "env_file": str(env_file),
            "no_user_site": sys.flags.no_user_site,
            "python_path": os.environ["PYTHONPATH"],
            "release_root": os.environ["KARKINOS_RELEASE_ROOT"],
            "release_sha": os.environ["KARKINOS_RELEASE_SHA"],
            "safe_path": sys.flags.safe_path,
            "static_dir": os.environ["KARKINOS_STATIC_DIR"],
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    runtime_python = release / "runtime" / "bin" / "python3.12"
    runtime_python.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8"
    )
    runtime_python.chmod(0o755)
    _write_launcher(release / "bin" / "karkinos")
    _write_control_launcher(release / "bin" / "karkinosctl", commit_sha=_SHA)
    manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
    manifest["file_checksums"] = release_artifact.payload_checksums(release)
    manifest["payload_fingerprint"] = release_artifact.payload_fingerprint(release)
    (release / "release.json").write_bytes(release_artifact.canonical_json(manifest))
    return release


def _launcher_environment(tmp_path: Path, capture: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KARKINOS_")
    }
    environment.update(
        {
            "HOME": str(tmp_path / "operator home"),
            "KARKINOS_TEST_CAPTURE_PATH": str(capture),
            # Prove that the generated launcher enforces the immutable setting.
            "PYTHONDONTWRITEBYTECODE": "0",
        }
    )
    return environment


def test_release_control_plane_copies_all_and_only_git_tracked_sources(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    tracked = [
        Path("scripts/release/manage_release.py"),
        Path("scripts/release/bootstrap_legacy.py"),
        Path("scripts/release/update_workflow.py"),
        *(Path(value) for value in RELEASE_CONTROL_FILES),
    ]
    for relative in tracked:
        source = repository / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"packaged:{relative.as_posix()}\n", encoding="utf-8")
    (repository / "scripts/release/scratch.py").write_text(
        "untracked\n", encoding="utf-8"
    )
    (repository / "scripts/release/.env").write_text(
        "PRIVATE=not-packaged\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "add", "--", *(relative.as_posix() for relative in tracked)],
        cwd=repository,
        check=True,
    )

    destination = tmp_path / "app"
    _copy_release_control_plane(repository, destination)

    assert {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    } == {relative.as_posix() for relative in tracked}


def test_candidate_runtime_install_is_exact_and_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repository"
    managed_runtime = tmp_path / "managed-python"
    runtime_root = managed_runtime / "cpython-3.12.13-macos-aarch64-none"
    runtime_python = runtime_root / "bin" / "python3.12"
    commands: list[tuple[list[str], Path, int | None]] = []

    def fake_run(command: list[str], *, cwd: Path, stdout: int | None = None) -> str:
        commands.append((command, cwd, stdout))
        if command[:3] == ["uv", "python", "install"]:
            runtime_python.parent.mkdir(parents=True)
            runtime_python.write_text("fixture\n", encoding="utf-8")
            return ""
        return "3.12.13\n"

    monkeypatch.setattr(build_macos_candidate, "_run", fake_run)

    assert (
        build_macos_candidate._install_managed_python(repo_root, managed_runtime)
        == runtime_root
    )
    build_macos_candidate._verify_managed_python(repo_root, runtime_python)

    assert commands == [
        (
            [
                "uv",
                "python",
                "install",
                "3.12.13",
                "--install-dir",
                str(managed_runtime),
            ],
            repo_root,
            subprocess.DEVNULL,
        ),
        (
            [
                str(runtime_python),
                "-I",
                "-c",
                "import platform; print(platform.python_version())",
            ],
            repo_root,
            None,
        ),
    ]


def test_candidate_runtime_verification_fails_closed_on_patch_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_python = tmp_path / "runtime" / "bin" / "python3.12"
    monkeypatch.setattr(
        build_macos_candidate,
        "_run",
        lambda *args, **kwargs: "3.12.14\n",
    )

    with pytest.raises(ValueError, match="macos_runtime_python_version_mismatch"):
        build_macos_candidate._verify_managed_python(tmp_path, runtime_python)


def test_candidate_production_install_uses_locked_hash_enforced_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repository"
    runtime_python = tmp_path / "runtime" / "bin" / "python3.12"
    site_packages = tmp_path / "lib" / "python3.12" / "site-packages"
    requirements = tmp_path / "requirements.txt"
    commands: list[tuple[list[str], Path, int | None]] = []

    def fake_run(command: list[str], *, cwd: Path, stdout: int | None = None) -> str:
        commands.append((command, cwd, stdout))
        if command[:2] == ["uv", "export"]:
            return "example==1.0 --hash=sha256:abc\n"
        return ""

    monkeypatch.setattr(build_macos_candidate, "_run", fake_run)

    build_macos_candidate._install_locked_production_packages(
        repo_root=repo_root,
        runtime_python=runtime_python,
        site_packages=site_packages,
        requirements=requirements,
    )

    assert requirements.read_text(encoding="utf-8") == (
        "example==1.0 --hash=sha256:abc\n"
    )
    assert commands == [
        (
            [
                "uv",
                "export",
                "--frozen",
                "--extra",
                "server",
                "--no-dev",
                "--no-emit-project",
                "--format",
                "requirements.txt",
            ],
            repo_root,
            None,
        ),
        (
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(runtime_python),
                "--target",
                str(site_packages),
                "--require-hashes",
                "--requirement",
                str(requirements),
                "--link-mode",
                "copy",
            ],
            repo_root,
            subprocess.DEVNULL,
        ),
    ]


def test_candidate_production_install_propagates_hash_verification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_command: list[str] = []

    def fake_run(command: list[str], *, cwd: Path, stdout: int | None = None) -> str:
        del cwd, stdout
        if command[:2] == ["uv", "export"]:
            return "example==1.0 --hash=sha256:abc\n"
        install_command.extend(command)
        raise subprocess.CalledProcessError(1, command, stderr="hash mismatch")

    monkeypatch.setattr(build_macos_candidate, "_run", fake_run)

    with pytest.raises(subprocess.CalledProcessError, match="returned non-zero"):
        build_macos_candidate._install_locked_production_packages(
            repo_root=tmp_path,
            runtime_python=tmp_path / "runtime" / "bin" / "python3.12",
            site_packages=tmp_path / "site-packages",
            requirements=tmp_path / "requirements.txt",
        )

    assert "--require-hashes" in install_command


def test_native_manifest_and_archive_are_bound_to_identity(tmp_path: Path) -> None:
    root = _native_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
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


def test_native_manifest_rejects_a_newer_release_control_protocol(
    tmp_path: Path,
) -> None:
    root = _native_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    manifest_path = root / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release_control_protocol"] = release_artifact.RELEASE_CONTROL_PROTOCOL + 1
    manifest_path.write_bytes(release_artifact.canonical_json(manifest))

    with pytest.raises(
        ValueError, match="release_manifest_control_protocol_unsupported"
    ):
        release_artifact.validate_manifest(root)


@pytest.mark.parametrize("relative_name", release_artifact.REQUIRED_RUNTIME_FILES)
def test_native_manifest_rejects_missing_required_runtime_file(
    tmp_path: Path, relative_name: str
) -> None:
    root = _native_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    (root / relative_name).unlink()

    with pytest.raises(ValueError, match="release_manifest_payload_incomplete"):
        release_artifact.validate_manifest(root)


@pytest.mark.parametrize(
    "relative_name", release_artifact.REQUIRED_RELEASE_CONTROL_FILES
)
def test_native_manifest_rejects_missing_release_control_file(
    tmp_path: Path, relative_name: str
) -> None:
    root = _native_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    (root / relative_name).unlink()

    with pytest.raises(ValueError, match="release_manifest_control_plane_incomplete"):
        release_artifact.validate_manifest(root)


@pytest.mark.parametrize(
    "relative_name", release_artifact.REQUIRED_RELEASE_CONTROL_EXECUTABLES
)
def test_native_manifest_rejects_non_executable_release_control(
    tmp_path: Path, relative_name: str
) -> None:
    root = _native_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    (root / relative_name).chmod(0o644)

    with pytest.raises(
        ValueError, match="release_manifest_control_plane_not_executable"
    ):
        release_artifact.validate_manifest(root)


def test_native_manifest_rejects_non_executable_managed_runtime(
    tmp_path: Path,
) -> None:
    root = _native_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    (root / "runtime" / "bin" / "python3.12").chmod(0o644)

    with pytest.raises(ValueError, match="release_manifest_runtime_not_executable"):
        release_artifact.validate_manifest(root)


def test_generated_launcher_runs_without_mutating_release_payload(
    tmp_path: Path,
) -> None:
    release = _generated_launcher_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
    capture = tmp_path / "launcher-capture.json"
    environment = _launcher_environment(tmp_path, capture)
    environment["PYTHONHOME"] = str(tmp_path / "invalid-python-home")
    environment["PYTHONPATH"] = str(tmp_path / "source-fallback")

    result = subprocess.run(
        [str(release / "bin" / "karkinos")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    runtime_home = Path(environment["HOME"]) / "Library/Application Support/Karkinos"
    default_env = runtime_home / "config" / ".env"
    assert default_env.read_bytes() == b""
    assert stat.S_IMODE(default_env.stat().st_mode) == 0o600
    assert (runtime_home / "config" / "config.json").read_text(encoding="utf-8") == (
        "{}\n"
    )
    observed = json.loads(capture.read_text(encoding="utf-8"))
    assert observed == {
        "artifact_fingerprint": manifest["payload_fingerprint"],
        "config_path": str(runtime_home / "config" / "config.json"),
        "data_dir": str(runtime_home / "data"),
        "dont_write_bytecode": True,
        "env_file": str(default_env),
        "no_user_site": 1,
        "python_path": f"{release / 'app'}:{release / 'lib/python3.12/site-packages'}",
        "release_root": str(release),
        "release_sha": _SHA,
        "safe_path": True,
        "static_dir": str(release / "app" / "web" / "dist"),
    }
    assert list(release.rglob("*.pyc")) == []
    release_artifact.validate_manifest(release, expected_commit_sha=_SHA)


def test_generated_launcher_validates_payload_before_creating_mutable_state(
    tmp_path: Path,
) -> None:
    release = _generated_launcher_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    (release / "app" / "server" / "__init__.py").write_text(
        '__version__ = "tampered"\n', encoding="utf-8"
    )
    environment = _launcher_environment(tmp_path, tmp_path / "unused.json")
    runtime_home = Path(environment["HOME"]) / "Library/Application Support/Karkinos"

    result = subprocess.run(
        [str(release / "bin" / "karkinos")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 78
    assert "payload integrity validation failed" in result.stderr
    assert not runtime_home.exists()


def test_generated_launcher_does_not_create_an_explicit_missing_env_file(
    tmp_path: Path,
) -> None:
    release = _generated_launcher_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    capture = tmp_path / "explicit-env-capture.json"
    environment = _launcher_environment(tmp_path, capture)
    explicit_env = tmp_path / "operator-selected" / ".env"
    environment["KARKINOS_ENV_FILE"] = str(explicit_env)

    result = subprocess.run(
        [str(release / "bin" / "karkinos")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 78
    assert not explicit_env.exists()
    assert not capture.exists()
    assert list(release.rglob("*.pyc")) == []
    release_artifact.validate_manifest(release, expected_commit_sha=_SHA)


def test_generated_control_launcher_uses_only_the_immutable_package(
    tmp_path: Path,
) -> None:
    release = _generated_launcher_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    environment = _launcher_environment(tmp_path, tmp_path / "unused.json")
    source_fallback = tmp_path / "source-fallback"
    (source_fallback / "tools").mkdir(parents=True)
    (source_fallback / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (source_fallback / "tools" / "release_artifact.py").write_text(
        'raise RuntimeError("source fallback used")\n', encoding="utf-8"
    )
    environment["PYTHONPATH"] = str(source_fallback)
    environment["PYTHONHOME"] = str(tmp_path / "invalid-python-home")

    result = subprocess.run(
        [str(release / "bin" / "karkinosctl"), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: manage_release.py" in result.stdout
    runtime_home = Path(environment["HOME"]) / "Library/Application Support/Karkinos"
    assert not runtime_home.exists()

    status_result = subprocess.run(
        [str(release / "bin" / "karkinosctl"), "status"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status_result.returncode == 0, status_result.stderr
    assert json.loads(status_result.stdout)["home"] == str(runtime_home)
    assert runtime_home.is_dir()
    assert list(release.rglob("*.pyc")) == []
    release_artifact.validate_manifest(release, expected_commit_sha=_SHA)


@pytest.mark.parametrize("tamper", ("commit", "fingerprint"))
def test_generated_control_launcher_fails_closed_on_manifest_tampering(
    tmp_path: Path, tamper: str
) -> None:
    release = _generated_launcher_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    manifest_path = release / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tamper == "commit":
        manifest["commit_sha"] = "b" * 40
    else:
        manifest["payload_fingerprint"] = "c" * 64
    manifest_path.write_bytes(release_artifact.canonical_json(manifest))
    environment = _launcher_environment(tmp_path, tmp_path / "unused.json")

    result = subprocess.run(
        [str(release / "bin" / "karkinosctl"), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 78
    assert "manifest" in result.stderr.lower()
    assert not (
        Path(environment["HOME"]) / "Library/Application Support/Karkinos"
    ).exists()
    assert list(release.rglob("*.pyc")) == []


def test_generated_control_launcher_fails_closed_when_manifest_is_missing(
    tmp_path: Path,
) -> None:
    release = _generated_launcher_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    (release / "release.json").unlink()
    environment = _launcher_environment(tmp_path, tmp_path / "unused.json")

    result = subprocess.run(
        [str(release / "bin" / "karkinosctl"), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 78
    assert "manifest is missing" in result.stderr.lower()
    assert not (
        Path(environment["HOME"]) / "Library/Application Support/Karkinos"
    ).exists()
    assert list(release.rglob("*.pyc")) == []


def test_generated_release_inventory_contains_control_plane_without_private_state(
    tmp_path: Path,
) -> None:
    release = _generated_launcher_tree(tmp_path / "Karkinos-0.3.2-macos-arm64")
    manifest = release_artifact.validate_manifest(release, expected_commit_sha=_SHA)
    inventory = set(manifest["file_checksums"])

    assert set(release_artifact.REQUIRED_RELEASE_CONTROL_FILES) <= inventory
    for relative_file in RELEASE_CONTROL_FILES:
        assert f"app/{relative_file}" in inventory
    assert not (
        {"data", "config", "logs", "exports", "screenshots", "reports"}
        & {path.parts[0] for path in map(Path, inventory)}
    )
    assert not (
        {".env", "config.json", "broker_statement.csv", "app.db", "runtime.sqlite"}
        & {path.name for path in map(Path, inventory)}
    )


@pytest.mark.parametrize(
    "member_name",
    ("Karkinos-0.3.2-macos-arm64/../escape", "/absolute"),
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
    link = tarfile.TarInfo("Karkinos-0.3.2-macos-arm64/bin/link")
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
    bomb = tarfile.TarInfo("Karkinos-0.3.2-macos-arm64/payload")
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
        candidate_workflow_run_id=456,
        candidate_workflow_run_attempt=3,
        candidate_workflow_event="push",
        image_workflow_run_id=456,
        image_workflow_run_attempt=2,
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
        expected_candidate_workflow_run_id=456,
        expected_candidate_workflow_run_attempt=3,
        expected_candidate_workflow_event="push",
        expected_image_reference="ghcr.io/imreese/karkinos",
        repo_root=Path("."),
    )
    assert verified["image"]["digest"] == "sha256:" + "b" * 64
    assert verified["image"]["candidate_tag"].endswith("run-456-attempt-2")
    assert verified["toolchain"] == {
        "python": "3.12.13",
        "node": "24.20.0",
        "uv": "0.11.28",
    }

    with pytest.raises(
        ValueError, match="candidate_manifest_workflow_attempt_mismatch"
    ):
        verify_candidate_manifest(
            manifest_path,
            artifact_dir=artifact_dir,
            expected_commit_sha=_SHA,
            expected_candidate_workflow_run_id=456,
            expected_candidate_workflow_run_attempt=4,
        )


def _candidate_image_metadata(reference: str, digest: str) -> dict[str, object]:
    images: dict[str, object] = {}
    for architecture in ("amd64", "arm64"):
        images[f"linux/{architecture}"] = {
            "architecture": architecture,
            "os": "linux",
            "config": {
                "Labels": {
                    "org.opencontainers.image.version": _VERSION,
                    "org.opencontainers.image.revision": _SHA,
                }
            },
        }
    return {
        "name": reference,
        "manifest": {"digest": digest},
        "image": images,
    }


def test_candidate_image_metadata_binds_both_runtime_platforms(
    tmp_path: Path,
) -> None:
    digest = "sha256:" + "b" * 64
    reference = f"ghcr.io/imreese/karkinos:candidate-sha-{_SHA}-run-456-attempt-2"
    metadata_path = tmp_path / "candidate-image-metadata.json"
    metadata_path.write_text(
        json.dumps(_candidate_image_metadata(reference, digest)), encoding="utf-8"
    )

    verified = verify_candidate_image_metadata(
        metadata_path,
        image_reference=reference,
        image_digest=digest,
        commit_sha=_SHA,
        version=_VERSION,
    )

    assert verified["platforms"] == ["linux/amd64", "linux/arm64"]
    assert verified["digest"] == digest


def test_candidate_image_metadata_fails_closed_on_remote_identity_mismatch(
    tmp_path: Path,
) -> None:
    digest = "sha256:" + "b" * 64
    reference = f"ghcr.io/imreese/karkinos:candidate-sha-{_SHA}-run-456-attempt-2"
    metadata = _candidate_image_metadata(reference, digest)
    metadata_path = tmp_path / "candidate-image-metadata.json"

    metadata["manifest"] = {"digest": "sha256:" + "c" * 64}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_image_digest_mismatch"):
        verify_candidate_image_metadata(
            metadata_path,
            image_reference=reference,
            image_digest=digest,
            commit_sha=_SHA,
            version=_VERSION,
        )

    metadata = _candidate_image_metadata(reference, digest)
    images = metadata["image"]
    assert isinstance(images, dict)
    images.pop("linux/arm64")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_image_platforms_invalid"):
        verify_candidate_image_metadata(
            metadata_path,
            image_reference=reference,
            image_digest=digest,
            commit_sha=_SHA,
            version=_VERSION,
        )

    metadata = _candidate_image_metadata(reference, digest)
    images = metadata["image"]
    assert isinstance(images, dict)
    arm64 = images["linux/arm64"]
    assert isinstance(arm64, dict)
    config = arm64["config"]
    assert isinstance(config, dict)
    labels = config["Labels"]
    assert isinstance(labels, dict)
    labels["org.opencontainers.image.revision"] = "d" * 40
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_image_labels_mismatch"):
        verify_candidate_image_metadata(
            metadata_path,
            image_reference=reference,
            image_digest=digest,
            commit_sha=_SHA,
            version=_VERSION,
        )


def test_candidate_image_promotion_requires_run_and_attempt_identity(
    monkeypatch,
) -> None:
    digest = "sha256:" + "b" * 64
    candidate = f"ghcr.io/imreese/karkinos:candidate-sha-{_SHA}-run-456-attempt-2"
    created: list[tuple[str, str]] = []
    monkeypatch.setattr(promote_candidate_image, "_inspect", lambda _reference: digest)
    monkeypatch.setattr(
        promote_candidate_image,
        "_create",
        lambda source, target: created.append((source, target)),
    )

    promote_candidate_image.promote(
        candidate_reference=candidate,
        expected_digest=digest,
        targets=["ghcr.io/imreese/karkinos:v1.2.3"],
    )
    assert created == [
        (
            f"{candidate}@{digest}",
            "ghcr.io/imreese/karkinos:v1.2.3",
        )
    ]

    with pytest.raises(ValueError, match="candidate_image_reference_invalid"):
        promote_candidate_image.promote(
            candidate_reference=f"ghcr.io/imreese/karkinos:candidate-sha-{_SHA}",
            expected_digest=digest,
            targets=["ghcr.io/imreese/karkinos:v1.2.3"],
        )
