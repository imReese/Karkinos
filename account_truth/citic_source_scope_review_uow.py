"""Atomic writes for privacy-minimized CITIC source-scope reviews."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import replace

from account_truth.citic_source_scope_review_contracts import (
    CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
)


class CiticSourceScopeReviewUnitOfWorkMixin:
    def record_review(
        self,
        *,
        intake_id: str,
        expected_file_fingerprint: str,
        expected_source_preview_fingerprint: str,
        expected_query_window_review_id: str,
        expected_query_window_review_fingerprint: str,
        account_alias: str,
        account_reference_hash: str,
        account_type: str,
        market_scopes: list[str],
        asset_classes: list[str],
        account_value_band: str,
        business_types: list[str],
        no_other_filters_attested: bool,
        complete_returned_results_attested: bool,
        source_scope_attested: bool,
        reviewer: str = "local_owner",
    ) -> object:
        normalized = self._normalized_review_inputs(
            intake_id=intake_id,
            expected_file_fingerprint=expected_file_fingerprint,
            expected_source_preview_fingerprint=(expected_source_preview_fingerprint),
            expected_query_window_review_id=expected_query_window_review_id,
            expected_query_window_review_fingerprint=(
                expected_query_window_review_fingerprint
            ),
            account_alias=account_alias,
            account_reference_hash=account_reference_hash,
            account_type=account_type,
            market_scopes=market_scopes,
            asset_classes=asset_classes,
            account_value_band=account_value_band,
            business_types=business_types,
            no_other_filters_attested=no_other_filters_attested,
            complete_returned_results_attested=(complete_returned_results_attested),
            source_scope_attested=source_scope_attested,
            reviewer=reviewer,
        )
        self._require_current_source_and_query_window(normalized)
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            latest_row = self._latest_review_row(
                conn,
                str(normalized["intake_id"]),
            )
            supersedes_review_id: str | None = None
            if latest_row is not None:
                latest = self._review_from_row(latest_row)
                if latest.decision == "accepted":
                    if self._same_accepted_scope(latest, normalized):
                        conn.rollback()
                        return replace(latest, reused=True)
                    raise self._rejection_type(
                        "citic_source_scope_active_review_conflict"
                    )
                supersedes_review_id = latest.review_id
            saved = self._insert_review(
                conn,
                normalized=normalized,
                decision="accepted",
                supersedes_review_id=supersedes_review_id,
                created_at=self._aware_now(self._clock()).isoformat(),
            )
            conn.commit()
            return saved

    def revoke_latest(
        self,
        *,
        intake_id: str,
        expected_active_review_id: str,
        expected_active_review_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> object:
        normalized_intake_id = intake_id.strip()
        normalized_review_id = expected_active_review_id.strip()
        normalized_fingerprint = expected_active_review_fingerprint.strip()
        normalized_reviewer = reviewer.strip() or "local_owner"
        if not normalized_intake_id.startswith("citic_intake_"):
            raise self._rejection_type("citic_source_scope_intake_id_invalid")
        if not normalized_review_id.startswith("citic_scope_review_"):
            raise self._rejection_type("citic_source_scope_review_id_invalid")
        if not self._evidence_fingerprint.fullmatch(normalized_fingerprint):
            raise self._rejection_type("citic_source_scope_review_fingerprint_invalid")
        if not self._safe_human_label(normalized_reviewer):
            raise self._rejection_type("citic_source_scope_reviewer_invalid")
        latest = self.get_latest_review(normalized_intake_id)
        if latest is None:
            raise self._rejection_type("citic_source_scope_review_missing")
        if latest.decision == "revoked":
            if latest.supersedes_review_id == normalized_review_id:
                return replace(latest, reused=True)
            raise self._rejection_type("citic_source_scope_review_superseded")
        if latest.review_id != normalized_review_id:
            raise self._rejection_type("citic_source_scope_review_superseded")
        if latest.review_fingerprint != normalized_fingerprint:
            raise self._rejection_type("citic_source_scope_review_fingerprint_mismatch")
        normalized = self._review_payload(latest, reviewer=normalized_reviewer)
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            current_row = self._latest_review_row(conn, normalized_intake_id)
            if current_row is None or str(current_row["review_id"]) != latest.review_id:
                raise self._rejection_type("citic_source_scope_review_superseded")
            saved = self._insert_review(
                conn,
                normalized=normalized,
                decision="revoked",
                supersedes_review_id=latest.review_id,
                created_at=self._aware_now(self._clock()).isoformat(),
                schema_version=latest.schema_version,
            )
            conn.commit()
            return saved

    def _insert_review(
        self,
        conn: sqlite3.Connection,
        *,
        normalized: dict[str, object],
        decision: str,
        supersedes_review_id: str | None,
        created_at: str,
        schema_version: str = CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
    ) -> object:
        payload = self._fingerprint_payload(
            normalized,
            schema_version=schema_version,
            decision=decision,
            supersedes_review_id=supersedes_review_id,
        )
        review_id = f"citic_scope_review_{uuid.uuid4().hex}"
        review_fingerprint = self._review_fingerprint(payload)
        conn.execute(
            """
            INSERT INTO citic_source_scope_reviews (
                review_id, schema_version, intake_id, file_fingerprint,
                source_preview_fingerprint, query_window_review_id,
                query_window_review_fingerprint, account_alias,
                account_reference_hash, account_type, market_scopes_json,
                asset_classes_json, account_value_band, business_types_json,
                no_other_filters_attested,
                complete_returned_results_attested, source_scope_attested,
                decision, supersedes_review_id, reviewer,
                review_fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                schema_version,
                normalized["intake_id"],
                normalized["file_fingerprint"],
                normalized["source_preview_fingerprint"],
                normalized["query_window_review_id"],
                normalized["query_window_review_fingerprint"],
                normalized["account_alias"],
                normalized["account_reference_hash"],
                normalized["account_type"],
                json.dumps(normalized["market_scopes"], separators=(",", ":")),
                json.dumps(normalized["asset_classes"], separators=(",", ":")),
                normalized["account_value_band"],
                json.dumps(normalized["business_types"], separators=(",", ":")),
                1,
                1,
                1,
                decision,
                supersedes_review_id,
                normalized["reviewer"],
                review_fingerprint,
                created_at,
            ),
        )
        row = conn.execute(
            "SELECT * FROM citic_source_scope_reviews WHERE review_id = ? LIMIT 1",
            (review_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("CITIC source-scope review disappeared")
        return self._review_from_row(row)
