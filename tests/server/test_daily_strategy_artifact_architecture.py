"""Executable ownership boundaries for daily strategy artifacts."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT_ROOT / "server/contracts/daily_strategy_artifacts.py"
NORMALIZED_RESEARCH_CONTRACT = (
    PROJECT_ROOT / "server/contracts/normalized_strategy_research.py"
)
PROJECTION = PROJECT_ROOT / "server/projections/daily_strategy_artifacts.py"
RESEARCH_CANDIDATE_PROJECTION = (
    PROJECT_ROOT / "server/projections/daily_strategy_research_candidates.py"
)
SQLITE_REPOSITORY = PROJECT_ROOT / "server/persistence/daily_strategy_artifacts.py"
BACKUP_REPOSITORY = PROJECT_ROOT / "server/persistence/daily_strategy_backups.py"
SERVICE = PROJECT_ROOT / "server/services/ai_shadow_research_daily_artifacts.py"
PRODUCTION_FILES = (
    CONTRACT,
    NORMALIZED_RESEARCH_CONTRACT,
    PROJECTION,
    RESEARCH_CANDIDATE_PROJECTION,
    SQLITE_REPOSITORY,
    BACKUP_REPOSITORY,
    SERVICE,
)

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


def test_daily_strategy_artifact_layers_have_single_physical_owners() -> None:
    service_source = SERVICE.read_text(encoding="utf-8")
    projection_imports = _imports(PROJECTION)

    assert "sqlite3" not in _imports(SERVICE)
    assert "sqlite3" not in _imports(BACKUP_REPOSITORY)
    assert "sqlite3" not in projection_imports
    assert "tempfile" not in projection_imports
    assert "os" not in projection_imports
    assert "read_text(" not in service_source
    assert "write_text(" not in service_source
    assert "os.replace(" not in service_source
    assert "BEGIN IMMEDIATE" not in service_source
    assert "BEGIN IMMEDIATE" in SQLITE_REPOSITORY.read_text(encoding="utf-8")


def test_daily_strategy_contracts_and_projections_do_not_depend_on_adapters() -> None:
    forbidden_prefixes = (
        "server.ai_runtime",
        "server.persistence",
        "server.routes",
        "server.services",
    )
    for path in (
        CONTRACT,
        NORMALIZED_RESEARCH_CONTRACT,
        PROJECTION,
        RESEARCH_CANDIDATE_PROJECTION,
    ):
        imports = _imports(path)
        assert not {
            imported for imported in imports if imported.startswith(forbidden_prefixes)
        }, path.name


def test_daily_strategy_modules_have_no_cross_module_private_imports() -> None:
    for path in PRODUCTION_FILES:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            assert not {
                alias.name
                for alias in node.names
                if alias.name.startswith("_") and not alias.name.startswith("__")
            }, path.name


def test_daily_strategy_modules_stay_bounded() -> None:
    for path in PRODUCTION_FILES:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 800, path.name
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assert node.end_lineno is not None
            assert node.end_lineno - node.lineno + 1 <= 350, (path.name, node.name)
