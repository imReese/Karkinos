"""Regression gates for the reviewed service architecture-debt closure."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVIEWED_MODULES = (
    "server/services/promoted_strategy_universe_scan.py",
    "server/services/promoted_strategy_universe_scan_persistence.py",
    "server/services/promoted_strategy_universe_scan_support.py",
    "server/services/broker_connector_soak_promotion.py",
    "server/services/broker_connector_soak_promotion_evidence.py",
    "server/services/broker_connector_soak_promotion_values.py",
    "server/services/capital_scaling_execution_facts.py",
    "server/services/capital_scaling_capacity_fact.py",
    "server/services/capital_scaling_operating_sample_fact.py",
    "server/services/capital_scaling_execution_scope_fact.py",
)

pytestmark = pytest.mark.unit


def test_reviewed_service_modules_and_functions_remain_bounded() -> None:
    violations: list[str] = []
    for relative in REVIEWED_MODULES:
        path = PROJECT_ROOT / relative
        source = path.read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        if line_count > 600:
            violations.append(f"{relative}:module:{line_count}")
        tree = ast.parse(source, filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if function_lines > 200:
                violations.append(
                    f"{relative}:{node.name}:{node.lineno}:{function_lines}"
                )
    assert violations == []


def test_reviewed_service_modules_do_not_import_private_symbols() -> None:
    violations: list[str] = []
    for relative in REVIEWED_MODULES:
        path = PROJECT_ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    violations.append(
                        f"{relative}:{node.lineno}:{node.module}.{alias.name}"
                    )
    assert violations == []
