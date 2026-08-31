"""Executable architecture boundaries for controlled broker submission."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import server.contracts.controlled_broker_submission as canonical_contract
import server.services.controlled_broker_submission as submission_module
from server.services.controlled_broker_submission import (
    ControlledBrokerSubmissionRejected,
    ControlledBrokerSubmissionService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "server/services"
CONTRACT = PROJECT_ROOT / "server/contracts/controlled_broker_submission.py"
SERVICE_PATHS = {
    SERVICE_ROOT / "controlled_broker_submission.py",
    SERVICE_ROOT / "controlled_broker_submission_command.py",
    SERVICE_ROOT / "controlled_broker_submission_evidence.py",
    SERVICE_ROOT / "controlled_broker_submission_gateway.py",
    SERVICE_ROOT / "controlled_broker_submission_policy.py",
    SERVICE_ROOT / "controlled_broker_submission_preview.py",
    SERVICE_ROOT / "controlled_broker_submission_queries.py",
    SERVICE_ROOT / "controlled_broker_submission_recovery.py",
    SERVICE_ROOT / "controlled_broker_submission_values.py",
}
PRODUCTION_PATHS = {CONTRACT, *SERVICE_PATHS}

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


def _getattr_literals(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "getattr" or len(node.args) < 2:
            continue
        attribute = node.args[1]
        if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
            names.append(attribute.value)
    return names


def test_submission_facade_preserves_public_contract() -> None:
    assert ControlledBrokerSubmissionService.__module__ == (
        "server.services.controlled_broker_submission"
    )
    assert ControlledBrokerSubmissionRejected.__module__ == (
        "server.services.controlled_broker_submission"
    )

    constant_names = {
        name
        for name in vars(canonical_contract)
        if name.startswith("CONTROLLED_BROKER_")
    }
    assert constant_names
    for name in constant_names:
        assert getattr(submission_module, name) is getattr(canonical_contract, name)

    expected_signatures = {
        "get_status": "(self) -> 'dict[str, Any]'",
        "preview": (
            "(self, *, order_id: 'str', confirmation_id: 'str', "
            "release_evidence_id: 'str') -> 'dict[str, Any]'"
        ),
        "submit": (
            "(self, *, order_id: 'str', confirmation_id: 'str', "
            "release_evidence_id: 'str', submit_fingerprint: 'str', "
            "operator_approval_id: 'str', "
            "operator_proof_signature_base64: 'str', acknowledgement: 'str') "
            "-> 'dict[str, Any]'"
        ),
        "preview_recovery": ("(self, *, submit_intent_id: 'str') -> 'dict[str, Any]'"),
        "recover": (
            "(self, *, submit_intent_id: 'str', recovery_fingerprint: 'str', "
            "operator_approval_id: 'str', "
            "operator_proof_signature_base64: 'str', acknowledgement: 'str') "
            "-> 'dict[str, Any]'"
        ),
        "list_intents": "(self, *, limit: 'int' = 100) -> 'list[dict[str, Any]]'",
        "get_intent": "(self, submit_intent_id: 'str') -> 'dict[str, Any]'",
    }
    assert {
        name: str(inspect.signature(getattr(ControlledBrokerSubmissionService, name)))
        for name in expected_signatures
    } == expected_signatures

    facade_classes = [
        node.name
        for node in _tree(SERVICE_ROOT / "controlled_broker_submission.py").body
        if isinstance(node, ast.ClassDef)
    ]
    assert facade_classes == [
        "ControlledBrokerSubmissionRejected",
        "ControlledBrokerSubmissionService",
    ]


def test_submission_keeps_module_level_monkeypatch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, object]] = []

    def fake_approval(**kwargs: object) -> tuple[dict[str, str], list[str]]:
        observed.append(("approval", kwargs))
        return {"operator_id": "operator-1"}, []

    def fake_approval_with_proof(
        **kwargs: object,
    ) -> tuple[dict[str, str], list[str]]:
        observed.append(("approval_with_proof", kwargs))
        return {"operator_id": "operator-2"}, []

    monkeypatch.setattr(submission_module, "resolve_operator_approval", fake_approval)
    monkeypatch.setattr(
        submission_module,
        "resolve_operator_approval_with_proof",
        fake_approval_with_proof,
    )
    monkeypatch.setattr(
        submission_module,
        "build_order_fingerprint",
        lambda order: f"fingerprint:{order['order_id']}",
    )
    monkeypatch.setattr(
        submission_module,
        "build_execution_gateway_order_contract",
        lambda order: {"contract_order_id": order["order_id"]},
    )
    service = ControlledBrokerSubmissionService(db=object())

    assert service._resolve_operator_approval(marker="first") == (
        {"operator_id": "operator-1"},
        [],
    )
    assert service._resolve_operator_approval_with_proof(marker="second") == (
        {"operator_id": "operator-2"},
        [],
    )
    assert service._build_order_fingerprint({"order_id": "OMS-1"}) == (
        "fingerprint:OMS-1"
    )
    assert service._build_execution_gateway_order_contract({"order_id": "OMS-1"}) == {
        "contract_order_id": "OMS-1"
    }
    assert observed == [
        ("approval", {"marker": "first"}),
        ("approval_with_proof", {"marker": "second"}),
    ]


def test_submission_family_has_zero_size_debt() -> None:
    assert set(SERVICE_ROOT.glob("controlled_broker_submission*.py")) == SERVICE_PATHS
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        source = path.read_text(encoding="utf-8")
        module_limit = 300 if path.name == "controlled_broker_submission.py" else 800
        if len(source.splitlines()) > module_limit:
            violations.append(f"{path.name}:module")
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > 350:
                violations.append(f"{path.name}:{node.name}:{size}")
    assert violations == []


def test_submission_family_has_no_cross_module_private_imports() -> None:
    violations: list[str] = []
    for path in sorted(PRODUCTION_PATHS):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    violations.append(f"{path.name}:{node.module}.{alias.name}")
    assert violations == []


def test_submission_policy_and_values_remain_pure() -> None:
    pure_paths = {
        SERVICE_ROOT / "controlled_broker_submission_policy.py",
        SERVICE_ROOT / "controlled_broker_submission_values.py",
    }
    forbidden_prefixes = (
        "server.db",
        "server.persistence",
        "server.routes",
        "server.services.operator_approval",
        "server.services.broker",
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
        source = path.read_text(encoding="utf-8")
        assert "BEGIN IMMEDIATE" not in source
        assert "append_event_sync" not in source


def test_submission_commands_delegate_to_existing_atomic_uows() -> None:
    expected_owners = {
        "prepare_controlled_broker_submit_intent_sync": {
            "controlled_broker_submission_command.py"
        },
        "claim_controlled_broker_recovery_query_sync": {
            "controlled_broker_submission_recovery.py"
        },
        "finalize_controlled_broker_submit_intent_sync": {
            "controlled_broker_submission_evidence.py"
        },
        "append_event_sync": {"controlled_broker_submission_evidence.py"},
        "get_oms_order_sync": {
            "controlled_broker_submission_command.py",
            "controlled_broker_submission_preview.py",
        },
    }
    for method, expected_owner in expected_owners.items():
        owners = {
            path.name for path in SERVICE_PATHS if method in _called_attributes(path)
        }
        assert owners == expected_owner

    for path in SERVICE_PATHS:
        source = path.read_text(encoding="utf-8")
        assert "BEGIN IMMEDIATE" not in source, path.name
        assert "sqlite3" not in _imports(path), path.name


def test_submission_and_recovery_each_have_one_external_effect_boundary() -> None:
    submit_owners = {
        path.name for path in SERVICE_PATHS if "submit_order" in _getattr_literals(path)
    }
    query_owners = {
        path.name for path in SERVICE_PATHS if "query_order" in _getattr_literals(path)
    }
    assert submit_owners == {"controlled_broker_submission_command.py"}
    assert query_owners == {"controlled_broker_submission_recovery.py"}
    assert (
        sum(_getattr_literals(path).count("submit_order") for path in SERVICE_PATHS)
        == 1
    )
    assert (
        sum(_getattr_literals(path).count("query_order") for path in SERVICE_PATHS) == 2
    )

    recovery = SERVICE_ROOT / "controlled_broker_submission_recovery.py"
    assert "submit_order" not in _getattr_literals(recovery)


def test_submission_family_has_no_extra_authority_or_reverse_dependencies() -> None:
    forbidden_calls = {
        "cancel_order",
        "append_ledger_entry_sync",
        "transition_oms_order_sync",
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
            or dependency.startswith("server.persistence.")
        }, path.name
        assert not (_called_attributes(path) & forbidden_calls), path.name


def test_submission_family_import_graph_is_acyclic() -> None:
    modules = {path.stem: path for path in SERVICE_PATHS}
    graph = {
        name: {
            imported.removeprefix("server.services.")
            for imported in _imports(path)
            if imported.startswith("server.services.")
            and imported.removeprefix("server.services.") in modules
        }
        for name, path in modules.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        assert name not in visiting, f"controlled broker submission cycle at {name}"
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for module in graph:
        visit(module)
