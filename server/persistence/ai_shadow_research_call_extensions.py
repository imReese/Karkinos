"""Provider-call extension authorizations and consumptions."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    CITATION_CONTRACT_RETRYABLE_FAILURE_CODES,
    OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES,
    SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    SHADOW_RESEARCH_OUTPUT_TRUNCATION_CALL_EXTENSION_CONFIRMATION,
    SHADOW_RESEARCH_TIMEOUT_RESUME_CALL_EXTENSION_CONFIRMATION,
    TIMEOUT_RESUME_ITERATION,
    TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES,
    ShadowResearchRejected,
)


class ShadowResearchCallExtensionRepositoryMixin:
    def authorize_citation_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        """Append exactly one call that restores one complete five-round retry."""
        if confirmation != SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION:
            raise PermissionError(
                "citation call extension requires exact owner confirmation"
            )
        approved_by = approved_by.strip()
        notes = notes.strip()
        if not approved_by or not notes:
            raise ShadowResearchRejected(
                "citation_call_extension_approver_and_notes_required"
            )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_citation_call_extensions
                WHERE failed_run_id=?
                """,
                (failed_run_id,),
            ).fetchone()
            if existing is not None:
                if existing["approved_by"] != approved_by or existing["notes"] != notes:
                    raise ShadowResearchRejected(
                        "citation_call_extension_authorization_conflict"
                    )
                return self._citation_call_extension_row(conn, existing)

            failed_run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                (failed_run_id,),
            ).fetchone()
            if failed_run is None:
                raise LookupError(f"shadow research run not found: {failed_run_id}")
            if (
                failed_run["status"] != "failed"
                or failed_run["failure_code"]
                not in CITATION_CONTRACT_RETRYABLE_FAILURE_CODES
                or int(failed_run["candidate_count"] or 0) != 0
            ):
                raise ShadowResearchRejected(
                    "citation_call_extension_requires_exact_zero_candidate_failure"
                )
            retry = conn.execute(
                """
                SELECT authorization.authorization_id,
                       authorization.provider_call_ceiling
                FROM ai_shadow_research_retry_consumptions AS consumption
                JOIN ai_shadow_research_retry_authorizations AS authorization
                  ON authorization.authorization_id=consumption.authorization_id
                WHERE consumption.replacement_run_id=?
                  AND authorization.market_date=?
                """,
                (failed_run_id, failed_run["market_date"]),
            ).fetchone()
            if retry is None:
                raise ShadowResearchRejected(
                    "citation_call_extension_requires_consumed_retry_authorization"
                )
            failed_call = conn.execute(
                """
                SELECT call_id FROM ai_shadow_research_provider_calls
                WHERE run_id=? AND status='failed' AND failure_code=?
                ORDER BY created_at DESC, call_id DESC LIMIT 1
                """,
                (failed_run_id, failed_run["failure_code"]),
            ).fetchone()
            if failed_call is None:
                raise ShadowResearchRejected(
                    "citation_call_extension_requires_failed_provider_call"
                )
            market_date = str(failed_run["market_date"])
            provider_calls = self._real_provider_call_count(conn, market_date)
            prior_ceiling = int(retry["provider_call_ceiling"])
            provider_call_ceiling = prior_ceiling + 1
            if (
                provider_calls != 2
                or prior_ceiling != 11
                or provider_call_ceiling != 12
                or provider_call_ceiling - provider_calls
                != SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            ):
                raise ShadowResearchRejected(
                    "citation_call_extension_must_restore_exact_five_round_capacity"
                )
            extension_id = (
                "ai-shadow-research-citation-extension:"
                + content_fingerprint(
                    {
                        "failed_run_id": failed_run_id,
                        "failure_code": failed_run["failure_code"],
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
                INSERT INTO ai_shadow_research_citation_call_extensions
                (extension_id, failed_run_id, market_date,
                 failed_input_fingerprint, failure_code,
                 provider_calls_at_authorization, prior_provider_call_ceiling,
                 authorized_additional_calls, provider_call_ceiling,
                 approved_by, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    extension_id,
                    failed_run_id,
                    market_date,
                    failed_run["input_fingerprint"],
                    failed_run["failure_code"],
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
                SELECT * FROM ai_shadow_research_citation_call_extensions
                WHERE extension_id=?
                """,
                (extension_id,),
            ).fetchone()
            if saved is None:
                raise RuntimeError(
                    "citation call extension authorization persistence failed"
                )
            return self._citation_call_extension_row(conn, saved)

    def authorize_output_truncation_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        """Append one call only when it restores the original ten-call capacity."""
        if (
            confirmation
            != SHADOW_RESEARCH_OUTPUT_TRUNCATION_CALL_EXTENSION_CONFIRMATION
        ):
            raise PermissionError(
                "output truncation call extension requires exact owner confirmation"
            )
        approved_by = approved_by.strip()
        notes = notes.strip()
        if not approved_by or not notes:
            raise ShadowResearchRejected(
                "output_truncation_call_extension_approver_and_notes_required"
            )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_output_truncation_call_extensions
                WHERE failed_run_id=?
                """,
                (failed_run_id,),
            ).fetchone()
            if existing is not None:
                if existing["approved_by"] != approved_by or existing["notes"] != notes:
                    raise ShadowResearchRejected(
                        "output_truncation_call_extension_authorization_conflict"
                    )
                return self._output_truncation_call_extension_row(conn, existing)

            failed_run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                (failed_run_id,),
            ).fetchone()
            if failed_run is None:
                raise LookupError(f"shadow research run not found: {failed_run_id}")
            if (
                failed_run["status"] != "failed"
                or failed_run["failure_code"]
                not in OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES
                or int(failed_run["candidate_count"] or 0) != 0
            ):
                raise ShadowResearchRejected(
                    "output_truncation_call_extension_requires_exact_zero_candidate_failure"
                )
            failed_call = conn.execute(
                """
                SELECT call_id FROM ai_shadow_research_provider_calls
                WHERE run_id=? AND status='failed' AND failure_code=?
                ORDER BY created_at DESC, call_id DESC LIMIT 1
                """,
                (failed_run_id, failed_run["failure_code"]),
            ).fetchone()
            if failed_call is None:
                raise ShadowResearchRejected(
                    "output_truncation_call_extension_requires_failed_provider_call"
                )
            market_date = str(failed_run["market_date"])
            prior_extension = conn.execute(
                """
                SELECT extension.provider_call_ceiling
                FROM ai_shadow_research_citation_call_extensions AS extension
                JOIN ai_shadow_research_citation_call_extension_consumptions AS consumption
                  ON consumption.extension_id=extension.extension_id
                WHERE extension.market_date=?
                """,
                (market_date,),
            ).fetchone()
            if prior_extension is None:
                raise ShadowResearchRejected(
                    "output_truncation_call_extension_requires_consumed_citation_extension"
                )
            provider_calls = self._real_provider_call_count(conn, market_date)
            prior_ceiling = int(prior_extension["provider_call_ceiling"])
            provider_call_ceiling = prior_ceiling + 1
            if (
                provider_calls != 3
                or prior_ceiling != 12
                or provider_call_ceiling != 13
                or provider_call_ceiling - provider_calls
                != SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            ):
                raise ShadowResearchRejected(
                    "output_truncation_call_extension_must_restore_exact_five_round_capacity"
                )
            extension_id = (
                "ai-shadow-research-output-truncation-extension:"
                + content_fingerprint(
                    {
                        "failed_run_id": failed_run_id,
                        "failure_code": failed_run["failure_code"],
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
                INSERT INTO ai_shadow_research_output_truncation_call_extensions
                (extension_id, failed_run_id, market_date,
                 failed_input_fingerprint, failure_code,
                 provider_calls_at_authorization, prior_provider_call_ceiling,
                 authorized_additional_calls, provider_call_ceiling,
                 approved_by, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    extension_id,
                    failed_run_id,
                    market_date,
                    failed_run["input_fingerprint"],
                    failed_run["failure_code"],
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
                SELECT * FROM ai_shadow_research_output_truncation_call_extensions
                WHERE extension_id=?
                """,
                (extension_id,),
            ).fetchone()
            if saved is None:
                raise RuntimeError(
                    "output truncation call extension authorization persistence failed"
                )
            return self._output_truncation_call_extension_row(conn, saved)

    def authorize_timeout_resume_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        """Authorize one extra call for an exact fifth-round timeout resume."""
        if confirmation != SHADOW_RESEARCH_TIMEOUT_RESUME_CALL_EXTENSION_CONFIRMATION:
            raise PermissionError(
                "timeout resume call extension requires exact owner confirmation"
            )
        approved_by = approved_by.strip()
        notes = notes.strip()
        if not approved_by or not notes:
            raise ShadowResearchRejected(
                "timeout_resume_call_extension_approver_and_notes_required"
            )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_timeout_resume_call_extensions
                WHERE failed_run_id=?
                """,
                (failed_run_id,),
            ).fetchone()
            if existing is not None:
                if existing["approved_by"] != approved_by or existing["notes"] != notes:
                    raise ShadowResearchRejected(
                        "timeout_resume_call_extension_authorization_conflict"
                    )
                return self._timeout_resume_call_extension_row(conn, existing)

            failed_run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                (failed_run_id,),
            ).fetchone()
            if failed_run is None:
                raise LookupError(f"shadow research run not found: {failed_run_id}")
            failed_run_mapping = dict(failed_run)
            if (
                failed_run["status"] != "failed"
                or failed_run["failure_code"]
                not in TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES
                or int(failed_run["candidate_count"] or 0) != 0
            ):
                raise ShadowResearchRejected(
                    "timeout_resume_requires_exact_partial_fifth_round_failure"
                )
            checkpoint = self._partial_resume_checkpoint(conn, failed_run_mapping)
            failed_call_id = (
                f"{failed_run_id}:hypothesis:iteration:{TIMEOUT_RESUME_ITERATION:02d}"
            )
            failed_call = conn.execute(
                """
                SELECT * FROM ai_shadow_research_provider_calls
                WHERE call_id=? AND run_id=? AND market_date=?
                  AND call_kind='hypothesis_iteration'
                  AND status='failed' AND failure_code='provider_timeout'
                """,
                (failed_call_id, failed_run_id, failed_run["market_date"]),
            ).fetchone()
            if failed_call is None:
                raise ShadowResearchRejected(
                    "timeout_resume_requires_exact_failed_fifth_hypothesis_call"
                )
            run_call_summary = conn.execute(
                """
                SELECT COUNT(*) AS recorded_calls,
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)
                           AS completed_calls,
                       SUM(CASE WHEN status='failed'
                                     AND failure_code='provider_timeout'
                                THEN 1 ELSE 0 END) AS timeout_calls
                FROM ai_shadow_research_provider_calls
                WHERE run_id=?
                """,
                (failed_run_id,),
            ).fetchone()
            if (
                run_call_summary is None
                or int(run_call_summary["recorded_calls"] or 0) != 9
                or int(run_call_summary["completed_calls"] or 0) != 8
                or int(run_call_summary["timeout_calls"] or 0) != 1
            ):
                raise ShadowResearchRejected(
                    "timeout_resume_requires_exact_four_round_call_lineage"
                )
            prior_extension = conn.execute(
                """
                SELECT extension.provider_call_ceiling
                FROM ai_shadow_research_output_truncation_call_extensions
                     AS extension
                JOIN ai_shadow_research_output_truncation_call_extension_consumptions
                     AS consumption
                  ON consumption.extension_id=extension.extension_id
                WHERE extension.market_date=?
                  AND consumption.replacement_run_id=?
                """,
                (failed_run["market_date"], failed_run_id),
            ).fetchone()
            if prior_extension is None:
                raise ShadowResearchRejected(
                    "timeout_resume_requires_consumed_output_truncation_extension"
                )
            market_date = str(failed_run["market_date"])
            provider_calls = self._real_provider_call_count(conn, market_date)
            prior_ceiling = int(prior_extension["provider_call_ceiling"])
            provider_call_ceiling = prior_ceiling + 1
            if (
                provider_calls != SHADOW_RESEARCH_MAX_PROVIDER_CALLS + 2
                or prior_ceiling != SHADOW_RESEARCH_MAX_PROVIDER_CALLS + 3
                or prior_ceiling - provider_calls != 1
                or provider_call_ceiling != SHADOW_RESEARCH_MAX_PROVIDER_CALLS + 4
                or provider_call_ceiling - provider_calls != 2
            ):
                raise ShadowResearchRejected(
                    "timeout_resume_must_provide_exact_fifth_round_capacity"
                )
            extension_id = (
                "ai-shadow-research-timeout-resume-extension:"
                + content_fingerprint(
                    {
                        "failed_run_id": failed_run_id,
                        "failed_call_id": failed_call_id,
                        "completed_evidence_fingerprint": checkpoint[
                            "completed_evidence_fingerprint"
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
                INSERT INTO ai_shadow_research_timeout_resume_call_extensions
                (extension_id, failed_run_id, market_date,
                 failed_input_fingerprint, failure_code,
                 completed_iteration_count, completed_evidence_fingerprint,
                 failed_call_id, provider_calls_at_authorization,
                 prior_provider_call_ceiling, authorized_additional_calls,
                 provider_call_ceiling, resume_iteration, approved_by, notes,
                 created_at)
                VALUES (?, ?, ?, ?, 'provider_timeout', 4, ?, ?, ?, ?, 1, ?, 5,
                        ?, ?, ?)
                """,
                (
                    extension_id,
                    failed_run_id,
                    market_date,
                    failed_run["input_fingerprint"],
                    checkpoint["completed_evidence_fingerprint"],
                    failed_call_id,
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
                SELECT * FROM ai_shadow_research_timeout_resume_call_extensions
                WHERE extension_id=?
                """,
                (extension_id,),
            ).fetchone()
            if saved is None:
                raise RuntimeError(
                    "timeout resume call extension authorization persistence failed"
                )
            return self._timeout_resume_call_extension_row(conn, saved)

    def _unconsumed_timeout_resume_call_extension(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> sqlite3.Row | None:
        if (
            run.get("status") != "failed"
            or run.get("failure_code") not in TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES
            or int(run.get("candidate_count") or 0) != 0
        ):
            return None
        return conn.execute(
            """
            SELECT extension.*
            FROM ai_shadow_research_timeout_resume_call_extensions AS extension
            LEFT JOIN ai_shadow_research_timeout_resume_call_extension_consumptions
                 AS consumption
              ON consumption.extension_id=extension.extension_id
            WHERE extension.failed_run_id=?
              AND extension.failed_input_fingerprint=?
              AND consumption.extension_id IS NULL
            """,
            (run["run_id"], run["input_fingerprint"]),
        ).fetchone()

    def _unconsumed_citation_call_extension(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> sqlite3.Row | None:
        if (
            run.get("status") != "failed"
            or run.get("failure_code") not in CITATION_CONTRACT_RETRYABLE_FAILURE_CODES
            or int(run.get("candidate_count") or 0) != 0
        ):
            return None
        return conn.execute(
            """
            SELECT extension.*
            FROM ai_shadow_research_citation_call_extensions AS extension
            LEFT JOIN ai_shadow_research_citation_call_extension_consumptions AS consumption
              ON consumption.extension_id=extension.extension_id
            WHERE extension.failed_run_id=?
              AND extension.failed_input_fingerprint=?
              AND consumption.extension_id IS NULL
            """,
            (run["run_id"], run["input_fingerprint"]),
        ).fetchone()

    def _unconsumed_output_truncation_call_extension(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> sqlite3.Row | None:
        if (
            run.get("status") != "failed"
            or run.get("failure_code") not in OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES
            or int(run.get("candidate_count") or 0) != 0
        ):
            return None
        return conn.execute(
            """
            SELECT extension.*
            FROM ai_shadow_research_output_truncation_call_extensions AS extension
            LEFT JOIN ai_shadow_research_output_truncation_call_extension_consumptions
                 AS consumption
              ON consumption.extension_id=extension.extension_id
            WHERE extension.failed_run_id=?
              AND extension.failed_input_fingerprint=?
              AND consumption.extension_id IS NULL
            """,
            (run["run_id"], run["input_fingerprint"]),
        ).fetchone()

    def _citation_call_extension_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        consumption = conn.execute(
            """
            SELECT replacement_run_id, replacement_input_fingerprint, consumed_at
            FROM ai_shadow_research_citation_call_extension_consumptions
            WHERE extension_id=?
            """,
            (row["extension_id"],),
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

    def _output_truncation_call_extension_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        consumption = conn.execute(
            """
            SELECT replacement_run_id, replacement_input_fingerprint, consumed_at
            FROM ai_shadow_research_output_truncation_call_extension_consumptions
            WHERE extension_id=?
            """,
            (row["extension_id"],),
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

    def _timeout_resume_call_extension_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        consumption = conn.execute(
            """
            SELECT resumed_run_id, resumed_input_fingerprint,
                   completed_evidence_fingerprint, consumed_at
            FROM ai_shadow_research_timeout_resume_call_extension_consumptions
            WHERE extension_id=?
            """,
            (row["extension_id"],),
        ).fetchone()
        return {
            **dict(row),
            "consumed": consumption is not None,
            "resumed_run_id": (
                consumption["resumed_run_id"] if consumption is not None else None
            ),
            "resumed_input_fingerprint": (
                consumption["resumed_input_fingerprint"]
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
