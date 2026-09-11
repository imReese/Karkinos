"""Prepare an explicitly isolated workspace for source development."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

DEV_MARKER = ".karkinos-dev-workspace"
DEV_MARKER_CONTENT = "karkinos.dev-workspace.v1\n"
MANAGED_MARKERS = (
    "current",
    ".service-config.json",
    ".release.lock",
    ".release-transaction.json",
    ".legacy-bootstrap-transaction.json",
    ".source-runtime.lock",
)
PRESERVED_OPTIONS = {
    "KARKINOS_LOG_MAX_BYTES",
    "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS",
    "KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS",
}


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _require_private_tree(workspace: Path) -> None:
    if not workspace.exists():
        return
    for directory, directories, files in os.walk(workspace, followlinks=False):
        for name in [*directories, *files]:
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or (
                stat.S_ISREG(info.st_mode) and info.st_nlink != 1
            ):
                raise ValueError(
                    f"development workspace contains a linked path: {path}"
                )
            if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
                raise ValueError(
                    f"development workspace contains a special file: {path}"
                )


def _durable_user_paths(environ: Mapping[str, str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    configured_workspace = environ.get("KARKINOS_WORKSPACE") or environ.get(
        "KARKINOS_HOME"
    )
    if configured_workspace:
        root = Path(configured_workspace).expanduser().resolve()
        paths.extend((root / "config", root / "data", root / "logs", root / "exports"))
    for name in ("KARKINOS_DATA_DIR", "KARKINOS_CONFIG_PATH", "KARKINOS_ENV_FILE"):
        if value := environ.get(name):
            paths.append(Path(value).expanduser().resolve())
    return tuple(paths)


def _require_separate_workspace(workspace: Path, environ: Mapping[str, str]) -> None:
    for path in _durable_user_paths(environ):
        if _overlaps(workspace, path):
            raise ValueError(
                "KARKINOS_DEV_WORKSPACE overlaps durable user data; "
                "choose a separate empty development directory"
            )
    if any(os.path.lexists(workspace / marker) for marker in MANAGED_MARKERS):
        raise ValueError(
            f"development workspace belongs to a managed runtime: {workspace}"
        )


def _require_env_file_args(arguments: Sequence[str], env_file: Path) -> None:
    for index, argument in enumerate(arguments):
        option = argument.partition("=")[0]
        if (
            option.startswith("--")
            and len(option) > 2
            and option != "--env-file"
            and "--env-file".startswith(option)
        ):
            raise ValueError("spell --env-file in full for development startup")
        if argument == "--env-file":
            if index + 1 == len(arguments):
                raise ValueError("--env-file requires a value")
            value = arguments[index + 1]
        elif argument.startswith("--env-file="):
            value = argument.partition("=")[2]
        else:
            continue
        if not value or Path(value).expanduser().resolve() != env_file:
            raise ValueError(
                "development --env-file must select "
                f"{env_file}; configure this dedicated development file"
            )


def prepare_environment(
    root: Path,
    environ: Mapping[str, str],
    arguments: Sequence[str] = (),
) -> dict[str, str]:
    root = root.resolve()
    configured_workspace = environ.get("KARKINOS_DEV_WORKSPACE")
    legacy_dev_home = environ.get("KARKINOS_DEV_HOME")
    if configured_workspace and legacy_dev_home:
        if (
            Path(configured_workspace).expanduser().resolve()
            != Path(legacy_dev_home).expanduser().resolve()
        ):
            raise ValueError(
                "KARKINOS_DEV_WORKSPACE and legacy KARKINOS_DEV_HOME disagree"
            )
    selected = configured_workspace or legacy_dev_home
    if selected is not None and (
        not selected or not Path(selected).expanduser().is_absolute()
    ):
        raise ValueError("KARKINOS_DEV_WORKSPACE must be a nonempty absolute path")
    selected_workspace = Path(selected).expanduser() if selected else root / ".run/dev"
    if selected_workspace.is_symlink():
        raise ValueError("KARKINOS_DEV_WORKSPACE must not be a symlink")
    workspace = selected_workspace.resolve()
    _require_separate_workspace(workspace, environ)
    _require_private_tree(workspace)
    env_file = workspace / "config/.env"
    _require_env_file_args(arguments, env_file)
    marker = workspace / DEV_MARKER
    if marker.exists():
        if marker.read_text(encoding="utf-8") != DEV_MARKER_CONTENT:
            raise ValueError("development workspace ownership marker is invalid")
    elif workspace.exists() and any(workspace.iterdir()):
        raise ValueError(
            "KARKINOS_DEV_WORKSPACE is neither an initialized development "
            "workspace nor an empty directory"
        )
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("config", "data", "logs", "run"):
        (workspace / name).mkdir(mode=0o700, exist_ok=True)
    for path, content in (
        (workspace / "config/config.json", "{}\n"),
        (
            env_file,
            "# Dedicated development settings; user workspace files are not used.\n",
        ),
        (marker, DEV_MARKER_CONTENT),
    ):
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
    result = {
        name: value
        for name, value in environ.items()
        if (
            not name.startswith("KARKINOS_")
            or name.startswith(
                ("KARKINOS_DEV_", "KARKINOS_FRONTEND_", "KARKINOS_TEST_")
            )
            or name in PRESERVED_OPTIONS
        )
        and name
        not in {
            "MODE",
            "BASH_ENV",
            "ENV",
            "VIRTUAL_ENV",
            "PYTHONPATH",
            "PYTHONHOME",
            "UV_ENV_FILE",
            "UV_CONFIG_FILE",
        }
    }
    result.update(
        {
            "KARKINOS_DEV_WORKSPACE": str(workspace),
            "KARKINOS_DEV_HOME": str(workspace),
            "KARKINOS_WORKSPACE": str(workspace),
            # Compatibility for code paths not yet renamed from HOME to WORKSPACE.
            "KARKINOS_HOME": str(workspace),
            "KARKINOS_DATA_DIR": str(workspace / "data"),
            "KARKINOS_CONFIG_PATH": str(workspace / "config/config.json"),
            "KARKINOS_ENV_FILE": str(env_file),
            "KARKINOS_STATIC_DIR": str(root / "web/dist"),
            "KARKINOS_RELEASE_ROOT": str(root),
            "KARKINOS_RELEASE_SHA": "",
            "KARKINOS_ARTIFACT_FINGERPRINT": "",
            "UV_PROJECT_ENVIRONMENT": str(root / ".venv"),
            "UV_PROJECT": str(root),
            "UV_WORKING_DIR": str(root),
            "UV_NO_ENV_FILE": "1",
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a development command is required after --")
    try:
        env = prepare_environment(args.repo, os.environ, command)
        print(f"Development workspace: {env['KARKINOS_DEV_WORKSPACE']}", flush=True)
        os.execvpe(command[0], command, env)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
