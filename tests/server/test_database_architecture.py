"""Executable ownership constraints for the application database boundary."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from server.db import AppDatabase

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

    database_methods = {
        name
        for name, value in inspect.getmembers(AppDatabase, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert database_methods == {*method_owners, "init", "init_sync"}


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


def test_persistence_helpers_have_domain_owners_instead_of_a_catch_all() -> None:
    forbidden_module = PERSISTENCE_ROOT / "database_support.py"
    assert not forbidden_module.exists()

    offenders: list[str] = []
    for path in sorted((PROJECT_ROOT / "server").rglob("*.py")):
        for imported in _module_imports(path):
            if imported == "server.persistence.database_support":
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []

    owned_helpers = {
        "controlled_clearance_lifecycle.py",
        "controlled_execution_rejections.py",
        "controlled_ledger_validation.py",
        "controlled_session_rejections.py",
        "database_normalization.py",
        "database_serialization.py",
        "financial_fact_event_payloads.py",
        "signal_journal_projection.py",
    }
    assert all(
        len((PERSISTENCE_ROOT / name).read_text(encoding="utf-8").splitlines()) <= 250
        for name in owned_helpers
    )


def test_unit_of_work_boundaries_remain_explicit() -> None:
    expected = {
        "ai_shadow_research_uow.py": 1,
        "analysis_reviews.py": 1,
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
        "execution_fact_uow.py": 2,
        "external_analysis_review_uow.py": 1,
        "external_memory_analysis.py": 1,
        "external_promoted_memory_analysis.py": 1,
        "external_promoted_analysis_memory_retrieval_uow.py": 1,
        "external_promoted_analysis_memory_uow.py": 2,
        "external_promoted_memory_analysis_review_uow.py": 1,
        "external_research_uow.py": 1,
        "external_reviewed_memory_retrieval_uow.py": 1,
        "external_reviewed_memory_uow.py": 2,
        "financial_facts_quote_ingestion_uow.py": 2,
        "financial_facts_quote_runs.py": 1,
        "financial_facts_valuation.py": 1,
        "ledger_mutation_uow.py": 2,
        "legacy_fund_trade_duplicate_repair.py": 1,
        "manual_order_ticket_uow.py": 2,
        "manual_trade_uow.py": 2,
        "market_calendar.py": 2,
        "market_calendar_publication_uow.py": 1,
        "memory_informed_analysis_uow.py": 2,
        "memory_retrieval_uow.py": 1,
        "migrations.py": 1,
        "oms.py": 2,
        "paper_shadow_run_uow.py": 1,
        "pending_fund_confirmation_uow.py": 2,
        "portfolio_cash_flow_uow.py": 2,
        "pre_trade_risk_uow.py": 1,
        "reviewed_fee_schedule_reviews.py": 1,
        "runtime_controls.py": 1,
        "strategy_research_uow.py": 1,
    }
    actual = {
        path.name: path.read_text(encoding="utf-8").count('"BEGIN IMMEDIATE"')
        for path in PERSISTENCE_ROOT.glob("*.py")
        if '"BEGIN IMMEDIATE"' in path.read_text(encoding="utf-8")
    }

    assert actual == expected
