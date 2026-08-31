"""Executable ownership boundaries for controlled broker cancellation."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from server.contracts.controlled_broker_cancellation import (
    ControlledBrokerCancellationRejected as CanonicalCancellationRejected,
)
from server.persistence.controlled_broker_cancellations import (
    ControlledBrokerCancellationStore as CanonicalCancellationStore,
)
from server.services.controlled_broker_cancellation import (
    ControlledBrokerCancellationRejected,
    ControlledBrokerCancellationStore,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT_ROOT / "server/contracts/controlled_broker_cancellation.py"
PROJECTION = PROJECT_ROOT / "server/projections/controlled_broker_cancellation.py"
SERVICE_ROOT = PROJECT_ROOT / "server/services"
SERVICE_PATHS = {
    SERVICE_ROOT / "controlled_broker_cancellation.py",
    SERVICE_ROOT / "controlled_broker_cancellation_audit.py",
    SERVICE_ROOT / "controlled_broker_cancellation_policy.py",
    SERVICE_ROOT / "controlled_broker_cancellation_preview.py",
    SERVICE_ROOT / "controlled_broker_cancellation_workflows.py",
}
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"
PERSISTENCE_PATHS = {
    PERSISTENCE_ROOT / "controlled_broker_cancellation_records.py",
    PERSISTENCE_ROOT / "controlled_broker_cancellation_schema.py",
    PERSISTENCE_ROOT / "controlled_broker_cancellation_uow.py",
    PERSISTENCE_ROOT / "controlled_broker_cancellations.py",
}
PRODUCTION_PATHS = {CONTRACT, PROJECTION, *SERVICE_PATHS, *PERSISTENCE_PATHS}

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _called_names(path: Path) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_cancellation_facade_preserves_public_class_identity() -> None:
    assert ControlledBrokerCancellationRejected is CanonicalCancellationRejected
    assert ControlledBrokerCancellationStore is CanonicalCancellationStore

    facade = SERVICE_ROOT / "controlled_broker_cancellation.py"
    direct_classes = [
        node.name for node in _tree(facade).body if isinstance(node, ast.ClassDef)
    ]
    assert direct_classes == ["ControlledBrokerCancellationService"]


def test_cancellation_sql_and_transactions_have_single_physical_owners() -> None:
    for path in {CONTRACT, PROJECTION, *SERVICE_PATHS}:
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(path), path.name
        assert "BEGIN IMMEDIATE" not in source, path.name
        assert "controlled_broker_cancellation_commands" not in source, path.name
        assert "controlled_broker_cancellation_recovery_claims" not in source, path.name

    uow = PERSISTENCE_ROOT / "controlled_broker_cancellation_uow.py"
    assert uow.read_text(encoding="utf-8").count('"BEGIN IMMEDIATE"') == 4
    schema = PERSISTENCE_ROOT / "controlled_broker_cancellation_schema.py"
    schema_source = schema.read_text(encoding="utf-8")
    assert "controlled_broker_cancellation_commands" in schema_source
    assert "controlled_broker_cancellation_recovery_claims" in schema_source


def test_cancellation_layers_do_not_invert_adapter_dependencies() -> None:
    forbidden_contract_edges = (
        "server.persistence",
        "server.routes",
        "server.services",
    )
    for path in (CONTRACT, PROJECTION):
        imports = _imports(path)
        assert not {
            imported
            for imported in imports
            if imported.startswith(forbidden_contract_edges)
        }, path.name

    for path in PERSISTENCE_PATHS:
        imports = _imports(path)
        assert not {
            imported
            for imported in imports
            if imported == "server.services" or imported.startswith("server.services.")
        }, path.name

    persistence_importers = {
        path.name
        for path in SERVICE_PATHS
        if any(imported.startswith("server.persistence") for imported in _imports(path))
    }
    assert persistence_importers == {"controlled_broker_cancellation.py"}


def test_cancellation_external_effects_have_one_workflow_owner() -> None:
    cancel_owners = {
        path.name for path in SERVICE_PATHS if "canceller" in _called_names(path)
    }
    query_owners = {
        path.name for path in SERVICE_PATHS if "query" in _called_names(path)
    }
    assert cancel_owners == {"controlled_broker_cancellation_workflows.py"}
    assert query_owners == {"controlled_broker_cancellation_workflows.py"}


def test_cancellation_modules_have_no_cross_module_private_imports() -> None:
    for path in PRODUCTION_PATHS:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            assert not {
                alias.name
                for alias in node.names
                if alias.name.startswith("_") and not alias.name.startswith("__")
            }, path.name


def test_cancellation_modules_and_functions_have_zero_size_debt() -> None:
    assert set(SERVICE_ROOT.glob("controlled_broker_cancellation*.py")) == SERVICE_PATHS
    assert set(PERSISTENCE_ROOT.glob("controlled_broker_cancellation*.py")) == (
        PERSISTENCE_PATHS
    )
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        source = path.read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{path.name}:module")
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(f"{path.name}:{node.name}:{size}")
    assert violations == []
