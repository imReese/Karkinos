"""Executable architecture boundaries for controlled-submission clearance."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import server.contracts.controlled_submission_reconciliation_clearance as canonical_contract
import server.services.controlled_submission_reconciliation_clearance as clearance_module
from server.persistence.controlled_clearance_uow import (
    ControlledClearanceUnitOfWorkMixin,
)
from server.services.controlled_submission_reconciliation_clearance import (
    ControlledSubmissionReconciliationClearanceRejected,
    ControlledSubmissionReconciliationClearanceService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "server/services"
PERSISTENCE_ROOT = PROJECT_ROOT / "server/persistence"
CONTRACT = (
    PROJECT_ROOT / "server/contracts/controlled_submission_reconciliation_clearance.py"
)
SERVICE_PATHS = {
    SERVICE_ROOT / "controlled_submission_reconciliation_clearance.py",
    SERVICE_ROOT / "controlled_submission_clearance_command.py",
    SERVICE_ROOT / "controlled_submission_clearance_context.py",
    SERVICE_ROOT / "controlled_submission_clearance_evidence.py",
    SERVICE_ROOT / "controlled_submission_clearance_evidence_values.py",
    SERVICE_ROOT / "controlled_submission_clearance_preview.py",
    SERVICE_ROOT / "controlled_submission_clearance_queries.py",
    SERVICE_ROOT / "controlled_submission_clearance_values.py",
}
PERSISTENCE_PATHS = {
    PERSISTENCE_ROOT / "controlled_clearance_lifecycle.py",
    PERSISTENCE_ROOT / "controlled_clearance_repository.py",
    PERSISTENCE_ROOT / "controlled_clearance_uow.py",
    PERSISTENCE_ROOT / "controlled_clearance_validation.py",
    PERSISTENCE_ROOT / "controlled_clearance_values.py",
    PERSISTENCE_ROOT / "controlled_clearance_writer.py",
}
PRODUCTION_PATHS = {CONTRACT, *SERVICE_PATHS, *PERSISTENCE_PATHS}

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _called_attributes(path: Path) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _called_names(path: Path) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _sql_literals(path: Path) -> list[str]:
    statements: list[str] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        normalized = " ".join(node.value.split()).upper()
        if normalized.startswith(
            ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "BEGIN ", "PRAGMA ")
        ):
            statements.append(normalized)
    return statements


def test_clearance_facade_preserves_public_contract() -> None:
    assert ControlledSubmissionReconciliationClearanceService.__module__ == (
        "server.services.controlled_submission_reconciliation_clearance"
    )
    assert ControlledSubmissionReconciliationClearanceRejected.__module__ == (
        "server.services.controlled_submission_reconciliation_clearance"
    )
    assert ControlledClearanceUnitOfWorkMixin.__module__ == (
        "server.persistence.controlled_clearance_uow"
    )

    constant_names = {
        name
        for name in vars(canonical_contract)
        if name.startswith("CONTROLLED_SUBMISSION_CLEARANCE_")
    }
    assert constant_names
    for name in constant_names:
        assert getattr(clearance_module, name) is getattr(canonical_contract, name)

    expected_signatures = {
        "get_status": "(self) -> 'dict[str, Any]'",
        "preview": (
            "(self, *, submit_intent_id: 'str', reconciliation_run_id: 'str') "
            "-> 'dict[str, Any]'"
        ),
        "record": (
            "(self, *, submit_intent_id: 'str', reconciliation_run_id: 'str', "
            "clearance_fingerprint: 'str', operator_approval_id: 'str', "
            "operator_proof_signature_base64: 'str', acknowledgement: 'str') "
            "-> 'dict[str, Any]'"
        ),
        "get_clearance": "(self, clearance_id: 'str') -> 'dict[str, Any]'",
        "list_clearances": ("(self, *, limit: 'int' = 100) -> 'list[dict[str, Any]]'"),
    }
    assert {
        name: str(
            inspect.signature(
                getattr(ControlledSubmissionReconciliationClearanceService, name)
            )
        )
        for name in expected_signatures
    } == expected_signatures
    assert (
        str(
            inspect.signature(
                ControlledClearanceUnitOfWorkMixin.record_controlled_submission_reconciliation_clearance_sync
            )
        )
        == "(self, *, clearance: 'dict[str, Any]') -> 'dict[str, Any]'"
    )

    facade_classes = [
        node.name
        for node in _tree(
            SERVICE_ROOT / "controlled_submission_reconciliation_clearance.py"
        ).body
        if isinstance(node, ast.ClassDef)
    ]
    assert facade_classes == [
        "ControlledSubmissionReconciliationClearanceRejected",
        "ControlledSubmissionReconciliationClearanceService",
    ]


def test_clearance_keeps_module_level_monkeypatch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, object]] = []

    def fake_approval(**kwargs: object) -> tuple[dict[str, str], list[str]]:
        observed.append(("approval", kwargs))
        return {"operator_id": "operator-1"}, []

    monkeypatch.setattr(
        clearance_module,
        "resolve_operator_approval_with_proof",
        fake_approval,
    )
    monkeypatch.setattr(
        clearance_module,
        "build_order_fingerprint",
        lambda order: f"fingerprint:{order['order_id']}",
    )
    monkeypatch.setattr(
        clearance_module,
        "BrokerEvidenceRepository",
        lambda path: ("broker-evidence", path),
    )
    monkeypatch.setattr(
        clearance_module,
        "BrokerOrderLifecycleEvidenceRepository",
        lambda path, *, ensure_schema: ("lifecycle", path, ensure_schema),
    )
    monkeypatch.setattr(
        clearance_module,
        "broker_order_lifecycle_terminal_outcome",
        lambda order, evidence: {"order": order, "evidence": evidence},
    )
    service = ControlledSubmissionReconciliationClearanceService(db=object())
    path = Path("evidence.sqlite3")

    assert service._resolve_operator_approval_with_proof(marker="proof") == (
        {"operator_id": "operator-1"},
        [],
    )
    assert service._build_order_fingerprint({"order_id": "OMS-1"}) == (
        "fingerprint:OMS-1"
    )
    assert service._broker_evidence_repository(path) == ("broker-evidence", path)
    assert service._broker_order_lifecycle_repository(
        path,
        ensure_schema=False,
    ) == ("lifecycle", path, False)
    assert service._broker_order_lifecycle_terminal_outcome(
        {"order": 1},
        {"evidence": 2},
    ) == {"order": {"order": 1}, "evidence": {"evidence": 2}}
    assert observed == [("approval", {"marker": "proof"})]


def test_clearance_family_has_zero_size_debt() -> None:
    assert set(SERVICE_ROOT.glob("controlled_submission_clearance_*.py")) == (
        SERVICE_PATHS
        - {SERVICE_ROOT / "controlled_submission_reconciliation_clearance.py"}
    )
    assert set(PERSISTENCE_ROOT.glob("controlled_clearance_*.py")) == (
        PERSISTENCE_PATHS
    )
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        source = path.read_text(encoding="utf-8")
        module_limit = (
            300
            if path.name
            in {
                "controlled_submission_reconciliation_clearance.py",
                "controlled_clearance_uow.py",
            }
            else 800
        )
        if len(source.splitlines()) > module_limit:
            violations.append(f"{path.name}:module:{len(source.splitlines())}")
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(f"{path.name}:{node.name}:{size}")
    assert violations == []


def test_clearance_family_has_no_cross_module_private_imports() -> None:
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    violations.append(f"{path.name}:{node.module}.{alias.name}")
    assert violations == []


def test_clearance_value_modules_remain_pure() -> None:
    pure_paths = {
        SERVICE_ROOT / "controlled_submission_clearance_evidence_values.py",
        SERVICE_ROOT / "controlled_submission_clearance_values.py",
        SERVICE_ROOT / "controlled_submission_clearance_context.py",
        PERSISTENCE_ROOT / "controlled_clearance_values.py",
    }
    forbidden_prefixes = (
        "account_truth",
        "server.db",
        "server.persistence",
        "server.routes",
        "server.services.operator_approval",
    )
    for path in pure_paths:
        imports = _imports(path)
        assert not {
            dependency
            for dependency in imports
            if any(
                dependency == prefix or dependency.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            )
        }, path.name
        assert _sql_literals(path) == []


def test_clearance_uow_alone_owns_the_single_transaction() -> None:
    begin_owners = {
        path.name
        for path in PERSISTENCE_PATHS
        if any(statement == "BEGIN IMMEDIATE" for statement in _sql_literals(path))
    }
    assert begin_owners == {"controlled_clearance_uow.py"}
    assert (
        sum(
            statement == "BEGIN IMMEDIATE"
            for path in PERSISTENCE_PATHS
            for statement in _sql_literals(path)
        )
        == 1
    )

    for path in PERSISTENCE_PATHS - {PERSISTENCE_ROOT / "controlled_clearance_uow.py"}:
        assert "connect" not in _called_attributes(path), path.name
        assert not ({"commit", "rollback"} & _called_attributes(path)), path.name


def test_clearance_persistence_has_explicit_read_validate_write_owners() -> None:
    repository = PERSISTENCE_ROOT / "controlled_clearance_repository.py"
    writer = PERSISTENCE_ROOT / "controlled_clearance_writer.py"
    uow = PERSISTENCE_ROOT / "controlled_clearance_uow.py"
    assert _sql_literals(repository)
    assert all(
        statement.startswith("SELECT ") for statement in _sql_literals(repository)
    )
    assert _sql_literals(writer)
    assert all(
        statement.startswith(("INSERT ", "UPDATE "))
        for statement in _sql_literals(writer)
    )
    assert not {
        statement
        for statement in _sql_literals(uow)
        if statement.startswith(("SELECT ", "INSERT ", "UPDATE ", "DELETE "))
    }
    assert "build_controlled_clearance_write_plan" in _called_names(uow)
    assert "write_controlled_clearance" in _called_names(uow)
    assert {
        path.name
        for path in PERSISTENCE_PATHS
        if "insert_event_sync" in _called_names(path)
    } == {"controlled_clearance_writer.py"}


def test_clearance_service_has_one_command_and_one_audit_owner() -> None:
    expected_owners = {
        "record_controlled_submission_reconciliation_clearance_sync": {
            "controlled_submission_clearance_command.py"
        },
        "append_event_sync": {"controlled_submission_clearance_evidence.py"},
    }
    for method, expected_owner in expected_owners.items():
        owners = {
            path.name for path in SERVICE_PATHS if method in _called_attributes(path)
        }
        assert owners == expected_owner
    for path in SERVICE_PATHS:
        assert _sql_literals(path) == [], path.name
        assert "sqlite3" not in _imports(path), path.name


def test_clearance_family_has_no_broker_ledger_or_capital_authority() -> None:
    forbidden_calls = {
        "submit_order",
        "cancel_order",
        "query_order",
        "append_ledger_entry_sync",
        "insert_ledger_entry_sync",
        "reserve_capital_sync",
        "release_capital_sync",
    }
    for path in PRODUCTION_PATHS:
        imports = _imports(path)
        assert not {
            dependency
            for dependency in imports
            if dependency == "server.routes"
            or dependency.startswith("server.routes.")
            or dependency.startswith("server.services.broker")
        }, path.name
        assert not (_called_attributes(path) & forbidden_calls), path.name
        for statement in _sql_literals(path):
            assert " LEDGER_ENTRIES" not in statement, path.name
            assert " CAPITAL_AUTHORIZATIONS" not in statement, path.name
            if statement.startswith(("INSERT ", "UPDATE ", "DELETE ")):
                assert " CONTROLLED_BROKER_SUBMIT_INTENTS" not in statement, path.name


def test_clearance_family_import_graph_is_acyclic() -> None:
    modules = {
        ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts): path
        for path in PRODUCTION_PATHS
    }
    graph = {
        name: {imported for imported in _imports(path) if imported in modules}
        for name, path in modules.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        assert name not in visiting, f"controlled-clearance cycle at {name}"
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for module in graph:
        visit(module)
