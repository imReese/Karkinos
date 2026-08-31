"""Executable architecture boundaries for controlled-session runtime authority."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import server.services.controlled_session_runtime_authority as authority_module
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION as CANONICAL_SCHEMA_VERSION,
)
from server.services.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
    ControlledSessionRuntimeAuthorityRejected,
    ControlledSessionRuntimeAuthorityService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "server/services"
CONTRACT = PROJECT_ROOT / "server/contracts/controlled_session_runtime_authority.py"
SERVICE_PATHS = {
    SERVICE_ROOT / "controlled_session_runtime_authority.py",
    SERVICE_ROOT / "controlled_session_runtime_evidence.py",
    SERVICE_ROOT / "controlled_session_runtime_issuance.py",
    SERVICE_ROOT / "controlled_session_runtime_policy.py",
    SERVICE_ROOT / "controlled_session_runtime_queries.py",
    SERVICE_ROOT / "controlled_session_runtime_replacement.py",
    SERVICE_ROOT / "controlled_session_runtime_revocation.py",
    SERVICE_ROOT / "controlled_session_runtime_values.py",
}
PRODUCTION_PATHS = {CONTRACT, *SERVICE_PATHS}

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


def _called_attributes(path: Path) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_runtime_authority_facade_preserves_public_contract() -> None:
    assert ControlledSessionRuntimeAuthorityService.__module__ == (
        "server.services.controlled_session_runtime_authority"
    )
    assert ControlledSessionRuntimeAuthorityRejected.__module__ == (
        "server.services.controlled_session_runtime_authority"
    )
    assert (
        CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION is CANONICAL_SCHEMA_VERSION
    )

    expected_signatures = {
        "get_status": "(self) -> 'dict[str, Any]'",
        "preview_issuance": (
            "(self, *, reservation_id: 'str', "
            "_replacement_of_session_id: 'str' = '') -> 'dict[str, Any]'"
        ),
        "issue": (
            "(self, *, reservation_id: 'str', issuance_fingerprint: 'str', "
            "operator_approval_id: 'str', operator_proof_signature_base64: 'str', "
            "acknowledgement: 'str') -> 'dict[str, Any]'"
        ),
        "preview_replacement": (
            "(self, *, predecessor_session_id: 'str', reservation_id: 'str') "
            "-> 'dict[str, Any]'"
        ),
        "replace_paused": (
            "(self, *, predecessor_session_id: 'str', reservation_id: 'str', "
            "replacement_fingerprint: 'str', operator_approval_id: 'str', "
            "operator_proof_signature_base64: 'str', acknowledgement: 'str') "
            "-> 'dict[str, Any]'"
        ),
        "list_replacements": "(self, *, limit: 'int' = 100) -> 'list[dict[str, Any]]'",
        "resolve_current": "(self, session_id: 'str') -> 'dict[str, Any]'",
        "authenticate": (
            "(self, session_id: 'str', session_token: 'str') -> 'dict[str, Any]'"
        ),
        "resolve_for_monitoring": "(self, session_id: 'str') -> 'dict[str, Any]'",
        "authenticate_for_monitoring": (
            "(self, session_id: 'str', session_token: 'str') -> 'dict[str, Any]'"
        ),
        "list_sessions": "(self, *, limit: 'int' = 100) -> 'list[dict[str, Any]]'",
        "preview_revocation": (
            "(self, *, session_id: 'str', reason_code: 'str') -> 'dict[str, Any]'"
        ),
        "revoke": (
            "(self, *, session_id: 'str', reason_code: 'str', "
            "revocation_fingerprint: 'str', operator_approval_id: 'str', "
            "operator_proof_signature_base64: 'str', acknowledgement: 'str') "
            "-> 'dict[str, Any]'"
        ),
        "list_revocations": "(self, *, limit: 'int' = 100) -> 'list[dict[str, Any]]'",
    }
    assert {
        name: str(
            inspect.signature(getattr(ControlledSessionRuntimeAuthorityService, name))
        )
        for name in expected_signatures
    } == expected_signatures

    facade_classes = [
        node.name
        for node in _tree(SERVICE_ROOT / "controlled_session_runtime_authority.py").body
        if isinstance(node, ast.ClassDef)
    ]
    assert facade_classes == [
        "ControlledSessionRuntimeAuthorityRejected",
        "ControlledSessionRuntimeAuthorityService",
    ]


def test_runtime_authority_keeps_module_level_operator_approval_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_resolver(**kwargs: object) -> tuple[dict[str, str], list[str]]:
        observed.update(kwargs)
        return {"operator_id": "operator-1"}, []

    monkeypatch.setattr(
        authority_module,
        "resolve_operator_approval_with_proof",
        fake_resolver,
    )
    service = ControlledSessionRuntimeAuthorityService(db=object())

    assert service._resolve_operator_approval(marker="evidence") == (
        {"operator_id": "operator-1"},
        [],
    )
    assert observed == {"marker": "evidence"}


def test_runtime_authority_family_has_zero_size_debt() -> None:
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


def test_runtime_authority_has_no_cross_module_private_imports() -> None:
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    violations.append(f"{path.name}:{node.module}.{alias.name}")
    assert violations == []


def test_runtime_authority_policy_and_values_remain_pure() -> None:
    pure_paths = {
        SERVICE_ROOT / "controlled_session_runtime_policy.py",
        SERVICE_ROOT / "controlled_session_runtime_values.py",
    }
    forbidden_prefixes = (
        "server.db",
        "server.persistence",
        "server.routes",
        "server.services.operator_approval",
    )
    for path in pure_paths:
        imports = _imports(path)
        assert not {
            dependency
            for dependency in imports
            if any(
                dependency == prefix or dependency.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            )
        }, path.name
        source = path.read_text(encoding="utf-8")
        assert "BEGIN IMMEDIATE" not in source
        assert "append_event_sync" not in source


def test_runtime_authority_commands_delegate_to_existing_atomic_uows() -> None:
    expected_owners = {
        "issue_controlled_session_sync": "controlled_session_runtime_issuance.py",
        "replace_paused_controlled_session_sync": (
            "controlled_session_runtime_replacement.py"
        ),
        "revoke_controlled_session_sync": "controlled_session_runtime_revocation.py",
        "append_event_sync": "controlled_session_runtime_evidence.py",
    }
    for method, expected_owner in expected_owners.items():
        owners = {
            path.name for path in SERVICE_PATHS if method in _called_attributes(path)
        }
        assert owners == {expected_owner}

    for path in SERVICE_PATHS:
        source = path.read_text(encoding="utf-8")
        assert "BEGIN IMMEDIATE" not in source, path.name
        assert "sqlite3" not in _imports(path), path.name


def test_runtime_authority_family_has_no_broker_or_reverse_dependencies() -> None:
    forbidden_calls = {"submit_order", "cancel_order", "append_ledger_entry_sync"}
    for path in PRODUCTION_PATHS:
        imports = _imports(path)
        assert not {
            dependency
            for dependency in imports
            if dependency == "server.routes"
            or dependency.startswith("server.routes.")
            or "broker_gateway" in dependency
            or dependency.startswith("execution.")
        }, path.name
        assert not (_called_attributes(path) & forbidden_calls), path.name


def test_runtime_authority_family_import_graph_is_acyclic() -> None:
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
        assert name not in visiting, f"runtime authority import cycle at {name}"
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for module in graph:
        visit(module)
