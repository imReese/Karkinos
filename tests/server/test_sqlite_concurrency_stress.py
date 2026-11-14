"""Stress testing SQLite concurrency under simultaneous multi-threading and multi-processing."""

from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest

from server.persistence.connection import (
    connect_sqlite,
    immediate_transaction,
    run_immediate_transaction,
)


def _init_test_db(db_path: Path) -> None:
    with closing(connect_sqlite(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        with immediate_transaction(conn):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stress_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id TEXT NOT NULL,
                    op_seq INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stress_accounts (
                    account_id TEXT PRIMARY KEY,
                    balance REAL NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO stress_accounts VALUES ('primary', 0.0)"
            )


def test_multithreaded_concurrent_read_write(tmp_path: Path):
    """Verify 10 concurrent threads (writers + readers) run without lock contention."""
    db_path = tmp_path / "stress_threads.db"
    _init_test_db(db_path)

    errors: list[Exception] = []
    thread_count = 10
    ops_per_thread = 40

    def worker(worker_num: int):
        conn = connect_sqlite(db_path)
        try:
            for op in range(ops_per_thread):
                if worker_num % 2 == 0:
                    # Writer thread
                    def write_op():
                        conn.execute(
                            "INSERT INTO stress_ledger (worker_id, op_seq, amount, created_at) VALUES (?, ?, ?, ?)",
                            (f"thread_{worker_num}", op, 10.0, time.time()),
                        )
                        conn.execute(
                            "UPDATE stress_accounts SET balance = balance + 10.0 WHERE account_id = 'primary'"
                        )

                    run_immediate_transaction(conn, write_op)
                else:
                    # Reader thread
                    cursor = conn.execute(
                        "SELECT COUNT(*), SUM(amount) FROM stress_ledger"
                    )
                    cursor.fetchone()
                    acc_cursor = conn.execute(
                        "SELECT balance FROM stress_accounts WHERE account_id = 'primary'"
                    )
                    acc_cursor.fetchone()
                time.sleep(0.001)
        except Exception as exc:
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert not errors, f"Encountered thread concurrency errors: {errors}"

    with closing(connect_sqlite(db_path, readonly=True)) as verify_conn:
        write_workers = sum(1 for i in range(thread_count) if i % 2 == 0)
        expected_rows = write_workers * ops_per_thread
        expected_balance = expected_rows * 10.0

        actual_rows = verify_conn.execute(
            "SELECT COUNT(*) FROM stress_ledger"
        ).fetchone()[0]
        actual_balance = verify_conn.execute(
            "SELECT balance FROM stress_accounts WHERE account_id = 'primary'"
        ).fetchone()[0]

        assert actual_rows == expected_rows
        assert abs(actual_balance - expected_balance) < 1e-4


def _mp_writer_worker(
    db_path_str: str, worker_id: int, ops: int, result_queue: mp.Queue
) -> None:
    """Isolated process worker opening its own SQLite connection."""
    conn = connect_sqlite(db_path_str)
    try:
        for op in range(ops):

            def write_tx():
                conn.execute(
                    "INSERT INTO stress_ledger (worker_id, op_seq, amount, created_at) VALUES (?, ?, ?, ?)",
                    (f"proc_{worker_id}", op, 25.0, time.time()),
                )
                conn.execute(
                    "UPDATE stress_accounts SET balance = balance + 25.0 WHERE account_id = 'primary'"
                )

            run_immediate_transaction(conn, write_tx)
            time.sleep(0.002)
        result_queue.put(("ok", worker_id))
    except Exception as exc:
        result_queue.put(("error", str(exc)))
    finally:
        conn.close()


def _mp_reader_worker(
    db_path_str: str, worker_id: int, ops: int, result_queue: mp.Queue
) -> None:
    """Isolated process reader reading while processes write."""
    conn = connect_sqlite(db_path_str, readonly=True)
    try:
        for _ in range(ops):
            conn.execute("SELECT COUNT(*), SUM(amount) FROM stress_ledger").fetchone()
            conn.execute(
                "SELECT balance FROM stress_accounts WHERE account_id = 'primary'"
            ).fetchone()
            time.sleep(0.002)
        result_queue.put(("ok", f"reader_{worker_id}"))
    except Exception as exc:
        result_queue.put(("error", str(exc)))
    finally:
        conn.close()


def test_multiprocess_concurrent_read_write(tmp_path: Path):
    """Verify independent OS processes competing for SQLite WAL database run with zero lock errors."""
    db_path = tmp_path / "stress_process.db"
    _init_test_db(db_path)

    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()

    writer_count = 3
    reader_count = 2
    ops_per_process = 25

    processes: list[mp.Process] = []
    for wid in range(writer_count):
        p = ctx.Process(
            target=_mp_writer_worker,
            args=(str(db_path), wid, ops_per_process, result_queue),
        )
        processes.append(p)

    for rid in range(reader_count):
        p = ctx.Process(
            target=_mp_reader_worker,
            args=(str(db_path), rid, ops_per_process, result_queue),
        )
        processes.append(p)

    for p in processes:
        p.start()

    for p in processes:
        p.join(timeout=20.0)

    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    assert len(results) == writer_count + reader_count
    for status, detail in results:
        assert status == "ok", f"Process worker failed: {detail}"

    # Verify final balance and row count
    with closing(connect_sqlite(db_path, readonly=True)) as verify_conn:
        expected_rows = writer_count * ops_per_process
        expected_balance = expected_rows * 25.0

        actual_rows = verify_conn.execute(
            "SELECT COUNT(*) FROM stress_ledger"
        ).fetchone()[0]
        actual_balance = verify_conn.execute(
            "SELECT balance FROM stress_accounts WHERE account_id = 'primary'"
        ).fetchone()[0]

        assert actual_rows == expected_rows
        assert abs(actual_balance - expected_balance) < 1e-4
