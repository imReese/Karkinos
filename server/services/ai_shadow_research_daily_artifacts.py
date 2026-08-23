"""Deterministic daily winner selection and local strategy backups.

DeepSeek may propose candidates, but this module only ranks candidates that
already passed the canonical strategy-advancement gate.  It persists one
immutable selection per research run and writes one content-addressed,
privacy-minimized JSON backup containing the reproducible Formula DSL drafts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from analytics.strategy_advancement_gate import (
    is_valid_passed_strategy_advancement_gate,
)
from server.ai_runtime.contracts import canonical_json, content_fingerprint

DAILY_STRATEGY_SELECTION_SCHEMA = "karkinos.ai.daily_strategy_selection.v1"
DAILY_STRATEGY_BACKUP_SCHEMA = "karkinos.ai.daily_strategy_backup.v1"
DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA = "karkinos.ai.daily_strategy_backup_receipt.v1"
DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA = (
    "karkinos.ai.daily_strategy_promotion_binding.v2"
)
DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA = (
    "karkinos.ai.strategy_operating_constraints.v1"
)

_COMPLETE_CANDIDATE_STATUSES = {"awaiting_human_approval", "research_blocked"}
_DRAFT_BACKUP_FIELDS = (
    "draft_id",
    "economic_hypothesis",
    "risk_impact",
    "failure_conditions",
    "limitations",
    "anti_lookahead_assumptions",
    "formula_ast",
    "formula_fingerprint",
    "parameter_values",
    "parameter_ranges",
    "selected_universe",
    "dataset_snapshot_id",
    "test_window",
    "frequency",
    "cost_model_reference",
    "iteration_context",
    "iteration_context_fingerprint",
    "validation",
)


class DailyStrategyArtifactRejected(ValueError):
    """Fail-closed daily selection or backup rejection."""


class DailyStrategyArtifactStore:
    """Persist immutable daily selections and content-addressed backups."""

    def __init__(self, db_path: str | Path, backup_root: str | Path) -> None:
        self._db_path = Path(db_path)
        self._backup_root = Path(backup_root)

    def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ai_shadow_research_daily_selections (
                    selection_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    winner_candidate_id TEXT,
                    expected_candidate_count INTEGER NOT NULL,
                    observed_candidate_count INTEGER NOT NULL,
                    selection_json TEXT NOT NULL,
                    selection_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_daily_backups (
                    backup_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    selection_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    artifact_fingerprint TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_daily_selection_date
                    ON ai_shadow_research_daily_selections(market_date DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_daily_backup_date
                    ON ai_shadow_research_daily_backups(market_date DESC);
            """)

    def record_daily_artifacts(
        self,
        *,
        run: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        drafts: Sequence[Mapping[str, Any]],
        expected_candidate_count: int,
        run_status: str,
        created_at: str,
    ) -> dict[str, Any]:
        """Select, back up, and atomically record one daily research outcome."""

        self.init()
        selection = build_daily_strategy_selection(
            run=run,
            candidates=candidates,
            expected_candidate_count=expected_candidate_count,
            created_at=created_at,
        )
        backup_payload = _build_backup_payload(
            run=run,
            run_status=run_status,
            candidates=candidates,
            drafts=drafts,
            selection=selection,
            created_at=created_at,
        )
        receipt = self._write_backup(backup_payload, created_at=created_at)
        with sqlite3.connect(self._db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            existing_selection = conn.execute(
                "SELECT * FROM ai_shadow_research_daily_selections WHERE run_id=?",
                (selection["run_id"],),
            ).fetchone()
            existing_backup = conn.execute(
                "SELECT * FROM ai_shadow_research_daily_backups WHERE run_id=?",
                (selection["run_id"],),
            ).fetchone()
            if existing_selection is not None or existing_backup is not None:
                if (
                    existing_selection is None
                    or existing_backup is None
                    or existing_selection["selection_fingerprint"]
                    != selection["selection_fingerprint"]
                    or existing_backup["artifact_fingerprint"]
                    != receipt["artifact_fingerprint"]
                ):
                    raise DailyStrategyArtifactRejected("daily_artifact_conflict")
                return {
                    "selection": _selection_from_row(existing_selection),
                    "backup": self._backup_projection(existing_backup),
                    "reused": True,
                }
            conn.execute(
                """
                INSERT INTO ai_shadow_research_daily_selections
                (selection_id, run_id, market_date, status, winner_candidate_id,
                 expected_candidate_count, observed_candidate_count, selection_json,
                 selection_fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selection["selection_id"],
                    selection["run_id"],
                    selection["market_date"],
                    selection["status"],
                    selection["winner_candidate_id"],
                    selection["expected_candidate_count"],
                    selection["observed_candidate_count"],
                    canonical_json(selection),
                    selection["selection_fingerprint"],
                    created_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_shadow_research_daily_backups
                (backup_id, run_id, market_date, selection_id, relative_path,
                 artifact_fingerprint, byte_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt["backup_id"],
                    selection["run_id"],
                    selection["market_date"],
                    selection["selection_id"],
                    receipt["relative_path"],
                    receipt["artifact_fingerprint"],
                    receipt["byte_count"],
                    created_at,
                ),
            )
        return {"selection": selection, "backup": receipt, "reused": False}

    def list_selections(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_shadow_research_daily_selections
                    ORDER BY market_date DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [_selection_from_row(row) for row in rows]

    def list_backups(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_shadow_research_daily_backups
                    ORDER BY market_date DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [self._backup_projection(row) for row in rows]

    def require_verified_winner(
        self, *, candidate_id: str, run_id: str
    ) -> dict[str, Any]:
        """Require the exact daily winner and its untampered local backup."""

        try:
            with self._connect_readonly() as conn:
                selection_row = conn.execute(
                    "SELECT * FROM ai_shadow_research_daily_selections WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                backup_row = conn.execute(
                    "SELECT * FROM ai_shadow_research_daily_backups WHERE run_id=?",
                    (run_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            raise DailyStrategyArtifactRejected(
                "daily_selection_or_backup_missing"
            ) from exc
        if selection_row is None or backup_row is None:
            raise DailyStrategyArtifactRejected("daily_selection_or_backup_missing")
        selection = _selection_from_row(selection_row)
        if (
            selection.get("integrity_status") != "verified"
            or selection.get("status") != "winner_selected"
            or selection.get("winner_candidate_id") != candidate_id
        ):
            raise DailyStrategyArtifactRejected(
                "candidate_is_not_verified_daily_winner"
            )
        backup = self._backup_projection(backup_row)
        if backup.get("verification_status") != "verified":
            raise DailyStrategyArtifactRejected("daily_strategy_backup_not_verified")
        operating_constraints = self._verified_winner_operating_constraints(
            backup_row,
            candidate_id=candidate_id,
        )
        return {
            "selection": selection,
            "backup": backup,
            "operating_constraints": operating_constraints,
        }

    def load_verified_winner_strategy(
        self,
        *,
        candidate_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Load the exact frozen Formula DSL snapshot selected for promotion."""

        verified = self.require_verified_winner(
            candidate_id=candidate_id,
            run_id=run_id,
        )
        try:
            with self._connect_readonly() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_shadow_research_daily_backups WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            if row is None:
                raise DailyStrategyArtifactRejected("daily_strategy_backup_missing")
            path = (self._backup_root / str(row["relative_path"])).resolve()
            path.relative_to(self._backup_root.resolve())
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise DailyStrategyArtifactRejected(
                "daily_strategy_snapshot_unreadable"
            ) from exc
        if (
            not isinstance(payload, Mapping)
            or content_fingerprint(payload) != row["artifact_fingerprint"]
        ):
            raise DailyStrategyArtifactRejected(
                "daily_strategy_snapshot_backup_mismatch"
            )
        matches = [
            item
            for item in payload.get("candidates") or []
            if isinstance(item, Mapping) and item.get("candidate_id") == candidate_id
        ]
        if len(matches) != 1:
            raise DailyStrategyArtifactRejected(
                "daily_strategy_snapshot_candidate_mismatch"
            )
        snapshot = matches[0]
        strategy = snapshot.get("strategy")
        if (
            not isinstance(strategy, Mapping)
            or snapshot.get("strategy_artifact_fingerprint")
            != content_fingerprint(strategy)
            or not isinstance(strategy.get("formula_ast"), Mapping)
            or not str(strategy.get("formula_fingerprint") or "")
            or not _nonempty_text_list(strategy.get("selected_universe"))
        ):
            raise DailyStrategyArtifactRejected(
                "daily_strategy_snapshot_strategy_mismatch"
            )
        return {
            "schema_version": "karkinos.ai.verified_winner_strategy.v1",
            "candidate_id": candidate_id,
            "run_id": run_id,
            "market_date": verified["selection"].get("market_date"),
            "selection_id": verified["selection"].get("selection_id"),
            "backup_artifact_fingerprint": verified["backup"].get(
                "artifact_fingerprint"
            ),
            "strategy_artifact_fingerprint": snapshot.get(
                "strategy_artifact_fingerprint"
            ),
            "strategy": dict(strategy),
            "operating_constraints": verified["operating_constraints"],
            "provider_contact_performed": False,
            "authorizes_strategy_promotion": False,
            "authorizes_order_creation": False,
            "changes_capital_authority": False,
        }

    def _write_backup(
        self, payload: Mapping[str, Any], *, created_at: str
    ) -> dict[str, Any]:
        market_date = str(payload.get("market_date") or "")
        try:
            date.fromisoformat(market_date)
        except ValueError as exc:
            raise DailyStrategyArtifactRejected("backup_market_date_invalid") from exc
        artifact_fingerprint = content_fingerprint(payload)
        fingerprint_token = artifact_fingerprint.removeprefix("sha256:")
        relative_path = Path(market_date) / f"{fingerprint_token}.json"
        target = self._backup_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        body = (canonical_json(dict(payload)) + "\n").encode("utf-8")
        if target.exists():
            if target.read_bytes() != body:
                raise DailyStrategyArtifactRejected("daily_backup_content_conflict")
        else:
            temp_path: Path | None = None
            try:
                descriptor, temp_name = tempfile.mkstemp(
                    prefix=".daily-strategy-", suffix=".tmp", dir=target.parent
                )
                temp_path = Path(temp_name)
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, target)
            finally:
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink()
        backup_id = (
            "ai-shadow-backup-"
            + content_fingerprint(
                {"run_id": payload.get("run_id"), "artifact": artifact_fingerprint}
            ).removeprefix("sha256:")[:24]
        )
        return {
            "schema_version": DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA,
            "backup_id": backup_id,
            "run_id": payload.get("run_id"),
            "market_date": market_date,
            "selection_id": payload.get("selection", {}).get("selection_id"),
            "relative_path": relative_path.as_posix(),
            "artifact_fingerprint": artifact_fingerprint,
            "byte_count": len(body),
            "created_at": created_at,
            "verification_status": "verified",
            "contains_private_account_identifiers": False,
            "contains_broker_export_rows": False,
        }

    def _backup_projection(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result.update(
            {
                "schema_version": DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA,
                "verification_status": "unverified",
                "contains_private_account_identifiers": False,
                "contains_broker_export_rows": False,
            }
        )
        try:
            candidate = (self._backup_root / str(row["relative_path"])).resolve()
            root = self._backup_root.resolve()
            candidate.relative_to(root)
            if not candidate.is_file():
                result["verification_status"] = "missing"
                return result
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                result["verification_status"] = "invalid_payload"
                return result
            if content_fingerprint(payload) != row["artifact_fingerprint"]:
                result["verification_status"] = "fingerprint_mismatch"
                return result
            if candidate.stat().st_size != int(row["byte_count"]):
                result["verification_status"] = "byte_count_mismatch"
                return result
            selection = payload.get("selection")
            if (
                payload.get("run_id") != row["run_id"]
                or payload.get("market_date") != row["market_date"]
                or not isinstance(selection, Mapping)
                or selection.get("selection_id") != row["selection_id"]
            ):
                result["verification_status"] = "identity_mismatch"
                return result
            result["verification_status"] = "verified"
            return result
        except (OSError, ValueError, json.JSONDecodeError):
            result["verification_status"] = "read_failed"
            return result

    def _verified_winner_operating_constraints(
        self,
        row: sqlite3.Row,
        *,
        candidate_id: str,
    ) -> dict[str, Any]:
        """Read reviewed operating constraints from the exact verified backup."""

        try:
            candidate = (self._backup_root / str(row["relative_path"])).resolve()
            root = self._backup_root.resolve()
            candidate.relative_to(root)
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise DailyStrategyArtifactRejected(
                "daily_strategy_operating_constraints_unreadable"
            ) from exc
        if (
            not isinstance(payload, Mapping)
            or content_fingerprint(payload) != row["artifact_fingerprint"]
        ):
            raise DailyStrategyArtifactRejected(
                "daily_strategy_operating_constraints_backup_mismatch"
            )
        matches = [
            item
            for item in payload.get("candidates") or []
            if isinstance(item, Mapping) and item.get("candidate_id") == candidate_id
        ]
        if len(matches) != 1:
            raise DailyStrategyArtifactRejected(
                "daily_strategy_operating_constraints_candidate_mismatch"
            )
        snapshot = matches[0]
        strategy = snapshot.get("strategy")
        if not isinstance(strategy, Mapping) or snapshot.get(
            "strategy_artifact_fingerprint"
        ) != content_fingerprint(strategy):
            raise DailyStrategyArtifactRejected(
                "daily_strategy_operating_constraints_strategy_mismatch"
            )
        economic_hypothesis = str(strategy.get("economic_hypothesis") or "").strip()
        risk_impact = str(strategy.get("risk_impact") or "").strip()
        failure_conditions = _nonempty_text_list(strategy.get("failure_conditions"))
        limitations = _nonempty_text_list(strategy.get("limitations"))
        anti_lookahead_assumptions = _nonempty_text_list(
            strategy.get("anti_lookahead_assumptions")
        )
        if (
            not economic_hypothesis
            or not risk_impact
            or not failure_conditions
            or not limitations
            or not anti_lookahead_assumptions
        ):
            raise DailyStrategyArtifactRejected(
                "daily_strategy_operating_constraints_incomplete"
            )
        core = {
            "schema_version": DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA,
            "candidate_id": candidate_id,
            "strategy_artifact_fingerprint": str(
                snapshot.get("strategy_artifact_fingerprint") or ""
            ),
            "source_backup_artifact_fingerprint": str(
                row["artifact_fingerprint"] or ""
            ),
            "economic_hypothesis": economic_hypothesis,
            "risk_impact": risk_impact,
            "failure_conditions": failure_conditions,
            "limitations": limitations,
            "anti_lookahead_assumptions": anti_lookahead_assumptions,
            "automatic_enforcement_enabled": False,
            "human_review_required": True,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }
        return {**core, "evidence_fingerprint": content_fingerprint(core)}

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self._db_path.exists():
            raise sqlite3.OperationalError("daily artifact store is not initialized")
        conn = sqlite3.connect(
            f"file:{self._db_path.resolve()}?mode=ro", uri=True, timeout=30
        )
        conn.row_factory = sqlite3.Row
        return conn


def build_daily_strategy_promotion_binding(
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one verified winner/backup pair into promotion-safe evidence."""

    selection = artifacts.get("selection")
    backup = artifacts.get("backup")
    operating_constraints = artifacts.get("operating_constraints")
    if (
        not isinstance(selection, Mapping)
        or not isinstance(backup, Mapping)
        or not isinstance(operating_constraints, Mapping)
    ):
        raise DailyStrategyArtifactRejected("daily_promotion_binding_artifact_missing")
    if (
        selection.get("schema_version") != DAILY_STRATEGY_SELECTION_SCHEMA
        or selection.get("integrity_status") != "verified"
        or selection.get("status") != "winner_selected"
        or backup.get("schema_version") != DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA
        or backup.get("verification_status") != "verified"
    ):
        raise DailyStrategyArtifactRejected("daily_promotion_binding_not_verified")
    identities = {
        "run_id": str(selection.get("run_id") or ""),
        "market_date": str(selection.get("market_date") or ""),
        "winner_candidate_id": str(selection.get("winner_candidate_id") or ""),
        "selection_id": str(selection.get("selection_id") or ""),
        "selection_fingerprint": str(selection.get("selection_fingerprint") or ""),
        "backup_id": str(backup.get("backup_id") or ""),
        "backup_artifact_fingerprint": str(backup.get("artifact_fingerprint") or ""),
    }
    if not all(identities.values()) or (
        backup.get("run_id") != identities["run_id"]
        or backup.get("market_date") != identities["market_date"]
        or backup.get("selection_id") != identities["selection_id"]
        or backup.get("contains_private_account_identifiers") is not False
        or backup.get("contains_broker_export_rows") is not False
    ):
        raise DailyStrategyArtifactRejected("daily_promotion_binding_identity_mismatch")
    constraints_core = {
        key: value
        for key, value in operating_constraints.items()
        if key != "evidence_fingerprint"
    }
    if (
        operating_constraints.get("schema_version")
        != DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA
        or operating_constraints.get("candidate_id")
        != identities["winner_candidate_id"]
        or operating_constraints.get("source_backup_artifact_fingerprint")
        != identities["backup_artifact_fingerprint"]
        or operating_constraints.get("evidence_fingerprint")
        != content_fingerprint(constraints_core)
        or operating_constraints.get("automatic_enforcement_enabled") is not False
        or operating_constraints.get("human_review_required") is not True
        or operating_constraints.get("authorizes_execution") is not False
        or operating_constraints.get("changes_capital_authority") is not False
    ):
        raise DailyStrategyArtifactRejected(
            "daily_promotion_binding_operating_constraints_invalid"
        )
    return {
        "schema_version": DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA,
        **identities,
        "operating_constraints": dict(operating_constraints),
        "contains_private_account_identifiers": False,
        "contains_broker_export_rows": False,
        "does_not_change_capital_authority": True,
        "authority_effect": "research_only",
    }


def build_daily_strategy_selection(
    *,
    run: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    expected_candidate_count: int,
    created_at: str,
) -> dict[str, Any]:
    """Select one new research candidate without deciding today's trade."""

    if expected_candidate_count < 1:
        raise DailyStrategyArtifactRejected("expected_candidate_count_invalid")
    run_id = str(run.get("run_id") or "")
    market_date = str(run.get("market_date") or "")
    if not run_id or not market_date:
        raise DailyStrategyArtifactRejected("daily_selection_run_identity_missing")
    outcomes = [_candidate_outcome(candidate) for candidate in candidates]
    outcomes.sort(key=lambda item: item["candidate_id"])
    blockers: list[str] = []
    ranked: list[dict[str, Any]] = []
    candidate_ids = [item["candidate_id"] for item in outcomes]
    if (
        any(not candidate_id for candidate_id in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
        or any(item["run_id"] != run_id for item in outcomes)
    ):
        blockers.append("candidate_identity_conflict")
    if len(outcomes) != expected_candidate_count:
        blockers.append("configured_candidate_set_incomplete")
    if any(item["status"] not in _COMPLETE_CANDIDATE_STATUSES for item in outcomes):
        blockers.append("candidate_evaluation_incomplete")
    lineage_by_number = {
        item.get("iteration_number"): item
        for item in outcomes
        if isinstance(item.get("iteration_number"), int)
        and not isinstance(item.get("iteration_number"), bool)
    }
    expected_iterations = set(range(1, expected_candidate_count + 1))
    if set(lineage_by_number) != expected_iterations or any(
        item.get("total_iterations") != expected_candidate_count for item in outcomes
    ):
        blockers.append("candidate_iteration_lineage_invalid")
    else:
        for iteration_number in range(1, expected_candidate_count + 1):
            item = lineage_by_number[iteration_number]
            previous = (
                None
                if iteration_number == 1
                else lineage_by_number[iteration_number - 1]
            )
            if (
                not item.get("formula_fingerprint")
                or item.get("parent_candidate_id")
                != (previous["candidate_id"] if previous else None)
                or item.get("parent_draft_id")
                != (previous["draft_id"] if previous else None)
                or item.get("parent_formula_fingerprint")
                != (previous["formula_fingerprint"] if previous else None)
                or not item.get("iteration_context_fingerprint")
                or item.get("sequential_feedback_bound") is not True
            ):
                blockers.append("candidate_iteration_lineage_invalid")
                break
    eligible = [item for item in outcomes if item["ranking_key"] is not None]
    if not eligible:
        blockers.append("no_candidate_passed_advancement_gate")
    if not blockers:
        eligible.sort(key=lambda item: item["ranking_key"])
        ranked = [
            {key: value for key, value in item.items() if key != "ranking_key"}
            | {"rank": ordinal}
            for ordinal, item in enumerate(eligible, start=1)
        ]
    winner_candidate_id = ranked[0]["candidate_id"] if ranked else None
    payload: dict[str, Any] = {
        "schema_version": DAILY_STRATEGY_SELECTION_SCHEMA,
        "selection_id": "",
        "run_id": run_id,
        "market_date": market_date,
        "status": "winner_selected" if winner_candidate_id else "no_selection",
        "winner_candidate_id": winner_candidate_id,
        "expected_candidate_count": expected_candidate_count,
        "observed_candidate_count": len(outcomes),
        "eligible_candidate_count": len(eligible),
        "blockers": sorted(set(blockers)),
        "ranking_method": {
            "type": "hard_gate_then_lexicographic",
            "priority": [
                "after_tax_excess_return_desc",
                "mean_oos_excess_return_desc",
                "worst_oos_excess_return_desc",
                "candidate_max_drawdown_asc",
                "candidate_turnover_to_initial_cash_asc",
                "candidate_id_asc",
            ],
            "weighted_average_used": False,
            "deepseek_selects_winner": False,
            "sequential_iteration_lineage_required": True,
        },
        "ranked_eligible_candidates": ranked,
        "candidate_outcomes": [
            {key: value for key, value in item.items() if key != "ranking_key"}
            for item in outcomes
        ],
        "created_at": created_at,
        "selection_scope": "new_candidate_research_only",
        "incumbent_strategy_policy": "leave_current_human_approved_strategy_unchanged",
        "incumbent_strategy_state_changed": False,
        "daily_trading_decision_status": "not_evaluated",
        "implies_daily_trading_no_action": False,
        "human_paper_shadow_approval_required": True,
        "automatic_strategy_replacement_enabled": False,
        "broker_submission_enabled": False,
        "does_not_change_capital_authority": True,
        "authority_effect": "research_only",
    }
    selection_id = (
        "ai-shadow-selection-"
        + content_fingerprint(
            {
                "run_id": run_id,
                "candidate_outcomes": payload["candidate_outcomes"],
                "ranking_method": payload["ranking_method"],
            }
        ).removeprefix("sha256:")[:24]
    )
    payload["selection_id"] = selection_id
    payload["selection_fingerprint"] = content_fingerprint(payload)
    return payload


def _candidate_outcome(candidate: Mapping[str, Any]) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or "")
    comparison = candidate.get("comparison")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    gate = comparison.get("promotion_gate")
    gate = gate if isinstance(gate, Mapping) else {}
    lineage = comparison.get("iteration_lineage")
    lineage = lineage if isinstance(lineage, Mapping) else {}
    metrics = _ranking_metrics(gate)
    eligible = (
        bool(candidate_id)
        and candidate.get("status") == "awaiting_human_approval"
        and candidate.get("recommendation") == "paper_shadow_review"
        and is_valid_passed_strategy_advancement_gate(gate)
        and metrics is not None
    )
    ranking_key = None
    if eligible and metrics is not None:
        ranking_key = (
            -metrics["after_tax_excess_return"],
            -metrics["mean_oos_excess_return"],
            -metrics["worst_oos_excess_return"],
            metrics["candidate_max_drawdown"],
            metrics["candidate_turnover_to_initial_cash"],
            candidate_id,
        )
    return {
        "candidate_id": candidate_id,
        "run_id": str(candidate.get("run_id") or ""),
        "draft_id": str(candidate.get("draft_id") or ""),
        "status": str(candidate.get("status") or ""),
        "recommendation": str(candidate.get("recommendation") or ""),
        "eligible": eligible,
        "promotion_gate_status": str(gate.get("status") or "missing"),
        "promotion_gate_fingerprint": gate.get("evidence_fingerprint"),
        "comparison_fingerprint": content_fingerprint(comparison),
        "iteration_number": lineage.get("iteration_number"),
        "total_iterations": lineage.get("total_iterations"),
        "formula_fingerprint": lineage.get("formula_fingerprint"),
        "parent_candidate_id": lineage.get("parent_candidate_id"),
        "parent_draft_id": lineage.get("parent_draft_id"),
        "parent_formula_fingerprint": lineage.get("parent_formula_fingerprint"),
        "iteration_context_fingerprint": lineage.get("iteration_context_fingerprint"),
        "sequential_feedback_bound": lineage.get("sequential_feedback_bound"),
        "ranking_metrics": (
            {key: _decimal_text(value) for key, value in metrics.items()}
            if metrics is not None
            else None
        ),
        "ranking_key": ranking_key,
    }


def _ranking_metrics(gate: Mapping[str, Any]) -> dict[str, Decimal] | None:
    checks_raw = gate.get("checks")
    if not isinstance(checks_raw, list):
        return None
    checks = {
        str(check.get("name")): check
        for check in checks_raw
        if isinstance(check, Mapping)
    }
    after_tax = _check_evidence(checks, "after_tax_excess_return")
    oos = _check_evidence(checks, "after_cost_oos_excess")
    drawdown = _check_evidence(checks, "drawdown")
    turnover = _check_evidence(checks, "turnover")
    values = {
        "after_tax_excess_return": _decimal(after_tax.get("after_tax_excess_return")),
        "mean_oos_excess_return": _decimal(oos.get("mean_oos_excess_return")),
        "worst_oos_excess_return": _decimal(oos.get("worst_oos_excess_return")),
        "candidate_max_drawdown": _decimal(drawdown.get("candidate_max_drawdown")),
        "candidate_turnover_to_initial_cash": _decimal(
            turnover.get("candidate_turnover_to_initial_cash")
        ),
    }
    if any(value is None for value in values.values()):
        return None
    return {key: value for key, value in values.items() if value is not None}


def _check_evidence(
    checks: Mapping[str, Mapping[str, Any]], name: str
) -> Mapping[str, Any]:
    check = checks.get(name)
    if not isinstance(check, Mapping) or check.get("status") != "pass":
        return {}
    evidence = check.get("evidence")
    return evidence if isinstance(evidence, Mapping) else {}


def _build_backup_payload(
    *,
    run: Mapping[str, Any],
    run_status: str,
    candidates: Sequence[Mapping[str, Any]],
    drafts: Sequence[Mapping[str, Any]],
    selection: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    drafts_by_id = {str(item.get("draft_id") or ""): item for item in drafts}
    candidate_snapshots: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: str(item.get("candidate_id"))):
        draft_id = str(candidate.get("draft_id") or "")
        draft = drafts_by_id.get(draft_id)
        if not isinstance(draft, Mapping):
            raise DailyStrategyArtifactRejected("strategy_draft_missing_from_backup")
        strategy = {key: draft[key] for key in _DRAFT_BACKUP_FIELDS if key in draft}
        if not isinstance(strategy.get("formula_ast"), Mapping) or not str(
            strategy.get("formula_fingerprint") or ""
        ):
            raise DailyStrategyArtifactRejected("strategy_formula_backup_incomplete")
        comparison = candidate.get("comparison")
        comparison = comparison if isinstance(comparison, Mapping) else {}
        gate = comparison.get("promotion_gate")
        gate = gate if isinstance(gate, Mapping) else {}
        candidate_snapshots.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "draft_id": draft_id,
                "status": candidate.get("status"),
                "recommendation": candidate.get("recommendation"),
                "strategy": strategy,
                "strategy_artifact_fingerprint": content_fingerprint(strategy),
                "comparison_fingerprint": content_fingerprint(comparison),
                "promotion_gate_status": gate.get("status"),
                "promotion_gate_fingerprint": gate.get("evidence_fingerprint"),
                "promotion_blockers": list(gate.get("blockers") or []),
            }
        )
    return {
        "schema_version": DAILY_STRATEGY_BACKUP_SCHEMA,
        "run_id": run.get("run_id"),
        "market_date": run.get("market_date"),
        "run_status": run_status,
        "run_input_fingerprint": run.get("input_fingerprint"),
        "selection": dict(selection),
        "candidates": candidate_snapshots,
        "created_at": created_at,
        "contains_private_account_identifiers": False,
        "contains_broker_export_rows": False,
        "contains_provider_credentials": False,
        "automatic_strategy_replacement_enabled": False,
        "broker_submission_enabled": False,
        "authority_effect": "research_only",
    }


def _selection_from_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(str(row["selection_json"]))
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    expected = payload.pop("selection_fingerprint", None)
    valid = (
        expected == row["selection_fingerprint"]
        and content_fingerprint(payload) == row["selection_fingerprint"]
    )
    payload["selection_fingerprint"] = expected
    payload["integrity_status"] = "verified" if valid else "fingerprint_mismatch"
    return payload


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _nonempty_text_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    normalized = [str(item).strip() for item in value if str(item).strip()]
    if len(normalized) != len(value):
        return []
    return normalized
