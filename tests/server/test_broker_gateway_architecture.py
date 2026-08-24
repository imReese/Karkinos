"""Executable architecture contract for the broker gateway service family."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import server.services.broker_gateway as gateway_module
from server.services.broker_gateway import BrokerGatewayService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAMILY = (
    "server/contracts/broker_gateway.py",
    "server/services/broker_gateway.py",
    "server/services/broker_gateway_execution.py",
    "server/services/broker_gateway_gates.py",
    "server/services/broker_gateway_manual_tickets.py",
    "server/services/broker_gateway_queries.py",
    "server/services/broker_gateway_values.py",
)
FAMILY_MODULES = {path.removesuffix(".py").replace("/", ".") for path in FAMILY}
PUBLIC_SIGNATURES = {
    "__init__": (
        "(self, *, db: 'Any', broker_connectors: 'list[Any] | None' = None, "
        "controlled_bridge_policy: 'Any | None' = None, "
        "trading_controls: 'Any | None' = None, "
        "current_per_order_confirmation_provider: "
        "'Callable[[str], dict[str, Any]] | None' = None) -> 'None'"
    ),
    "get_status": "(self) -> 'dict[str, Any]'",
    "list_gateways": (
        "(self, *, kill_switch: 'dict[str, Any] | None' = None) "
        "-> 'list[dict[str, Any]]'"
    ),
    "list_connector_health": "(self) -> 'list[dict[str, Any]]'",
    "query_staged_account_facts": "(self) -> 'dict[str, Any]'",
    "query_connector_snapshot": ("(self, connector_id: 'str') -> 'dict[str, Any]'"),
    "query_connector_lifecycle_evidence": (
        "(self, connector_id: 'str') -> 'dict[str, Any]'"
    ),
    "query_staged_fills": (
        "(self, *, symbol: 'str | None' = None, limit: 'int' = 50) "
        "-> 'dict[str, Any]'"
    ),
    "query_order": "(self, order_id: 'str') -> 'dict[str, Any]'",
    "preview_manual_ticket": (
        "(self, order_id: 'str', *, actor: 'str | None' = None) " "-> 'dict[str, Any]'"
    ),
    "export_manual_ticket": (
        "(self, order_id: 'str', *, actor: 'str | None' = None) " "-> 'dict[str, Any]'"
    ),
    "dry_run_manual_ticket": (
        "(self, order_id: 'str', *, actor: 'str | None' = None) " "-> 'dict[str, Any]'"
    ),
    "create_manual_ticket": (
        "(self, order_id: 'str', *, actor: 'str | None' = None) " "-> 'dict[str, Any]'"
    ),
    "preview_manual_execution_record": (
        "(self, order_id: 'str', *, fill_price: 'Any', quantity: 'Any', "
        "fee: 'Any' = None, tax: 'Any' = None, transfer_fee: 'Any' = None, "
        "actor: 'str | None' = None) -> 'dict[str, Any]'"
    ),
    "record_manual_execution_evidence": (
        "(self, order_id: 'str', *, preview_fingerprint: 'str', "
        "fill_price: 'Any', quantity: 'Any', fee: 'Any' = None, "
        "tax: 'Any' = None, transfer_fee: 'Any' = None, "
        "actor: 'str | None' = None, operator_note: 'str | None' = None) "
        "-> 'dict[str, Any]'"
    ),
    "submit_live_disabled": (
        "(self, order_id: 'str', *, actor: 'str | None' = None) " "-> 'dict[str, Any]'"
    ),
    "cancel_live_disabled": (
        "(self, order_id: 'str', *, actor: 'str | None' = None) " "-> 'dict[str, Any]'"
    ),
}
LEGACY_HELPER_NAMES = {
    "_FINGERPRINT_PATTERN",
    "_CONTROLLED_BRIDGE_REQUIRED_GATES",
    "_REQUIRED_GATEWAY_EVIDENCE",
    "_manual_execution_preview",
    "_manual_execution_ledger_draft",
    "_fingerprint_payload",
    "_required_decimal",
    "_optional_decimal",
    "_money_string",
    "_quantity_string",
    "_clean_number",
    "_string_list",
    "_operator_account_alias",
    "_fee_tax_assumptions",
    "_cash_impact_preview",
    "_position_cost_preview",
    "_trading_session_constraints",
    "_first_mapping",
    "_mapping_value",
    "_optional_clean_number",
    "_optional_string",
    "_order_intent_payload",
    "_order_payload",
    "_gateway_event_payload",
    "_broker_fill_payload",
    "_cash_balance_payloads",
    "_position_payloads",
    "_broker_account_fill_payload",
    "_decimal_value",
}

pytestmark = pytest.mark.unit


def _tree(relative_path: str) -> ast.Module:
    path = PROJECT_ROOT / relative_path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(relative_path: str) -> list[tuple[str, str, int]]:
    imports: list[tuple[str, str, int]] = []
    for node in ast.walk(_tree(relative_path)):
        if isinstance(node, ast.Import):
            imports.extend(
                (alias.name, alias.name, node.lineno) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.extend(
                (node.module, alias.name, node.lineno) for alias in node.names
            )
    return imports


def test_broker_gateway_family_has_zero_size_debt() -> None:
    violations: list[str] = []
    for relative_path in FAMILY:
        path = PROJECT_ROOT / relative_path
        source = path.read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{relative_path}: module exceeds 800 lines")
        for node in ast.walk(_tree(relative_path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = (node.end_lineno or node.lineno) - node.lineno + 1
                if size > 350:
                    violations.append(
                        f"{relative_path}:{node.lineno} {node.name} exceeds 350 lines"
                    )

    assert violations == []


def test_facade_preserves_public_identity_signatures_and_compatibility_names() -> None:
    assert BrokerGatewayService.__module__ == "server.services.broker_gateway"
    assert gateway_module.BROKER_GATEWAY_SCHEMA_VERSION == (
        "karkinos.broker_gateway.v1"
    )
    assert gateway_module.CONTROLLED_BRIDGE_POLICY_SCHEMA_VERSION == (
        "karkinos.controlled_broker_bridge_policy.v1"
    )
    assert gateway_module.MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCOPE == (
        "order_id, execution_preview, ledger_entry_draft, "
        "position_cost_preview, controlled_bridge_policy, "
        "current_per_order_confirmation"
    )
    assert {
        name: str(inspect.signature(getattr(BrokerGatewayService, name)))
        for name in PUBLIC_SIGNATURES
    } == PUBLIC_SIGNATURES
    assert {
        name for name in LEGACY_HELPER_NAMES if not hasattr(gateway_module, name)
    } == set()


def test_family_dependency_graph_is_one_way_acyclic_and_uses_public_symbols() -> None:
    graph: dict[str, set[str]] = {module: set() for module in FAMILY_MODULES}
    private_imports: list[str] = []
    forbidden_runtime_dependencies: list[str] = []
    for relative_path in FAMILY:
        owner = relative_path.removesuffix(".py").replace("/", ".")
        for dependency, name, line in _imports(relative_path):
            if dependency in FAMILY_MODULES:
                graph[owner].add(dependency)
                if name.startswith("_"):
                    private_imports.append(f"{relative_path}:{line}:{name}")
            if dependency == "sqlite3" or dependency.startswith(
                ("server.routes", "server.persistence")
            ):
                forbidden_runtime_dependencies.append(
                    f"{relative_path}:{line}:{dependency}"
                )

    assert private_imports == []
    assert forbidden_runtime_dependencies == []
    assert graph["server.services.broker_gateway_values"] == set()
    assert all(
        "server.services.broker_gateway" not in dependencies
        for module, dependencies in graph.items()
        if module != "server.services.broker_gateway"
    )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        assert module not in visiting, f"broker gateway dependency cycle at {module}"
        if module in visited:
            return
        visiting.add(module)
        for dependency in graph[module]:
            visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)


def test_values_module_is_pure_and_facade_owns_broker_evidence_composition() -> None:
    value_dependencies = {dependency for dependency, _, _ in _imports(FAMILY[-1])}
    assert not any(
        dependency == "sqlite3"
        or dependency.startswith(("account_truth", "server", "execution"))
        for dependency in value_dependencies
    )
    evidence_readers = {
        relative_path
        for relative_path in FAMILY
        if any(
            dependency == "account_truth.broker_evidence"
            for dependency, _, _ in _imports(relative_path)
        )
    }
    assert evidence_readers == {"server/services/broker_gateway.py"}


def test_facade_retains_runtime_composition_monkeypatch_seams(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeOmsService:
        def __init__(self, *, db: object) -> None:
            seen["oms_db"] = db

    class FakeLifecycleView:
        def __init__(self, *, db: object, broker_connectors: list[object]) -> None:
            seen["view"] = (db, broker_connectors)

        def list_health(self) -> list[dict[str, object]]:
            return [{"status": "persisted-only"}]

    class FakeEvidenceRepository:
        def __init__(self, path: Path) -> None:
            seen["repository_path"] = path

    db = type("Database", (), {"_path": PROJECT_ROOT / "local.db"})()
    connectors = [object()]
    monkeypatch.setattr(gateway_module, "OmsService", FakeOmsService)
    monkeypatch.setattr(
        gateway_module,
        "BrokerLifecycleEvidenceViewService",
        FakeLifecycleView,
    )
    monkeypatch.setattr(
        gateway_module,
        "BrokerEvidenceRepository",
        FakeEvidenceRepository,
    )
    monkeypatch.setattr(
        gateway_module,
        "resolve_kill_switch_evidence",
        lambda controls: {
            "status": "pass",
            "enabled": False,
            "reason": "",
            "updated_at": None,
            "evidence_available": True,
            "blockers": [],
            "evidence_ref": "test:kill-switch",
        },
    )

    service = BrokerGatewayService(
        db=db,
        broker_connectors=connectors,
        trading_controls=object(),
    )

    assert seen["oms_db"] is db
    assert service.list_connector_health() == [{"status": "persisted-only"}]
    assert seen["view"] == (db, connectors)
    assert service._broker_evidence_repository().__class__ is FakeEvidenceRepository
    assert seen["repository_path"] == PROJECT_ROOT / "local.db"
    assert service.get_status()["kill_switch_status"] == "pass"
