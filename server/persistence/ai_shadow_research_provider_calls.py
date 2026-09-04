"""Provider-call claims, usage queries, and budget enforcement."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from server.contracts.ai_shadow_research_automation import (
    PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
    SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION,
    ShadowResearchRejected,
)
from server.projections.ai_shadow_research import (
    empty_shadow_research_usage,
    project_shadow_research_usage,
)


class ShadowResearchProviderCallRepositoryMixin:
    """Reserve calls atomically and report non-authorizing persisted usage."""

    def claim_provider_call(
        self,
        *,
        call_id: str,
        run_id: str,
        market_date: str,
        call_kind: str,
        call_limit: int,
        now: str,
        daily_token_budget: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_shadow_research_provider_calls WHERE call_id=?",
                (call_id,),
            ).fetchone()
            if existing is not None:
                return dict(existing), True
            provider_calls = self._real_provider_call_count(conn, market_date)
            effective_call_limit = self._effective_provider_call_ceiling(
                conn,
                run_id=run_id,
                market_date=market_date,
                call_limit=call_limit,
            )
            if provider_calls >= effective_call_limit:
                raise ShadowResearchRejected("daily_provider_call_limit_reached")
            if daily_token_budget is not None:
                totals = self._provider_call_usage_totals(conn, market_date)
                reserved_so_far = int(totals["reserved"])
                if (
                    reserved_so_far + SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION
                    > daily_token_budget
                ):
                    raise ShadowResearchRejected("daily_token_budget_exceeded")
            conn.execute(
                """
                INSERT INTO ai_shadow_research_provider_calls
                (call_id, run_id, market_date, call_kind, status, reserved_tokens,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, 'reserved', ?, ?, ?)
                """,
                (
                    call_id,
                    run_id,
                    market_date,
                    call_kind,
                    SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION,
                    now,
                    now,
                ),
            )
        return self.get_provider_call(call_id), False

    def _effective_provider_call_ceiling(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        market_date: str,
        call_limit: int,
    ) -> int:
        rows = conn.execute(
            """
            SELECT authorization.provider_call_ceiling AS ceiling
            FROM ai_shadow_research_retry_consumptions AS consumption
            JOIN ai_shadow_research_retry_authorizations AS authorization
              ON authorization.authorization_id=consumption.authorization_id
            WHERE consumption.replacement_run_id=? AND authorization.market_date=?
            UNION ALL
            SELECT extension.provider_call_ceiling AS ceiling
            FROM ai_shadow_research_citation_call_extension_consumptions AS consumption
            JOIN ai_shadow_research_citation_call_extensions AS extension
              ON extension.extension_id=consumption.extension_id
            WHERE consumption.replacement_run_id=? AND extension.market_date=?
            UNION ALL
            SELECT extension.provider_call_ceiling AS ceiling
            FROM ai_shadow_research_output_truncation_call_extension_consumptions
                 AS consumption
            JOIN ai_shadow_research_output_truncation_call_extensions AS extension
              ON extension.extension_id=consumption.extension_id
            WHERE consumption.replacement_run_id=? AND extension.market_date=?
            UNION ALL
            SELECT extension.provider_call_ceiling AS ceiling
            FROM ai_shadow_research_timeout_resume_call_extension_consumptions
                 AS consumption
            JOIN ai_shadow_research_timeout_resume_call_extensions AS extension
              ON extension.extension_id=consumption.extension_id
            WHERE consumption.resumed_run_id=? AND extension.market_date=?
            UNION ALL
            SELECT authorization.provider_call_ceiling AS ceiling
            FROM ai_shadow_research_corrected_panel_rearm_consumptions AS consumption
            JOIN ai_shadow_research_corrected_panel_rearm_authorizations AS authorization
              ON authorization.authorization_id=consumption.authorization_id
            WHERE consumption.replacement_run_id=? AND authorization.market_date=?
            UNION ALL
            SELECT extension.provider_call_ceiling AS ceiling
            FROM ai_shadow_research_corrected_panel_citation_resume_consumptions
                 AS consumption
            JOIN ai_shadow_research_corrected_panel_citation_resume_extensions
                 AS extension ON extension.extension_id=consumption.extension_id
            WHERE consumption.resumed_run_id=? AND extension.market_date=?
            """,
            (
                run_id,
                market_date,
                run_id,
                market_date,
                run_id,
                market_date,
                run_id,
                market_date,
                run_id,
                market_date,
                run_id,
                market_date,
            ),
        ).fetchall()
        return max([call_limit, *(int(row["ceiling"]) for row in rows)])

    def _real_provider_call_count(
        self,
        conn: sqlite3.Connection,
        market_date: str,
    ) -> int:
        return int(self._provider_call_usage_totals(conn, market_date)["calls"])

    def _provider_call_usage_totals(
        self,
        conn: sqlite3.Connection,
        market_date: str,
    ) -> sqlite3.Row:
        placeholders = ", ".join("?" for _ in PROVIDER_FREE_RETRYABLE_FAILURE_CODES)
        totals = conn.execute(
            f"""
            SELECT COUNT(*) AS recorded_calls,
                   COALESCE(SUM(CASE WHEN NOT (
                       call.status IN ('failed', 'deferred')
                       AND COALESCE(call.actual_tokens, 0)=0
                       AND (call.failure_code IN ({placeholders})
                            OR partial_resume.resume_id IS NOT NULL)
                   ) THEN 1 ELSE 0 END), 0) AS calls,
                   COALESCE(SUM(CASE WHEN NOT (
                       call.status IN ('failed', 'deferred')
                       AND COALESCE(call.actual_tokens, 0)=0
                       AND (call.failure_code IN ({placeholders})
                            OR partial_resume.resume_id IS NOT NULL)
                   ) THEN call.reserved_tokens ELSE 0 END), 0) AS reserved,
                   COALESCE(SUM(call.actual_tokens), 0) AS actual
            FROM ai_shadow_research_provider_calls AS call
            LEFT JOIN ai_shadow_research_provider_free_partial_resumes AS partial_resume
              ON partial_resume.failed_call_id=call.call_id
             AND partial_resume.run_id=call.run_id
             AND partial_resume.market_date=call.market_date
            WHERE call.market_date=?
            """,
            (
                *PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
                *PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
                market_date,
            ),
        ).fetchone()
        if totals is None:
            raise RuntimeError("provider call usage totals unavailable")
        return totals

    def get_provider_call(self, call_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_shadow_research_provider_calls WHERE call_id=?",
                (call_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"shadow research provider call not found: {call_id}")
        return dict(row)

    def finish_provider_call(
        self,
        call_id: str,
        *,
        status: str,
        actual_tokens: int | None,
        failure_code: str | None,
        now: str,
    ) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE ai_shadow_research_provider_calls
                SET status=?, actual_tokens=?, failure_code=?, updated_at=?
                WHERE call_id=?
                """,
                (status, actual_tokens, failure_code, now, call_id),
            )

    def usage_for_market_date(self, market_date: str | None) -> dict[str, Any]:
        if not market_date:
            return empty_shadow_research_usage(None)
        try:
            with self._connect_readonly() as conn:
                records = self._load_usage_records(conn, market_date)
        except sqlite3.OperationalError:
            return empty_shadow_research_usage(market_date)
        return project_shadow_research_usage(market_date=market_date, **records)

    def provider_activity_for_local_date(
        self,
        local_date: str,
        *,
        timezone_name: str,
    ) -> dict[str, Any]:
        """Report physical call attempts by local calendar day, not research day."""

        day = date.fromisoformat(local_date)
        zone = ZoneInfo(timezone_name)
        starts_at = datetime.combine(day, time.min, tzinfo=zone).astimezone(
            timezone.utc
        )
        ends_at = datetime.combine(
            day + timedelta(days=1), time.min, tzinfo=zone
        ).astimezone(timezone.utc)
        placeholders = ", ".join("?" for _ in PROVIDER_FREE_RETRYABLE_FAILURE_CODES)
        contacted_predicate = f"""
            NOT (
                call.status IN ('failed', 'deferred')
                AND COALESCE(call.actual_tokens, 0)=0
                AND (call.failure_code IN ({placeholders})
                     OR partial_resume.resume_id IS NOT NULL)
            )
        """
        range_predicate = """
            julianday(call.created_at) >= julianday(?)
            AND julianday(call.created_at) < julianday(?)
        """
        try:
            with self._connect_readonly() as conn:
                totals = conn.execute(
                    f"""
                    SELECT COUNT(*) AS recorded_call_attempts,
                           COALESCE(SUM(CASE WHEN {contacted_predicate}
                                            THEN 1 ELSE 0 END), 0)
                               AS provider_calls
                    FROM ai_shadow_research_provider_calls AS call
                    LEFT JOIN ai_shadow_research_provider_free_partial_resumes
                              AS partial_resume
                      ON partial_resume.failed_call_id=call.call_id
                     AND partial_resume.run_id=call.run_id
                     AND partial_resume.market_date=call.market_date
                    WHERE {range_predicate}
                    """,
                    (
                        *PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
                        starts_at.isoformat(),
                        ends_at.isoformat(),
                    ),
                ).fetchone()
                last_attempt = conn.execute(
                    f"""
                    SELECT call.created_at, call.updated_at, call.status,
                           call.failure_code, call.call_kind, call.market_date
                    FROM ai_shadow_research_provider_calls AS call
                    WHERE {range_predicate}
                    ORDER BY julianday(call.created_at) DESC, call.call_id DESC
                    LIMIT 1
                    """,
                    (starts_at.isoformat(), ends_at.isoformat()),
                ).fetchone()
                last_provider_call = conn.execute(
                    f"""
                    SELECT call.created_at, call.market_date
                    FROM ai_shadow_research_provider_calls AS call
                    LEFT JOIN ai_shadow_research_provider_free_partial_resumes
                              AS partial_resume
                      ON partial_resume.failed_call_id=call.call_id
                     AND partial_resume.run_id=call.run_id
                     AND partial_resume.market_date=call.market_date
                    WHERE {range_predicate} AND {contacted_predicate}
                    ORDER BY julianday(call.created_at) DESC, call.call_id DESC
                    LIMIT 1
                    """,
                    (
                        starts_at.isoformat(),
                        ends_at.isoformat(),
                        *PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
                    ),
                ).fetchone()
        except sqlite3.OperationalError:
            totals = None
            last_attempt = None
            last_provider_call = None
        recorded = int(totals["recorded_call_attempts"]) if totals else 0
        calls = int(totals["provider_calls"]) if totals else 0
        attempt = dict(last_attempt) if last_attempt is not None else {}
        return {
            "schema_version": "karkinos.ai.provider_local_day_activity.v1",
            "local_date": local_date,
            "timezone": timezone_name,
            "provider_calls": calls,
            "recorded_call_attempts": recorded,
            "provider_free_rejections": recorded - calls,
            "last_attempt_at": attempt.get("created_at"),
            "last_attempt_updated_at": attempt.get("updated_at"),
            "last_attempt_status": attempt.get("status"),
            "last_attempt_failure_code": attempt.get("failure_code"),
            "last_attempt_kind": attempt.get("call_kind"),
            "last_attempt_market_date": attempt.get("market_date"),
            "last_provider_call_at": (
                last_provider_call["created_at"]
                if last_provider_call is not None
                else None
            ),
            "last_provider_call_market_date": (
                last_provider_call["market_date"]
                if last_provider_call is not None
                else None
            ),
            "read_only": True,
            "provider_contact_performed": False,
            "database_writes_performed": False,
            "authority_effect": "none",
        }

    def _load_usage_records(
        self,
        conn: sqlite3.Connection,
        market_date: str,
    ) -> dict[str, Any]:
        totals = dict(self._provider_call_usage_totals(conn, market_date))
        retry = conn.execute(
            """
            SELECT authorization.authorization_id,
                   authorization.authorized_additional_calls,
                   authorization.provider_call_ceiling,
                   consumption.replacement_run_id
            FROM ai_shadow_research_retry_authorizations AS authorization
            LEFT JOIN ai_shadow_research_retry_consumptions AS consumption
              ON consumption.authorization_id=authorization.authorization_id
            WHERE authorization.market_date=?
            """,
            (market_date,),
        ).fetchone()
        citation = conn.execute(
            """
            SELECT extension.extension_id, extension.authorized_additional_calls,
                   extension.provider_call_ceiling, consumption.replacement_run_id
            FROM ai_shadow_research_citation_call_extensions AS extension
            LEFT JOIN ai_shadow_research_citation_call_extension_consumptions
                 AS consumption ON consumption.extension_id=extension.extension_id
            WHERE extension.market_date=?
            """,
            (market_date,),
        ).fetchone()
        output_truncation = conn.execute(
            """
            SELECT extension.extension_id, extension.authorized_additional_calls,
                   extension.provider_call_ceiling, consumption.replacement_run_id
            FROM ai_shadow_research_output_truncation_call_extensions AS extension
            LEFT JOIN ai_shadow_research_output_truncation_call_extension_consumptions
                 AS consumption ON consumption.extension_id=extension.extension_id
            WHERE extension.market_date=?
            """,
            (market_date,),
        ).fetchone()
        timeout_resume = conn.execute(
            """
            SELECT extension.extension_id, extension.authorized_additional_calls,
                   extension.provider_call_ceiling, extension.resume_iteration,
                   consumption.resumed_run_id
            FROM ai_shadow_research_timeout_resume_call_extensions AS extension
            LEFT JOIN ai_shadow_research_timeout_resume_call_extension_consumptions
                 AS consumption ON consumption.extension_id=extension.extension_id
            WHERE extension.market_date=?
            """,
            (market_date,),
        ).fetchone()
        corrected_panel = conn.execute(
            """
            SELECT authorization.authorization_id,
                   authorization.authorized_additional_calls,
                   authorization.provider_call_ceiling,
                   consumption.replacement_run_id
            FROM ai_shadow_research_corrected_panel_rearm_authorizations
                 AS authorization
            LEFT JOIN ai_shadow_research_corrected_panel_rearm_consumptions
                 AS consumption
              ON consumption.authorization_id=authorization.authorization_id
            WHERE authorization.market_date=?
            """,
            (market_date,),
        ).fetchone()
        corrected_panel_citation_resume = conn.execute(
            """
            SELECT extension.extension_id, extension.authorized_additional_calls,
                   extension.provider_call_ceiling, extension.resume_iteration,
                   extension.resume_stage, consumption.resumed_run_id
            FROM ai_shadow_research_corrected_panel_citation_resume_extensions
                 AS extension
            LEFT JOIN ai_shadow_research_corrected_panel_citation_resume_consumptions
                 AS consumption ON consumption.extension_id=extension.extension_id
            WHERE extension.market_date=?
            """,
            (market_date,),
        ).fetchone()
        provider_free_partial_resume = conn.execute(
            """
            SELECT resume_id, run_id, failed_call_id, failure_code,
                   completed_iteration_count, resume_iteration
            FROM ai_shadow_research_provider_free_partial_resumes
            WHERE market_date=? ORDER BY consumed_at DESC LIMIT 1
            """,
            (market_date,),
        ).fetchone()
        return {
            "totals": totals,
            "retry": _optional_record(retry),
            "citation": _optional_record(citation),
            "output_truncation": _optional_record(output_truncation),
            "timeout_resume": _optional_record(timeout_resume),
            "corrected_panel": _optional_record(corrected_panel),
            "corrected_panel_citation_resume": _optional_record(
                corrected_panel_citation_resume
            ),
            "provider_free_partial_resume": _optional_record(
                provider_free_partial_resume
            ),
        }


def _optional_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
