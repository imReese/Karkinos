from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import analytics.acceptance as acceptance
import analytics.acceptance_audit as compatibility_facade
from analytics.acceptance_audit_report import (
    AUDIT_REGISTRY,
    build_acceptance_audit_export,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_PACKAGE = PROJECT_ROOT / "analytics/acceptance"
ACCEPTANCE_SOURCES = (
    PROJECT_ROOT / "analytics/acceptance_audit.py",
    PROJECT_ROOT / "analytics/acceptance_audit_report.py",
    PROJECT_ROOT / "analytics/acceptance_audit_verification.py",
    *sorted(ACCEPTANCE_PACKAGE.glob("*.py")),
)
EXPECTED_ALL_AUDITS_SHA256 = (
    "c3942b52e22206bf1d2472c6ae0318b6e25841b2a892cf94a68b2aebcf0e56f7"
)


def _source_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_compatibility_facade_reexports_the_package_api() -> None:
    assert compatibility_facade.__all__ == acceptance.__all__
    assert {
        name: getattr(compatibility_facade, name)
        for name in compatibility_facade.__all__
    } == {name: getattr(acceptance, name) for name in acceptance.__all__}

    facade_definitions = [
        node.name
        for node in _source_tree(PROJECT_ROOT / "analytics/acceptance_audit.py").body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert facade_definitions == []


def test_all_acceptance_manifest_output_is_byte_stable() -> None:
    payload = build_acceptance_audit_export(
        selected_audit="all",
        generated_at="2000-01-01T00:00:00Z",
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()

    assert len(AUDIT_REGISTRY) == 40
    assert sum(audit["required_count"] for audit in payload["audits"]) == 397
    assert hashlib.sha256(encoded).hexdigest() == EXPECTED_ALL_AUDITS_SHA256


def test_acceptance_modules_and_functions_stay_within_reviewable_limits() -> None:
    oversized_modules = {
        path.relative_to(PROJECT_ROOT).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in ACCEPTANCE_SOURCES
        if len(path.read_text(encoding="utf-8").splitlines()) > 800
    }
    oversized_functions: dict[str, int] = {}
    for path in ACCEPTANCE_SOURCES:
        for node in ast.walk(_source_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assert node.end_lineno is not None
            size = node.end_lineno - node.lineno + 1
            if size > 350:
                name = f"{path.relative_to(PROJECT_ROOT).as_posix()}::{node.name}"
                oversized_functions[name] = size

    assert oversized_modules == {}
    assert oversized_functions == {}


def test_manifest_modules_are_data_only_and_do_not_depend_on_each_other() -> None:
    violations: list[str] = []
    for path in sorted(ACCEPTANCE_PACKAGE.glob("*.py")):
        if path.name in {"__init__.py", "models.py"}:
            continue
        for node in _source_tree(path).body:
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{path.name} imports {alias.name}" for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module not in {
                "__future__",
                "analytics.acceptance.models",
            }:
                violations.append(f"{path.name} imports {node.module}")

    assert violations == []
