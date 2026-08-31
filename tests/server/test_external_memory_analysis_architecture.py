"""Executable ownership boundaries for external memory-informed analysis."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import server.ai_runtime.external_memory_informed_analysis as facade
from server.ai_runtime.external_memory_analysis_output import decode_stage_output
from server.ai_runtime.external_memory_analysis_provider import (
    OpenAICompatibleMemoryInformedProvider,
)
from server.ai_runtime.external_memory_analysis_result import (
    ExternalMemoryAnalysisResult,
)
from server.ai_runtime.external_memory_analysis_service import (
    HumanExternalMemoryAnalysisService,
)
from server.contracts.external_memory_analysis import (
    ExternalMemoryAnalysisRecord,
    ExternalMemoryAnalysisReplay,
    ExternalModelCallRecord,
    HumanExternalMemoryAnalysisRequest,
)
from server.persistence.external_memory_analysis import (
    ExternalMemoryAnalysisStore,
    model_call_from_row,
    record_from_row,
)
from tests.test_server_import_boundaries import (
    _server_import_graph,
    _strongly_connected_components,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACADE = PROJECT_ROOT / "server/ai_runtime/external_memory_informed_analysis.py"
CONTRACT = PROJECT_ROOT / "server/contracts/external_memory_analysis.py"
PERSISTENCE = PROJECT_ROOT / "server/persistence/external_memory_analysis.py"
AI_RUNTIME_PATHS = {
    FACADE,
    PROJECT_ROOT / "server/ai_runtime/external_memory_analysis_output.py",
    PROJECT_ROOT / "server/ai_runtime/external_memory_analysis_provider.py",
    PROJECT_ROOT / "server/ai_runtime/external_memory_analysis_result.py",
    PROJECT_ROOT / "server/ai_runtime/external_memory_analysis_service.py",
    PROJECT_ROOT / "server/ai_runtime/external_memory_analysis_workflow.py",
}
PRODUCTION_PATHS = {CONTRACT, PERSISTENCE, *AI_RUNTIME_PATHS}

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


def test_external_memory_analysis_facade_preserves_public_contracts() -> None:
    assert (
        facade.HumanExternalMemoryAnalysisRequest is HumanExternalMemoryAnalysisRequest
    )
    assert facade.ExternalMemoryAnalysisRecord is ExternalMemoryAnalysisRecord
    assert facade.ExternalModelCallRecord is ExternalModelCallRecord
    assert facade.ExternalMemoryAnalysisReplay is ExternalMemoryAnalysisReplay
    assert facade.ExternalMemoryAnalysisResult is ExternalMemoryAnalysisResult
    assert facade.ExternalMemoryAnalysisStore is ExternalMemoryAnalysisStore
    assert (
        facade.HumanExternalMemoryAnalysisService is HumanExternalMemoryAnalysisService
    )
    assert (
        facade.OpenAICompatibleMemoryInformedProvider
        is OpenAICompatibleMemoryInformedProvider
    )
    assert facade._decode_stage_output is decode_stage_output
    assert facade.record_from_row is record_from_row
    assert facade.model_call_from_row is model_call_from_row


def test_external_memory_analysis_sql_has_one_physical_owner() -> None:
    for path in {CONTRACT, *AI_RUNTIME_PATHS}:
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(path), path.name
        assert "CREATE TABLE" not in source, path.name
        assert "BEGIN IMMEDIATE" not in source, path.name
        assert "sqlite3.connect(" not in source, path.name

    source = PERSISTENCE.read_text(encoding="utf-8")
    assert "CREATE TABLE" in source
    assert source.count('conn.execute("BEGIN IMMEDIATE")') == 1
    assert "sqlite3.connect(" in source


def test_external_memory_analysis_layers_have_one_way_dependencies() -> None:
    contract_imports = _imports(CONTRACT)
    assert not {
        item
        for item in contract_imports
        if item.startswith(
            (
                "server.composition",
                "server.persistence",
                "server.routes",
                "server.services",
            )
        )
    }

    persistence_imports = _imports(PERSISTENCE)
    assert not {
        item
        for item in persistence_imports
        if item.startswith(("server.composition", "server.routes", "server.services"))
    }

    for path in AI_RUNTIME_PATHS - {FACADE}:
        imports = _imports(path)
        assert not {
            item
            for item in imports
            if item.startswith(
                ("server.composition", "server.persistence", "server.routes")
            )
        }, path.name


def test_external_memory_analysis_modules_use_only_public_cross_module_symbols() -> (
    None
):
    violations: list[str] = []
    for path in PRODUCTION_PATHS:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    violations.append(f"{path.name}:{node.lineno}:{alias.name}")
    assert violations == []


def test_external_memory_analysis_family_has_zero_size_debt() -> None:
    assert set(
        (PROJECT_ROOT / "server/ai_runtime").glob("external_memory_analysis_*.py")
    ) == AI_RUNTIME_PATHS - {FACADE}
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


def test_external_memory_analysis_refactor_keeps_server_graph_acyclic() -> None:
    paths = sorted((PROJECT_ROOT / "server").rglob("*.py"))
    assert _strongly_connected_components(_server_import_graph(paths)) == []
