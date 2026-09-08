"""Development startup must never inherit the daily account or build environment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.service.dev_environment import DEV_MARKER, prepare_environment


def _environment(tmp_path: Path) -> dict[str, str]:
    return {"HOME": str(tmp_path / "user-home"), "PATH": os.environ["PATH"]}


def test_default_account_is_empty_and_does_not_copy_checkout_files(tmp_path):
    root = tmp_path / "dev-checkout"
    root.mkdir()
    (root / "config.json").write_text('{"private": "do not copy"}')
    (root / ".env").write_text("KARKINOS_TUSHARE_TOKEN=private\n")
    env = prepare_environment(root, _environment(tmp_path))
    home = root / ".run/dev-home"
    assert env["KARKINOS_HOME"] == str(home)
    assert env["KARKINOS_DATA_DIR"] == str(home / "data")
    assert json.loads(Path(env["KARKINOS_CONFIG_PATH"]).read_text()) == {}
    assert "private" not in Path(env["KARKINOS_ENV_FILE"]).read_text()
    assert list((home / "data").iterdir()) == []
    assert (home / DEV_MARKER).stat().st_mode & 0o777 == 0o600


def test_repeated_start_keeps_existing_development_config_and_database(tmp_path):
    root = tmp_path / "checkout"
    initial = prepare_environment(root, _environment(tmp_path))
    config = Path(initial["KARKINOS_CONFIG_PATH"])
    config.write_text('{"server":{"port":9001}}')
    database = Path(initial["KARKINOS_DATA_DIR"]) / "app.db"
    database.write_bytes(b"development fixture")
    repeated = prepare_environment(root, _environment(tmp_path))
    assert repeated == initial
    assert config.read_text() == '{"server":{"port":9001}}'
    assert database.read_bytes() == b"development fixture"


def test_inherited_production_paths_credentials_and_python_environment_are_removed(
    tmp_path,
):
    env = {
        **_environment(tmp_path),
        "KARKINOS_HOME": str(tmp_path / "production"),
        "KARKINOS_CONFIG_PATH": str(tmp_path / "production/config/config.json"),
        "KARKINOS_DATA_DIR": str(tmp_path / "production/data"),
        "KARKINOS_ENV_FILE": str(tmp_path / "production/config/.env"),
        "KARKINOS_RELEASE_SHA": "a" * 40,
        "KARKINOS_RELEASE_OTHER": "private",
        "KARKINOS_TUSHARE_TOKEN": "private",
        "KARKINOS_DEV_BACKEND_PORT": "9001",
        "KARKINOS_FRONTEND_PORT": "5174",
        "KARKINOS_LOG_MAX_BYTES": "100",
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "production/.venv"),
        "VIRTUAL_ENV": str(tmp_path / "production/.venv"),
        "PYTHONPATH": str(tmp_path / "production"),
        "PYTHONHOME": str(tmp_path / "production/python"),
        "MODE": "dev",
        "BASH_ENV": str(tmp_path / "production/shell-init"),
        "ENV": str(tmp_path / "production/shell-init"),
        "UV_WORKING_DIR": str(tmp_path / "production"),
        "UV_ENV_FILE": str(tmp_path / "production/config/.env"),
        "UV_CONFIG_FILE": str(tmp_path / "production/uv.toml"),
    }
    root = tmp_path / "checkout"
    actual = prepare_environment(root, env)
    assert actual["KARKINOS_HOME"] == str(root / ".run/dev-home")
    assert actual["UV_PROJECT_ENVIRONMENT"] == str(root / ".venv")
    assert actual["UV_WORKING_DIR"] == str(root)
    assert actual["UV_NO_ENV_FILE"] == "1"
    assert actual["KARKINOS_RELEASE_SHA"] == ""
    for key in (
        "KARKINOS_RELEASE_OTHER",
        "KARKINOS_TUSHARE_TOKEN",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "PYTHONHOME",
        "MODE",
        "BASH_ENV",
        "ENV",
        "UV_ENV_FILE",
        "UV_CONFIG_FILE",
    ):
        assert key not in actual
    for key in (
        "KARKINOS_DEV_BACKEND_PORT",
        "KARKINOS_FRONTEND_PORT",
        "KARKINOS_LOG_MAX_BYTES",
    ):
        assert actual[key] == env[key]


@pytest.mark.parametrize("home", ["", "relative/home"])
def test_explicit_development_home_requires_absolute_path(tmp_path, home):
    with pytest.raises(ValueError, match="absolute path"):
        prepare_environment(
            tmp_path / "checkout",
            {**_environment(tmp_path), "KARKINOS_DEV_HOME": home},
        )


@pytest.mark.parametrize("location", ["same", "child", "parent", "default"])
def test_rejects_production_path_overlap_before_creating_anything(tmp_path, location):
    env = _environment(tmp_path)
    production = tmp_path / "production"
    home = {
        "same": production,
        "child": production / "development",
        "parent": tmp_path,
        "default": Path(env["HOME"]) / "Library/Application Support/Karkinos",
    }[location]
    env.update(KARKINOS_HOME=str(production), KARKINOS_DEV_HOME=str(home))
    with pytest.raises(ValueError, match="overlaps"):
        prepare_environment(tmp_path / "checkout", env)
    assert not (home / DEV_MARKER).exists()


@pytest.mark.parametrize(
    "key", ["KARKINOS_DATA_DIR", "KARKINOS_CONFIG_PATH", "KARKINOS_ENV_FILE"]
)
def test_rejects_external_daily_paths_inside_requested_development_home(tmp_path, key):
    home = tmp_path / "dev"
    with pytest.raises(ValueError, match="overlaps"):
        prepare_environment(
            tmp_path / "checkout",
            {
                **_environment(tmp_path),
                "KARKINOS_DEV_HOME": str(home),
                key: str(home / "private"),
            },
        )
    assert not home.exists()


def test_symlink_alias_of_default_daily_home_is_rejected(tmp_path):
    env = _environment(tmp_path)
    production = Path(env["HOME"]) / "Library/Application Support/Karkinos"
    production.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(production, target_is_directory=True)
    with pytest.raises(ValueError, match="overlaps"):
        prepare_environment(
            tmp_path / "checkout",
            {**env, "KARKINOS_DEV_HOME": str(alias / "dev")},
        )
    assert list(production.iterdir()) == []


@pytest.mark.parametrize(
    "marker",
    [
        "current",
        ".release.lock",
        ".service-config.json",
        ".release-transaction.json",
        ".source-runtime.lock",
    ],
)
def test_unknown_managed_home_is_rejected_by_markers(tmp_path, marker):
    managed = tmp_path / "unknown-managed-home"
    managed.mkdir()
    (managed / marker).write_text("marker")
    with pytest.raises(ValueError, match="managed home"):
        prepare_environment(
            tmp_path / "checkout",
            {**_environment(tmp_path), "KARKINOS_DEV_HOME": str(managed / "dev")},
        )
    assert not (managed / "dev").exists()


def test_unmarked_nonempty_home_is_not_silently_adopted(tmp_path):
    home = tmp_path / "existing-account"
    (home / "data").mkdir(parents=True)
    database = home / "data/app.db"
    database.write_bytes(b"private fixture")
    with pytest.raises(ValueError, match="no existing account was opened"):
        prepare_environment(
            tmp_path / "checkout",
            {**_environment(tmp_path), "KARKINOS_DEV_HOME": str(home)},
        )
    assert database.read_bytes() == b"private fixture"


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
@pytest.mark.parametrize(
    "relative",
    ["config/.env", "config/config.json", "data/app.db", "data/nested/meta.db"],
)
def test_existing_development_home_cannot_link_external_files(tmp_path, link, relative):
    root = tmp_path / "checkout"
    env = _environment(tmp_path)
    initial = prepare_environment(root, env)
    destination = Path(initial["KARKINOS_HOME"]) / relative
    destination.parent.mkdir(exist_ok=True)
    destination.unlink(missing_ok=True)
    external = tmp_path / "external"
    external.write_bytes(b"private fixture")
    if link == "symlink":
        destination.symlink_to(external)
    else:
        os.link(external, destination)
    with pytest.raises(ValueError, match="linked path"):
        prepare_environment(root, env)
    assert external.read_bytes() == b"private fixture"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--env-file", "/unrelated/.env"],
        ["--env-file=/unrelated/.env"],
        ["--env-file"],
        ["--env-file="],
    ],
)
def test_cli_cannot_select_another_environment_file(tmp_path, arguments):
    root = tmp_path / "checkout"
    with pytest.raises(ValueError, match="--env-file"):
        prepare_environment(root, _environment(tmp_path), arguments)
    assert not (root / ".run/dev-home").exists()


def test_repeated_env_file_arguments_are_all_validated(tmp_path):
    root = tmp_path / "checkout"
    dedicated = root / ".run/dev-home/config/.env"
    with pytest.raises(ValueError, match="--env-file"):
        prepare_environment(
            root,
            _environment(tmp_path),
            ["--env-file=/unrelated/.env", "--env-file", str(dedicated)],
        )


@pytest.mark.parametrize("option", ["--e", "--env", "--env-f", "--env-fil"])
@pytest.mark.parametrize("equals", [True, False])
def test_server_argparse_environment_file_abbreviations_cannot_bypass_guard(
    tmp_path, option, equals
):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file")
    arguments = [f"{option}=/private/.env"] if equals else [option, "/private/.env"]
    assert parser.parse_args(arguments).env_file == "/private/.env"
    root = tmp_path / "checkout"
    with pytest.raises(ValueError, match="spell --env-file in full"):
        prepare_environment(root, _environment(tmp_path), arguments)
    assert not (root / ".run/dev-home").exists()


def test_dedicated_dotenv_cannot_override_paths_or_release_identity(tmp_path):
    from server.bootstrap import load_runtime_environment_file

    root = tmp_path / "checkout"
    env = prepare_environment(root, _environment(tmp_path))
    dotenv = Path(env["KARKINOS_ENV_FILE"])
    dotenv.write_text(
        "\n".join(
            f"{name}=/daily/private"
            for name in (
                "KARKINOS_HOME",
                "KARKINOS_DATA_DIR",
                "KARKINOS_CONFIG_PATH",
                "KARKINOS_ENV_FILE",
                "KARKINOS_STATIC_DIR",
                "KARKINOS_RELEASE_ROOT",
                "KARKINOS_RELEASE_SHA",
                "KARKINOS_ARTIFACT_FINGERPRINT",
            )
        )
        + "\nKARKINOS_TUSHARE_TOKEN=development-fixture\n"
    )
    actual = dict(env)
    assert load_runtime_environment_file(dotenv, environ=actual, required=True)
    assert all(actual[key] == value for key, value in env.items())
    assert actual["KARKINOS_TUSHARE_TOKEN"] == "development-fixture"


def test_cli_exec_preserves_argument_boundaries_and_sets_environment(tmp_path):
    root = tmp_path / "checkout with spaces"
    output = tmp_path / "result.json"
    code = (
        "import json, os, pathlib, sys; "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({"
        "'home': os.environ['KARKINOS_HOME'], 'args': sys.argv[2:]}))"
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/service/dev_environment.py",
            "--repo",
            str(root),
            "--",
            sys.executable,
            "-c",
            code,
            str(output),
            "literal $(echo secret); argument",
        ],
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text()) == {
        "home": str(root / ".run/dev-home"),
        "args": ["literal $(echo secret); argument"],
    }
