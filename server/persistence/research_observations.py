"""Atomic persistence for independent target-only research observations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from server.persistence.connection import connect_sqlite


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("research_observation_clock_timezone_required")
    return value.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("research_observation_identity_required")
    return value


class ResearchObservationsRepository:
    """Store frozen sources, append-only publications, and durable request receipts."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._path = Path(database_path)
        self._clock = clock

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(connect_sqlite(self._path, readonly=not write)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                if write:
                    conn.execute("BEGIN IMMEDIATE")
                yield conn

    def get(self, observation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            # One read transaction keeps the row and append-only history coherent.
            conn.execute("BEGIN")
            row = self._row(conn, observation_id)
            return self._detail(conn, row) if row is not None else None

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("research_observation_limit_invalid")
        with self._connect() as conn:
            conn.execute("BEGIN")
            rows = conn.execute(
                "SELECT * FROM research_observations ORDER BY started_at DESC, id "
                "LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._detail(conn, row) for row in rows]

    def get_operation(
        self,
        *,
        observation_id: str,
        request_id: str,
        kind: str,
        request_fingerprint: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._receipt(
                conn, observation_id, request_id, kind, request_fingerprint
            )

    def start(
        self,
        *,
        observation_id: str,
        request_id: str,
        request_fingerprint: str,
        source_backtest_result_id: int,
        source: Mapping[str, Any],
        code_binding: Mapping[str, Any],
        policy: Mapping[str, Any],
        universe: Sequence[Mapping[str, Any]],
        max_active_observations: int = 20,
    ) -> dict[str, Any]:
        with self._connect(write=True) as conn:
            prior = self._receipt(
                conn, observation_id, request_id, "start", request_fingerprint
            )
            if prior is not None:
                return prior
            if self._row(conn, observation_id) is not None:
                raise ValueError("research_observation_identity_conflict")
            if (
                isinstance(max_active_observations, bool)
                or not isinstance(max_active_observations, int)
                or max_active_observations < 1
            ):
                raise ValueError("research_observation_active_limit_invalid")
            active_count = conn.execute(
                "SELECT COUNT(*) FROM research_observations WHERE lifecycle='active'"
            ).fetchone()[0]
            if active_count >= max_active_observations:
                raise ValueError("research_observation_active_limit_reached")
            started_at = _instant(self._clock()).isoformat()
            conn.execute(
                """INSERT INTO research_observations
                (id, source_backtest_result_id, source_json, code_binding_json,
                 policy_json, universe_json, started_at, lifecycle, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0)""",
                (
                    observation_id,
                    source_backtest_result_id,
                    _json(dict(source)),
                    _json(dict(code_binding)),
                    _json(dict(policy)),
                    _json(list(universe)),
                    started_at,
                ),
            )
            return self._record_result(
                conn,
                observation_id,
                request_id,
                "start",
                request_fingerprint,
                started_at,
            )

    def advance(
        self,
        *,
        observation_id: str,
        request_id: str,
        request_fingerprint: str,
        expected_version: int,
        publication: Mapping[str, Any] | None = None,
        outcomes: Sequence[Mapping[str, Any]] = (),
        blocker: Mapping[str, Any] | None = None,
        publication_deadline: datetime | None = None,
        computation_not_before: datetime | None = None,
    ) -> dict[str, Any]:
        with self._connect(write=True) as conn:
            prior = self._receipt(
                conn, observation_id, request_id, "advance", request_fingerprint
            )
            if prior is not None:
                return prior
            row = self._require_version(conn, observation_id, expected_version)
            if row["lifecycle"] != "active" and publication is not None:
                raise ValueError("research_observation_paused")
            now = self._locked_clock(conn, row)
            if computation_not_before is not None and now < _instant(
                computation_not_before
            ):
                raise ValueError("research_observation_computation_clock_reversed")
            if publication is not None:
                if publication_deadline is None:
                    raise ValueError(
                        "research_observation_publication_deadline_required"
                    )
                if now >= _instant(publication_deadline):
                    raise ValueError(
                        "research_observation_publication_deadline_elapsed"
                    )
                self._insert_publication(conn, row, publication, now)
            for outcome in outcomes:
                self._insert_outcome(conn, observation_id, outcome, now)
            conn.execute(
                """UPDATE research_observations
                SET version=version+1, last_blocker_json=? WHERE id=?""",
                (_json(dict(blocker)) if blocker is not None else None, observation_id),
            )
            return self._record_result(
                conn,
                observation_id,
                request_id,
                "advance",
                request_fingerprint,
                now.isoformat(),
                publication_id=publication["id"] if publication is not None else None,
                outcome_keys=[
                    {
                        "publication_id": item["publication_id"],
                        "horizon": item["horizon"],
                    }
                    for item in outcomes
                ],
            )

    def pause(
        self,
        *,
        observation_id: str,
        request_id: str,
        request_fingerprint: str,
        expected_version: int,
    ) -> dict[str, Any]:
        with self._connect(write=True) as conn:
            prior = self._receipt(
                conn, observation_id, request_id, "pause", request_fingerprint
            )
            if prior is not None:
                return prior
            row = self._require_version(conn, observation_id, expected_version)
            now = self._locked_clock(conn, row)
            conn.execute(
                """UPDATE research_observations
                SET lifecycle='paused', version=version+1 WHERE id=?""",
                (observation_id,),
            )
            return self._record_result(
                conn,
                observation_id,
                request_id,
                "pause",
                request_fingerprint,
                now.isoformat(),
            )

    def _locked_clock(self, conn: sqlite3.Connection, row: sqlite3.Row) -> datetime:
        now = _instant(self._clock())
        previous = conn.execute(
            "SELECT MAX(completed_at) FROM research_observation_operations "
            "WHERE observation_id=?",
            (row["id"],),
        ).fetchone()[0]
        if now < datetime.fromisoformat(previous or row["started_at"]):
            raise ValueError("research_observation_clock_reversed")
        return now

    @staticmethod
    def _row(conn: sqlite3.Connection, observation_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM research_observations WHERE id=?", (observation_id,)
        ).fetchone()

    def _require_version(
        self, conn: sqlite3.Connection, observation_id: str, expected_version: int
    ) -> sqlite3.Row:
        row = self._row(conn, observation_id)
        if row is None:
            raise ValueError("research_observation_not_found")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or row["version"] != expected_version
        ):
            raise ValueError("research_observation_version_conflict")
        return row

    @staticmethod
    def _receipt(
        conn: sqlite3.Connection,
        observation_id: str,
        request_id: str,
        kind: str,
        request_fingerprint: str,
    ) -> dict[str, Any] | None:
        for value in (observation_id, request_id, request_fingerprint):
            _text(value)
        row = conn.execute(
            """SELECT kind, request_fingerprint, result_json
            FROM research_observation_operations
            WHERE observation_id=? AND request_id=?""",
            (observation_id, request_id),
        ).fetchone()
        if row is None:
            return None
        if row["kind"] != kind or row["request_fingerprint"] != request_fingerprint:
            raise ValueError("research_observation_request_conflict")
        return json.loads(row["result_json"])

    def _record_result(
        self,
        conn: sqlite3.Connection,
        observation_id: str,
        request_id: str,
        kind: str,
        request_fingerprint: str,
        completed_at: str,
        *,
        publication_id: str | None = None,
        outcome_keys: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        row = self._row(conn, observation_id)
        assert row is not None
        result = {
            "id": observation_id,
            "lifecycle": row["lifecycle"],
            "version": row["version"],
            "started_at": row["started_at"],
            "last_blocker": json.loads(row["last_blocker_json"])
            if row["last_blocker_json"] is not None
            else None,
            "publication_id": publication_id,
            "outcome_keys": outcome_keys or [],
        }
        conn.execute(
            """INSERT INTO research_observation_operations
            (observation_id, request_id, kind, request_fingerprint, result_json,
             completed_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                observation_id,
                request_id,
                kind,
                request_fingerprint,
                _json(result),
                completed_at,
            ),
        )
        return result

    @staticmethod
    def _detail(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for field in ("source", "code_binding", "policy", "universe", "last_blocker"):
            value = result.pop(f"{field}_json")
            result[field] = json.loads(value) if value is not None else None
        for key, sql in (
            (
                "publications",
                "SELECT * FROM research_observation_publications "
                "WHERE observation_id=? ORDER BY decision_session, id",
            ),
            (
                "outcomes",
                "SELECT outcome.* FROM research_observation_outcomes outcome "
                "JOIN research_observation_publications publication "
                "ON publication.id=outcome.publication_id WHERE publication.observation_id=? "
                "ORDER BY publication.decision_session, outcome.horizon",
            ),
        ):
            items = []
            for record in conn.execute(sql, (row["id"],)).fetchall():
                item = dict(record)
                item["payload"] = json.loads(item.pop("payload_json"))
                items.append(item)
            result[key] = items
        return result

    @staticmethod
    def _insert_publication(
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        publication: Mapping[str, Any],
        now: datetime,
    ) -> None:
        session = _text(publication["decision_session"])
        if date.fromisoformat(session).isoformat() != session:
            raise ValueError("research_observation_session_invalid")
        latest = conn.execute(
            "SELECT MAX(decision_session) FROM research_observation_publications "
            "WHERE observation_id=?",
            (row["id"],),
        ).fetchone()[0]
        if latest is not None and session <= latest:
            raise ValueError("research_observation_session_already_published")
        payload = dict(publication["payload"])
        if "published_at" in payload:
            raise ValueError("research_observation_publication_clock_owned")
        payload["published_at"] = now.isoformat()
        conn.execute(
            """INSERT INTO research_observation_publications
            (id, observation_id, decision_session, published_at, dataset_id, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                _text(publication["id"]),
                row["id"],
                session,
                now.isoformat(),
                _text(publication["dataset_id"]),
                _json(payload),
            ),
        )

    @staticmethod
    def _insert_outcome(
        conn: sqlite3.Connection,
        observation_id: str,
        outcome: Mapping[str, Any],
        now: datetime,
    ) -> None:
        publication_id = _text(outcome["publication_id"])
        publication = conn.execute(
            "SELECT observation_id FROM research_observation_publications WHERE id=?",
            (publication_id,),
        ).fetchone()
        if publication is None or publication["observation_id"] != observation_id:
            raise ValueError("research_observation_outcome_publication_mismatch")
        horizon = outcome["horizon"]
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
            raise ValueError("research_observation_horizon_invalid")
        conn.execute(
            """INSERT INTO research_observation_outcomes
            (publication_id, horizon, measured_at, dataset_id, payload_json)
            VALUES (?, ?, ?, ?, ?)""",
            (
                publication_id,
                horizon,
                now.isoformat(),
                _text(outcome["dataset_id"]),
                _json(dict(outcome["payload"])),
            ),
        )
