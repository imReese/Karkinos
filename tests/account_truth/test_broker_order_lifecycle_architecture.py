"""Executable architecture boundaries for broker lifecycle evidence."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from account_truth import broker_order_lifecycle as lifecycle
from account_truth import broker_order_lifecycle_collector as collector

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "account_truth/broker_order_lifecycle.py",
    "account_truth/broker_order_lifecycle_contracts.py",
    "account_truth/broker_order_lifecycle_preview.py",
    "account_truth/broker_order_lifecycle_projection.py",
    "account_truth/broker_order_lifecycle_repository.py",
    "account_truth/broker_order_lifecycle_schema.py",
    "account_truth/broker_order_lifecycle_uow.py",
    "account_truth/broker_order_lifecycle_values.py",
    "account_truth/broker_order_lifecycle_collector.py",
    "account_truth/broker_order_lifecycle_collector_contracts.py",
    "account_truth/broker_order_lifecycle_collector_preview.py",
    "account_truth/broker_order_lifecycle_collector_projection.py",
    "account_truth/broker_order_lifecycle_collector_repository.py",
    "account_truth/broker_order_lifecycle_collector_schema.py",
    "account_truth/broker_order_lifecycle_collector_uow.py",
    "account_truth/broker_order_lifecycle_collector_values.py",
)
WRITE_MODULES = {
    "account_truth/broker_order_lifecycle_schema.py",
    "account_truth/broker_order_lifecycle_uow.py",
    "account_truth/broker_order_lifecycle_collector_schema.py",
    "account_truth/broker_order_lifecycle_collector_uow.py",
}

pytestmark = pytest.mark.unit


def _path(relative_path: str) -> Path:
    return PROJECT_ROOT / relative_path


def _tree(relative_path: str) -> ast.Module:
    path = _path(relative_path)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_architecture_inventory_covers_every_lifecycle_module() -> None:
    discovered = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "account_truth").glob("broker_order_lifecycle*.py")
    }

    assert discovered == set(MODULES)


def test_lifecycle_modules_and_functions_remain_bounded() -> None:
    violations: list[str] = []
    for relative_path in MODULES:
        source = _path(relative_path).read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{relative_path}: module exceeds 800 lines")
        for node in ast.walk(_tree(relative_path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(
                    f"{relative_path}:{node.lineno} {node.name} exceeds 350 lines"
                )

    assert violations == []


def test_public_facades_keep_type_identity_and_call_contracts() -> None:
    assert lifecycle.BrokerOrderLifecycleEvidenceRejected.__module__ == (
        "account_truth.broker_order_lifecycle"
    )
    assert lifecycle.BrokerOrderLifecycleEvidenceRepository.__module__ == (
        "account_truth.broker_order_lifecycle"
    )
    assert collector.BrokerOrderLifecycleCollectorRejected.__module__ == (
        "account_truth.broker_order_lifecycle_collector"
    )
    assert collector.BrokerOrderLifecycleCollectorRepository.__module__ == (
        "account_truth.broker_order_lifecycle_collector"
    )
    assert tuple(
        inspect.signature(lifecycle.preview_broker_order_lifecycle_export).parameters
    ) == ("content", "source_name", "max_snapshot_age_seconds", "clock")
    assert tuple(
        inspect.signature(
            collector.preview_broker_order_lifecycle_collector_batch
        ).parameters
    ) == ("content", "source_name", "max_snapshot_age_seconds", "clock")
    assert tuple(
        inspect.signature(
            lifecycle.BrokerOrderLifecycleEvidenceRepository.record
        ).parameters
    ) == ("self", "preview", "acknowledgement")
    assert tuple(
        inspect.signature(
            collector.BrokerOrderLifecycleCollectorRepository.prepare
        ).parameters
    ) == ("self", "preview", "acknowledgement")


def test_cross_module_imports_use_public_seams() -> None:
    violations: list[str] = []
    for relative_path in MODULES:
        for node in ast.walk(_tree(relative_path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("account_truth.broker_order_lifecycle"):
                continue
            for imported in node.names:
                if imported.name.startswith("_"):
                    violations.append(
                        f"{relative_path}:{node.lineno} imports {imported.name}"
                    )

    assert violations == []


def test_sqlite_mutation_is_owned_only_by_schema_and_units_of_work() -> None:
    mutation_tokens = ("INSERT INTO", "UPDATE ", "DELETE FROM", "BEGIN IMMEDIATE")
    violations: list[str] = []
    for relative_path in MODULES:
        source = _path(relative_path).read_text(encoding="utf-8")
        if relative_path not in WRITE_MODULES and any(
            token in source for token in mutation_tokens
        ):
            violations.append(relative_path)

    assert violations == []
    lifecycle_uow = _path("account_truth/broker_order_lifecycle_uow.py").read_text(
        encoding="utf-8"
    )
    collector_uow = _path(
        "account_truth/broker_order_lifecycle_collector_uow.py"
    ).read_text(encoding="utf-8")
    assert lifecycle_uow.count('conn.execute("BEGIN IMMEDIATE")') == 1
    assert collector_uow.count('conn.execute("BEGIN IMMEDIATE")') == 2
    assert "prepared_preview_json" in collector_uow
    assert "broker_order_lifecycle_collector_state" in collector_uow


def test_contract_normalization_and_preview_layers_are_provider_free() -> None:
    pure_paths = (
        "account_truth/broker_order_lifecycle_contracts.py",
        "account_truth/broker_order_lifecycle_values.py",
        "account_truth/broker_order_lifecycle_preview.py",
        "account_truth/broker_order_lifecycle_collector_contracts.py",
        "account_truth/broker_order_lifecycle_collector_values.py",
        "account_truth/broker_order_lifecycle_collector_preview.py",
    )
    forbidden_imports = ("sqlite3", "server", "requests", "httpx")
    violations: dict[str, list[str]] = {}
    for relative_path in pure_paths:
        imported: list[str] = []
        for node in ast.walk(_tree(relative_path)):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        forbidden = sorted(
            dependency
            for dependency in imported
            if any(
                dependency == prefix or dependency.startswith(f"{prefix}.")
                for prefix in forbidden_imports
            )
        )
        if forbidden:
            violations[relative_path] = forbidden

    assert violations == {}
