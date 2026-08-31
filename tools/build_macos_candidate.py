#!/usr/bin/env python3
"""Build a self-contained, provider-neutral macOS candidate archive.

The archive contains the Karkinos application, a uv-managed Python 3.12
runtime, and locked production packages. It intentionally contains no config,
credentials, database, logs, or account evidence. The launcher keeps all
mutable state under Application Support.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

_RELEASE_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?$"
)
_FORBIDDEN_SOURCE_NAMES = {
    ".env",
    "config.json",
    "broker_statement.csv",
    "secret.py",
    "app.db",
    "runtime.sqlite",
}
_FORBIDDEN_SOURCE_PREFIXES = (
    "data/store/",
    "config/",
    "logs/",
    "exports/",
    "screenshots/",
    "reports/",
)

REPOSITORY_DIRS = (
    "account_truth",
    "analytics",
    "backtest",
    "core",
    "data",
    "domain",
    "execution",
    "notification",
    "risk",
    "server",
    "strategy",
)

RELEASE_CONTROL_DIRECTORIES = ("scripts/release",)

RELEASE_CONTROL_FILES = (
    "scripts/service/manage_launch_agent.sh",
    "tools/__init__.py",
    "tools/download_candidate.py",
    "tools/release_artifact.py",
    "tools/release_candidate.py",
    "tools/release_fetch.py",
)

MANAGED_PYTHON_VERSION = "3.12.13"
MANAGED_PYTHON_MINOR = MANAGED_PYTHON_VERSION.rsplit(".", maxsplit=1)[0]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name == "__pycache__"
        or name.endswith((".pyc", ".pyo"))
        or name == ".DS_Store"
    }


def _copy_tree_without_symlinks(source: Path, destination: Path) -> None:
    """Copy a tree while rejecting links instead of following them."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"release_source_tree_invalid:{source}")
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ValueError(f"release_destination_tree_invalid:{destination}")
    destination.mkdir(parents=True, exist_ok=True)
    with os.scandir(source) as entries:
        for entry in entries:
            source_path = Path(entry.path)
            destination_path = destination / entry.name
            if entry.is_symlink():
                raise ValueError(f"release_source_symlink_unsupported:{source_path}")
            if entry.name in _FORBIDDEN_SOURCE_NAMES:
                raise ValueError(f"release_private_source_forbidden:{source_path}")
            if entry.is_dir(follow_symlinks=False):
                _copy_tree_without_symlinks(source_path, destination_path)
            elif entry.is_file(follow_symlinks=False):
                shutil.copy2(source_path, destination_path)
            else:
                raise ValueError(f"release_source_file_unsupported:{source_path}")


def _copy_tracked_file(repo_root: Path, relative_file: str, destination: Path) -> None:
    """Copy one Git-tracked file without following a source link."""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative_file],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() != relative_file:
        raise ValueError(f"release_source_file_not_tracked:{relative_file}")
    source = repo_root / relative_file
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"release_source_file_invalid:{relative_file}")
    target = destination / relative_file
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tracked_directory(
    repo_root: Path, relative_directory: str, destination: Path
) -> None:
    """Copy only Git-tracked source files into the immutable application tree."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", relative_directory],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    paths = [Path(value) for value in result.stdout.decode().split("\0") if value]
    if not paths:
        raise ValueError(f"release_source_directory_missing:{relative_directory}")
    for relative_path in paths:
        relative_name = relative_path.as_posix()
        if relative_path.name in _FORBIDDEN_SOURCE_NAMES or any(
            relative_name.startswith(prefix) for prefix in _FORBIDDEN_SOURCE_PREFIXES
        ):
            raise ValueError(f"release_private_source_forbidden:{relative_path}")
        source = repo_root / relative_path
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"release_source_file_invalid:{relative_path}")
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _copy_release_control_plane(repo_root: Path, destination: Path) -> None:
    """Copy the Git-tracked updater and service-control implementation."""
    for directory in RELEASE_CONTROL_DIRECTORIES:
        _copy_tracked_directory(repo_root, directory, destination)
    for relative_file in RELEASE_CONTROL_FILES:
        _copy_tracked_file(repo_root, relative_file, destination)


def _git_worktree_clean(repo_root: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    # Ignored frontend output and dependency/runtime caches do not appear in
    # this listing. Any tracked change or untracked source/private file does.
    if result.stdout:
        raise ValueError("release_source_worktree_not_clean")


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    commit_sha = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise ValueError("release_source_commit_invalid")
    return commit_sha


def _run(command: list[str], *, cwd: Path, stdout: int | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=stdout is None,
        text=True,
    )
    return result.stdout if stdout is None else ""


def _install_managed_python(repo_root: Path, managed_runtime: Path) -> Path:
    """Install the exact release runtime and return its immutable root."""
    _run(
        [
            "uv",
            "python",
            "install",
            MANAGED_PYTHON_VERSION,
            "--install-dir",
            str(managed_runtime),
        ],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
    )
    runtime_candidates = sorted(
        path.parent.parent
        for path in managed_runtime.rglob(f"python{MANAGED_PYTHON_MINOR}")
        if path.is_file() and path.parent.name == "bin"
    )
    if len(runtime_candidates) != 1:
        raise ValueError("macos_runtime_install_invalid")
    return runtime_candidates[0]


def _verify_managed_python(repo_root: Path, runtime_python: Path) -> None:
    """Fail closed if the copied interpreter does not match the pinned patch."""
    observed_version = _run(
        [
            str(runtime_python),
            "-I",
            "-c",
            "import platform; print(platform.python_version())",
        ],
        cwd=repo_root,
    ).strip()
    if observed_version != MANAGED_PYTHON_VERSION:
        raise ValueError("macos_runtime_python_version_mismatch")


def _install_locked_production_packages(
    *,
    repo_root: Path,
    runtime_python: Path,
    site_packages: Path,
    requirements: Path,
) -> None:
    """Export the frozen production graph and require every artifact hash."""
    requirements.write_text(
        _run(
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
            cwd=repo_root,
        ),
        encoding="utf-8",
    )
    _run(
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
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
    )


def _version(repo_root: Path) -> str:
    namespace: dict[str, object] = {}
    source = repo_root / "server/__init__.py"
    if source.is_symlink() or not source.is_file():
        raise ValueError("server_version_source_invalid")
    exec(source.read_text(encoding="utf-8"), namespace)
    version = namespace.get("__version__")
    if not isinstance(version, str) or _RELEASE_VERSION.fullmatch(version) is None:
        raise ValueError("server_version_invalid")
    return version


def _architecture(value: str | None) -> str:
    normalized = value or os.uname().machine
    aliases = {
        "aarch64": "arm64",
        "arm64": "arm64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("macos_architecture_unsupported") from exc


def _write_launcher(path: Path) -> None:
    path.write_text(
        """#!/bin/sh
set -eu

RELEASE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
if [ ! -f "$RELEASE_ROOT/release.json" ]; then
    echo "Karkinos release manifest is missing." >&2
    exit 78
fi
KARKINOS_HOME=${KARKINOS_HOME:-"$HOME/Library/Application Support/Karkinos"}
export KARKINOS_HOME
export KARKINOS_RELEASE_ROOT="$RELEASE_ROOT"
export KARKINOS_STATIC_DIR="$RELEASE_ROOT/app/web/dist"
KARKINOS_RELEASE_SHA=$(grep -Eo '"commit_sha":"[0-9a-f]+"' "$RELEASE_ROOT/release.json" | cut -d '"' -f 4)
KARKINOS_ARTIFACT_FINGERPRINT=$(grep -Eo '"payload_fingerprint":"[0-9a-f]+"' "$RELEASE_ROOT/release.json" | cut -d '"' -f 4)
if ! printf '%s' "$KARKINOS_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$' ||
    ! printf '%s' "$KARKINOS_ARTIFACT_FINGERPRINT" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "Karkinos release manifest identity is invalid." >&2
    exit 78
fi
export KARKINOS_RELEASE_SHA KARKINOS_ARTIFACT_FINGERPRINT
export KARKINOS_DATA_DIR=${KARKINOS_DATA_DIR:-"$KARKINOS_HOME/data"}
export KARKINOS_CONFIG_PATH=${KARKINOS_CONFIG_PATH:-"$KARKINOS_HOME/config/config.json"}
if [ -n "${KARKINOS_ENV_FILE:-}" ]; then
    KARKINOS_ENV_FILE_IS_DEFAULT=0
else
    KARKINOS_ENV_FILE="$KARKINOS_HOME/config/.env"
    KARKINOS_ENV_FILE_IS_DEFAULT=1
fi
export KARKINOS_ENV_FILE
export KARKINOS_HOST=${KARKINOS_HOST:-127.0.0.1}
export KARKINOS_PORT=${KARKINOS_PORT:-8000}
unset PYTHONHOME
export PYTHONPATH="$RELEASE_ROOT/app:$RELEASE_ROOT/lib/python3.12/site-packages"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1

PYTHON="$RELEASE_ROOT/runtime/bin/python3.12"
if [ ! -f "$PYTHON" ] || [ ! -x "$PYTHON" ] || [ -L "$PYTHON" ]; then
    echo "Karkinos release runtime is missing Python 3.12." >&2
    exit 78
fi
if ! "$PYTHON" -B -s -P -c 'import os; from pathlib import Path; from tools.release_artifact import validate_manifest; validate_manifest(Path(os.environ["KARKINOS_RELEASE_ROOT"]), expected_commit_sha=os.environ["KARKINOS_RELEASE_SHA"])'; then
    echo "Karkinos release payload integrity validation failed." >&2
    exit 78
fi

mkdir -p "$KARKINOS_DATA_DIR" "$KARKINOS_HOME/config" "$KARKINOS_HOME/logs"
if [ ! -f "$KARKINOS_CONFIG_PATH" ]; then
    printf '{}\\n' > "$KARKINOS_CONFIG_PATH"
    chmod 600 "$KARKINOS_CONFIG_PATH"
fi
if [ "$KARKINOS_ENV_FILE_IS_DEFAULT" -eq 1 ]; then
    if [ -L "$KARKINOS_ENV_FILE" ] || { [ -e "$KARKINOS_ENV_FILE" ] && [ ! -f "$KARKINOS_ENV_FILE" ]; }; then
        echo "Karkinos default environment file path is invalid." >&2
        exit 78
    fi
    if [ ! -e "$KARKINOS_ENV_FILE" ]; then
        (umask 077 && : > "$KARKINOS_ENV_FILE")
    fi
fi

cd "$RELEASE_ROOT/app"
exec "$PYTHON" -B -s -P -m server "$@"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_control_launcher(path: Path, *, commit_sha: str) -> None:
    """Write the package-local release controller entrypoint."""
    if re.fullmatch(r"[0-9a-f]{40}", commit_sha) is None:
        raise ValueError("release_commit_sha_invalid")
    path.write_text(
        f"""#!/bin/sh
set -eu

RELEASE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
EXPECTED_RELEASE_SHA={commit_sha}
if [ ! -f "$RELEASE_ROOT/release.json" ]; then
    echo "Karkinos release manifest is missing." >&2
    exit 78
fi
KARKINOS_RELEASE_SHA=$(grep -Eo '"commit_sha":"[0-9a-f]+"' "$RELEASE_ROOT/release.json" | cut -d '"' -f 4 || true)
KARKINOS_ARTIFACT_FINGERPRINT=$(grep -Eo '"payload_fingerprint":"[0-9a-f]+"' "$RELEASE_ROOT/release.json" | cut -d '"' -f 4 || true)
if [ "$KARKINOS_RELEASE_SHA" != "$EXPECTED_RELEASE_SHA" ] ||
    ! printf '%s' "$KARKINOS_RELEASE_SHA" | grep -Eq '^[0-9a-f]{{40}}$' ||
    ! printf '%s' "$KARKINOS_ARTIFACT_FINGERPRINT" | grep -Eq '^[0-9a-f]{{64}}$'; then
    echo "Karkinos release manifest identity is invalid." >&2
    exit 78
fi

KARKINOS_HOME=${{KARKINOS_HOME:-"$HOME/Library/Application Support/Karkinos"}}
export KARKINOS_HOME
export KARKINOS_RELEASE_ROOT="$RELEASE_ROOT"
export KARKINOS_RELEASE_SHA KARKINOS_ARTIFACT_FINGERPRINT
unset PYTHONHOME
export PYTHONPATH="$RELEASE_ROOT/app:$RELEASE_ROOT/lib/python3.12/site-packages"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1

PYTHON="$RELEASE_ROOT/runtime/bin/python3.12"
if [ ! -f "$PYTHON" ] || [ ! -x "$PYTHON" ] || [ -L "$PYTHON" ]; then
    echo "Karkinos release runtime is missing Python 3.12." >&2
    exit 78
fi
if ! "$PYTHON" -B -s -P -c 'import os; from pathlib import Path; from tools.release_artifact import validate_manifest; validate_manifest(Path(os.environ["KARKINOS_RELEASE_ROOT"]), expected_commit_sha=os.environ["KARKINOS_RELEASE_SHA"])'; then
    echo "Karkinos release payload integrity validation failed." >&2
    exit 78
fi

cd "$RELEASE_ROOT/app"
exec "$PYTHON" -B -s -P "$RELEASE_ROOT/app/scripts/release/manage_release.py" "$@"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        yield path


def _flatten_copy(source: Path, destination: Path) -> None:
    """Copy a managed Python runtime after checking link targets stay inside it."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError("macos_runtime_directory_invalid")
    source_root = source.resolve()
    for path in source.rglob("*"):
        if not path.is_symlink():
            continue
        target = path.resolve()
        if source_root not in target.parents and target != source_root:
            raise ValueError("macos_runtime_symlink_escape")
    shutil.copytree(source, destination, symlinks=False)


def _deterministic_tar(source: Path, output: Path) -> None:
    with output.open("wb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
            ) as archive:
                for path in _iter_files(source):
                    relative = path.relative_to(source).as_posix()
                    info = archive.gettarinfo(
                        str(path), arcname=f"{source.name}/{relative}"
                    )
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    if info.isreg():
                        with path.open("rb") as payload:
                            archive.addfile(info, payload)
                    else:
                        archive.addfile(info)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_candidate(
    *,
    repo_root: Path,
    output: Path,
    commit_sha: str,
    version: str | None,
    architecture: str,
) -> tuple[Path, Path]:
    if re.fullmatch(r"[0-9a-f]{40}", commit_sha) is None:
        raise ValueError("release_commit_sha_invalid")
    _git_worktree_clean(repo_root)
    if _git_head(repo_root) != commit_sha:
        raise ValueError("release_source_commit_mismatch")
    version = version or _version(repo_root)
    if _RELEASE_VERSION.fullmatch(version) is None:
        raise ValueError("release_version_invalid")

    from tools.release_artifact import (
        NATIVE_ARTIFACT_SCHEMA,
        RELEASE_CONTROL_PROTOCOL,
        canonical_json,
        payload_checksums,
        payload_fingerprint,
    )

    if architecture != _architecture(None):
        raise ValueError("macos_architecture_runner_mismatch")
    if output.exists() or output.is_symlink():
        raise ValueError("release_output_already_exists")
    output = output.absolute()
    for ancestor in (output.parent, *output.parent.parents):
        if ancestor.is_symlink():
            raise ValueError("release_output_parent_symlink_unsupported")
        if ancestor.parent == ancestor:
            break
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="karkinos-native-") as temporary:
        staging = Path(temporary) / f"Karkinos-{version}-macos-{architecture}"
        app = staging / "app"
        for directory in REPOSITORY_DIRS:
            _copy_tracked_directory(repo_root, directory, app)
        _copy_release_control_plane(repo_root, app)
        pyproject = repo_root / "pyproject.toml"
        if pyproject.is_symlink() or not pyproject.is_file():
            raise ValueError("release_pyproject_invalid")
        shutil.copy2(pyproject, app / "pyproject.toml")
        _copy_tree_without_symlinks(repo_root / "web" / "dist", app / "web" / "dist")

        managed_runtime = Path(temporary) / "managed-python"
        runtime_source = _install_managed_python(repo_root, managed_runtime)
        _flatten_copy(runtime_source, staging / "runtime")
        runtime_python = staging / "runtime" / "bin" / "python3.12"
        if not runtime_python.is_file():
            raise ValueError("macos_runtime_python_missing")
        _verify_managed_python(repo_root, runtime_python)

        site_packages = staging / "lib" / "python3.12" / "site-packages"
        site_packages.mkdir(parents=True)
        requirements = Path(temporary) / "requirements.txt"
        _install_locked_production_packages(
            repo_root=repo_root,
            runtime_python=runtime_python,
            site_packages=site_packages,
            requirements=requirements,
        )

        launcher = staging / "bin" / "karkinos"
        launcher.parent.mkdir()
        _write_launcher(launcher)
        _write_control_launcher(staging / "bin" / "karkinosctl", commit_sha=commit_sha)
        manifest = {
            "schema_version": NATIVE_ARTIFACT_SCHEMA,
            "artifact_kind": "macos-native",
            "release_control_protocol": RELEASE_CONTROL_PROTOCOL,
            "version": version,
            "commit_sha": commit_sha,
            "architecture": architecture,
            "entrypoint": "bin/karkinos",
            "runtime": "python3.12",
            "mutable_state": "~/Library/Application Support/Karkinos",
            "file_checksums": payload_checksums(staging),
            "payload_fingerprint": payload_fingerprint(staging),
        }
        manifest_path = staging / "release.json"
        manifest_path.write_bytes(canonical_json(manifest))
        from tools.release_artifact import validate_manifest

        validate_manifest(
            staging,
            expected_commit_sha=commit_sha,
            expected_architecture=architecture,
            expected_version=version,
        )
        _deterministic_tar(staging, output)

    checksum = _sha256(output)
    checksum_path = output.with_name(output.name + ".sha256")
    checksum_path.write_text(f"{checksum}  {output.name}\n", encoding="utf-8")
    return output, checksum_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--version")
    parser.add_argument("--architecture")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        archive, checksum = build_candidate(
            repo_root=_repo_root(),
            output=args.output,
            commit_sha=args.commit_sha,
            version=args.version,
            architecture=_architecture(args.architecture),
        )
    except (
        OSError,
        UnicodeError,
        subprocess.CalledProcessError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Built {archive}")
    print(f"SHA256 {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
