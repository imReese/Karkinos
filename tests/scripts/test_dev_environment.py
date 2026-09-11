"""Development startup must stay isolated from the user workspace."""

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


def test_default_workspace_is_repo_local_and_empty(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "config.json").write_text('{"private": "do not copy"}')
    (root / ".env").write_text("KARKINOS_TUSHARE_TOKEN=private\n")

    env = prepare_environment(root, _environment(tmp_path))
    workspace = root / ".run/dev"

    assert env["KARKINOS_DEV_WORKSPACE"] == str(workspace)
    assert env["KARKINOS_WORKSPACE"] == str(workspace)
    assert env["KARKINOS_HOME"] == str(workspace)
    assert env["KARKINOS_DATA_DIR"] == str(workspace / "data")
    assert json.loads(Path(env["KARKINOS_CONFIG_PATH"]).read_text()) == {}
    assert "private" not in Path(env["KARKINOS_ENV_FILE"]).read_text()
    assert list((workspace / "data").iterdir()) == []
    assert (workspace / DEV_MARKER).stat().st_mode & 0o777 == 0o600


def test_repeated_start_preserves_development_state(tmp_path):
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


def test_inherited_user_state_and_credentials_are_removed(tmp_path):
    user_workspace = tmp_path / "user-workspace"
    env = {
        **_environment(tmp_path),
        "KARKINOS_WORKSPACE": str(user_workspace),
        "KARKINOS_HOME": str(user_workspace),
        "KARKINOS_CONFIG_PATH": str(user_workspace / "config.json"),
        "KARKINOS_DATA_DIR": str(user_workspace / "data/store"),
        "KARKINOS_ENV_FILE": str(user_workspace / ".env"),
        "KARKINOS_TUSHARE_TOKEN": "private",
        "KARKINOS_RELEASE_OTHER": "private",
        "KARKINOS_DEV_BACKEND_PORT": "9001",
        "KARKINOS_FRONTEND_PORT": "5174",
        "KARKINOS_LOG_MAX_BYTES": "100",
        "VIRTUAL_ENV": str(user_workspace / ".venv"),
        "PYTHONPATH": str(user_workspace),
    }
    root = tmp_path / "checkout"

    actual = prepare_environment(root, env)

    assert actual["KARKINOS_WORKSPACE"] == str(root / ".run/dev")
    assert actual["UV_PROJECT_ENVIRONMENT"] == str(root / ".venv")
    for key in (
        "KARKINOS_TUSHARE_TOKEN",
        "KARKINOS_RELEASE_OTHER",
        "VIRTUAL_ENV",
        "PYTHONPATH",
    ):
        assert key not in actual
    assert actual["KARKINOS_DEV_BACKEND_PORT"] == "9001"
    assert actual["KARKINOS_FRONTEND_PORT"] == "5174"
    assert actual["KARKINOS_LOG_MAX_BYTES"] == "100"


@pytest.mark.parametrize("value", ["", "relative/workspace"])
def test_explicit_development_workspace_must_be_absolute(tmp_path, value):
    with pytest.raises(ValueError, match="absolute path"):
        prepare_environment(
            tmp_path / "checkout",
            {**_environment(tmp_path), "KARKINOS_DEV_WORKSPACE": value},
        )


def test_legacy_dev_home_must_agree_with_workspace(tmp_path):
    with pytest.raises(ValueError, match="disagree"):
        prepare_environment(
            tmp_path / "checkout",
            {
                **_environment(tmp_path),
                "KARKINOS_DEV_WORKSPACE": str(tmp_path / "dev-a"),
                "KARKINOS_DEV_HOME": str(tmp_path / "dev-b"),
            },
        )


def test_development_workspace_cannot_overlap_durable_user_data(tmp_path):
    user_workspace = tmp_path / "user"
    with pytest.raises(ValueError, match="overlaps"):
        prepare_environment(
            tmp_path / "checkout",
            {
                **_environment(tmp_path),
                "KARKINOS_WORKSPACE": str(user_workspace),
                "KARKINOS_DEV_WORKSPACE": str(user_workspace / "data/store/dev"),
            },
        )


def test_unmarked_nonempty_workspace_is_not_adopted(tmp_path):
    workspace = tmp_path / "dev"
    workspace.mkdir()
    private = workspace / "private.db"
    private.write_bytes(b"private fixture")

    with pytest.raises(ValueError, match="neither an initialized"):
        prepare_environment(
            tmp_path / "checkout",
            {
                **_environment(tmp_path),
                "KARKINOS_DEV_WORKSPACE": str(workspace),
            },
        )
    assert private.read_bytes() == b"private fixture"


def test_existing_development_workspace_cannot_link_external_files(tmp_path):
    root = tmp_path / "checkout"
    env = _environment(tmp_path)
    initial = prepare_environment(root, env)
    destination = Path(initial["KARKINOS_WORKSPACE"]) / "config/config.json"
    destination.unlink()
    external = tmp_path / "external"
    external.write_bytes(b"private fixture")
    destination.symlink_to(external)

    with pytest.raises(ValueError, match="linked path"):
        prepare_environment(root, env)


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
    assert not (root / ".run/dev").exists()


def test_cli_exec_preserves_argument_boundaries_and_sets_workspace(tmp_path):
    root = tmp_path / "checkout with spaces"
    output = tmp_path / "result.json"
    code = (
        "import json, os, pathlib, sys; "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({"
        "'workspace': os.environ['KARKINOS_WORKSPACE'], 'args': sys.argv[2:]}))"
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
        "workspace": str(root / ".run/dev"),
        "args": ["literal $(echo secret); argument"],
    }
