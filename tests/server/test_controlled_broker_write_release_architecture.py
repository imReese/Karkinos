"""Executable ownership boundaries for controlled broker write releases."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_FILES = (
    "server/contracts/controlled_broker_write_release.py",
    "server/persistence/controlled_broker_write_releases.py",
    "server/services/controlled_broker_write_release.py",
    "server/services/controlled_broker_write_release_dossier.py",
    "server/services/controlled_broker_write_release_policy.py",
    "server/services/controlled_broker_write_release_workflow.py",
)
APPLICATION_FILES = tuple(
    path for path in PRODUCTION_FILES if "/persistence/" not in path
)

pytestmark = pytest.mark.unit


def _tree(relative_path: str) -> ast.Module:
    path = PROJECT_ROOT / relative_path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(relative_path: str) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(relative_path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_write_release_application_layers_own_no_sqlite_or_sql() -> None:
    sql_markers = ("BEGIN IMMEDIATE", "CREATE TABLE", "SELECT ", "INSERT INTO")
    for relative_path in APPLICATION_FILES:
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(relative_path), relative_path
        assert all(marker not in source for marker in sql_markers), relative_path


def test_write_release_persistence_owns_exact_atomic_uows() -> None:
    relative_path = "server/persistence/controlled_broker_write_releases.py"
    source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    imports = _imports(relative_path)

    assert source.count('connection.execute("BEGIN IMMEDIATE")') == 2
    assert not {
        imported
        for imported in imports
        if imported == "server.services" or imported.startswith("server.services.")
    }


def test_write_release_modules_stay_bounded_and_facade_stays_stable() -> None:
    for relative_path in PRODUCTION_FILES:
        path = PROJECT_ROOT / relative_path
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 800, relative_path
        for node in ast.walk(_tree(relative_path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno is not None
                assert node.end_lineno - node.lineno + 1 <= 350, (
                    relative_path,
                    node.name,
                )

    facade = _tree("server/services/controlled_broker_write_release.py")
    service = next(
        node
        for node in facade.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ControlledBrokerWriteReleaseService"
    )
    public_methods = {
        node.name
        for node in service.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    assert public_methods == {
        "get_status",
        "preview_dossier",
        "record_release",
        "preview_revocation",
        "revoke_release",
        "resolve_release_evidence",
        "list_releases",
        "get_release",
    }
