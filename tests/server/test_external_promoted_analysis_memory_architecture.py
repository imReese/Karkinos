"""Executable architecture boundaries for promoted external-analysis memory."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import server.ai_runtime.external_promoted_analysis_memory as promotion_facade
import server.ai_runtime.external_promoted_analysis_memory_retrieval as retrieval_facade
import server.ai_runtime.external_promoted_memory_analysis_reviews as review_facade
from server.ai_runtime.external_promoted_analysis_memory_result import (
    ExternalPromotedAnalysisMemoryPromotionResult,
    memory_artifact_payload,
)
from server.ai_runtime.external_promoted_analysis_memory_retrieval_result import (
    ExternalPromotedAnalysisMemoryRetrievalResult,
)
from server.ai_runtime.external_promoted_analysis_memory_retrieval_service import (
    HumanExternalPromotedAnalysisMemoryRetrievalService,
)
from server.ai_runtime.external_promoted_analysis_memory_service import (
    ExternalPromotedAnalysisMemoryPromotionService,
    memory_content,
)
from server.ai_runtime.external_promoted_memory_analysis_review_result import (
    ExternalPromotedMemoryAnalysisReviewResult,
)
from server.ai_runtime.external_promoted_memory_analysis_review_service import (
    HumanExternalPromotedMemoryAnalysisReviewService,
    promoted_review_target,
)
from server.contracts.external_promoted_analysis_memory import (
    ExternalPromotedAnalysisMemoryPromotionRequest,
    ExternalPromotedAnalysisMemoryRejected,
)
from server.contracts.external_promoted_analysis_memory_retrieval import (
    ExternalPromotedAnalysisMemoryRetrievalRejected,
    HumanExternalPromotedAnalysisMemoryRetrievalRequest,
)
from server.contracts.external_promoted_memory_analysis_review import (
    ExternalPromotedMemoryAnalysisReviewRejected,
    HumanExternalPromotedMemoryAnalysisReviewRequest,
)
from server.persistence.external_promoted_analysis_memory_retrieval_uow import (
    ExternalPromotedAnalysisMemoryRetrievalStore,
    retrieval_from_row,
)
from server.persistence.external_promoted_analysis_memory_uow import (
    ExternalPromotedAnalysisMemoryStore,
    promotion_from_row,
    revocation_from_row,
)
from server.persistence.external_promoted_memory_analysis_review_uow import (
    ExternalPromotedMemoryAnalysisReviewStore,
    review_from_row,
)
from tests.test_server_import_boundaries import (
    _server_import_graph,
    _strongly_connected_components,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_RUNTIME_ROOT = PROJECT_ROOT / "server/ai_runtime"
CONTRACT_ROOT = PROJECT_ROOT / "server/contracts"
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"

FACADES = {
    AI_RUNTIME_ROOT / "external_promoted_analysis_memory.py",
    AI_RUNTIME_ROOT / "external_promoted_analysis_memory_retrieval.py",
    AI_RUNTIME_ROOT / "external_promoted_memory_analysis_reviews.py",
}
AI_RUNTIME_SUPPORT = {
    AI_RUNTIME_ROOT / "external_promoted_analysis_memory_result.py",
    AI_RUNTIME_ROOT / "external_promoted_analysis_memory_service.py",
    AI_RUNTIME_ROOT / "external_promoted_analysis_memory_retrieval_result.py",
    AI_RUNTIME_ROOT / "external_promoted_analysis_memory_retrieval_service.py",
    AI_RUNTIME_ROOT / "external_promoted_memory_analysis_review_result.py",
    AI_RUNTIME_ROOT / "external_promoted_memory_analysis_review_service.py",
}
CONTRACTS = {
    CONTRACT_ROOT / "external_promoted_analysis_memory.py",
    CONTRACT_ROOT / "external_promoted_analysis_memory_retrieval.py",
    CONTRACT_ROOT / "external_promoted_memory_analysis_review.py",
}
UOWS = {
    PERSISTENCE_ROOT / "external_promoted_analysis_memory_uow.py": 2,
    PERSISTENCE_ROOT / "external_promoted_analysis_memory_retrieval_uow.py": 1,
    PERSISTENCE_ROOT / "external_promoted_memory_analysis_review_uow.py": 1,
}
PRODUCTION_PATHS = {*FACADES, *AI_RUNTIME_SUPPORT, *CONTRACTS, *UOWS}

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


def test_promoted_memory_facades_preserve_canonical_public_identities() -> None:
    assert (
        review_facade.HumanExternalPromotedMemoryAnalysisReviewRequest
        is HumanExternalPromotedMemoryAnalysisReviewRequest
    )
    assert (
        review_facade.ExternalPromotedMemoryAnalysisReviewRejected
        is ExternalPromotedMemoryAnalysisReviewRejected
    )
    assert (
        review_facade.ExternalPromotedMemoryAnalysisReviewResult
        is ExternalPromotedMemoryAnalysisReviewResult
    )
    assert (
        review_facade.HumanExternalPromotedMemoryAnalysisReviewService
        is HumanExternalPromotedMemoryAnalysisReviewService
    )
    assert (
        review_facade.ExternalPromotedMemoryAnalysisReviewStore
        is ExternalPromotedMemoryAnalysisReviewStore
    )
    assert review_facade._promoted_review_target is promoted_review_target
    assert review_facade._review_from_row is review_from_row

    assert (
        promotion_facade.ExternalPromotedAnalysisMemoryPromotionRequest
        is ExternalPromotedAnalysisMemoryPromotionRequest
    )
    assert (
        promotion_facade.ExternalPromotedAnalysisMemoryRejected
        is ExternalPromotedAnalysisMemoryRejected
    )
    assert (
        promotion_facade.ExternalPromotedAnalysisMemoryPromotionResult
        is ExternalPromotedAnalysisMemoryPromotionResult
    )
    assert (
        promotion_facade.ExternalPromotedAnalysisMemoryPromotionService
        is ExternalPromotedAnalysisMemoryPromotionService
    )
    assert (
        promotion_facade.ExternalPromotedAnalysisMemoryStore
        is ExternalPromotedAnalysisMemoryStore
    )
    assert promotion_facade._memory_content is memory_content
    assert promotion_facade._memory_artifact_payload is memory_artifact_payload
    assert promotion_facade._promotion_from_row is promotion_from_row
    assert promotion_facade._revocation_from_row is revocation_from_row

    assert (
        retrieval_facade.HumanExternalPromotedAnalysisMemoryRetrievalRequest
        is HumanExternalPromotedAnalysisMemoryRetrievalRequest
    )
    assert (
        retrieval_facade.ExternalPromotedAnalysisMemoryRetrievalRejected
        is ExternalPromotedAnalysisMemoryRetrievalRejected
    )
    assert (
        retrieval_facade.ExternalPromotedAnalysisMemoryRetrievalResult
        is ExternalPromotedAnalysisMemoryRetrievalResult
    )
    assert (
        retrieval_facade.HumanExternalPromotedAnalysisMemoryRetrievalService
        is HumanExternalPromotedAnalysisMemoryRetrievalService
    )
    assert (
        retrieval_facade.ExternalPromotedAnalysisMemoryRetrievalStore
        is ExternalPromotedAnalysisMemoryRetrievalStore
    )
    assert retrieval_facade._retrieval_from_row is retrieval_from_row


def test_promoted_memory_sql_and_atomic_uows_have_only_persistence_owners() -> None:
    for path in {*FACADES, *AI_RUNTIME_SUPPORT, *CONTRACTS}:
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(path), path.name
        assert "sqlite3.connect(" not in source, path.name
        assert "CREATE TABLE" not in source, path.name
        assert "BEGIN IMMEDIATE" not in source, path.name

    for path, expected_uows in UOWS.items():
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" in _imports(path), path.name
        assert "sqlite3.connect(" in source, path.name
        assert "CREATE TABLE" in source, path.name
        assert source.count('conn.execute("BEGIN IMMEDIATE")') == expected_uows


def test_promoted_memory_layers_have_one_way_dependencies() -> None:
    for path in CONTRACTS:
        assert not {
            imported
            for imported in _imports(path)
            if imported.startswith(
                ("server.composition", "server.persistence", "server.routes")
            )
        }, path.name

    for path in UOWS:
        assert not {
            imported
            for imported in _imports(path)
            if imported.startswith(
                ("server.composition", "server.routes", "server.services")
            )
        }, path.name

    for path in AI_RUNTIME_SUPPORT:
        assert not {
            imported
            for imported in _imports(path)
            if imported.startswith(
                ("server.composition", "server.persistence", "server.routes")
            )
        }, path.name


def test_routes_and_composition_depend_only_on_compatibility_facades() -> None:
    direct_support_modules = (
        {f"server.ai_runtime.{path.stem}" for path in AI_RUNTIME_SUPPORT}
        | {f"server.contracts.{path.stem}" for path in CONTRACTS}
        | {f"server.persistence.{path.stem}" for path in UOWS}
    )
    offenders: list[str] = []
    for root_name in ("composition", "routes"):
        for path in sorted((PROJECT_ROOT / "server" / root_name).rglob("*.py")):
            imported_support = sorted(_imports(path) & direct_support_modules)
            if imported_support:
                offenders.append(f"{path.name}:{','.join(imported_support)}")
    assert offenders == []


def test_promoted_memory_modules_use_only_public_cross_module_symbols() -> None:
    violations: list[str] = []
    for path in PRODUCTION_PATHS:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    violations.append(f"{path.name}:{node.lineno}:{alias.name}")
    assert violations == []


def test_promoted_memory_family_has_zero_size_debt() -> None:
    assert set(AI_RUNTIME_ROOT.glob("external_promoted_analysis_memory*.py")) == {
        AI_RUNTIME_ROOT / "external_promoted_analysis_memory.py",
        AI_RUNTIME_ROOT / "external_promoted_analysis_memory_retrieval.py",
        AI_RUNTIME_ROOT / "external_promoted_analysis_memory_result.py",
        AI_RUNTIME_ROOT / "external_promoted_analysis_memory_service.py",
        AI_RUNTIME_ROOT / "external_promoted_analysis_memory_retrieval_result.py",
        AI_RUNTIME_ROOT / "external_promoted_analysis_memory_retrieval_service.py",
    }
    assert set(
        AI_RUNTIME_ROOT.glob("external_promoted_memory_analysis_review*.py")
    ) == {
        AI_RUNTIME_ROOT / "external_promoted_memory_analysis_reviews.py",
        AI_RUNTIME_ROOT / "external_promoted_memory_analysis_review_result.py",
        AI_RUNTIME_ROOT / "external_promoted_memory_analysis_review_service.py",
    }
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        source = path.read_text(encoding="utf-8")
        line_limit = 300 if path in FACADES else 800
        if len(source.splitlines()) > line_limit:
            violations.append(f"{path.name}:module:{len(source.splitlines())}")
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(f"{path.name}:{node.name}:{size}")
    assert violations == []


def test_promoted_memory_refactor_keeps_server_import_graph_acyclic() -> None:
    paths = sorted((PROJECT_ROOT / "server").rglob("*.py"))
    assert _strongly_connected_components(_server_import_graph(paths)) == []
