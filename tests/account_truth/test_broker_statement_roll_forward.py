from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace

from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.broker_statement_roll_forward import (
    DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX,
    roll_forward_daily_broker_statement,
    roll_forward_daily_broker_statement_for_state,
)
from server.config import BrokerStatementCollectorConfig

STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
cash-anchor,cash_snapshot,2026-08-10T15:00:00+08:00,2026-08-10,,,,CNY,0,0,0,0,0,0,1000,,,
position-anchor,position_snapshot,2026-08-10T15:00:00+08:00,2026-08-10,SYN001,Synthetic Stock,stock,CNY,0,10,0,0,0,0,,10,10,source position
sell-001,trade_sell,2026-08-17T10:00:00+08:00,,SYN001,Synthetic Stock,stock,CNY,10,12,120,1,1,118,,0,0,source sell
"""


def test_daily_snapshot_roll_forward_is_deterministic_and_replaces_prior_day(
    tmp_path,
) -> None:
    path = tmp_path / "broker_statement.csv"
    path.write_text(STATEMENT, encoding="utf-8")

    first = roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    first_bytes = path.read_bytes()
    replay = roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )

    assert first.status == "rolled_forward"
    assert first.generated_cash_snapshot_count == 1
    assert first.generated_position_snapshot_count == 1
    assert replay.status == "unchanged"
    assert path.read_bytes() == first_bytes

    preview = parse_broker_statement_csv(first_bytes)
    assert preview.validation_status == "pass"
    assert len(preview.events) == 5
    generated = [
        event
        for event in preview.events
        if event.event_id.startswith(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX)
    ]
    assert {event.event_type for event in generated} == {
        "cash_snapshot",
        "position_snapshot",
    }
    cash = next(event for event in generated if event.event_type == "cash_snapshot")
    position = next(
        event for event in generated if event.event_type == "position_snapshot"
    )
    assert cash.cash_balance is not None
    assert str(cash.cash_balance) == "1118"
    assert position.position_quantity is not None
    assert str(position.position_quantity) == "0"
    assert cash.occurred_at == "2026-08-21T08:45:00+08:00"
    assert position.occurred_at == cash.occurred_at

    next_day = roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    next_preview = parse_broker_statement_csv(path.read_bytes())

    assert next_day.status == "rolled_forward"
    assert next_day.source_fact_fingerprint == first.source_fact_fingerprint
    assert len(next_preview.events) == 5
    assert all(
        event.occurred_at == "2026-08-24T08:45:00+08:00"
        for event in next_preview.events
        if event.event_id.startswith(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX)
    )


def test_daily_snapshot_roll_forward_fails_closed_on_future_source_event(tmp_path):
    path = tmp_path / "broker_statement.csv"
    content = STATEMENT.replace(
        "2026-08-17T10:00:00+08:00",
        "2026-08-21T10:00:00+08:00",
    )
    path.write_text(content, encoding="utf-8")

    result = roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )

    assert result.status == "blocked"
    assert result.blocker == "daily_snapshot_roll_forward_source_after_decision_cutoff"
    assert path.read_text(encoding="utf-8") == content


def test_daily_snapshot_roll_forward_fails_closed_on_newer_ledger_fact(tmp_path):
    path = tmp_path / "broker_statement.csv"
    path.write_text(STATEMENT, encoding="utf-8")
    os.utime(path, (1787280000, 1787280000))

    result = roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
        ledger_entries=[
            {
                "timestamp": "2026-08-18T10:00:00+08:00",
                "created_at": "2026-08-18T10:01:00+08:00",
            }
        ],
    )

    assert result.status == "blocked"
    assert result.blocker == (
        "daily_snapshot_roll_forward_source_predates_latest_ledger_event"
    )
    assert DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX not in path.read_text(
        encoding="utf-8"
    )


def test_state_roll_forward_is_explicitly_enabled_and_non_authorizing(tmp_path):
    path = tmp_path / "broker_statement.csv"
    path.write_text(STATEMENT, encoding="utf-8")

    class EmptyLedger:
        def get_ledger_entries_sync(self, *, limit, offset):
            assert (limit, offset) == (5000, 0)
            return []

    disabled = roll_forward_daily_broker_statement_for_state(
        state=SimpleNamespace(
            config=SimpleNamespace(
                broker_statement_collector=BrokerStatementCollectorConfig(
                    enabled=True,
                    path=str(path),
                )
            ),
            db=EmptyLedger(),
        ),
        run_date="2026-08-21",
    )
    enabled = roll_forward_daily_broker_statement_for_state(
        state=SimpleNamespace(
            config=SimpleNamespace(
                broker_statement_collector=BrokerStatementCollectorConfig(
                    enabled=True,
                    daily_snapshot_roll_forward_enabled=True,
                    path=str(path),
                )
            ),
            db=EmptyLedger(),
        ),
        run_date="2026-08-21",
    )

    assert disabled.status == "disabled"
    assert enabled.status == "rolled_forward"
    assert enabled.provider_contacted is False
    assert enabled.production_ledger_mutated is False
    assert enabled.broker_submission_enabled is False
    assert enabled.authorizes_execution is False
    assert enabled.changes_capital_authority is False


def test_daily_snapshot_roll_forward_rejects_ledger_revision_after_source_refresh(
    tmp_path,
) -> None:
    path = tmp_path / "broker_statement.csv"
    path.write_text(STATEMENT, encoding="utf-8")
    modified_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()

    result = roll_forward_daily_broker_statement(
        path=path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
        ledger_entries=[
            {
                "timestamp": "2026-08-17T10:00:00+08:00",
                "created_at": modified_at.replace(
                    year=modified_at.year + 1
                ).isoformat(),
            }
        ],
    )

    assert result.status == "blocked"
    assert result.blocker == (
        "daily_snapshot_roll_forward_source_predates_latest_ledger_revision"
    )
