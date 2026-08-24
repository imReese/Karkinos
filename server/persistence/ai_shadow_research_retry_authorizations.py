"""Retry and corrected-panel rearm authorizations."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
    SHADOW_RESEARCH_CORRECTED_PANEL_REARM_CONFIRMATION,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    SHADOW_RESEARCH_RETRY_CONFIRMATION,
    ShadowResearchRejected,
    require_corrected_panel_rearm_evidence,
    shadow_research_json_object,
)
from server.persistence.ai_shadow_research_records import (
    require_verified_no_selection,
)


class ShadowResearchRetryAuthorizationRepositoryMixin:
    def authorize_retry(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        """Append one owner-authorized, research-only ten-call retry envelope."""
        if confirmation != SHADOW_RESEARCH_RETRY_CONFIRMATION:
            raise PermissionError("research retry requires exact owner confirmation")
        approved_by = approved_by.strip()
        notes = notes.strip()
        if not approved_by or not notes:
            raise ShadowResearchRejected("retry_approver_and_notes_required")
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_retry_authorizations
                WHERE failed_run_id=?
                """,
                (failed_run_id,),
            ).fetchone()
            if existing is not None:
                if existing["approved_by"] != approved_by or existing["notes"] != notes:
                    raise ShadowResearchRejected("retry_authorization_conflict")
                return self._retry_authorization_row(conn, existing)

            failed_run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                (failed_run_id,),
            ).fetchone()
            if failed_run is None:
                raise LookupError(f"shadow research run not found: {failed_run_id}")
            if (
                failed_run["status"] != "failed"
                or not str(failed_run["failure_code"] or "")
                or int(failed_run["candidate_count"] or 0) != 0
            ):
                raise ShadowResearchRejected("retry_requires_failed_zero_candidate_run")
            candidate = conn.execute(
                "SELECT 1 FROM ai_shadow_research_candidates WHERE run_id=? LIMIT 1",
                (failed_run_id,),
            ).fetchone()
            if candidate is not None:
                raise ShadowResearchRejected("retry_requires_no_candidate_artifact")
            placeholders = ", ".join("?" for _ in PROVIDER_FREE_RETRYABLE_FAILURE_CODES)
            failed_provider_call = conn.execute(
                f"""
                SELECT status, failure_code
                FROM ai_shadow_research_provider_calls
                WHERE run_id=? AND NOT (
                    status='failed'
                    AND COALESCE(actual_tokens, 0)=0
                    AND failure_code IN ({placeholders})
                )
                ORDER BY created_at DESC, call_id DESC LIMIT 1
                """,
                (failed_run_id, *PROVIDER_FREE_RETRYABLE_FAILURE_CODES),
            ).fetchone()
            if (
                failed_provider_call is None
                or failed_provider_call["status"] != "failed"
                or not str(failed_provider_call["failure_code"] or "")
            ):
                raise ShadowResearchRejected(
                    "retry_requires_failed_real_provider_call_evidence"
                )
            market_date = str(failed_run["market_date"])
            market_conflict = conn.execute(
                """
                SELECT 1 FROM ai_shadow_research_retry_authorizations
                WHERE market_date=? LIMIT 1
                """,
                (market_date,),
            ).fetchone()
            if market_conflict is not None:
                raise ShadowResearchRejected(
                    "one_research_retry_authorization_per_market_date"
                )
            provider_calls = self._real_provider_call_count(conn, market_date)
            if provider_calls <= 0:
                raise ShadowResearchRejected(
                    "retry_requires_failed_real_provider_call_evidence"
                )
            additional_calls = SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            provider_call_ceiling = provider_calls + additional_calls
            authorization_id = (
                "ai-shadow-research-retry:"
                + content_fingerprint(
                    {
                        "failed_run_id": failed_run_id,
                        "failure_code": failed_run["failure_code"],
                        "provider_calls_at_authorization": provider_calls,
                        "authorized_additional_calls": additional_calls,
                        "approved_by": approved_by,
                        "notes": notes,
                    }
                )[:24]
            )
            conn.execute(
                """
                INSERT INTO ai_shadow_research_retry_authorizations
                (authorization_id, failed_run_id, market_date,
                 failed_input_fingerprint, failure_code,
                 provider_calls_at_authorization, authorized_additional_calls,
                 provider_call_ceiling, approved_by, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    authorization_id,
                    failed_run_id,
                    market_date,
                    failed_run["input_fingerprint"],
                    failed_run["failure_code"],
                    provider_calls,
                    additional_calls,
                    provider_call_ceiling,
                    approved_by,
                    notes,
                    now,
                ),
            )
            saved = conn.execute(
                """
                SELECT * FROM ai_shadow_research_retry_authorizations
                WHERE authorization_id=?
                """,
                (authorization_id,),
            ).fetchone()
            if saved is None:
                raise RuntimeError("research retry authorization persistence failed")
            return self._retry_authorization_row(conn, saved)

    def authorize_corrected_panel_rearm(
        self,
        completed_run_id: str,
        *,
        rearm_evidence: Mapping[str, Any],
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        """Authorize one exact full-market panel replacement research run."""
        if confirmation != SHADOW_RESEARCH_CORRECTED_PANEL_REARM_CONFIRMATION:
            raise PermissionError(
                "corrected panel rearm requires exact owner confirmation"
            )
        approved_by = approved_by.strip()
        notes = notes.strip()
        if not approved_by or not notes:
            raise ShadowResearchRejected(
                "corrected_panel_rearm_approver_and_notes_required"
            )
        normalized_evidence = require_corrected_panel_rearm_evidence(rearm_evidence)
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM ai_shadow_research_corrected_panel_rearm_authorizations
                WHERE completed_run_id=?
                """,
                (completed_run_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["approved_by"] != approved_by
                    or existing["notes"] != notes
                    or existing["expected_rearm_evidence_fingerprint"]
                    != normalized_evidence["evidence_fingerprint"]
                ):
                    raise ShadowResearchRejected(
                        "corrected_panel_rearm_authorization_conflict"
                    )
                return self._corrected_panel_rearm_authorization_row(conn, existing)

            run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                (completed_run_id,),
            ).fetchone()
            if run is None:
                raise LookupError(f"shadow research run not found: {completed_run_id}")
            if (
                run["status"] != "completed"
                or int(run["candidate_count"] or 0) != SHADOW_RESEARCH_MAX_CANDIDATES
                or str(run["market_date"]) != normalized_evidence["market_date"]
            ):
                raise ShadowResearchRejected(
                    "corrected_panel_rearm_requires_completed_five_candidate_run"
                )
            candidate_counts = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status IN
                           ('awaiting_human_approval', 'research_blocked')
                           THEN 1 ELSE 0 END) AS terminal
                FROM ai_shadow_research_candidates WHERE run_id=?
                """,
                (completed_run_id,),
            ).fetchone()
            if (
                candidate_counts is None
                or int(candidate_counts["total"] or 0) != SHADOW_RESEARCH_MAX_CANDIDATES
                or int(candidate_counts["terminal"] or 0)
                != SHADOW_RESEARCH_MAX_CANDIDATES
            ):
                raise ShadowResearchRejected(
                    "corrected_panel_rearm_candidate_lineage_incomplete"
                )
            selection = conn.execute(
                """
                SELECT * FROM ai_shadow_research_daily_selections
                WHERE run_id=? AND market_date=?
                """,
                (completed_run_id, run["market_date"]),
            ).fetchone()
            selection_fingerprint = require_verified_no_selection(
                selection,
                run_id=completed_run_id,
                market_date=str(run["market_date"]),
            )
            provider_calls = self._real_provider_call_count(
                conn, str(run["market_date"])
            )
            prior_ceiling = self._effective_provider_call_ceiling(
                conn,
                run_id=completed_run_id,
                market_date=str(run["market_date"]),
                call_limit=SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
            )
            if provider_calls != prior_ceiling:
                raise ShadowResearchRejected(
                    "corrected_panel_rearm_requires_consumed_prior_call_ceiling"
                )
            provider_call_ceiling = prior_ceiling + SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            authorization_id = (
                "ai-shadow-research-corrected-panel-rearm:"
                + content_fingerprint(
                    {
                        "completed_run_id": completed_run_id,
                        "completed_input_fingerprint": run["input_fingerprint"],
                        "completed_selection_fingerprint": selection_fingerprint,
                        "expected_rearm_evidence_fingerprint": normalized_evidence[
                            "evidence_fingerprint"
                        ],
                        "provider_calls_at_authorization": provider_calls,
                        "prior_provider_call_ceiling": prior_ceiling,
                        "provider_call_ceiling": provider_call_ceiling,
                        "approved_by": approved_by,
                        "notes": notes,
                    }
                )[:24]
            )
            conn.execute(
                """
                INSERT INTO ai_shadow_research_corrected_panel_rearm_authorizations
                (authorization_id, completed_run_id, market_date,
                 completed_input_fingerprint, completed_selection_fingerprint,
                 expected_rearm_evidence_json,
                 expected_rearm_evidence_fingerprint,
                 provider_calls_at_authorization, prior_provider_call_ceiling,
                 authorized_additional_calls, provider_call_ceiling,
                 approved_by, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 10, ?, ?, ?, ?)
                """,
                (
                    authorization_id,
                    completed_run_id,
                    run["market_date"],
                    run["input_fingerprint"],
                    selection_fingerprint,
                    canonical_json(normalized_evidence),
                    normalized_evidence["evidence_fingerprint"],
                    provider_calls,
                    prior_ceiling,
                    provider_call_ceiling,
                    approved_by,
                    notes,
                    now,
                ),
            )
            saved = conn.execute(
                """
                SELECT *
                FROM ai_shadow_research_corrected_panel_rearm_authorizations
                WHERE authorization_id=?
                """,
                (authorization_id,),
            ).fetchone()
            if saved is None:
                raise RuntimeError(
                    "corrected panel rearm authorization persistence failed"
                )
            return self._corrected_panel_rearm_authorization_row(conn, saved)

    def _unconsumed_retry_authorization(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> sqlite3.Row | None:
        if run.get("status") != "failed" or int(run.get("candidate_count") or 0) != 0:
            return None
        return conn.execute(
            """
            SELECT authorization.*
            FROM ai_shadow_research_retry_authorizations AS authorization
            LEFT JOIN ai_shadow_research_retry_consumptions AS consumption
              ON consumption.authorization_id=authorization.authorization_id
            WHERE authorization.failed_run_id=?
              AND authorization.failed_input_fingerprint=?
              AND consumption.authorization_id IS NULL
            """,
            (run["run_id"], run["input_fingerprint"]),
        ).fetchone()

    def _unconsumed_corrected_panel_rearm_authorization(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> sqlite3.Row | None:
        if (
            run.get("status") != "completed"
            or int(run.get("candidate_count") or 0) != SHADOW_RESEARCH_MAX_CANDIDATES
        ):
            return None
        return conn.execute(
            """
            SELECT authorization.*
            FROM ai_shadow_research_corrected_panel_rearm_authorizations
                 AS authorization
            LEFT JOIN ai_shadow_research_corrected_panel_rearm_consumptions
                 AS consumption
              ON consumption.authorization_id=authorization.authorization_id
            WHERE authorization.completed_run_id=?
              AND authorization.completed_input_fingerprint=?
              AND consumption.authorization_id IS NULL
            """,
            (run["run_id"], run["input_fingerprint"]),
        ).fetchone()

    def _can_rearm_provider_free_failure(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> bool:
        if (
            run.get("status") != "failed"
            or str(run.get("failure_code") or "")
            not in PROVIDER_FREE_RETRYABLE_FAILURE_CODES
            or int(run.get("candidate_count") or 0) != 0
        ):
            return False
        candidate = conn.execute(
            "SELECT 1 FROM ai_shadow_research_candidates WHERE run_id=? LIMIT 1",
            (run["run_id"],),
        ).fetchone()
        if candidate is not None:
            return False
        placeholders = ", ".join("?" for _ in PROVIDER_FREE_RETRYABLE_FAILURE_CODES)
        contacted = conn.execute(
            f"""
            SELECT 1 FROM ai_shadow_research_provider_calls
            WHERE run_id=? AND NOT (
                status='failed'
                AND COALESCE(actual_tokens, 0)=0
                AND failure_code IN ({placeholders})
            )
            LIMIT 1
            """,
            (run["run_id"], *PROVIDER_FREE_RETRYABLE_FAILURE_CODES),
        ).fetchone()
        return contacted is None

    def _retry_authorization_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        consumption = conn.execute(
            """
            SELECT replacement_run_id, replacement_input_fingerprint, consumed_at
            FROM ai_shadow_research_retry_consumptions
            WHERE authorization_id=?
            """,
            (row["authorization_id"],),
        ).fetchone()
        return {
            **dict(row),
            "consumed": consumption is not None,
            "replacement_run_id": (
                consumption["replacement_run_id"] if consumption is not None else None
            ),
            "replacement_input_fingerprint": (
                consumption["replacement_input_fingerprint"]
                if consumption is not None
                else None
            ),
            "consumed_at": (
                consumption["consumed_at"] if consumption is not None else None
            ),
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "capital_authority_changed": False,
            "authority_effect": "research_only",
        }

    def _corrected_panel_rearm_authorization_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        consumption = conn.execute(
            """
            SELECT replacement_run_id, replacement_input_fingerprint,
                   consumed_rearm_evidence_fingerprint, consumed_at
            FROM ai_shadow_research_corrected_panel_rearm_consumptions
            WHERE authorization_id=?
            """,
            (row["authorization_id"],),
        ).fetchone()
        payload = dict(row)
        payload["expected_rearm_evidence"] = shadow_research_json_object(
            payload.pop("expected_rearm_evidence_json", None)
        )
        return {
            **payload,
            "consumed": consumption is not None,
            "replacement_run_id": (
                consumption["replacement_run_id"] if consumption is not None else None
            ),
            "replacement_input_fingerprint": (
                consumption["replacement_input_fingerprint"]
                if consumption is not None
                else None
            ),
            "consumed_rearm_evidence_fingerprint": (
                consumption["consumed_rearm_evidence_fingerprint"]
                if consumption is not None
                else None
            ),
            "consumed_at": (
                consumption["consumed_at"] if consumption is not None else None
            ),
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "capital_authority_changed": False,
            "authority_effect": "research_only",
        }
