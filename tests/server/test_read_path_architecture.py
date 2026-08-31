"""Executable zero-write boundaries for HTTP reads and pure projections."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = PROJECT_ROOT / "server"
GET_ROUTE_ROOTS = (SERVER_ROOT / "routes", SERVER_ROOT / "http")
MUTATION_PREFIXES = (
    "confirm_",
    "delete_",
    "insert_",
    "publish_",
    "record_",
    "save_",
    "set_",
    "update_",
    "upsert_",
)

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _is_get_endpoint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "get"
        for decorator in node.decorator_list
    )


def _mutation_calls(node: ast.AST) -> list[tuple[int, str]]:
    return [
        (call.lineno, call.func.attr)
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr.startswith(MUTATION_PREFIXES)
    ]


def test_get_endpoints_have_no_persistence_mutation_calls() -> None:
    violations: list[str] = []
    paths = sorted(
        {
            path
            for root in GET_ROUTE_ROOTS
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
        }
    )
    for path in paths:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _is_get_endpoint(node):
                continue
            violations.extend(
                f"{path.relative_to(PROJECT_ROOT)}:{line}:{node.name}:{name}"
                for line, name in _mutation_calls(node)
            )
    assert violations == []


def test_projection_modules_never_call_mutation_ports() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT)}:{line}:{name}"
        for path in sorted((SERVER_ROOT / "projections").rglob("*.py"))
        for line, name in _mutation_calls(_tree(path))
    ]
    assert violations == []
