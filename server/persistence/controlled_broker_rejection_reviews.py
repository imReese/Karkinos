"""Append-only repository for controlled broker rejection reviews."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable


class ControlledBrokerRejectionReviewAlreadyRecorded(RuntimeError):
    """One submit intent already owns a different immutable review."""

    def __init__(self, existing_review: dict[str, Any]) -> None:
        super().__init__("controlled_broker_rejection_review_already_recorded")
        self.existing_review = existing_review


class ControlledBrokerRejectionReviewRepository:
    """Own rejection-review uniqueness, writes, and bounded reads."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def record_review(
        self,
        *,
        submit_intent_id: str,
        review_fingerprint: str,
        reviewer_id: str,
        disposition: str,
        build_record: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        """Record one exact review after revalidating its domain draft in-UoW."""

        with sqlite3.connect(self._path, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM controlled_broker_rejection_reviews
                WHERE submit_intent_id = ?
                LIMIT 1
                """,
                (submit_intent_id,),
            ).fetchone()
            if existing is not None:
                row = dict(existing)
                if (
                    str(row.get("review_fingerprint") or "") == review_fingerprint
                    and str(row.get("reviewer_id") or "") == reviewer_id
                    and str(row.get("disposition") or "") == disposition
                ):
                    connection.commit()
                    return row, True
                raise ControlledBrokerRejectionReviewAlreadyRecorded(row)

            record = build_record()
            connection.execute(
                """
                INSERT INTO controlled_broker_rejection_reviews (
                    review_id, review_fingerprint, submit_intent_id,
                    submit_fingerprint, order_id, order_fingerprint,
                    result_fingerprint, gateway_id, account_alias,
                    client_order_id, submission_operator_id, reviewer_id,
                    disposition, rejection_classification, evidence_as_of,
                    recorded_at_epoch_ms, recorded_at, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["review_id"],
                    review_fingerprint,
                    submit_intent_id,
                    record["submit_fingerprint"],
                    record["order_id"],
                    record["order_fingerprint"],
                    record["result_fingerprint"],
                    record["gateway_id"],
                    record["account_alias"],
                    record["client_order_id"],
                    record["submission_operator_id"],
                    reviewer_id,
                    disposition,
                    record["rejection_classification"],
                    record["evidence_as_of"],
                    record["recorded_at_epoch_ms"],
                    record["recorded_at"],
                    json.dumps(
                        record["payload"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    record["recorded_at"],
                ),
            )
            saved = connection.execute(
                """
                SELECT * FROM controlled_broker_rejection_reviews
                WHERE review_id = ?
                LIMIT 1
                """,
                (record["review_id"],),
            ).fetchone()
            connection.commit()
        if saved is None:
            raise RuntimeError("controlled broker rejection review insert disappeared")
        return dict(saved), False

    def list_reviews(self, *, limit: int = 500) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 500))
        with sqlite3.connect(self._path, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            rows = connection.execute(
                """
                SELECT * FROM controlled_broker_rejection_reviews
                ORDER BY recorded_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return [dict(row) for row in rows]
