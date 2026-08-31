from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from server.contracts.portfolio_trades import (
    ManualTradeCorrectionWrite,
    ManualTradeWrite,
    PendingFundConfirmationWrite,
    PendingFundOrderWrite,
)
from server.ledger.models import LedgerEntry
from server.persistence.initializer import initialize_database
from server.persistence.manual_trade_uow import ManualTradeUnitOfWork
from server.persistence.pending_fund_confirmation_uow import (
    PendingFundConfirmationUnitOfWork,
)
from server.persistence.schema_v1 import initialize_v1_baseline_schema
from server.projections.service import build_portfolio_projection

pytestmark = pytest.mark.unit

NOW = "2026-08-26T10:00:00+08:00"


def _manual_trade(
    *,
    command_id: str = "manual-trade-command-1",
    operator_id: str = "human-operator",
) -> ManualTradeWrite:
    return ManualTradeWrite(
        command_id=command_id,
        operator_id=operator_id,
        timestamp=NOW,
        symbol="600000.SH",
        display_name="浦发银行",
        direction="buy",
        quantity=10.0,
        price=10.0,
        commission=1.0,
        gross_amount=100.0,
        net_cash_impact=-101.0,
        fee_breakdown_json=json.dumps(
            {
                "commission": "1",
                "stamp_tax": "0",
                "transfer_fee": "0",
                "other_fees": "0",
                "total_fee": "1",
            },
            sort_keys=True,
        ),
        fee_rule_id="manual_fee_input",
        fee_rule_version="manual_fee_input",
        asset_class="stock",
        note="deterministic manual trade",
    )


def _pending_order(
    *,
    command_id: str = "pending-fund-command-1",
    operator_id: str = "human-operator",
) -> PendingFundOrderWrite:
    return PendingFundOrderWrite(
        command_id=command_id,
        operator_id=operator_id,
        submitted_at=NOW,
        symbol="012999",
        display_name="示例稳健混合C",
        amount=200.0,
        commission=1.0,
        asset_class="fund",
        target_trade_date="2026-08-26",
        note="explicit subscription",
    )


def _confirmation(
    run_id: str = "manual-nav-run-1",
    *,
    command_id: str = "pending-confirm-command-1",
    operator_id: str = "human-operator",
) -> PendingFundConfirmationWrite:
    return PendingFundConfirmationWrite(
        command_id=command_id,
        operator_id=operator_id,
        order_id=1,
        evidence_fetch_run_id=run_id,
        confirmation_note="reviewed persisted NAV evidence",
    )


def _valuation_writer(
    calls: list[dict[str, object]],
    *,
    fail: bool = False,
) -> Callable[..., dict[str, object]]:
    def write(conn: sqlite3.Connection, **kwargs) -> dict[str, object]:
        candidate_rows = kwargs.get("candidate_ledger_rows")
        assert isinstance(candidate_rows, list) and len(candidate_rows) == 1
        candidate = dict(candidate_rows[0])
        assert int(candidate["id"]) > 0
        calls.append(candidate)
        current = conn.execute(
            "SELECT value_json FROM runtime_controls WHERE key = 'test_valuation'"
        ).fetchone()
        count = int(current[0]) + 1 if current is not None else 1
        conn.execute(
            """
            INSERT INTO runtime_controls (key, value_json, updated_at)
            VALUES ('test_valuation', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (str(count), NOW),
        )
        snapshot_id = f"test-{count}"
        conn.execute(
            """
            INSERT INTO valuation_snapshots (
                snapshot_id, as_of, trade_date, valuation_policy,
                ledger_cutoff_id, ledger_fingerprint, quote_set_fingerprint,
                status, quotes_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                NOW,
                "2026-08-26",
                "test",
                int(candidate["id"]),
                f"test-ledger-{candidate['id']}-{count}",
                "test-quotes",
                "ready",
                "[]",
                "{}",
                NOW,
            ),
        )
        if fail:
            raise RuntimeError("valuation publication failed")
        return {"snapshot_id": snapshot_id, "status": "ready"}

    return write


def _count(path: Path, table: str, where: str = "") -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0])


def _valuation_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT value_json FROM runtime_controls WHERE key = 'test_valuation'"
        ).fetchone()
    return int(row[0]) if row is not None else 0


def _ledger_rows(path: Path) -> list[dict[str, object]]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM ledger_entries ORDER BY timestamp, id"
            ).fetchall()
        ]


def _persist_nav_evidence(
    path: Path,
    *,
    run_id: str = "manual-nav-run-1",
    manual_explicit_trigger: bool = True,
    metadata: object | None = None,
    price: float = 10.0,
    nav_date: str = "2026-08-26",
    status: str = "success",
) -> None:
    run_metadata = (
        {
            "confirmation_only": True,
            "manual_explicit_trigger": manual_explicit_trigger,
        }
        if metadata is None
        else metadata
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO quote_fetch_runs (
                run_id, started_at, finished_at, trigger, provider, asset_type,
                symbol_count, success_count, failure_count, cache_hit_count,
                status, metadata_json
            ) VALUES (?, ?, ?, 'fund_nav_sync', 'fixture', 'fund', 1, 1, 0, 0,
                      ?, ?)
            """,
            (run_id, NOW, NOW, status, json.dumps(run_metadata, sort_keys=True)),
        )
        conn.commit()
    from server.db import AppDatabase

    AppDatabase(path).save_quote_snapshot_sync(
        symbol="012999",
        asset_class="fund",
        price=price,
        volume=None,
        timestamp=f"{nav_date}T15:00:00+08:00",
        quote_source="eastmoney_fund_page",
        provider_name="fixture",
        quote_status="live",
        provider_status="live",
        captured_reason="fund_nav_sync",
        nav_date=nav_date,
        fetch_run_id=run_id,
    )


def test_manual_trade_commits_canonical_ledger_projection_and_valuation(
    tmp_path,
) -> None:
    path = tmp_path / "manual.db"
    initialize_database(path)
    calls: list[dict[str, object]] = []
    result = ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer(calls),
    ).record(_manual_trade())

    assert result.trade["id"] == 1
    assert result.ledger_entry_id == 1
    assert _count(path, "trades") == 1
    assert _count(path, "ledger_entries") == 1
    assert _count(path, "event_log") == 1
    assert _valuation_count(path) == 1
    assert calls[0]["source"] == "portfolio_trade"
    assert calls[0]["source_ref"] == "trade:1"


def test_manual_trade_rejects_non_finite_financial_values_before_write(
    tmp_path,
) -> None:
    path = tmp_path / "manual-non-finite.db"
    initialize_database(path)
    command = replace(
        _manual_trade(),
        quantity=float("inf"),
        gross_amount=float("inf"),
        net_cash_impact=float("-inf"),
    )

    with pytest.raises(ValueError, match="financial values must be finite"):
        ManualTradeUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([]),
        ).record(command)

    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0


def test_manual_trade_rejects_fee_components_that_do_not_sum_before_write(
    tmp_path,
) -> None:
    path = tmp_path / "manual-inconsistent-fees.db"
    initialize_database(path)
    command = replace(
        _manual_trade(),
        commission=5.0,
        net_cash_impact=-107.0,
        fee_breakdown_json=json.dumps(
            {
                "commission": "5",
                "stamp_tax": "200",
                "transfer_fee": "0",
                "other_fees": "0",
                "total_fee": "7",
            },
            sort_keys=True,
        ),
    )

    with pytest.raises(
        ValueError,
        match="fee_breakdown components do not sum to total_fee",
    ):
        ManualTradeUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([]),
        ).record(command)

    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0


def test_manual_trade_rejects_fee_breakdown_without_commission_before_write(
    tmp_path,
) -> None:
    path = tmp_path / "manual-missing-commission.db"
    initialize_database(path)
    command = replace(
        _manual_trade(),
        net_cash_impact=-102.0,
        fee_breakdown_json=json.dumps(
            {
                "other_fees": "2",
                "total_fee": "2",
            },
            sort_keys=True,
        ),
    )

    with pytest.raises(ValueError, match="fee breakdown must include commission"):
        ManualTradeUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([]),
        ).record(command)

    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0


def test_manual_trade_rejects_unknown_fee_component_before_write(tmp_path) -> None:
    path = tmp_path / "manual-unknown-fee-component.db"
    initialize_database(path)
    command = replace(
        _manual_trade(),
        fee_breakdown_json=json.dumps(
            {
                "commission": "1",
                "stamp_tax": "0",
                "transfer_fee": "0",
                "other_fees": "0",
                "regulatory_fee": "9",
                "total_fee": "1",
            },
            sort_keys=True,
        ),
    )

    with pytest.raises(
        ValueError,
        match="fee breakdown contains unsupported components: regulatory_fee",
    ):
        ManualTradeUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([]),
        ).record(command)

    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0


def test_pending_fund_order_rejects_non_finite_amount_before_write(tmp_path) -> None:
    path = tmp_path / "pending-fund-non-finite.db"
    initialize_database(path)

    with pytest.raises(ValueError, match="financial values must be finite"):
        PendingFundConfirmationUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([]),
        ).create_pending(replace(_pending_order(), amount=float("inf")))

    assert _count(path, "pending_fund_orders") == 0


def test_app_database_manual_trade_uses_real_transaction_valuation_writer(
    tmp_path,
) -> None:
    from server.db import AppDatabase

    database = AppDatabase(tmp_path / "manual-production-writer.db")
    database.init_sync()
    result = database.record_manual_trade_sync(_manual_trade())

    publication = database.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "ready"
    snapshot = database.get_valuation_snapshot_sync(publication["snapshot_id"])
    assert snapshot is not None
    assert snapshot["ledger_cutoff_id"] == result.ledger_entry_id

    correction = database.correct_manual_trade_sync(
        ManualTradeCorrectionWrite(
            command_id="manual-correction-command-1",
            operator_id="human-operator",
            trade_id=int(result.trade["id"]),
        )
    )
    corrected_publication = database.get_runtime_control_sync(
        "valuation_snapshot_publication"
    )
    assert corrected_publication is not None
    assert corrected_publication["snapshot_id"] != publication["snapshot_id"]
    corrected_snapshot = database.get_valuation_snapshot_sync(
        corrected_publication["snapshot_id"]
    )
    assert corrected_snapshot is not None
    assert (
        corrected_snapshot["ledger_cutoff_id"] == correction.correction_ledger_entry_id
    )


@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_asset_identity",
        "after_claim",
        "after_trade_projection",
        "after_ledger_entry",
        "after_valuation",
        "after_claim_completion",
        "before_record_commit",
    ],
)
def test_manual_trade_stage_failure_rolls_back_and_retry_has_no_duplicate(
    tmp_path,
    failure_stage,
) -> None:
    path = tmp_path / f"manual-{failure_stage}.db"
    initialize_database(path)
    calls: list[dict[str, object]] = []

    def inject(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError(f"fault:{stage}")

    with pytest.raises(RuntimeError, match=f"fault:{failure_stage}"):
        ManualTradeUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer(calls),
            failure_injector=inject,
        ).record(_manual_trade())

    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0
    assert _count(path, "watchlist_assets") == 0
    assert _count(path, "instrument_metadata") == 0
    assert _count(path, "event_log") == 0
    assert _count(path, "portfolio_mutation_claims") == 0
    assert _count(path, "valuation_snapshots") == 0
    assert _valuation_count(path) == 0

    ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer(calls),
    ).record(_manual_trade())
    assert _count(path, "trades") == 1
    assert _count(path, "ledger_entries") == 1
    assert _count(path, "portfolio_mutation_claims") == 1
    assert _valuation_count(path) == 1


def test_manual_trade_valuation_failure_rolls_back_partial_valuation_write(
    tmp_path,
) -> None:
    path = tmp_path / "manual-valuation-failure.db"
    initialize_database(path)
    with pytest.raises(RuntimeError, match="valuation publication failed"):
        ManualTradeUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([], fail=True),
        ).record(_manual_trade())

    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0
    assert _count(path, "valuation_snapshots") == 0
    assert _valuation_count(path) == 0
    assert _count(path, "portfolio_mutation_claims") == 0


def test_manual_trade_command_claim_replays_exactly_and_preserves_legitimate_duplicates(
    tmp_path,
) -> None:
    path = tmp_path / "manual-command-claims.db"
    initialize_database(path)
    writer = _valuation_writer([])
    first_command = _manual_trade()
    first = ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).record(first_command)
    replay = ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).record(first_command)
    assert replay.replayed is True
    assert replay.ledger_entry_id == first.ledger_entry_id

    with pytest.raises(ValueError, match="different request"):
        ManualTradeUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=writer,
        ).record(replace(first_command, note="payload drift"))

    duplicate = ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).record(replace(first_command, command_id="manual-trade-command-2"))
    assert duplicate.replayed is False
    assert duplicate.ledger_entry_id != first.ledger_entry_id
    assert _count(path, "trades") == 2
    assert _count(path, "ledger_entries") == 2
    assert _count(path, "portfolio_mutation_claims") == 2


def test_manual_trade_replay_fails_closed_when_valuation_identity_drifts(
    tmp_path,
) -> None:
    path = tmp_path / "manual-valuation-replay-drift.db"
    initialize_database(path)
    writer = _valuation_writer([])
    command = _manual_trade()
    uow = ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    )
    uow.record(command)

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE valuation_snapshots SET status = 'blocked' WHERE snapshot_id = ?",
            ("test-1",),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="valuation result drifted"):
        uow.record(command)
    assert _count(path, "trades") == 1
    assert _count(path, "ledger_entries") == 1


@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_correction_entry",
        "after_claim",
        "after_valuation",
        "after_claim_completion",
        "before_correction_commit",
    ],
)
def test_manual_trade_correction_is_append_only_atomic_and_replay_safe(
    tmp_path,
    failure_stage,
) -> None:
    path = tmp_path / f"manual-correction-{failure_stage}.db"
    initialize_database(path)
    calls: list[dict[str, object]] = []
    writer = _valuation_writer(calls)
    ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).record(_manual_trade())

    def inject(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError(f"fault:{stage}")

    with pytest.raises(RuntimeError, match=f"fault:{failure_stage}"):
        ManualTradeUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=writer,
            failure_injector=inject,
        ).correct(
            ManualTradeCorrectionWrite(
                command_id="manual-correction-command-1",
                operator_id="human-operator",
                trade_id=1,
            )
        )

    assert _count(path, "trades") == 1
    assert _count(path, "ledger_entries") == 1
    assert _valuation_count(path) == 1
    assert _count(path, "portfolio_mutation_claims") == 1

    retry_uow = ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    )
    correction_command = ManualTradeCorrectionWrite(
        command_id="manual-correction-command-1",
        operator_id="human-operator",
        trade_id=1,
    )
    corrected = retry_uow.correct(correction_command)
    replay = ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).correct(correction_command)

    assert corrected.replayed is False
    assert replay.replayed is True
    assert replay.correction_ledger_entry_id == corrected.correction_ledger_entry_id
    assert _count(path, "trades") == 1
    assert _count(path, "ledger_entries") == 2
    assert _count(path, "portfolio_mutation_claims") == 2
    assert _valuation_count(path) == 2
    projection = build_portfolio_projection(
        [LedgerEntry.from_row(row) for row in _ledger_rows(path)]
    )
    assert projection.cash == 0
    assert projection.positions["600000.SH"].quantity == 0
    with pytest.raises(ValueError, match="already corrected"):
        retry_uow.correct(
            replace(correction_command, command_id="manual-correction-command-2")
        )


def test_manual_trade_correction_replay_rejects_projection_drift(tmp_path) -> None:
    path = tmp_path / "manual-correction-replay-drift.db"
    initialize_database(path)
    writer = _valuation_writer([])
    uow = ManualTradeUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    )
    uow.record(_manual_trade())
    command = ManualTradeCorrectionWrite(
        command_id="manual-correction-command-1",
        operator_id="human-operator",
        trade_id=1,
    )
    uow.correct(command)

    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE trades SET quantity = 999 WHERE id = 1")
        conn.commit()

    with pytest.raises(RuntimeError, match="drifted from canonical ledger"):
        uow.correct(command)
    assert _count(path, "ledger_entries") == 2
    assert _count(path, "portfolio_mutation_claims") == 2


@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_asset_identity",
        "after_claim",
        "after_pending_order",
        "after_pending_event",
        "after_claim_completion",
        "before_pending_commit",
    ],
)
def test_pending_creation_stage_failure_rolls_back_and_retry_is_idempotent(
    tmp_path,
    failure_stage,
) -> None:
    path = tmp_path / f"pending-create-{failure_stage}.db"
    initialize_database(path)

    def inject(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError(f"fault:{stage}")

    with pytest.raises(RuntimeError, match=f"fault:{failure_stage}"):
        PendingFundConfirmationUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([]),
            failure_injector=inject,
        ).create_pending(_pending_order())

    assert _count(path, "pending_fund_orders") == 0
    assert _count(path, "watchlist_assets") == 0
    assert _count(path, "instrument_metadata") == 0
    assert _count(path, "event_log") == 0
    assert _count(path, "portfolio_mutation_claims") == 0

    uow = PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer([]),
    )
    created = uow.create_pending(_pending_order())
    replay = PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer([]),
    ).create_pending(_pending_order())
    assert created.replayed is False
    assert replay.replayed is True
    assert replay.order["id"] == created.order["id"]
    assert _count(path, "pending_fund_orders") == 1
    assert _count(path, "event_log") == 1
    assert _count(path, "portfolio_mutation_claims") == 1

    duplicate = uow.create_pending(
        replace(_pending_order(), command_id="pending-fund-command-2")
    )
    assert duplicate.replayed is False
    assert duplicate.order["id"] != created.order["id"]
    assert _count(path, "pending_fund_orders") == 2
    assert _count(path, "portfolio_mutation_claims") == 2


@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_confirmation_asset_identity",
        "after_claim",
        "after_trade_projection",
        "after_ledger_entry",
        "after_pending_status",
        "after_confirmation_event",
        "after_valuation",
        "after_claim_completion",
        "before_confirmation_commit",
    ],
)
def test_pending_confirmation_stage_failure_rolls_back_and_retry_has_no_duplicate(
    tmp_path,
    failure_stage,
) -> None:
    path = tmp_path / f"pending-confirm-{failure_stage}.db"
    initialize_database(path)
    calls: list[dict[str, object]] = []
    writer = _valuation_writer(calls)
    PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).create_pending(_pending_order())
    _persist_nav_evidence(path)

    def inject(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError(f"fault:{stage}")

    with pytest.raises(RuntimeError, match=f"fault:{failure_stage}"):
        PendingFundConfirmationUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=writer,
            failure_injector=inject,
        ).confirm(_confirmation())

    with sqlite3.connect(path) as conn:
        status = conn.execute(
            "SELECT status FROM pending_fund_orders WHERE id = 1"
        ).fetchone()[0]
    assert status == "pending"
    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0
    assert _count(path, "event_log") == 3
    assert _count(path, "valuation_snapshots") == 0
    assert _valuation_count(path) == 0
    assert _count(path, "portfolio_mutation_claims") == 1

    result = PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).confirm(_confirmation())
    assert result.replayed is False
    assert _count(path, "trades") == 1
    assert _count(path, "ledger_entries") == 1
    assert _count(path, "event_log") == 5
    assert _valuation_count(path) == 1
    assert _count(path, "portfolio_mutation_claims") == 2


def test_pending_confirmation_restart_replay_binds_exact_persisted_evidence(
    tmp_path,
) -> None:
    path = tmp_path / "pending-replay.db"
    initialize_database(path)
    calls: list[dict[str, object]] = []
    writer = _valuation_writer(calls)
    PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).create_pending(_pending_order())
    _persist_nav_evidence(path)

    first = PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).confirm(_confirmation())
    replay = PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).confirm(_confirmation())

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.ledger_entry_id == first.ledger_entry_id
    assert _count(path, "trades") == 1
    assert _count(path, "ledger_entries") == 1
    assert _count(path, "event_log") == 5
    assert _valuation_count(path) == 1
    assert len(calls) == 1
    with pytest.raises(ValueError, match="already confirmed"):
        PendingFundConfirmationUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=writer,
        ).confirm(
            replace(
                _confirmation(),
                command_id="pending-confirm-command-2",
            )
        )
    with sqlite3.connect(path) as conn:
        bound = conn.execute("""
            SELECT confirmation_quote_snapshot_id, confirmation_fetch_run_id,
                   confirmed_by, confirmation_note
            FROM pending_fund_orders WHERE id = 1
            """).fetchone()
    assert bound == (
        1,
        "manual-nav-run-1",
        "human-operator",
        "reviewed persisted NAV evidence",
    )


def test_app_database_pending_confirmation_uses_real_transaction_valuation_writer(
    tmp_path,
) -> None:
    from server.db import AppDatabase

    path = tmp_path / "pending-production-writer.db"
    database = AppDatabase(path)
    database.init_sync()
    pending = database.create_pending_fund_order_sync(_pending_order())
    _persist_nav_evidence(path)
    result = database.confirm_pending_fund_order_sync(
        PendingFundConfirmationWrite(
            command_id="pending-confirm-command-1",
            operator_id="human-operator",
            order_id=int(pending.order["id"]),
            evidence_fetch_run_id="manual-nav-run-1",
            confirmation_note="reviewed persisted NAV evidence",
        )
    )

    publication = database.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "ready"
    snapshot = database.get_valuation_snapshot_sync(publication["snapshot_id"])
    assert snapshot is not None
    assert snapshot["ledger_cutoff_id"] == result.ledger_entry_id
    assert result.order["confirmation_fetch_run_id"] == "manual-nav-run-1"


def test_pending_confirmation_rejects_scheduled_or_invalid_run_metadata(
    tmp_path,
) -> None:
    scheduled_path = tmp_path / "scheduled-evidence.db"
    initialize_database(scheduled_path)
    uow = PendingFundConfirmationUnitOfWork(
        scheduled_path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer([]),
    )
    uow.create_pending(_pending_order())
    _persist_nav_evidence(scheduled_path, manual_explicit_trigger=False)

    with pytest.raises(RuntimeError, match="manual_explicit_trigger"):
        uow.confirm(_confirmation())
    assert _count(scheduled_path, "trades") == 0
    assert _count(scheduled_path, "ledger_entries") == 0

    invalid_path = tmp_path / "invalid-metadata.db"
    initialize_database(invalid_path)
    invalid_uow = PendingFundConfirmationUnitOfWork(
        invalid_path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer([]),
    )
    invalid_uow.create_pending(_pending_order())
    _persist_nav_evidence(invalid_path, metadata=["not", "an", "object"])
    with pytest.raises(RuntimeError, match="metadata is invalid"):
        invalid_uow.confirm(_confirmation())
    assert _count(invalid_path, "trades") == 0
    assert _count(invalid_path, "ledger_entries") == 0


@pytest.mark.parametrize("run_status", ["partial", "partial_success"])
def test_pending_confirmation_rejects_partial_quote_run_evidence(
    tmp_path,
    run_status: str,
) -> None:
    path = tmp_path / f"partial-evidence-{run_status}.db"
    initialize_database(path)
    uow = PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer([]),
    )
    uow.create_pending(_pending_order())
    _persist_nav_evidence(path, status=run_status)

    with pytest.raises(RuntimeError, match="run_status"):
        uow.confirm(_confirmation())

    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0
    with sqlite3.connect(path) as conn:
        status = conn.execute(
            "SELECT status FROM pending_fund_orders WHERE id = 1"
        ).fetchone()[0]
    assert status == "pending"


def test_pending_confirmation_valuation_failure_rolls_back_every_financial_fact(
    tmp_path,
) -> None:
    path = tmp_path / "pending-valuation-failure.db"
    initialize_database(path)
    PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer([]),
    ).create_pending(_pending_order())
    _persist_nav_evidence(path)

    with pytest.raises(RuntimeError, match="valuation publication failed"):
        PendingFundConfirmationUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([], fail=True),
        ).confirm(_confirmation())

    with sqlite3.connect(path) as conn:
        order = conn.execute("""
            SELECT status, trade_id, confirmation_fetch_run_id
            FROM pending_fund_orders WHERE id = 1
            """).fetchone()
    assert order == ("pending", None, None)
    assert _count(path, "trades") == 0
    assert _count(path, "ledger_entries") == 0
    assert _count(path, "event_log") == 3
    assert _count(path, "valuation_snapshots") == 0
    assert _valuation_count(path) == 0
    assert _count(path, "portfolio_mutation_claims") == 1


def test_pending_confirmation_replay_fails_closed_on_evidence_or_ledger_drift(
    tmp_path,
) -> None:
    path = tmp_path / "pending-drift.db"
    initialize_database(path)
    writer = _valuation_writer([])
    uow = PendingFundConfirmationUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    )
    uow.create_pending(_pending_order())
    _persist_nav_evidence(path)
    uow.confirm(_confirmation())
    _persist_nav_evidence(path, run_id="manual-nav-run-2")

    with pytest.raises(ValueError, match="different request"):
        uow.confirm(_confirmation("manual-nav-run-2"))

    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ledger_entries SET note = 'drifted' WHERE id = 1")
        conn.commit()
    with pytest.raises(RuntimeError, match="ledger drifted"):
        uow.confirm(_confirmation())
    assert _count(path, "trades") == 1
    assert _count(path, "ledger_entries") == 1


def test_manual_trade_migration_rejects_invalid_orphaned_legacy_fact(
    tmp_path,
) -> None:
    path = tmp_path / "invalid-manual-trade-migration.db"
    with sqlite3.connect(path) as conn:
        initialize_v1_baseline_schema(conn)
        conn.execute(
            """
            INSERT INTO trades (
                timestamp, symbol, direction, quantity, price, commission,
                asset_class, note, created_at
            ) VALUES (?, '600000.SH', 'buy', -10, 10, 1, 'stock',
                      'invalid legacy row', ?)
            """,
            (NOW, NOW),
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match="legacy portfolio trade cannot be canonicalized safely",
    ):
        initialize_database(path)
    assert _count(path, "ledger_entries") == 0
