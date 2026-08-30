"""Atomic retry, extension, and corrected-panel run replacement claims."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    ShadowResearchRejected,
    require_corrected_panel_rearm_evidence,
)


class ShadowResearchRunReplacementRepositoryMixin:
    """Replace one persisted run while preserving all authorization bindings."""

    def _claim_replacement_run(
        self,
        conn: sqlite3.Connection,
        *,
        existing_run: dict[str, Any],
        market_date: str,
        input_fingerprint: str,
        baseline_seed_result_id: int,
        run_context: Mapping[str, Any],
        corrected_panel_rearm_evidence: Mapping[str, Any] | None,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        claim = self._resolve_replacement_claim(
            conn,
            run=existing_run,
            input_fingerprint=input_fingerprint,
            corrected_panel_rearm_evidence=corrected_panel_rearm_evidence,
        )
        if claim is None:
            return existing_run, True
        consumptions = self._load_replacement_consumptions(
            conn,
            market_date=market_date,
            rebind_prior_consumptions=(
                bool(claim["provider_free_rearm"])
                or claim["citation_extension"] is not None
                or claim["output_truncation_extension"] is not None
            ),
        )
        return self._replace_existing_run(
            conn,
            run=existing_run,
            claim=claim,
            consumptions=consumptions,
            market_date=market_date,
            baseline_seed_result_id=baseline_seed_result_id,
            run_context=run_context,
            now=now,
        )

    def _resolve_replacement_claim(
        self,
        conn: sqlite3.Connection,
        *,
        run: Mapping[str, Any],
        input_fingerprint: str,
        corrected_panel_rearm_evidence: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        retry = self._unconsumed_retry_authorization(conn, run)
        citation = (
            self._unconsumed_citation_call_extension(conn, run)
            if input_fingerprint != run["input_fingerprint"]
            else None
        )
        output_truncation = (
            self._unconsumed_output_truncation_call_extension(conn, run)
            if input_fingerprint != run["input_fingerprint"]
            else None
        )
        corrected_panel = (
            self._unconsumed_corrected_panel_rearm_authorization(conn, run)
            if input_fingerprint != run["input_fingerprint"]
            else None
        )
        provider_free_rearm = input_fingerprint != run[
            "input_fingerprint"
        ] and self._can_rearm_provider_free_failure(conn, run)
        if retry is not None:
            input_fingerprint = content_fingerprint(
                {
                    "failed_input_fingerprint": run["input_fingerprint"],
                    "current_input_fingerprint": input_fingerprint,
                    "retry_authorization_id": retry["authorization_id"],
                }
            )
        elif citation is not None:
            input_fingerprint = content_fingerprint(
                {
                    "failed_input_fingerprint": run["input_fingerprint"],
                    "current_input_fingerprint": input_fingerprint,
                    "citation_call_extension_id": citation["extension_id"],
                }
            )
        elif output_truncation is not None:
            input_fingerprint = content_fingerprint(
                {
                    "failed_input_fingerprint": run["input_fingerprint"],
                    "current_input_fingerprint": input_fingerprint,
                    "output_truncation_call_extension_id": output_truncation[
                        "extension_id"
                    ],
                }
            )
        elif corrected_panel is not None:
            normalized = require_corrected_panel_rearm_evidence(
                corrected_panel_rearm_evidence
            )
            if (
                normalized["evidence_fingerprint"]
                != corrected_panel["expected_rearm_evidence_fingerprint"]
            ):
                raise ShadowResearchRejected("corrected_panel_rearm_evidence_drift")
            input_fingerprint = content_fingerprint(
                {
                    "completed_input_fingerprint": run["input_fingerprint"],
                    "current_input_fingerprint": input_fingerprint,
                    "corrected_panel_rearm_authorization_id": corrected_panel[
                        "authorization_id"
                    ],
                    "corrected_panel_rearm_evidence_fingerprint": normalized[
                        "evidence_fingerprint"
                    ],
                }
            )
        elif not provider_free_rearm:
            return None
        return {
            "input_fingerprint": input_fingerprint,
            "retry_authorization": retry,
            "citation_extension": citation,
            "output_truncation_extension": output_truncation,
            "corrected_panel_rearm": corrected_panel,
            "provider_free_rearm": provider_free_rearm,
        }

    def _load_replacement_consumptions(
        self,
        conn: sqlite3.Connection,
        *,
        market_date: str,
        rebind_prior_consumptions: bool,
    ) -> dict[str, sqlite3.Row | None]:
        if not rebind_prior_consumptions:
            return {
                "retry": None,
                "citation": None,
                "output_truncation": None,
                "corrected_panel": None,
            }
        retry = conn.execute(
            """
            SELECT consumption.authorization_id
            FROM ai_shadow_research_retry_consumptions AS consumption
            JOIN ai_shadow_research_retry_authorizations AS authorization
              ON authorization.authorization_id=consumption.authorization_id
            WHERE authorization.market_date=?
            """,
            (market_date,),
        ).fetchone()
        citation = conn.execute(
            """
            SELECT consumption.extension_id
            FROM ai_shadow_research_citation_call_extension_consumptions AS consumption
            JOIN ai_shadow_research_citation_call_extensions AS extension
              ON extension.extension_id=consumption.extension_id
            WHERE extension.market_date=?
            """,
            (market_date,),
        ).fetchone()
        output_truncation = conn.execute(
            """
            SELECT consumption.extension_id
            FROM ai_shadow_research_output_truncation_call_extension_consumptions
                 AS consumption
            JOIN ai_shadow_research_output_truncation_call_extensions AS extension
              ON extension.extension_id=consumption.extension_id
            WHERE extension.market_date=?
            """,
            (market_date,),
        ).fetchone()
        corrected_panel = conn.execute(
            """
            SELECT consumption.authorization_id
            FROM ai_shadow_research_corrected_panel_rearm_consumptions AS consumption
            JOIN ai_shadow_research_corrected_panel_rearm_authorizations AS authorization
              ON authorization.authorization_id=consumption.authorization_id
            WHERE authorization.market_date=?
            """,
            (market_date,),
        ).fetchone()
        return {
            "retry": retry,
            "citation": citation,
            "output_truncation": output_truncation,
            "corrected_panel": corrected_panel,
        }

    def _replace_existing_run(
        self,
        conn: sqlite3.Connection,
        *,
        run: Mapping[str, Any],
        claim: Mapping[str, Any],
        consumptions: Mapping[str, sqlite3.Row | None],
        market_date: str,
        baseline_seed_result_id: int,
        run_context: Mapping[str, Any],
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        input_fingerprint = str(claim["input_fingerprint"])
        run_id = f"ai-shadow-research:{market_date}:{input_fingerprint[:16]}"
        attempt_id = (
            "ai-shadow-research-attempt:"
            + content_fingerprint(
                {
                    "superseded_run_id": run["run_id"],
                    "replacement_run_id": run_id,
                    "recorded_at": now,
                }
            )[:24]
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_run_attempts
            (attempt_id, market_date, superseded_run_id,
             superseded_input_fingerprint, replacement_run_id,
             replacement_input_fingerprint, failure_code,
             run_snapshot_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                market_date,
                run["run_id"],
                run["input_fingerprint"],
                run_id,
                input_fingerprint,
                (
                    run["failure_code"]
                    or (
                        "corrected_panel_rearm_authorized"
                        if claim["corrected_panel_rearm"] is not None
                        else "provider_free_rearm"
                    )
                ),
                canonical_json(run),
                now,
            ),
        )
        conn.execute(
            """
            UPDATE ai_shadow_research_runs
            SET run_id=?, input_fingerprint=?, status='running',
                baseline_seed_result_id=?, baseline_result_id=NULL,
                research_capital_mode=?, research_context_id=?,
                valuation_snapshot_id=?, ledger_cutoff_id=?,
                session_id=NULL, failure_code=NULL, candidate_count=0,
                created_at=?, updated_at=?
            WHERE run_id=?
            """,
            (
                run_id,
                input_fingerprint,
                baseline_seed_result_id,
                run_context["research_capital_mode"],
                run_context["research_context_id"],
                run_context["valuation_snapshot_id"],
                run_context["ledger_cutoff_id"],
                now,
                now,
                run["run_id"],
            ),
        )
        self._record_replacement_consumptions(
            conn,
            claim=claim,
            consumptions=consumptions,
            run_id=run_id,
            input_fingerprint=input_fingerprint,
            now=now,
        )
        rearmed = conn.execute(
            "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if rearmed is None:
            raise RuntimeError("shadow research retry persistence failed")
        return dict(rearmed), False

    def _record_replacement_consumptions(
        self,
        conn: sqlite3.Connection,
        *,
        claim: Mapping[str, Any],
        consumptions: Mapping[str, sqlite3.Row | None],
        run_id: str,
        input_fingerprint: str,
        now: str,
    ) -> None:
        retry = claim["retry_authorization"]
        if retry is not None:
            conn.execute(
                """
                INSERT INTO ai_shadow_research_retry_consumptions
                (authorization_id, replacement_run_id,
                 replacement_input_fingerprint, consumed_at)
                VALUES (?, ?, ?, ?)
                """,
                (retry["authorization_id"], run_id, input_fingerprint, now),
            )
        elif consumptions["retry"] is not None:
            conn.execute(
                """
                UPDATE ai_shadow_research_retry_consumptions
                SET replacement_run_id=?, replacement_input_fingerprint=?
                WHERE authorization_id=?
                """,
                (run_id, input_fingerprint, consumptions["retry"]["authorization_id"]),
            )
        citation = claim["citation_extension"]
        if citation is not None:
            conn.execute(
                """
                INSERT INTO ai_shadow_research_citation_call_extension_consumptions
                (extension_id, replacement_run_id,
                 replacement_input_fingerprint, consumed_at)
                VALUES (?, ?, ?, ?)
                """,
                (citation["extension_id"], run_id, input_fingerprint, now),
            )
        elif consumptions["citation"] is not None:
            conn.execute(
                """
                UPDATE ai_shadow_research_citation_call_extension_consumptions
                SET replacement_run_id=?, replacement_input_fingerprint=?
                WHERE extension_id=?
                """,
                (run_id, input_fingerprint, consumptions["citation"]["extension_id"]),
            )
        output_truncation = claim["output_truncation_extension"]
        if output_truncation is not None:
            conn.execute(
                """
                INSERT INTO ai_shadow_research_output_truncation_call_extension_consumptions
                (extension_id, replacement_run_id,
                 replacement_input_fingerprint, consumed_at)
                VALUES (?, ?, ?, ?)
                """,
                (output_truncation["extension_id"], run_id, input_fingerprint, now),
            )
        elif consumptions["output_truncation"] is not None:
            conn.execute(
                """
                UPDATE ai_shadow_research_output_truncation_call_extension_consumptions
                SET replacement_run_id=?, replacement_input_fingerprint=?
                WHERE extension_id=?
                """,
                (
                    run_id,
                    input_fingerprint,
                    consumptions["output_truncation"]["extension_id"],
                ),
            )
        corrected_panel = claim["corrected_panel_rearm"]
        if corrected_panel is not None:
            conn.execute(
                """
                INSERT INTO ai_shadow_research_corrected_panel_rearm_consumptions
                (authorization_id, replacement_run_id,
                 replacement_input_fingerprint,
                 consumed_rearm_evidence_fingerprint, consumed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    corrected_panel["authorization_id"],
                    run_id,
                    input_fingerprint,
                    corrected_panel["expected_rearm_evidence_fingerprint"],
                    now,
                ),
            )
        elif consumptions["corrected_panel"] is not None:
            conn.execute(
                """
                UPDATE ai_shadow_research_corrected_panel_rearm_consumptions
                SET replacement_run_id=?, replacement_input_fingerprint=?
                WHERE authorization_id=?
                """,
                (
                    run_id,
                    input_fingerprint,
                    consumptions["corrected_panel"]["authorization_id"],
                ),
            )
