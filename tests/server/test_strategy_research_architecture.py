"""Executable ownership boundaries for human-gated AI strategy research."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from server.ai_runtime.strategy_research import (
    CritiqueRequest,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
    RestrictedFormulaBacktestAdapter,
    StrategyResearchAuditStore,
    StrategyResearchModelProvider,
    StrategyResearchRejected,
    StrategyResearchSelection,
    StrategyResearchService,
    _build_hypothesis_citation_catalog,
    _citation_path_exists,
    _compact_hypothesis_citation_catalog,
    rolling_oos_parameters,
)
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter as CanonicalRestrictedFormulaBacktestAdapter,
)
from server.ai_runtime.strategy_research_backtest import (
    rolling_oos_parameters as canonical_rolling_oos_parameters,
)
from server.ai_runtime.strategy_research_backtest_workflow import (
    StrategyResearchBacktestWorkflowMixin,
)
from server.ai_runtime.strategy_research_citations import (
    build_hypothesis_citation_catalog,
    citation_path_exists,
    compact_hypothesis_citation_catalog,
)
from server.ai_runtime.strategy_research_critique import StrategyResearchCritiqueMixin
from server.ai_runtime.strategy_research_generation import (
    StrategyResearchGenerationMixin,
)
from server.ai_runtime.strategy_research_provider import (
    StrategyResearchModelProvider as CanonicalStrategyResearchModelProvider,
)
from server.ai_runtime.strategy_research_session import StrategyResearchSessionMixin
from server.contracts.strategy_research import (
    CritiqueRequest as CanonicalCritiqueRequest,
)
from server.contracts.strategy_research import (
    FormulaBacktestRequest as CanonicalFormulaBacktestRequest,
)
from server.contracts.strategy_research import (
    HypothesisGenerationRequest as CanonicalHypothesisGenerationRequest,
)
from server.contracts.strategy_research import (
    StrategyResearchRejected as CanonicalStrategyResearchRejected,
)
from server.contracts.strategy_research import (
    StrategyResearchSelection as CanonicalStrategyResearchSelection,
)
from server.persistence.strategy_research import (
    StrategyResearchAuditStore as CanonicalStrategyResearchAuditStore,
)
from server.projections.backtest_result import (
    build_backtest_report_metrics_json as canonical_build_backtest_report_metrics_json,
)
from server.projections.backtest_result import (
    fill_to_response as canonical_fill_to_response,
)
from server.services.backtest_result_projection import (
    build_backtest_report_metrics_json,
    fill_to_response,
)
from tests.test_server_import_boundaries import (
    _server_import_graph,
    _strongly_connected_components,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_RUNTIME_ROOT = PROJECT_ROOT / "server/ai_runtime"
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"
CONTRACT = PROJECT_ROOT / "server/contracts/strategy_research.py"
COMPOSITION = PROJECT_ROOT / "server/composition/strategy_research.py"
BACKTEST_PROJECTION = PROJECT_ROOT / "server/projections/backtest_result.py"
AI_RUNTIME_PATHS = {
    AI_RUNTIME_ROOT / "strategy_research.py",
    AI_RUNTIME_ROOT / "strategy_research_account_evidence.py",
    AI_RUNTIME_ROOT / "strategy_research_backtest.py",
    AI_RUNTIME_ROOT / "strategy_research_backtest_workflow.py",
    AI_RUNTIME_ROOT / "strategy_research_citations.py",
    AI_RUNTIME_ROOT / "strategy_research_critique.py",
    AI_RUNTIME_ROOT / "strategy_research_generation.py",
    AI_RUNTIME_ROOT / "strategy_research_model_contract.py",
    AI_RUNTIME_ROOT / "strategy_research_privacy.py",
    AI_RUNTIME_ROOT / "strategy_research_provider.py",
    AI_RUNTIME_ROOT / "strategy_research_sealed.py",
    AI_RUNTIME_ROOT / "strategy_research_session.py",
    AI_RUNTIME_ROOT / "strategy_research_support.py",
    AI_RUNTIME_ROOT / "strategy_research_values.py",
}
PERSISTENCE_PATHS = {
    PERSISTENCE_ROOT / "strategy_research.py",
    PERSISTENCE_ROOT / "strategy_research_backtests.py",
    PERSISTENCE_ROOT / "strategy_research_critiques.py",
    PERSISTENCE_ROOT / "strategy_research_errors.py",
    PERSISTENCE_ROOT / "strategy_research_events.py",
    PERSISTENCE_ROOT / "strategy_research_schema.py",
    PERSISTENCE_ROOT / "strategy_research_sealed.py",
    PERSISTENCE_ROOT / "strategy_research_sessions.py",
    PERSISTENCE_ROOT / "strategy_research_uow.py",
}
PRODUCTION_PATHS = {
    CONTRACT,
    COMPOSITION,
    BACKTEST_PROJECTION,
    *AI_RUNTIME_PATHS,
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


def test_strategy_research_facade_preserves_contracts_and_test_seams() -> None:
    assert StrategyResearchRejected is CanonicalStrategyResearchRejected
    assert StrategyResearchSelection is CanonicalStrategyResearchSelection
    assert HypothesisGenerationRequest is CanonicalHypothesisGenerationRequest
    assert FormulaBacktestRequest is CanonicalFormulaBacktestRequest
    assert CritiqueRequest is CanonicalCritiqueRequest
    assert StrategyResearchAuditStore is CanonicalStrategyResearchAuditStore
    assert RestrictedFormulaBacktestAdapter is CanonicalRestrictedFormulaBacktestAdapter
    assert StrategyResearchModelProvider is CanonicalStrategyResearchModelProvider
    assert (
        build_backtest_report_metrics_json
        is canonical_build_backtest_report_metrics_json
    )
    assert fill_to_response is canonical_fill_to_response
    assert rolling_oos_parameters is canonical_rolling_oos_parameters
    assert _build_hypothesis_citation_catalog is build_hypothesis_citation_catalog
    assert _compact_hypothesis_citation_catalog is compact_hypothesis_citation_catalog
    assert _citation_path_exists is citation_path_exists

    assert (
        StrategyResearchService.generate_hypotheses
        is StrategyResearchGenerationMixin.generate_hypotheses
    )
    assert (
        StrategyResearchService.run_formula_backtest
        is StrategyResearchBacktestWorkflowMixin.run_formula_backtest
    )
    assert StrategyResearchService.critique is StrategyResearchCritiqueMixin.critique
    assert (
        StrategyResearchService.get_session is StrategyResearchSessionMixin.get_session
    )
    assert str(inspect.signature(StrategyResearchService)) == (
        "(*, db: 'Any', db_path: 'Path', settings: "
        "'ProviderConnectivitySettings | None', capture_service: "
        "'HumanResearchContextCaptureService', evidence_repository: "
        "'CanonicalEvidenceRepository', ai_store: 'AiAuditStore', research_store: "
        "'StrategyResearchAuditStore', data_store: 'DataStore', transport: "
        "'JsonHttpTransport | None' = None, now: 'Callable[[], str] | None' = None, "
        "monotonic: 'Callable[[], float] | None' = None, model_timeout_seconds: "
        "'float' = 180.0, reviewed_fee_schedule_resolver: "
        "'Callable[..., Any] | None' = None, provider_send_admission: "
        "'ProviderSendAdmission | None' = None, execution_guard: "
        "'Callable[[], None] | None' = None) -> 'None'"
    )


def test_strategy_research_sql_has_one_physical_owner() -> None:
    for path in {CONTRACT, COMPOSITION, *AI_RUNTIME_PATHS}:
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(path), path.name
        assert "CREATE TABLE" not in source, path.name
        assert "BEGIN IMMEDIATE" not in source, path.name
        assert "sqlite3.connect(" not in source, path.name

    uow = PERSISTENCE_ROOT / "strategy_research_uow.py"
    source = uow.read_text(encoding="utf-8")
    assert source.count('"BEGIN IMMEDIATE"') == 1
    assert "sqlite3.connect(" in source
    assert {
        path.name
        for path in PERSISTENCE_PATHS
        if "CREATE TABLE" in path.read_text(encoding="utf-8")
    } == {"strategy_research_schema.py"}


def test_strategy_research_layers_do_not_invert_dependencies() -> None:
    for path in {
        CONTRACT,
        BACKTEST_PROJECTION,
        AI_RUNTIME_ROOT / "strategy_research_citations.py",
    }:
        imports = _imports(path)
        assert not {
            item
            for item in imports
            if item.startswith(
                (
                    "server.composition",
                    "server.persistence",
                    "server.routes",
                    "server.services",
                )
            )
        }, path.name

    for path in PERSISTENCE_PATHS:
        imports = _imports(path)
        assert not {
            item
            for item in imports
            if item.startswith(
                ("server.composition", "server.routes", "server.services")
            )
        }, path.name

    for path in AI_RUNTIME_PATHS - {AI_RUNTIME_ROOT / "strategy_research.py"}:
        assert not {
            item for item in _imports(path) if item.startswith("server.routes")
        }, path.name
    assert not {
        item
        for item in _imports(AI_RUNTIME_ROOT / "strategy_research_backtest.py")
        if item.startswith("server.services")
    }


def test_strategy_research_modules_have_no_cross_module_private_imports() -> None:
    for path in PRODUCTION_PATHS:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            assert not {
                alias.name
                for alias in node.names
                if alias.name.startswith("_") and not alias.name.startswith("__")
            }, path.name


def test_strategy_research_modules_and_functions_have_zero_size_debt() -> None:
    assert set(AI_RUNTIME_ROOT.glob("strategy_research*.py")) == AI_RUNTIME_PATHS
    assert set(PERSISTENCE_ROOT.glob("strategy_research*.py")) == PERSISTENCE_PATHS
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


def test_strategy_research_refactor_keeps_server_import_graph_acyclic() -> None:
    paths = sorted((PROJECT_ROOT / "server").rglob("*.py"))
    assert _strongly_connected_components(_server_import_graph(paths)) == []
