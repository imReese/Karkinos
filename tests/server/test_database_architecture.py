"""Executable ownership constraints for the application database boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"
FACADE_ROOT = PERSISTENCE_ROOT / "facades"

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_app_database_is_a_thin_repository_composition_root() -> None:
    path = PROJECT_ROOT / "server/db.py"
    source = path.read_text(encoding="utf-8")
    tree = _tree(path)
    app_database = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AppDatabase"
    )
    direct_methods = {
        node.name
        for node in app_database.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert len(source.splitlines()) <= 200
    assert direct_methods == {"__init__", "path", "init", "init_sync"}
    assert "sqlite3" not in _module_imports(path)
    assert "aiosqlite" not in _module_imports(path)
    assert "BEGIN " not in source


def test_database_compatibility_surface_is_partitioned_without_duplicates() -> None:
    facade_paths = sorted(
        path
        for path in FACADE_ROOT.glob("*.py")
        if path.name not in {"__init__.py", "base.py"}
    )
    method_owners: dict[str, str] = {}
    for path in facade_paths:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 500, path.name
        facade = next(
            node for node in _tree(path).body if isinstance(node, ast.ClassDef)
        )
        for method in (
            node
            for node in facade.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            assert method.end_lineno is not None
            assert method.end_lineno - method.lineno + 1 <= 60, (
                path.name,
                method.name,
            )
            assert method.name not in method_owners, (
                method.name,
                method_owners.get(method.name),
                path.name,
            )
            method_owners[method.name] = path.name

    assert len(method_owners) == 168


def test_persistence_layer_does_not_depend_on_application_services() -> None:
    offenders = {
        path.relative_to(PROJECT_ROOT).as_posix(): sorted(
            imported
            for imported in _module_imports(path)
            if imported == "server.services" or imported.startswith("server.services.")
        )
        for path in sorted(PERSISTENCE_ROOT.rglob("*.py"))
    }

    assert {path: imports for path, imports in offenders.items() if imports} == {}


def test_unit_of_work_boundaries_remain_explicit() -> None:
    expected = {
        "ai_shadow_research_uow.py": 1,
        "broker_connector_soak.py": 1,
        "controlled_broker_cancellation_uow.py": 4,
        "controlled_broker_write_releases.py": 2,
        "controlled_broker_intents.py": 3,
        "controlled_broker_rejection_reviews.py": 1,
        "controlled_clearance_uow.py": 1,
        "controlled_ledger_correction_uow.py": 1,
        "controlled_ledger_posting_uow.py": 1,
        "controlled_session_budgets.py": 1,
        "controlled_session_gate_snapshots.py": 1,
        "controlled_session_issuance_uow.py": 1,
        "controlled_session_pause_uow.py": 1,
        "controlled_session_rate_admission_uow.py": 1,
        "controlled_session_replacement_uow.py": 1,
        "controlled_session_revocation_uow.py": 1,
        "decision_outcome_reviews.py": 1,
        "decision_quality.py": 1,
        "daily_strategy_artifacts.py": 1,
        "external_memory_analysis.py": 1,
        "reviewed_fee_schedule_reviews.py": 1,
        "strategy_research_uow.py": 1,
    }
    actual = {
        path.name: path.read_text(encoding="utf-8").count('"BEGIN IMMEDIATE"')
        for path in PERSISTENCE_ROOT.glob("*.py")
        if '"BEGIN IMMEDIATE"' in path.read_text(encoding="utf-8")
    }

    assert actual == expected
