"""Executable architecture boundaries for per-order confirmation."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import server.contracts.per_order_confirmation as canonical_contract
import server.services.per_order_confirmation as confirmation_module
from server.services.execution_identity import build_order_fingerprint
from server.services.per_order_confirmation import (
    PerOrderConfirmationRejected,
    PerOrderConfirmationService,
)
from tests.test_server_import_boundaries import _cross_module_private_imports

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "server/services"
CONTRACT = PROJECT_ROOT / "server/contracts/per_order_confirmation.py"
SERVICE_PATHS = {
    SERVICE_ROOT / "per_order_confirmation.py",
    SERVICE_ROOT / "per_order_confirmation_commands.py",
    SERVICE_ROOT / "per_order_confirmation_evidence.py",
    SERVICE_ROOT / "per_order_confirmation_preview.py",
    SERVICE_ROOT / "per_order_confirmation_queries.py",
    SERVICE_ROOT / "per_order_confirmation_values.py",
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


def _called_attributes(path: Path) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_confirmation_facade_preserves_public_contract() -> None:
    assert PerOrderConfirmationService.__module__ == (
        "server.services.per_order_confirmation"
    )
    assert PerOrderConfirmationRejected.__module__ == (
        "server.services.per_order_confirmation"
    )
    assert confirmation_module.build_order_fingerprint is build_order_fingerprint

    for name in (
        "PER_ORDER_DOSSIER_SCHEMA_VERSION",
        "PER_ORDER_CONFIRMATION_SCHEMA_VERSION",
        "PER_ORDER_CONFIRMATION_EVENT_TYPE",
        "PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE",
        "PER_ORDER_CONFIRMATION_EVENT_SOURCE",
        "PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT",
        "PER_ORDER_CONFIRMATION_MAX_SOAK_AGE_SECONDS",
    ):
        assert getattr(confirmation_module, name) is getattr(canonical_contract, name)

    expected_signatures = {
        "get_status": "(self) -> 'dict[str, Any]'",
        "preview_dossier": (
            "(self, order_id: 'str', *, "
            "capital_evaluation_input_fingerprint: 'str' = '', "
            "prior_batch_reconciliation_fingerprint: 'str' = '', "
            "execution_gateway_verification_fingerprint: 'str' = '') "
            "-> 'dict[str, Any]'"
        ),
        "record_confirmation": (
            "(self, order_id: 'str', *, "
            "capital_evaluation_input_fingerprint: 'str', "
            "prior_batch_reconciliation_fingerprint: 'str', "
            "execution_gateway_verification_fingerprint: 'str', "
            "dossier_fingerprint: 'str', operator_label: 'str', "
            "operator_approval_id: 'str', acknowledgement: 'str') "
            "-> 'dict[str, Any]'"
        ),
        "resolve_confirmation": ("(self, confirmation_id: 'str') -> 'dict[str, Any]'"),
        "list_confirmations": (
            "(self, order_id: 'str', *, limit: 'int' = 100) "
            "-> 'list[dict[str, Any]]'"
        ),
    }
    assert {
        name: str(inspect.signature(getattr(PerOrderConfirmationService, name)))
        for name in expected_signatures
    } == expected_signatures


def test_confirmation_family_has_zero_size_and_private_import_debt() -> None:
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        source = path.read_text(encoding="utf-8")
        module_limit = 200 if path.name == "per_order_confirmation.py" else 800
        if len(source.splitlines()) > module_limit:
            violations.append(f"{path.name}:module")
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(f"{path.name}:{node.name}:{size}")
    assert violations == []
    assert _cross_module_private_imports(sorted(PRODUCTION_PATHS)) == set()


def test_confirmation_ownership_stays_one_way_and_non_authorizing() -> None:
    values_path = SERVICE_ROOT / "per_order_confirmation_values.py"
    contract_imports = _imports(CONTRACT)
    values_imports = _imports(values_path)
    assert not {
        item
        for item in contract_imports
        if item.startswith(("server.persistence", "server.routes", "server.services"))
    }
    assert not {
        item
        for item in values_imports
        if item.startswith(("server.persistence", "server.routes", "server.db"))
    }

    write_owners = {
        path.name
        for path in SERVICE_PATHS
        if "append_event_sync" in _called_attributes(path)
    }
    assert write_owners == {"per_order_confirmation_commands.py"}
    forbidden_calls = {
        "submit_order",
        "cancel_order",
        "transition_oms_order_sync",
        "append_ledger_entry_sync",
        "reserve_capital_sync",
        "release_capital_sync",
    }
    for path in PRODUCTION_PATHS:
        assert "sqlite3" not in _imports(path), path.name
        assert not (_called_attributes(path) & forbidden_calls), path.name
        assert not {
            item
            for item in _imports(path)
            if item == "server.routes" or item.startswith("server.routes.")
        }, path.name


def test_confirmation_family_import_graph_is_acyclic() -> None:
    modules = {path.stem: path for path in SERVICE_PATHS}
    graph = {
        name: {
            imported.removeprefix("server.services.")
            for imported in _imports(path)
            if imported.startswith("server.services.")
            and imported.removeprefix("server.services.") in modules
        }
        for name, path in modules.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        assert name not in visiting, f"per-order confirmation cycle at {name}"
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for module in graph:
        visit(module)
