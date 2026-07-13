"""Persist normalized QMT order-lifecycle evidence without broker authority."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

QMT_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION = "karkinos.qmt_order_lifecycle_export.v1"
BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_preview.v1"
)
BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_evidence.v1"
)
BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT = (
    "record_qmt_order_lifecycle_evidence_without_execution_authority"
)
DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 120
MAX_EXPORT_BYTES = 2 * 1024 * 1024

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_ORDER_STATUSES = frozenset(
    {
        "submitted",
        "open",
        "partially_filled",
        "filled",
        "cancelled",
        "rejected",
    }
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "provider",
        "snapshot_kind",
        "gateway_id",
        "account_id",
        "account_alias",
        "captured_at",
        "source_sequence",
        "orders",
        "fills",
    }
)
_ORDER_FIELDS = frozenset(
    {
        "broker_order_id",
        "client_order_id",
        "symbol",
        "side",
        "status",
        "order_quantity",
        "cumulative_filled_quantity",
        "cancelled_quantity",
        "average_fill_price",
        "submitted_at",
        "updated_at",
    }
)
_FILL_FIELDS = frozenset(
    {
        "broker_trade_id",
        "broker_order_id",
        "client_order_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "fee",
        "tax",
        "transfer_fee",
        "net_amount",
        "filled_at",
    }
)
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
)


class BrokerOrderLifecycleEvidenceRejected(ValueError):
    """Raised when an explicit lifecycle evidence record request is unsafe."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def preview_qmt_order_lifecycle_export(
    content: str | bytes,
    *,
    source_name: str = "",
    max_snapshot_age_seconds: int = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Normalize one exact-order QMT export without persisting any fact."""

    observed_at = _aware_utc((clock or (lambda: datetime.now(UTC)))())
    max_age = max(30, min(int(max_snapshot_age_seconds), 3600))
    raw, text, decode_blockers = _decode_content(content)
    blockers = list(decode_blockers)
    file_fingerprint = hashlib.sha256(raw).hexdigest()
    data: dict[str, Any] = {}
    if not blockers:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            blockers.append("qmt_order_lifecycle_json_invalid")
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                blockers.append("qmt_order_lifecycle_payload_not_object")

    if _contains_sensitive_key(data):
        blockers.append("qmt_order_lifecycle_credentials_not_allowed")
    _reject_unknown_fields(data, _TOP_LEVEL_FIELDS, "payload", blockers)

    schema_version = str(data.get("schema_version") or "")
    provider = str(data.get("provider") or "").strip().lower()
    snapshot_kind = str(data.get("snapshot_kind") or "").strip().lower()
    gateway_id = str(data.get("gateway_id") or "").strip()
    account_alias = str(data.get("account_alias") or "").strip()
    account_id = str(data.get("account_id") or "").strip()
    captured_at = _timestamp(
        data.get("captured_at"),
        blocker="qmt_order_lifecycle_captured_at_invalid",
        blockers=blockers,
    )
    source_sequence = _source_sequence(data.get("source_sequence"), blockers)

    if schema_version != QMT_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION:
        blockers.append("qmt_order_lifecycle_schema_unsupported")
    if provider != "qmt":
        blockers.append("qmt_order_lifecycle_provider_invalid")
    if snapshot_kind != "exact_order_lifecycle":
        blockers.append("qmt_order_lifecycle_snapshot_kind_invalid")
    if not _ID_PATTERN.fullmatch(gateway_id):
        blockers.append("qmt_order_lifecycle_gateway_id_invalid")
    if not _ID_PATTERN.fullmatch(account_alias):
        blockers.append("qmt_order_lifecycle_account_alias_invalid")
    if not account_id:
        blockers.append("qmt_order_lifecycle_account_id_missing")

    if captured_at:
        captured = datetime.fromisoformat(captured_at)
        age_seconds = (observed_at - captured).total_seconds()
        if age_seconds < -5:
            blockers.append("qmt_order_lifecycle_snapshot_in_future")
        elif age_seconds > max_age:
            blockers.append("qmt_order_lifecycle_snapshot_stale")

    raw_orders = data.get("orders")
    if not isinstance(raw_orders, list) or len(raw_orders) != 1:
        blockers.append("qmt_order_lifecycle_exactly_one_order_required")
        raw_order: dict[str, Any] = {}
    else:
        raw_order = raw_orders[0] if isinstance(raw_orders[0], dict) else {}
        if not raw_order:
            blockers.append("qmt_order_lifecycle_order_invalid")
    order = _normalize_order(raw_order, blockers)

    raw_fills = data.get("fills")
    if not isinstance(raw_fills, list):
        blockers.append("qmt_order_lifecycle_fills_invalid")
        raw_fills = []
    fills: list[dict[str, Any]] = []
    for index, raw_fill in enumerate(raw_fills, start=1):
        if not isinstance(raw_fill, dict):
            blockers.append(f"qmt_order_lifecycle_fill_{index}_invalid")
            continue
        fills.append(_normalize_fill(raw_fill, index=index, blockers=blockers))
    _validate_order_and_fills(order, fills, captured_at, blockers)

    core = {
        "schema_version": BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        "provider": provider,
        "snapshot_kind": snapshot_kind,
        "gateway_id": gateway_id,
        "account_alias": account_alias,
        "account_ref_hash": _account_ref_hash(account_id),
        "captured_at": captured_at,
        "source_sequence": source_sequence,
        "order": order,
        "fills": fills,
        "file_fingerprint": file_fingerprint,
    }
    evidence_fingerprint = _fingerprint(core)
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION,
        "evidence_schema_version": (BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION),
        "observation_id": _fingerprint(
            {
                "domain": "karkinos.broker_order_lifecycle.observation_id.v1",
                "evidence_fingerprint": evidence_fingerprint,
            }
        ),
        "evidence_fingerprint": evidence_fingerprint,
        "file_fingerprint": file_fingerprint,
        "provider": provider,
        "snapshot_kind": snapshot_kind,
        "gateway_id": gateway_id,
        "account_alias": account_alias,
        "account_ref_hash": _account_ref_hash(account_id),
        "source_name": _sanitized_source_name(source_name),
        "captured_at": captured_at,
        "observed_at": observed_at.isoformat(),
        "source_sequence": source_sequence,
        "max_snapshot_age_seconds": max_age,
        "validation_status": "pass" if not unique_blockers else "blocked",
        "ready_to_record": not unique_blockers,
        "blockers": unique_blockers,
        "order": order,
        "fills": fills,
        "fill_count": len(fills),
        **_safety_flags(),
    }


def resolve_broker_order_lifecycle_from_connection(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    account_alias: str,
    broker_order_id: str,
    client_order_id: str,
) -> dict[str, Any]:
    """Resolve persisted evidence using the caller's current SQLite transaction."""

    identity = {
        "gateway_id": str(gateway_id or ""),
        "account_alias": str(account_alias or ""),
        "broker_order_id": str(broker_order_id or ""),
        "client_order_id": str(client_order_id or ""),
    }
    if not all(identity.values()):
        return _resolution("identity_incomplete", identity=identity)
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if not {
        "broker_order_lifecycle_observations",
        "broker_order_lifecycle_orders",
        "broker_order_lifecycle_fills",
    }.issubset(tables):
        return _resolution("not_configured", identity=identity)
    row = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_observations
        WHERE provider = 'qmt'
          AND gateway_id = ?
          AND account_alias = ?
          AND (broker_order_id = ? OR client_order_id = ?)
        ORDER BY source_sequence DESC, id DESC
        LIMIT 1
        """,
        (
            identity["gateway_id"],
            identity["account_alias"],
            identity["broker_order_id"],
            identity["client_order_id"],
        ),
    ).fetchone()
    if row is None:
        return _resolution("not_found", identity=identity)
    observation = _observation_from_row(row, reused=False)
    if str(row["validation_status"]) != "pass":
        return _resolution(
            "blocked",
            identity=identity,
            observation=observation,
            blockers=[str(item) for item in observation.get("blockers") or []],
        )
    if (
        str(row["broker_order_id"]) != identity["broker_order_id"]
        or str(row["client_order_id"]) != identity["client_order_id"]
    ):
        return _resolution(
            "identity_conflict",
            identity=identity,
            observation=observation,
            blockers=["qmt_order_lifecycle_order_identity_conflict"],
        )
    order_row = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_orders
        WHERE observation_id = ? LIMIT 1
        """,
        (str(row["observation_id"]),),
    ).fetchone()
    fill_rows = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_fills
        WHERE observation_id = ? ORDER BY filled_at ASC, id ASC
        """,
        (str(row["observation_id"]),),
    ).fetchall()
    if order_row is None:
        return _resolution(
            "blocked",
            identity=identity,
            observation=observation,
            blockers=["qmt_order_lifecycle_order_fact_missing"],
        )
    return {
        **_resolution(
            "found",
            identity=identity,
            observation=observation,
        ),
        "order": _order_from_row(order_row),
        "fills": [_fill_from_row(fill_row) for fill_row in fill_rows],
        "fill_count": len(fill_rows),
    }


def broker_order_lifecycle_clearance_blockers(
    order: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    """Return canonical blockers for treating a controlled order as fully filled."""

    resolution_status = str(evidence.get("status") or "")
    if resolution_status in {"blocked", "identity_conflict"}:
        return ["controlled_submission_clearance_lifecycle_evidence_blocked"]
    if resolution_status != "found":
        return []
    lifecycle_order = _dict(evidence.get("order"))
    expected_quantity = abs(_decimal(order.get("quantity")))
    filled_quantity = abs(_decimal(lifecycle_order.get("cumulative_filled_quantity")))
    cancelled_quantity = abs(_decimal(lifecycle_order.get("cancelled_quantity")))
    if (
        str(lifecycle_order.get("status") or "") != "filled"
        or str(lifecycle_order.get("symbol") or "") != str(order.get("symbol") or "")
        or str(lifecycle_order.get("side") or "") != str(order.get("side") or "")
        or abs(_decimal(lifecycle_order.get("order_quantity"))) != expected_quantity
        or filled_quantity != expected_quantity
        or cancelled_quantity != 0
    ):
        return ["controlled_submission_clearance_lifecycle_evidence_mismatch"]
    return []


class BrokerOrderLifecycleEvidenceRepository:
    """Atomic staging store for sanitized QMT lifecycle observations."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ensure_schema: bool = True,
    ) -> None:
        self._path = Path(db_path)
        if ensure_schema:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    def record(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Record one explicit import; never contact a provider or mutate OMS."""

        if acknowledgement != BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT:
            raise BrokerOrderLifecycleEvidenceRejected(
                "QMT lifecycle evidence acknowledgement mismatch",
                evidence=_rejection(
                    preview,
                    ["qmt_order_lifecycle_acknowledgement_mismatch"],
                ),
            )
        if (
            str(preview.get("schema_version") or "")
            != BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION
        ):
            raise BrokerOrderLifecycleEvidenceRejected(
                "QMT lifecycle evidence preview schema invalid",
                evidence=_rejection(
                    preview,
                    ["qmt_order_lifecycle_preview_schema_invalid"],
                ),
            )
        integrity_blockers = _preview_integrity_blockers(preview)
        if integrity_blockers:
            raise BrokerOrderLifecycleEvidenceRejected(
                "QMT lifecycle evidence preview integrity invalid",
                evidence=_rejection(preview, integrity_blockers),
            )

        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT * FROM broker_order_lifecycle_observations
                WHERE observation_id = ? LIMIT 1
                """,
                (str(preview.get("observation_id") or ""),),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return self._observation_response(conn, existing, reused=True)

            blockers = [str(item) for item in preview.get("blockers") or []]
            if not blockers:
                blockers.extend(self._transaction_blockers(conn, preview))
            blockers = list(dict.fromkeys(blockers))
            validation_status = "pass" if not blockers else "blocked"
            order = _dict(preview.get("order"))
            created_at = datetime.now(UTC).isoformat()
            payload = {
                "schema_version": (BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION),
                "validation_status": validation_status,
                "blockers": blockers,
                "order_fingerprint": _fingerprint(order),
                "fill_fingerprint": _fingerprint(preview.get("fills") or []),
                "fill_count": len(preview.get("fills") or []),
                **_safety_flags(),
            }
            conn.execute(
                """
                INSERT INTO broker_order_lifecycle_observations (
                    observation_id, schema_version, provider, snapshot_kind,
                    gateway_id, account_alias, account_ref_hash, source_name,
                    source_sequence, captured_at, observed_at,
                    max_snapshot_age_seconds, file_fingerprint,
                    evidence_fingerprint, validation_status, blockers_json,
                    broker_order_id, client_order_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(preview.get("observation_id") or ""),
                    BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
                    str(preview.get("provider") or ""),
                    str(preview.get("snapshot_kind") or ""),
                    str(preview.get("gateway_id") or ""),
                    str(preview.get("account_alias") or ""),
                    str(preview.get("account_ref_hash") or ""),
                    str(preview.get("source_name") or ""),
                    int(preview.get("source_sequence") or 0),
                    str(preview.get("captured_at") or ""),
                    str(preview.get("observed_at") or ""),
                    int(preview.get("max_snapshot_age_seconds") or 0),
                    str(preview.get("file_fingerprint") or ""),
                    str(preview.get("evidence_fingerprint") or ""),
                    validation_status,
                    _json(blockers),
                    str(order.get("broker_order_id") or ""),
                    str(order.get("client_order_id") or ""),
                    _json(payload),
                    created_at,
                ),
            )
            if validation_status == "pass":
                self._insert_order(conn, preview, created_at=created_at)
                self._insert_fills(conn, preview, created_at=created_at)
            saved = conn.execute(
                """
                SELECT * FROM broker_order_lifecycle_observations
                WHERE observation_id = ? LIMIT 1
                """,
                (str(preview.get("observation_id") or ""),),
            ).fetchone()
            conn.commit()
            if saved is None:
                raise RuntimeError("QMT lifecycle evidence was not persisted")
            return self._observation_response(conn, saved, reused=False)

    def list_observations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read persisted observations only; return empty when not configured."""

        if not self._table_exists("broker_order_lifecycle_observations"):
            return []
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM broker_order_lifecycle_observations
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [self._observation_response(conn, row, reused=False) for row in rows]

    def resolve_order(
        self,
        *,
        gateway_id: str,
        account_alias: str,
        broker_order_id: str,
        client_order_id: str,
    ) -> dict[str, Any]:
        """Resolve the newest persisted evidence for both exact order ids."""

        if not self._path.exists():
            return _resolution(
                "not_configured",
                identity={
                    "gateway_id": str(gateway_id or ""),
                    "account_alias": str(account_alias or ""),
                    "broker_order_id": str(broker_order_id or ""),
                    "client_order_id": str(client_order_id or ""),
                },
            )
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return resolve_broker_order_lifecycle_from_connection(
                conn,
                gateway_id=gateway_id,
                account_alias=account_alias,
                broker_order_id=broker_order_id,
                client_order_id=client_order_id,
            )

    def _transaction_blockers(
        self,
        conn: sqlite3.Connection,
        preview: dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        latest = conn.execute(
            """
            SELECT * FROM broker_order_lifecycle_observations
            WHERE provider = ? AND gateway_id = ? AND account_alias = ?
              AND validation_status = 'pass'
            ORDER BY source_sequence DESC, id DESC
            LIMIT 1
            """,
            (
                str(preview.get("provider") or ""),
                str(preview.get("gateway_id") or ""),
                str(preview.get("account_alias") or ""),
            ),
        ).fetchone()
        if latest is not None:
            if str(latest["account_ref_hash"]) != str(
                preview.get("account_ref_hash") or ""
            ):
                blockers.append("qmt_order_lifecycle_account_identity_changed")
            current_sequence = int(preview.get("source_sequence") or 0)
            latest_sequence = int(latest["source_sequence"])
            if current_sequence < latest_sequence:
                blockers.append("qmt_order_lifecycle_source_sequence_regressed")
            elif current_sequence == latest_sequence:
                blockers.append("qmt_order_lifecycle_source_sequence_evidence_conflict")
            if str(preview.get("captured_at") or "") <= str(latest["captured_at"]):
                blockers.append("qmt_order_lifecycle_captured_at_not_monotonic")

        order = _dict(preview.get("order"))
        conflicting = conn.execute(
            """
            SELECT observation.broker_order_id, observation.client_order_id,
                   order_fact.symbol, order_fact.side, order_fact.order_quantity
            FROM broker_order_lifecycle_observations AS observation
            JOIN broker_order_lifecycle_orders AS order_fact
              ON order_fact.observation_id = observation.observation_id
            WHERE observation.provider = ?
              AND observation.gateway_id = ?
              AND observation.account_alias = ?
              AND observation.validation_status = 'pass'
              AND (
                  observation.broker_order_id = ?
                  OR observation.client_order_id = ?
              )
            ORDER BY observation.source_sequence DESC, observation.id DESC
            LIMIT 1
            """,
            (
                str(preview.get("provider") or ""),
                str(preview.get("gateway_id") or ""),
                str(preview.get("account_alias") or ""),
                str(order.get("broker_order_id") or ""),
                str(order.get("client_order_id") or ""),
            ),
        ).fetchone()
        if conflicting is not None and (
            str(conflicting["broker_order_id"])
            != str(order.get("broker_order_id") or "")
            or str(conflicting["client_order_id"])
            != str(order.get("client_order_id") or "")
        ):
            blockers.append("qmt_order_lifecycle_order_identity_drift")
        if conflicting is not None and (
            str(conflicting["symbol"]) != str(order.get("symbol") or "")
            or str(conflicting["side"]) != str(order.get("side") or "")
            or str(conflicting["order_quantity"])
            != str(order.get("order_quantity") or "")
        ):
            blockers.append("qmt_order_lifecycle_order_contract_drift")
        return blockers

    def _insert_order(
        self,
        conn: sqlite3.Connection,
        preview: dict[str, Any],
        *,
        created_at: str,
    ) -> None:
        order = _dict(preview.get("order"))
        conn.execute(
            """
            INSERT INTO broker_order_lifecycle_orders (
                observation_id, broker_order_id, client_order_id, symbol, side,
                status, order_quantity, cumulative_filled_quantity,
                cancelled_quantity, average_fill_price, submitted_at,
                updated_at, order_fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(preview.get("observation_id") or ""),
                str(order.get("broker_order_id") or ""),
                str(order.get("client_order_id") or ""),
                str(order.get("symbol") or ""),
                str(order.get("side") or ""),
                str(order.get("status") or ""),
                str(order.get("order_quantity") or "0"),
                str(order.get("cumulative_filled_quantity") or "0"),
                str(order.get("cancelled_quantity") or "0"),
                order.get("average_fill_price"),
                str(order.get("submitted_at") or ""),
                str(order.get("updated_at") or ""),
                _fingerprint(order),
                created_at,
            ),
        )

    def _insert_fills(
        self,
        conn: sqlite3.Connection,
        preview: dict[str, Any],
        *,
        created_at: str,
    ) -> None:
        values = []
        for fill in preview.get("fills") or []:
            values.append(
                (
                    str(preview.get("observation_id") or ""),
                    str(fill.get("broker_trade_id") or ""),
                    str(fill.get("broker_order_id") or ""),
                    str(fill.get("client_order_id") or ""),
                    str(fill.get("symbol") or ""),
                    str(fill.get("side") or ""),
                    str(fill.get("quantity") or "0"),
                    str(fill.get("price") or "0"),
                    str(fill.get("fee") or "0"),
                    str(fill.get("tax") or "0"),
                    str(fill.get("transfer_fee") or "0"),
                    str(fill.get("net_amount") or "0"),
                    str(fill.get("filled_at") or ""),
                    _fingerprint(fill),
                    created_at,
                )
            )
        if values:
            conn.executemany(
                """
                INSERT INTO broker_order_lifecycle_fills (
                    observation_id, broker_trade_id, broker_order_id,
                    client_order_id, symbol, side, quantity, price, fee, tax,
                    transfer_fee, net_amount, filled_at, fill_fingerprint,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def _observation_response(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        reused: bool,
    ) -> dict[str, Any]:
        return _observation_from_row(row, reused=reused)

    def _table_exists(self, table: str) -> bool:
        if not self._path.exists():
            return False
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            return row is not None

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS broker_order_lifecycle_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    snapshot_kind TEXT NOT NULL,
                    gateway_id TEXT NOT NULL,
                    account_alias TEXT NOT NULL,
                    account_ref_hash TEXT NOT NULL,
                    source_name TEXT NOT NULL DEFAULT '',
                    source_sequence INTEGER NOT NULL CHECK(source_sequence >= 0),
                    captured_at TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    max_snapshot_age_seconds INTEGER NOT NULL,
                    file_fingerprint TEXT NOT NULL,
                    evidence_fingerprint TEXT NOT NULL,
                    validation_status TEXT NOT NULL CHECK(
                        validation_status IN ('pass', 'blocked')
                    ),
                    blockers_json TEXT NOT NULL DEFAULT '[]',
                    broker_order_id TEXT NOT NULL DEFAULT '',
                    client_order_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_order_lifecycle_scope_sequence
                ON broker_order_lifecycle_observations(
                    provider, gateway_id, account_alias,
                    source_sequence DESC, id DESC
                );

                CREATE INDEX IF NOT EXISTS idx_order_lifecycle_order_ids
                ON broker_order_lifecycle_observations(
                    broker_order_id, client_order_id, id DESC
                );

                CREATE TABLE IF NOT EXISTS broker_order_lifecycle_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL UNIQUE,
                    broker_order_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    order_quantity TEXT NOT NULL,
                    cumulative_filled_quantity TEXT NOT NULL,
                    cancelled_quantity TEXT NOT NULL,
                    average_fill_price TEXT,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    order_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(observation_id)
                        REFERENCES broker_order_lifecycle_observations(observation_id)
                );

                CREATE TABLE IF NOT EXISTS broker_order_lifecycle_fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL,
                    broker_trade_id TEXT NOT NULL,
                    broker_order_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    tax TEXT NOT NULL,
                    transfer_fee TEXT NOT NULL,
                    net_amount TEXT NOT NULL,
                    filled_at TEXT NOT NULL,
                    fill_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(observation_id, broker_trade_id),
                    FOREIGN KEY(observation_id)
                        REFERENCES broker_order_lifecycle_observations(observation_id)
                );

                CREATE INDEX IF NOT EXISTS idx_order_lifecycle_fills_observation
                ON broker_order_lifecycle_fills(observation_id, filled_at, id);
                """)
            conn.commit()


def _normalize_order(
    data: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    _reject_unknown_fields(data, _ORDER_FIELDS, "order", blockers)
    order = {
        "broker_order_id": _id_field(data, "broker_order_id", "order", blockers),
        "client_order_id": _id_field(data, "client_order_id", "order", blockers),
        "symbol": str(data.get("symbol") or "").strip(),
        "side": str(data.get("side") or "").strip().lower(),
        "status": str(data.get("status") or "").strip().lower(),
        "order_quantity": _decimal_field(data, "order_quantity", "order", blockers),
        "cumulative_filled_quantity": _decimal_field(
            data, "cumulative_filled_quantity", "order", blockers
        ),
        "cancelled_quantity": _decimal_field(
            data, "cancelled_quantity", "order", blockers
        ),
        "average_fill_price": _optional_decimal_field(
            data, "average_fill_price", "order", blockers
        ),
        "submitted_at": _timestamp(
            data.get("submitted_at"),
            blocker="qmt_order_lifecycle_order_submitted_at_invalid",
            blockers=blockers,
        ),
        "updated_at": _timestamp(
            data.get("updated_at"),
            blocker="qmt_order_lifecycle_order_updated_at_invalid",
            blockers=blockers,
        ),
    }
    if not _SYMBOL_PATTERN.fullmatch(order["symbol"]):
        blockers.append("qmt_order_lifecycle_order_symbol_invalid")
    if order["side"] not in {"buy", "sell"}:
        blockers.append("qmt_order_lifecycle_order_side_invalid")
    if order["status"] not in _ORDER_STATUSES:
        blockers.append("qmt_order_lifecycle_order_status_invalid")
    return order


def _normalize_fill(
    data: dict[str, Any],
    *,
    index: int,
    blockers: list[str],
) -> dict[str, Any]:
    prefix = f"fill_{index}"
    _reject_unknown_fields(data, _FILL_FIELDS, prefix, blockers)
    fill = {
        "broker_trade_id": _id_field(data, "broker_trade_id", prefix, blockers),
        "broker_order_id": _id_field(data, "broker_order_id", prefix, blockers),
        "client_order_id": _id_field(data, "client_order_id", prefix, blockers),
        "symbol": str(data.get("symbol") or "").strip(),
        "side": str(data.get("side") or "").strip().lower(),
        "quantity": _decimal_field(data, "quantity", prefix, blockers),
        "price": _decimal_field(data, "price", prefix, blockers),
        "fee": _decimal_field(data, "fee", prefix, blockers),
        "tax": _decimal_field(data, "tax", prefix, blockers),
        "transfer_fee": _decimal_field(data, "transfer_fee", prefix, blockers),
        "net_amount": _decimal_field(
            data,
            "net_amount",
            prefix,
            blockers,
            allow_negative=True,
        ),
        "filled_at": _timestamp(
            data.get("filled_at"),
            blocker=f"qmt_order_lifecycle_{prefix}_filled_at_invalid",
            blockers=blockers,
        ),
    }
    if not _SYMBOL_PATTERN.fullmatch(fill["symbol"]):
        blockers.append(f"qmt_order_lifecycle_{prefix}_symbol_invalid")
    if fill["side"] not in {"buy", "sell"}:
        blockers.append(f"qmt_order_lifecycle_{prefix}_side_invalid")
    return fill


def _validate_order_and_fills(
    order: dict[str, Any],
    fills: list[dict[str, Any]],
    captured_at: str,
    blockers: list[str],
) -> None:
    quantity = _decimal(order.get("order_quantity"))
    filled_quantity = _decimal(order.get("cumulative_filled_quantity"))
    cancelled_quantity = _decimal(order.get("cancelled_quantity"))
    if quantity <= 0:
        blockers.append("qmt_order_lifecycle_order_quantity_not_positive")
    if filled_quantity < 0 or cancelled_quantity < 0:
        blockers.append("qmt_order_lifecycle_order_quantities_negative")
    if filled_quantity + cancelled_quantity > quantity:
        blockers.append("qmt_order_lifecycle_order_quantity_components_exceed_total")

    status = str(order.get("status") or "")
    if status in {"submitted", "open", "rejected"} and (
        filled_quantity != 0 or cancelled_quantity != 0
    ):
        blockers.append("qmt_order_lifecycle_nonfill_status_has_quantity")
    if status == "partially_filled" and not (
        0 < filled_quantity < quantity and cancelled_quantity == 0
    ):
        blockers.append("qmt_order_lifecycle_partial_fill_quantities_invalid")
    if status == "filled" and not (
        filled_quantity == quantity and cancelled_quantity == 0
    ):
        blockers.append("qmt_order_lifecycle_filled_quantities_invalid")
    if status == "cancelled" and not (
        cancelled_quantity > 0 and filled_quantity + cancelled_quantity == quantity
    ):
        blockers.append("qmt_order_lifecycle_cancelled_quantities_invalid")

    submitted_at = str(order.get("submitted_at") or "")
    updated_at = str(order.get("updated_at") or "")
    if submitted_at and updated_at and submitted_at > updated_at:
        blockers.append("qmt_order_lifecycle_order_time_regressed")
    if updated_at and captured_at and updated_at > captured_at:
        blockers.append("qmt_order_lifecycle_order_updated_after_capture")

    seen_trade_ids: set[str] = set()
    fill_total = Decimal("0")
    weighted_total = Decimal("0")
    for fill in fills:
        trade_id = str(fill.get("broker_trade_id") or "")
        if trade_id in seen_trade_ids:
            blockers.append("qmt_order_lifecycle_broker_trade_id_duplicate")
        seen_trade_ids.add(trade_id)
        for field in (
            "broker_order_id",
            "client_order_id",
            "symbol",
            "side",
        ):
            if str(fill.get(field) or "") != str(order.get(field) or ""):
                blockers.append(f"qmt_order_lifecycle_fill_{field}_mismatch")
        fill_quantity = _decimal(fill.get("quantity"))
        fill_price = _decimal(fill.get("price"))
        if fill_quantity <= 0:
            blockers.append("qmt_order_lifecycle_fill_quantity_not_positive")
        if fill_price <= 0:
            blockers.append("qmt_order_lifecycle_fill_price_not_positive")
        if str(fill.get("filled_at") or "") < submitted_at:
            blockers.append("qmt_order_lifecycle_fill_before_submission")
        if str(fill.get("filled_at") or "") > updated_at:
            blockers.append("qmt_order_lifecycle_fill_after_order_update")
        fill_total += fill_quantity
        weighted_total += fill_quantity * fill_price
    if fill_total != filled_quantity:
        blockers.append("qmt_order_lifecycle_fill_sum_mismatch")
    average = order.get("average_fill_price")
    if filled_quantity > 0:
        if average is None or _decimal(average) <= 0:
            blockers.append("qmt_order_lifecycle_average_fill_price_missing")
        elif fill_total > 0:
            calculated_average = weighted_total / fill_total
            if abs(calculated_average - _decimal(average)) > Decimal("0.0001"):
                blockers.append("qmt_order_lifecycle_average_fill_price_mismatch")
    elif average is not None:
        blockers.append("qmt_order_lifecycle_average_fill_price_without_fill")


def _decode_content(content: str | bytes) -> tuple[bytes, str, list[str]]:
    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    blockers: list[str] = []
    if len(raw) > MAX_EXPORT_BYTES:
        blockers.append("qmt_order_lifecycle_export_too_large")
        return raw, "", blockers
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        blockers.append("qmt_order_lifecycle_export_not_utf8")
        text = ""
    return raw, text, blockers


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _reject_unknown_fields(
    data: dict[str, Any],
    allowed: frozenset[str],
    prefix: str,
    blockers: list[str],
) -> None:
    for key in sorted(set(data) - allowed):
        blockers.append(f"qmt_order_lifecycle_{prefix}_field_unsupported:{key}")


def _id_field(
    data: dict[str, Any],
    field: str,
    prefix: str,
    blockers: list[str],
) -> str:
    value = str(data.get(field) or "").strip()
    if not _ID_PATTERN.fullmatch(value):
        blockers.append(f"qmt_order_lifecycle_{prefix}_{field}_invalid")
    return value


def _decimal_field(
    data: dict[str, Any],
    field: str,
    prefix: str,
    blockers: list[str],
    *,
    allow_negative: bool = False,
) -> str:
    try:
        value = Decimal(str(data[field]))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        blockers.append(f"qmt_order_lifecycle_{prefix}_{field}_invalid")
        return "0"
    if not value.is_finite() or (value < 0 and not allow_negative):
        blockers.append(f"qmt_order_lifecycle_{prefix}_{field}_invalid")
        return "0"
    return _format_decimal(value)


def _optional_decimal_field(
    data: dict[str, Any],
    field: str,
    prefix: str,
    blockers: list[str],
) -> str | None:
    if data.get(field) is None:
        return None
    return _decimal_field(data, field, prefix, blockers)


def _source_sequence(value: Any, blockers: list[str]) -> int:
    if isinstance(value, bool):
        blockers.append("qmt_order_lifecycle_source_sequence_invalid")
        return 0
    try:
        sequence = int(value)
    except (TypeError, ValueError):
        blockers.append("qmt_order_lifecycle_source_sequence_invalid")
        return 0
    if sequence < 0 or str(value).strip() != str(sequence):
        blockers.append("qmt_order_lifecycle_source_sequence_invalid")
        return 0
    return sequence


def _timestamp(
    value: Any,
    *,
    blocker: str,
    blockers: list[str],
) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        blockers.append(blocker)
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        blockers.append(blocker)
        return ""
    return parsed.astimezone(UTC).isoformat()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _account_ref_hash(account_id: str) -> str:
    if not account_id:
        return ""
    return _fingerprint(
        {
            "domain": "karkinos.qmt_order_lifecycle.account_ref.v1",
            "account_id": account_id,
        }
    )


def _observation_from_row(
    row: sqlite3.Row,
    *,
    reused: bool,
) -> dict[str, Any]:
    payload = _json_object(row["payload_json"])
    return {
        "schema_version": str(row["schema_version"]),
        "observation_id": str(row["observation_id"]),
        "provider": str(row["provider"]),
        "snapshot_kind": str(row["snapshot_kind"]),
        "gateway_id": str(row["gateway_id"]),
        "account_alias": str(row["account_alias"]),
        "account_ref_hash": str(row["account_ref_hash"]),
        "source_name": str(row["source_name"]),
        "source_sequence": int(row["source_sequence"]),
        "captured_at": str(row["captured_at"]),
        "observed_at": str(row["observed_at"]),
        "max_snapshot_age_seconds": int(row["max_snapshot_age_seconds"]),
        "file_fingerprint": str(row["file_fingerprint"]),
        "evidence_fingerprint": str(row["evidence_fingerprint"]),
        "validation_status": str(row["validation_status"]),
        "blockers": _json_list(row["blockers_json"]),
        "broker_order_id": str(row["broker_order_id"]),
        "client_order_id": str(row["client_order_id"]),
        "recorded_at": str(row["created_at"]),
        "persisted": True,
        "reused": reused,
        "fill_count": int(payload.get("fill_count") or 0),
        **_safety_flags(),
    }


def _order_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "broker_order_id",
            "client_order_id",
            "symbol",
            "side",
            "status",
            "order_quantity",
            "cumulative_filled_quantity",
            "cancelled_quantity",
            "average_fill_price",
            "submitted_at",
            "updated_at",
            "order_fingerprint",
        )
    }


def _fill_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "broker_trade_id",
            "broker_order_id",
            "client_order_id",
            "symbol",
            "side",
            "quantity",
            "price",
            "fee",
            "tax",
            "transfer_fee",
            "net_amount",
            "filled_at",
            "fill_fingerprint",
        )
    }


def _resolution(
    status: str,
    *,
    identity: dict[str, str],
    observation: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        "status": status,
        "identity": identity,
        "observation": observation or {},
        "blockers": list(blockers or []),
        **_safety_flags(),
    }


def _preview_integrity_blockers(preview: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    core = {
        "schema_version": BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        "provider": str(preview.get("provider") or ""),
        "snapshot_kind": str(preview.get("snapshot_kind") or ""),
        "gateway_id": str(preview.get("gateway_id") or ""),
        "account_alias": str(preview.get("account_alias") or ""),
        "account_ref_hash": str(preview.get("account_ref_hash") or ""),
        "captured_at": str(preview.get("captured_at") or ""),
        "source_sequence": preview.get("source_sequence"),
        "order": _dict(preview.get("order")),
        "fills": preview.get("fills") if isinstance(preview.get("fills"), list) else [],
        "file_fingerprint": str(preview.get("file_fingerprint") or ""),
    }
    expected_fingerprint = _fingerprint(core)
    if str(preview.get("evidence_fingerprint") or "") != expected_fingerprint:
        blockers.append("qmt_order_lifecycle_preview_fingerprint_drift")
    expected_observation_id = _fingerprint(
        {
            "domain": "karkinos.broker_order_lifecycle.observation_id.v1",
            "evidence_fingerprint": expected_fingerprint,
        }
    )
    if str(preview.get("observation_id") or "") != expected_observation_id:
        blockers.append("qmt_order_lifecycle_preview_observation_id_drift")
    preview_blockers = [str(item) for item in preview.get("blockers") or []]
    expected_status = "pass" if not preview_blockers else "blocked"
    if str(preview.get("validation_status") or "") != expected_status:
        blockers.append("qmt_order_lifecycle_preview_validation_status_drift")
    if bool(preview.get("ready_to_record")) != (not preview_blockers):
        blockers.append("qmt_order_lifecycle_preview_readiness_drift")
    if (
        str(preview.get("evidence_schema_version") or "")
        != BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION
    ):
        blockers.append("qmt_order_lifecycle_preview_evidence_schema_drift")
    for field, expected in _safety_flags().items():
        if preview.get(field) is not expected:
            blockers.append(f"qmt_order_lifecycle_preview_safety_drift:{field}")
    return blockers


def _rejection(preview: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        "status": "rejected",
        "observation_id": str(preview.get("observation_id") or ""),
        "blockers": blockers,
        **_safety_flags(),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "explicit_ingestion_required": True,
        "provider_contacted": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_release_submission_interlock": True,
        "authorizes_execution": False,
    }


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _format_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _sanitized_source_name(value: Any) -> str:
    source_name = str(value or "").strip()
    if not source_name or "/" in source_name or "\\" in source_name:
        return "qmt local exact-order lifecycle export"
    return source_name[:128]


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
