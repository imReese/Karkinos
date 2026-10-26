"""Withdraw exact corrupted evidence without rewriting its financial history."""

from __future__ import annotations

import sqlite3

import pytest

from server.contracts.strategy_research import backtest_evidence_blocker
from server.persistence import migrations
from server.persistence.backtest_results import (
    V25_BACKTEST_INVALIDATIONS,
    BacktestResultsRepository,
    backtest_row_fingerprint,
    insert_backtest_result,
)
from server.persistence.schema_v1 import initialize_v1_baseline_schema

pytestmark = pytest.mark.unit


def raw_row(path, result_id):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return dict(
            conn.execute(
                "SELECT * FROM backtest_results WHERE id=?", (result_id,)
            ).fetchone()
        )


def insert_fixture(conn):
    return insert_backtest_result(
        conn,
        created_at="2026-01-02T00:00:00+00:00",
        config_json="{}",
        initial_cash=1000,
        final_equity=1000,
        total_return=0,
        sharpe=0,
        max_dd=0,
        equity_curve_json="[]",
    )


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        initialize_v1_baseline_schema(conn)
        for statement in V25_BACKTEST_INVALIDATIONS:
            conn.execute(statement)
        result_id = insert_fixture(conn)
    return path, result_id, BacktestResultsRepository(path)


def invalidate(repo, result_id, fingerprint, **overrides):
    args = dict(
        result_id=result_id,
        expected_row_fingerprint=fingerprint,
        actor="fixture-reviewer",
        reason="Recorded fills contradict the saved financial curve.",
        idempotency_key="withdraw-corrupted-evidence",
    )
    args.update(overrides)
    return repo.append_invalidation_sync(**args)


def test_v24_to_v25_keeps_original_rows_and_migration_history(tmp_path, monkeypatch):
    path = tmp_path / "v24.db"
    with sqlite3.connect(path) as conn:
        initialize_v1_baseline_schema(conn)
        with monkeypatch.context() as context:
            context.setattr(
                migrations,
                "_MIGRATIONS",
                tuple(m for m in migrations.migration_registry() if m.version <= 24),
            )
            migrations.apply_schema_migrations(
                conn, baseline_initializer=initialize_v1_baseline_schema
            )
        result_id = insert_fixture(conn)
    before = raw_row(path, result_id)
    with sqlite3.connect(path) as conn:
        history = conn.execute(
            "SELECT * FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert history[-1][0] == 24
        migrations.apply_schema_migrations(
            conn, baseline_initializer=initialize_v1_baseline_schema
        )
        assert (
            conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            == 25
        )
        assert (
            conn.execute(
                "SELECT * FROM schema_migrations WHERE version<=24 ORDER BY version"
            ).fetchall()
            == history
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM backtest_result_invalidations"
            ).fetchone()[0]
            == 0
        )
    assert raw_row(path, result_id) == before


@pytest.mark.asyncio
async def test_append_is_idempotent_preserves_raw_and_marks_get_and_list(saved):
    path, result_id, repo = saved
    before = raw_row(path, result_id)
    fingerprint = backtest_row_fingerprint(before)
    assert (await repo.get_result(result_id))["evidence_invalidation"] is None
    first = invalidate(repo, result_id, fingerprint)
    assert invalidate(repo, result_id, fingerprint) == first
    assert raw_row(path, result_id) == before
    row = await repo.get_result(result_id)
    assert row["evidence_invalidation"]["status"] == "invalidated"
    assert backtest_row_fingerprint(row) == fingerprint
    assert backtest_evidence_blocker(row) == "backtest_evidence_invalidated"
    assert (await repo.list_results())[0]["evidence_invalidation"] == row[
        "evidence_invalidation"
    ]
    with pytest.raises(ValueError, match="idempotency conflict"):
        invalidate(
            repo,
            result_id,
            fingerprint,
            reason="A different review cannot replace the original.",
        )


def test_source_compare_before_append_rejects_changed_row(saved):
    path, result_id, repo = saved
    fingerprint = backtest_row_fingerprint(raw_row(path, result_id))
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE backtest_results SET final_equity=999 WHERE id=?", (result_id,)
        )
    with pytest.raises(ValueError, match="source fingerprint changed"):
        invalidate(repo, result_id, fingerprint)
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM backtest_result_invalidations"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE backtest_result_invalidations SET reason='replacement'",
        "DELETE FROM backtest_result_invalidations",
        "INSERT OR REPLACE INTO backtest_result_invalidations SELECT result_id,row_fingerprint,actor,'replacement',idempotency_key,created_at FROM backtest_result_invalidations",
    ],
)
def test_invalidations_are_append_only_even_for_sql_replace(saved, statement):
    path, result_id, repo = saved
    invalidate(repo, result_id, backtest_row_fingerprint(raw_row(path, result_id)))
    with (
        sqlite3.connect(path) as conn,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        conn.execute(statement)


@pytest.mark.asyncio
async def test_changed_invalidated_row_cannot_escape_denial(saved):
    path, result_id, repo = saved
    invalidate(repo, result_id, backtest_row_fingerprint(raw_row(path, result_id)))
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE backtest_results SET metrics_json=? WHERE id=?",
            ('{"claimed":"repaired"}', result_id),
        )
    row = await repo.get_result(result_id)
    assert row["evidence_invalidation"]["status"] == "fingerprint_mismatch"
    assert backtest_evidence_blocker(row) == "backtest_evidence_fingerprint_mismatch"


@pytest.mark.asyncio
async def test_unmigrated_read_preserves_raw_but_blocks_financial_use(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        initialize_v1_baseline_schema(conn)
        result_id = insert_fixture(conn)
    row = await BacktestResultsRepository(path).get_result(result_id)
    assert row["total_return"] == 0
    assert backtest_evidence_blocker(row) == "backtest_evidence_unavailable"
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='backtest_result_invalidations'"
            ).fetchone()
            is None
        )
