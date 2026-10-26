"""Read-only persisted backtest evidence for qualification promotion checks."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from server.contracts.ai_shadow_research_qualification import (
    SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
    SHADOW_RESEARCH_QUALIFICATION_TARGET_STAGE,
    ShadowResearchQualificationRejected,
    public_qualification_approval_projection,
    qualification_candidate_fingerprint,
    qualification_candidate_record,
    qualification_run_record,
)
from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.strategy_research import backtest_evidence_blocker
from server.persistence.backtest_results import (
    backtest_invalidation_for_result,
    with_backtest_invalidation,
)


class ShadowResearchQualificationPromotionRepositoryMixin:
    """Read the exact canonical backtest rows bound by a qualification run."""

    def configure_research_policy(
        self, *, policy, simulation_change, expected_generation, now
    ):
        """Keep SIM opt-in/revocation serialized with the existing policy write."""
        from server.contracts.ai_shadow_research_automation import ShadowResearchPolicy

        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM automation_policies WHERE policy_id='ai_shadow_research'"
            ).fetchone()
            previous = _json_object(row["payload_json"]) if row else {}
            prior = previous.get("simulation_validation") or {}
            saved = dict(policy)
            if simulation_change:
                current = saved.get("simulation_validation") or {}
                if prior.get("generation") != expected_generation:
                    raise ValueError("simulation_policy_generation_conflict")
                if prior and current.get("grant_id") != prior.get("grant_id"):
                    raise ValueError("simulation_policy_identity_conflict")
            elif previous.get("simulation_validation") is not None:
                saved["simulation_validation"] = previous["simulation_validation"]
            else:
                saved.pop("simulation_validation", None)
            saved = ShadowResearchPolicy.from_mapping(saved).to_dict()
            conn.execute(
                """INSERT INTO automation_policies(policy_id,payload_json,created_at,updated_at,updated_by)
                VALUES('ai_shadow_research',?,?,?,?) ON CONFLICT(policy_id) DO UPDATE SET
                payload_json=excluded.payload_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (
                    canonical_json(saved),
                    row["created_at"] if row else now,
                    now,
                    saved["updated_by"],
                ),
            )
        return {
            **saved,
            "created_at": row["created_at"] if row else now,
            "updated_at": now,
        }

    def configure_publication_grant(
        self, *, policy: Mapping[str, Any], expected_generation: str | None, now: str
    ) -> dict[str, Any]:
        from server.contracts.recommendation_publication import (
            PUBLICATION_POLICY_ID,
            validate_publication_grant,
        )

        validated = validate_publication_grant(policy)
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM automation_policies WHERE policy_id=?",
                (PUBLICATION_POLICY_ID,),
            ).fetchone()
            previous = _json_object(row["payload_json"]) if row is not None else {}
            if previous.get("generation") != expected_generation:
                raise ValueError("publication_grant_generation_conflict")
            if previous and previous.get("grant_id") != validated["grant_id"]:
                raise ValueError("publication_grant_identity_conflict")
            conn.execute(
                """INSERT INTO automation_policies
                (policy_id,payload_json,created_at,updated_at,updated_by)
                VALUES (?,?,?,?,?) ON CONFLICT(policy_id) DO UPDATE SET
                payload_json=excluded.payload_json,updated_at=excluded.updated_at,
                updated_by=excluded.updated_by""",
                (
                    PUBLICATION_POLICY_ID,
                    canonical_json(validated),
                    row["created_at"] if row is not None else now,
                    now,
                    validated["updated_by"],
                ),
            )
        return validated

    def publish_qualified_candidate_under_policy(
        self,
        *,
        strategy_id: str,
        readiness: Mapping[str, Any],
        decision: Mapping[str, Any],
        expected_state: Mapping[str, Any] | None,
        incumbent: Mapping[str, Any] | None,
        current_evidence_validator: Callable[[], Mapping[str, Any]],
        now: str,
    ) -> dict[str, Any]:
        """Commit a real policy decision and one explicitly bound replacement."""
        from server.contracts.recommendation_publication import (
            PUBLICATION_POLICY_ID,
            publication_time,
            validate_publication_grant,
        )

        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM automation_policies WHERE policy_id=?",
                (PUBLICATION_POLICY_ID,),
            ).fetchone()
            policy = validate_publication_grant(_json_object(row[0]) if row else {})
            if (
                not policy["enabled"]
                or policy["grant_id"] != decision["grant_id"]
                or policy["generation"] != decision["generation"]
                or publication_time(now) >= publication_time(policy["expires_at"])
            ):
                raise ValueError("publication_grant_changed_or_inactive")
            current_row = conn.execute(
                "SELECT * FROM strategy_promotion_states WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
            current = dict(current_row) if current_row is not None else None
            payload = _json_object(current["payload_json"]) if current else {}
            if (
                current
                and current["stage"] == "paper_shadow"
                and payload.get("publication_decision") == dict(decision)
            ):
                return {"strategy_promotion": current, "reused": True}
            if promotion_state_fingerprint(current) != promotion_state_fingerprint(
                expected_state
            ):
                raise ValueError("publication_candidate_state_conflict")
            if current and current["stage"] in {"retired", "paused"}:
                raise ValueError("publication_terminal_source_requires_new_version")
            events = conn.execute(
                "SELECT payload_json FROM strategy_promotion_events WHERE event_type='policy_publication'"
            ).fetchall()
            used = sum(
                _json_object(item[0]).get("grant_id") == policy["grant_id"]
                for item in events
            )
            if used >= policy["max_publications"]:
                raise ValueError("publication_count_budget_exhausted")
            reopened = current_evidence_validator()
            if dict(reopened) != dict(readiness):
                raise ValueError("publication_evidence_changed")
            incumbent_id = decision.get("expected_incumbent_strategy_id")
            if incumbent_id:
                incumbent_row = conn.execute(
                    "SELECT * FROM strategy_promotion_states WHERE strategy_id=?",
                    (incumbent_id,),
                ).fetchone()
                actual = dict(incumbent_row) if incumbent_row else None
                if (
                    not actual
                    or actual["stage"] != "paper_shadow"
                    or promotion_state_fingerprint(actual)
                    != promotion_state_fingerprint(incumbent)
                ):
                    raise ValueError("publication_incumbent_state_conflict")
            state_payload = {
                "schema_version": "karkinos.strategy_promotion_pipeline.v1",
                "decision_source": "policy",
                "readiness": dict(readiness),
                "publication_decision": dict(decision),
                "live_like_enabled": False,
                "broker_submission_enabled": False,
                "does_not_change_capital_authority": True,
            }
            conn.execute(
                """INSERT INTO strategy_promotion_states
                (strategy_id,stage,gate_status,live_like_enabled,missing_requirements_json,
                 backtest_result_id,payload_json,created_at,updated_at)
                VALUES (?,'paper_shadow','paper_shadow_enabled',0,'[]',?,?,?,?)
                ON CONFLICT(strategy_id) DO UPDATE SET stage=excluded.stage,
                gate_status=excluded.gate_status,live_like_enabled=0,
                missing_requirements_json='[]',backtest_result_id=excluded.backtest_result_id,
                payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
                (
                    strategy_id,
                    readiness["backtest_result_id"],
                    canonical_json(state_payload),
                    current["created_at"] if current else now,
                    now,
                ),
            )
            conn.execute(
                """INSERT INTO strategy_promotion_events
                (strategy_id,event_type,from_stage,to_stage,actor,payload_json,created_at)
                VALUES (?,'policy_publication',?,'paper_shadow',?,?,?)""",
                (
                    strategy_id,
                    current["stage"] if current else "research",
                    "policy:" + policy["grant_id"],
                    canonical_json(dict(decision)),
                    now,
                ),
            )
            if incumbent_id and incumbent_id != strategy_id:
                if incumbent is None:
                    raise ValueError("publication_incumbent_state_conflict")
                previous_payload = _json_object(incumbent["payload_json"])
                previous_payload.update(
                    superseded_by=strategy_id,
                    replacement_decision=decision["decision_id"],
                )
                conn.execute(
                    """UPDATE strategy_promotion_states SET stage='retired',
                    gate_status='lifecycle_retired',payload_json=?,updated_at=? WHERE strategy_id=?""",
                    (canonical_json(previous_payload), now, incumbent_id),
                )
                conn.execute(
                    """INSERT INTO strategy_promotion_events
                    (strategy_id,event_type,from_stage,to_stage,actor,payload_json,created_at)
                    VALUES (?,'lifecycle_retired','paper_shadow','retired',?,?,?)""",
                    (
                        incumbent_id,
                        "policy:" + policy["grant_id"],
                        canonical_json(dict(decision)),
                        now,
                    ),
                )
            saved = conn.execute(
                "SELECT * FROM strategy_promotion_states WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
            return {"strategy_promotion": dict(saved), "reused": False}

    def get_backtest_evidence_invalidations(
        self, result_ids: Sequence[int]
    ) -> dict[int, dict[str, Any] | None]:
        """Read current validity through the existing read-only unit of work."""
        unavailable = {
            result_id: {"status": "unavailable", "result_id": result_id}
            for result_id in result_ids
        }
        try:
            with self._connect_readonly() as conn:
                return {
                    result_id: backtest_invalidation_for_result(conn, result_id)
                    for result_id in result_ids
                }
        except (OSError, sqlite3.Error):
            return unavailable

    def get_qualification_backtest_source(self, result_id: int) -> dict[str, Any]:
        if result_id <= 0:
            raise ValueError("qualification_backtest_result_identity_missing")
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM backtest_results WHERE id=?",
                (result_id,),
            ).fetchone()
            value = (
                with_backtest_invalidation(conn, dict(row)) if row is not None else None
            )
        if value is None:
            raise LookupError(f"qualification backtest result not found: {result_id}")
        if blocker := backtest_evidence_blocker(value):
            raise ShadowResearchQualificationRejected(blocker)
        return {
            "id": result_id,
            "initial_cash": value.get("initial_cash"),
            "final_equity": value.get("final_equity"),
            "total_return": value.get("total_return"),
            "sharpe": value.get("sharpe"),
            "max_drawdown": value.get("max_drawdown"),
            "equity_curve": _json_list(value.get("equity_curve_json")),
            "metrics": _json_object(value.get("metrics_json")),
            "cost_summary": _json_object(value.get("cost_summary_json")),
        }

    def approve_qualification_candidate_for_paper_shadow(
        self,
        qualification_candidate_id: str,
        *,
        approval: Mapping[str, Any],
        strategy_id: str,
        readiness: Mapping[str, Any],
        state_payload: Mapping[str, Any],
        event_payload: Mapping[str, Any],
        expected_state: Mapping[str, Any] | None,
        current_evidence_validator: Callable[
            [], tuple[Mapping[str, Any], Sequence[str]]
        ],
        actor: str,
        now: str,
    ) -> dict[str, Any]:
        """Atomically approve and record the evidence-owned paper state."""

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
            selection = run.get("selection")
            if (
                run.get("status") != "completed"
                or not isinstance(selection, Mapping)
                or selection.get("winner_qualification_candidate_id")
                != qualification_candidate_id
                or candidate.get("status") != "qualified"
                or candidate.get("recommendation") != "paper_shadow_review"
            ):
                raise ShadowResearchQualificationRejected(
                    "qualification_candidate_not_eligible_for_approval"
                )
            candidate_fingerprint = qualification_candidate_fingerprint(candidate)
            _require_atomic_approval_request(
                approval,
                qualification_candidate_id=qualification_candidate_id,
                qualification_run_id=str(candidate["qualification_run_id"]),
                candidate_fingerprint=candidate_fingerprint,
            )
            current_evidence, current_blockers = current_evidence_validator()
            _require_current_atomic_evidence(
                current_evidence,
                current_blockers=current_blockers,
                approval=approval,
                readiness=readiness,
            )
            # The validator may read the content-addressed backup outside this
            # SQLite connection. Reopen it immediately before the writes while
            # BEGIN IMMEDIATE still excludes concurrent database writers.
            self._require_current_source_artifact_binding(conn, run_row)
            if (
                readiness.get("strategy_id") != strategy_id
                or readiness.get("candidate_id") != candidate["source_candidate_id"]
                or readiness.get("qualification_candidate_id")
                != qualification_candidate_id
                or readiness.get("qualification_run_id")
                != candidate["qualification_run_id"]
                or readiness.get("human_approval_id")
                != approval["qualification_approval_id"]
                or int(readiness.get("backtest_result_id") or 0)
                != int(candidate.get("candidate_result_id") or 0)
                or readiness.get("comparison_fingerprint")
                != candidate.get("comparison_fingerprint")
                or readiness.get("live_like_enabled") is not False
                or readiness.get("broker_submission_enabled") is not False
                or readiness.get("does_not_create_order") is not True
                or readiness.get("does_not_authorize_execution") is not True
                or readiness.get("does_not_change_capital_authority") is not True
            ):
                raise ShadowResearchQualificationRejected(
                    "qualification_atomic_promotion_readiness_invalid"
                )
            if (
                not str(actor or "").strip()
                or state_payload.get("readiness") != readiness
                or state_payload.get("live_like_enabled") is not False
                or state_payload.get("broker_submission_enabled") is not False
                or state_payload.get("does_not_change_capital_authority") is not True
                or event_payload.get("live_like_enabled") is not False
                or event_payload.get("broker_submission_enabled") is not False
                or event_payload.get("does_not_change_capital_authority") is not True
            ):
                raise ShadowResearchQualificationRejected(
                    "qualification_atomic_promotion_payload_invalid"
                )
            current = conn.execute(
                "SELECT * FROM strategy_promotion_states WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
            actual_state_fingerprint = promotion_state_fingerprint(
                dict(current) if current is not None else None
            )
            if actual_state_fingerprint != promotion_state_fingerprint(expected_state):
                raise ShadowResearchQualificationRejected(
                    "qualification_promotion_state_cas_conflict"
                )
            existing_approval = conn.execute(
                """
                SELECT * FROM ai_shadow_research_qualification_approvals
                WHERE qualification_candidate_id=?
                """,
                (qualification_candidate_id,),
            ).fetchone()
            if existing_approval is not None:
                _require_existing_approval_matches(existing_approval, approval)
            else:
                conn.execute(
                    """
                    INSERT INTO ai_shadow_research_qualification_approvals
                    (qualification_approval_id, qualification_run_id,
                     qualification_candidate_id, target_stage, approved_by, notes,
                     confirmation, qualification_candidate_fingerprint, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _approval_values(approval),
                )
            state_json = canonical_json(dict(state_payload))
            if current is not None and str(current["stage"]) == "paper_shadow":
                if (
                    bool(current["live_like_enabled"])
                    or int(current["backtest_result_id"] or 0)
                    != int(candidate["candidate_result_id"])
                    or str(current["payload_json"]) != state_json
                ):
                    raise ShadowResearchQualificationRejected(
                        "canonical_paper_shadow_qualification_binding_conflict"
                    )
                state_row = current
            else:
                created_at = str(current["created_at"]) if current is not None else now
                conn.execute(
                    """
                    INSERT INTO strategy_promotion_states
                    (strategy_id, stage, gate_status, live_like_enabled,
                     missing_requirements_json, backtest_result_id, payload_json,
                     created_at, updated_at)
                    VALUES (?, 'paper_shadow', 'paper_shadow_enabled', 0, '[]', ?, ?, ?, ?)
                    ON CONFLICT(strategy_id) DO UPDATE SET
                        stage=excluded.stage,
                        gate_status=excluded.gate_status,
                        live_like_enabled=0,
                        missing_requirements_json='[]',
                        backtest_result_id=excluded.backtest_result_id,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        strategy_id,
                        int(candidate["candidate_result_id"]),
                        state_json,
                        created_at,
                        now,
                    ),
                )
                _insert_qualification_promotion_event(
                    conn,
                    strategy_id=strategy_id,
                    from_stage=(
                        str(current["stage"]) if current is not None else "research"
                    ),
                    actor=actor,
                    payload=event_payload,
                    now=now,
                )
                state_row = conn.execute(
                    "SELECT * FROM strategy_promotion_states WHERE strategy_id=?",
                    (strategy_id,),
                ).fetchone()
            if state_row is None:
                raise RuntimeError(
                    "qualification promotion state insert returned no row"
                )
            return {
                "qualification_approval": public_qualification_approval_projection(
                    {
                        **{key: approval[key] for key in _APPROVAL_FIELDS},
                        "reused": existing_approval is not None,
                    }
                ),
                "strategy_promotion": {
                    **dict(state_row),
                    "live_like_enabled": False,
                    "missing_requirements": [],
                    "payload": _json_object(state_row["payload_json"]),
                },
            }


_APPROVAL_FIELDS = (
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


def promotion_state_fingerprint(state: Mapping[str, Any] | None) -> str | None:
    return content_fingerprint(dict(state)) if state is not None else None


def _approval_values(approval: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(approval[key] for key in _APPROVAL_FIELDS)


def _require_atomic_approval_request(
    approval: Mapping[str, Any],
    *,
    qualification_candidate_id: str,
    qualification_run_id: str,
    candidate_fingerprint: str,
) -> None:
    if (
        approval.get("qualification_candidate_id") != qualification_candidate_id
        or approval.get("qualification_run_id") != qualification_run_id
        or approval.get("target_stage") != SHADOW_RESEARCH_QUALIFICATION_TARGET_STAGE
        or approval.get("qualification_candidate_fingerprint") != candidate_fingerprint
        or approval.get("confirmation") != SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION
        or approval.get("manual_confirmation_recorded") is not True
        or approval.get("broker_submission_enabled") is not False
        or approval.get("capital_authority_granted") is not False
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_atomic_approval_binding_invalid"
        )


def _require_current_atomic_evidence(
    evidence: Mapping[str, Any],
    *,
    current_blockers: Sequence[str],
    approval: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> None:
    """Require the in-transaction replay to equal the proposed readiness."""

    expected = {
        "source_candidate_id": readiness.get("candidate_id"),
        "qualification_candidate_id": readiness.get("qualification_candidate_id"),
        "qualification_run_id": readiness.get("qualification_run_id"),
        "qualification_approval_id": readiness.get("human_approval_id"),
        "backtest_result_id": readiness.get("backtest_result_id"),
        "comparison_fingerprint": readiness.get("comparison_fingerprint"),
        "strategy_advancement_gate": readiness.get("strategy_advancement_gate"),
        "daily_strategy_artifact_binding": readiness.get(
            "daily_strategy_artifact_binding"
        ),
        "qualification_binding": readiness.get("qualification_binding"),
    }
    if (
        current_blockers
        or evidence.get("status") != "pass"
        or any(evidence.get(key) != value for key, value in expected.items())
        or evidence.get("qualification_approval_id")
        != approval.get("qualification_approval_id")
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_atomic_current_evidence_drift"
        )


def _require_existing_approval_matches(
    existing: sqlite3.Row,
    requested: Mapping[str, Any],
) -> None:
    if any(existing[key] != requested[key] for key in _APPROVAL_FIELDS[:-1]):
        raise ShadowResearchQualificationRejected("qualification_approval_conflict")


def _insert_qualification_promotion_event(
    conn: sqlite3.Connection,
    *,
    strategy_id: str,
    from_stage: str,
    actor: str,
    payload: Mapping[str, Any],
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO strategy_promotion_events
        (strategy_id, event_type, from_stage, to_stage, actor, payload_json, created_at)
        VALUES (?, 'promoted_to_paper_shadow', ?, 'paper_shadow', ?, ?, ?)
        """,
        (strategy_id, from_stage, actor, canonical_json(dict(payload)), now),
    )


def _json_list(value: Any) -> list[Any]:
    parsed = _json(value)
    return parsed if isinstance(parsed, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    parsed = _json(value)
    return parsed if isinstance(parsed, dict) else {}


def _json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in {None, ""}:
        return None
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return None


__all__ = [
    "ShadowResearchQualificationPromotionRepositoryMixin",
    "promotion_state_fingerprint",
]
