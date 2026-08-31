"""Executable ownership boundaries for broker connector soak evidence."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from server.projections import broker_connector_soak as projections
from server.services import broker_connector_soak as service

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE = PROJECT_ROOT / "server/services/broker_connector_soak.py"
PROJECTIONS = PROJECT_ROOT / "server/projections/broker_connector_soak.py"
PERSISTENCE = PROJECT_ROOT / "server/persistence/broker_connector_soak.py"
PRODUCTION_FILES = (SERVICE, PROJECTIONS, PERSISTENCE)

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_broker_soak_physical_owners_are_separated() -> None:
    service_source = SERVICE.read_text(encoding="utf-8")
    projection_imports = _imports(PROJECTIONS)

    assert "sqlite3" not in _imports(SERVICE)
    assert "sqlite3" not in projection_imports
    assert "BEGIN IMMEDIATE" not in service_source
    assert "server.persistence" not in projection_imports
    assert not {
        name
        for name in projection_imports
        if name == "server.services" or name.startswith("server.services.")
    }
    assert PERSISTENCE.read_text(encoding="utf-8").count('"BEGIN IMMEDIATE"') == 1


def test_broker_soak_public_policy_identity_is_stable() -> None:
    assert (
        service.reviewed_broker_soak_sequence_is_accepted
        is projections.reviewed_broker_soak_sequence_is_accepted
    )


def test_broker_soak_modules_have_no_cross_module_private_imports() -> None:
    for path in PRODUCTION_FILES:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            assert not {
                alias.name
                for alias in node.names
                if alias.name.startswith("_") and not alias.name.startswith("__")
            }, path.name


def test_broker_soak_modules_stay_bounded() -> None:
    for path in PRODUCTION_FILES:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 800, path.name
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assert node.end_lineno is not None
            assert node.end_lineno - node.lineno + 1 <= 350, (path.name, node.name)
