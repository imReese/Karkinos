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
from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from analytics.backtest_fee_tax_evidence import build_backtest_fee_tax_evidence
from analytics.backtest_market_regime_evidence import (
    build_backtest_market_regime_evidence,
)
from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from analytics.oos_validation import build_rolling_out_of_sample_validation
from analytics.strategy_advancement_gate import (
    build_strategy_advancement_gate,
    is_valid_passed_strategy_advancement_gate,
    strategy_advancement_backtest_view,
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
    STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT,
    STRATEGY_RESEARCH_MAX_CANDIDATES,
    STRATEGY_RESEARCH_MAX_PROVIDER_CALLS,
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
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
    build_daily_strategy_promotion_binding,
)
from server.services.reviewed_fee_schedule import (
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
)
from server.services.valuation_snapshot import build_current_valuation_snapshot

logger = logging.getLogger(__name__)

SHADOW_RESEARCH_POLICY_ID = "ai_shadow_research"
SHADOW_RESEARCH_POLICY_SCHEMA = "karkinos.ai.shadow_research_policy.v2"
SHADOW_RESEARCH_API_SCHEMA = "karkinos.ai.shadow_research_automation.v1"
SHADOW_RESEARCH_RUN_TYPE = "ai_shadow_research"
SHADOW_RESEARCH_RUNTIME_CONTRACT = "karkinos.ai.shadow_research_runtime.v8"
SHADOW_RESEARCH_POLICY_CONFIRMATION = (
    "authorize_five_sequential_after_close_deepseek_strategy_research_without_"
    "daily_token_budget_or_strategy_or_trade_authority"
)
SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION = (
    "authorize_after_close_deepseek_strategy_research_without_strategy_or_trade_"
    "authority"
)
SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED = "unbounded_daily"
SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED = "legacy_bounded_daily"
SHADOW_RESEARCH_PAUSE_CONFIRMATION = (
    "pause_after_close_ai_strategy_research_without_changing_trading_authority"
)
SHADOW_RESEARCH_PROMOTION_CONFIRMATION = "approve_evidence_bound_candidate_for_paper_shadow_only_without_production_or_trade_authority"
SHADOW_RESEARCH_RETRY_CONFIRMATION = (
    "authorize_one_additional_complete_five_round_ten_call_strategy_research_"
    "retry_without_strategy_trade_or_capital_authority"
)
SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION = (
    "authorize_one_additional_deepseek_call_for_citation_contract_retry_without_"
    "strategy_trade_or_capital_authority"
)
SHADOW_RESEARCH_OUTPUT_TRUNCATION_CALL_EXTENSION_CONFIRMATION = (
    "authorize_one_additional_deepseek_call_for_output_truncation_retry_without_"
    "strategy_trade_or_capital_authority"
)
SHADOW_RESEARCH_TIMEOUT_RESUME_CALL_EXTENSION_CONFIRMATION = (
    "authorize_one_additional_deepseek_call_for_partial_fifth_round_timeout_"
    "resume_without_strategy_trade_or_capital_authority"
)
_CITATION_CONTRACT_RETRYABLE_FAILURE_CODES = ("provider_citation_not_in_bound_input",)
_OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES = ("provider_output_truncated",)
_TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES = ("provider_timeout",)
_TIMEOUT_RESUME_COMPLETED_ITERATIONS = 4
_TIMEOUT_RESUME_ITERATION = 5
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION = (
    STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION
)
SHADOW_RESEARCH_MAX_PROVIDER_CALLS = STRATEGY_RESEARCH_MAX_PROVIDER_CALLS
SHADOW_RESEARCH_MAX_CANDIDATES = STRATEGY_RESEARCH_MAX_CANDIDATES
_PROVIDER_FREE_RETRYABLE_FAILURE_CODES = (
    "account_evidence_binding_mismatch",
    "ai_runtime_role_identity_conflict",
    "research_account_binding_required",
    "research_account_capital_evidence_not_passing",
    "research_account_evidence_identity_mismatch",
    "research_account_evidence_not_authoritative",
    "research_account_total_equity_invalid",
    "research_account_truth_binding_not_reconciled",
    "research_initial_cash_exceeds_current_account_equity",
    "research_initial_cash_invalid",
    "reviewed_fee_schedule_current_reconciliation_blocked",
)


class ShadowResearchRejected(ValueError):
    """Fail-closed shadow research policy or evidence rejection."""


@dataclass(frozen=True)
class ShadowResearchPolicy:
    enabled: bool = False
    after_close_time: str = "15:30"
    max_provider_calls_per_market_date: int = SHADOW_RESEARCH_MAX_PROVIDER_CALLS
    daily_token_budget: int | None = None
    max_candidates_per_run: int = SHADOW_RESEARCH_MAX_CANDIDATES
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
        if not (
            1
            <= self.max_provider_calls_per_market_date
            <= SHADOW_RESEARCH_MAX_PROVIDER_CALLS
        ):
            raise ShadowResearchRejected("provider_call_limit_out_of_range")
        if self.daily_token_budget is not None and (
            isinstance(self.daily_token_budget, bool)
            or self.daily_token_budget < SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION
        ):
            raise ShadowResearchRejected("legacy_daily_token_budget_out_of_range")
        if not 1 <= self.max_candidates_per_run <= SHADOW_RESEARCH_MAX_CANDIDATES:
            raise ShadowResearchRejected("candidate_limit_out_of_range")
        if self.max_provider_calls_per_market_date < self.max_candidates_per_run * 2:
            raise ShadowResearchRejected(
                "provider_call_limit_cannot_cover_sequential_iterations"
            )
        if self.daily_token_budget is not None and self.daily_token_budget < (
            SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * self.max_candidates_per_run * 2
        ):
            raise ShadowResearchRejected(
                "legacy_daily_token_budget_cannot_cover_reserved_calls"
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
        if self.enabled:
            required_authorization = (
                SHADOW_RESEARCH_POLICY_CONFIRMATION
                if self.daily_token_budget is None
                else SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION
            )
            if self.authorization != required_authorization:
                raise PermissionError(
                    "standing shadow research requires exact owner authorization"
                )

    @property
    def token_budget_mode(self) -> str:
        return (
            SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED
            if self.daily_token_budget is None
            else SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED
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
            "token_budget_mode": self.token_budget_mode,
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
        raw_daily_token_budget = (
            value.get("daily_token_budget") if "daily_token_budget" in value else None
        )
        daily_token_budget = (
            int(raw_daily_token_budget) if raw_daily_token_budget is not None else None
        )
        expected_token_budget_mode = (
            SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED
            if daily_token_budget is None
            else SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED
        )
        if value.get("token_budget_mode") not in (
            None,
            expected_token_budget_mode,
        ):
            raise ShadowResearchRejected("token_budget_mode_conflicts_with_policy")
        return cls(
            enabled=bool(value.get("enabled", False)),
            after_close_time=str(value.get("after_close_time") or "15:30"),
            max_provider_calls_per_market_date=int(
                value.get("max_provider_calls_per_market_date")
                or SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            ),
            daily_token_budget=daily_token_budget,
            max_candidates_per_run=int(
                value.get("max_candidates_per_run") or SHADOW_RESEARCH_MAX_CANDIDATES
            ),
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
                CREATE TABLE IF NOT EXISTS ai_shadow_research_run_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    market_date TEXT NOT NULL,
                    superseded_run_id TEXT NOT NULL UNIQUE,
                    superseded_input_fingerprint TEXT NOT NULL UNIQUE,
                    replacement_run_id TEXT NOT NULL,
                    replacement_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL,
                    run_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_retry_authorizations (
                    authorization_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL,
                    provider_calls_at_authorization INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 10),
                    provider_call_ceiling INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_retry_consumptions (
                    authorization_id TEXT PRIMARY KEY,
                    replacement_run_id TEXT NOT NULL UNIQUE,
                    replacement_input_fingerprint TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_citation_call_extensions (
                    extension_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL,
                    provider_calls_at_authorization INTEGER NOT NULL,
                    prior_provider_call_ceiling INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 1),
                    provider_call_ceiling INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_citation_call_extension_consumptions (
                    extension_id TEXT PRIMARY KEY,
                    replacement_run_id TEXT NOT NULL UNIQUE,
                    replacement_input_fingerprint TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_output_truncation_call_extensions (
                    extension_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL
                        CHECK(failure_code = 'provider_output_truncated'),
                    provider_calls_at_authorization INTEGER NOT NULL,
                    prior_provider_call_ceiling INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 1),
                    provider_call_ceiling INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_output_truncation_call_extension_consumptions (
                    extension_id TEXT PRIMARY KEY,
                    replacement_run_id TEXT NOT NULL UNIQUE,
                    replacement_input_fingerprint TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_timeout_resume_call_extensions (
                    extension_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL
                        CHECK(failure_code = 'provider_timeout'),
                    completed_iteration_count INTEGER NOT NULL
                        CHECK(completed_iteration_count = 4),
                    completed_evidence_fingerprint TEXT NOT NULL,
                    failed_call_id TEXT NOT NULL UNIQUE,
                    provider_calls_at_authorization INTEGER NOT NULL,
                    prior_provider_call_ceiling INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 1),
                    provider_call_ceiling INTEGER NOT NULL,
                    resume_iteration INTEGER NOT NULL
                        CHECK(resume_iteration = 5),
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_timeout_resume_call_extension_consumptions (
                    extension_id TEXT PRIMARY KEY,
                    resumed_run_id TEXT NOT NULL UNIQUE,
                    resumed_input_fingerprint TEXT NOT NULL UNIQUE,
                    completed_evidence_fingerprint TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
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
        timeout_resume_input_evidence: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_runs WHERE market_date=?
                ORDER BY created_at LIMIT 1
                """,
                (market_date,),
            ).fetchone()
            if existing is not None:
                existing_run = dict(existing)
                timeout_resume_extension = (
                    self._unconsumed_timeout_resume_call_extension(conn, existing_run)
                )
                if timeout_resume_extension is not None:
                    if timeout_resume_input_evidence is not None:
                        self._validate_timeout_resume_input_evidence(
                            conn,
                            run=existing_run,
                            baseline_seed_result_id=baseline_seed_result_id,
                            valuation_snapshot_id=valuation_snapshot_id,
                            ledger_cutoff_id=ledger_cutoff_id,
                            evidence=timeout_resume_input_evidence,
                        )
                    elif input_fingerprint != existing_run["input_fingerprint"]:
                        raise ShadowResearchRejected(
                            "timeout_resume_input_fingerprint_drift"
                        )
                    checkpoint = self._partial_resume_checkpoint(conn, existing_run)
                    if checkpoint["completed_evidence_fingerprint"] != (
                        timeout_resume_extension["completed_evidence_fingerprint"]
                    ):
                        raise ShadowResearchRejected(
                            "timeout_resume_completed_evidence_drift"
                        )
                    conn.execute(
                        """
                        UPDATE ai_shadow_research_runs
                        SET status='running', failure_code=NULL,
                            candidate_count=?, updated_at=?
                        WHERE run_id=? AND status='failed'
                        """,
                        (
                            _TIMEOUT_RESUME_COMPLETED_ITERATIONS,
                            now,
                            existing_run["run_id"],
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO ai_shadow_research_timeout_resume_call_extension_consumptions
                        (extension_id, resumed_run_id, resumed_input_fingerprint,
                         completed_evidence_fingerprint, consumed_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            timeout_resume_extension["extension_id"],
                            existing_run["run_id"],
                            input_fingerprint,
                            checkpoint["completed_evidence_fingerprint"],
                            now,
                        ),
                    )
                    resumed = conn.execute(
                        "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                        (existing_run["run_id"],),
                    ).fetchone()
                    if resumed is None:
                        raise RuntimeError("timeout resume persistence failed")
                    return {
                        **dict(resumed),
                        "partial_resume_iteration": _TIMEOUT_RESUME_ITERATION,
                        "partial_resume_extension_id": timeout_resume_extension[
                            "extension_id"
                        ],
                        "partial_resume_evidence_fingerprint": checkpoint[
                            "completed_evidence_fingerprint"
                        ],
                    }, False
                retry_authorization = self._unconsumed_retry_authorization(
                    conn, existing_run
                )
                citation_extension = (
                    self._unconsumed_citation_call_extension(conn, existing_run)
                    if input_fingerprint != existing_run["input_fingerprint"]
                    else None
                )
                output_truncation_extension = (
                    self._unconsumed_output_truncation_call_extension(
                        conn, existing_run
                    )
                    if input_fingerprint != existing_run["input_fingerprint"]
                    else None
                )
                provider_free_rearm = input_fingerprint != existing_run[
                    "input_fingerprint"
                ] and self._can_rearm_provider_free_failure(conn, existing_run)
                if retry_authorization is not None:
                    input_fingerprint = content_fingerprint(
                        {
                            "failed_input_fingerprint": existing_run[
                                "input_fingerprint"
                            ],
                            "current_input_fingerprint": input_fingerprint,
                            "retry_authorization_id": retry_authorization[
                                "authorization_id"
                            ],
                        }
                    )
                elif citation_extension is not None:
                    input_fingerprint = content_fingerprint(
                        {
                            "failed_input_fingerprint": existing_run[
                                "input_fingerprint"
                            ],
                            "current_input_fingerprint": input_fingerprint,
                            "citation_call_extension_id": citation_extension[
                                "extension_id"
                            ],
                        }
                    )
                elif output_truncation_extension is not None:
                    input_fingerprint = content_fingerprint(
                        {
                            "failed_input_fingerprint": existing_run[
                                "input_fingerprint"
                            ],
                            "current_input_fingerprint": input_fingerprint,
                            "output_truncation_call_extension_id": (
                                output_truncation_extension["extension_id"]
                            ),
                        }
                    )
                elif not provider_free_rearm:
                    return existing_run, True
                retry_consumption = (
                    conn.execute(
                        """
                        SELECT consumption.authorization_id
                        FROM ai_shadow_research_retry_consumptions AS consumption
                        JOIN ai_shadow_research_retry_authorizations AS authorization
                          ON authorization.authorization_id=consumption.authorization_id
                        WHERE authorization.market_date=?
                        """,
                        (market_date,),
                    ).fetchone()
                    if (
                        provider_free_rearm
                        or citation_extension is not None
                        or output_truncation_extension is not None
                    )
                    else None
                )
                citation_extension_consumption = (
                    conn.execute(
                        """
                        SELECT consumption.extension_id
                        FROM ai_shadow_research_citation_call_extension_consumptions
                             AS consumption
                        JOIN ai_shadow_research_citation_call_extensions AS extension
                          ON extension.extension_id=consumption.extension_id
                        WHERE extension.market_date=?
                        """,
                        (market_date,),
                    ).fetchone()
                    if (
                        provider_free_rearm
                        or citation_extension is not None
                        or output_truncation_extension is not None
                    )
                    else None
                )
                output_truncation_extension_consumption = (
                    conn.execute(
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
                    if (
                        provider_free_rearm
                        or citation_extension is not None
                        or output_truncation_extension is not None
                    )
                    else None
                )
                run_id = f"ai-shadow-research:{market_date}:{input_fingerprint[:16]}"
                attempt_id = (
                    "ai-shadow-research-attempt:"
                    + content_fingerprint(
                        {
                            "superseded_run_id": existing_run["run_id"],
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
                        existing_run["run_id"],
                        existing_run["input_fingerprint"],
                        run_id,
                        input_fingerprint,
                        existing_run["failure_code"],
                        canonical_json(existing_run),
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE ai_shadow_research_runs
                    SET run_id=?, input_fingerprint=?, status='running',
                        baseline_seed_result_id=?, baseline_result_id=NULL,
                        valuation_snapshot_id=?, ledger_cutoff_id=?,
                        session_id=NULL, failure_code=NULL, candidate_count=0,
                        created_at=?, updated_at=?
                    WHERE run_id=?
                    """,
                    (
                        run_id,
                        input_fingerprint,
                        baseline_seed_result_id,
                        valuation_snapshot_id,
                        ledger_cutoff_id,
                        now,
                        now,
                        existing_run["run_id"],
                    ),
                )
                if retry_authorization is not None:
                    conn.execute(
                        """
                        INSERT INTO ai_shadow_research_retry_consumptions
                        (authorization_id, replacement_run_id,
                         replacement_input_fingerprint, consumed_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            retry_authorization["authorization_id"],
                            run_id,
                            input_fingerprint,
                            now,
                        ),
                    )
                elif retry_consumption is not None:
                    conn.execute(
                        """
                        UPDATE ai_shadow_research_retry_consumptions
                        SET replacement_run_id=?, replacement_input_fingerprint=?
                        WHERE authorization_id=?
                        """,
                        (
                            run_id,
                            input_fingerprint,
                            retry_consumption["authorization_id"],
                        ),
                    )
                if citation_extension is not None:
                    conn.execute(
                        """
                        INSERT INTO ai_shadow_research_citation_call_extension_consumptions
                        (extension_id, replacement_run_id,
                         replacement_input_fingerprint, consumed_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            citation_extension["extension_id"],
                            run_id,
                            input_fingerprint,
                            now,
                        ),
                    )
                elif citation_extension_consumption is not None:
                    conn.execute(
                        """
                        UPDATE ai_shadow_research_citation_call_extension_consumptions
                        SET replacement_run_id=?, replacement_input_fingerprint=?
                        WHERE extension_id=?
                        """,
                        (
                            run_id,
                            input_fingerprint,
                            citation_extension_consumption["extension_id"],
                        ),
                    )
                if output_truncation_extension is not None:
                    conn.execute(
                        """
                        INSERT INTO ai_shadow_research_output_truncation_call_extension_consumptions
                        (extension_id, replacement_run_id,
                         replacement_input_fingerprint, consumed_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            output_truncation_extension["extension_id"],
                            run_id,
                            input_fingerprint,
                            now,
                        ),
                    )
                elif output_truncation_extension_consumption is not None:
                    conn.execute(
                        """
                        UPDATE ai_shadow_research_output_truncation_call_extension_consumptions
                        SET replacement_run_id=?, replacement_input_fingerprint=?
                        WHERE extension_id=?
                        """,
                        (
                            run_id,
                            input_fingerprint,
                            output_truncation_extension_consumption["extension_id"],
                        ),
                    )
                rearmed = conn.execute(
                    "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if rearmed is None:
                    raise RuntimeError("shadow research retry persistence failed")
                return dict(rearmed), False
            duplicate_input = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE input_fingerprint=?",
                (input_fingerprint,),
            ).fetchone()
            if duplicate_input is not None:
                return dict(duplicate_input), True
            run_id = f"ai-shadow-research:{market_date}:{input_fingerprint[:16]}"
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

    def _validate_timeout_resume_input_evidence(
        self,
        conn: sqlite3.Connection,
        *,
        run: Mapping[str, Any],
        baseline_seed_result_id: int,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        evidence: Mapping[str, Any],
    ) -> None:
        selection_components = evidence.get("selection_components")
        if not isinstance(selection_components, Mapping):
            raise ShadowResearchRejected("timeout_resume_input_evidence_invalid")
        if (
            int(run.get("baseline_seed_result_id") or 0) != int(baseline_seed_result_id)
            or str(run.get("valuation_snapshot_id") or "") != str(valuation_snapshot_id)
            or int(run.get("ledger_cutoff_id") or 0) != int(ledger_cutoff_id)
        ):
            raise ShadowResearchRejected("timeout_resume_input_evidence_drift")

        baseline_result_id = int(run.get("baseline_result_id") or 0)
        baseline = conn.execute(
            """
            SELECT baseline_fingerprint
            FROM ai_shadow_research_baselines
            WHERE backtest_result_id=?
            """,
            (baseline_result_id,),
        ).fetchone()
        if baseline is None or baseline["baseline_fingerprint"] != str(
            evidence.get("baseline_fingerprint") or ""
        ):
            raise ShadowResearchRejected("timeout_resume_input_evidence_drift")

        try:
            expected_selection = StrategyResearchSelection(
                saved_backtest_result_id=baseline_result_id,
                **dict(selection_components),
            ).to_dict()
        except (TypeError, ValueError, StrategyResearchRejected) as exc:
            raise ShadowResearchRejected(
                "timeout_resume_input_evidence_invalid"
            ) from exc
        requests = conn.execute(
            """
            SELECT session.request_json
            FROM ai_shadow_research_candidates AS candidate
            JOIN ai_strategy_research_sessions AS session
              ON session.session_id=candidate.session_id
            WHERE candidate.run_id=?
            ORDER BY CAST(json_extract(candidate.comparison_json,
                         '$.iteration_lineage.iteration_number') AS INTEGER),
                     candidate.created_at, candidate.candidate_id
            """,
            (run["run_id"],),
        ).fetchall()
        expected_request_fields = {
            "requested_by": str(evidence.get("requested_by") or ""),
            "account_alias": str(evidence.get("account_alias") or ""),
            "research_question": str(evidence.get("research_question") or ""),
        }
        if len(requests) != _TIMEOUT_RESUME_COMPLETED_ITERATIONS or not all(
            expected_request_fields.values()
        ):
            raise ShadowResearchRejected("timeout_resume_input_evidence_invalid")
        for row in requests:
            request = _json_object(row["request_json"])
            if (
                any(
                    request.get(key) != value
                    for key, value in expected_request_fields.items()
                )
                or request.get("selection") != expected_selection
                or request.get("confirmation_recorded") is not True
                or request.get("api_key_recorded") is not False
            ):
                raise ShadowResearchRejected("timeout_resume_input_evidence_drift")

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
            placeholders = ", ".join(
                "?" for _ in _PROVIDER_FREE_RETRYABLE_FAILURE_CODES
            )
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
                (failed_run_id, *_PROVIDER_FREE_RETRYABLE_FAILURE_CODES),
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
                not in _CITATION_CONTRACT_RETRYABLE_FAILURE_CODES
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
                not in _OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES
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
                not in _TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES
                or int(failed_run["candidate_count"] or 0) != 0
            ):
                raise ShadowResearchRejected(
                    "timeout_resume_requires_exact_partial_fifth_round_failure"
                )
            checkpoint = self._partial_resume_checkpoint(conn, failed_run_mapping)
            failed_call_id = (
                f"{failed_run_id}:hypothesis:iteration:"
                f"{_TIMEOUT_RESUME_ITERATION:02d}"
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
            or run.get("failure_code") not in _TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES
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

    def load_partial_resume_checkpoint(
        self,
        run_id: str,
        *,
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise LookupError(f"shadow research run not found: {run_id}")
            checkpoint = self._partial_resume_checkpoint(conn, dict(run))
        if checkpoint["completed_evidence_fingerprint"] != expected_fingerprint:
            raise ShadowResearchRejected("timeout_resume_completed_evidence_drift")
        return checkpoint

    def _partial_resume_checkpoint(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> dict[str, Any]:
        rows = conn.execute(
            """
            SELECT c.candidate_id, c.run_id, c.session_id, c.draft_id,
                   c.backtest_run_id, c.critique_id, c.baseline_result_id,
                   c.candidate_result_id, c.status, c.recommendation,
                   c.comparison_json, c.promotion_status, c.created_at,
                   c.updated_at,
                   s.idempotency_key AS session_idempotency_key,
                   s.request_fingerprint AS session_request_fingerprint,
                   s.request_json AS session_request_json,
                   s.selection_fingerprint AS session_selection_fingerprint,
                   s.status AS session_status,
                   d.contract_json AS draft_contract_json,
                   d.artifact_fingerprint AS draft_artifact_fingerprint,
                   d.formula_fingerprint AS draft_formula_fingerprint,
                   d.validation_status AS draft_validation_status,
                   b.idempotency_key AS backtest_idempotency_key,
                   b.session_id AS backtest_session_id,
                   b.draft_id AS backtest_draft_id,
                   b.status AS backtest_status,
                   b.canonical_backtest_result_id,
                   b.evidence_fingerprint AS backtest_evidence_fingerprint,
                   q.idempotency_key AS critique_idempotency_key,
                   q.session_id AS critique_session_id,
                   q.draft_id AS critique_draft_id,
                   q.backtest_run_id AS critique_backtest_run_id,
                   q.status AS critique_status,
                   q.normalized_artifact_json AS critique_artifact_json,
                   q.artifact_fingerprint AS critique_artifact_fingerprint
            FROM ai_shadow_research_candidates AS c
            LEFT JOIN ai_strategy_research_sessions AS s
              ON s.session_id=c.session_id
            LEFT JOIN ai_strategy_hypothesis_drafts AS d
              ON d.session_id=c.session_id AND d.draft_id=c.draft_id
            LEFT JOIN ai_strategy_formula_backtests AS b
              ON b.backtest_run_id=c.backtest_run_id
            LEFT JOIN ai_strategy_backtest_critiques AS q
              ON q.critique_id=c.critique_id
            WHERE c.run_id=?
            ORDER BY CAST(json_extract(c.comparison_json,
                         '$.iteration_lineage.iteration_number') AS INTEGER),
                     c.created_at, c.candidate_id
            """,
            (run["run_id"],),
        ).fetchall()
        if len(rows) != _TIMEOUT_RESUME_COMPLETED_ITERATIONS:
            raise ShadowResearchRejected(
                "timeout_resume_requires_exact_four_completed_candidates"
            )
        candidates: list[dict[str, Any]] = []
        drafts: list[dict[str, Any]] = []
        evidence_iterations: list[dict[str, Any]] = []
        previous_iteration: dict[str, Any] | None = None
        candidate_columns = (
            "candidate_id",
            "run_id",
            "session_id",
            "draft_id",
            "backtest_run_id",
            "critique_id",
            "baseline_result_id",
            "candidate_result_id",
            "status",
            "recommendation",
            "comparison_json",
            "promotion_status",
            "created_at",
            "updated_at",
        )
        for expected_iteration, row in enumerate(rows, start=1):
            candidate = _candidate_row({key: row[key] for key in candidate_columns})
            draft = _json_object(row["draft_contract_json"])
            session_request = _json_object(row["session_request_json"])
            critique_artifact = _json_object(row["critique_artifact_json"])
            expected_context = _build_iteration_context(
                iteration_number=expected_iteration,
                total_iterations=SHADOW_RESEARCH_MAX_CANDIDATES,
                previous_iteration=previous_iteration,
            )
            comparison = candidate["comparison"]
            expected_lineage = _iteration_lineage(
                expected_context,
                current_formula_fingerprint=draft.get("formula_fingerprint"),
            )
            expected_hypothesis_call_id = (
                f"{run['run_id']}:hypothesis:iteration:{expected_iteration:02d}"
            )
            expected_backtest_idempotency_key = (
                f"{run['run_id']}:backtest:{candidate['draft_id']}"
            )
            expected_critique_idempotency_key = (
                f"{run['run_id']}:critique:{candidate['draft_id']}"
            )
            completed_calls = conn.execute(
                """
                SELECT call_id, run_id, market_date, call_kind, status,
                       actual_tokens, failure_code, created_at, updated_at
                FROM ai_shadow_research_provider_calls
                WHERE call_id IN (?, ?)
                ORDER BY call_id
                """,
                (expected_hypothesis_call_id, expected_critique_idempotency_key),
            ).fetchall()
            completed_call_evidence = [dict(call) for call in completed_calls]
            completed_call_by_id = {
                str(call["call_id"]): call for call in completed_call_evidence
            }
            hypothesis_call = completed_call_by_id.get(expected_hypothesis_call_id)
            critique_call = completed_call_by_id.get(expected_critique_idempotency_key)
            if (
                candidate["status"]
                not in {"awaiting_human_approval", "research_blocked"}
                or candidate["promotion_status"]
                not in {"awaiting_human_approval", "blocked_by_evidence"}
                or int(candidate["baseline_result_id"] or 0)
                != int(run.get("baseline_result_id") or 0)
                or row["session_status"] != "completed"
                or row["session_idempotency_key"] != expected_hypothesis_call_id
                or session_request.get("iteration_context") != expected_context
                or row["draft_validation_status"] != "valid"
                or not draft
                or row["draft_artifact_fingerprint"] != content_fingerprint(draft)
                or row["draft_formula_fingerprint"] != draft.get("formula_fingerprint")
                or draft.get("iteration_context_fingerprint")
                != expected_context["context_fingerprint"]
                or row["backtest_idempotency_key"] != expected_backtest_idempotency_key
                or row["backtest_session_id"] != candidate["session_id"]
                or row["backtest_draft_id"] != candidate["draft_id"]
                or row["backtest_status"] != "completed"
                or int(row["canonical_backtest_result_id"] or 0)
                != int(candidate["candidate_result_id"] or 0)
                or row["critique_idempotency_key"] != expected_critique_idempotency_key
                or row["critique_session_id"] != candidate["session_id"]
                or row["critique_draft_id"] != candidate["draft_id"]
                or row["critique_backtest_run_id"] != candidate["backtest_run_id"]
                or row["critique_status"] != "completed"
                or not critique_artifact
                or row["critique_artifact_fingerprint"]
                != content_fingerprint(critique_artifact)
                or comparison.get("deepseek_critique") != critique_artifact
                or comparison.get("iteration_lineage") != expected_lineage
                or len(completed_calls) != 2
                or hypothesis_call is None
                or critique_call is None
                or hypothesis_call["run_id"] != run["run_id"]
                or critique_call["run_id"] != run["run_id"]
                or hypothesis_call["market_date"] != run["market_date"]
                or critique_call["market_date"] != run["market_date"]
                or hypothesis_call["call_kind"] != "hypothesis_iteration"
                or critique_call["call_kind"] != "critique"
                or hypothesis_call["status"] != "completed"
                or critique_call["status"] != "completed"
                or hypothesis_call["failure_code"] is not None
                or critique_call["failure_code"] is not None
            ):
                raise ShadowResearchRejected(
                    "timeout_resume_completed_iteration_evidence_invalid"
                )
            candidates.append(candidate)
            drafts.append(draft)
            previous_iteration = {
                "hypotheses": {"session_id": candidate["session_id"]},
                "draft": draft,
                "candidate": candidate,
            }
            evidence_iterations.append(
                {
                    "iteration_number": expected_iteration,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_fingerprint": content_fingerprint(
                        {
                            "candidate_id": candidate["candidate_id"],
                            "session_id": candidate["session_id"],
                            "draft_id": candidate["draft_id"],
                            "backtest_run_id": candidate["backtest_run_id"],
                            "critique_id": candidate["critique_id"],
                            "candidate_result_id": candidate["candidate_result_id"],
                            "status": candidate["status"],
                            "recommendation": candidate["recommendation"],
                            "comparison": comparison,
                        }
                    ),
                    "session_request_fingerprint": row["session_request_fingerprint"],
                    "session_request_json_fingerprint": content_fingerprint(
                        session_request
                    ),
                    "session_selection_fingerprint": row[
                        "session_selection_fingerprint"
                    ],
                    "draft_artifact_fingerprint": row["draft_artifact_fingerprint"],
                    "backtest_evidence_fingerprint": row[
                        "backtest_evidence_fingerprint"
                    ],
                    "critique_artifact_fingerprint": row[
                        "critique_artifact_fingerprint"
                    ],
                    "provider_calls": completed_call_evidence,
                }
            )
        checkpoint_core = {
            "run_id": run["run_id"],
            "input_fingerprint": run["input_fingerprint"],
            "baseline_result_id": run.get("baseline_result_id"),
            "completed_iterations": evidence_iterations,
            "resume_iteration": _TIMEOUT_RESUME_ITERATION,
        }
        return {
            "completed_evidence_fingerprint": content_fingerprint(checkpoint_core),
            "completed_iteration_count": len(candidates),
            "resume_iteration": _TIMEOUT_RESUME_ITERATION,
            "candidates": candidates,
            "drafts": drafts,
            "previous_iteration": previous_iteration,
        }

    def _unconsumed_citation_call_extension(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> sqlite3.Row | None:
        if (
            run.get("status") != "failed"
            or run.get("failure_code") not in _CITATION_CONTRACT_RETRYABLE_FAILURE_CODES
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
            or run.get("failure_code") not in _OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES
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

    def _can_rearm_provider_free_failure(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> bool:
        if (
            run.get("status") != "failed"
            or str(run.get("failure_code") or "")
            not in _PROVIDER_FREE_RETRYABLE_FAILURE_CODES
            or int(run.get("candidate_count") or 0) != 0
        ):
            return False
        candidate = conn.execute(
            "SELECT 1 FROM ai_shadow_research_candidates WHERE run_id=? LIMIT 1",
            (run["run_id"],),
        ).fetchone()
        if candidate is not None:
            return False
        placeholders = ", ".join("?" for _ in _PROVIDER_FREE_RETRYABLE_FAILURE_CODES)
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
            (run["run_id"], *_PROVIDER_FREE_RETRYABLE_FAILURE_CODES),
        ).fetchone()
        return contacted is None

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
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_shadow_research_provider_calls WHERE call_id=?",
                (call_id,),
            ).fetchone()
            if existing is not None:
                return dict(existing), True
            provider_calls = self._real_provider_call_count(conn, market_date)
            authorized_ceiling = conn.execute(
                """
                SELECT authorization.provider_call_ceiling
                FROM ai_shadow_research_retry_consumptions AS consumption
                JOIN ai_shadow_research_retry_authorizations AS authorization
                  ON authorization.authorization_id=consumption.authorization_id
                WHERE consumption.replacement_run_id=?
                  AND authorization.market_date=?
                """,
                (run_id, market_date),
            ).fetchone()
            extension_ceiling = conn.execute(
                """
                SELECT extension.provider_call_ceiling
                FROM ai_shadow_research_citation_call_extension_consumptions AS consumption
                JOIN ai_shadow_research_citation_call_extensions AS extension
                  ON extension.extension_id=consumption.extension_id
                WHERE consumption.replacement_run_id=?
                  AND extension.market_date=?
                """,
                (run_id, market_date),
            ).fetchone()
            output_truncation_extension_ceiling = conn.execute(
                """
                SELECT extension.provider_call_ceiling
                FROM ai_shadow_research_output_truncation_call_extension_consumptions
                     AS consumption
                JOIN ai_shadow_research_output_truncation_call_extensions AS extension
                  ON extension.extension_id=consumption.extension_id
                WHERE consumption.replacement_run_id=?
                  AND extension.market_date=?
                """,
                (run_id, market_date),
            ).fetchone()
            timeout_resume_extension_ceiling = conn.execute(
                """
                SELECT extension.provider_call_ceiling
                FROM ai_shadow_research_timeout_resume_call_extension_consumptions
                     AS consumption
                JOIN ai_shadow_research_timeout_resume_call_extensions AS extension
                  ON extension.extension_id=consumption.extension_id
                WHERE consumption.resumed_run_id=?
                  AND extension.market_date=?
                """,
                (run_id, market_date),
            ).fetchone()
            effective_call_limit = max(
                call_limit,
                (
                    int(authorized_ceiling["provider_call_ceiling"])
                    if authorized_ceiling is not None
                    else call_limit
                ),
                (
                    int(extension_ceiling["provider_call_ceiling"])
                    if extension_ceiling is not None
                    else call_limit
                ),
                (
                    int(output_truncation_extension_ceiling["provider_call_ceiling"])
                    if output_truncation_extension_ceiling is not None
                    else call_limit
                ),
                (
                    int(timeout_resume_extension_ceiling["provider_call_ceiling"])
                    if timeout_resume_extension_ceiling is not None
                    else call_limit
                ),
            )
            if provider_calls >= effective_call_limit:
                raise ShadowResearchRejected("daily_provider_call_limit_reached")
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

    def _real_provider_call_count(
        self,
        conn: sqlite3.Connection,
        market_date: str,
    ) -> int:
        totals = conn.execute(
            f"""
            SELECT COUNT(*) AS calls
            FROM ai_shadow_research_provider_calls
            WHERE market_date=? AND NOT (
                status='failed'
                AND COALESCE(actual_tokens, 0)=0
                AND failure_code IN ({", ".join("?" for _ in _PROVIDER_FREE_RETRYABLE_FAILURE_CODES)})
            )
            """,
            (market_date, *_PROVIDER_FREE_RETRYABLE_FAILURE_CODES),
        ).fetchone()
        return int(totals["calls"])

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
                "recorded_call_attempts": 0,
                "provider_free_rejections": 0,
                "reserved_tokens": 0,
                "actual_tokens": 0,
                "retry_authorization_id": None,
                "retry_authorization_consumed": False,
                "authorized_additional_calls": 0,
                "authorized_provider_call_ceiling": None,
                "retry_replacement_run_id": None,
                "citation_call_extension_id": None,
                "citation_call_extension_consumed": False,
                "citation_authorized_additional_calls": 0,
                "citation_extension_replacement_run_id": None,
                "output_truncation_call_extension_id": None,
                "output_truncation_call_extension_consumed": False,
                "output_truncation_authorized_additional_calls": 0,
                "output_truncation_extension_replacement_run_id": None,
                "timeout_resume_call_extension_id": None,
                "timeout_resume_call_extension_consumed": False,
                "timeout_resume_authorized_additional_calls": 0,
                "timeout_resume_resumed_run_id": None,
                "timeout_resume_iteration": None,
            }
        try:
            with self._connect_readonly() as conn:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS recorded_calls,
                           COALESCE(SUM(CASE WHEN NOT (
                               status='failed'
                               AND COALESCE(actual_tokens, 0)=0
                               AND failure_code IN ({", ".join("?" for _ in _PROVIDER_FREE_RETRYABLE_FAILURE_CODES)})
                           ) THEN 1 ELSE 0 END), 0) AS calls,
                           COALESCE(SUM(CASE WHEN NOT (
                               status='failed'
                               AND COALESCE(actual_tokens, 0)=0
                               AND failure_code IN ({", ".join("?" for _ in _PROVIDER_FREE_RETRYABLE_FAILURE_CODES)})
                           ) THEN reserved_tokens ELSE 0 END), 0) AS reserved,
                           COALESCE(SUM(actual_tokens), 0) AS actual
                    FROM ai_shadow_research_provider_calls WHERE market_date=?
                    """,
                    (
                        *_PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
                        *_PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
                        market_date,
                    ),
                ).fetchone()
                authorization = conn.execute(
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
                extension = conn.execute(
                    """
                    SELECT extension.extension_id,
                           extension.authorized_additional_calls,
                           extension.provider_call_ceiling,
                           consumption.replacement_run_id
                    FROM ai_shadow_research_citation_call_extensions AS extension
                    LEFT JOIN ai_shadow_research_citation_call_extension_consumptions AS consumption
                      ON consumption.extension_id=extension.extension_id
                    WHERE extension.market_date=?
                    """,
                    (market_date,),
                ).fetchone()
                output_truncation_extension = conn.execute(
                    """
                    SELECT extension.extension_id,
                           extension.authorized_additional_calls,
                           extension.provider_call_ceiling,
                           consumption.replacement_run_id
                    FROM ai_shadow_research_output_truncation_call_extensions
                         AS extension
                    LEFT JOIN ai_shadow_research_output_truncation_call_extension_consumptions
                         AS consumption
                      ON consumption.extension_id=extension.extension_id
                    WHERE extension.market_date=?
                    """,
                    (market_date,),
                ).fetchone()
                timeout_resume_extension = conn.execute(
                    """
                    SELECT extension.extension_id,
                           extension.authorized_additional_calls,
                           extension.provider_call_ceiling,
                           extension.resume_iteration,
                           consumption.resumed_run_id
                    FROM ai_shadow_research_timeout_resume_call_extensions
                         AS extension
                    LEFT JOIN ai_shadow_research_timeout_resume_call_extension_consumptions
                         AS consumption
                      ON consumption.extension_id=extension.extension_id
                    WHERE extension.market_date=?
                    """,
                    (market_date,),
                ).fetchone()
        except sqlite3.OperationalError:
            return {
                "market_date": market_date,
                "provider_calls": 0,
                "recorded_call_attempts": 0,
                "provider_free_rejections": 0,
                "reserved_tokens": 0,
                "actual_tokens": 0,
                "retry_authorization_id": None,
                "retry_authorization_consumed": False,
                "authorized_additional_calls": 0,
                "authorized_provider_call_ceiling": None,
                "retry_replacement_run_id": None,
                "citation_call_extension_id": None,
                "citation_call_extension_consumed": False,
                "citation_authorized_additional_calls": 0,
                "citation_extension_replacement_run_id": None,
                "output_truncation_call_extension_id": None,
                "output_truncation_call_extension_consumed": False,
                "output_truncation_authorized_additional_calls": 0,
                "output_truncation_extension_replacement_run_id": None,
                "timeout_resume_call_extension_id": None,
                "timeout_resume_call_extension_consumed": False,
                "timeout_resume_authorized_additional_calls": 0,
                "timeout_resume_resumed_run_id": None,
                "timeout_resume_iteration": None,
            }
        return {
            "market_date": market_date,
            "provider_calls": int(row["calls"]),
            "recorded_call_attempts": int(row["recorded_calls"]),
            "provider_free_rejections": int(row["recorded_calls"]) - int(row["calls"]),
            "reserved_tokens": int(row["reserved"]),
            "actual_tokens": int(row["actual"]),
            "retry_authorization_id": (
                authorization["authorization_id"] if authorization is not None else None
            ),
            "retry_authorization_consumed": bool(
                authorization is not None
                and authorization["replacement_run_id"] is not None
            ),
            "authorized_additional_calls": (
                (
                    int(authorization["authorized_additional_calls"])
                    if authorization is not None
                    else 0
                )
                + (
                    int(extension["authorized_additional_calls"])
                    if extension is not None
                    else 0
                )
                + (
                    int(output_truncation_extension["authorized_additional_calls"])
                    if output_truncation_extension is not None
                    else 0
                )
                + (
                    int(timeout_resume_extension["authorized_additional_calls"])
                    if timeout_resume_extension is not None
                    else 0
                )
            ),
            "authorized_provider_call_ceiling": (
                int(timeout_resume_extension["provider_call_ceiling"])
                if timeout_resume_extension is not None
                else (
                    int(output_truncation_extension["provider_call_ceiling"])
                    if output_truncation_extension is not None
                    else (
                        int(extension["provider_call_ceiling"])
                        if extension is not None
                        else (
                            int(authorization["provider_call_ceiling"])
                            if authorization is not None
                            else None
                        )
                    )
                )
            ),
            "retry_replacement_run_id": (
                authorization["replacement_run_id"]
                if authorization is not None
                else None
            ),
            "citation_call_extension_id": (
                extension["extension_id"] if extension is not None else None
            ),
            "citation_call_extension_consumed": bool(
                extension is not None and extension["replacement_run_id"] is not None
            ),
            "citation_authorized_additional_calls": (
                int(extension["authorized_additional_calls"])
                if extension is not None
                else 0
            ),
            "citation_extension_replacement_run_id": (
                extension["replacement_run_id"] if extension is not None else None
            ),
            "output_truncation_call_extension_id": (
                output_truncation_extension["extension_id"]
                if output_truncation_extension is not None
                else None
            ),
            "output_truncation_call_extension_consumed": bool(
                output_truncation_extension is not None
                and output_truncation_extension["replacement_run_id"] is not None
            ),
            "output_truncation_authorized_additional_calls": (
                int(output_truncation_extension["authorized_additional_calls"])
                if output_truncation_extension is not None
                else 0
            ),
            "output_truncation_extension_replacement_run_id": (
                output_truncation_extension["replacement_run_id"]
                if output_truncation_extension is not None
                else None
            ),
            "timeout_resume_call_extension_id": (
                timeout_resume_extension["extension_id"]
                if timeout_resume_extension is not None
                else None
            ),
            "timeout_resume_call_extension_consumed": bool(
                timeout_resume_extension is not None
                and timeout_resume_extension["resumed_run_id"] is not None
            ),
            "timeout_resume_authorized_additional_calls": (
                int(timeout_resume_extension["authorized_additional_calls"])
                if timeout_resume_extension is not None
                else 0
            ),
            "timeout_resume_resumed_run_id": (
                timeout_resume_extension["resumed_run_id"]
                if timeout_resume_extension is not None
                else None
            ),
            "timeout_resume_iteration": (
                int(timeout_resume_extension["resume_iteration"])
                if timeout_resume_extension is not None
                else None
            ),
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
        daily_artifact_store: DailyStrategyArtifactStore | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._state = state
        self._db = state.db
        self._store = store
        self._data_store = data_store
        self._research_service_builder = research_service_builder
        self._reviewed_fee_schedule_resolver = reviewed_fee_schedule_resolver
        self._daily_artifacts = daily_artifact_store or DailyStrategyArtifactStore(
            db_path=Path(self._db._path),
            backup_root=Path(store._path).parent / "strategy-research-backups",
        )
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get_policy(self) -> ShadowResearchPolicy:
        stored = self._db.get_automation_policy_sync(SHADOW_RESEARCH_POLICY_ID)
        return ShadowResearchPolicy.from_mapping(stored)

    def update_policy(self, patch: Mapping[str, Any]) -> dict[str, Any]:
        current = self.get_policy().to_dict()
        merged = {**current, **dict(patch)}
        merged["token_budget_mode"] = (
            SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED
            if merged.get("daily_token_budget") is None
            else SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED
        )
        enabled = bool(merged.get("enabled", False))
        confirmation = str(merged.pop("confirmation", "") or "")
        if enabled:
            if merged.get("daily_token_budget") is not None:
                raise ShadowResearchRejected(
                    "enabled_shadow_research_requires_unbounded_daily_token_policy"
                )
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
        daily_selections = self._daily_artifacts.list_selections(limit=20)
        daily_backups = self._daily_artifacts.list_backups(limit=20)
        latest_market_date = runs[0]["market_date"] if runs else None
        kill_switch = self._kill_switch()
        latest_selection = daily_selections[0] if daily_selections else None
        latest_backup = daily_backups[0] if daily_backups else None
        daily_winner_candidate_id = None
        if (
            latest_selection
            and latest_backup
            and latest_selection.get("integrity_status") == "verified"
            and latest_selection.get("status") == "winner_selected"
            and latest_backup.get("verification_status") == "verified"
            and latest_backup.get("run_id") == latest_selection.get("run_id")
        ):
            daily_winner_candidate_id = latest_selection.get("winner_candidate_id")
        research_outcome = {
            "status": (
                "new_candidate_available_for_human_review"
                if daily_winner_candidate_id
                else "no_new_candidate_current_strategy_unchanged"
            ),
            "new_candidate_winner_id": daily_winner_candidate_id,
            "incumbent_strategy_policy": (
                "leave_current_human_approved_strategy_unchanged"
            ),
            "incumbent_strategy_state_changed": False,
            "daily_trading_decision_status": "not_evaluated",
            "implies_daily_trading_no_action": False,
        }
        return {
            "schema_version": SHADOW_RESEARCH_API_SCHEMA,
            "policy": policy.to_dict(),
            "kill_switch": kill_switch,
            "usage": self._store.usage_for_market_date(latest_market_date),
            "runs": runs,
            "candidates": candidates,
            "daily_selections": daily_selections,
            "daily_backups": daily_backups,
            "daily_new_candidate_winner_id": daily_winner_candidate_id,
            "daily_winner_candidate_id": daily_winner_candidate_id,
            "research_outcome": research_outcome,
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "human_paper_shadow_approval_required": True,
            "authority_effect": "research_only",
        }

    def authorize_retry(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        return self._store.authorize_retry(
            failed_run_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    def authorize_timeout_resume_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        return self._store.authorize_timeout_resume_call_extension(
            failed_run_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    def authorize_output_truncation_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        return self._store.authorize_output_truncation_call_extension(
            failed_run_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    def authorize_citation_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        return self._store.authorize_citation_call_extension(
            failed_run_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        candidate = self._store.get_candidate(candidate_id)
        daily_artifacts = self._daily_artifacts.require_verified_winner(
            candidate_id=candidate_id,
            run_id=str(candidate.get("run_id") or ""),
        )
        daily_strategy_artifact_binding = build_daily_strategy_promotion_binding(
            daily_artifacts
        )
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
            "daily_strategy_artifact_binding": daily_strategy_artifact_binding,
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
            current_readiness = promotion_state.get("payload", {}).get("readiness")
            current_readiness = (
                current_readiness if isinstance(current_readiness, dict) else {}
            )
            if (
                current_readiness.get("daily_strategy_artifact_binding")
                != daily_strategy_artifact_binding
            ):
                raise ShadowResearchRejected(
                    "canonical_paper_shadow_daily_artifact_binding_conflict"
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
            "daily_selection": daily_artifacts["selection"],
            "daily_backup": daily_artifacts["backup"],
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
        if (
            policy.max_candidates_per_run != SHADOW_RESEARCH_MAX_CANDIDATES
            or policy.max_provider_calls_per_market_date
            != SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            or policy.daily_token_budget is not None
        ):
            return self._record_preflight(
                status="blocked_by_policy",
                failure_code=(
                    "unbounded_daily_token_policy_not_authorized"
                    if policy.daily_token_budget is not None
                    else "five_sequential_iterations_not_authorized"
                ),
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
                "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
                "policy": policy.to_dict(),
                "baseline_fingerprint": prepared.fingerprint,
                "valuation_snapshot_id": valuation["snapshot_id"],
                "ledger_cutoff_id": valuation["ledger_cutoff_id"],
            }
        )
        selection_components = {
            "universe": tuple(
                asset["symbol"] for asset in prepared.request.assets or []
            ),
            "asset_classes": tuple(
                asset["asset_class"] for asset in prepared.request.assets or []
            ),
            "dataset_snapshot_id": str(prepared.snapshot["snapshot_id"]),
            "start_date": prepared.request.start_date,
            "end_date": prepared.request.end_date,
            "frequency": BarFrequency.DAILY.value,
            "initial_cash": prepared.request.initial_cash,
            "cost_model_reference": prepared.cost_model_reference,
            "account_truth_freshness_as_of": _frozen_market_close_as_of(
                prepared.market_date,
                policy.after_close_time,
            ).isoformat(),
            "valuation_snapshot_id": str(valuation["snapshot_id"]),
            "ledger_cutoff_id": int(valuation["ledger_cutoff_id"]),
        }
        now_text = self._now().astimezone(timezone.utc).isoformat()
        run, reused = self._store.claim_run(
            market_date=prepared.market_date,
            input_fingerprint=input_fingerprint,
            baseline_seed_result_id=prepared.seed_result_id,
            valuation_snapshot_id=str(valuation["snapshot_id"]),
            ledger_cutoff_id=int(valuation["ledger_cutoff_id"]),
            now=now_text,
            timeout_resume_input_evidence={
                "baseline_fingerprint": prepared.fingerprint,
                "requested_by": f"automation:{policy.updated_by}",
                "account_alias": "standing-owner-authorized-shadow-research",
                "research_question": policy.research_question,
                "selection_components": selection_components,
            },
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
                **selection_components,
            )
            self._require_deepseek_provider()
            research = self._build_research_service(external=True)
            local_research = self._build_research_service(external=False)
            resume_iteration = int(run.get("partial_resume_iteration") or 1)
            if resume_iteration == 1:
                candidates: list[dict[str, Any]] = []
                valid_drafts: list[dict[str, Any]] = []
                previous_iteration: dict[str, Any] | None = None
            else:
                if resume_iteration != _TIMEOUT_RESUME_ITERATION:
                    raise ShadowResearchRejected("partial_resume_iteration_invalid")
                checkpoint = self._store.load_partial_resume_checkpoint(
                    str(run["run_id"]),
                    expected_fingerprint=str(
                        run.get("partial_resume_evidence_fingerprint") or ""
                    ),
                )
                candidates = list(checkpoint["candidates"])
                valid_drafts = list(checkpoint["drafts"])
                previous_iteration = checkpoint["previous_iteration"]
                if (
                    len(candidates) != _TIMEOUT_RESUME_COMPLETED_ITERATIONS
                    or len(valid_drafts) != _TIMEOUT_RESUME_COMPLETED_ITERATIONS
                ):
                    raise ShadowResearchRejected(
                        "partial_resume_completed_iteration_count_invalid"
                    )
            for iteration_number in range(
                resume_iteration, policy.max_candidates_per_run + 1
            ):
                iteration_context = _build_iteration_context(
                    iteration_number=iteration_number,
                    total_iterations=policy.max_candidates_per_run,
                    previous_iteration=previous_iteration,
                )
                hypotheses, draft = await self._generate_iteration_hypothesis(
                    run=run,
                    policy=policy,
                    selection=selection,
                    external_research=research,
                    iteration_context=iteration_context,
                )
                run = self._store.update_run(
                    run["run_id"],
                    now=self._utc_now(),
                    session_id=hypotheses["session_id"],
                )
                candidate = await self._run_candidate(
                    run=run,
                    policy=policy,
                    hypotheses=hypotheses,
                    draft=draft,
                    iteration_context=iteration_context,
                    baseline_result_id=baseline_result_id,
                    local_research=local_research,
                    external_research=research,
                )
                if candidate.get("status") not in {
                    "awaiting_human_approval",
                    "research_blocked",
                }:
                    raise ShadowResearchRejected("sequential_iteration_not_complete")
                candidates.append(candidate)
                valid_drafts.append(dict(draft))
                previous_iteration = {
                    "hypotheses": hypotheses,
                    "draft": draft,
                    "candidate": candidate,
                }
            terminal_status = (
                "completed"
                if candidates
                and all(
                    item["status"] in {"awaiting_human_approval", "research_blocked"}
                    for item in candidates
                )
                else "partial"
            )
            daily_artifacts: dict[str, Any] | None = None
            daily_artifact_failure: str | None = None
            try:
                daily_artifacts = self._daily_artifacts.record_daily_artifacts(
                    run=run,
                    candidates=candidates,
                    drafts=valid_drafts,
                    expected_candidate_count=policy.max_candidates_per_run,
                    run_status=terminal_status,
                    created_at=self._utc_now(),
                )
            except DailyStrategyArtifactRejected as exc:
                daily_artifact_failure = _failure_code(exc)
                terminal_status = "partial"
            self._store.update_run(
                run["run_id"],
                now=self._utc_now(),
                status=terminal_status,
                candidate_count=len(candidates),
                failure_code=(
                    daily_artifact_failure
                    or (
                        None
                        if terminal_status == "completed"
                        else "candidate_stage_partial"
                    )
                ),
            )
            await self._notify(prepared.market_date, candidates, daily_artifacts)
            return {
                **self.status(),
                "run_status": terminal_status,
                "run_id": run["run_id"],
                "reused": False,
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

    async def _generate_iteration_hypothesis(
        self,
        *,
        run: Mapping[str, Any],
        policy: ShadowResearchPolicy,
        selection: StrategyResearchSelection,
        external_research: Any,
        iteration_context: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        iteration_number = int(iteration_context["iteration_number"])
        self._require_runtime_authorization(policy)
        call_id = f"{run['run_id']}:hypothesis:iteration:{iteration_number:02d}"
        resume_extension_id = str(run.get("partial_resume_extension_id") or "")
        if resume_extension_id:
            if iteration_number != _TIMEOUT_RESUME_ITERATION:
                raise ShadowResearchRejected(
                    "timeout_resume_may_only_generate_fifth_hypothesis"
                )
            call_id += (
                ":timeout-resume:"
                + content_fingerprint({"extension_id": resume_extension_id})[:12]
            )
        _, call_reused = self._store.claim_provider_call(
            call_id=call_id,
            run_id=str(run["run_id"]),
            market_date=str(run["market_date"]),
            call_kind="hypothesis_iteration",
            call_limit=policy.max_provider_calls_per_market_date,
            now=self._utc_now(),
        )
        if call_reused:
            raise ShadowResearchRejected(
                "iteration_hypothesis_provider_call_already_claimed"
            )
        try:
            hypotheses = await external_research.generate_hypotheses(
                HypothesisGenerationRequest(
                    idempotency_key=call_id,
                    requested_by=f"automation:{policy.updated_by}",
                    account_alias="standing-owner-authorized-shadow-research",
                    research_question=policy.research_question,
                    selection=selection,
                    confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
                    iteration_context=dict(iteration_context),
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
            status=str(hypotheses.get("status") or "failed"),
            actual_tokens=_hypothesis_usage(hypotheses),
            failure_code=hypotheses.get("failure_code"),
            now=self._utc_now(),
        )
        if hypotheses.get("status") != "completed":
            failure_code = str(hypotheses.get("failure_code") or "").strip()
            if (
                failure_code
                and len(failure_code) <= 160
                and all(char.isalnum() or char in "_:-." for char in failure_code)
            ):
                raise ShadowResearchRejected(failure_code)
            raise ShadowResearchRejected("iteration_hypothesis_generation_not_complete")
        drafts = hypotheses.get("drafts")
        if not isinstance(drafts, list) or len(drafts) != 1:
            raise ShadowResearchRejected("iteration_requires_exactly_one_draft")
        draft = drafts[0]
        if (
            not isinstance(draft, dict)
            or draft.get("validation", {}).get("status") != "valid"
        ):
            raise ShadowResearchRejected("iteration_hypothesis_not_locally_validated")
        if draft.get("iteration_context_fingerprint") != iteration_context.get(
            "context_fingerprint"
        ):
            raise ShadowResearchRejected("iteration_hypothesis_context_mismatch")
        return dict(hypotheses), dict(draft)

    async def _run_candidate(
        self,
        *,
        run: Mapping[str, Any],
        policy: ShadowResearchPolicy,
        hypotheses: Mapping[str, Any],
        draft: Mapping[str, Any],
        iteration_context: Mapping[str, Any],
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
                iteration_context=iteration_context,
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
                    "iteration_lineage": _iteration_lineage(
                        iteration_context,
                        current_formula_fingerprint=draft.get("formula_fingerprint"),
                    ),
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
        iteration_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        baseline = await self._db.get_backtest_result(baseline_result_id)
        candidate = await self._db.get_backtest_result(candidate_result_id)
        if not isinstance(baseline, dict) or not isinstance(candidate, dict):
            raise ShadowResearchRejected("comparison_backtest_missing")
        baseline_view = strategy_advancement_backtest_view(baseline)
        candidate_view = strategy_advancement_backtest_view(candidate)
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
            "iteration_lineage": _iteration_lineage(
                iteration_context,
                current_formula_fingerprint=draft.get("formula_fingerprint"),
            ),
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
            asset_class_text = str(asset.get("asset_class") or "stock").strip().lower()
            if asset_class_text != "stock":
                raise ShadowResearchRejected(
                    "daily_candidate_strategy_asset_class_not_supported"
                )
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
            account_truth_as_of=_frozen_market_close_as_of(
                market_date,
                policy.after_close_time,
            ),
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
                "drawdown_evidence": build_backtest_drawdown_evidence(
                    equity_curve=result.equity_curve,
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
        self,
        market_date: str,
        candidates: list[Mapping[str, Any]],
        daily_artifacts: Mapping[str, Any] | None,
    ) -> None:
        sender = getattr(getattr(self._state, "notifier", None), "send", None)
        if not callable(sender) or not candidates:
            return
        eligible = sum(
            item.get("recommendation") == "paper_shadow_review" for item in candidates
        )
        selection = (
            daily_artifacts.get("selection")
            if isinstance(daily_artifacts, Mapping)
            and isinstance(daily_artifacts.get("selection"), Mapping)
            else {}
        )
        backup = (
            daily_artifacts.get("backup")
            if isinstance(daily_artifacts, Mapping)
            and isinstance(daily_artifacts.get("backup"), Mapping)
            else {}
        )
        winner = selection.get("winner_candidate_id") or "无新优胜者"
        message = (
            f"DeepSeek 收盘后策略研究已完成（{market_date}）。\n"
            f"已完成串行迭代轮次: {len(candidates)}\n"
            f"建议进入人工 paper/shadow 复核: {eligible}\n"
            f"确定性新候选优胜者: {winner}\n"
            f"策略备份校验: {backup.get('verification_status') or 'missing'}\n"
            "无新优胜者只表示本批次不提出新晋级；当前已人工批准策略保持不变，"
            "当天是否交易仍由独立的 Decision、Account Truth、行情、费用与风险门决定。\n"
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


def _build_iteration_context(
    *,
    iteration_number: int,
    total_iterations: int,
    previous_iteration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    parent_iteration = None
    if iteration_number == 1:
        if previous_iteration is not None:
            raise ShadowResearchRejected("initial_iteration_parent_forbidden")
    else:
        if not isinstance(previous_iteration, Mapping):
            raise ShadowResearchRejected("sequential_iteration_parent_missing")
        hypotheses = previous_iteration.get("hypotheses")
        draft = previous_iteration.get("draft")
        candidate = previous_iteration.get("candidate")
        if not all(
            isinstance(item, Mapping) for item in (hypotheses, draft, candidate)
        ):
            raise ShadowResearchRejected("sequential_iteration_parent_invalid")
        comparison = candidate.get("comparison")
        comparison = comparison if isinstance(comparison, Mapping) else {}
        candidate_metrics = comparison.get("candidate")
        candidate_metrics = (
            candidate_metrics if isinstance(candidate_metrics, Mapping) else {}
        )
        deltas = comparison.get("deltas")
        deltas = deltas if isinstance(deltas, Mapping) else {}
        gate = comparison.get("promotion_gate")
        gate = gate if isinstance(gate, Mapping) else {}
        critique = comparison.get("deepseek_critique")
        critique = critique if isinstance(critique, Mapping) else {}
        parent_core = {
            "iteration_number": iteration_number - 1,
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "session_id": str(hypotheses.get("session_id") or ""),
            "draft_id": str(draft.get("draft_id") or ""),
            "formula_fingerprint": str(draft.get("formula_fingerprint") or ""),
            "backtest_run_id": str(candidate.get("backtest_run_id") or ""),
            "critique_id": str(candidate.get("critique_id") or ""),
            "strategy": {
                "economic_hypothesis": draft.get("economic_hypothesis"),
                "formula_ast": draft.get("formula_ast"),
                "parameter_values": draft.get("parameter_values") or {},
                "parameter_ranges": draft.get("parameter_ranges") or {},
                "risk_impact": draft.get("risk_impact"),
                "failure_conditions": list(draft.get("failure_conditions") or []),
                "limitations": list(draft.get("limitations") or []),
            },
            "evaluation": {
                "total_return": candidate_metrics.get("total_return"),
                "sharpe": candidate_metrics.get("sharpe"),
                "max_drawdown": candidate_metrics.get("max_drawdown"),
                "oos_fold_count": candidate_metrics.get("oos_fold_count"),
                "mean_oos_return": candidate_metrics.get("mean_oos_return"),
                "worst_oos_return": candidate_metrics.get("worst_oos_return"),
                "oos_validation_status": candidate_metrics.get("oos_validation_status"),
                "total_return_delta": deltas.get("total_return"),
                "sharpe_delta": deltas.get("sharpe"),
                "max_drawdown_delta": deltas.get("max_drawdown"),
                "recommendation": candidate.get("recommendation"),
                "promotion_gate_status": gate.get("status"),
                "promotion_gate_blockers": list(gate.get("blockers") or []),
                "promotion_gate_fingerprint": gate.get("evidence_fingerprint"),
            },
            "critique": {
                key: critique.get(key)
                for key in (
                    "supported_claims",
                    "contradicted_claims",
                    "evidence_gaps",
                    "cost_turnover_sensitivity",
                    "concentration_risk",
                    "sample_dependence",
                    "possible_overfitting",
                    "recommended_ablations",
                    "recommended_walk_forward_stress_tests",
                    "explicit_failure_conditions",
                    "uncertainty",
                    "citations",
                )
                if key in critique
            },
        }
        parent_iteration = {
            **parent_core,
            "parent_artifact_fingerprint": "sha256:" + content_fingerprint(parent_core),
        }
    context_core = {
        "schema_version": STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT,
        "iteration_number": iteration_number,
        "total_iterations": total_iterations,
        "parent_iteration": parent_iteration,
        "required_behavior": {
            "draft_count": 1,
            "must_change_formula_from_parent": iteration_number > 1,
            "must_use_parent_backtest_and_critique": iteration_number > 1,
            "authority_effect": "none",
        },
    }
    return {
        **context_core,
        "context_fingerprint": "sha256:" + content_fingerprint(context_core),
    }


def _iteration_lineage(
    iteration_context: Mapping[str, Any],
    *,
    current_formula_fingerprint: Any,
) -> dict[str, Any]:
    parent = iteration_context.get("parent_iteration")
    parent = parent if isinstance(parent, Mapping) else {}
    return {
        "schema_version": STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT,
        "iteration_number": iteration_context.get("iteration_number"),
        "total_iterations": iteration_context.get("total_iterations"),
        "formula_fingerprint": current_formula_fingerprint,
        "parent_candidate_id": parent.get("candidate_id"),
        "parent_draft_id": parent.get("draft_id"),
        "parent_formula_fingerprint": parent.get("formula_fingerprint"),
        "iteration_context_fingerprint": iteration_context.get("context_fingerprint"),
        "sequential_feedback_bound": bool(parent)
        or iteration_context.get("iteration_number") == 1,
    }


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


def _frozen_market_close_as_of(
    market_date: str,
    after_close_time: str,
) -> datetime:
    try:
        return datetime.combine(
            datetime.fromisoformat(market_date).date(),
            time.fromisoformat(after_close_time),
            tzinfo=_SHANGHAI_TZ,
        )
    except ValueError as exc:
        raise ShadowResearchRejected("frozen_market_close_invalid") from exc


def _asset_class(value: str) -> AssetClass:
    try:
        return AssetClass.FUND if value == "etf" else AssetClass(value)
    except ValueError as exc:
        raise ShadowResearchRejected("baseline_asset_class_invalid") from exc


def _backtest_source_fingerprint(row: Mapping[str, Any]) -> str:
    return content_fingerprint(
        {
            "id": int(row.get("id") or 0),
            "initial_cash": row.get("initial_cash"),
            "final_equity": row.get("final_equity"),
            "total_return": row.get("total_return"),
            "sharpe": row.get("sharpe"),
            "max_drawdown": row.get("max_drawdown"),
            "equity_curve": _json_list(row.get("equity_curve_json")),
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


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return list(decoded) if isinstance(decoded, list) else []


def _failure_code(exc: Exception) -> str:
    value = str(exc).strip()
    if isinstance(exc, ValueError) and value.startswith(
        "conflicting role id: external.strategy_"
    ):
        return "ai_runtime_role_identity_conflict"
    if (
        value
        and len(value) <= 160
        and all(char.isalnum() or char in "_:-." for char in value)
    ):
        return value
    return type(exc).__name__
