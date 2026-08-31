"""Executable ownership rules for manual-ticket and OMS order-state writes."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _called_attributes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _defined_methods(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            }
    raise AssertionError(f"class not found: {class_name}")


def test_trading_route_uses_only_atomic_manual_order_commands() -> None:
    calls = _called_attributes(ROOT / "server/routes/trading.py")
    assert calls.isdisjoint(
        {
            "save_manual_order_sync",
            "record_order_sync",
            "update_manual_order_status_sync",
            "update_order_status_sync",
            "update_action_task_status_sync",
        }
    )


def test_manual_gateway_is_atomic_and_scheduler_does_not_wire_execution() -> None:
    gateway_path = ROOT / "execution/gateway.py"
    calls = _called_attributes(gateway_path)
    assert calls.isdisjoint(
        {
            "save_manual_order_sync",
            "record_order_sync",
            "update_manual_order_status_sync",
            "update_order_status_sync",
        }
    )
    gateway_source = gateway_path.read_text(encoding="utf-8")
    adapter_source = (ROOT / "server/services/manual_order_tickets.py").read_text(
        encoding="utf-8"
    )
    scheduler_source = (ROOT / "server/scheduler_loop.py").read_text(encoding="utf-8")
    composition_source = (ROOT / "server/scheduler.py").read_text(encoding="utf-8")
    assert "server." not in gateway_source
    assert "ManualOrderTicketPort" in gateway_source
    assert "ManualOrderTicketService" in adapter_source
    assert "ManualOrderTicketCommand" in adapter_source
    assert "ManualOrderStateCommand" in adapter_source
    assert "pre_trade_risk_manager_factory" not in scheduler_source
    assert "manual_confirm_gateway_factory" not in scheduler_source
    assert "paper_execution_connector_factory" not in scheduler_source
    assert "PreTradeRiskManager" not in composition_source
    assert "build_manual_confirm_gateway" not in composition_source
    assert "PaperExecutionConnector" not in composition_source


def test_oms_service_uses_only_atomic_order_state_commands() -> None:
    calls = _called_attributes(ROOT / "server/services/oms.py")
    assert calls.isdisjoint(
        {
            "upsert_oms_order_sync",
            "update_oms_order_status_sync",
            "record_oms_transition_sync",
        }
    )
    assert {"create_oms_order_sync", "transition_oms_order_sync"} <= calls


def test_order_state_uows_own_explicit_write_transactions() -> None:
    manual = (ROOT / "server/persistence/manual_order_ticket_uow.py").read_text(
        encoding="utf-8"
    )
    oms = (ROOT / "server/persistence/oms.py").read_text(encoding="utf-8")

    assert manual.count('conn.execute("BEGIN IMMEDIATE")') == 2
    assert oms.count('conn.execute("BEGIN IMMEDIATE")') == 2
    assert "order_state_command_claims" not in (
        ROOT / "server/persistence/schema_v1_financial_fragments.py"
    ).read_text(encoding="utf-8")
    assert "claim_atomic_order_state_commands" in (
        ROOT / "server/persistence/migrations.py"
    ).read_text(encoding="utf-8")


def test_unsafe_split_order_state_writers_are_not_public_repository_methods() -> None:
    unsafe_manual = {
        "save_manual_order_sync",
        "update_manual_order_status_sync",
    }
    unsafe_oms = {
        "upsert_oms_order_sync",
        "update_oms_order_status_sync",
        "record_oms_transition_sync",
    }

    assert _defined_methods(
        ROOT / "server/persistence/paper_trading.py",
        "PaperTradingRepository",
    ).isdisjoint(unsafe_manual)
    assert _defined_methods(
        ROOT / "server/persistence/facades/strategy_trading.py",
        "StrategyTradingDatabaseFacade",
    ).isdisjoint(unsafe_manual)
    assert _defined_methods(
        ROOT / "server/persistence/oms.py",
        "OmsRepository",
    ).isdisjoint(unsafe_oms)
    assert _defined_methods(
        ROOT / "server/persistence/facades/execution.py",
        "ExecutionDatabaseFacade",
    ).isdisjoint(unsafe_oms)
