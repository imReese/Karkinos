"""Tests for canonical runtime path resolution."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from server.config import BrokerStatementCollectorConfig
from server.runtime_paths import (
    resolve_broker_statement_path,
    resolve_workspace,
)
from server.services.account.roll_forward import (
    roll_forward_daily_broker_statement_for_state,
)

STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
cash-anchor,cash_snapshot,2026-08-10T15:00:00+08:00,2026-08-10,,,,CNY,0,0,0,0,0,0,1000,,,
position-anchor,position_snapshot,2026-08-10T15:00:00+08:00,2026-08-10,SYN001,Synthetic Stock,stock,CNY,0,10,0,0,0,0,,10,10,source position
sell-001,trade_sell,2026-08-17T10:00:00+08:00,,SYN001,Synthetic Stock,stock,CNY,10,12,120,1,1,118,,0,0,source sell
"""


def test_resolve_broker_statement_path_absolute(tmp_path: Path) -> None:
    abs_file = (tmp_path / "statement.csv").resolve()
    assert resolve_broker_statement_path(abs_file) == abs_file


def test_resolve_broker_statement_path_workspace_preference(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws_file = workspace / "broker_statement.csv"
    ws_file.write_text("workspace-statement")

    monkeypatch.setenv("KARKINOS_WORKSPACE", str(workspace))
    assert resolve_broker_statement_path("broker_statement.csv") == ws_file.resolve()


def test_resolve_broker_statement_path_fallback(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "empty_workspace"
    workspace.mkdir()
    monkeypatch.setenv("KARKINOS_WORKSPACE", str(workspace))

    resolved = resolve_broker_statement_path("non_existent.csv")
    assert resolved == (workspace / "non_existent.csv").resolve()


def test_server_account_roll_forward_resolves_relative_path(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    stmt = workspace / "broker_statement.csv"
    stmt.write_text(STATEMENT, encoding="utf-8")
    monkeypatch.setenv("KARKINOS_WORKSPACE", str(workspace))

    class EmptyLedger:
        def get_ledger_entries_sync(self, *, limit, offset):
            assert (limit, offset) == (5000, 0)
            return []

    # Without collector, it resolves raw config.path via resolve_broker_statement_path
    result = roll_forward_daily_broker_statement_for_state(
        state=SimpleNamespace(
            config=SimpleNamespace(
                broker_statement_collector=BrokerStatementCollectorConfig(
                    enabled=True,
                    daily_snapshot_roll_forward_enabled=True,
                    path="broker_statement.csv",
                )
            ),
            db=EmptyLedger(),
        ),
        run_date="2026-08-21",
    )

    assert result.status == "rolled_forward"
    assert "karkinos-daily-roll-forward-20260821-cash" in stmt.read_text(
        encoding="utf-8"
    )
