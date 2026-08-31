"""Executable ownership and atomicity constraints for the frozen v1 schema."""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from server import db as db_module
from server.persistence import initializer, migrations
from server.persistence.schema_v1 import initialize_v1_baseline_schema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_MODULES = tuple(
    sorted((PROJECT_ROOT / "server/persistence").glob("schema_v1*.py"))
)
FRAGMENT_MODULES = tuple(
    path for path in SCHEMA_MODULES if path.name.endswith("_fragments.py")
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


def test_v1_schema_modules_are_bounded_and_persistence_only() -> None:
    assert SCHEMA_MODULES
    for path in SCHEMA_MODULES:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 800, path.name
        assert not {
            imported
            for imported in _imports(path)
            if imported == "server.services"
            or imported.startswith("server.services.")
            or imported == "server.routes"
            or imported.startswith("server.routes.")
        }, path.name
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno is not None
                assert node.end_lineno - node.lineno + 1 <= 350, (
                    path.name,
                    node.name,
                )


def test_frozen_fragments_are_declarative_and_composed_once_in_order() -> None:
    assert {path.name for path in FRAGMENT_MODULES} == {
        "schema_v1_financial_fragments.py",
        "schema_v1_operational_fragments.py",
        "schema_v1_reference_fragments.py",
    }
    for path in FRAGMENT_MODULES:
        tree = _tree(path)
        assert not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for node in tree.body
        ), path.name
        assert _imports(path) == set()

    source = (PROJECT_ROOT / "server/persistence/schema_v1.py").read_text(
        encoding="utf-8"
    )
    ordered_calls = (
        "conn.executescript(_V1_BASELINE_SCHEMA_SQL)",
        "ensure_controlled_submission_clearance_terminal_schema(conn)",
        "conn.executescript(CONTROLLED_SUBMISSION_LEDGER_POSTING_TABLE_SQL)",
        "conn.executescript(CONTROLLED_SUBMISSION_LEDGER_CORRECTION_TABLE_SQL)",
        "ensure_v1_compatibility_schema(conn)",
    )
    positions = [source.index(call) for call in ordered_calls]
    assert positions == sorted(positions)
    assert source.count("conn.executescript(_V1_BASELINE_SCHEMA_SQL)") == 1


def test_public_initializer_identity_and_frozen_checksum_remain_stable() -> None:
    assert initialize_v1_baseline_schema.__module__ == "server.persistence.schema_v1"
    assert initializer.initialize_v1_baseline_schema is initialize_v1_baseline_schema
    assert db_module._initialize_v1_baseline_schema is initialize_v1_baseline_schema
    assert migrations.V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM == (
        "06667c9d72bfa7fcbe263ee8c41a95948f839bf3a460fdb5ecb9bb45eb862f31"
    )
    with sqlite3.connect(":memory:") as connection:
        initialize_v1_baseline_schema(connection)
        contract = migrations._read_schema_contract(connection)
    assert migrations._schema_contract_checksum(contract) == (
        migrations.V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM
    )


def test_failed_exact_terminal_rebuild_rolls_back_rename_and_copy(tmp_path) -> None:
    database_path = tmp_path / "legacy-invalid-clearance.db"
    with sqlite3.connect(database_path) as connection:
        _create_legacy_clearance_table(connection)
        _insert_legacy_clearance(connection, fill_count=-1)
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        with sqlite3.connect(database_path) as connection:
            initialize_v1_baseline_schema(connection)

    with sqlite3.connect(database_path) as connection:
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        table_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                ("controlled_submission_reconciliation_clearances",),
            ).fetchone()[0]
        )
        row = connection.execute(
            "SELECT clearance_id, fill_count "
            "FROM controlled_submission_reconciliation_clearances"
        ).fetchone()

    assert row == ("legacy-clearance-invalid", -1)
    assert "terminal_status" not in table_sql
    assert "controlled_submission_reconciliation_clearances_v2" not in table_names


def _create_legacy_clearance_table(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE controlled_submission_reconciliation_clearances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clearance_id TEXT NOT NULL UNIQUE,
            clearance_fingerprint TEXT NOT NULL UNIQUE,
            submit_intent_id TEXT NOT NULL UNIQUE,
            submit_fingerprint TEXT NOT NULL,
            order_id TEXT NOT NULL UNIQUE,
            broker_order_id TEXT NOT NULL,
            review_reconciliation_run_id TEXT NOT NULL,
            review_reconciliation_item_id INTEGER NOT NULL,
            broker_evidence_fingerprint TEXT NOT NULL,
            account_truth_import_run_id TEXT NOT NULL,
            account_truth_file_fingerprint TEXT NOT NULL,
            account_truth_source_fingerprint TEXT NOT NULL,
            clearance_reconciliation_run_id TEXT NOT NULL UNIQUE,
            operator_id TEXT NOT NULL,
            operator_approval_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status = 'cleared'),
            fill_count INTEGER NOT NULL,
            fill_quantity TEXT NOT NULL,
            cleared_at_epoch_ms INTEGER NOT NULL,
            cleared_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)


def _insert_legacy_clearance(
    connection: sqlite3.Connection, *, fill_count: int
) -> None:
    connection.execute(
        """
        INSERT INTO controlled_submission_reconciliation_clearances (
            clearance_id, clearance_fingerprint, submit_intent_id,
            submit_fingerprint, order_id, broker_order_id,
            review_reconciliation_run_id, review_reconciliation_item_id,
            broker_evidence_fingerprint, account_truth_import_run_id,
            account_truth_file_fingerprint, account_truth_source_fingerprint,
            clearance_reconciliation_run_id, operator_id,
            operator_approval_id, status, fill_count, fill_quantity,
            cleared_at_epoch_ms, cleared_at, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-clearance-invalid",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "OMS-legacy-invalid",
            "BROKER-legacy-invalid",
            "legacy-review-run",
            1,
            "d" * 64,
            "legacy-import-run",
            "e" * 64,
            "f" * 64,
            "legacy-clearance-run",
            "legacy-operator",
            "1" * 64,
            "cleared",
            fill_count,
            "100",
            1,
            "2026-07-13T00:00:00+00:00",
            "{}",
            "2026-07-13T00:00:00+00:00",
        ),
    )
