"""Atomic unit of work for broker order-lifecycle evidence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
)
from account_truth.broker_order_lifecycle_contracts import (
    broker_order_lifecycle_safety_flags as _safety_flags,
)
from account_truth.broker_order_lifecycle_projection import (
    broker_order_lifecycle_observation_from_row as _observation_from_row,
)
from account_truth.broker_order_lifecycle_values import broker_order_dict as _dict
from account_truth.broker_order_lifecycle_values import broker_order_json as _json
from account_truth.broker_order_lifecycle_values import (
    broker_order_lifecycle_fingerprint as _fingerprint,
)


class BrokerOrderLifecycleEvidenceUnitOfWorkMixin:
    def record(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Record one explicit import; never contact a provider or mutate OMS."""

        if acknowledgement != BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT:
            raise self._lifecycle_rejection(
                "broker lifecycle evidence acknowledgement mismatch",
                evidence=_rejection(
                    preview,
                    ["broker_order_lifecycle_acknowledgement_mismatch"],
                ),
            )
        if (
            str(preview.get("schema_version") or "")
            != BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION
        ):
            raise self._lifecycle_rejection(
                "broker lifecycle evidence preview schema invalid",
                evidence=_rejection(
                    preview,
                    ["broker_order_lifecycle_preview_schema_invalid"],
                ),
            )
        integrity_blockers = _preview_integrity_blockers(preview)
        if integrity_blockers:
            raise self._lifecycle_rejection(
                "broker lifecycle evidence preview integrity invalid",
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
                raise RuntimeError("broker lifecycle evidence was not persisted")
            return self._observation_response(conn, saved, reused=False)

    def _transaction_blockers(
        self,
        conn: sqlite3.Connection,
        preview: dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        latest = conn.execute(
            """
                SELECT * FROM broker_order_lifecycle_observations
                WHERE gateway_id = ? AND account_alias = ?
                  AND validation_status = 'pass'
                ORDER BY captured_at DESC, id DESC
                LIMIT 1
                """,
            (
                str(preview.get("gateway_id") or ""),
                str(preview.get("account_alias") or ""),
            ),
        ).fetchone()
        if latest is not None:
            if str(latest["provider"]) != str(preview.get("provider") or ""):
                blockers.append("broker_order_lifecycle_provider_changed")
            if str(latest["account_ref_hash"]) != str(
                preview.get("account_ref_hash") or ""
            ):
                blockers.append("broker_order_lifecycle_account_identity_changed")
            current_sequence = int(preview.get("source_sequence") or 0)
            latest_sequence = int(latest["source_sequence"])
            if current_sequence < latest_sequence:
                blockers.append("broker_order_lifecycle_source_sequence_regressed")
            elif current_sequence == latest_sequence:
                blockers.append(
                    "broker_order_lifecycle_source_sequence_evidence_conflict"
                )
            if str(preview.get("captured_at") or "") <= str(latest["captured_at"]):
                blockers.append("broker_order_lifecycle_captured_at_not_monotonic")

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
            blockers.append("broker_order_lifecycle_order_identity_drift")
        if conflicting is not None and (
            str(conflicting["symbol"]) != str(order.get("symbol") or "")
            or str(conflicting["side"]) != str(order.get("side") or "")
            or str(conflicting["order_quantity"])
            != str(order.get("order_quantity") or "")
        ):
            blockers.append("broker_order_lifecycle_order_contract_drift")
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
        blockers.append("broker_order_lifecycle_preview_fingerprint_drift")
    expected_observation_id = _fingerprint(
        {
            "domain": "karkinos.broker_order_lifecycle.observation_id.v1",
            "evidence_fingerprint": expected_fingerprint,
        }
    )
    if str(preview.get("observation_id") or "") != expected_observation_id:
        blockers.append("broker_order_lifecycle_preview_observation_id_drift")
    preview_blockers = [str(item) for item in preview.get("blockers") or []]
    expected_status = "pass" if not preview_blockers else "blocked"
    if str(preview.get("validation_status") or "") != expected_status:
        blockers.append("broker_order_lifecycle_preview_validation_status_drift")
    if bool(preview.get("ready_to_record")) != (not preview_blockers):
        blockers.append("broker_order_lifecycle_preview_readiness_drift")
    if (
        str(preview.get("evidence_schema_version") or "")
        != BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION
    ):
        blockers.append("broker_order_lifecycle_preview_evidence_schema_drift")
    for field, expected in _safety_flags().items():
        if preview.get(field) is not expected:
            blockers.append(f"broker_order_lifecycle_preview_safety_drift:{field}")
    return blockers


def _rejection(preview: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        "status": "rejected",
        "observation_id": str(preview.get("observation_id") or ""),
        "blockers": blockers,
        **_safety_flags(),
    }
