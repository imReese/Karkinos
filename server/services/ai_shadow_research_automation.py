"""After-close, evidence-bound AI strategy research automation.

The service may spend an explicitly authorized provider budget on research.
It never registers a production strategy, creates a trading plan, or contacts a
broker.  Candidate promotion is a separate human-only paper/shadow record.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd

from analytics.backtest_capacity_evidence import build_backtest_capacity_evidence
from analytics.backtest_fee_tax_evidence import build_backtest_fee_tax_evidence
from analytics.backtest_market_regime_evidence import (
    build_backtest_market_regime_evidence,
)
from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from analytics.oos_validation import build_rolling_out_of_sample_validation
from analytics.strategy_advancement_gate import (
    build_strategy_advancement_gate,
    is_valid_passed_strategy_advancement_gate,
)
from backtest.engine import BacktestEngine
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.manager import DataManager
from data.store import DataStore
from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.strategy_research import (
    BACKTEST_CONFIRMATION,
    CRITIQUE_EXPORT_CONFIRMATION,
    HYPOTHESIS_EXPORT_CONFIRMATION,
    STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION,
    CritiqueRequest,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
    StrategyResearchSelection,
    _rolling_oos_parameters,
)
from server.bootstrap import build_strategy
from server.config import BacktestConfig
from server.models import BacktestRequest
from server.routes.backtest import (
    _backtest_report_metrics_json,
    _fill_to_response,
)
from server.services.reviewed_fee_schedule import (
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
)
from server.services.valuation_snapshot import build_current_valuation_snapshot

logger = logging.getLogger(__name__)

SHADOW_RESEARCH_POLICY_ID = "ai_shadow_research"
SHADOW_RESEARCH_POLICY_SCHEMA = "karkinos.ai.shadow_research_policy.v1"
SHADOW_RESEARCH_API_SCHEMA = "karkinos.ai.shadow_research_automation.v1"
SHADOW_RESEARCH_RUN_TYPE = "ai_shadow_research"
SHADOW_RESEARCH_POLICY_CONFIRMATION = "authorize_after_close_deepseek_strategy_research_without_strategy_or_trade_authority"
SHADOW_RESEARCH_PAUSE_CONFIRMATION = (
    "pause_after_close_ai_strategy_research_without_changing_trading_authority"
)
SHADOW_RESEARCH_PROMOTION_CONFIRMATION = "approve_evidence_bound_candidate_for_paper_shadow_only_without_production_or_trade_authority"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION = (
    STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION
)


class ShadowResearchRejected(ValueError):
    """Fail-closed shadow research policy or evidence rejection."""


@dataclass(frozen=True)
class ShadowResearchPolicy:
    enabled: bool = False
    after_close_time: str = "15:30"
    max_provider_calls_per_market_date: int = 3
    daily_token_budget: int = 700_000
    max_candidates_per_run: int = 2
    baseline_backtest_result_id: int | None = None
    require_complete_account_evidence: bool = True
    research_question: str = (
        "基于冻结的最新持久化行情、账户证据与基线回测，提出可证伪、低换手、"
        "包含明确风险退出条件的 Formula DSL 策略改进假设。"
    )
    updated_by: str = "human:owner"
    authorization: str = ""

    def __post_init__(self) -> None:
        try:
            parsed = time.fromisoformat(self.after_close_time)
        except ValueError as exc:
            raise ShadowResearchRejected("after_close_time_invalid") from exc
        if parsed.second or parsed.microsecond:
            raise ShadowResearchRejected("after_close_time_must_be_minute_precision")
        if not 1 <= self.max_provider_calls_per_market_date <= 4:
            raise ShadowResearchRejected("provider_call_limit_out_of_range")
        if not (
            SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION
            <= self.daily_token_budget
            <= 1_000_000
        ):
            raise ShadowResearchRejected("daily_token_budget_out_of_range")
        if not 1 <= self.max_candidates_per_run <= 3:
            raise ShadowResearchRejected("candidate_limit_out_of_range")
        if self.max_provider_calls_per_market_date < self.max_candidates_per_run + 1:
            raise ShadowResearchRejected(
                "provider_call_limit_cannot_cover_candidate_critiques"
            )
        if self.daily_token_budget < SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * (
            self.max_candidates_per_run + 1
        ):
            raise ShadowResearchRejected(
                "daily_token_budget_cannot_cover_reserved_calls"
            )
        if (
            self.baseline_backtest_result_id is not None
            and self.baseline_backtest_result_id <= 0
        ):
            raise ShadowResearchRejected("baseline_backtest_result_id_invalid")
        if not self.research_question.strip():
            raise ShadowResearchRejected("research_question_required")
        if not self.updated_by.strip():
            raise ShadowResearchRejected("updated_by_required")
        if self.enabled and self.authorization != SHADOW_RESEARCH_POLICY_CONFIRMATION:
            raise PermissionError(
                "standing shadow research requires exact owner authorization"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SHADOW_RESEARCH_POLICY_SCHEMA,
            "policy_id": SHADOW_RESEARCH_POLICY_ID,
            "enabled": self.enabled,
            "after_close_time": self.after_close_time,
            "timezone": "Asia/Shanghai",
            "max_provider_calls_per_market_date": self.max_provider_calls_per_market_date,
            "daily_token_budget": self.daily_token_budget,
            "max_candidates_per_run": self.max_candidates_per_run,
            "baseline_backtest_result_id": self.baseline_backtest_result_id,
            "require_complete_account_evidence": self.require_complete_account_evidence,
            "research_question": self.research_question,
            "updated_by": self.updated_by,
            "authorization_recorded": self.enabled,
            "authorization": self.authorization if self.enabled else "",
            "automatic_strategy_replacement_enabled": False,
            "broker_submission_enabled": False,
            "production_strategy_mutation_enabled": False,
            "human_paper_shadow_approval_required": True,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ShadowResearchPolicy":
        value = dict(raw or {})
        return cls(
            enabled=bool(value.get("enabled", False)),
            after_close_time=str(value.get("after_close_time") or "15:30"),
            max_provider_calls_per_market_date=int(
                value.get("max_provider_calls_per_market_date") or 3
            ),
            daily_token_budget=int(value.get("daily_token_budget") or 700_000),
            max_candidates_per_run=int(value.get("max_candidates_per_run") or 2),
            baseline_backtest_result_id=(
                int(value["baseline_backtest_result_id"])
                if value.get("baseline_backtest_result_id") is not None
                else None
            ),
            require_complete_account_evidence=bool(
                value.get("require_complete_account_evidence", True)
            ),
            research_question=str(
                value.get("research_question") or cls.research_question
            ),
            updated_by=str(value.get("updated_by") or "human:owner"),
            authorization=str(value.get("authorization") or ""),
        )


class ShadowResearchStore:
    """Atomic run, provider budget, candidate, and promotion audit storage."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ai_shadow_research_runs (
                    run_id TEXT PRIMARY KEY,
                    market_date TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    baseline_seed_result_id INTEGER NOT NULL,
                    baseline_result_id INTEGER,
                    valuation_snapshot_id TEXT NOT NULL,
                    ledger_cutoff_id INTEGER NOT NULL,
                    session_id TEXT,
                    failure_code TEXT,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_baselines (
                    baseline_fingerprint TEXT PRIMARY KEY,
                    backtest_result_id INTEGER NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_provider_calls (
                    call_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    market_date TEXT NOT NULL,
                    call_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reserved_tokens INTEGER NOT NULL,
                    actual_tokens INTEGER,
                    failure_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    backtest_run_id TEXT,
                    critique_id TEXT,
                    baseline_result_id INTEGER NOT NULL,
                    candidate_result_id INTEGER,
                    status TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    comparison_json TEXT NOT NULL,
                    promotion_status TEXT NOT NULL DEFAULT 'awaiting_human_approval',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(run_id, draft_id)
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_promotions (
                    promotion_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    target_stage TEXT NOT NULL CHECK(target_stage = 'paper_shadow'),
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    candidate_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_runs_market_date
                    ON ai_shadow_research_runs(market_date DESC, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_shadow_one_run_per_market_date
                    ON ai_shadow_research_runs(market_date);
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_candidates_created
                    ON ai_shadow_research_candidates(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_calls_market_date
                    ON ai_shadow_research_provider_calls(market_date, created_at);
            """)

    def claim_run(
        self,
        *,
        market_date: str,
        input_fingerprint: str,
        baseline_seed_result_id: int,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        run_id = f"ai-shadow-research:{market_date}:{input_fingerprint[:16]}"
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_runs
                WHERE input_fingerprint=? OR market_date=?
                ORDER BY created_at LIMIT 1
                """,
                (input_fingerprint, market_date),
            ).fetchone()
            if existing is not None:
                return dict(existing), True
            conn.execute(
                """
                INSERT INTO ai_shadow_research_runs
                (run_id, market_date, input_fingerprint, status,
                 baseline_seed_result_id, valuation_snapshot_id, ledger_cutoff_id,
                 created_at, updated_at)
                VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    market_date,
                    input_fingerprint,
                    baseline_seed_result_id,
                    valuation_snapshot_id,
                    ledger_cutoff_id,
                    now,
                    now,
                ),
            )
        return self.get_run(run_id), False

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"shadow research run not found: {run_id}")
        return dict(row)

    def update_run(self, run_id: str, *, now: str, **updates: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "baseline_result_id",
            "session_id",
            "failure_code",
            "candidate_count",
        }
        values = {key: value for key, value in updates.items() if key in allowed}
        if not values:
            return self.get_run(run_id)
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._connect(immediate=True) as conn:
            conn.execute(
                f"UPDATE ai_shadow_research_runs SET {assignments}, updated_at=? WHERE run_id=?",
                (*values.values(), now, run_id),
            )
        return self.get_run(run_id)

    def save_baseline(
        self,
        *,
        baseline_fingerprint: str,
        request: BacktestRequest,
        result: Mapping[str, Any],
        now: str,
    ) -> int:
        """Persist a computed baseline exactly once with its canonical result row."""
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT backtest_result_id FROM ai_shadow_research_baselines WHERE baseline_fingerprint=?",
                (baseline_fingerprint,),
            ).fetchone()
            if existing is not None:
                return int(existing["backtest_result_id"])
            cursor = conn.execute(
                """
                INSERT INTO backtest_results
                (created_at, config_json, initial_cash, final_equity, total_return,
                 sharpe, sortino, max_drawdown, win_rate, duration_days,
                 equity_curve_json, metrics_json, cost_summary_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    request.model_dump_json(),
                    result["initial_cash"],
                    result["final_equity"],
                    result["total_return"],
                    result["sharpe"],
                    result["sortino"],
                    result["max_drawdown"],
                    result["win_rate"],
                    result["duration_days"],
                    json.dumps(result["equity_curve"], ensure_ascii=False),
                    json.dumps(result["metrics_json"], ensure_ascii=False),
                    json.dumps(result["cost_summary_json"], ensure_ascii=False),
                ),
            )
            result_id = int(cursor.lastrowid or 0)
            conn.execute(
                "INSERT INTO ai_shadow_research_baselines VALUES (?, ?, ?)",
                (baseline_fingerprint, result_id, now),
            )
            return result_id

    def claim_provider_call(
        self,
        *,
        call_id: str,
        run_id: str,
        market_date: str,
        call_kind: str,
        call_limit: int,
        token_budget: int,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_shadow_research_provider_calls WHERE call_id=?",
                (call_id,),
            ).fetchone()
            if existing is not None:
                return dict(existing), True
            totals = conn.execute(
                """
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(
                           CASE
                               WHEN actual_tokens > reserved_tokens THEN actual_tokens
                               ELSE reserved_tokens
                           END
                       ), 0) AS tokens
                FROM ai_shadow_research_provider_calls WHERE market_date=?
                """,
                (market_date,),
            ).fetchone()
            if int(totals["calls"]) >= call_limit:
                raise ShadowResearchRejected("daily_provider_call_limit_reached")
            if (
                int(totals["tokens"]) + SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION
                > token_budget
            ):
                raise ShadowResearchRejected("daily_provider_token_budget_reached")
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

    def save_candidate(
        self,
        *,
        run_id: str,
        session_id: str,
        draft_id: str,
        backtest_run_id: str | None,
        critique_id: str | None,
        baseline_result_id: int,
        candidate_result_id: int | None,
        status: str,
        recommendation: str,
        comparison: Mapping[str, Any],
        now: str,
    ) -> dict[str, Any]:
        candidate_id = (
            "ai-shadow-candidate-"
            + content_fingerprint({"run_id": run_id, "draft_id": draft_id})[:24]
        )
        promotion_status = (
            "awaiting_human_approval"
            if status == "awaiting_human_approval"
            else "blocked_by_evidence"
        )
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO ai_shadow_research_candidates
                (candidate_id, run_id, session_id, draft_id, backtest_run_id,
                 critique_id, baseline_result_id, candidate_result_id, status,
                 recommendation, comparison_json, promotion_status, created_at,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, draft_id) DO UPDATE SET
                    backtest_run_id=excluded.backtest_run_id,
                    critique_id=excluded.critique_id,
                    candidate_result_id=excluded.candidate_result_id,
                    status=excluded.status,
                    recommendation=excluded.recommendation,
                    comparison_json=excluded.comparison_json,
                    promotion_status=CASE
                        WHEN ai_shadow_research_candidates.promotion_status IN
                             ('paper_shadow_approval_recorded', 'paper_shadow_approved')
                        THEN ai_shadow_research_candidates.promotion_status
                        ELSE excluded.promotion_status
                    END,
                    updated_at=excluded.updated_at
                """,
                (
                    candidate_id,
                    run_id,
                    session_id,
                    draft_id,
                    backtest_run_id,
                    critique_id,
                    baseline_result_id,
                    candidate_result_id,
                    status,
                    recommendation,
                    canonical_json(dict(comparison)),
                    promotion_status,
                    now,
                    now,
                ),
            )
        return self.get_candidate(candidate_id)

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_shadow_research_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"shadow research candidate not found: {candidate_id}")
        return _candidate_row(row)

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        if confirmation != SHADOW_RESEARCH_PROMOTION_CONFIRMATION:
            raise PermissionError(
                "paper/shadow approval requires exact human confirmation"
            )
        if not approved_by.strip() or not notes.strip():
            raise ShadowResearchRejected("approver_and_notes_required")
        candidate = self.get_candidate(candidate_id)
        comparison = candidate["comparison"]
        promotion_gate = comparison.get("promotion_gate")
        if (
            candidate["status"] != "awaiting_human_approval"
            or candidate["recommendation"] != "paper_shadow_review"
            or not is_valid_passed_strategy_advancement_gate(promotion_gate)
        ):
            raise ShadowResearchRejected("candidate_not_eligible_for_paper_shadow")
        candidate_fingerprint = content_fingerprint(
            {
                "candidate_id": candidate_id,
                "comparison": comparison,
                "candidate_result_id": candidate.get("candidate_result_id"),
                "critique_id": candidate.get("critique_id"),
            }
        )
        promotion_id = (
            "ai-shadow-promotion-"
            + content_fingerprint(
                {
                    "candidate_id": candidate_id,
                    "candidate_fingerprint": candidate_fingerprint,
                }
            )[:24]
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_shadow_research_promotions WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO ai_shadow_research_promotions
                    VALUES (?, ?, 'paper_shadow', ?, ?, ?, ?)
                    """,
                    (
                        promotion_id,
                        candidate_id,
                        approved_by.strip(),
                        notes.strip(),
                        candidate_fingerprint,
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE ai_shadow_research_candidates
                    SET promotion_status='paper_shadow_approval_recorded', updated_at=?
                    WHERE candidate_id=?
                    """,
                    (now, candidate_id),
                )
            else:
                promotion_id = str(existing["promotion_id"])
                approved_by = str(existing["approved_by"])
                notes = str(existing["notes"])
                now = str(existing["created_at"])
        return {
            "schema_version": SHADOW_RESEARCH_API_SCHEMA,
            "promotion_id": promotion_id,
            "candidate_id": candidate_id,
            "target_stage": "paper_shadow",
            "approved_by": approved_by.strip(),
            "notes": notes.strip(),
            "created_at": now,
            "production_strategy_replaced": False,
            "strategy_registry_mutated": False,
            "broker_order_created": False,
            "manual_confirmation_recorded": True,
            "authority_effect": "paper_shadow_research_only",
        }

    def finalize_candidate_paper_shadow_stage(
        self,
        candidate_id: str,
        *,
        strategy_promotion: Mapping[str, Any],
        now: str,
    ) -> dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if candidate["promotion_status"] not in {
            "paper_shadow_approval_recorded",
            "paper_shadow_approved",
        }:
            raise ShadowResearchRejected("paper_shadow_approval_not_recorded")
        if (
            strategy_promotion.get("stage") != "paper_shadow"
            or bool(strategy_promotion.get("live_like_enabled"))
            or int(strategy_promotion.get("backtest_result_id") or 0)
            != int(candidate.get("candidate_result_id") or 0)
        ):
            raise ShadowResearchRejected("canonical_paper_shadow_stage_invalid")
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE ai_shadow_research_candidates
                SET promotion_status='paper_shadow_approved', updated_at=?
                WHERE candidate_id=?
                """,
                (now, candidate_id),
            )
        return self.get_candidate(candidate_id)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_shadow_research_runs ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]

    def list_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_shadow_research_candidates
                    ORDER BY created_at DESC, candidate_id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [_candidate_row(row) for row in rows]

    def usage_for_market_date(self, market_date: str | None) -> dict[str, Any]:
        if not market_date:
            return {
                "market_date": None,
                "provider_calls": 0,
                "reserved_tokens": 0,
                "actual_tokens": 0,
            }
        try:
            with self._connect_readonly() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS calls,
                           COALESCE(SUM(reserved_tokens), 0) AS reserved,
                           COALESCE(SUM(actual_tokens), 0) AS actual
                    FROM ai_shadow_research_provider_calls WHERE market_date=?
                    """,
                    (market_date,),
                ).fetchone()
        except sqlite3.OperationalError:
            return {
                "market_date": market_date,
                "provider_calls": 0,
                "reserved_tokens": 0,
                "actual_tokens": 0,
            }
        return {
            "market_date": market_date,
            "provider_calls": int(row["calls"]),
            "reserved_tokens": int(row["reserved"]),
            "actual_tokens": int(row["actual"]),
        }

    def _connect(self, *, immediate: bool = False) -> _CommitConnection:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        return _CommitConnection(conn)

    def _connect_readonly(self) -> _CommitConnection:
        if not self._path.exists():
            raise sqlite3.OperationalError("shadow research store is not initialized")
        conn = sqlite3.connect(
            f"file:{self._path.resolve()}?mode=ro", uri=True, timeout=30
        )
        conn.row_factory = sqlite3.Row
        return _CommitConnection(conn)


class _CommitConnection:
    """Small context wrapper that commits or rolls back sqlite transactions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()


@dataclass(frozen=True)
class PreparedBaseline:
    seed_result_id: int
    market_date: str
    snapshot: dict[str, Any]
    request: BacktestRequest
    result: dict[str, Any]
    cost_model_reference: str
    fee_schedule_evidence: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(
            {
                "seed_result_id": self.seed_result_id,
                "config": self.request.model_dump(mode="json"),
                "dataset_snapshot_id": self.snapshot["snapshot_id"],
                "metrics": self.result["metrics_json"],
                "cost_summary": self.result["cost_summary_json"],
                "cost_model_reference": self.cost_model_reference,
                "fee_schedule_evidence": self.fee_schedule_evidence,
            }
        )


class AiShadowResearchAutomationService:
    """Run one complete after-close research cycle under a persisted policy."""

    def __init__(
        self,
        *,
        state: Any,
        store: ShadowResearchStore,
        data_store: DataStore,
        research_service_builder: Callable[[bool], Any] | None = None,
        reviewed_fee_schedule_resolver: Callable[..., Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._state = state
        self._db = state.db
        self._store = store
        self._data_store = data_store
        self._research_service_builder = research_service_builder
        self._reviewed_fee_schedule_resolver = reviewed_fee_schedule_resolver
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get_policy(self) -> ShadowResearchPolicy:
        stored = self._db.get_automation_policy_sync(SHADOW_RESEARCH_POLICY_ID)
        return ShadowResearchPolicy.from_mapping(stored)

    def update_policy(self, patch: Mapping[str, Any]) -> dict[str, Any]:
        current = self.get_policy().to_dict()
        merged = {**current, **dict(patch)}
        enabled = bool(merged.get("enabled", False))
        confirmation = str(merged.pop("confirmation", "") or "")
        if enabled:
            if confirmation != SHADOW_RESEARCH_POLICY_CONFIRMATION:
                raise PermissionError(
                    "standing shadow research requires exact owner authorization"
                )
            merged["authorization"] = SHADOW_RESEARCH_POLICY_CONFIRMATION
        else:
            if confirmation != SHADOW_RESEARCH_PAUSE_CONFIRMATION:
                raise PermissionError(
                    "pausing shadow research requires exact confirmation"
                )
            merged["authorization"] = ""
        policy = ShadowResearchPolicy.from_mapping(merged)
        saved = self._db.upsert_automation_policy_sync(
            policy_id=SHADOW_RESEARCH_POLICY_ID,
            payload=policy.to_dict(),
            updated_by=policy.updated_by,
        )
        return {
            **policy.to_dict(),
            "created_at": saved.get("created_at"),
            "updated_at": saved.get("updated_at"),
        }

    def status(self) -> dict[str, Any]:
        policy = self.get_policy()
        runs = self._store.list_runs(limit=20)
        candidates = self._store.list_candidates(limit=50)
        latest_market_date = runs[0]["market_date"] if runs else None
        kill_switch = self._kill_switch()
        return {
            "schema_version": SHADOW_RESEARCH_API_SCHEMA,
            "policy": policy.to_dict(),
            "kill_switch": kill_switch,
            "usage": self._store.usage_for_market_date(latest_market_date),
            "runs": runs,
            "candidates": candidates,
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "human_paper_shadow_approval_required": True,
            "authority_effect": "research_only",
        }

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        approval = self._store.approve_candidate(
            candidate_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )
        candidate = self._store.get_candidate(candidate_id)
        candidate_result_id = int(candidate.get("candidate_result_id") or 0)
        if not candidate_result_id:
            raise ShadowResearchRejected("candidate_backtest_result_missing")
        strategy_id = f"ai_formula_shadow:{candidate_id}"
        readiness = {
            "schema_version": "karkinos.ai.shadow_research_promotion_readiness.v1",
            "strategy_id": strategy_id,
            "promotion_status": "promotable_for_paper_review",
            "is_promotable": True,
            "missing_requirements": [],
            "backtest_result_id": candidate_result_id,
            "candidate_id": candidate_id,
            "critique_id": candidate.get("critique_id"),
            "comparison_fingerprint": content_fingerprint(candidate["comparison"]),
            "human_approval_id": approval["promotion_id"],
            "strategy_advancement_gate": candidate["comparison"]["promotion_gate"],
            "live_like_enabled": False,
            "broker_submission_enabled": False,
        }
        from server.services.strategy_promotion_pipeline import (
            STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
            StrategyPromotionPipeline,
        )

        pipeline = StrategyPromotionPipeline(db=self._db)
        current = self._db.get_strategy_promotion_state_sync(strategy_id)
        if current is not None and str(current.get("stage")) == "paper_shadow":
            if (
                bool(current.get("live_like_enabled"))
                or int(current.get("backtest_result_id") or 0) != candidate_result_id
            ):
                raise ShadowResearchRejected("canonical_paper_shadow_stage_conflict")
            promotion_state = next(
                item
                for item in pipeline.list_states()
                if item["strategy_id"] == strategy_id
            )
        else:
            pipeline.evaluate_readiness(readiness, actor=approved_by.strip())
            promotion_state = pipeline.request_promotion(
                strategy_id,
                target_stage="paper_shadow",
                readiness=readiness,
                actor=approved_by.strip(),
                confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
                review_note=notes.strip(),
            )
        self._store.finalize_candidate_paper_shadow_stage(
            candidate_id,
            strategy_promotion=promotion_state,
            now=self._utc_now(),
        )
        return {
            **approval,
            "strategy_id": strategy_id,
            "strategy_promotion": promotion_state,
            "paper_shadow_stage_recorded": True,
            "production_strategy_replaced": False,
            "strategy_registry_mutated": False,
            "broker_order_created": False,
        }

    async def run_once(self) -> dict[str, Any]:
        policy = self.get_policy()
        if not policy.enabled:
            return {**self.status(), "run_status": "disabled"}
        kill_switch = self._kill_switch()
        if kill_switch["enabled"]:
            return self._record_preflight(
                status="blocked_by_kill_switch",
                failure_code="kill_switch_enabled",
            )

        try:
            prepared = await asyncio.to_thread(self._prepare_baseline, policy)
        except asyncio.CancelledError:
            raise
        except (ReviewedFeeScheduleRejected, ReviewedFeeScheduleReadRejected) as exc:
            return self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code=exc.code,
            )
        except Exception as exc:
            return self._record_preflight(
                status="blocked_by_market_evidence",
                failure_code=_failure_code(exc),
            )
        now_dt = self._now().astimezone(_SHANGHAI_TZ)
        if not _after_close(prepared.market_date, now_dt, policy.after_close_time):
            return {
                **self.status(),
                "run_status": "waiting_for_market_close",
                "market_date": prepared.market_date,
            }

        try:
            valuation = await asyncio.to_thread(
                build_current_valuation_snapshot, self._db, persist=True
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code=_failure_code(exc),
                market_date=prepared.market_date,
            )
        if (
            policy.require_complete_account_evidence
            and valuation.get("status") != "complete"
        ):
            return self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code="valuation_snapshot_not_complete",
                market_date=prepared.market_date,
            )
        if str(valuation.get("trade_date")) != prepared.market_date:
            return self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code="valuation_market_date_mismatch",
                market_date=prepared.market_date,
            )

        input_fingerprint = content_fingerprint(
            {
                "policy": policy.to_dict(),
                "baseline_fingerprint": prepared.fingerprint,
                "valuation_snapshot_id": valuation["snapshot_id"],
                "ledger_cutoff_id": valuation["ledger_cutoff_id"],
            }
        )
        now_text = self._now().astimezone(timezone.utc).isoformat()
        run, reused = self._store.claim_run(
            market_date=prepared.market_date,
            input_fingerprint=input_fingerprint,
            baseline_seed_result_id=prepared.seed_result_id,
            valuation_snapshot_id=str(valuation["snapshot_id"]),
            ledger_cutoff_id=int(valuation["ledger_cutoff_id"]),
            now=now_text,
        )
        if reused:
            return {
                **self.status(),
                "run_status": run["status"],
                "run_id": run["run_id"],
                "reused": True,
            }

        try:
            baseline_result_id = int(run.get("baseline_result_id") or 0)
            if not baseline_result_id:
                baseline_result_id = self._store.save_baseline(
                    baseline_fingerprint=prepared.fingerprint,
                    request=prepared.request,
                    result=prepared.result,
                    now=now_text,
                )
                run = self._store.update_run(
                    run["run_id"], now=now_text, baseline_result_id=baseline_result_id
                )

            selection = StrategyResearchSelection(
                saved_backtest_result_id=baseline_result_id,
                universe=tuple(
                    asset["symbol"] for asset in prepared.request.assets or []
                ),
                asset_classes=tuple(
                    asset["asset_class"] for asset in prepared.request.assets or []
                ),
                dataset_snapshot_id=str(prepared.snapshot["snapshot_id"]),
                start_date=prepared.request.start_date,
                end_date=prepared.request.end_date,
                frequency=BarFrequency.DAILY.value,
                initial_cash=prepared.request.initial_cash,
                cost_model_reference=prepared.cost_model_reference,
                valuation_snapshot_id=str(valuation["snapshot_id"]),
                ledger_cutoff_id=int(valuation["ledger_cutoff_id"]),
            )
            self._require_deepseek_provider()
            research = self._build_research_service(external=True)
            self._require_runtime_authorization(policy)
            hypothesis_call_id = f"{run['run_id']}:hypothesis"
            _, call_reused = self._store.claim_provider_call(
                call_id=hypothesis_call_id,
                run_id=run["run_id"],
                market_date=prepared.market_date,
                call_kind="hypothesis",
                call_limit=policy.max_provider_calls_per_market_date,
                token_budget=policy.daily_token_budget,
                now=now_text,
            )
            if call_reused:
                raise ShadowResearchRejected("hypothesis_provider_call_already_claimed")
            try:
                hypotheses = await research.generate_hypotheses(
                    HypothesisGenerationRequest(
                        idempotency_key=f"{run['run_id']}:hypothesis",
                        requested_by=f"automation:{policy.updated_by}",
                        account_alias="standing-owner-authorized-shadow-research",
                        research_question=policy.research_question,
                        selection=selection,
                        confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
                    )
                )
            except asyncio.CancelledError:
                self._fail_provider_call(
                    hypothesis_call_id, "provider_call_cancelled_uncertain"
                )
                raise
            except Exception as exc:
                self._fail_provider_call(hypothesis_call_id, _failure_code(exc))
                raise
            self._store.finish_provider_call(
                hypothesis_call_id,
                status=str(hypotheses.get("status") or "failed"),
                actual_tokens=_hypothesis_usage(hypotheses),
                failure_code=hypotheses.get("failure_code"),
                now=self._utc_now(),
            )
            if hypotheses.get("status") != "completed":
                raise ShadowResearchRejected("hypothesis_generation_not_complete")
            self._store.update_run(
                run["run_id"], now=self._utc_now(), session_id=hypotheses["session_id"]
            )

            candidates: list[dict[str, Any]] = []
            valid_drafts = [
                draft
                for draft in hypotheses.get("drafts", [])
                if draft.get("validation", {}).get("status") == "valid"
            ][: policy.max_candidates_per_run]
            if not valid_drafts:
                raise ShadowResearchRejected("no_locally_validated_hypothesis")
            local_research = self._build_research_service(external=False)
            for draft in valid_drafts:
                candidates.append(
                    await self._run_candidate(
                        run=run,
                        policy=policy,
                        hypotheses=hypotheses,
                        draft=draft,
                        baseline_result_id=baseline_result_id,
                        local_research=local_research,
                        external_research=research,
                    )
                )
            terminal_status = (
                "completed"
                if candidates
                and all(
                    item["status"] in {"awaiting_human_approval", "research_blocked"}
                    for item in candidates
                )
                else "partial"
            )
            self._store.update_run(
                run["run_id"],
                now=self._utc_now(),
                status=terminal_status,
                candidate_count=len(candidates),
                failure_code=(
                    None
                    if terminal_status == "completed"
                    else "candidate_stage_partial"
                ),
            )
            await self._notify(prepared.market_date, candidates)
            return {
                **self.status(),
                "run_status": terminal_status,
                "run_id": run["run_id"],
                "reused": call_reused,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "After-close AI shadow research failed closed", exc_info=True
            )
            self._store.update_run(
                run["run_id"],
                now=self._utc_now(),
                status="failed",
                failure_code=_failure_code(exc),
            )
            return {
                **self.status(),
                "run_status": "failed",
                "run_id": run["run_id"],
                "failure_code": _failure_code(exc),
            }

    async def _run_candidate(
        self,
        *,
        run: Mapping[str, Any],
        policy: ShadowResearchPolicy,
        hypotheses: Mapping[str, Any],
        draft: Mapping[str, Any],
        baseline_result_id: int,
        local_research: Any,
        external_research: Any,
    ) -> dict[str, Any]:
        draft_id = str(draft["draft_id"])
        backtest_run_id: str | None = None
        candidate_result_id: int | None = None
        critique_id: str | None = None
        try:
            self._require_runtime_authorization(policy)
            backtest = await local_research.run_formula_backtest(
                FormulaBacktestRequest(
                    idempotency_key=f"{run['run_id']}:backtest:{draft_id}",
                    requested_by=f"automation:{policy.updated_by}",
                    session_id=str(hypotheses["session_id"]),
                    draft_id=draft_id,
                    confirmation=BACKTEST_CONFIRMATION,
                )
            )
            if backtest.get("status") != "completed" or not backtest.get(
                "canonical_backtest"
            ):
                raise ShadowResearchRejected("formula_backtest_not_complete")
            backtest_run_id = str(backtest["backtest_run_id"])
            candidate_result_id = int(backtest["canonical_backtest"]["result_id"])
            self._require_runtime_authorization(policy)
            call_id = f"{run['run_id']}:critique:{draft_id}"
            _, call_reused = self._store.claim_provider_call(
                call_id=call_id,
                run_id=str(run["run_id"]),
                market_date=str(run["market_date"]),
                call_kind="critique",
                call_limit=policy.max_provider_calls_per_market_date,
                token_budget=policy.daily_token_budget,
                now=self._utc_now(),
            )
            if call_reused:
                raise ShadowResearchRejected("critique_provider_call_already_claimed")
            try:
                critique = await external_research.critique(
                    CritiqueRequest(
                        idempotency_key=f"{run['run_id']}:critique:{draft_id}",
                        requested_by=f"automation:{policy.updated_by}",
                        session_id=str(hypotheses["session_id"]),
                        draft_id=draft_id,
                        backtest_run_id=backtest_run_id,
                        confirmation=CRITIQUE_EXPORT_CONFIRMATION,
                    )
                )
            except asyncio.CancelledError:
                self._fail_provider_call(call_id, "provider_call_cancelled_uncertain")
                raise
            except Exception as exc:
                self._fail_provider_call(call_id, _failure_code(exc))
                raise
            self._store.finish_provider_call(
                call_id,
                status=str(critique.get("status") or "failed"),
                actual_tokens=_critique_usage(critique),
                failure_code=critique.get("failure_code"),
                now=self._utc_now(),
            )
            if critique.get("status") != "completed":
                raise ShadowResearchRejected("strategy_critique_not_complete")
            critique_id = str(critique["critique_id"])
            comparison = await self._build_comparison(
                baseline_result_id=baseline_result_id,
                candidate_result_id=candidate_result_id,
                draft=draft,
                critique=critique,
            )
            recommendation = str(comparison["recommendation"])
            return self._store.save_candidate(
                run_id=str(run["run_id"]),
                session_id=str(hypotheses["session_id"]),
                draft_id=draft_id,
                backtest_run_id=backtest_run_id,
                critique_id=critique_id,
                baseline_result_id=baseline_result_id,
                candidate_result_id=candidate_result_id,
                status=(
                    "awaiting_human_approval"
                    if recommendation == "paper_shadow_review"
                    else "research_blocked"
                ),
                recommendation=recommendation,
                comparison=comparison,
                now=self._utc_now(),
            )
        except Exception as exc:
            return self._store.save_candidate(
                run_id=str(run["run_id"]),
                session_id=str(hypotheses["session_id"]),
                draft_id=draft_id,
                backtest_run_id=backtest_run_id,
                critique_id=critique_id,
                baseline_result_id=baseline_result_id,
                candidate_result_id=candidate_result_id,
                status="failed_closed",
                recommendation="reject",
                comparison={
                    "schema_version": "karkinos.ai.shadow_research_comparison.v1",
                    "failure_code": _failure_code(exc),
                    "promotion_gate": {
                        "status": "blocked",
                        "blockers": [_failure_code(exc)],
                    },
                    "automatic_strategy_replacement_enabled": False,
                    "broker_submission_enabled": False,
                },
                now=self._utc_now(),
            )

    async def _build_comparison(
        self,
        *,
        baseline_result_id: int,
        candidate_result_id: int,
        draft: Mapping[str, Any],
        critique: Mapping[str, Any],
    ) -> dict[str, Any]:
        baseline = await self._db.get_backtest_result(baseline_result_id)
        candidate = await self._db.get_backtest_result(candidate_result_id)
        if not isinstance(baseline, dict) or not isinstance(candidate, dict):
            raise ShadowResearchRejected("comparison_backtest_missing")
        baseline_view = _backtest_view(baseline)
        candidate_view = _backtest_view(candidate)
        critique_artifact = (
            critique.get("artifact")
            if isinstance(critique.get("artifact"), Mapping)
            else {}
        )
        advancement_gate = build_strategy_advancement_gate(
            baseline=baseline_view,
            candidate=candidate_view,
            critique_evidence={
                "status": critique.get("status"),
                "critique_id": critique.get("critique_id"),
                "artifact_fingerprint": (
                    content_fingerprint(critique_artifact)
                    if critique_artifact
                    else None
                ),
            },
        )
        improvements = {
            "total_return": candidate_view["total_return"]
            >= baseline_view["total_return"],
            "sharpe": candidate_view["sharpe"] >= baseline_view["sharpe"],
            "max_drawdown": abs(candidate_view["max_drawdown"])
            <= abs(baseline_view["max_drawdown"]),
        }
        recommendation = (
            "paper_shadow_review" if advancement_gate.passed else "keep_researching"
        )
        return {
            "schema_version": "karkinos.ai.shadow_research_comparison.v1",
            "baseline_source_fingerprint": _backtest_source_fingerprint(baseline),
            "candidate_source_fingerprint": _backtest_source_fingerprint(candidate),
            "economic_hypothesis": draft.get("economic_hypothesis"),
            "risk_impact": draft.get("risk_impact"),
            "failure_conditions": list(draft.get("failure_conditions") or []),
            "limitations": list(draft.get("limitations") or []),
            "baseline": baseline_view,
            "candidate": candidate_view,
            "deltas": {
                "total_return": candidate_view["total_return"]
                - baseline_view["total_return"],
                "sharpe": candidate_view["sharpe"] - baseline_view["sharpe"],
                "max_drawdown": candidate_view["max_drawdown"]
                - baseline_view["max_drawdown"],
                "total_cost": candidate_view["total_cost"]
                - baseline_view["total_cost"],
            },
            "improvements": improvements,
            "deepseek_critique": critique_artifact,
            "recommendation": recommendation,
            "promotion_gate": advancement_gate.to_json_dict(),
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "authority_effect": "research_only",
        }

    def _prepare_baseline(self, policy: ShadowResearchPolicy) -> PreparedBaseline:
        rows = asyncio.run(self._db.get_backtest_results())
        seed = None
        if policy.baseline_backtest_result_id is not None:
            seed = asyncio.run(
                self._db.get_backtest_result(policy.baseline_backtest_result_id)
            )
        else:
            for summary in rows:
                candidate = asyncio.run(
                    self._db.get_backtest_result(int(summary["id"]))
                )
                config = _json_object(
                    candidate.get("config_json") if candidate else None
                )
                if candidate and config.get("strategy") not in {
                    None,
                    "",
                    "ai_formula_research",
                }:
                    seed = candidate
                    break
        if not isinstance(seed, dict):
            raise ShadowResearchRejected("eligible_baseline_backtest_missing")
        config = _json_object(seed.get("config_json"))
        assets = config.get("assets")
        if not isinstance(assets, list) or not assets:
            raise ShadowResearchRejected("baseline_assets_missing")
        start_date = str(config.get("start_date") or "")
        if not start_date:
            raise ShadowResearchRejected("baseline_start_date_missing")
        handlers: dict[Symbol, DataHandler] = {}
        instruments: dict[Symbol, Any] = {}
        frames: dict[Symbol, pd.DataFrame] = {}
        last_dates: list[str] = []
        normalized_assets: list[dict[str, str]] = []
        for asset in assets:
            if not isinstance(asset, dict) or not asset.get("symbol"):
                raise ShadowResearchRejected("baseline_asset_invalid")
            symbol = Symbol(str(asset["symbol"]))
            asset_class_text = str(asset.get("asset_class") or "stock")
            asset_class = _asset_class(asset_class_text)
            frame = self._data_store.load_bars(symbol, BarFrequency.DAILY)
            if frame is None or frame.empty or "timestamp" not in frame.columns:
                raise ShadowResearchRejected(f"persisted_bars_missing:{symbol}")
            frame = frame.copy()
            frame["timestamp"] = pd.to_datetime(frame["timestamp"])
            frame = frame.loc[
                frame["timestamp"] >= pd.Timestamp(start_date)
            ].sort_values("timestamp")
            if frame.empty:
                raise ShadowResearchRejected(f"persisted_window_empty:{symbol}")
            frames[symbol] = frame
            last_dates.append(frame["timestamp"].iloc[-1].date().isoformat())
            normalized_assets.append(
                {"symbol": str(symbol), "asset_class": asset_class_text}
            )
            instruments[symbol] = DataManager.get_instrument(symbol, asset_class)
        market_date = min(last_dates)
        for asset, (symbol, frame) in zip(
            normalized_assets, frames.items(), strict=True
        ):
            asset_class = _asset_class(asset["asset_class"])
            sliced = frame.loc[
                frame["timestamp"]
                <= pd.Timestamp(market_date)
                + pd.Timedelta(days=1)
                - pd.Timedelta(microseconds=1)
            ].reset_index(drop=True)
            handlers[symbol] = DataHandler(
                sliced, symbol, BarFrequency.DAILY, asset_class
            )
        snapshot = build_backtest_dataset_snapshot(
            start_date=start_date,
            end_date=market_date,
            configured_source=None,
            data_handlers=handlers,
            store=self._data_store,
            source_names=[],
        )
        if snapshot.get("data_quality", {}).get("status") != "ok":
            raise ShadowResearchRejected("baseline_dataset_quality_not_complete")
        request = BacktestRequest(
            start_date=start_date,
            end_date=market_date,
            initial_cash=float(
                config.get("initial_cash") or seed.get("initial_cash") or 0
            ),
            strategy=str(config.get("strategy")),
            short_period=int(config.get("short_period") or 5),
            long_period=int(config.get("long_period") or 20),
            params=dict(config.get("params") or {}),
            assets=normalized_assets,
            oos_mode="rolling",
        )
        fee_resolution = self._resolve_reviewed_fee_schedule(
            start_date=start_date,
            end_date=market_date,
            universe=tuple(asset["symbol"] for asset in normalized_assets),
            asset_classes=tuple(asset["asset_class"] for asset in normalized_assets),
        )
        commission_calc = getattr(fee_resolution, "commission_calc", None)
        fee_schedule_evidence = getattr(fee_resolution, "fee_evidence", None)
        cost_model_reference = str(
            getattr(fee_resolution, "cost_model_reference", "") or ""
        )
        if (
            commission_calc is None
            or not isinstance(fee_schedule_evidence, Mapping)
            or not cost_model_reference
        ):
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_resolution_invalid"
            )
        fee_schedule_evidence = dict(fee_schedule_evidence)
        strategy = build_strategy(
            SimpleNamespace(
                strategy=request.strategy,
                short_period=request.short_period,
                long_period=request.long_period,
                params=request.params,
            ),
            _NullEventBus(),
        )
        result = BacktestEngine(
            strategy=strategy,
            instruments=instruments,
            data_handlers=handlers,
            initial_cash=Decimal(str(request.initial_cash)),
            commission_calc=commission_calc,
            db=None,
        ).run()
        min_train, test_window, step = _rolling_oos_parameters(len(result.equity_curve))
        request.oos_min_train_points = min_train
        request.oos_test_window_points = test_window
        request.oos_step_points = step
        evidence = (
            result.evidence_bundle.to_json_dict() if result.evidence_bundle else {}
        )
        metrics = result.metrics
        metrics_json = metrics.to_json_dict()
        metrics_json.update(
            {
                "evidence_bundle": evidence,
                "dataset_snapshot": snapshot,
                "oos_validation": build_rolling_out_of_sample_validation(
                    strategy_id=request.strategy,
                    benchmark_role="current_persisted_baseline",
                    result=result,
                    min_train_points=min_train,
                    test_window_points=test_window,
                    step_points=step,
                ).to_json_dict(),
                "fee_component_evidence": build_backtest_fee_tax_evidence(
                    fills=result.fills,
                    cost_model_reference=cost_model_reference,
                    account_specific=True,
                    fee_schedule_source=str(
                        fee_schedule_evidence.get("fee_schedule_source") or ""
                    ),
                    fee_schedule_fingerprint=str(
                        fee_schedule_evidence.get("fee_schedule_fingerprint") or ""
                    ),
                    broker_statement_reconciled=bool(
                        fee_schedule_evidence.get("broker_statement_reconciled", False)
                    ),
                    fee_schedule_binding=fee_schedule_evidence,
                ),
                "capacity_review": build_backtest_capacity_evidence(
                    fills=result.fills,
                    data_handlers=handlers,
                    initial_cash=result.initial_cash,
                ),
                "market_regime_robustness": build_backtest_market_regime_evidence(
                    result=result,
                    data_handlers=handlers,
                ),
                "automatic_baseline_refresh": True,
                "persisted_market_data_only": True,
            }
        )
        payload = {
            "initial_cash": float(result.initial_cash),
            "final_equity": float(result.final_equity),
            "total_return": float(result.total_return),
            "annual_return": metrics.annual_return,
            "sharpe": metrics.sharpe,
            "sortino": metrics.sortino,
            "max_drawdown": metrics.max_drawdown,
            "win_rate": metrics.win_rate,
            "duration_days": result.duration_days,
            "equity_curve": [
                {"timestamp": timestamp.isoformat(), "equity": float(value)}
                for timestamp, value in result.equity_curve
            ],
            "metrics_json": metrics_json,
            "cost_summary_json": result.cost_summary.to_json_dict(),
            "evidence_json": evidence,
            "fills": [_fill_to_response(fill) for fill in result.fills],
        }
        payload["metrics_json"] = _backtest_report_metrics_json(request, payload)
        return PreparedBaseline(
            seed_result_id=int(seed["id"]),
            market_date=market_date,
            snapshot=snapshot,
            request=request,
            result=payload,
            cost_model_reference=cost_model_reference,
            fee_schedule_evidence=fee_schedule_evidence,
        )

    def _resolve_reviewed_fee_schedule(self, **kwargs: Any) -> Any:
        if self._reviewed_fee_schedule_resolver is None:
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_resolver_missing")
        return self._reviewed_fee_schedule_resolver(**kwargs)

    def _build_research_service(self, *, external: bool) -> Any:
        if self._research_service_builder is not None:
            return self._research_service_builder(external)
        from server.routes.ai_strategy_research import _build_write_service

        return _build_write_service(self._state, external=external)

    def _require_deepseek_provider(self) -> None:
        """Fail closed before export unless the configured edge is DeepSeek."""
        if self._research_service_builder is not None:
            return
        from server.ai_runtime.provider_connectivity import (
            load_provider_connectivity_settings,
        )

        settings = load_provider_connectivity_settings(self._state.config)
        host = (urlparse(settings.endpoint_origin).hostname or "").casefold()
        if settings.provider_id.strip().casefold() != "deepseek" or not (
            host == "deepseek.com" or host.endswith(".deepseek.com")
        ):
            raise ShadowResearchRejected("deepseek_provider_not_configured")

    def _fail_provider_call(self, call_id: str, failure_code: str) -> None:
        self._store.finish_provider_call(
            call_id,
            status="failed",
            actual_tokens=None,
            failure_code=failure_code,
            now=self._utc_now(),
        )

    def _kill_switch(self) -> dict[str, Any]:
        controls = getattr(self._state, "trading_controls", None)
        snapshot = controls.snapshot() if controls is not None else None
        return {
            "enabled": bool(getattr(snapshot, "kill_switch_enabled", False)),
            "reason": str(getattr(snapshot, "reason", "") or ""),
        }

    def _require_runtime_authorization(self, expected: ShadowResearchPolicy) -> None:
        if self._kill_switch()["enabled"]:
            raise ShadowResearchRejected("blocked_by_kill_switch")
        current = self.get_policy()
        if not current.enabled:
            raise ShadowResearchRejected("shadow_research_policy_paused")
        if content_fingerprint(current.to_dict()) != content_fingerprint(
            expected.to_dict()
        ):
            raise ShadowResearchRejected("shadow_research_policy_changed")

    def _record_preflight(
        self,
        *,
        status: str,
        failure_code: str,
        market_date: str | None = None,
    ) -> dict[str, Any]:
        effective_date = (
            market_date or self._now().astimezone(_SHANGHAI_TZ).date().isoformat()
        )
        now = self._utc_now()
        fingerprint = content_fingerprint(
            {
                "market_date": effective_date,
                "status": status,
                "failure_code": failure_code,
            }
        )
        row = self._db.upsert_automation_run_sync(
            {
                "run_id": f"automation:ai-shadow-research-preflight:{effective_date}:{fingerprint[:12]}",
                "run_type": SHADOW_RESEARCH_RUN_TYPE,
                "run_date": effective_date,
                "status": status,
                "execution_mode": "research_only",
                "started_at": now,
                "finished_at": now,
                "source_ref": None,
                "payload": {
                    "schema_version": SHADOW_RESEARCH_API_SCHEMA,
                    "failure_code": failure_code,
                    "provider_call_performed": False,
                    "automatic_strategy_replacement_enabled": False,
                    "broker_submission_enabled": False,
                    "authority_effect": "none",
                },
            }
        )
        return {
            **self.status(),
            "run_status": status,
            "failure_code": failure_code,
            "preflight_run_id": row["run_id"],
        }

    async def _notify(
        self, market_date: str, candidates: list[Mapping[str, Any]]
    ) -> None:
        sender = getattr(getattr(self._state, "notifier", None), "send", None)
        if not callable(sender) or not candidates:
            return
        eligible = sum(
            item.get("recommendation") == "paper_shadow_review" for item in candidates
        )
        message = (
            f"DeepSeek 收盘后策略研究已完成（{market_date}）。\n"
            f"研究候选: {len(candidates)}\n"
            f"建议进入人工 paper/shadow 复核: {eligible}\n"
            "请在 Web 的 AI 研究页检查新旧指标、成本、OOS 与风险。"
            "系统没有替换生产策略，也没有创建或提交真实订单。"
        )
        try:
            await asyncio.to_thread(
                sender,
                title=f"Karkinos AI 策略研究: {market_date}",
                message=message,
            )
        except Exception:
            logger.warning("Shadow research notification failed", exc_info=True)

    def _utc_now(self) -> str:
        return self._now().astimezone(timezone.utc).isoformat()


class _NullEventBus:
    def subscribe(self, *args: Any, **kwargs: Any) -> None:
        return None

    def publish(self, *args: Any, **kwargs: Any) -> None:
        return None


def build_ai_shadow_research_automation_service(
    state: Any,
) -> AiShadowResearchAutomationService:
    path = Path(getattr(state.db, "_path"))
    store = ShadowResearchStore(path)
    store.init()
    from server.bootstrap import resolve_data_dir
    from server.services.reviewed_fee_schedule import resolve_reviewed_fee_schedule

    return AiShadowResearchAutomationService(
        state=state,
        store=store,
        data_store=DataStore(resolve_data_dir()),
        reviewed_fee_schedule_resolver=lambda **kwargs: resolve_reviewed_fee_schedule(
            state, **kwargs
        ),
    )


async def run_ai_shadow_research_automation_loop(
    *, state: Any, interval_seconds: float = 300.0
) -> None:
    """Poll a read-mostly standing policy and run once per new evidence identity."""
    service: AiShadowResearchAutomationService | None = None
    while True:
        try:
            if service is None:
                service = build_ai_shadow_research_automation_service(state)
            await service.run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Shadow research automation loop failed closed", exc_info=True
            )
        await asyncio.sleep(max(30.0, interval_seconds))


def _after_close(market_date: str, now: datetime, after_close_time: str) -> bool:
    evidence_date = datetime.fromisoformat(market_date).date()
    if evidence_date < now.date():
        return True
    if evidence_date > now.date():
        return False
    return now.time().replace(tzinfo=None) >= time.fromisoformat(after_close_time)


def _asset_class(value: str) -> AssetClass:
    try:
        return AssetClass.FUND if value == "etf" else AssetClass(value)
    except ValueError as exc:
        raise ShadowResearchRejected("baseline_asset_class_invalid") from exc


def _backtest_view(row: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _json_object(row.get("metrics_json"))
    costs = _json_object(row.get("cost_summary_json"))
    evidence = _json_object(metrics.get("evidence_bundle"))
    research = _json_object(metrics.get("research_evidence_bundle"))
    oos = _json_object(metrics.get("oos_validation"))
    aggregate = _json_object(oos.get("aggregate"))
    oos_folds = [
        {
            "fold_index": fold.get("fold_index"),
            "split_timestamp": fold.get("split_timestamp"),
            "net_return": _json_object(fold.get("out_of_sample")).get("net_return"),
            "total_cost": _json_object(fold.get("out_of_sample")).get("total_cost"),
        }
        for fold in oos.get("folds") or []
        if isinstance(fold, Mapping)
    ]
    dataset = _json_object(metrics.get("dataset_snapshot"))
    dataset_quality = _json_object(dataset.get("data_quality"))
    total_cost = float(evidence.get("total_cost") or 0)
    return {
        "result_id": int(row["id"]),
        "initial_cash": float(row.get("initial_cash") or 0),
        "total_return": float(row.get("total_return") or 0),
        "sharpe": float(row.get("sharpe") or 0),
        "max_drawdown": float(row.get("max_drawdown") or 0),
        "total_cost": total_cost,
        "total_commission": float(costs.get("total_commission") or 0),
        "total_slippage": float(costs.get("total_slippage") or 0),
        "total_trades": int(costs.get("total_trades") or 0),
        "gross_turnover": float(costs.get("gross_turnover") or 0),
        "oos_validation_mode": str(oos.get("validation_mode") or "missing"),
        "oos_fold_count": int(oos.get("fold_count") or 0),
        "oos_pass_rate": aggregate.get("pass_rate"),
        "oos_folds": oos_folds,
        "mean_oos_return": float(aggregate.get("mean_out_of_sample_return") or 0),
        "worst_oos_return": float(aggregate.get("worst_out_of_sample_return") or 0),
        "oos_validation_status": str(oos.get("validation_status") or "missing"),
        "evidence_gate_status": str(research.get("gate_status") or "missing"),
        "dataset_snapshot_id": dataset.get("snapshot_id"),
        "dataset_quality_status": dataset_quality.get("status"),
        "dataset_issue_count": len(dataset_quality.get("issues") or []),
        "parameter_robustness": _json_object(
            metrics.get("parameter_robustness") or metrics.get("sweep_robustness")
        ),
        "formula_parameter_values": _json_object(
            _json_object(metrics.get("formula_binding")).get("parameter_values")
        ),
        "market_regime_robustness": _json_object(
            metrics.get("market_regime_robustness")
        ),
        "account_capital_constraint": _json_object(
            metrics.get("account_capital_constraint")
        ),
        "capacity_review": _json_object(metrics.get("capacity_review")),
        "fee_component_evidence": _json_object(metrics.get("fee_component_evidence")),
    }


def _backtest_source_fingerprint(row: Mapping[str, Any]) -> str:
    return content_fingerprint(
        {
            "id": int(row.get("id") or 0),
            "initial_cash": row.get("initial_cash"),
            "final_equity": row.get("final_equity"),
            "total_return": row.get("total_return"),
            "sharpe": row.get("sharpe"),
            "max_drawdown": row.get("max_drawdown"),
            "metrics": _json_object(row.get("metrics_json")),
            "cost_summary": _json_object(row.get("cost_summary_json")),
        }
    )


def _hypothesis_usage(session: Mapping[str, Any]) -> int | None:
    drafts = session.get("drafts")
    if not isinstance(drafts, list) or not drafts:
        return None
    provenance = (
        drafts[0].get("provider_provenance") if isinstance(drafts[0], dict) else None
    )
    return _usage_tokens(provenance)


def _critique_usage(critique: Mapping[str, Any]) -> int | None:
    artifact = critique.get("artifact")
    provenance = (
        artifact.get("provider_provenance") if isinstance(artifact, dict) else None
    )
    return _usage_tokens(provenance)


def _usage_tokens(provenance: Any) -> int | None:
    if not isinstance(provenance, Mapping):
        return None
    usage = provenance.get("usage")
    if not isinstance(usage, Mapping):
        return None
    value = usage.get("total_tokens")
    try:
        parsed = int(value) if value is not None else None
        return parsed if parsed is None or parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def _candidate_row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["comparison"] = _json_object(result.pop("comparison_json", "{}"))
    result.update(
        {
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "human_paper_shadow_approval_required": True,
        }
    )
    return result


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _failure_code(exc: Exception) -> str:
    value = str(exc).strip()
    if (
        value
        and len(value) <= 160
        and all(char.isalnum() or char in "_:-." for char in value)
    ):
        return value
    return type(exc).__name__
