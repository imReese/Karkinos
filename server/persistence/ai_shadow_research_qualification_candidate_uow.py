"""Atomic candidate replay persistence for account qualification."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from typing import Any

from server.contracts.ai_shadow_research_qualification import (
    ShadowResearchQualificationRejected,
    build_qualification_candidate_values,
    qualification_candidate_record,
    qualification_optional_positive_int,
    qualification_required_text,
)
from server.contracts.content_identity import content_fingerprint
from server.persistence.backtest_results import insert_backtest_result


class ShadowResearchQualificationCandidateUnitOfWorkMixin:
    """Commit one candidate backtest and overlay in a single SQLite transaction."""

    def save_qualification_candidate_with_backtest(
        self,
        *,
        qualification_run_id: str,
        source_candidate_id: str,
        source_draft_id: str,
        source_formula_fingerprint: str,
        qualified_formula_fingerprint: str,
        source_formula_semantic_fingerprint: str,
        qualified_formula_semantic_fingerprint: str,
        rank: int,
        backtest_values: Mapping[str, Any],
        candidate_evidence_builder: Callable[
            [Mapping[str, Any]], tuple[Mapping[str, Any], str, str]
        ],
        now: str,
    ) -> dict[str, Any]:
        source_identity = _candidate_source_identity(
            qualification_run_id=qualification_run_id,
            source_candidate_id=source_candidate_id,
            source_draft_id=source_draft_id,
            source_formula_fingerprint=source_formula_fingerprint,
            qualified_formula_fingerprint=qualified_formula_fingerprint,
            source_formula_semantic_fingerprint=(source_formula_semantic_fingerprint),
            qualified_formula_semantic_fingerprint=(
                qualified_formula_semantic_fingerprint
            ),
            rank=rank,
        )
        candidate_id = qualification_candidate_id(source_identity)
        timestamp = qualification_required_text(now, "now")
        with self._connect(immediate=True) as conn:
            run = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_runs
                WHERE qualification_run_id=?
                """,
                (source_identity["qualification_run_id"],),
            ).fetchone()
            if run is None:
                raise ShadowResearchQualificationRejected(
                    "qualification_run_not_running"
                )
            self._require_current_source_artifact_binding(conn, run)
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_candidates
                WHERE qualification_run_id=? AND source_candidate_id=?
                """,
                (
                    source_identity["qualification_run_id"],
                    source_identity["source_candidate_id"],
                ),
            ).fetchone()
            if existing is not None:
                result = conn.execute(
                    "SELECT * FROM backtest_results WHERE id=?",
                    (existing["candidate_result_id"],),
                ).fetchone()
                if not _atomic_candidate_matches(
                    existing,
                    qualification_candidate_id=candidate_id,
                    source_identity=source_identity,
                ) or not _backtest_result_matches(result, backtest_values):
                    raise ShadowResearchQualificationRejected(
                        "qualification_candidate_conflict"
                    )
                return qualification_candidate_record(dict(existing))
            if run is None or str(run["status"]) != "running":
                raise ShadowResearchQualificationRejected(
                    "qualification_run_not_running"
                )
            require_source_candidate_binding(conn, run=run, values=source_identity)
            result_id = insert_backtest_result(
                conn,
                created_at=timestamp,
                **_normalized_backtest_values(backtest_values),
            )
            if result_id <= 0:
                raise ShadowResearchQualificationRejected(
                    "qualification_candidate_backtest_persistence_failed"
                )
            result = conn.execute(
                "SELECT * FROM backtest_results WHERE id=?", (result_id,)
            ).fetchone()
            if result is None:
                raise ShadowResearchQualificationRejected(
                    "qualification_backtest_persistence_missing"
                )
            comparison, status, recommendation = candidate_evidence_builder(
                dict(result)
            )
            values = build_qualification_candidate_values(
                **source_identity,
                candidate_result_id=result_id,
                comparison=comparison,
                comparison_fingerprint=None,
                status=status,
                recommendation=recommendation,
                now=timestamp,
            )
            return save_qualification_candidate_row(
                conn,
                qualification_candidate_id=candidate_id,
                values=values,
            )


def qualification_candidate_id(values: Mapping[str, Any]) -> str:
    return (
        "ai-shadow-qualified-candidate-"
        + content_fingerprint(
            {
                "qualification_run_id": values["qualification_run_id"],
                "source_candidate_id": values["source_candidate_id"],
                "source_draft_id": values["source_draft_id"],
                "qualified_formula_fingerprint": values[
                    "qualified_formula_fingerprint"
                ],
                "qualified_formula_semantic_fingerprint": values[
                    "qualified_formula_semantic_fingerprint"
                ],
            }
        )[:24]
    )


def save_qualification_candidate_row(
    conn: sqlite3.Connection,
    *,
    qualification_candidate_id: str,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    run = conn.execute(
        """
        SELECT * FROM ai_shadow_research_qualification_runs
        WHERE qualification_run_id=?
        """,
        (values["qualification_run_id"],),
    ).fetchone()
    existing = conn.execute(
        """
        SELECT * FROM ai_shadow_research_qualification_candidates
        WHERE qualification_run_id=? AND source_candidate_id=?
        """,
        (values["qualification_run_id"], values["source_candidate_id"]),
    ).fetchone()
    if existing is not None:
        if not _candidate_matches(
            existing,
            qualification_candidate_id=qualification_candidate_id,
            values=values,
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_candidate_conflict"
            )
        return qualification_candidate_record(dict(existing))
    if run is None or str(run["status"]) != "running":
        raise ShadowResearchQualificationRejected("qualification_run_not_running")
    require_source_candidate_binding(conn, run=run, values=values)
    try:
        conn.execute(
            """
            INSERT INTO ai_shadow_research_qualification_candidates
            (qualification_candidate_id, qualification_run_id,
             source_candidate_id, source_draft_id,
             source_formula_fingerprint, qualified_formula_fingerprint,
             source_formula_semantic_fingerprint,
             qualified_formula_semantic_fingerprint,
             candidate_result_id, comparison_json, comparison_fingerprint,
             status, recommendation, rank, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (qualification_candidate_id, *values.values()),
        )
    except sqlite3.IntegrityError as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_candidate_conflict"
        ) from exc
    row = conn.execute(
        """
        SELECT * FROM ai_shadow_research_qualification_candidates
        WHERE qualification_candidate_id=?
        """,
        (qualification_candidate_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("qualification candidate insert returned no row")
    return qualification_candidate_record(dict(row))


def require_source_candidate_binding(
    conn: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    values: Mapping[str, Any],
) -> None:
    source = conn.execute(
        """
        SELECT candidate_id, run_id, draft_id
        FROM ai_shadow_research_candidates
        WHERE candidate_id=?
        """,
        (values["source_candidate_id"],),
    ).fetchone()
    if (
        source is None
        or str(source["run_id"]) != str(run["source_run_id"])
        or str(source["draft_id"]) != values["source_draft_id"]
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_source_candidate_binding_mismatch"
        )


def _candidate_source_identity(**values: Any) -> dict[str, Any]:
    rank = qualification_optional_positive_int(values["rank"], field="candidate_rank")
    if rank is None:
        raise ShadowResearchQualificationRejected(
            "qualification_candidate_rank_invalid"
        )
    identity = {
        key: qualification_required_text(values[key], key)
        for key in (
            "qualification_run_id",
            "source_candidate_id",
            "source_draft_id",
            "source_formula_fingerprint",
            "qualified_formula_fingerprint",
            "source_formula_semantic_fingerprint",
            "qualified_formula_semantic_fingerprint",
        )
    }
    identity["rank"] = rank
    if (
        identity["source_formula_semantic_fingerprint"]
        != identity["qualified_formula_semantic_fingerprint"]
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_formula_semantics_changed"
        )
    return identity


def _normalized_backtest_values(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "config_json": str(values["config_json"]),
        "initial_cash": float(values["initial_cash"]),
        "final_equity": float(values["final_equity"]),
        "total_return": float(values["total_return"]),
        "sharpe": float(values["sharpe"]),
        "max_dd": float(values["max_dd"]),
        "equity_curve_json": str(values["equity_curve_json"]),
        "annual_return": float(values.get("annual_return") or 0),
        "sortino": float(values.get("sortino") or 0),
        "win_rate": float(values.get("win_rate") or 0),
        "duration_days": int(values.get("duration_days") or 0),
        "metrics_json": str(values.get("metrics_json") or "{}"),
        "cost_summary_json": str(values.get("cost_summary_json") or "{}"),
    }


def _backtest_result_matches(
    row: sqlite3.Row | None,
    values: Mapping[str, Any],
) -> bool:
    if row is None:
        return False
    expected = _normalized_backtest_values(values)
    expected["max_drawdown"] = expected.pop("max_dd")
    expected.pop("annual_return")
    return all(row[key] == value for key, value in expected.items())


def _atomic_candidate_matches(
    row: sqlite3.Row,
    *,
    qualification_candidate_id: str,
    source_identity: Mapping[str, Any],
) -> bool:
    return (
        row["qualification_candidate_id"] == qualification_candidate_id
        and int(row["candidate_result_id"] or 0) > 0
        and all(row[key] == value for key, value in source_identity.items())
    )


def _candidate_matches(
    row: sqlite3.Row,
    *,
    qualification_candidate_id: str,
    values: Mapping[str, Any],
) -> bool:
    return row["qualification_candidate_id"] == qualification_candidate_id and all(
        row[key] == value for key, value in values.items()
    )


__all__ = [
    "ShadowResearchQualificationCandidateUnitOfWorkMixin",
    "qualification_candidate_id",
    "save_qualification_candidate_row",
]
