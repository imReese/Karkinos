"""Atomic isolated paper-book writes; no shared execution or account ledger."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from analytics.paper_performance import evaluate_paper_health, paper_book_performance
from server.persistence.automation_runs import require_observation_automation_policy
from server.persistence.connection import connect_sqlite


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("paper_book_clock_timezone_required")
    return value.astimezone(timezone.utc)


class ResearchPaperBooksRepository:
    def __init__(self, database_path: str | Path, *, clock: Callable[[], datetime]):
        self.path = Path(database_path)
        self.clock = clock

    @contextmanager
    def _connect(self, *, write=False) -> Iterator[sqlite3.Connection]:
        with closing(connect_sqlite(self.path, readonly=not write)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield conn

    def get(self, observation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = self._row(conn, observation_id)
            return self._detail(conn, row) if row is not None else None

    def get_operation(self, observation_id, request_id, kind, fingerprint):
        with self._connect() as conn:
            row = self._row(conn, observation_id)
            return (
                self._receipt(conn, row, request_id, kind, fingerprint) if row else None
            )

    def start(
        self,
        *,
        book_id,
        observation_id,
        request_id,
        fingerprint,
        source,
        policy,
        code_binding,
        instruments,
        initial_cash,
        evaluation_start,
        computation_not_before,
    ):
        with self._connect(write=True) as conn:
            existing = self._row(conn, observation_id)
            replay = self._receipt(conn, existing, request_id, "start", fingerprint)
            if replay is not None:
                return replay
            if existing is not None:
                raise ValueError("paper_book_already_exists_conflict")
            observation = conn.execute(
                "SELECT lifecycle, started_at FROM research_observations WHERE id=?",
                (observation_id,),
            ).fetchone()
            if observation is None:
                raise ValueError("paper_book_observation_not_found")
            if observation["lifecycle"] != "active":
                raise ValueError("paper_book_observation_paused")
            now = _instant(self.clock())
            source_completed = conn.execute(
                "SELECT MAX(completed_at) FROM research_observation_operations WHERE observation_id=?",
                (observation_id,),
            ).fetchone()[0]
            if now < _instant(computation_not_before) or now < datetime.fromisoformat(
                source_completed or observation["started_at"]
            ):
                raise ValueError("paper_book_clock_reversed")
            if now >= datetime.combine(
                evaluation_start, time(9, 30), ZoneInfo("Asia/Shanghai")
            ):
                raise ValueError("paper_book_start_window_elapsed")
            conn.execute(
                """INSERT INTO research_paper_books
                (id, observation_id, source_json, policy_json, code_binding_json,
                 instruments_json, initial_cash, started_at, evaluation_start,
                 lifecycle, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0)""",
                (
                    book_id,
                    observation_id,
                    _json(source),
                    _json(policy),
                    _json(code_binding),
                    _json(instruments),
                    initial_cash,
                    now.isoformat(),
                    evaluation_start.isoformat(),
                ),
            )
            return self._record(
                conn, observation_id, request_id, "start", fingerprint, now
            )

    def settle(
        self,
        *,
        observation_id,
        request_id,
        fingerprint,
        expected_version,
        steps: Sequence[Mapping],
        computation_not_before: datetime,
        automation_generation=None,
        automation_stop_requested=None,
    ):
        with self._connect(write=True) as conn:
            row = self._row(conn, observation_id)
            replay = self._receipt(conn, row, request_id, "settle", fingerprint)
            if replay is not None:
                return replay
            row = self._version(row, expected_version)
            if automation_generation is not None:
                if (
                    automation_stop_requested is not None
                    and automation_stop_requested()
                ):
                    raise ValueError("paper_book_automation_stopped")
                require_observation_automation_policy(
                    conn, observation_id, automation_generation, paper_settlement=True
                )
            now = self._locked_clock(conn, row, computation_not_before)
            last = conn.execute(
                "SELECT MAX(session) FROM research_paper_steps WHERE book_id=?",
                (row["id"],),
            ).fetchone()[0]
            if not steps:
                raise ValueError("paper_book_no_new_sessions")
            for step in steps:
                if last is not None and step["session"] <= last:
                    raise ValueError("paper_book_session_conflict")
                conn.execute(
                    """INSERT INTO research_paper_steps
                    (book_id, session, book_version, dataset_id, input_json,
                     projection_json, settled_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"],
                        step["session"],
                        expected_version + 1,
                        step["dataset_id"],
                        _json(step["input"]),
                        _json(step["projection"]),
                        now.isoformat(),
                    ),
                )
                last = step["session"]
            conn.execute(
                "UPDATE research_paper_books SET version=version+1 WHERE id=?",
                (row["id"],),
            )
            updated = self._detail(conn, self._row(conn, observation_id))
            if (
                updated["health"]["action"] == "pause_paper_target_acceptance"
                and row["paused_at"] is None
            ):
                conn.execute(
                    "UPDATE research_paper_books SET lifecycle='paused', paused_at=? WHERE id=?",
                    (now.isoformat(), row["id"]),
                )
            return self._record(
                conn, observation_id, request_id, "settle", fingerprint, now
            )

    def pause(self, *, observation_id, request_id, fingerprint, expected_version):
        with self._connect(write=True) as conn:
            row = self._row(conn, observation_id)
            replay = self._receipt(conn, row, request_id, "pause", fingerprint)
            if replay is not None:
                return replay
            row = self._version(row, expected_version)
            now = self._locked_clock(conn, row)
            if row["paused_at"] is None:
                conn.execute(
                    "UPDATE research_paper_books SET lifecycle='paused', paused_at=?, version=version+1 WHERE id=?",
                    (now.isoformat(), row["id"]),
                )
            return self._record(
                conn, observation_id, request_id, "pause", fingerprint, now
            )

    @staticmethod
    def _row(conn, observation_id):
        return conn.execute(
            "SELECT * FROM research_paper_books WHERE observation_id=?",
            (observation_id,),
        ).fetchone()

    @staticmethod
    def _version(row, expected):
        if row is None:
            raise ValueError("paper_book_not_found")
        if type(expected) is not int or expected != row["version"]:
            raise ValueError("paper_book_version_conflict")
        return row

    def _locked_clock(self, conn, row, not_before=None):
        now = _instant(self.clock())
        previous = conn.execute(
            "SELECT MAX(completed_at) FROM research_paper_operations WHERE book_id=?",
            (row["id"],),
        ).fetchone()[0]
        if now < datetime.fromisoformat(previous or row["started_at"]) or (
            not_before is not None and now < _instant(not_before)
        ):
            raise ValueError("paper_book_clock_reversed")
        return now

    def _receipt(self, conn, row, request_id, kind, fingerprint):
        if row is None:
            return None
        receipt = conn.execute(
            "SELECT * FROM research_paper_operations WHERE book_id=? AND request_id=?",
            (row["id"], request_id),
        ).fetchone()
        if receipt is None:
            return None
        if receipt["kind"] != kind or receipt["request_fingerprint"] != fingerprint:
            raise ValueError("paper_book_request_conflict")
        return self._detail(conn, json.loads(receipt["result_json"]))

    def _record(self, conn, observation_id, request_id, kind, fingerprint, now):
        row = self._row(conn, observation_id)
        conn.execute(
            """INSERT INTO research_paper_operations
            (book_id, request_id, kind, request_fingerprint, result_json, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                row["id"],
                request_id,
                kind,
                fingerprint,
                _json(dict(row)),
                now.isoformat(),
            ),
        )
        return self._detail(conn, row)

    @staticmethod
    def _detail(conn, row):
        result = dict(row)
        for name in ("source", "policy", "code_binding", "instruments"):
            result[name] = json.loads(result.pop(name + "_json"))
        result["steps"] = [
            {
                "session": step["session"],
                "book_version": step["book_version"],
                "dataset_id": step["dataset_id"],
                "settled_at": step["settled_at"],
                "input": json.loads(step["input_json"]),
                "projection": json.loads(step["projection_json"]),
            }
            for step in conn.execute(
                "SELECT * FROM research_paper_steps WHERE book_id=? AND book_version<=? ORDER BY session",
                (row["id"], row["version"]),
            ).fetchall()
        ]
        result["last_settled_session"] = (
            result["steps"][-1]["session"] if result["steps"] else None
        )
        projection = (
            result["steps"][-1]["projection"]
            if result["steps"]
            else {
                "cash": row["initial_cash"],
                "equity": row["initial_cash"],
                "dividend_receivable": "0",
                "dividend_income": "0",
                "positions": {},
            }
        )
        result["state"] = {
            key: projection[key]
            for key in (
                "cash",
                "equity",
                "dividend_receivable",
                "dividend_income",
                "positions",
            )
        }
        for field in ("fills", "attempts"):
            result[field] = [
                value
                for step in result["steps"]
                for value in step["projection"].get(field, [])
            ]
        result.update(
            scope="independent_paper",
            automatic=False,
            account_authority=False,
            limitations=result["policy"]["limitations"],
        )
        result["performance"] = paper_book_performance(result)
        result["health"] = evaluate_paper_health(
            result["performance"], result["policy"].get("health_policy")
        )
        return result
