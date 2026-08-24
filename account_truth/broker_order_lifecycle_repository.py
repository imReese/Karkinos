"""Read repository for persisted broker order-lifecycle evidence."""

from __future__ import annotations

import sqlite3
from typing import Any

from account_truth.broker_order_lifecycle_projection import (
    broker_order_lifecycle_observation_from_row as _observation_from_row,
)
from account_truth.broker_order_lifecycle_projection import (
    broker_order_lifecycle_resolution as _resolution,
)
from account_truth.broker_order_lifecycle_projection import (
    resolve_broker_order_lifecycle_from_connection,
)


class BrokerOrderLifecycleEvidenceReadRepositoryMixin:
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
