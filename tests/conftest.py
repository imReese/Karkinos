"""pytest 共享配置。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from core.types import Symbol


def pytest_collection_modifyitems(config, items) -> None:
    """Apply coarse test layers from stable paths instead of per-test boilerplate."""
    for item in items:
        path = str(item.path).replace("\\", "/")
        name = item.name
        if _is_acceptance_test(path):
            item.add_marker(pytest.mark.acceptance)
        elif _is_api_contract_test(path):
            item.add_marker(pytest.mark.api_contract)
        else:
            item.add_marker(pytest.mark.unit)

        if _is_slow_test(path, name):
            item.add_marker(pytest.mark.slow)


def _is_acceptance_test(path: str) -> bool:
    filename = path.rsplit("/", 1)[-1]
    return filename in {
        "test_acceptance_audit.py",
        "test_acceptance_audit_cli.py",
        "test_decision_cockpit_acceptance.py",
        "test_profit_discipline_smoke.py",
    }


def _is_api_contract_test(path: str) -> bool:
    filename = path.rsplit("/", 1)[-1]
    return filename in {
        "test_server_db.py",
        "test_server_routes.py",
        "test_ci_workflow.py",
    } or (
        "/tests/server/" in path
        and filename
        in {
            "test_bridge.py",
            "test_fund_nav_sync.py",
            "test_ledger_repository.py",
            "test_ledger_routes.py",
            "test_projection_service.py",
            "test_scheduler_quote_fetch_runs.py",
            "test_signal_journal_routes.py",
            "test_trading_routes.py",
        }
    )


def _is_slow_test(path: str, name: str) -> bool:
    filename = path.rsplit("/", 1)[-1]
    return filename == "test_benchmark_fixtures.py" or name in {
        "test_poll_all_times_out_slow_symbols_without_blocking_fast_quotes",
        "test_tushare_default_realtime_timeout_waits_for_slow_valid_quote",
        "test_scheduler_waits_between_poll_iterations",
    }


@pytest.fixture
def symbol_600519() -> Symbol:
    return Symbol("600519")


@pytest.fixture
def symbol_510300() -> Symbol:
    return Symbol("510300")


@pytest.fixture
def now() -> datetime:
    return datetime(2024, 1, 15, 10, 0, 0)


@pytest.fixture
def decimal_close() -> Decimal:
    return Decimal("1850.00")
