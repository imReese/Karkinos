"""Executable boundaries for extracted service and persistence helpers."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_MODULES = (
    "analytics/strategy_advancement_evidence.py",
    "analytics/strategy_advancement_gate.py",
    "account_truth/broker_adapter_release.py",
    "account_truth/broker_adapter_release_manifest.py",
    "account_truth/broker_execution_edge_conformance.py",
    "account_truth/broker_execution_edge_values.py",
    "account_truth/citic_source_scope_review.py",
    "account_truth/citic_source_scope_values.py",
    "data/market_daily_store.py",
    "data/market_calendar.py",
    "data/market_calendar_values.py",
    "data/providers/akshare_open_end_funds.py",
    "data/providers/akshare_source.py",
    "data/providers/akshare_support.py",
    "data/store.py",
    "server/ai_runtime/task_schema.py",
    "server/ai_runtime/analysis_review_schema.py",
    "server/ai_runtime/analysis_reviews.py",
    "server/ai_runtime/task_analysis.py",
    "server/ai_runtime/task_analysis_fixture.py",
    "server/ai_runtime/tasks.py",
    "server/services/paper_shadow_contracts.py",
    "server/services/paper_shadow_execution.py",
    "server/services/paper_shadow_review.py",
    "server/services/paper_shadow_run.py",
    "server/services/paper_shadow_values.py",
    "server/persistence/controlled_ledger_posting_uow.py",
    "server/services/account_truth_evidence_readiness.py",
    "server/services/account_truth_evidence_readiness_support.py",
    "server/services/account_truth_evidence_scope.py",
    "server/services/capital_scaling_evidence_contracts.py",
    "server/services/capital_scaling_evidence_values.py",
    "server/services/capital_scaling_execution_facts.py",
    "server/services/capital_scaling_financial_facts.py",
    "server/services/capital_scaling_evidence_window.py",
    "server/account_truth_gate.py",
    "server/account_truth_gate_support.py",
    "server/account_truth_gate_values.py",
    "server/services/automation_alerts.py",
    "server/services/automation_alert_support.py",
    "server/services/controlled_session_live_gates.py",
    "server/services/controlled_session_live_gate_values.py",
    "server/services/controlled_submission_ledger_posting.py",
    "server/services/controlled_submission_ledger_posting_support.py",
    "server/services/daily_candidate_production_readiness.py",
    "server/services/daily_candidate_readiness_support.py",
    "server/services/daily_trading_plan.py",
    "server/services/daily_trading_plan_support.py",
    "server/services/market_refresh.py",
    "server/services/market_refresh_errors.py",
    "server/services/operator_approval.py",
    "server/services/operator_approval_contracts.py",
    "server/services/strategy_promotion_pipeline.py",
    "server/services/strategy_promotion_support.py",
)
PURE_MODULES = (
    "server/services/account_truth_evidence_readiness_support.py",
    "server/account_truth_gate_support.py",
    "server/account_truth_gate_values.py",
    "server/services/automation_alert_support.py",
    "server/services/controlled_session_live_gate_values.py",
    "server/services/controlled_submission_ledger_posting_support.py",
    "server/services/daily_candidate_readiness_support.py",
    "server/services/daily_trading_plan_support.py",
    "server/services/market_refresh_errors.py",
    "server/services/operator_approval_contracts.py",
    "server/persistence/database_normalization.py",
    "data/market_calendar_values.py",
    "data/providers/akshare_support.py",
    "account_truth/broker_execution_edge_values.py",
    "account_truth/citic_source_scope_values.py",
    "server/ai_runtime/task_schema.py",
    "server/ai_runtime/analysis_review_schema.py",
)

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


def test_extracted_service_modules_remain_bounded() -> None:
    violations: list[str] = []
    for relative_path in SERVICE_MODULES:
        path = PROJECT_ROOT / relative_path
        source = path.read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{relative_path}: module exceeds 800 lines")
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = (node.end_lineno or node.lineno) - node.lineno + 1
                if size > 350:
                    violations.append(
                        f"{relative_path}:{node.lineno} {node.name} exceeds 350 lines"
                    )

    assert violations == []


def test_pure_support_modules_do_not_own_runtime_or_database_dependencies() -> None:
    violations: dict[str, list[str]] = {}
    forbidden = ("sqlite3", "server.db", "server.routes", "server.services")
    for relative_path in PURE_MODULES:
        path = PROJECT_ROOT / relative_path
        imported = sorted(
            dependency
            for dependency in _imports(path)
            if any(
                dependency == prefix or dependency.startswith(f"{prefix}.")
                for prefix in forbidden
            )
        )
        if imported:
            violations[relative_path] = imported

    assert violations == {}
