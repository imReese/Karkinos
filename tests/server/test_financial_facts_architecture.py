"""Executable ownership boundaries for canonical financial facts."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from server import db as db_module
from server.persistence.facades import base as facade_base
from server.persistence.financial_facts import FinancialFactsRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"
FINANCIAL_FACT_MODULES = tuple(sorted(PERSISTENCE_ROOT.glob("financial_facts*.py")))
CAPABILITY_METHODS = {
    "financial_facts_valuation.py": {
        "get_valuation_snapshot_sync",
        "publish_current_valuation_snapshot_sync",
        "save_valuation_snapshot_sync",
    },
    "financial_facts_quote_runs.py": {
        "create_quote_fetch_run",
        "finish_quote_fetch_run",
        "get_quote_fetch_run",
        "list_quote_fetch_runs",
    },
    "financial_facts_quotes.py": {
        "get_latest_daily_close_before_sync",
        "get_latest_market_bar_before_date_sync",
        "get_latest_quote",
        "get_latest_quote_before_date_sync",
        "get_latest_quote_sync",
        "get_latest_quotes_sync",
        "get_market_bar_on_date_sync",
        "get_recent_quote_snapshots_sync",
        "list_latest_quotes_sync",
        "list_quote_selection_candidates_sync",
        "list_quote_snapshots_sync",
        "save_daily_close_snapshot_sync",
        "save_quote_snapshot_sync",
        "upsert_latest_quote_sync",
    },
    "financial_facts_portfolio.py": {
        "confirm_pending_fund_order_sync",
        "correct_cash_flow_sync",
        "correct_manual_trade_sync",
        "create_pending_fund_order_sync",
        "get_cash_flows",
        "get_cash_flows_sync",
        "get_pending_fund_orders_sync",
        "get_total_deposits",
        "get_total_deposits_sync",
        "get_trades",
        "get_trades_sync",
        "record_cash_flow_sync",
        "record_manual_trade_sync",
        "save_portfolio_snapshot_sync",
    },
    "financial_facts_ledger.py": {
        "append_ledger_entry_sync",
        "confirm_ledger_trade_settlement_sync",
        "get_ledger_entries_sync",
        "get_ledger_entry_sync",
        "insert_ledger_entry_sync",
        "settle_ledger_trade_sync",
    },
    "financial_facts_quote_ingestion_uow.py": {
        "persist_quote_ingestion_sync",
        "publish_quote_fetch_run_sync",
        "staged_quote_ingestions_sync",
    },
}
PUBLIC_METHODS = set().union(*CAPABILITY_METHODS.values())

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


def _public_methods(path: Path) -> set[str]:
    methods: set[str] = set()
    for node in _tree(path).body:
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        methods.update(
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not child.name.startswith("_")
        )
    return methods


def test_financial_fact_modules_are_bounded_and_do_not_reverse_depend() -> None:
    assert {path.name for path in FINANCIAL_FACT_MODULES} == {
        "financial_facts.py",
        "financial_facts_ledger.py",
        "financial_facts_portfolio.py",
        "financial_facts_quote_ingestion_uow.py",
        "financial_facts_quote_runs.py",
        "financial_facts_quotes.py",
        "financial_facts_valuation.py",
        "financial_facts_valuation_composition.py",
    }
    projection_importers: set[str] = set()
    for path in FINANCIAL_FACT_MODULES:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 800, path.name
        imports = _imports(path)
        assert not {
            imported
            for imported in imports
            if imported == "server.services"
            or imported.startswith("server.services.")
            or imported == "server.routes"
            or imported.startswith("server.routes.")
        }, path.name
        if any(imported.startswith("server.projections.") for imported in imports):
            projection_importers.add(path.name)
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno is not None
                assert node.end_lineno - node.lineno + 1 <= 350, (
                    path.name,
                    node.name,
                )
    assert projection_importers == {"financial_facts_valuation_composition.py"}


def test_projection_dependency_is_isolated_to_a_lazy_composition_seam() -> None:
    path = PERSISTENCE_ROOT / "financial_facts_valuation_composition.py"
    tree = _tree(path)
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            isinstance(node, ast.ImportFrom)
            and str(node.module).startswith("server.projections.")
        )
        for node in tree.body
    )
    projection_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "server.projections.valuation_snapshot"
    ]
    assert len(projection_imports) == 1


def test_each_financial_concept_has_one_canonical_method_owner() -> None:
    actual = {
        path.name: _public_methods(path)
        for path in FINANCIAL_FACT_MODULES
        if _public_methods(path)
    }
    assert actual == CAPABILITY_METHODS
    owners: dict[str, str] = {}
    for module_name, methods in actual.items():
        for method in methods:
            assert method not in owners, method
            owners[method] = module_name
    assert set(owners) == PUBLIC_METHODS


def test_public_repository_identity_constructor_and_surface_remain_stable() -> None:
    assert FinancialFactsRepository.__module__ == "server.persistence.financial_facts"
    assert db_module.FinancialFactsRepository is FinancialFactsRepository
    assert facade_base.FinancialFactsRepository is FinancialFactsRepository

    parameters = inspect.signature(FinancialFactsRepository).parameters
    assert list(parameters) == [
        "database_path",
        "runtime_controls",
        "valuation_publisher",
        "now",
    ]
    assert parameters["database_path"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        for name in ("runtime_controls", "valuation_publisher", "now")
    )
    assert parameters["now"].default is None

    surface = {
        name
        for name, value in inspect.getmembers(
            FinancialFactsRepository, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert surface == PUBLIC_METHODS


def test_public_module_is_composition_only() -> None:
    path = PERSISTENCE_ROOT / "financial_facts.py"
    tree = _tree(path)
    repository = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FinancialFactsRepository"
    )
    methods = [
        node.name
        for node in repository.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert methods == ["__init__"]
    assert "sqlite3" not in _imports(path)
    assert "conn.execute" not in path.read_text(encoding="utf-8")
