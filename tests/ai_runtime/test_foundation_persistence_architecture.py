"""Architecture guards for the foundational AI runtime persistence split."""

from __future__ import annotations

import ast
from pathlib import Path

from server.ai_runtime.persistence.ai_audit import AiAuditStore as PersistedAiAuditStore
from server.ai_runtime.store import AiAuditStore

ROOT = Path(__file__).resolve().parents[2]
AI_RUNTIME = ROOT / "server" / "ai_runtime"
FACADE_FILES = (
    AI_RUNTIME / "store.py",
    AI_RUNTIME / "evidence.py",
    AI_RUNTIME / "capture.py",
    AI_RUNTIME / "provider_connectivity.py",
)
PERSISTENCE_FILES = tuple(sorted((AI_RUNTIME / "persistence").glob("*.py")))
PRODUCTION_FILES = FACADE_FILES + PERSISTENCE_FILES
SCOPED_MODULES = {
    path: "server."
    + path.relative_to(ROOT / "server").with_suffix("").as_posix().replace("/", ".")
    for path in PRODUCTION_FILES
}
SQL_MARKERS = (
    "sqlite3",
    "BEGIN ",
    "CREATE TABLE",
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    ".execute(",
    ".executescript(",
)


def test_public_ai_audit_store_keeps_the_original_class_identity() -> None:
    assert AiAuditStore is PersistedAiAuditStore


def test_foundation_facades_own_no_sql_or_database_connection() -> None:
    for path in FACADE_FILES:
        source = path.read_text(encoding="utf-8")
        assert not [marker for marker in SQL_MARKERS if marker in source], path


def test_foundation_sql_is_confined_to_persistence_modules() -> None:
    sqlite_owners = {
        path.name
        for path in PERSISTENCE_FILES
        if "import sqlite3" in path.read_text(encoding="utf-8")
    }
    assert sqlite_owners == {
        "ai_audit.py",
        "canonical_evidence.py",
        "context_capture.py",
        "provider_connectivity.py",
    }


def test_foundation_unit_of_work_boundaries_remain_explicit() -> None:
    actual = {
        path.name: path.read_text(encoding="utf-8").count('"BEGIN IMMEDIATE"')
        for path in PERSISTENCE_FILES
        if '"BEGIN IMMEDIATE"' in path.read_text(encoding="utf-8")
    }
    assert actual == {"ai_audit.py": 1, "provider_connectivity.py": 1}


def test_foundation_persistence_does_not_import_runtime_facades() -> None:
    forbidden = {"store", "evidence", "capture", "provider_connectivity"}
    for path in PERSISTENCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module.split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not imported.intersection(forbidden), path


def test_foundation_dependency_graph_is_explicit_and_acyclic() -> None:
    modules = set(SCOPED_MODULES.values())
    actual: dict[str, set[str]] = {}
    for path, module_name in SCOPED_MODULES.items():
        package = module_name.split(".")[:-1]
        dependencies: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.level:
                parent = package[: len(package) - node.level + 1]
                imported = ".".join((*parent, node.module))
            else:
                imported = node.module
            if imported in modules:
                dependencies.add(imported)
        actual[module_name] = dependencies

    assert actual == {
        "server.ai_runtime.store": {"server.ai_runtime.persistence.ai_audit"},
        "server.ai_runtime.evidence": {
            "server.ai_runtime.persistence.canonical_evidence"
        },
        "server.ai_runtime.capture": {
            "server.ai_runtime.evidence",
            "server.ai_runtime.persistence.context_capture",
            "server.ai_runtime.store",
        },
        "server.ai_runtime.provider_connectivity": {
            "server.ai_runtime.persistence.provider_connectivity",
            "server.ai_runtime.store",
        },
        "server.ai_runtime.persistence.__init__": set(),
        "server.ai_runtime.persistence.ai_audit": {
            "server.ai_runtime.persistence.ai_audit_schema"
        },
        "server.ai_runtime.persistence.ai_audit_schema": set(),
        "server.ai_runtime.persistence.canonical_evidence": set(),
        "server.ai_runtime.persistence.context_capture": set(),
        "server.ai_runtime.persistence.provider_connectivity": set(),
    }


def test_foundation_modules_have_bounded_file_and_function_sizes() -> None:
    for path in PRODUCTION_FILES:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 800, path
        tree = ast.parse(source)
        oversized = {
            node.name: (node.end_lineno or node.lineno) - node.lineno + 1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and (node.end_lineno or node.lineno) - node.lineno + 1 > 350
        }
        assert not oversized, (path, oversized)


def test_foundation_modules_do_not_import_cross_module_private_symbols() -> None:
    for path in PRODUCTION_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        private_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name.startswith("_")
        }
        assert not private_imports, (path, private_imports)
