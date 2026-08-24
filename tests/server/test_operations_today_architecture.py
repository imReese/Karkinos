"""Executable boundaries for the Operations Today projection family."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "server/services/operations_today.py",
    "server/services/operations_today_contracts.py",
    "server/services/operations_today_values.py",
    "server/services/operations_today_paper_shadow.py",
    "server/services/operations_today_scheduler.py",
    "server/services/operations_today_subsystems.py",
)
MODULE_NAMES = {path.removesuffix(".py").replace("/", ".") for path in MODULES}

pytestmark = pytest.mark.unit


def _tree(relative_path: str) -> ast.Module:
    path = PROJECT_ROOT / relative_path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(relative_path: str) -> list[tuple[str, str, int]]:
    imports: list[tuple[str, str, int]] = []
    for node in ast.walk(_tree(relative_path)):
        if isinstance(node, ast.Import):
            imports.extend(
                (alias.name, alias.name, node.lineno) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.extend(
                (node.module, alias.name, node.lineno) for alias in node.names
            )
    return imports


def test_operations_today_modules_have_zero_size_debt() -> None:
    violations: list[str] = []
    for relative_path in MODULES:
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{relative_path}: module exceeds 800 lines")
        for node in ast.walk(_tree(relative_path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = (node.end_lineno or node.lineno) - node.lineno + 1
                if size > 350:
                    violations.append(
                        f"{relative_path}:{node.lineno} {node.name} exceeds 350 lines"
                    )

    assert violations == []


def test_operations_today_dependency_graph_is_acyclic_and_uses_public_symbols() -> None:
    graph: dict[str, set[str]] = {module: set() for module in MODULE_NAMES}
    private_imports: list[str] = []
    for relative_path in MODULES:
        owner = relative_path.removesuffix(".py").replace("/", ".")
        for dependency, name, line in _imports(relative_path):
            if dependency not in MODULE_NAMES:
                continue
            graph[owner].add(dependency)
            if name.startswith("_"):
                private_imports.append(f"{relative_path}:{line}:{name}")

    assert private_imports == []
    facade = "server.services.operations_today"
    assert all(
        facade not in dependencies
        for module, dependencies in graph.items()
        if module != facade
    )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        assert module not in visiting, f"Operations Today dependency cycle at {module}"
        if module in visited:
            return
        visiting.add(module)
        for dependency in graph[module]:
            visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)


def test_operations_today_family_does_not_depend_on_routes_or_persistence() -> None:
    violations: list[str] = []
    for relative_path in MODULES:
        for dependency, _, line in _imports(relative_path):
            if dependency == "sqlite3" or dependency.startswith(
                ("server.routes", "server.persistence")
            ):
                violations.append(f"{relative_path}:{line}:{dependency}")

    assert violations == []


def test_operations_today_facade_only_owns_top_level_composition() -> None:
    definitions = {
        node.name
        for node in _tree(MODULES[0]).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert definitions == {"build_operations_today_summary"}
