"""Append-only provider-free account-qualification evidence repository."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from server.contracts.ai_shadow_research_qualification import (
    SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
    SHADOW_RESEARCH_QUALIFICATION_TARGET_STAGE,
    SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES,
    ShadowResearchQualificationRejected,
    build_qualification_candidate_values,
    normalize_qualification_blockers,
    public_qualification_approval_projection,
    public_qualification_candidate_projection,
    public_qualification_run_projection,
    qualification_bounded_limit,
    qualification_candidate_fingerprint,
    qualification_candidate_record,
    qualification_payload_fingerprint,
    qualification_required_text,
    qualification_run_identity,
    qualification_run_input_fingerprint,
    qualification_run_record,
    require_qualification_terminal_payload,
)
from server.contracts.content_identity import canonical_json, content_fingerprint
from server.persistence.ai_shadow_research_qualification_candidate_uow import (
    qualification_candidate_id,
    save_qualification_candidate_row,
)
from server.persistence.daily_strategy_backups import DailyStrategyBackupStore
from server.projections.daily_strategy_artifacts import selection_from_record


class ShadowResearchQualificationRepositoryMixin:
    def create_or_get_qualification_run(
        self,
        *,
        source_run_id: str,
        market_date: str,
        source_selection_id: str,
        source_selection_fingerprint: str,
        source_backup_fingerprint: str,
        valuation_snapshot_id: str,
        valuation_snapshot_fingerprint: str,
        ledger_cutoff_id: int,
        ledger_fingerprint: str,
        account_evidence_reference: str,
        account_evidence_fingerprint: str,
        account_truth_source_fingerprint: str,
        account_truth_scope_fingerprint: str,
        reviewed_cost_model_reference: str,
        reviewed_fee_schedule_fingerprint: str,
        initial_cash_text: str,
        baseline_result_id: int,
        now: str,
        input_fingerprint: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        identity = qualification_run_identity(
            source_run_id=source_run_id,
            market_date=market_date,
            source_selection_id=source_selection_id,
            source_selection_fingerprint=source_selection_fingerprint,
            source_backup_fingerprint=source_backup_fingerprint,
            valuation_snapshot_id=valuation_snapshot_id,
            valuation_snapshot_fingerprint=valuation_snapshot_fingerprint,
            ledger_cutoff_id=ledger_cutoff_id,
            ledger_fingerprint=ledger_fingerprint,
            account_evidence_reference=account_evidence_reference,
            account_evidence_fingerprint=account_evidence_fingerprint,
            account_truth_source_fingerprint=account_truth_source_fingerprint,
            account_truth_scope_fingerprint=account_truth_scope_fingerprint,
            reviewed_cost_model_reference=reviewed_cost_model_reference,
            reviewed_fee_schedule_fingerprint=reviewed_fee_schedule_fingerprint,
            initial_cash_text=initial_cash_text,
            baseline_result_id=baseline_result_id,
        )
        expected_fingerprint = qualification_run_input_fingerprint(identity)
        if input_fingerprint not in (None, "", expected_fingerprint):
            raise ShadowResearchQualificationRejected(
                "qualification_input_fingerprint_conflict"
            )
        qualification_run_id = "ai-shadow-qualification-" + expected_fingerprint[:24]
        timestamp = qualification_required_text(now, "now")
        stored_identity = {
            key: value for key, value in identity.items() if key != "schema_version"
        }
        with self._connect(immediate=True) as conn:
            self._require_current_source_artifact_binding(conn, stored_identity)
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE input_fingerprint=? OR qualification_run_id=?
                """,
                (expected_fingerprint, qualification_run_id),
            ).fetchone()
            if existing is not None:
                if not _run_identity_matches(
                    existing,
                    identity=stored_identity,
                    input_fingerprint=expected_fingerprint,
                ):
                    raise ShadowResearchQualificationRejected(
                        "qualification_run_identity_conflict"
                    )
                return qualification_run_record(dict(existing)), True
            conn.execute(
                """
                INSERT INTO ai_shadow_research_qualification_runs
                (qualification_run_id, source_run_id, market_date,
                 source_selection_id, source_selection_fingerprint,
                 source_backup_fingerprint, valuation_snapshot_id,
                 valuation_snapshot_fingerprint, ledger_cutoff_id,
                 ledger_fingerprint, account_evidence_reference,
                 account_evidence_fingerprint, account_truth_source_fingerprint,
                 account_truth_scope_fingerprint, reviewed_cost_model_reference,
                 reviewed_fee_schedule_fingerprint, initial_cash_text,
                 baseline_result_id, input_fingerprint, status, selection_json,
                 selection_fingerprint, blockers_json, failure_code, created_at,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'running', NULL, NULL, '[]', NULL, ?, ?)
                """,
                (
                    qualification_run_id,
                    stored_identity["source_run_id"],
                    stored_identity["market_date"],
                    stored_identity["source_selection_id"],
                    stored_identity["source_selection_fingerprint"],
                    stored_identity["source_backup_fingerprint"],
                    stored_identity["valuation_snapshot_id"],
                    stored_identity["valuation_snapshot_fingerprint"],
                    stored_identity["ledger_cutoff_id"],
                    stored_identity["ledger_fingerprint"],
                    stored_identity["account_evidence_reference"],
                    stored_identity["account_evidence_fingerprint"],
                    stored_identity["account_truth_source_fingerprint"],
                    stored_identity["account_truth_scope_fingerprint"],
                    stored_identity["reviewed_cost_model_reference"],
                    stored_identity["reviewed_fee_schedule_fingerprint"],
                    stored_identity["initial_cash_text"],
                    stored_identity["baseline_result_id"],
                    expected_fingerprint,
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE qualification_run_id=?
                """,
                (qualification_run_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("qualification run insert returned no row")
        return qualification_run_record(dict(row)), False

    def finish_qualification_run(
        self,
        qualification_run_id: str,
        *,
        status: str,
        selection: Mapping[str, Any],
        blockers: Sequence[str] | None,
        failure_code: str | None,
        now: str,
        selection_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        if status not in SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES:
            raise ShadowResearchQualificationRejected(
                "qualification_terminal_status_invalid"
            )
        selection_payload, expected_selection_fingerprint = (
            qualification_payload_fingerprint(
                selection,
                embedded_field="selection_fingerprint",
            )
        )
        if selection_fingerprint not in (
            None,
            "",
            expected_selection_fingerprint,
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_selection_fingerprint_conflict"
            )
        normalized_blockers = normalize_qualification_blockers(blockers)
        normalized_failure = str(failure_code or "").strip() or None
        timestamp = qualification_required_text(now, "now")
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE qualification_run_id=?
                """,
                (qualification_run_id,),
            ).fetchone()
            if row is None:
                raise LookupError(
                    f"qualification run not found: {qualification_run_id}"
                )
            self._require_current_source_artifact_binding(conn, row)
            _require_terminal_result_valid(
                conn,
                row=row,
                status=status,
                selection=selection_payload,
                blockers=normalized_blockers,
                failure_code=normalized_failure,
            )
            selection_json = canonical_json(selection_payload)
            blockers_json = canonical_json(normalized_blockers)
            if str(row["status"]) != "running":
                if not _terminal_result_matches(
                    row,
                    status=status,
                    selection_json=selection_json,
                    selection_fingerprint=expected_selection_fingerprint,
                    blockers_json=blockers_json,
                    failure_code=normalized_failure,
                ):
                    raise ShadowResearchQualificationRejected(
                        "qualification_terminal_result_conflict"
                    )
                return qualification_run_record(dict(row))
            conn.execute(
                """
                UPDATE ai_shadow_research_qualification_runs
                SET status=?, selection_json=?, selection_fingerprint=?,
                    blockers_json=?, failure_code=?, updated_at=?
                WHERE qualification_run_id=?
                """,
                (
                    status,
                    selection_json,
                    expected_selection_fingerprint,
                    blockers_json,
                    normalized_failure,
                    timestamp,
                    qualification_run_id,
                ),
            )
            updated = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE qualification_run_id=?
                """,
                (qualification_run_id,),
            ).fetchone()
        if updated is None:
            raise RuntimeError("qualification run completion returned no row")
        return qualification_run_record(dict(updated))

    def save_qualification_candidate(
        self,
        *,
        qualification_run_id: str,
        source_candidate_id: str,
        source_draft_id: str,
        source_formula_fingerprint: str,
        qualified_formula_fingerprint: str,
        source_formula_semantic_fingerprint: str,
        qualified_formula_semantic_fingerprint: str,
        candidate_result_id: int | None,
        comparison: Mapping[str, Any],
        status: str,
        recommendation: str,
        rank: int,
        now: str,
        comparison_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        normalized = build_qualification_candidate_values(
            qualification_run_id=qualification_run_id,
            source_candidate_id=source_candidate_id,
            source_draft_id=source_draft_id,
            source_formula_fingerprint=source_formula_fingerprint,
            qualified_formula_fingerprint=qualified_formula_fingerprint,
            source_formula_semantic_fingerprint=(source_formula_semantic_fingerprint),
            qualified_formula_semantic_fingerprint=(
                qualified_formula_semantic_fingerprint
            ),
            candidate_result_id=candidate_result_id,
            comparison=comparison,
            comparison_fingerprint=comparison_fingerprint,
            status=status,
            recommendation=recommendation,
            rank=rank,
            now=now,
        )
        candidate_id = qualification_candidate_id(normalized)
        with self._connect(immediate=True) as conn:
            run = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE qualification_run_id=?
                """,
                (normalized["qualification_run_id"],),
            ).fetchone()
            if run is None:
                raise ShadowResearchQualificationRejected(
                    "qualification_run_not_running"
                )
            self._require_current_source_artifact_binding(conn, run)
            return save_qualification_candidate_row(
                conn,
                qualification_candidate_id=candidate_id,
                values=normalized,
            )

    def get_qualification_run(self, qualification_run_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE qualification_run_id=?
                """,
                (qualification_run_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"qualification run not found: {qualification_run_id}")
        return qualification_run_record(dict(row))

    def get_public_qualification_run(self, qualification_run_id: str) -> dict[str, Any]:
        return public_qualification_run_projection(
            self.get_qualification_run(qualification_run_id)
        )

    def list_qualification_runs(
        self,
        *,
        limit: int = 20,
        source_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_limit = qualification_bounded_limit(limit)
        where = "WHERE source_run_id=?" if source_run_id else ""
        parameters: tuple[Any, ...] = (
            (
                qualification_required_text(source_run_id, "source_run_id"),
                normalized_limit,
            )
            if source_run_id
            else (normalized_limit,)
        )
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    f"""
                    SELECT * FROM ai_shadow_research_qualification_runs
                    {where}
                    ORDER BY updated_at DESC, qualification_run_id DESC
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [qualification_run_record(dict(row)) for row in rows]

    def list_public_qualification_runs(
        self,
        *,
        limit: int = 20,
        source_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            public_qualification_run_projection(run)
            for run in self.list_qualification_runs(
                limit=limit,
                source_run_id=source_run_id,
            )
        ]

    def get_qualification_candidate(
        self, qualification_candidate_id: str
    ) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_candidates
                WHERE qualification_candidate_id=?
                """,
                (qualification_candidate_id,),
            ).fetchone()
        if row is None:
            raise LookupError(
                f"qualification candidate not found: {qualification_candidate_id}"
            )
        return qualification_candidate_record(dict(row))

    def get_public_qualification_candidate(
        self, qualification_candidate_id: str
    ) -> dict[str, Any]:
        return public_qualification_candidate_projection(
            self.get_qualification_candidate(qualification_candidate_id)
        )

    def list_qualification_candidates(
        self, qualification_run_id: str
    ) -> list[dict[str, Any]]:
        with self._connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_candidates
                WHERE qualification_run_id=?
                ORDER BY rank, qualification_candidate_id
                """,
                (
                    qualification_required_text(
                        qualification_run_id, "qualification_run_id"
                    ),
                ),
            ).fetchall()
        return [qualification_candidate_record(dict(row)) for row in rows]

    def list_public_qualification_candidates(
        self, qualification_run_id: str
    ) -> list[dict[str, Any]]:
        return [
            public_qualification_candidate_projection(candidate)
            for candidate in self.list_qualification_candidates(qualification_run_id)
        ]

    def approve_qualification_candidate(
        self,
        qualification_candidate_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        prepared = self.prepare_qualification_candidate_approval(
            qualification_candidate_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=now,
        )
        requested = {
            key: prepared[key]
            for key in (
                "qualification_approval_id",
                "qualification_run_id",
                "qualification_candidate_id",
                "target_stage",
                "approved_by",
                "notes",
                "confirmation",
                "qualification_candidate_fingerprint",
                "created_at",
            )
        }
        with self._connect(immediate=True) as conn:
            candidate_row = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_candidates
                WHERE qualification_candidate_id=?
                """,
                (qualification_candidate_id,),
            ).fetchone()
            if candidate_row is None:
                raise LookupError(
                    f"qualification candidate not found: {qualification_candidate_id}"
                )
            candidate = qualification_candidate_record(dict(candidate_row))
            run_row = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE qualification_run_id=?
                """,
                (candidate["qualification_run_id"],),
            ).fetchone()
            if run_row is None:
                raise ShadowResearchQualificationRejected(
                    "qualification_approval_run_missing"
                )
            run = qualification_run_record(dict(run_row))
            self._require_current_source_artifact_binding(conn, run_row)
            _require_candidate_approval_eligible(run=run, candidate=candidate)
            if requested["qualification_candidate_fingerprint"] != (
                qualification_candidate_fingerprint(candidate)
            ):
                raise ShadowResearchQualificationRejected(
                    "qualification_approval_candidate_changed"
                )
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_approvals
                WHERE qualification_candidate_id=?
                """,
                (qualification_candidate_id,),
            ).fetchone()
            if existing is not None:
                existing_record = dict(existing)
                replay_fields = {
                    key: value
                    for key, value in requested.items()
                    if key != "created_at"
                }
                if any(
                    existing_record[key] != value
                    for key, value in replay_fields.items()
                ):
                    raise ShadowResearchQualificationRejected(
                        "qualification_approval_conflict"
                    )
                return public_qualification_approval_projection(
                    {**existing_record, "reused": True}
                )
            conn.execute(
                """
                INSERT INTO ai_shadow_research_qualification_approvals
                (qualification_approval_id, qualification_run_id,
                 qualification_candidate_id, target_stage, approved_by, notes,
                 confirmation, qualification_candidate_fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(requested.values()),
            )
        return public_qualification_approval_projection({**requested, "reused": False})

    def prepare_qualification_candidate_approval(
        self,
        qualification_candidate_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        """Validate and project an approval without performing any write."""

        if confirmation != SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION:
            raise PermissionError(
                "qualification approval requires exact human confirmation"
            )
        normalized_approver = qualification_required_text(approved_by, "approved_by")
        normalized_notes = qualification_required_text(notes, "approval_notes")
        timestamp = qualification_required_text(now, "now")
        with self._connect_readonly() as conn:
            candidate_row = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_candidates
                WHERE qualification_candidate_id=?
                """,
                (qualification_candidate_id,),
            ).fetchone()
            if candidate_row is None:
                raise LookupError(
                    f"qualification candidate not found: {qualification_candidate_id}"
                )
            candidate = qualification_candidate_record(dict(candidate_row))
            run_row = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE qualification_run_id=?
                """,
                (candidate["qualification_run_id"],),
            ).fetchone()
            if run_row is None:
                raise ShadowResearchQualificationRejected(
                    "qualification_approval_run_missing"
                )
            self._require_current_source_artifact_binding(conn, run_row)
            _require_candidate_approval_eligible(
                run=qualification_run_record(dict(run_row)),
                candidate=candidate,
            )
        candidate_fingerprint = qualification_candidate_fingerprint(candidate)
        approval_id = (
            "ai-shadow-qualification-approval-"
            + content_fingerprint(
                {
                    "qualification_candidate_id": qualification_candidate_id,
                    "qualification_candidate_fingerprint": candidate_fingerprint,
                }
            )[:24]
        )
        return public_qualification_approval_projection(
            {
                "qualification_approval_id": approval_id,
                "qualification_run_id": candidate["qualification_run_id"],
                "qualification_candidate_id": qualification_candidate_id,
                "target_stage": SHADOW_RESEARCH_QUALIFICATION_TARGET_STAGE,
                "approved_by": normalized_approver,
                "notes": normalized_notes,
                "confirmation": confirmation,
                "qualification_candidate_fingerprint": candidate_fingerprint,
                "created_at": timestamp,
                "reused": False,
            }
        )

    def get_qualification_approval(
        self, qualification_candidate_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._connect_readonly() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM ai_shadow_research_qualification_approvals
                    WHERE qualification_candidate_id=?
                    """,
                    (qualification_candidate_id,),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        return (
            public_qualification_approval_projection(dict(row))
            if row is not None
            else None
        )

    def _require_current_source_artifact_binding(
        self,
        conn: sqlite3.Connection,
        identity: Mapping[str, Any],
    ) -> None:
        _require_source_artifact_binding(
            conn,
            identity,
            backup_root=self._qualification_backup_root,
        )


def _require_source_artifact_binding(
    conn: sqlite3.Connection,
    identity: Mapping[str, Any],
    *,
    backup_root: Any,
) -> None:
    source_run = conn.execute(
        "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
        (identity["source_run_id"],),
    ).fetchone()
    if (
        source_run is None
        or str(source_run["market_date"]) != identity["market_date"]
        or str(source_run["status"]) != "completed"
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_source_run_not_complete"
        )
    try:
        selection = conn.execute(
            """
            SELECT * FROM ai_shadow_research_daily_selections
            WHERE selection_id=?
            """,
            (identity["source_selection_id"],),
        ).fetchone()
        backup = conn.execute(
            """
            SELECT * FROM ai_shadow_research_daily_backups
            WHERE run_id=?
            """,
            (identity["source_run_id"],),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_source_artifacts_missing"
        ) from exc
    if (
        selection is None
        or str(selection["run_id"]) != identity["source_run_id"]
        or str(selection["market_date"]) != identity["market_date"]
        or str(selection["selection_fingerprint"])
        != identity["source_selection_fingerprint"]
        or backup is None
        or str(backup["selection_id"]) != identity["source_selection_id"]
        or str(backup["run_id"]) != identity["source_run_id"]
        or str(backup["market_date"]) != identity["market_date"]
        or str(backup["artifact_fingerprint"]) != identity["source_backup_fingerprint"]
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_source_artifact_binding_mismatch"
        )
    selection_projection = selection_from_record(dict(selection))
    if (
        selection_projection.get("integrity_status") != "verified"
        or selection_projection.get("run_id") != identity["source_run_id"]
        or selection_projection.get("market_date") != identity["market_date"]
        or selection_projection.get("selection_id") != identity["source_selection_id"]
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_source_selection_live_verification_failed"
        )
    backup_store = DailyStrategyBackupStore(backup_root)
    receipt = backup_store.project_receipt(dict(backup))
    if (
        receipt.get("verification_status") != "verified"
        or receipt.get("artifact_fingerprint") != identity["source_backup_fingerprint"]
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_source_backup_live_verification_failed"
        )
    try:
        backup_payload = backup_store.load_verified_payload(dict(backup))
    except (OSError, ValueError) as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_source_backup_live_verification_failed"
        ) from exc
    expected_selection = dict(selection_projection)
    expected_selection.pop("integrity_status", None)
    if backup_payload.get("selection") != expected_selection:
        raise ShadowResearchQualificationRejected(
            "qualification_source_selection_backup_binding_mismatch"
        )


def _require_terminal_result_valid(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    status: str,
    selection: Mapping[str, Any],
    blockers: Sequence[str],
    failure_code: str | None,
) -> None:
    winner_id = require_qualification_terminal_payload(
        run=row,
        status=status,
        selection=selection,
        blockers=blockers,
        failure_code=failure_code,
    )
    if winner_id is not None:
        winner = conn.execute(
            """
            SELECT * FROM ai_shadow_research_qualification_candidates
            WHERE qualification_candidate_id=? AND qualification_run_id=?
            """,
            (winner_id, row["qualification_run_id"]),
        ).fetchone()
        if (
            winner is None
            or str(winner["status"]) != "qualified"
            or str(winner["recommendation"]) != "paper_shadow_review"
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_winner_not_eligible"
            )


def _require_candidate_approval_eligible(
    *,
    run: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> None:
    selection = run.get("selection")
    if (
        run.get("status") != "completed"
        or not isinstance(selection, Mapping)
        or selection.get("status") != "winner_selected"
        or selection.get("winner_qualification_candidate_id")
        != candidate.get("qualification_candidate_id")
        or candidate.get("status") != "qualified"
        or candidate.get("recommendation") != "paper_shadow_review"
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_candidate_not_eligible_for_approval"
        )


def _run_identity_matches(
    row: sqlite3.Row,
    *,
    identity: Mapping[str, Any],
    input_fingerprint: str,
) -> bool:
    return row["input_fingerprint"] == input_fingerprint and all(
        row[key] == value for key, value in identity.items()
    )


def _terminal_result_matches(
    row: sqlite3.Row,
    *,
    status: str,
    selection_json: str,
    selection_fingerprint: str,
    blockers_json: str,
    failure_code: str | None,
) -> bool:
    expected = {
        "status": status,
        "selection_json": selection_json,
        "selection_fingerprint": selection_fingerprint,
        "blockers_json": blockers_json,
        "failure_code": failure_code,
    }
    return all(row[key] == value for key, value in expected.items())


__all__ = ["ShadowResearchQualificationRepositoryMixin"]
