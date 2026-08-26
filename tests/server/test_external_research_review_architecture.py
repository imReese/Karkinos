"""Executable architecture boundaries for external research and its reviews."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from server.ai_runtime import external_analysis_reviews, external_research
from server.ai_runtime.external_research_provider import (
    OpenAICompatibleBacktestReportProvider,
)
from server.ai_runtime.external_research_result import ExternalBacktestReportResult
from server.ai_runtime.external_research_service import (
    HumanExternalBacktestReportService,
)
from server.ai_runtime.external_research_store import ExternalBacktestReportAuditStore
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.external_research import (
    ExternalBacktestReportRecord,
    HumanExternalBacktestReportRequest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_RUNTIME_ROOT = PROJECT_ROOT / "server" / "ai_runtime"

EXPECTED_PRODUCTION_MODULES = {
    "server/ai_runtime/external_analysis_review_target.py",
    "server/ai_runtime/external_analysis_review_values.py",
    "server/ai_runtime/external_analysis_reviews.py",
    "server/ai_runtime/external_research.py",
    "server/ai_runtime/external_research_errors.py",
    "server/ai_runtime/external_research_output.py",
    "server/ai_runtime/external_research_provider.py",
    "server/ai_runtime/external_research_result.py",
    "server/ai_runtime/external_research_service.py",
    "server/ai_runtime/external_research_store.py",
    "server/ai_runtime/external_research_workflow.py",
    "server/contracts/external_research.py",
    "server/persistence/external_analysis_review_projection.py",
    "server/persistence/external_analysis_review_repository.py",
    "server/persistence/external_analysis_review_schema.py",
    "server/persistence/external_analysis_review_uow.py",
    "server/persistence/external_research_projection.py",
    "server/persistence/external_research_repository.py",
    "server/persistence/external_research_schema.py",
    "server/persistence/external_research_uow.py",
}

FACADE_MODULES = {
    "server/ai_runtime/external_analysis_reviews.py",
    "server/ai_runtime/external_research.py",
}

SCHEMA_OWNERS = {
    "server/persistence/external_analysis_review_schema.py",
    "server/persistence/external_research_schema.py",
}

REPOSITORY_OWNERS = {
    "server/persistence/external_analysis_review_repository.py",
    "server/persistence/external_research_repository.py",
}

UOW_OWNERS = {
    "server/persistence/external_analysis_review_uow.py",
    "server/persistence/external_research_uow.py",
}

pytestmark = pytest.mark.unit


def _path(relative_path: str) -> Path:
    return PROJECT_ROOT / relative_path


def _tree(relative_path: str) -> ast.Module:
    path = _path(relative_path)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(relative_path: str) -> set[str]:
    imports: set[str] = set()
    module_name = relative_path.removesuffix(".py").replace("/", ".")
    package = module_name.rpartition(".")[0]
    for node in ast.walk(_tree(relative_path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
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


def test_family_inventory_has_no_unreviewed_architecture_baseline() -> None:
    discovered = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for root, patterns in (
            (PROJECT_ROOT / "server/ai_runtime", ("external_research*.py",)),
            (
                PROJECT_ROOT / "server/ai_runtime",
                ("external_analysis_review*.py",),
            ),
            (PROJECT_ROOT / "server/persistence", ("external_research_*.py",)),
            (
                PROJECT_ROOT / "server/persistence",
                ("external_analysis_review_*.py",),
            ),
        )
        for pattern in patterns
        for path in root.glob(pattern)
    }
    discovered.add("server/contracts/external_research.py")
    assert discovered == EXPECTED_PRODUCTION_MODULES


def test_modules_and_named_functions_stay_within_reviewable_limits() -> None:
    violations: list[str] = []
    for relative_path in sorted(EXPECTED_PRODUCTION_MODULES):
        source = _path(relative_path).read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{relative_path}: module exceeds 800 lines")
        for node in ast.walk(_tree(relative_path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assert node.end_lineno is not None
            length = node.end_lineno - node.lineno + 1
            if length > 350:
                violations.append(
                    f"{relative_path}:{node.name}: function exceeds 350 lines"
                )
    assert violations == []


def test_external_research_facade_is_a_small_explicit_compatibility_surface() -> None:
    source = _path("server/ai_runtime/external_research.py").read_text(encoding="utf-8")
    assert len(source.splitlines()) < 300
    tree = _tree("server/ai_runtime/external_research.py")
    assert not [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def test_ai_runtime_facades_have_no_sqlite_or_sql_ownership() -> None:
    for relative_path in sorted(FACADE_MODULES):
        source = _path(relative_path).read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(relative_path), relative_path
        assert "sqlite3.connect(" not in source, relative_path
        assert "CREATE TABLE" not in source, relative_path
        assert "BEGIN IMMEDIATE" not in source, relative_path
        assert "SELECT * FROM ai_external" not in source, relative_path
        assert "INSERT INTO ai_external" not in source, relative_path


def test_schema_repository_and_uow_owners_are_explicit() -> None:
    for relative_path in sorted(EXPECTED_PRODUCTION_MODULES):
        source = _path(relative_path).read_text(encoding="utf-8")
        if "CREATE TABLE" in source:
            assert relative_path in SCHEMA_OWNERS
        if "sqlite3.connect(" in source:
            assert relative_path in REPOSITORY_OWNERS
        if "BEGIN IMMEDIATE" in source:
            assert relative_path in UOW_OWNERS

    for relative_path in SCHEMA_OWNERS:
        source = _path(relative_path).read_text(encoding="utf-8")
        assert source.count("CREATE TABLE IF NOT EXISTS") >= 1
        assert "BEGIN IMMEDIATE" not in source
    for relative_path in REPOSITORY_OWNERS:
        source = _path(relative_path).read_text(encoding="utf-8")
        assert source.count("sqlite3.connect(") == 1
        assert "CREATE TABLE" not in source
        assert "BEGIN IMMEDIATE" not in source
    for relative_path in UOW_OWNERS:
        source = _path(relative_path).read_text(encoding="utf-8")
        assert source.count('conn.execute("BEGIN IMMEDIATE")') == 1
        assert "CREATE TABLE" not in source


def test_public_compatibility_types_and_aliases_remain_canonical() -> None:
    assert external_research.ExternalBacktestReportAuditStore is (
        ExternalBacktestReportAuditStore
    )
    assert external_research.OpenAICompatibleBacktestReportProvider is (
        OpenAICompatibleBacktestReportProvider
    )
    assert external_research.HumanExternalBacktestReportService is (
        HumanExternalBacktestReportService
    )
    assert external_research.ExternalBacktestReportResult is (
        ExternalBacktestReportResult
    )
    assert external_research.ExternalBacktestReportRecord is (
        ExternalBacktestReportRecord
    )
    assert external_research.HumanExternalBacktestReportRequest is (
        HumanExternalBacktestReportRequest
    )
    assert external_analysis_reviews.ExternalAnalysisReviewStore.__module__ == (
        "server.ai_runtime.external_analysis_reviews"
    )
    assert external_analysis_reviews.HumanExternalAnalysisReviewService.__module__ == (
        "server.ai_runtime.external_analysis_reviews"
    )
    assert external_analysis_reviews.IdempotencyConflict is IdempotencyConflict

    assert external_research.edge_request_options is (
        external_research._edge_request_options
    )
    assert external_research.message_text is external_research._message_text
    assert external_analysis_reviews.review_target is (
        external_analysis_reviews._review_target
    )
    assert external_analysis_reviews.event_hash is external_analysis_reviews._event_hash
    assert external_analysis_reviews.cost_evidence is (
        external_analysis_reviews._cost_evidence
    )


def test_contracts_and_persistence_do_not_depend_on_runtime_workflow() -> None:
    contract_imports = _imports("server/contracts/external_research.py")
    assert not {
        item
        for item in contract_imports
        if item.startswith(
            (
                "server.ai_runtime",
                "server.composition",
                "server.persistence",
                "server.routes",
                "server.services",
            )
        )
    }
    for relative_path in sorted(
        path
        for path in EXPECTED_PRODUCTION_MODULES
        if path.startswith("server/persistence/external_research_")
    ):
        assert not {
            item
            for item in _imports(relative_path)
            if item.startswith(
                (
                    "server.ai_runtime",
                    "server.composition",
                    "server.routes",
                    "server.services",
                )
            )
        }, relative_path


def test_internal_modules_do_not_use_the_public_facade_as_a_helper_hub() -> None:
    offenders: set[str] = set()
    for path in AI_RUNTIME_ROOT.glob("*.py"):
        if path.name == "external_research.py":
            continue
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        if "server.ai_runtime.external_research" in _imports(relative_path):
            offenders.add(relative_path)
    assert offenders == set()


def test_public_constructor_and_method_parameters_remain_compatible() -> None:
    assert _parameter_names(external_research.ExternalBacktestReportAuditStore) == (
        "db_path",
    )
    assert _parameter_names(
        external_research.ExternalBacktestReportAuditStore.create_or_get
    ) == (
        "self",
        "request",
        "capture_id",
        "workflow_id",
        "context_snapshot_id",
        "context_fingerprint",
        "evidence_reference_id",
        "provider_id",
        "model_id",
        "created_at",
    )
    assert _parameter_names(
        external_research.OpenAICompatibleBacktestReportProvider
    ) == (
        "provider_id",
        "settings",
        "evidence_reference_id",
        "research_question",
        "context_binding",
        "transport",
        "monotonic",
        "timeout_seconds",
    )
    assert _parameter_names(external_research.HumanExternalBacktestReportService) == (
        "settings",
        "capture_service",
        "evidence_repository",
        "ai_store",
        "report_store",
        "transport",
        "now",
        "monotonic",
        "model_timeout_seconds",
    )
    assert _parameter_names(external_analysis_reviews.ExternalAnalysisReviewStore) == (
        "db_path",
    )
    assert _parameter_names(
        external_analysis_reviews.ExternalAnalysisReviewStore.record
    ) == ("self", "target", "request", "created_at")
    assert _parameter_names(
        external_analysis_reviews.HumanExternalAnalysisReviewService
    ) == ("analysis_service", "review_store", "now")


def test_scoped_production_dependency_graph_is_acyclic() -> None:
    module_by_name = {
        relative_path.removesuffix(".py").replace("/", "."): relative_path
        for relative_path in EXPECTED_PRODUCTION_MODULES
    }
    graph = {
        module_name: {
            imported
            for imported in _imports(relative_path)
            if imported in module_by_name
        }
        for module_name, relative_path in module_by_name.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module_name: str) -> None:
        if module_name in visiting:
            raise AssertionError(f"external research dependency cycle: {module_name}")
        if module_name in visited:
            return
        visiting.add(module_name)
        for dependency in graph[module_name]:
            visit(dependency)
        visiting.remove(module_name)
        visited.add(module_name)

    for module_name in graph:
        visit(module_name)
