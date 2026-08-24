"""Executable boundaries for the portfolio application projection family."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "server/projections/portfolio_application.py",
    "server/projections/portfolio_assets.py",
    "server/projections/portfolio_quotes.py",
    "server/projections/portfolio_positions.py",
)

pytestmark = pytest.mark.unit


def _tree(relative_path: str) -> ast.Module:
    path = PROJECT_ROOT / relative_path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(relative_path: str) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(relative_path)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_portfolio_projection_modules_remain_bounded() -> None:
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


def test_portfolio_projection_dependency_graph_stays_one_way() -> None:
    dependencies = {path: _imports(path) for path in MODULES}
    facade = "server.projections.portfolio_application"

    for relative_path in MODULES[1:]:
        assert facade not in dependencies[relative_path]
    assert "server.projections.portfolio_quotes" not in dependencies[MODULES[1]]
    assert "server.projections.portfolio_positions" not in dependencies[MODULES[1]]
    assert "server.projections.portfolio_positions" not in dependencies[MODULES[2]]


def test_portfolio_projection_family_does_not_depend_on_routes_or_sqlite() -> None:
    violations: dict[str, list[str]] = {}
    for relative_path in MODULES:
        forbidden = sorted(
            dependency
            for dependency in _imports(relative_path)
            if dependency == "sqlite3" or dependency.startswith("server.routes")
        )
        if forbidden:
            violations[relative_path] = forbidden

    assert violations == {}


def test_portfolio_facade_only_owns_top_level_application_composition() -> None:
    definitions = {
        node.name
        for node in _tree(MODULES[0]).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert definitions == {
        "build_account_state_response",
        "build_portfolio_snapshot",
    }
