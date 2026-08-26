from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.contracts.portfolio_cash_flows import (
    CashFlowCorrectionWrite,
    CashFlowWrite,
)
from server.ledger.models import LedgerEntry
from server.persistence.financial_facts_portfolio import PortfolioFactsRepositoryMixin
from server.persistence.initializer import initialize_database
from server.persistence.portfolio_cash_flow_uow import PortfolioCashFlowUnitOfWork
from server.persistence.schema_v1 import initialize_v1_baseline_schema
from server.projections.service import build_portfolio_projection
from server.services.portfolio_cash_flow_commands import PortfolioCashFlowCommandService

pytestmark = pytest.mark.unit

NOW = "2026-08-26T10:00:00+08:00"


def _cash_flow(
    *,
    command_id: str = "cash-flow-command-1",
    operator_id: str = "human-operator",
    flow_type: str = "deposit",
    amount: float = 100.0,
    timestamp: str = NOW,
    note: str = "deterministic cash flow",
) -> CashFlowWrite:
    return CashFlowWrite(
        command_id=command_id,
        operator_id=operator_id,
        timestamp=timestamp,
        amount=amount,
        flow_type=flow_type,
        note=note,
    )


def _valuation_writer(calls: list[dict], *, fail: bool = False):
    def write(conn: sqlite3.Connection, **kwargs):
        candidate_rows = kwargs.get("candidate_ledger_rows")
        assert isinstance(candidate_rows, list) and len(candidate_rows) == 1
        candidate = dict(candidate_rows[0])
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


def _count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _valuation_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT value_json FROM runtime_controls WHERE key = 'test_valuation'"
        ).fetchone()
    return int(row[0]) if row is not None else 0


def _ledger_rows(path: Path) -> list[dict]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM ledger_entries ORDER BY timestamp, id"
            ).fetchall()
        ]


class _PortfolioRepository(PortfolioFactsRepositoryMixin):
    def __init__(self, path: Path, writer) -> None:
        self._path = path
        self._valuation_transaction_writer = writer

    @staticmethod
    def _now() -> datetime:
        return datetime.fromisoformat(NOW)

    def get_ledger_entries_sync(self, limit=50, offset=0):
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM ledger_entries
                ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]


def test_cash_flow_commits_ledger_projection_and_valuation_atomically(tmp_path) -> None:
    path = tmp_path / "cash-flow.db"
    initialize_database(path)
    calls: list[dict] = []
    result = PortfolioCashFlowUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer(calls),
    ).record(_cash_flow())

    assert result.cash_flow["id"] == 1
    assert result.ledger_entry_id == 1
    assert _count(path, "cash_flows") == 1
    assert _count(path, "ledger_entries") == 1
    assert _count(path, "event_log") == 1
    assert _valuation_count(path) == 1
    assert calls[0]["source"] == "portfolio_cash_flow"
    assert calls[0]["source_ref"] == "cash_flow:1"


def test_app_database_cash_flow_uses_real_transaction_valuation_writer(
    tmp_path,
) -> None:
    from server.db import AppDatabase

    database = AppDatabase(tmp_path / "cash-flow-production-writer.db")
    database.init_sync()
    result = database.record_cash_flow_sync(_cash_flow())
    publication = database.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "ready"
    snapshot = database.get_valuation_snapshot_sync(publication["snapshot_id"])
    assert snapshot is not None
    assert snapshot["ledger_cutoff_id"] == result.ledger_entry_id

    correction = database.correct_cash_flow_sync(
        CashFlowCorrectionWrite(
            command_id="cash-flow-correction-command-1",
            operator_id="human-operator",
            cash_flow_id=int(result.cash_flow["id"]),
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


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), float("-inf")])
def test_cash_flow_rejects_non_finite_amount_before_persistence(
    tmp_path,
    amount: float,
) -> None:
    from server.db import AppDatabase

    database = AppDatabase(tmp_path / "cash-flow-non-finite.db")
    database.init_sync()

    with pytest.raises(ValueError, match="finite and positive"):
        database.record_cash_flow_sync(_cash_flow(amount=amount))

    assert _count(database.path, "cash_flows") == 0
    assert _count(database.path, "ledger_entries") == 0


@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_cash_flow_projection",
        "after_claim",
        "after_ledger_entry",
        "after_valuation",
        "after_claim_completion",
        "before_record_commit",
    ],
)
def test_cash_flow_stage_failure_rolls_back_and_retry_has_no_duplicate(
    tmp_path,
    failure_stage,
) -> None:
    path = tmp_path / f"cash-flow-{failure_stage}.db"
    initialize_database(path)
    calls: list[dict] = []

    def inject(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError(f"fault:{stage}")

    with pytest.raises(RuntimeError, match=f"fault:{failure_stage}"):
        PortfolioCashFlowUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer(calls),
            failure_injector=inject,
        ).record(_cash_flow())

    assert _count(path, "cash_flows") == 0
    assert _count(path, "ledger_entries") == 0
    assert _count(path, "event_log") == 0
    assert _count(path, "valuation_snapshots") == 0
    assert _valuation_count(path) == 0
    assert _count(path, "portfolio_mutation_claims") == 0

    PortfolioCashFlowUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_valuation_writer(calls),
    ).record(_cash_flow())
    assert _count(path, "cash_flows") == 1
    assert _count(path, "ledger_entries") == 1
    assert _valuation_count(path) == 1
    assert _count(path, "portfolio_mutation_claims") == 1


def test_cash_flow_valuation_failure_rolls_back_partial_valuation_write(
    tmp_path,
) -> None:
    path = tmp_path / "cash-flow-valuation-failure.db"
    initialize_database(path)
    with pytest.raises(RuntimeError, match="valuation publication failed"):
        PortfolioCashFlowUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=_valuation_writer([], fail=True),
        ).record(_cash_flow())

    assert _count(path, "cash_flows") == 0
    assert _count(path, "ledger_entries") == 0
    assert _count(path, "event_log") == 0
    assert _count(path, "valuation_snapshots") == 0
    assert _valuation_count(path) == 0
    assert _count(path, "portfolio_mutation_claims") == 0


def test_cash_flow_command_claim_replays_exactly_and_keeps_legitimate_duplicates(
    tmp_path,
) -> None:
    path = tmp_path / "cash-flow-command-claims.db"
    initialize_database(path)
    writer = _valuation_writer([])
    uow = PortfolioCashFlowUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    )
    command = _cash_flow()
    first = uow.record(command)
    replay = PortfolioCashFlowUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).record(command)
    assert replay.replayed is True
    assert replay.ledger_entry_id == first.ledger_entry_id

    with pytest.raises(ValueError, match="different request"):
        uow.record(replace(command, amount=101.0))

    duplicate = uow.record(replace(command, command_id="cash-flow-command-2"))
    assert duplicate.replayed is False
    assert duplicate.ledger_entry_id != first.ledger_entry_id
    assert _count(path, "cash_flows") == 2
    assert _count(path, "ledger_entries") == 2
    assert _count(path, "portfolio_mutation_claims") == 2


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
def test_cash_flow_correction_is_append_only_atomic_and_replay_safe(
    tmp_path,
    failure_stage,
) -> None:
    path = tmp_path / f"cash-flow-correction-{failure_stage}.db"
    initialize_database(path)
    calls: list[dict] = []
    writer = _valuation_writer(calls)
    PortfolioCashFlowUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).record(_cash_flow())

    def inject(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError(f"fault:{stage}")

    with pytest.raises(RuntimeError, match=f"fault:{failure_stage}"):
        PortfolioCashFlowUnitOfWork(
            path,
            now=lambda: NOW,
            valuation_transaction_writer=writer,
            failure_injector=inject,
        ).correct(
            CashFlowCorrectionWrite(
                command_id="cash-flow-correction-command-1",
                operator_id="human-operator",
                cash_flow_id=1,
            )
        )

    assert _count(path, "cash_flows") == 1
    assert _count(path, "ledger_entries") == 1
    assert _valuation_count(path) == 1
    assert _count(path, "portfolio_mutation_claims") == 1

    retry_uow = PortfolioCashFlowUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    )
    correction_command = CashFlowCorrectionWrite(
        command_id="cash-flow-correction-command-1",
        operator_id="human-operator",
        cash_flow_id=1,
    )
    corrected = retry_uow.correct(correction_command)
    replay = PortfolioCashFlowUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    ).correct(correction_command)

    assert corrected.replayed is False
    assert replay.replayed is True
    assert replay.correction_ledger_entry_id == corrected.correction_ledger_entry_id
    assert _count(path, "cash_flows") == 1
    assert _count(path, "ledger_entries") == 2
    assert _valuation_count(path) == 2
    assert _count(path, "portfolio_mutation_claims") == 2
    projection = build_portfolio_projection(
        [LedgerEntry.from_row(row) for row in _ledger_rows(path)]
    )
    assert projection.cash == 0
    assert projection.total_deposits == 0
    with pytest.raises(ValueError, match="already corrected"):
        retry_uow.correct(
            replace(correction_command, command_id="cash-flow-correction-command-2")
        )


def test_cash_flow_correction_replay_rejects_projection_drift(tmp_path) -> None:
    path = tmp_path / "cash-flow-correction-replay-drift.db"
    initialize_database(path)
    writer = _valuation_writer([])
    uow = PortfolioCashFlowUnitOfWork(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=writer,
    )
    uow.record(_cash_flow())
    command = CashFlowCorrectionWrite(
        command_id="cash-flow-correction-command-1",
        operator_id="human-operator",
        cash_flow_id=1,
    )
    uow.correct(command)

    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE cash_flows SET amount = 999 WHERE id = 1")
        conn.commit()

    with pytest.raises(RuntimeError, match="drifted from canonical ledger"):
        uow.correct(command)
    assert _count(path, "ledger_entries") == 2
    assert _count(path, "portfolio_mutation_claims") == 2


def test_cash_flow_public_read_filters_corrections_and_rebuilds_from_ledger(
    tmp_path,
) -> None:
    path = tmp_path / "cash-flow-public.db"
    initialize_database(path)
    repository = _PortfolioRepository(path, _valuation_writer([]))
    repository.record_cash_flow_sync(_cash_flow(amount=100.0))
    repository.record_cash_flow_sync(
        _cash_flow(
            command_id="cash-flow-command-2",
            flow_type="withdraw",
            amount=30.0,
            timestamp="2026-08-26T11:00:00+08:00",
            note="withdrawal",
        )
    )
    repository.correct_cash_flow_sync(
        CashFlowCorrectionWrite(
            command_id="cash-flow-correction-command-1",
            operator_id="human-operator",
            cash_flow_id=1,
        )
    )

    active = repository.get_cash_flows_sync()
    assert [row["id"] for row in active] == [2]
    assert repository.get_total_deposits_sync() == -30.0
    assert _count(path, "cash_flows") == 2

    installed = []
    state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0.0, assets=[]),
        db=repository,
        scheduler=SimpleNamespace(
            is_running=True,
            latest_quotes={},
            install_runtime_portfolio=installed.append,
        ),
    )
    PortfolioCashFlowCommandService(state)._refresh_runtime_projection()
    assert len(installed) == 1
    assert float(installed[0].cash) == -30.0


def test_cash_flow_projection_drift_fails_closed_while_ledger_remains_authority(
    tmp_path,
) -> None:
    path = tmp_path / "cash-flow-drift.db"
    initialize_database(path)
    repository = _PortfolioRepository(path, _valuation_writer([]))
    repository.record_cash_flow_sync(_cash_flow())
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE cash_flows SET amount = 999 WHERE id = 1")
        conn.commit()

    with pytest.raises(RuntimeError, match="drifted from canonical ledger"):
        repository.get_cash_flows_sync()
    with pytest.raises(RuntimeError, match="drifted from canonical ledger"):
        repository.correct_cash_flow_sync(
            CashFlowCorrectionWrite(
                command_id="cash-flow-correction-command-1",
                operator_id="human-operator",
                cash_flow_id=1,
            )
        )
    assert repository.get_total_deposits_sync() == 100.0
    assert _count(path, "ledger_entries") == 1


def test_cash_flow_migration_canonicalizes_legacy_rows_without_duplicates(
    tmp_path,
) -> None:
    path = tmp_path / "cash-flow-migration.db"
    with sqlite3.connect(path) as conn:
        initialize_v1_baseline_schema(conn)
        conn.execute(
            """
            INSERT INTO cash_flows (timestamp, amount, flow_type, note, created_at)
            VALUES (?, 100, 'deposit', 'legacy deposit', ?),
                   (?, 30, 'withdraw', 'legacy withdraw', ?)
            """,
            (NOW, NOW, "2026-08-26T11:00:00+08:00", NOW),
        )
        conn.commit()

    initialize_database(path)
    initialize_database(path)
    rows = _ledger_rows(path)
    assert [(row["entry_type"], row["amount"]) for row in rows] == [
        ("cash_deposit", 100.0),
        ("cash_withdrawal", 30.0),
    ]
    assert [row["source_ref"] for row in rows] == ["cash_flow:1", "cash_flow:2"]
    assert _count(path, "event_log") == 2


def test_cash_flow_migration_rejects_invalid_orphaned_legacy_fact(tmp_path) -> None:
    path = tmp_path / "invalid-cash-flow-migration.db"
    with sqlite3.connect(path) as conn:
        initialize_v1_baseline_schema(conn)
        conn.execute(
            """
            INSERT INTO cash_flows (timestamp, amount, flow_type, note, created_at)
            VALUES (?, -100, 'deposit', 'invalid legacy row', ?)
            """,
            (NOW, NOW),
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match="legacy portfolio cash flow cannot be canonicalized safely",
    ):
        initialize_database(path)
    assert _count(path, "ledger_entries") == 0
