"""Executable ownership constraints for reviewed-memory retrieval."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import server.ai_runtime.memory_retrieval as retrieval_facade
from server.ai_runtime.store import IdempotencyConflict
from tests.test_server_import_boundaries import _cross_module_private_imports

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_RUNTIME_ROOT = PROJECT_ROOT / "server/ai_runtime"
CONTRACT_ROOT = PROJECT_ROOT / "server/contracts"
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"

FACADE = AI_RUNTIME_ROOT / "memory_retrieval.py"
AI_RUNTIME_SUPPORT = {
    AI_RUNTIME_ROOT / "memory_retrieval_result.py",
    AI_RUNTIME_ROOT / "memory_retrieval_service.py",
    AI_RUNTIME_ROOT / "memory_retrieval_values.py",
}
CONTRACT = CONTRACT_ROOT / "memory_retrieval.py"
PROJECTION = PERSISTENCE_ROOT / "memory_retrieval_projection.py"
REPOSITORY = PERSISTENCE_ROOT / "memory_retrieval_repository.py"
SCHEMA = PERSISTENCE_ROOT / "memory_retrieval_schema.py"
UOW = PERSISTENCE_ROOT / "memory_retrieval_uow.py"
PERSISTENCE = {PROJECTION, REPOSITORY, SCHEMA, UOW}
PRODUCTION_PATHS = {FACADE, CONTRACT, *AI_RUNTIME_SUPPORT, *PERSISTENCE}

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    module_name = path.relative_to(PROJECT_ROOT).with_suffix("").as_posix()
    package = module_name.replace("/", ".").rpartition(".")[0]
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package_parts = package.split(".")
                base = ".".join(package_parts[: len(package_parts) - node.level + 1])
                imported = f"{base}.{node.module}" if node.module else base
            else:
                imported = node.module or ""
            if imported:
                imports.add(imported)
    return imports


def _parameter_names(callable_object: object) -> tuple[str, ...]:
    return tuple(inspect.signature(callable_object).parameters)


def test_memory_retrieval_family_inventory_has_zero_baseline() -> None:
    assert set(AI_RUNTIME_ROOT.glob("memory_retrieval*.py")) == {
        FACADE,
        *AI_RUNTIME_SUPPORT,
    }
    assert set(CONTRACT_ROOT.glob("memory_retrieval*.py")) == {CONTRACT}
    assert set(PERSISTENCE_ROOT.glob("memory_retrieval*.py")) == PERSISTENCE


def test_memory_retrieval_family_has_zero_size_debt() -> None:
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        source = path.read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        if line_count > 800:
            violations.append(f"{path.name}:module:{line_count}")
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if function_lines > 350:
                violations.append(f"{path.name}:{node.name}:{function_lines}")
    assert violations == []


def test_memory_retrieval_persistence_has_single_explicit_owners() -> None:
    facade_source = FACADE.read_text(encoding="utf-8")
    assert "sqlite3" not in _imports(FACADE)
    assert "sqlite3.connect(" not in facade_source
    assert "CREATE TABLE" not in facade_source
    assert "BEGIN IMMEDIATE" not in facade_source

    for path in PRODUCTION_PATHS:
        source = path.read_text(encoding="utf-8")
        if "CREATE TABLE" in source:
            assert path == SCHEMA
        if "sqlite3.connect(" in source:
            assert path == REPOSITORY
        if "BEGIN IMMEDIATE" in source:
            assert path == UOW

    assert REPOSITORY.read_text(encoding="utf-8").count("sqlite3.connect(") == 1
    assert UOW.read_text(encoding="utf-8").count('conn.execute("BEGIN IMMEDIATE")') == 1


def test_memory_retrieval_layers_have_one_way_dependencies() -> None:
    for path in {CONTRACT, *AI_RUNTIME_SUPPORT}:
        assert not {
            imported
            for imported in _imports(path)
            if imported.startswith(
                ("server.composition", "server.persistence", "server.routes")
            )
        }, path.name
    for path in PERSISTENCE:
        assert not {
            imported
            for imported in _imports(path)
            if imported.startswith(
                ("server.composition", "server.routes", "server.services")
            )
        }, path.name


def test_routes_and_composition_depend_only_on_memory_retrieval_facade() -> None:
    direct_support_modules = {
        path.relative_to(PROJECT_ROOT).with_suffix("").as_posix().replace("/", ".")
        for path in {CONTRACT, *AI_RUNTIME_SUPPORT, *PERSISTENCE}
    }
    offenders: list[str] = []
    for root_name in ("composition", "routes"):
        for path in sorted((PROJECT_ROOT / "server" / root_name).rglob("*.py")):
            imported_support = sorted(_imports(path) & direct_support_modules)
            if imported_support:
                offenders.append(f"{path.name}:{','.join(imported_support)}")
    assert offenders == []


def test_public_compatibility_identities_and_signatures_are_stable() -> None:
    public_types = (
        retrieval_facade.ReviewedMemoryRetrievalRejected,
        retrieval_facade.HumanReviewedMemoryRetrievalRequest,
        retrieval_facade.EvidenceRebinding,
        retrieval_facade.ReviewedMemorySelection,
        retrieval_facade.ReviewedMemoryRetrievalTarget,
        retrieval_facade.StoredReviewedMemoryRetrieval,
        retrieval_facade.ReviewedMemoryRetrievalAuditReplay,
        retrieval_facade.ReviewedMemoryRetrievalReplay,
        retrieval_facade.ReviewedMemoryRetrievalResult,
    )
    assert all(item.__module__ == retrieval_facade.__name__ for item in public_types)
    assert retrieval_facade.IdempotencyConflict is IdempotencyConflict
    assert _parameter_names(retrieval_facade.ReviewedMemoryRetrievalStore) == (
        "db_path",
    )
    assert _parameter_names(retrieval_facade.ReviewedMemoryRetrievalStore.record) == (
        "self",
        "request",
        "target",
        "created_at",
    )
    assert _parameter_names(retrieval_facade.HumanReviewedMemoryRetrievalService) == (
        "review_service",
        "analysis_service",
        "ai_store",
        "evidence_repository",
        "retrieval_store",
        "now",
    )


def test_legacy_private_helper_monkeypatch_seams_remain_live(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(retrieval_facade, "_retrieval_from_row", lambda row: sentinel)
    monkeypatch.setattr(
        retrieval_facade,
        "_retrieval_event_hash",
        lambda **kwargs: "patched",
    )
    monkeypatch.setattr(
        retrieval_facade,
        "_exact_memory_artifact",
        lambda **kwargs: sentinel,
    )

    assert (
        retrieval_facade.ReviewedMemoryRetrievalStore._retrieval_from_row(None)
        is sentinel
    )
    assert (
        retrieval_facade.ReviewedMemoryRetrievalStore._retrieval_event_hash()
        == "patched"
    )
    assert (
        retrieval_facade.HumanReviewedMemoryRetrievalService._exact_memory_artifact(
            artifacts=(),
            memory_artifact_id=None,
        )
        is sentinel
    )


def test_memory_retrieval_family_uses_only_public_cross_module_imports() -> None:
    assert _cross_module_private_imports(sorted(PRODUCTION_PATHS)) == set()
