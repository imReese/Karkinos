"""Executable architecture boundaries for the CITIC source evidence stores."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from account_truth import citic_source_canonical_resolution as canonical
from account_truth import citic_source_intake as intake
from account_truth import citic_source_query_window_review as query_window
from account_truth import citic_source_scope_review as scope

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAMILIES = (
    "citic_source_intake",
    "citic_source_canonical_resolution",
    "citic_source_query_window_review",
    "citic_source_scope_review",
)
LAYERS = (
    "",
    "_contracts",
    "_projection",
    "_repository",
    "_schema",
    "_uow",
    "_values",
)
MODULES = tuple(
    f"account_truth/{family}{layer}.py"
    for family in FAMILIES
    for layer in LAYERS
    if not (family == "citic_source_scope_review" and layer == "_values")
) + ("account_truth/citic_source_scope_values.py",)
FACADES = tuple(f"account_truth/{family}.py" for family in FAMILIES)
SCHEMA_MODULES = tuple(f"account_truth/{family}_schema.py" for family in FAMILIES)
UOW_MODULES = tuple(f"account_truth/{family}_uow.py" for family in FAMILIES)
REPOSITORY_MODULES = tuple(
    f"account_truth/{family}_repository.py" for family in FAMILIES
)

pytestmark = pytest.mark.unit


def _path(relative_path: str) -> Path:
    return PROJECT_ROOT / relative_path


def _tree(relative_path: str) -> ast.Module:
    path = _path(relative_path)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_architecture_inventory_covers_every_citic_source_persistence_module() -> None:
    discovered = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for family in FAMILIES
        for path in (PROJECT_ROOT / "account_truth").glob(f"{family}*.py")
    }
    discovered.add("account_truth/citic_source_scope_values.py")

    assert discovered == set(MODULES)


def test_citic_source_modules_and_functions_remain_bounded() -> None:
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
    expected_modules = {
        intake.CiticSourceIntake: "account_truth.citic_source_intake",
        intake.CiticSourceIntakeRejected: "account_truth.citic_source_intake",
        intake.CiticSourceIntakeReadRejected: "account_truth.citic_source_intake",
        intake.CiticSourceIntakeRepository: "account_truth.citic_source_intake",
        canonical.CiticSourceCanonicalResolution: (
            "account_truth.citic_source_canonical_resolution"
        ),
        canonical.CiticSourceCanonicalResolutionRejected: (
            "account_truth.citic_source_canonical_resolution"
        ),
        canonical.CiticSourceCanonicalResolutionReadRejected: (
            "account_truth.citic_source_canonical_resolution"
        ),
        canonical.CiticSourceCanonicalResolutionRepository: (
            "account_truth.citic_source_canonical_resolution"
        ),
        query_window.CiticSourceQueryWindowReview: (
            "account_truth.citic_source_query_window_review"
        ),
        query_window.CiticSourceQueryWindowReviewRejected: (
            "account_truth.citic_source_query_window_review"
        ),
        query_window.CiticSourceQueryWindowReviewReadRejected: (
            "account_truth.citic_source_query_window_review"
        ),
        query_window.CiticSourceQueryWindowReviewRepository: (
            "account_truth.citic_source_query_window_review"
        ),
        scope.CiticSourceScopeReview: "account_truth.citic_source_scope_review",
        scope.CiticSourceScopeReviewRejected: (
            "account_truth.citic_source_scope_review"
        ),
        scope.CiticSourceScopeReviewReadRejected: (
            "account_truth.citic_source_scope_review"
        ),
        scope.CiticSourceScopeReviewRepository: (
            "account_truth.citic_source_scope_review"
        ),
    }
    assert {type_: type_.__module__ for type_ in expected_modules} == expected_modules

    assert tuple(
        inspect.signature(intake.CiticSourceIntakeRepository.record_review).parameters
    ) == (
        "self",
        "preview",
        "expected_file_fingerprint",
        "review_status",
        "reviewer",
    )
    assert tuple(
        inspect.signature(
            canonical.CiticSourceCanonicalResolutionRepository.record_resolution
        ).parameters
    ) == (
        "self",
        "source_preview_fingerprints",
        "expected_source_set_fingerprint",
        "scope_review_id",
        "scope_review_import_run_id",
        "scope_review_fingerprint",
        "reviewer",
    )
    assert tuple(
        inspect.signature(
            query_window.CiticSourceQueryWindowReviewRepository.record_review
        ).parameters
    ) == (
        "self",
        "preview",
        "expected_file_fingerprint",
        "expected_source_preview_fingerprint",
        "query_start_date",
        "query_end_date",
        "query_window_attested",
        "reviewer",
    )
    assert tuple(
        inspect.signature(
            scope.CiticSourceScopeReviewRepository.record_review
        ).parameters
    ) == (
        "self",
        "intake_id",
        "expected_file_fingerprint",
        "expected_source_preview_fingerprint",
        "expected_query_window_review_id",
        "expected_query_window_review_fingerprint",
        "account_alias",
        "account_reference_hash",
        "account_type",
        "market_scopes",
        "asset_classes",
        "account_value_band",
        "business_types",
        "no_other_filters_attested",
        "complete_returned_results_attested",
        "source_scope_attested",
        "reviewer",
    )


def test_cross_store_collaborator_monkeypatch_seams_remain_live(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intake_sentinel = object()
    query_window_sentinel = object()
    monkeypatch.setattr(
        query_window,
        "CiticSourceIntakeRepository",
        lambda _path: intake_sentinel,
    )
    query_repository = query_window.CiticSourceQueryWindowReviewRepository(
        tmp_path / "query.db"
    )
    assert query_repository._intake_repository() is intake_sentinel

    monkeypatch.setattr(
        scope,
        "CiticSourceIntakeRepository",
        lambda _path: intake_sentinel,
    )
    monkeypatch.setattr(
        scope,
        "CiticSourceQueryWindowReviewRepository",
        lambda _path: query_window_sentinel,
    )
    scope_repository = scope.CiticSourceScopeReviewRepository(tmp_path / "scope.db")
    assert scope_repository._intake_repository() is intake_sentinel
    assert scope_repository._query_window_repository() is query_window_sentinel


def test_business_facades_are_free_of_sqlite_and_sql() -> None:
    sql_tokens = (
        "SELECT ",
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "CREATE TABLE",
        "ALTER TABLE",
        "BEGIN IMMEDIATE",
        "PRAGMA ",
    )
    violations: list[str] = []
    for relative_path in FACADES:
        source = _path(relative_path).read_text(encoding="utf-8")
        imported = {
            alias.name
            for node in ast.walk(_tree(relative_path))
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        if "sqlite3" in imported or any(token in source for token in sql_tokens):
            violations.append(relative_path)

    assert violations == []


def test_sql_schema_and_transactions_have_explicit_owners() -> None:
    allowed_sql_modules = set(SCHEMA_MODULES + UOW_MODULES + REPOSITORY_MODULES)
    sql_tokens = ("SELECT ", "INSERT INTO", "CREATE TABLE", "ALTER TABLE", "PRAGMA ")
    mutation_tokens = ("INSERT INTO", "UPDATE ", "DELETE FROM", "BEGIN IMMEDIATE")
    ddl_tokens = ("CREATE TABLE", "ALTER TABLE")
    violations: list[str] = []
    for relative_path in MODULES:
        source = _path(relative_path).read_text(encoding="utf-8")
        if relative_path not in allowed_sql_modules and any(
            token in source for token in sql_tokens
        ):
            violations.append(f"{relative_path}: SQL outside persistence owner")
        if relative_path not in UOW_MODULES and any(
            token in source for token in mutation_tokens
        ):
            violations.append(f"{relative_path}: mutation outside UoW")
        if relative_path not in SCHEMA_MODULES and any(
            token in source for token in ddl_tokens
        ):
            violations.append(f"{relative_path}: DDL outside schema")

    assert violations == []
    expected_begin_counts = {
        "account_truth/citic_source_intake_uow.py": 1,
        "account_truth/citic_source_canonical_resolution_uow.py": 2,
        "account_truth/citic_source_query_window_review_uow.py": 2,
        "account_truth/citic_source_scope_review_uow.py": 2,
    }
    assert {
        relative_path: _path(relative_path)
        .read_text(encoding="utf-8")
        .count('conn.execute("BEGIN IMMEDIATE")')
        for relative_path in UOW_MODULES
    } == expected_begin_counts


def test_cross_module_imports_use_public_seams() -> None:
    violations: list[str] = []
    for relative_path in MODULES:
        for node in ast.walk(_tree(relative_path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("account_truth.citic_source_"):
                continue
            for imported in node.names:
                if imported.name.startswith("_"):
                    violations.append(
                        f"{relative_path}:{node.lineno} imports {imported.name}"
                    )

    assert violations == []


def test_contract_and_value_layers_are_provider_and_persistence_free() -> None:
    pure_paths = tuple(
        relative_path
        for relative_path in MODULES
        if relative_path.endswith(("_contracts.py", "_values.py"))
        or relative_path.endswith("citic_source_scope_values.py")
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
