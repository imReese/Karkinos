"""Controlled session persistence capability: controlled_session_budgets."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_session_access import (
    ControlledSessionRepositoryAccess,
)
from server.persistence.database_support import (
    controlled_session_budget_rejection,
    json_dict,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledSessionBudgetRepositoryMixin(ControlledSessionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

    def reserve_controlled_session_budget_sync(
        self,
        *,
        reservation: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically reserve bounded capital without issuing execution authority."""
        requested = dict(reservation)
        money_fields = (
            "reserved_gross_units",
            "reserved_buy_units",
            "reserved_turnover_units",
            "capital_capacity_units",
            "cash_capacity_units",
            "turnover_capacity_units",
        )
        count_fields = ("reserved_order_count", "order_count_capacity")
        try:
            requested_by_symbol = {
                str(symbol): int(value)
                for symbol, value in (
                    requested.get("reserved_by_symbol_units") or {}
                ).items()
            }
            symbol_capacities = {
                str(symbol): int(value)
                for symbol, value in (
                    requested.get("symbol_capacity_units") or {}
                ).items()
            }
            invalid_money_units = any(
                int(requested.get(field) or 0) < 0 for field in money_fields
            )
            invalid_count_units = any(
                int(requested.get(field) or 0) <= 0 for field in count_fields
            )
        except (AttributeError, TypeError, ValueError):
            return controlled_session_budget_rejection(
                requested,
                ["budget_reservation_units_invalid"],
            )
        if invalid_money_units:
            return controlled_session_budget_rejection(
                requested,
                ["budget_reservation_money_units_invalid"],
            )
        if invalid_count_units:
            return controlled_session_budget_rejection(
                requested,
                ["budget_reservation_order_count_invalid"],
            )
        if (
            not requested_by_symbol
            or set(requested_by_symbol) != set(symbol_capacities)
            or any(value < 0 for value in requested_by_symbol.values())
            or any(value <= 0 for value in symbol_capacities.values())
        ):
            return controlled_session_budget_rejection(
                requested,
                ["budget_reservation_symbol_units_invalid"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                        SELECT * FROM controlled_session_budget_reservations
                        WHERE reservation_id = ?
                        LIMIT 1
                        """,
                    (requested["reservation_id"],),
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    return {
                        "status": "reserved",
                        "blockers": [],
                        "reused": True,
                        "reservation": dict(existing),
                    }
                attestation_conflict = conn.execute(
                    """
                        SELECT reservation_id
                        FROM controlled_session_budget_reservations
                        WHERE attestation_id = ?
                        LIMIT 1
                        """,
                    (requested["attestation_id"],),
                ).fetchone()
                if attestation_conflict is not None:
                    conn.rollback()
                    return controlled_session_budget_rejection(
                        requested,
                        ["budget_reservation_attestation_already_reserved"],
                    )

                scope = (
                    requested["authorization_id"],
                    requested["account_alias"],
                )
                overlap = conn.execute(
                    """
                        SELECT
                            COALESCE(SUM(reserved_gross_units), 0) AS gross_units,
                            COALESCE(SUM(reserved_buy_units), 0) AS buy_units,
                            COALESCE(SUM(reserved_order_count), 0) AS order_count,
                            MIN(order_count_capacity) AS minimum_order_capacity
                        FROM controlled_session_budget_reservations
                        WHERE authorization_id = ?
                          AND account_alias = ?
                          AND status = 'reserved'
                          AND requested_start_at < ?
                          AND requested_expires_at > ?
                        """,
                    (
                        *scope,
                        requested["requested_expires_at"],
                        requested["requested_start_at"],
                    ),
                ).fetchone()
                overlap_symbol_rows = conn.execute(
                    """
                        SELECT reserved_by_symbol_json, symbol_capacity_json
                        FROM controlled_session_budget_reservations
                        WHERE authorization_id = ?
                          AND account_alias = ?
                          AND status = 'reserved'
                          AND requested_start_at < ?
                          AND requested_expires_at > ?
                        """,
                    (
                        *scope,
                        requested["requested_expires_at"],
                        requested["requested_start_at"],
                    ),
                ).fetchall()
                daily = conn.execute(
                    """
                        SELECT COALESCE(SUM(reserved_turnover_units), 0) AS turnover_units
                        FROM controlled_session_budget_reservations
                        WHERE authorization_id = ?
                          AND account_alias = ?
                          AND trading_day = ?
                          AND status = 'reserved'
                        """,
                    (*scope, requested["trading_day"]),
                ).fetchone()
                before = {
                    "overlapping_gross_units": int(overlap["gross_units"] or 0),
                    "overlapping_buy_units": int(overlap["buy_units"] or 0),
                    "overlapping_order_count": int(overlap["order_count"] or 0),
                    "daily_turnover_units": int(daily["turnover_units"] or 0),
                    "overlapping_by_symbol_units": {
                        symbol: 0 for symbol in sorted(requested_by_symbol)
                    },
                }
                effective_symbol_capacities = dict(symbol_capacities)
                symbol_evidence_blockers: list[str] = []
                for row in overlap_symbol_rows:
                    existing_reserved = json_dict(row["reserved_by_symbol_json"])
                    existing_capacities = json_dict(row["symbol_capacity_json"])
                    if not existing_reserved or not existing_capacities:
                        symbol_evidence_blockers.extend(
                            f"atomic_existing_symbol_budget_evidence_missing:{symbol}"
                            for symbol in requested_by_symbol
                        )
                        continue
                    for symbol in requested_by_symbol:
                        reserved_present = symbol in existing_reserved
                        capacity_present = symbol in existing_capacities
                        if reserved_present != capacity_present:
                            symbol_evidence_blockers.append(
                                f"atomic_existing_symbol_budget_evidence_missing:{symbol}"
                            )
                            continue
                        if not reserved_present:
                            continue
                        before["overlapping_by_symbol_units"][symbol] += int(
                            existing_reserved[symbol]
                        )
                        effective_symbol_capacities[symbol] = min(
                            effective_symbol_capacities[symbol],
                            int(existing_capacities[symbol]),
                        )
                minimum_order_capacity = min(
                    int(requested["order_count_capacity"]),
                    int(
                        overlap["minimum_order_capacity"]
                        or requested["order_count_capacity"]
                    ),
                )
                after = {
                    "overlapping_gross_units": before["overlapping_gross_units"]
                    + int(requested["reserved_gross_units"]),
                    "overlapping_buy_units": before["overlapping_buy_units"]
                    + int(requested["reserved_buy_units"]),
                    "overlapping_order_count": before["overlapping_order_count"]
                    + int(requested["reserved_order_count"]),
                    "daily_turnover_units": before["daily_turnover_units"]
                    + int(requested["reserved_turnover_units"]),
                    "overlapping_by_symbol_units": {
                        symbol: before["overlapping_by_symbol_units"][symbol]
                        + requested_by_symbol[symbol]
                        for symbol in sorted(requested_by_symbol)
                    },
                }
                blockers: list[str] = list(dict.fromkeys(symbol_evidence_blockers))
                if after["overlapping_gross_units"] > int(
                    requested["capital_capacity_units"]
                ):
                    blockers.append("atomic_capital_budget_unavailable")
                if after["overlapping_buy_units"] > int(
                    requested["cash_capacity_units"]
                ):
                    blockers.append("atomic_cash_budget_unavailable")
                if after["daily_turnover_units"] > int(
                    requested["turnover_capacity_units"]
                ):
                    blockers.append("atomic_daily_turnover_budget_unavailable")
                if after["overlapping_order_count"] > minimum_order_capacity:
                    blockers.append("atomic_order_count_budget_unavailable")
                for symbol, after_units in after["overlapping_by_symbol_units"].items():
                    if after_units > effective_symbol_capacities[symbol]:
                        blockers.append(f"atomic_symbol_budget_unavailable:{symbol}")
                if blockers:
                    conn.rollback()
                    return controlled_session_budget_rejection(
                        requested,
                        blockers,
                        before=before,
                        after=after,
                    )

                created_at = str(requested["created_at"])
                conn.execute(
                    """
                        INSERT INTO controlled_session_budget_reservations (
                            reservation_id, attestation_id, envelope_fingerprint,
                            capital_evaluation_input_fingerprint, authorization_id,
                            policy_version, account_alias, strategy_id, trading_day,
                            requested_start_at, requested_expires_at,
                            reserved_gross_units, reserved_buy_units,
                            reserved_turnover_units, reserved_order_count,
                            capital_capacity_units, cash_capacity_units,
                            turnover_capacity_units, order_count_capacity,
                            reserved_by_symbol_json, symbol_capacity_json,
                            status, payload_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                    (
                        requested["reservation_id"],
                        requested["attestation_id"],
                        requested["envelope_fingerprint"],
                        requested["capital_evaluation_input_fingerprint"],
                        requested["authorization_id"],
                        requested["policy_version"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["trading_day"],
                        requested["requested_start_at"],
                        requested["requested_expires_at"],
                        int(requested["reserved_gross_units"]),
                        int(requested["reserved_buy_units"]),
                        int(requested["reserved_turnover_units"]),
                        int(requested["reserved_order_count"]),
                        int(requested["capital_capacity_units"]),
                        int(requested["cash_capacity_units"]),
                        int(requested["turnover_capacity_units"]),
                        int(requested["order_count_capacity"]),
                        _serialize_event_payload_json(requested_by_symbol),
                        _serialize_event_payload_json(symbol_capacities),
                        "reserved",
                        _serialize_event_payload_json(requested["payload"]),
                        created_at,
                    ),
                )
                saved = conn.execute(
                    """
                        SELECT * FROM controlled_session_budget_reservations
                        WHERE reservation_id = ?
                        LIMIT 1
                        """,
                    (requested["reservation_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "reserved",
                    "blockers": [],
                    "reused": False,
                    "reservation": dict(saved) if saved is not None else {},
                    "aggregate_before": before,
                    "aggregate_after": after,
                }
            except (sqlite3.OperationalError, TypeError, ValueError):
                conn.rollback()
                return controlled_session_budget_rejection(
                    requested,
                    ["budget_reservation_transaction_unavailable"],
                )

    def list_controlled_session_budget_reservations_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable reservation records newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                    SELECT * FROM controlled_session_budget_reservations
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_session_budget_reservation_sync(
        self,
        reservation_id: str,
    ) -> dict[str, Any] | None:
        """Read one reservation by its deterministic id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                (reservation_id,),
            ).fetchone()
            return dict(row) if row is not None else None
