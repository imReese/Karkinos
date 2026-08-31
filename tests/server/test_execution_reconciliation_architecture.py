"""Executable architecture boundaries for execution reconciliation."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from server.contracts.execution_reconciliation import (
    CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION as CANONICAL_CONTROLLED_SCHEMA,
)
from server.contracts.execution_reconciliation import (
    EXECUTION_RECONCILIATION_SCHEMA_VERSION as CANONICAL_RECONCILIATION_SCHEMA,
)
from server.services.execution_reconciliation import (
    CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION,
    EXECUTION_RECONCILIATION_SCHEMA_VERSION,
    ExecutionReconciliationService,
    build_current_plan_paper_actual_comparison,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "server/services"
CONTRACT = PROJECT_ROOT / "server/contracts/execution_reconciliation.py"
SERVICE_PATHS = {
    SERVICE_ROOT / "execution_reconciliation.py",
    SERVICE_ROOT / "execution_reconciliation_broker_evidence.py",
    SERVICE_ROOT / "execution_reconciliation_comparison.py",
    SERVICE_ROOT / "execution_reconciliation_controlled.py",
    SERVICE_ROOT / "execution_reconciliation_values.py",
}
PRODUCTION_PATHS = {CONTRACT, *SERVICE_PATHS}

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _family_dependencies(path: Path) -> set[str]:
    return {
        imported.removeprefix("server.services.")
        for imported in _imports(path)
        if imported.startswith("server.services.execution_reconciliation")
    }


def _called_names(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            result.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            result.add(node.func.attr)
    return result


def test_execution_reconciliation_facade_preserves_public_contract() -> None:
    assert ExecutionReconciliationService.__module__ == (
        "server.services.execution_reconciliation"
    )
    assert build_current_plan_paper_actual_comparison.__module__ == (
        "server.services.execution_reconciliation"
    )
    assert EXECUTION_RECONCILIATION_SCHEMA_VERSION is CANONICAL_RECONCILIATION_SCHEMA
    assert (
        CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION
        is CANONICAL_CONTROLLED_SCHEMA
    )
    assert str(
        inspect.signature(ExecutionReconciliationService.run_reconciliation)
    ) == ("(self, *, run_date: 'str | None' = None) -> 'dict[str, Any]'")
    parameters = inspect.signature(
        build_current_plan_paper_actual_comparison
    ).parameters
    assert list(parameters) == [
        "db",
        "order",
        "broker_events",
        "controlled_intent",
    ]
    assert parameters["broker_events"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["broker_events"].default is None
    assert parameters["controlled_intent"].kind is inspect.Parameter.KEYWORD_ONLY

    facade_classes = [
        node.name
        for node in _tree(SERVICE_ROOT / "execution_reconciliation.py").body
        if isinstance(node, ast.ClassDef)
    ]
    assert facade_classes == ["ExecutionReconciliationService"]


def test_execution_reconciliation_family_has_zero_size_debt() -> None:
    assert set(SERVICE_ROOT.glob("execution_reconciliation*.py")) == SERVICE_PATHS
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        source = path.read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{path.name}:module")
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(f"{path.name}:{node.name}:{size}")
    assert violations == []


def test_execution_reconciliation_has_no_cross_module_private_imports() -> None:
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    violations.append(f"{path.name}:{node.module}.{alias.name}")
    assert violations == []


def test_execution_reconciliation_owns_no_sql_or_http_dependencies() -> None:
    for path in PRODUCTION_PATHS:
        source = path.read_text(encoding="utf-8")
        imports = _imports(path)
        assert "sqlite3" not in imports, path.name
        assert "BEGIN IMMEDIATE" not in source, path.name
        assert not {
            item
            for item in imports
            if item == "server.routes" or item.startswith("server.routes.")
        }, path.name
        assert not {
            item
            for item in imports
            if item == "server.persistence" or item.startswith("server.persistence.")
        }, path.name


def test_broker_repository_access_has_one_service_owner() -> None:
    owners = {
        path.name
        for path in SERVICE_PATHS
        if any(
            imported.startswith("account_truth.broker") for imported in _imports(path)
        )
    }
    assert owners == {"execution_reconciliation_broker_evidence.py"}
    assert "BrokerEvidenceRepository" in (
        SERVICE_ROOT / "execution_reconciliation_broker_evidence.py"
    ).read_text(encoding="utf-8")
    assert "BrokerEvidenceRepository" not in (
        SERVICE_ROOT / "execution_reconciliation.py"
    ).read_text(encoding="utf-8")


def test_execution_reconciliation_family_import_graph_is_acyclic() -> None:
    modules = {path.stem: path for path in SERVICE_PATHS}
    graph = {
        name: {
            dependency
            for dependency in _family_dependencies(path)
            if dependency in modules
        }
        for name, path in modules.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        assert name not in visiting, f"execution reconciliation import cycle at {name}"
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for module in graph:
        visit(module)


def test_only_reconciliation_run_persistence_is_invoked_directly() -> None:
    facade = SERVICE_ROOT / "execution_reconciliation.py"
    source = facade.read_text(encoding="utf-8")
    assert "upsert_execution_reconciliation_run_sync" in source
    forbidden_mutations = (
        "create_oms_order",
        "transition_oms_order",
        "record_fill",
        "append_ledger",
        "post_ledger",
        "submit_order",
        "cancel_order",
    )
    for path in PRODUCTION_PATHS:
        assert not {
            mutation
            for mutation in forbidden_mutations
            if mutation in _called_names(path)
        }, path.name
