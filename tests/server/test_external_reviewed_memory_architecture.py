"""Executable architecture boundaries for external reviewed memory."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import server.ai_runtime.external_reviewed_memory as promotion_facade
import server.ai_runtime.external_reviewed_memory_retrieval as retrieval_facade
from server.ai_runtime.store import IdempotencyConflict
from tests.test_server_import_boundaries import (
    _cross_module_private_imports,
    _server_import_graph,
    _strongly_connected_components,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_RUNTIME_ROOT = PROJECT_ROOT / "server/ai_runtime"
CONTRACT_ROOT = PROJECT_ROOT / "server/contracts"
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"

FACADES = {
    AI_RUNTIME_ROOT / "external_reviewed_memory.py",
    AI_RUNTIME_ROOT / "external_reviewed_memory_retrieval.py",
}
AI_RUNTIME_SUPPORT = {
    AI_RUNTIME_ROOT / "external_reviewed_memory_result.py",
    AI_RUNTIME_ROOT / "external_reviewed_memory_service.py",
    AI_RUNTIME_ROOT / "external_reviewed_memory_values.py",
    AI_RUNTIME_ROOT / "external_reviewed_memory_retrieval_result.py",
    AI_RUNTIME_ROOT / "external_reviewed_memory_retrieval_service.py",
    AI_RUNTIME_ROOT / "external_reviewed_memory_retrieval_values.py",
}
CONTRACTS = {
    CONTRACT_ROOT / "external_reviewed_memory.py",
    CONTRACT_ROOT / "external_reviewed_memory_retrieval.py",
}
PROJECTIONS = {
    PERSISTENCE_ROOT / "external_reviewed_memory_projection.py",
    PERSISTENCE_ROOT / "external_reviewed_memory_retrieval_projection.py",
}
REPOSITORIES = {
    PERSISTENCE_ROOT / "external_reviewed_memory_repository.py",
    PERSISTENCE_ROOT / "external_reviewed_memory_retrieval_repository.py",
}
SCHEMAS = {
    PERSISTENCE_ROOT / "external_reviewed_memory_schema.py",
    PERSISTENCE_ROOT / "external_reviewed_memory_retrieval_schema.py",
}
UOWS = {
    PERSISTENCE_ROOT / "external_reviewed_memory_uow.py": 2,
    PERSISTENCE_ROOT / "external_reviewed_memory_retrieval_uow.py": 1,
}
PERSISTENCE = {*PROJECTIONS, *REPOSITORIES, *SCHEMAS, *UOWS}
PRODUCTION_PATHS = {*FACADES, *AI_RUNTIME_SUPPORT, *CONTRACTS, *PERSISTENCE}

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


def test_external_reviewed_memory_family_inventory_has_zero_baseline() -> None:
    assert set(AI_RUNTIME_ROOT.glob("external_reviewed_memory*.py")) == {
        *FACADES,
        *AI_RUNTIME_SUPPORT,
    }
    assert set(CONTRACT_ROOT.glob("external_reviewed_memory*.py")) == CONTRACTS
    assert set(PERSISTENCE_ROOT.glob("external_reviewed_memory*.py")) == PERSISTENCE


def test_external_reviewed_memory_family_has_zero_size_debt() -> None:
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


def test_facades_have_no_sqlite_sql_schema_or_transaction_ownership() -> None:
    for path in FACADES:
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(path), path.name
        assert "sqlite3.connect(" not in source, path.name
        assert "CREATE TABLE" not in source, path.name
        assert "BEGIN IMMEDIATE" not in source, path.name
        assert "SELECT * FROM ai_external" not in source, path.name
        assert "INSERT INTO ai_external" not in source, path.name


def test_persistence_owners_are_exact_and_non_overlapping() -> None:
    for path in PRODUCTION_PATHS:
        source = path.read_text(encoding="utf-8")
        if "CREATE TABLE" in source:
            assert path in SCHEMAS
        if "sqlite3.connect(" in source:
            assert path in REPOSITORIES
        if "BEGIN IMMEDIATE" in source:
            assert path in UOWS

    for path in SCHEMAS:
        source = path.read_text(encoding="utf-8")
        assert source.count("CREATE TABLE IF NOT EXISTS") >= 1
        assert "sqlite3.connect(" not in source
        assert "BEGIN IMMEDIATE" not in source
    for path in REPOSITORIES:
        source = path.read_text(encoding="utf-8")
        assert source.count("sqlite3.connect(") == 1
        assert "CREATE TABLE" not in source
        assert "BEGIN IMMEDIATE" not in source
    for path, expected_count in UOWS.items():
        source = path.read_text(encoding="utf-8")
        assert source.count('conn.execute("BEGIN IMMEDIATE")') == expected_count
        assert "sqlite3.connect(" not in source
        assert "CREATE TABLE" not in source


def test_external_reviewed_memory_layers_have_one_way_dependencies() -> None:
    for path in CONTRACTS | AI_RUNTIME_SUPPORT:
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


def test_routes_and_composition_depend_only_on_compatibility_facades() -> None:
    direct_support_modules = {
        path.relative_to(PROJECT_ROOT).with_suffix("").as_posix().replace("/", ".")
        for path in AI_RUNTIME_SUPPORT | CONTRACTS | PERSISTENCE
    }
    offenders: list[str] = []
    for root_name in ("composition", "routes"):
        for path in sorted((PROJECT_ROOT / "server" / root_name).rglob("*.py")):
            imported_support = sorted(_imports(path) & direct_support_modules)
            if imported_support:
                offenders.append(f"{path.name}:{','.join(imported_support)}")
    assert offenders == []


def test_public_compatibility_identities_and_signatures_are_stable() -> None:
    promotion_types = (
        promotion_facade.ExternalReviewedMemoryEffectiveStatus,
        promotion_facade.ExternalReviewedMemoryPromotionRejected,
        promotion_facade.ExternalReviewedMemoryPromotionRequest,
        promotion_facade.ExternalReviewedMemoryRevocationRequest,
        promotion_facade.ExternalReviewedMemoryTarget,
        promotion_facade.StoredExternalReviewedMemoryPromotion,
        promotion_facade.StoredExternalReviewedMemoryRevocation,
        promotion_facade.ExternalReviewedMemoryAuditReplay,
        promotion_facade.ExternalReviewedMemoryReplay,
        promotion_facade.ExternalReviewedMemoryPromotionResult,
    )
    retrieval_types = (
        retrieval_facade.ExternalReviewedMemoryRetrievalRejected,
        retrieval_facade.HumanExternalReviewedMemoryRetrievalRequest,
        retrieval_facade.ExternalReviewedMemorySelection,
        retrieval_facade.ExternalReviewedMemoryRetrievalTarget,
        retrieval_facade.StoredExternalReviewedMemoryRetrieval,
        retrieval_facade.ExternalReviewedMemoryRetrievalAuditReplay,
        retrieval_facade.ExternalReviewedMemoryRetrievalReplay,
        retrieval_facade.ExternalReviewedMemoryRetrievalResult,
    )
    assert all(item.__module__ == promotion_facade.__name__ for item in promotion_types)
    assert all(item.__module__ == retrieval_facade.__name__ for item in retrieval_types)
    assert promotion_facade.IdempotencyConflict is IdempotencyConflict
    assert retrieval_facade.IdempotencyConflict is IdempotencyConflict

    assert _parameter_names(promotion_facade.ExternalReviewedMemoryStore) == (
        "db_path",
    )
    assert _parameter_names(
        promotion_facade.ExternalReviewedMemoryStore.record_promotion
    ) == ("self", "request", "target", "created_at")
    assert _parameter_names(
        promotion_facade.ExternalReviewedMemoryStore.record_revocation
    ) == ("self", "promotion", "request", "created_at")
    assert _parameter_names(
        promotion_facade.ExternalReviewedMemoryPromotionService
    ) == ("review_service", "ai_store", "promotion_store", "now")
    assert _parameter_names(retrieval_facade.ExternalReviewedMemoryRetrievalStore) == (
        "db_path",
    )
    assert _parameter_names(
        retrieval_facade.ExternalReviewedMemoryRetrievalStore.record
    ) == ("self", "request", "target", "created_at")
    assert _parameter_names(
        retrieval_facade.HumanExternalReviewedMemoryRetrievalService
    ) == (
        "promotion_service",
        "ai_store",
        "evidence_repository",
        "current_context_validator",
        "retrieval_store",
        "now",
    )


def test_legacy_private_helper_monkeypatch_seams_remain_live(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(promotion_facade, "_promotion_from_row", lambda row: sentinel)
    monkeypatch.setattr(promotion_facade, "_revocation_from_row", lambda row: sentinel)
    monkeypatch.setattr(promotion_facade, "_event_hash", lambda **kwargs: "patched")
    monkeypatch.setattr(promotion_facade, "_memory_content", lambda **kwargs: sentinel)
    monkeypatch.setattr(
        promotion_facade,
        "_memory_artifact_payload",
        lambda **kwargs: sentinel,
    )
    monkeypatch.setattr(
        promotion_facade,
        "_optional_non_empty_string",
        lambda value: "patched",
    )
    assert promotion_facade.ExternalReviewedMemoryStore._promotion_from_row(None) is (
        sentinel
    )
    assert promotion_facade.ExternalReviewedMemoryStore._revocation_from_row(None) is (
        sentinel
    )
    assert promotion_facade.ExternalReviewedMemoryStore._event_hash() == "patched"
    assert (
        promotion_facade.ExternalReviewedMemoryPromotionService._memory_content()
        is sentinel
    )
    assert (
        promotion_facade.ExternalReviewedMemoryPromotionService._memory_artifact_payload()
        is sentinel
    )
    assert (
        promotion_facade.ExternalReviewedMemoryPromotionResult._memory_artifact_payload()
        is sentinel
    )
    assert (
        promotion_facade.ExternalReviewedMemoryPromotionService._optional_non_empty_string(
            None
        )
        == "patched"
    )

    monkeypatch.setattr(retrieval_facade, "_retrieval_from_row", lambda row: sentinel)
    monkeypatch.setattr(retrieval_facade, "_event_hash", lambda **kwargs: "patched")
    assert (
        retrieval_facade.ExternalReviewedMemoryRetrievalStore._retrieval_from_row(None)
        is sentinel
    )
    assert (
        retrieval_facade.ExternalReviewedMemoryRetrievalStore._event_hash() == "patched"
    )


def test_family_uses_only_public_cross_module_imports() -> None:
    assert _cross_module_private_imports(sorted(PRODUCTION_PATHS)) == set()


def test_external_reviewed_memory_refactor_keeps_server_graph_acyclic() -> None:
    paths = sorted((PROJECT_ROOT / "server").rglob("*.py"))
    assert _strongly_connected_components(_server_import_graph(paths)) == []
