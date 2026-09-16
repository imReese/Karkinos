"""共享启动配置的优先级、快照隔离和失败原子性。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from server.runtime_environment import (
    load_runtime_environment,
    load_runtime_environment_file,
)


def test_snapshot_is_immutable_and_process_values_win(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("KARKINOS_TDX_DATA_SERVICE_KEY=file-value\nKARKINOS_PORT=8000\n")
    incoming = {"KARKINOS_TDX_DATA_SERVICE_KEY": "process-value"}
    before = dict(os.environ)
    snapshot = load_runtime_environment(path, environ=incoming)
    assert snapshot.values["KARKINOS_TDX_DATA_SERVICE_KEY"] == "process-value"
    assert snapshot.values["KARKINOS_PORT"] == "8000"
    assert snapshot.file_loaded
    assert snapshot.env_file == path.resolve()
    assert incoming == {"KARKINOS_TDX_DATA_SERVICE_KEY": "process-value"}
    assert dict(os.environ) == before
    incoming["KARKINOS_TDX_DATA_SERVICE_KEY"] = "later-change"
    assert snapshot.values["KARKINOS_TDX_DATA_SERVICE_KEY"] == "process-value"
    assert "process-value" not in repr(snapshot)
    with pytest.raises(TypeError):
        snapshot.values["KARKINOS_PORT"] = "9999"  # type: ignore[index]


def test_path_precedence_is_explicit_then_environment_then_default(
    tmp_path: Path,
) -> None:
    paths = [tmp_path / name for name in ("explicit.env", "selected.env", ".env")]
    for index, path in enumerate(paths):
        path.write_text(f"VALUE={index}\n")
    values = {"KARKINOS_ENV_FILE": str(paths[1])}
    assert load_runtime_environment(paths[0], environ=values).values["VALUE"] == "0"
    assert load_runtime_environment(environ=values).values["VALUE"] == "1"
    assert (
        load_runtime_environment(environ={}, default_path=paths[2]).values["VALUE"]
        == "2"
    )


def test_optional_missing_file_is_allowed_but_selected_missing_file_is_not(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing.env"
    snapshot = load_runtime_environment(environ={}, default_path=path)
    assert not snapshot.file_loaded
    for kwargs in (
        {"explicit_path": path},
        {"environ": {"KARKINOS_ENV_FILE": str(path)}},
    ):
        with pytest.raises(ValueError, match="does not exist"):
            load_runtime_environment(**kwargs)


def test_invalid_file_does_not_partially_modify_environment(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("EARLY=private-config-value\nMISSING_VALUE\n")
    values = {"EXISTING": "unchanged"}
    with pytest.raises(ValueError) as caught:
        load_runtime_environment_file(path, environ=values)
    assert "private-config-value" not in str(caught.value)
    assert values == {"EXISTING": "unchanged"}


def test_empty_optional_credentials_keep_existing_bootstrap_semantics(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env"
    path.write_text("KARKINOS_TDX_DATA_SERVICE_KEY=file-value\nKARKINOS_PORT=9000\n")
    snapshot = load_runtime_environment(
        path, environ={"KARKINOS_TDX_DATA_SERVICE_KEY": "  ", "KARKINOS_PORT": ""}
    )
    assert snapshot.values["KARKINOS_TDX_DATA_SERVICE_KEY"] == "file-value"
    assert snapshot.values["KARKINOS_PORT"] == ""


def test_loading_again_does_not_reuse_a_global_cached_key(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("KARKINOS_TDX_DATA_SERVICE_KEY=first\n")
    first = load_runtime_environment(path, environ={})
    path.write_text("KARKINOS_TDX_DATA_SERVICE_KEY=second\n")
    second = load_runtime_environment(path, environ={})
    assert first.values["KARKINOS_TDX_DATA_SERVICE_KEY"] == "first"
    assert second.values["KARKINOS_TDX_DATA_SERVICE_KEY"] == "second"
