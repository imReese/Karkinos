"""Executable ownership boundaries for AI shadow research automation."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from server.contracts.ai_shadow_research_automation import (
    PreparedBaseline as CanonicalPreparedBaseline,
)
from server.contracts.ai_shadow_research_automation import (
    ShadowResearchPolicy as CanonicalShadowResearchPolicy,
)
from server.contracts.ai_shadow_research_automation import (
    ShadowResearchRejected as CanonicalShadowResearchRejected,
)
from server.contracts.ai_shadow_research_automation import (
    build_shadow_research_iteration_context,
    build_shadow_research_iteration_lineage,
)
from server.persistence.ai_shadow_research import (
    ShadowResearchStore as CanonicalShadowResearchStore,
)
from server.services.ai_shadow_research_automation import (
    PreparedBaseline,
    ShadowResearchPolicy,
    ShadowResearchRejected,
    ShadowResearchStore,
    _after_close,
    _build_corrected_panel_rearm_evidence,
    _build_iteration_context,
    _failure_code,
    _iteration_lineage,
    build_current_valuation_snapshot,
)
from server.services.ai_shadow_research_policy import (
    build_corrected_panel_rearm_evidence,
)
from server.services.ai_shadow_research_support import (
    is_after_shadow_research_close,
    shadow_research_failure_code,
)
from tests.test_server_import_boundaries import (
    _server_import_graph,
    _strongly_connected_components,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT_ROOT / "server/contracts/ai_shadow_research_automation.py"
QUALIFICATION_CONTRACT = (
    PROJECT_ROOT / "server/contracts/ai_shadow_research_qualification.py"
)
COMPOSITION = PROJECT_ROOT / "server/composition/ai_shadow_research_automation.py"
PROJECTION = PROJECT_ROOT / "server/projections/ai_shadow_research.py"
SERVICE_ROOT = PROJECT_ROOT / "server/services"
SERVICE_PATHS = {
    SERVICE_ROOT / "ai_shadow_research_automation.py",
    SERVICE_ROOT / "ai_shadow_research_baseline.py",
    SERVICE_ROOT / "ai_shadow_research_candidate_workflow.py",
    SERVICE_ROOT / "ai_shadow_research_commands.py",
    SERVICE_ROOT / "ai_shadow_research_daily_artifacts.py",
    SERVICE_ROOT / "ai_shadow_research_job_scheduler.py",
    SERVICE_ROOT / "ai_shadow_research_policy.py",
    SERVICE_ROOT / "ai_shadow_research_qualification.py",
    SERVICE_ROOT / "ai_shadow_research_qualification_support.py",
    SERVICE_ROOT / "ai_shadow_research_support.py",
    SERVICE_ROOT / "ai_shadow_research_worker.py",
    SERVICE_ROOT / "ai_shadow_research_worker_status.py",
    SERVICE_ROOT / "ai_shadow_research_workflow.py",
}
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"
PERSISTENCE_PATHS = {
    PERSISTENCE_ROOT / "ai_shadow_research.py",
    PERSISTENCE_ROOT / "ai_shadow_research_call_extensions.py",
    PERSISTENCE_ROOT / "ai_shadow_research_candidates.py",
    PERSISTENCE_ROOT / "ai_shadow_research_citation_resume.py",
    PERSISTENCE_ROOT / "ai_shadow_research_partial_resume.py",
    PERSISTENCE_ROOT / "ai_shadow_research_provider_calls.py",
    PERSISTENCE_ROOT / "ai_shadow_research_worker_jobs.py",
    PERSISTENCE_ROOT / "ai_shadow_research_qualification.py",
    PERSISTENCE_ROOT / "ai_shadow_research_qualification_candidate_uow.py",
    PERSISTENCE_ROOT / "ai_shadow_research_qualification_promotion.py",
    PERSISTENCE_ROOT / "ai_shadow_research_qualification_promotion.py",
    PERSISTENCE_ROOT / "ai_shadow_research_records.py",
    PERSISTENCE_ROOT / "ai_shadow_research_retry_authorizations.py",
    PERSISTENCE_ROOT / "ai_shadow_research_run_claims.py",
    PERSISTENCE_ROOT / "ai_shadow_research_run_replacements.py",
    PERSISTENCE_ROOT / "ai_shadow_research_runs.py",
    PERSISTENCE_ROOT / "ai_shadow_research_schema.py",
    PERSISTENCE_ROOT / "ai_shadow_research_uow.py",
}
PRODUCTION_PATHS = {
    CONTRACT,
    QUALIFICATION_CONTRACT,
    COMPOSITION,
    PROJECTION,
    *SERVICE_PATHS,
    *PERSISTENCE_PATHS,
}

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


def test_shadow_research_facade_preserves_public_identity_and_patch_seams() -> None:
    assert ShadowResearchRejected is CanonicalShadowResearchRejected
    assert ShadowResearchPolicy is CanonicalShadowResearchPolicy
    assert PreparedBaseline is CanonicalPreparedBaseline
    assert ShadowResearchStore is CanonicalShadowResearchStore
    assert _build_iteration_context is build_shadow_research_iteration_context
    assert _iteration_lineage is build_shadow_research_iteration_lineage
    assert _after_close is is_after_shadow_research_close
    assert _failure_code is shadow_research_failure_code
    assert _build_corrected_panel_rearm_evidence is build_corrected_panel_rearm_evidence
    assert callable(build_current_valuation_snapshot)

    facade = SERVICE_ROOT / "ai_shadow_research_automation.py"
    service = next(
        node
        for node in _tree(facade).body
        if isinstance(node, ast.ClassDef)
        and node.name == "AiShadowResearchAutomationService"
    )
    methods = {
        node.name: ast.get_source_segment(facade.read_text(encoding="utf-8"), node)
        for node in service.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_build_corrected_panel_rearm_evidence" in methods
    assert "_build_current_valuation_snapshot" in methods
    assert "_build_corrected_panel_rearm_evidence" in (
        methods["_build_corrected_panel_rearm_evidence"] or ""
    )
    assert "build_current_valuation_snapshot" in (
        methods["_build_current_valuation_snapshot"] or ""
    )


def test_shadow_research_sql_schema_and_transactions_have_physical_owners() -> None:
    for path in {
        CONTRACT,
        QUALIFICATION_CONTRACT,
        COMPOSITION,
        PROJECTION,
        *SERVICE_PATHS,
    }:
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(path), path.name
        assert "BEGIN IMMEDIATE" not in source, path.name
        assert "ai_shadow_research_runs" not in source, path.name
        assert "CREATE TABLE" not in source, path.name

    uow = PERSISTENCE_ROOT / "ai_shadow_research_uow.py"
    assert uow.read_text(encoding="utf-8").count('"BEGIN IMMEDIATE"') == 1
    connection_owners = {
        path.name
        for path in PERSISTENCE_PATHS
        if "sqlite3.connect(" in path.read_text(encoding="utf-8")
    }
    assert connection_owners == {"ai_shadow_research_uow.py"}
    schema_owners = {
        path.name
        for path in PERSISTENCE_PATHS
        if "CREATE TABLE" in path.read_text(encoding="utf-8")
    }
    assert schema_owners == {"ai_shadow_research_schema.py"}


def test_shadow_research_layers_do_not_invert_dependencies() -> None:
    forbidden_inner_edges = (
        "server.composition",
        "server.persistence",
        "server.routes",
        "server.services",
    )
    for path in (CONTRACT, QUALIFICATION_CONTRACT, PROJECTION):
        imports = _imports(path)
        assert not {
            imported
            for imported in imports
            if imported.startswith(forbidden_inner_edges)
        }, path.name

    for path in PERSISTENCE_PATHS:
        imports = _imports(path)
        assert not {
            imported
            for imported in imports
            if imported.startswith(("server.composition", "server.services"))
        }, path.name

    persistence_importers = {
        path.name
        for path in SERVICE_PATHS
        if any(imported.startswith("server.persistence") for imported in _imports(path))
    }
    assert persistence_importers == {
        "ai_shadow_research_automation.py",
        "ai_shadow_research_daily_artifacts.py",
    }


def test_shadow_research_modules_have_no_cross_module_private_imports() -> None:
    for path in PRODUCTION_PATHS:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            assert not {
                alias.name
                for alias in node.names
                if alias.name.startswith("_") and not alias.name.startswith("__")
            }, path.name


def test_shadow_research_modules_and_functions_have_zero_size_debt() -> None:
    assert set(SERVICE_ROOT.glob("ai_shadow_research*.py")) == SERVICE_PATHS
    assert set(PERSISTENCE_ROOT.glob("ai_shadow_research*.py")) == PERSISTENCE_PATHS
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        source = path.read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{path.name}:module")
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(f"{path.name}:{node.name}:{size}")
    assert violations == []


def test_shadow_research_refactor_keeps_full_server_import_graph_acyclic() -> None:
    paths = sorted((PROJECT_ROOT / "server").rglob("*.py"))
    assert _strongly_connected_components(_server_import_graph(paths)) == []
