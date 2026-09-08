"""Local identities for prepared main source checkouts and their supervisor."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path

SCHEMA = 1
RUNTIME_BINDINGS = (
    "KARKINOS_HOME",
    "KARKINOS_DATA_DIR",
    "KARKINOS_CONFIG_PATH",
    "KARKINOS_ENV_FILE",
    "KARKINOS_MAIN_PORT",
)


def source_directory(home: Path) -> Path:
    return home / "source"


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    entry = path.lstat()
    if (
        not stat.S_ISDIR(entry.st_mode)
        or entry.st_uid != os.getuid()
        or entry.st_mode & 0o022
    ):
        raise ValueError(f"unsafe source directory: {path}")


def read_record(path: Path) -> dict:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "r") as stream:
        entry = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(entry.st_mode)
            or entry.st_uid != os.getuid()
            or entry.st_nlink != 1
            or entry.st_mode & 0o022
        ):
            raise ValueError(f"unsafe source record: {path}")
        record = json.load(stream)
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ValueError(f"unsupported source record: {path}")
    return record


def write_record(path: Path, record: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
    )
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump({**record, "schema": SCHEMA}, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def revision(record: dict) -> str:
    sha = record.get("sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid prepared source SHA")
    return sha


def git(root: Path, *args: str) -> str:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    return subprocess.run(
        ["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def build_identity(root: Path) -> str:
    digest = hashlib.sha256()
    for directory in (root / ".venv", root / ".venv/bin", root / "web"):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(
                f"prepared build directory is missing or redirected: {directory}"
            )
    static = root / "web/dist"
    if not (static / "index.html").is_file() or static.is_symlink():
        raise ValueError("prepared frontend build is missing")
    names = ["pyproject.toml", "uv.lock", "web/package-lock.json", ".venv/pyvenv.cfg"]
    names.extend(
        str(path.relative_to(root))
        for path in sorted(static.rglob("*"))
        if not path.is_dir() or path.is_symlink()
    )
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing prepared source file: {path}")
        digest.update(name.encode() + b"\0" + path.read_bytes())
    if not (root / ".venv/bin/python").is_file():
        raise ValueError("prepared Python environment is missing")
    digest.update(str((root / ".venv/bin/python").resolve()).encode())
    return digest.hexdigest()


def check_checkout(root: Path, home: Path, sha: str) -> None:
    expected = source_directory(home) / "checkouts" / sha
    if root != expected or root.resolve() != expected:
        raise ValueError("prepared source checkout is outside its managed directory")
    if git(root, "rev-parse", "HEAD") != sha:
        raise ValueError("prepared source SHA changed")
    if git(root, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD":
        raise ValueError("prepared source must have a detached HEAD")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("prepared source checkout was modified")
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    if common != source_directory(home) / "repository.git":
        raise ValueError("prepared checkout belongs to a different Git repository")


def check_prepared(root: Path, home: Path) -> str:
    record = read_record(source_directory(home) / "prepared" / f"{root.name}.json")
    sha = revision(record)
    check_checkout(root, home, sha)
    if record.get("build_identity") != build_identity(root):
        raise ValueError("prepared source build changed; prepare a fresh checkout")
    return sha


def selected_checkout(home: Path) -> Path:
    selected = read_record(source_directory(home) / "selected.json")
    root = source_directory(home) / "checkouts" / revision(selected)
    check_prepared(root, home)
    return root


@contextlib.contextmanager
def running_record(home: Path, root: Path, sha: str, port: int, env: dict[str, str]):
    path = source_directory(home) / "run" / "running.json"
    record = {
        "sha": sha,
        "root": str(root),
        "port": port,
        "pid": os.getpid(),
        "token": uuid.uuid4().hex,
        "phase": "starting",
        "bindings": {
            name: str(port) if name == "KARKINOS_MAIN_PORT" else env[name]
            for name in RUNTIME_BINDINGS
        },
    }
    write_record(path, record)

    def ready():
        write_record(path, {**record, "phase": "ready"})

    try:
        yield ready
    finally:
        path.unlink(missing_ok=True)
