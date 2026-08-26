"""Executable layering rules for the external-provider connectivity edge."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import server.ai_runtime.provider_connectivity as facade
from server.ai_runtime.provider_connectivity_adapter import (
    OpenAICompatibleConnectivityAdapter,
)
from server.ai_runtime.provider_connectivity_audit import (
    ProviderConnectivityAuditStore,
)
from server.ai_runtime.provider_connectivity_contracts import (
    ConnectivityCheckRequest,
    ConnectivityCheckResult,
    ProviderConnectivitySettings,
)
from server.ai_runtime.provider_connectivity_service import (
    ProviderConnectivityService,
)
from server.ai_runtime.provider_connectivity_settings import (
    load_provider_connectivity_settings,
)
from server.ai_runtime.provider_connectivity_transport import (
    HttpxDeadlineJsonTransport,
    UrllibJsonTransport,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "server" / "ai_runtime"
FAMILY_PATHS = {
    RUNTIME_ROOT / "provider_connectivity.py",
    RUNTIME_ROOT / "provider_connectivity_adapter.py",
    RUNTIME_ROOT / "provider_connectivity_audit.py",
    RUNTIME_ROOT / "provider_connectivity_contracts.py",
    RUNTIME_ROOT / "provider_connectivity_service.py",
    RUNTIME_ROOT / "provider_connectivity_settings.py",
    RUNTIME_ROOT / "provider_connectivity_transport.py",
    RUNTIME_ROOT / "openai_compatibility.py",
    RUNTIME_ROOT / "persistence" / "provider_connectivity.py",
}
FACADE = RUNTIME_ROOT / "provider_connectivity.py"
PERSISTENCE = RUNTIME_ROOT / "persistence" / "provider_connectivity.py"

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_name(path: Path) -> str:
    return "server." + path.relative_to(ROOT / "server").with_suffix(
        ""
    ).as_posix().replace("/", ".")


def _imports(path: Path) -> set[str]:
    module_name = _module_name(path)
    package = module_name.rpartition(".")[0]
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                imported = f"{base}.{node.module}" if node.module else base
            else:
                imported = node.module or ""
            if imported:
                result.add(imported)
    return result


def test_provider_connectivity_family_inventory_is_explicit() -> None:
    discovered = set(RUNTIME_ROOT.glob("provider_connectivity*.py"))
    discovered.add(RUNTIME_ROOT / "openai_compatibility.py")
    discovered.add(PERSISTENCE)
    assert discovered == FAMILY_PATHS


def test_public_facade_is_small_and_reexports_canonical_implementations() -> None:
    source = FACADE.read_text(encoding="utf-8")
    assert len(source.splitlines()) < 300
    assert not [
        node
        for node in _tree(FACADE).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert facade.ProviderConnectivitySettings is ProviderConnectivitySettings
    assert facade.ConnectivityCheckRequest is ConnectivityCheckRequest
    assert facade.ConnectivityCheckResult is ConnectivityCheckResult
    assert facade.OpenAICompatibleConnectivityAdapter is (
        OpenAICompatibleConnectivityAdapter
    )
    assert facade.ProviderConnectivityAuditStore is ProviderConnectivityAuditStore
    assert facade.ProviderConnectivityService is ProviderConnectivityService
    assert facade.HttpxDeadlineJsonTransport is HttpxDeadlineJsonTransport
    assert facade.UrllibJsonTransport is UrllibJsonTransport
    assert facade.load_provider_connectivity_settings is (
        load_provider_connectivity_settings
    )


def test_provider_connectivity_layers_have_one_way_dependencies() -> None:
    contracts = RUNTIME_ROOT / "provider_connectivity_contracts.py"
    forbidden_in_contracts = {
        item
        for item in _imports(contracts)
        if item.startswith(
            (
                "server.ai_runtime.provider_connectivity_",
                "server.ai_runtime.persistence",
                "server.composition",
                "server.routes",
                "server.services",
            )
        )
    }
    assert forbidden_in_contracts == set()

    assert not {
        item
        for item in _imports(PERSISTENCE)
        if item.startswith(
            (
                "server.ai_runtime",
                "server.composition",
                "server.routes",
                "server.services",
            )
        )
    }

    leaf_modules = {
        RUNTIME_ROOT / "provider_connectivity_settings.py",
        RUNTIME_ROOT / "provider_connectivity_transport.py",
        RUNTIME_ROOT / "provider_connectivity_adapter.py",
        RUNTIME_ROOT / "provider_connectivity_audit.py",
        RUNTIME_ROOT / "openai_compatibility.py",
    }
    for path in leaf_modules:
        imports = _imports(path)
        assert "server.ai_runtime.provider_connectivity_service" not in imports, path
        assert "server.ai_runtime.provider_connectivity" not in imports, path


def test_runtime_modules_do_not_use_connectivity_facade_as_a_helper_hub() -> None:
    offenders: list[str] = []
    for path in RUNTIME_ROOT.glob("*.py"):
        if path == FACADE:
            continue
        if "server.ai_runtime.provider_connectivity" in _imports(path):
            offenders.append(path.name)
    assert offenders == []


def test_family_dependency_graph_is_acyclic() -> None:
    modules = {_module_name(path): path for path in FAMILY_PATHS}
    graph = {
        module: {dependency for dependency in _imports(path) if dependency in modules}
        for module, path in modules.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in visiting:
            raise AssertionError(f"provider connectivity dependency cycle: {module}")
        if module in visited:
            return
        visiting.add(module)
        for dependency in graph[module]:
            visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)


def test_family_has_zero_size_and_dynamic_locator_debt() -> None:
    violations: list[str] = []
    for path in FAMILY_PATHS:
        source = path.read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{path.name}:module")
        if "__module__" in source or "sys.modules" in source:
            violations.append(f"{path.name}:dynamic_locator")
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(f"{path.name}:{node.name}:{size}")
    assert violations == []
