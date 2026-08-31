from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from server import state_preflight

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _runtime_environment(tmp_path: Path) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("KARKINOS_")
    }
    python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{PROJECT_ROOT}{os.pathsep}{python_path}" if python_path else str(PROJECT_ROOT)
    )
    environment["KARKINOS_CONFIG_PATH"] = str(tmp_path / "config.json")
    environment["KARKINOS_DATA_DIR"] = str(tmp_path / "data")
    return environment


def _run_server(
    tmp_path: Path,
    *arguments: str,
    inspect_imports: bool = False,
) -> subprocess.CompletedProcess[str]:
    if inspect_imports:
        program = """
import json
import sys

from server.__main__ import main

sys.argv = ["python -m server", *sys.argv[1:]]
main()
forbidden = sorted(
    name
    for name in sys.modules
    if name == "uvicorn"
    or name.startswith("uvicorn.")
    or name == "server.app"
    or name.startswith("data.providers.")
    or name.startswith("server.ai_runtime.provider")
)
print("FORBIDDEN_IMPORTS=" + json.dumps(forbidden))
"""
        command = [sys.executable, "-c", program, *arguments]
    else:
        command = [sys.executable, "-m", "server", *arguments]
    return subprocess.run(
        command,
        cwd=tmp_path,
        env=_runtime_environment(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_initializes_only_app_database_then_data_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Path]] = []

    class FakeAppDatabase:
        def __init__(self, path: Path) -> None:
            calls.append(("app-construct", path))

        def init_sync(self) -> None:
            calls.append(("app-init", tmp_path / "data" / "app.db"))

    class FakeDataStore:
        def __init__(self, path: Path) -> None:
            calls.append(("market-init", path))

    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(state_preflight, "AppDatabase", FakeAppDatabase)
    monkeypatch.setattr(state_preflight, "DataStore", FakeDataStore)
    monkeypatch.setattr(
        state_preflight,
        "_require_sqlite_integrity",
        lambda path: calls.append(("integrity", path)),
    )

    state_preflight.preflight_persistent_state()

    assert calls == [
        ("app-construct", tmp_path / "data" / "app.db"),
        ("app-init", tmp_path / "data" / "app.db"),
        ("market-init", tmp_path / "data"),
        ("integrity", tmp_path / "data" / "app.db"),
        ("integrity", tmp_path / "data" / "meta.db"),
    ]


def test_preflight_fails_closed_before_market_store_when_app_database_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IncompatibleAppDatabase:
        def __init__(self, _path: Path) -> None:
            pass

        def init_sync(self) -> None:
            raise RuntimeError("incompatible application database")

    class UnexpectedDataStore:
        def __init__(self, _path: Path) -> None:
            raise AssertionError("market store must not run after app DB failure")

    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(state_preflight, "AppDatabase", IncompatibleAppDatabase)
    monkeypatch.setattr(state_preflight, "DataStore", UnexpectedDataStore)

    with pytest.raises(RuntimeError, match="incompatible application database"):
        state_preflight.preflight_persistent_state()


def test_check_state_initializes_local_sqlite_without_runtime_imports(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")

    result = _run_server(tmp_path, "--check-state", inspect_imports=True)

    assert result.returncode == 0, result.stderr
    assert "Karkinos persisted state compatible" in result.stdout
    assert "FORBIDDEN_IMPORTS=[]" in result.stdout
    with sqlite3.connect(tmp_path / "data" / "app.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[
            0
        ]
    with sqlite3.connect(tmp_path / "data" / "meta.db") as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'bar_meta'"
        ).fetchone() == ("bar_meta",)


def test_check_state_validates_configuration_before_touching_state(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"server": {"port": 0}}),
        encoding="utf-8",
    )

    result = _run_server(tmp_path, "--check-state")

    assert result.returncode != 0
    assert not (tmp_path / "data").exists()


def test_check_config_and_check_state_are_mutually_exclusive(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")

    result = _run_server(tmp_path, "--check-config", "--check-state")

    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
    assert not (tmp_path / "data").exists()
