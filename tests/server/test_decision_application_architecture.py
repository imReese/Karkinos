"""Executable architecture boundaries for the Decision application family."""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from server.services import decision_application
from server.services.strategy_promotion_pipeline import (
    resolve_strategy_order_generation_gate as canonical_order_generation_gate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "server/services"
DECISION_MODULES = {
    SERVICE_ROOT / "decision_action_application.py",
    SERVICE_ROOT / "decision_application.py",
    SERVICE_ROOT / "decision_candidate_projection.py",
    SERVICE_ROOT / "decision_contracts.py",
    SERVICE_ROOT / "decision_gate_evidence.py",
    SERVICE_ROOT / "decision_portfolio_projection.py",
    SERVICE_ROOT / "decision_projection.py",
    SERVICE_ROOT / "decision_workflow_projection.py",
}
PUBLIC_SIGNATURES = {
    "run_batch_pre_trade_risk_for_state": "(state: 'Any') -> 'dict[str, Any]'",
    "intraday_decision_payload": "(state: 'Any') -> 'dict[str, Any]'",
    "today_decision_payload": (
        "(state: 'Any', *, portfolio_context: 'dict[str, Any] | None' = None) "
        "-> 'dict[str, Any]'"
    ),
    "trading_plan_positions": (
        "(state: 'Any', *, portfolio_context: 'dict[str, Any] | None' = None) "
        "-> 'dict[str, Any]'"
    ),
    "decision_portfolio_context": "(state: 'Any') -> 'dict[str, Any]'",
    "account_truth_gate_evidence": "(state: 'Any') -> 'dict[str, Any]'",
    "action_trade_date": "(action: 'dict[str, Any]') -> 'str | None'",
    "data_freshness_evidence": (
        "(action: 'dict[str, Any]', db: 'Any', *, quotes: "
        "'dict[str, dict[str, Any]]', allow_direct_quote_fallback: 'bool') "
        "-> 'dict[str, Any]'"
    ),
    "paper_shadow_evidence": (
        "(action: 'dict[str, Any]', manual_confirmation_status: 'str', *, "
        "db: 'Any') -> 'dict[str, Any]'"
    ),
    "paper_shadow_allows_manual_ticket": ("(evidence: 'dict[str, Any]') -> 'bool'"),
    "latest_quote_timestamp": "(quotes: 'Any') -> 'str | None'",
    "strategy_attribution_gate_evidence": (
        "(state: 'Any', db: 'Any', actions: 'list[dict[str, Any]]') "
        "-> 'dict[str, Any]'"
    ),
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


def _family_dependencies(path: Path) -> set[str]:
    modules = {item.stem for item in DECISION_MODULES}
    dependencies: set[str] = set()
    for imported in _imports(path):
        if not imported.startswith("server.services.decision_"):
            continue
        name = imported.removeprefix("server.services.").split(".", maxsplit=1)[0]
        if name in modules:
            dependencies.add(name)
    return dependencies


def _called_names(path: Path) -> set[str]:
    called: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    return called


def test_decision_facade_preserves_public_contract_and_identity() -> None:
    for name, expected_signature in PUBLIC_SIGNATURES.items():
        value = getattr(decision_application, name)
        assert value.__module__ == "server.services.decision_application", name
        assert str(inspect.signature(value)) == expected_signature, name
    assert (
        decision_application.resolve_strategy_order_generation_gate
        is canonical_order_generation_gate
    )


def test_decision_facade_keeps_patchable_composition_seams(monkeypatch) -> None:
    sentinel = lambda *_args, **_kwargs: {"sentinel": True}
    monkeypatch.setattr(
        decision_application,
        "_account_truth_gate_evidence",
        sentinel,
    )
    monkeypatch.setattr(
        decision_application,
        "_decision_portfolio_context",
        sentinel,
    )
    ports = decision_application._projection_ports()
    assert ports.account_truth_evidence is sentinel
    assert ports.portfolio_context is sentinel
    assert decision_application.account_truth_gate_evidence(object()) == {
        "sentinel": True
    }
    assert decision_application.decision_portfolio_context(object()) == {
        "sentinel": True
    }


def test_decision_family_has_zero_size_debt() -> None:
    violations: list[str] = []
    for path in sorted(DECISION_MODULES):
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


def test_decision_family_has_no_cross_module_private_imports() -> None:
    violations: list[str] = []
    for path in sorted(DECISION_MODULES):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    violations.append(f"{path.name}:{node.module}.{alias.name}")
    assert violations == []


def test_decision_family_owns_no_sql_http_or_persistence_dependency() -> None:
    violations: list[str] = []
    sql = re.compile(r"\b(?:BEGIN|SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE)\b", re.I)
    for path in sorted(DECISION_MODULES):
        imports = _imports(path)
        forbidden_imports = sorted(
            dependency
            for dependency in imports
            if dependency == "sqlite3"
            or dependency == "server.routes"
            or dependency.startswith("server.routes.")
            or dependency == "server.persistence"
            or dependency.startswith("server.persistence.")
        )
        if forbidden_imports:
            violations.append(f"{path.name}:imports:{forbidden_imports}")
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if sql.search(node.value):
                    violations.append(f"{path.name}:sql:{node.lineno}")
    assert violations == []


def test_decision_family_import_graph_is_acyclic() -> None:
    modules = {path.stem: path for path in DECISION_MODULES}
    graph = {
        name: {
            dependency
            for dependency in _family_dependencies(path)
            if dependency in modules
        }
        for name, path in modules.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        assert name not in visiting, f"Decision import cycle at {name}"
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for module in graph:
        visit(module)


def test_decision_family_cannot_submit_cancel_or_mutate_financial_facts() -> None:
    forbidden_calls = {
        "submit",
        "submit_order",
        "cancel",
        "cancel_order",
        "save_manual_order_sync",
        "record_order_sync",
        "record_fill_sync",
        "insert_ledger_entry_sync",
        "post_ledger",
    }
    violations = {
        path.name: sorted(_called_names(path) & forbidden_calls)
        for path in DECISION_MODULES
        if _called_names(path) & forbidden_calls
    }
    assert violations == {}
