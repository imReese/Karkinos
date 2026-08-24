"""Executable ownership constraints for the reviewed fee schedule domain."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from server.services.reviewed_fee_schedule import (
    ReviewedFeeScheduleResolution,
    ReviewedFeeScheduleReviewRepository,
)
from server.services.reviewed_fee_schedule_commission import (
    ReviewedFeeScheduleResolution as CanonicalResolution,
)
from server.services.reviewed_fee_schedule_repository import (
    ReviewedFeeScheduleReviewRepository as CanonicalRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "server/services"
DOMAIN_PATHS = {
    SERVICE_ROOT / "reviewed_fee_schedule.py",
    SERVICE_ROOT / "reviewed_fee_schedule_commission.py",
    SERVICE_ROOT / "reviewed_fee_schedule_policy.py",
    SERVICE_ROOT / "reviewed_fee_schedule_reconciliation.py",
    SERVICE_ROOT / "reviewed_fee_schedule_repository.py",
    SERVICE_ROOT / "reviewed_fee_schedule_workflows.py",
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


def test_reviewed_fee_schedule_modules_and_functions_have_zero_size_debt() -> None:
    assert set(SERVICE_ROOT.glob("reviewed_fee_schedule*.py")) == DOMAIN_PATHS
    violations: list[str] = []
    for path in sorted(DOMAIN_PATHS):
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


def test_reviewed_fee_schedule_facade_preserves_canonical_class_identity() -> None:
    assert ReviewedFeeScheduleResolution is CanonicalResolution
    assert ReviewedFeeScheduleReviewRepository is CanonicalRepository

    facade = SERVICE_ROOT / "reviewed_fee_schedule.py"
    direct_classes = [
        node.name for node in _tree(facade).body if isinstance(node, ast.ClassDef)
    ]
    assert direct_classes == []
    assert len(facade.read_text(encoding="utf-8").splitlines()) <= 160


def test_review_repository_is_the_only_service_adapter_to_review_persistence() -> None:
    persistence_module = "server.persistence.reviewed_fee_schedule_reviews"
    owners = {
        path.name for path in DOMAIN_PATHS if persistence_module in _imports(path)
    }
    assert owners == {"reviewed_fee_schedule_repository.py"}

    for path in DOMAIN_PATHS:
        source = path.read_text(encoding="utf-8")
        assert "sqlite3" not in _imports(path)
        assert "BEGIN IMMEDIATE" not in source


def test_facade_injects_patchable_account_truth_dependencies() -> None:
    tree = _tree(SERVICE_ROOT / "reviewed_fee_schedule.py")
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    expected = {
        "build_reviewed_fee_schedule_preview",
        "build_reviewed_fee_schedule_review_status",
        "resolve_reviewed_fee_schedule",
    }
    assert set(functions) == expected

    for function in functions.values():
        names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
        assert "build_account_truth_evidence_readiness" in names
        assert "build_latest_account_truth_promotion_evidence" in names
