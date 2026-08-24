"""SQLite repository and atomic UoWs for broker write-edge releases."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RELEASE_TABLE = "controlled_broker_write_releases"
_REVOCATION_TABLE = "controlled_broker_write_release_revocations"
_RELEASE_COLUMNS = {
    "id",
    "release_evidence_id",
    "evidence_fingerprint",
    "gateway_id",
    "account_alias",
    "provider",
    "effective_at",
    "expires_at",
    "operator_id",
    "operator_key_id",
    "operator_approval_id",
    "payload_json",
    "created_at",
}
_REVOCATION_COLUMNS = {
    "id",
    "revocation_id",
    "release_evidence_id",
    "revocation_fingerprint",
    "reason_code",
    "operator_id",
    "operator_key_id",
    "operator_approval_id",
    "payload_json",
    "created_at",
}


class ControlledBrokerWriteReleaseReadRejected(RuntimeError):
    """Raised when persisted write-release evidence cannot be read safely."""


class ControlledBrokerWriteReleaseUowRejected(RuntimeError):
    """An atomic issue or revoke decision failed before any row was written."""

    def __init__(self, evidence: Mapping[str, Any], blockers: list[str]) -> None:
        super().__init__("controlled_broker_write_release_uow_rejected")
        self.evidence = dict(evidence)
        self.blockers = list(dict.fromkeys(blockers))


@dataclass(frozen=True)
class ReleaseIssueWrite:
    evidence: Mapping[str, Any]
    blockers: tuple[str, ...]
    gateway_id: str
    account_alias: str
    payload: Mapping[str, Any] | None
    evidence_fingerprint: str
    payload_json: str
    created_at: str
    active_at: datetime


@dataclass(frozen=True)
class ReleaseRevocationWrite:
    evidence: Mapping[str, Any]
    blockers: tuple[str, ...]
    payload: Mapping[str, Any] | None
    revocation_id: str
    payload_json: str
    created_at: str


class ControlledBrokerWriteReleaseRepository:
    """Own release schema, bounded reads, idempotency, and write transactions."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def get_release_row(self, release_evidence_id: str) -> dict[str, Any] | None:
        with self._read_connection(_RELEASE_TABLE, _RELEASE_COLUMNS) as connection:
            if connection is None:
                return None
            row = connection.execute(
                f"SELECT * FROM {_RELEASE_TABLE} WHERE release_evidence_id = ?",
                (release_evidence_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_revocation_row(self, release_evidence_id: str) -> dict[str, Any] | None:
        with self._read_connection(
            _REVOCATION_TABLE, _REVOCATION_COLUMNS
        ) as connection:
            if connection is None:
                return None
            row = connection.execute(
                f"SELECT * FROM {_REVOCATION_TABLE} WHERE release_evidence_id = ?",
                (release_evidence_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_release_ids(self, *, limit: int) -> list[str]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._read_connection(_RELEASE_TABLE, _RELEASE_COLUMNS) as connection:
            if connection is None:
                return []
            rows = connection.execute(
                f"SELECT release_evidence_id FROM {_RELEASE_TABLE} "
                "ORDER BY id DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        return [str(row["release_evidence_id"]) for row in rows]

    def issue_release(
        self,
        prepare: Callable[[], ReleaseIssueWrite],
    ) -> tuple[dict[str, Any], bool]:
        """Revalidate and append one release under an immediate transaction."""

        self._ensure_schema()
        with sqlite3.connect(self._path, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            write = prepare()
            blockers = [
                *write.blockers,
                *self._active_scope_conflicts(connection, write),
            ]
            if blockers:
                connection.rollback()
                raise ControlledBrokerWriteReleaseUowRejected(write.evidence, blockers)
            if write.payload is None:
                connection.rollback()
                raise RuntimeError("write release UoW missing an accepted payload")
            release_id = str(write.payload.get("release_evidence_id") or "")
            existing = connection.execute(
                f"SELECT * FROM {_RELEASE_TABLE} WHERE release_evidence_id = ?",
                (release_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["evidence_fingerprint"]) != write.evidence_fingerprint:
                    connection.rollback()
                    raise ControlledBrokerWriteReleaseUowRejected(
                        write.evidence,
                        ["controlled_broker_write_release_id_conflict"],
                    )
                connection.commit()
                return dict(existing), True
            self._insert_release(connection, write)
            saved = connection.execute(
                f"SELECT * FROM {_RELEASE_TABLE} WHERE release_evidence_id = ?",
                (release_id,),
            ).fetchone()
            connection.commit()
        if saved is None:
            raise RuntimeError("broker write release was not persisted")
        return dict(saved), False

    def revoke_release(
        self,
        release_evidence_id: str,
        prepare: Callable[
            [dict[str, Any] | None, dict[str, Any] | None],
            ReleaseRevocationWrite,
        ],
    ) -> tuple[dict[str, Any], bool]:
        """Revalidate and append one exact revocation under an immediate UoW."""

        self._ensure_schema()
        with sqlite3.connect(self._path, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            release_row = connection.execute(
                f"SELECT * FROM {_RELEASE_TABLE} WHERE release_evidence_id = ?",
                (release_evidence_id,),
            ).fetchone()
            release_id = (
                str(release_row["release_evidence_id"])
                if release_row is not None
                else release_evidence_id
            )
            existing = connection.execute(
                f"SELECT * FROM {_REVOCATION_TABLE} WHERE release_evidence_id = ?",
                (release_id,),
            ).fetchone()
            write = prepare(
                dict(release_row) if release_row is not None else None,
                dict(existing) if existing is not None else None,
            )
            if write.blockers:
                connection.rollback()
                raise ControlledBrokerWriteReleaseUowRejected(
                    write.evidence, list(write.blockers)
                )
            if existing is not None:
                if str(existing["revocation_fingerprint"]) != str(
                    write.evidence.get("revocation_fingerprint") or ""
                ):
                    connection.rollback()
                    raise ControlledBrokerWriteReleaseUowRejected(
                        write.evidence,
                        ["controlled_broker_write_release_already_revoked"],
                    )
                connection.commit()
                return dict(existing), True
            if write.payload is None:
                connection.rollback()
                raise RuntimeError("write release revocation UoW missing a payload")
            self._insert_revocation(connection, write)
            saved = connection.execute(
                f"SELECT * FROM {_REVOCATION_TABLE} WHERE release_evidence_id = ?",
                (str(write.payload.get("release_evidence_id") or ""),),
            ).fetchone()
            connection.commit()
        if saved is None:
            raise RuntimeError("broker write release revocation was not persisted")
        return dict(saved), False

    def _active_scope_conflicts(
        self,
        connection: sqlite3.Connection,
        write: ReleaseIssueWrite,
    ) -> list[str]:
        rows = connection.execute(
            f"SELECT release_evidence_id, expires_at, payload_json "
            f"FROM {_RELEASE_TABLE} WHERE gateway_id = ? AND account_alias = ? "
            "ORDER BY id DESC",
            (
                write.gateway_id,
                write.account_alias,
            ),
        ).fetchall()
        for row in rows:
            if _json_fingerprint(row["payload_json"]) == str(
                write.evidence.get("dossier_fingerprint") or ""
            ):
                continue
            revoked = connection.execute(
                f"SELECT 1 FROM {_REVOCATION_TABLE} WHERE release_evidence_id = ?",
                (row["release_evidence_id"],),
            ).fetchone()
            expiry = _parse_timestamp(row["expires_at"])
            if revoked is None and (expiry is None or write.active_at < expiry):
                return ["controlled_broker_write_release_active_scope_conflict"]
        return []

    @staticmethod
    def _insert_release(
        connection: sqlite3.Connection, write: ReleaseIssueWrite
    ) -> None:
        assert write.payload is not None
        payload = write.payload
        connection.execute(
            f"""
            INSERT INTO {_RELEASE_TABLE} (
                release_evidence_id, evidence_fingerprint, gateway_id,
                account_alias, provider, effective_at, expires_at,
                operator_id, operator_key_id, operator_approval_id,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["release_evidence_id"],
                write.evidence_fingerprint,
                payload["gateway_id"],
                payload["account_alias"],
                payload["provider"],
                payload["effective_at"],
                payload["expires_at"],
                payload["operator_id"],
                payload["operator_key_id"],
                payload["operator_approval_id"],
                write.payload_json,
                write.created_at,
            ),
        )

    @staticmethod
    def _insert_revocation(
        connection: sqlite3.Connection, write: ReleaseRevocationWrite
    ) -> None:
        assert write.payload is not None
        payload = write.payload
        connection.execute(
            f"""
            INSERT INTO {_REVOCATION_TABLE} (
                revocation_id, release_evidence_id, revocation_fingerprint,
                reason_code, operator_id, operator_key_id,
                operator_approval_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                write.revocation_id,
                payload["release_evidence_id"],
                payload["revocation_fingerprint"],
                payload["reason_code"],
                payload["operator_id"],
                payload["operator_key_id"],
                payload["operator_approval_id"],
                write.payload_json,
                write.created_at,
            ),
        )

    @contextmanager
    def _read_connection(
        self, table: str, expected_columns: set[str]
    ) -> Iterator[sqlite3.Connection | None]:
        if not self._path.is_file():
            yield None
            return
        try:
            uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if exists is None:
                    yield None
                    return
                columns = {
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                if not expected_columns.issubset(columns):
                    raise ControlledBrokerWriteReleaseReadRejected(
                        "controlled_broker_write_release_schema_incomplete"
                    )
                yield connection
        except ControlledBrokerWriteReleaseReadRejected:
            raise
        except sqlite3.Error as exc:
            raise ControlledBrokerWriteReleaseReadRejected(
                "controlled_broker_write_release_read_failed"
            ) from exc

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as connection:
            connection.executescript(f"""
                CREATE TABLE IF NOT EXISTS {_RELEASE_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    release_evidence_id TEXT NOT NULL UNIQUE,
                    evidence_fingerprint TEXT NOT NULL,
                    gateway_id TEXT NOT NULL,
                    account_alias TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    operator_key_id TEXT NOT NULL,
                    operator_approval_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_controlled_broker_write_release_scope
                ON {_RELEASE_TABLE}(gateway_id, account_alias, id DESC);
                CREATE TABLE IF NOT EXISTS {_REVOCATION_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    revocation_id TEXT NOT NULL UNIQUE,
                    release_evidence_id TEXT NOT NULL UNIQUE,
                    revocation_fingerprint TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    operator_key_id TEXT NOT NULL,
                    operator_approval_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(release_evidence_id)
                        REFERENCES {_RELEASE_TABLE}(release_evidence_id)
                );
                """)
            connection.commit()


def _json_fingerprint(payload_json: Any) -> str:
    import json

    try:
        payload = json.loads(str(payload_json or ""))
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("dossier_fingerprint") or "")


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


__all__ = [
    "ControlledBrokerWriteReleaseReadRejected",
    "ControlledBrokerWriteReleaseRepository",
    "ControlledBrokerWriteReleaseUowRejected",
    "ReleaseIssueWrite",
    "ReleaseRevocationWrite",
]
