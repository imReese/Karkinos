from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from analytics.strategy_advancement_gate import (
    STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES,
    StrategyAdvancementGate,
)
from core.types import BarFrequency, CommissionType, InstrumentType, Symbol
from data.store import DataStore
from execution.commission import MultiAssetCommission, StockACommission
from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.formula_dsl import CANONICAL_COST_MODEL_REFERENCE
from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
    ProviderCallDeferred,
)
from server.ai_runtime.store import AiAuditStore
from server.ai_runtime.strategy_research import (
    StrategyResearchAuditStore,
    StrategyResearchSelection,
)
from server.config import AIProviderConfig, ServerConfig
from server.db import AppDatabase
from server.dependencies import AppState
from server.models import BacktestRequest
from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_ACCOUNT_BOUND_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
    SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION,
    SHADOW_RESEARCH_CORRECTED_PANEL_CITATION_RESUME_CONFIRMATION,
    SHADOW_RESEARCH_CORRECTED_PANEL_REARM_CONFIRMATION,
    SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_OUTPUT_TRUNCATION_CALL_EXTENSION_CONFIRMATION,
    SHADOW_RESEARCH_PAUSE_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION,
    SHADOW_RESEARCH_RETRY_CONFIRMATION,
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
    SHADOW_RESEARCH_TIMEOUT_RESUME_CALL_EXTENSION_CONFIRMATION,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
    AiShadowResearchAutomationService,
    PreparedBaseline,
    ShadowResearchPolicy,
    ShadowResearchRejected,
    ShadowResearchStore,
    _after_close,
    _build_iteration_context,
    _failure_code,
    _iteration_lineage,
)
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
    build_daily_strategy_promotion_binding,
    build_daily_strategy_selection,
)
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    normalize_a_share_members,
    preliminary_research_panel_symbols,
)
from server.services.reviewed_fee_schedule import ReviewedFeeScheduleRejected
from server.services.trading_controls import TradingControlState
from tests.ai_shadow_strategy_fixtures import seed_ai_shadow_canonical_sources

SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_peak_pricing_window_defers_before_any_research_or_provider_claim(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        provider_call_window_policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
        now=lambda: datetime(2026, 8, 31, 16, 0, tzinfo=SHANGHAI),
    )
    service.update_policy(_policy_payload(enabled=True))
    persisted_policy = db.get_automation_policy_sync("ai_shadow_research")
    assert persisted_policy["provider_call_window_policy_id"] == (
        "deepseek.beijing_weekday_peak.v1"
    )
    assert len(persisted_policy["provider_call_window_policy_fingerprint"]) == 64

    def unexpected_baseline(policy: ShadowResearchPolicy) -> PreparedBaseline:
        raise AssertionError("pricing admission must run before baseline preparation")

    monkeypatch.setattr(service, "_prepare_baseline", unexpected_baseline)

    result = await service.run_once()

    assert result["run_status"] == "deferred_for_provider_off_peak"
    assert result["failure_code"] == "deepseek_peak_pricing_window"
    assert result["next_eligible_at"] == "2026-08-31T18:00:00+08:00"
    assert result["provider_call_window"]["provider_call_performed"] is False
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_shadow_research_runs").fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_provider_calls"
            ).fetchone()[0]
            == 0
        )
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM automation_runs WHERE run_id=?",
                (result["preflight_run_id"],),
            ).fetchone()[0]
        )
    assert payload["provider_call_performed"] is False
    assert payload["provider_call_window"]["next_eligible_at"] == (
        "2026-08-31T18:00:00+08:00"
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_non_deepseek_builder_is_rejected_before_deepseek_window_scheduling(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    state = _state(db)
    state.config = ServerConfig(
        ai=AIProviderConfig(
            enabled=True,
            provider="openai",
            model="fixture-model",
            base_url="https://api.openai.com",
        )
    )
    service = AiShadowResearchAutomationService(
        state=state,
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: object(),
        provider_call_window_policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
        now=lambda: datetime(2026, 8, 31, 16, 0, tzinfo=SHANGHAI),
    )
    service.update_policy(_policy_payload(enabled=True))

    with pytest.raises(
        ShadowResearchRejected,
        match="deepseek_provider_not_configured",
    ):
        await service.run_once()

    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM automation_runs").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_shadow_research_runs").fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_batch_deadline_is_rechecked_after_baseline_before_any_run_claim(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    current = {
        "value": datetime(2026, 8, 31, 6, 54, tzinfo=SHANGHAI),
    }
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        provider_call_window_policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
        now=lambda: current["value"],
    )
    service.update_policy(_policy_payload(enabled=True))

    def baseline_crossing_deadline(policy: ShadowResearchPolicy) -> object:
        current["value"] = datetime(2026, 8, 31, 9, 0, tzinfo=SHANGHAI)
        return object()

    monkeypatch.setattr(service, "_prepare_baseline", baseline_crossing_deadline)

    result = await service.run_once()

    assert result["run_status"] == "deferred_for_provider_off_peak"
    assert result["next_eligible_at"] == "2026-08-31T18:00:00+08:00"
    assert result["provider_call_window"]["batch_deadline_at"] == (
        "2026-08-31T09:00:00+08:00"
    )
    assert result["provider_call_window"]["batch_deadline_missed"] is True
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_shadow_research_runs").fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_provider_calls"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_shadow_policy_confirmation_literals_match_the_operator_contract() -> None:
    assert SHADOW_RESEARCH_POLICY_CONFIRMATION == (
        "authorize_five_sequential_after_close_deepseek_normalized_notional_"
        "strategy_research_without_account_strategy_trade_or_capital_authority"
    )
    assert SHADOW_RESEARCH_ACCOUNT_BOUND_POLICY_CONFIRMATION == (
        "authorize_five_sequential_after_close_deepseek_strategy_research_without_"
        "daily_token_budget_or_strategy_or_trade_authority"
    )
    assert SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION == (
        "authorize_after_close_deepseek_strategy_research_without_strategy_or_trade_"
        "authority"
    )
    assert SHADOW_RESEARCH_PAUSE_CONFIRMATION == (
        "pause_after_close_ai_strategy_research_without_changing_trading_authority"
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_shadow_policy_persists_exact_provider_window_revision_and_rejects_drift() -> (
    None
):
    payload = ShadowResearchPolicy().to_dict()

    assert payload["schema_version"] == "karkinos.ai.shadow_research_policy.v4"
    assert payload["research_capital_mode"] == "normalized_notional"
    assert payload["require_complete_account_evidence"] is False
    assert payload["promotion_requires_complete_account_evidence"] is True
    assert payload["provider_call_window_schema"] == (
        "karkinos.ai.provider_call_window.v1"
    )
    assert payload["provider_call_window_policy_id"] == (
        "deepseek.beijing_weekday_peak.v1"
    )
    assert len(payload["provider_call_window_policy_fingerprint"]) == 64

    with pytest.raises(
        ShadowResearchRejected, match="provider_call_window_policy_drift"
    ):
        ShadowResearchPolicy.from_mapping(
            {**payload, "provider_call_window_policy_id": "deepseek.unknown.v2"}
        )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    ("daily_token_budget", "authorization", "expected_authorization"),
    [
        (
            None,
            "authorize_five_sequentialis_after_shadow_research_close_deepseek_strategy_research_without_"
            "daily_token_budget_or_strategy_or_trade_authority",
            SHADOW_RESEARCH_ACCOUNT_BOUND_POLICY_CONFIRMATION,
        ),
        (
            SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * 10,
            "authorizeis_after_shadow_research_close_deepseek_strategy_research_without_strategy_or_trade_"
            "authority",
            SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
        ),
    ],
)
def test_shadow_policy_reads_refactor_era_authorization_without_weakening_new_writes(
    daily_token_budget: int | None,
    authorization: str,
    expected_authorization: str,
) -> None:
    policy = ShadowResearchPolicy.from_mapping(
        {
            "enabled": True,
            "daily_token_budget": daily_token_budget,
            "max_provider_calls_per_market_date": 10,
            "max_candidates_per_run": 5,
            "require_complete_account_evidence": False,
            "authorization": authorization,
        }
    )

    assert policy.authorization == expected_authorization
    assert policy.research_capital_mode == SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND
    assert policy.require_complete_account_evidence is True
    assert policy.to_dict()["authorization"] == expected_authorization


def _state(db: AppDatabase) -> AppState:
    state = AppState()
    state.config = ServerConfig(
        ai=AIProviderConfig(
            enabled=True,
            provider="deepseek",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
        )
    )
    state.db = db
    state.trading_controls = TradingControlState(db=db)
    return state


@pytest.mark.unit
@pytest.mark.trading_safety
def test_service_requires_initialized_app_state_database(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="application database is not initialized"):
        AiShadowResearchAutomationService(
            state=AppState(),
            store=ShadowResearchStore(tmp_path / "app.db"),
            data_store=DataStore(tmp_path / "market"),
        )


def _policy_payload(*, enabled: bool) -> dict:
    return {
        "enabled": enabled,
        "after_close_time": "15:30",
        "max_provider_calls_per_market_date": 10,
        "daily_token_budget": None,
        "token_budget_mode": SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
        "max_candidates_per_run": 5,
        "baseline_backtest_result_id": None,
        "research_capital_mode": SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
        "require_complete_account_evidence": False,
        "research_question": "Generate one falsifiable formula improvement.",
        "updated_by": "human:owner",
        "confirmation": (
            SHADOW_RESEARCH_POLICY_CONFIRMATION
            if enabled
            else SHADOW_RESEARCH_PAUSE_CONFIRMATION
        ),
    }


def _account_bound_policy_payload(*, enabled: bool) -> dict:
    return {
        **_policy_payload(enabled=enabled),
        "research_capital_mode": SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        "require_complete_account_evidence": True,
        "confirmation": (
            SHADOW_RESEARCH_ACCOUNT_BOUND_POLICY_CONFIRMATION
            if enabled
            else SHADOW_RESEARCH_PAUSE_CONFIRMATION
        ),
    }


def _corrected_panel_rearm_evidence() -> dict:
    core = {
        "schema_version": "karkinos.ai.corrected_panel_rearm_evidence.v1",
        "market_date": "2026-08-21",
        "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
        "prepared_baseline_fingerprint": "sha256:prepared-baseline",
        "dataset_snapshot_id": "sha256:dataset",
        "market_universe_truth_schema_version": "karkinos.market_universe_truth.v2",
        "market_universe_truth_fingerprint": "sha256:truth",
        "market_universe_snapshot_id": "sha256:universe",
        "research_panel_schema_version": "karkinos.research_panel_snapshot.v2",
        "research_panel_fingerprint": "sha256:panel",
        "research_panel_member_count": 40,
        "required_trading_date_count": 154,
        "receipt_bound_history": True,
        "stock_only": True,
        "provider_contacted_during_build": False,
        "authorizes_strategy_promotion": False,
        "authorizes_order_creation": False,
        "changes_capital_authority": False,
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def _seed_completed_no_selection_for_corrected_panel_rearm(
    tmp_path,
) -> tuple[ShadowResearchStore, dict, dict]:
    db_path = tmp_path / "app.db"
    db = AppDatabase(db_path)
    db.init_sync()
    store = ShadowResearchStore(db_path)
    store.init()
    daily_artifacts = DailyStrategyArtifactStore(
        db_path, tmp_path / "strategy-research-backups"
    )
    daily_artifacts.init()
    run, reused = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint="sha256:single-stock-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-old",
        valuation_snapshot_id="valuation-old",
        ledger_cutoff_id=1,
        now="2026-08-22T00:00:00+00:00",
    )
    assert reused is False
    candidates = []
    with sqlite3.connect(db_path) as conn:
        for ordinal in range(1, 6):
            candidate = {
                "candidate_id": f"old-candidate-{ordinal}",
                "run_id": run["run_id"],
                "draft_id": f"old-draft-{ordinal}",
                "status": "research_blocked",
                "recommendation": "keep_researching",
                "comparison": {
                    "iteration_lineage": {
                        "iteration_number": ordinal,
                        "total_iterations": 5,
                    },
                    "promotion_gate": {"status": "blocked", "blockers": ["test"]},
                },
            }
            candidates.append(candidate)
            conn.execute(
                """
                INSERT INTO ai_shadow_research_candidates
                (candidate_id, run_id, session_id, draft_id, baseline_result_id,
                 status, recommendation, comparison_json, promotion_status,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, 'blocked_by_evidence', ?, ?)
                """,
                (
                    candidate["candidate_id"],
                    run["run_id"],
                    "old-session",
                    candidate["draft_id"],
                    candidate["status"],
                    candidate["recommendation"],
                    canonical_json(candidate["comparison"]),
                    "2026-08-22T00:00:00+00:00",
                    "2026-08-22T00:00:00+00:00",
                ),
            )
        selection = build_daily_strategy_selection(
            run=run,
            candidates=candidates,
            expected_candidate_count=5,
            created_at="2026-08-22T00:00:00+00:00",
        )
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
                selection["created_at"],
            ),
        )
        backup = daily_artifacts._write_backup(
            {
                "schema_version": "karkinos.ai.daily_strategy_backup.v1",
                "run_id": run["run_id"],
                "market_date": run["market_date"],
                "selection": selection,
                "candidates": candidates,
                "drafts": [],
            },
            created_at="2026-08-22T00:00:00+00:00",
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_daily_backups
            (backup_id, run_id, market_date, selection_id, relative_path,
             artifact_fingerprint, byte_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                backup["backup_id"],
                backup["run_id"],
                backup["market_date"],
                backup["selection_id"],
                backup["relative_path"],
                backup["artifact_fingerprint"],
                backup["byte_count"],
                backup["created_at"],
            ),
        )
        conn.execute("""
            INSERT INTO ai_shadow_research_timeout_resume_call_extensions
            (extension_id, failed_run_id, market_date, failed_input_fingerprint,
             failure_code, completed_iteration_count,
             completed_evidence_fingerprint, failed_call_id,
             provider_calls_at_authorization, prior_provider_call_ceiling,
             authorized_additional_calls, provider_call_ceiling,
             resume_iteration, approved_by, notes, created_at)
            VALUES ('timeout-extension', 'old-failed-run', '2026-08-21',
                    'sha256:old-failed-input', 'provider_timeout', 4,
                    'sha256:completed-four', 'old-failed-call', 12, 13, 1, 14,
                    5, 'human:owner', 'Prior bounded resume.',
                    '2026-08-22T00:00:00+00:00')
            """)
        conn.execute(
            """
            INSERT INTO ai_shadow_research_timeout_resume_call_extension_consumptions
            (extension_id, resumed_run_id, resumed_input_fingerprint,
             completed_evidence_fingerprint, consumed_at)
            VALUES ('timeout-extension', ?, ?, 'sha256:completed-four',
                    '2026-08-22T00:00:00+00:00')
            """,
            (run["run_id"], run["input_fingerprint"]),
        )
        conn.commit()
    store.update_run(
        run["run_id"],
        now="2026-08-23T00:00:00+00:00",
        status="completed",
        candidate_count=5,
    )
    for ordinal in range(14):
        call, _ = store.claim_provider_call(
            call_id=f"old-call-{ordinal}",
            run_id=run["run_id"],
            market_date="2026-08-21",
            call_kind="hypothesis_iteration" if ordinal % 2 == 0 else "critique",
            call_limit=10,
            now="2026-08-23T00:00:00+00:00",
        )
        store.finish_provider_call(
            call["call_id"],
            status="completed",
            actual_tokens=1,
            failure_code=None,
            now="2026-08-23T00:00:01+00:00",
        )
    return store, store.get_run(run["run_id"]), selection


@pytest.mark.unit
@pytest.mark.trading_safety
def test_corrected_panel_rearm_is_exactly_one_bound_ten_call_envelope(
    tmp_path,
) -> None:
    store, completed_run, selection = (
        _seed_completed_no_selection_for_corrected_panel_rearm(tmp_path)
    )
    evidence = _corrected_panel_rearm_evidence()
    authorization = store.authorize_corrected_panel_rearm(
        completed_run["run_id"],
        rearm_evidence=evidence,
        approved_by="human:owner",
        notes="Replace the legacy single-stock evidence with the frozen 40-stock panel.",
        confirmation=SHADOW_RESEARCH_CORRECTED_PANEL_REARM_CONFIRMATION,
        now="2026-08-23T01:00:00+00:00",
    )

    assert authorization["completed_selection_fingerprint"] == (
        selection["selection_fingerprint"]
    )
    assert authorization["provider_calls_at_authorization"] == 14
    assert authorization["prior_provider_call_ceiling"] == 14
    assert authorization["authorized_additional_calls"] == 10
    assert authorization["provider_call_ceiling"] == 24
    assert authorization["consumed"] is False
    assert authorization["broker_submission_enabled"] is False
    assert authorization["capital_authority_changed"] is False

    drifted = {
        **evidence,
        "research_panel_fingerprint": "sha256:drifted-panel",
    }
    drifted.pop("evidence_fingerprint")
    drifted["evidence_fingerprint"] = content_fingerprint(drifted)
    with pytest.raises(
        ShadowResearchRejected, match="corrected_panel_rearm_evidence_drift"
    ):
        store.claim_run(
            market_date="2026-08-21",
            input_fingerprint="sha256:forty-stock-input",
            baseline_seed_result_id=1,
            research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
            research_context_id="valuation-new",
            valuation_snapshot_id="valuation-new",
            ledger_cutoff_id=1,
            now="2026-08-23T01:01:00+00:00",
            corrected_panel_rearm_evidence=drifted,
        )
    assert (
        store.usage_for_market_date("2026-08-21")["corrected_panel_rearm_consumed"]
        is False
    )

    replacement, reused = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint="sha256:forty-stock-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-new",
        valuation_snapshot_id="valuation-new",
        ledger_cutoff_id=1,
        now="2026-08-23T01:02:00+00:00",
        corrected_panel_rearm_evidence=evidence,
    )
    assert reused is False
    assert replacement["run_id"] != completed_run["run_id"]

    for ordinal in range(10):
        store.claim_provider_call(
            call_id=f"corrected-call-{ordinal}",
            run_id=replacement["run_id"],
            market_date="2026-08-21",
            call_kind="hypothesis_iteration" if ordinal % 2 == 0 else "critique",
            call_limit=10,
            now="2026-08-23T01:03:00+00:00",
        )
    with pytest.raises(
        ShadowResearchRejected, match="daily_provider_call_limit_reached"
    ):
        store.claim_provider_call(
            call_id="corrected-call-over-ceiling",
            run_id=replacement["run_id"],
            market_date="2026-08-21",
            call_kind="hypothesis_iteration",
            call_limit=10,
            now="2026-08-23T01:04:00+00:00",
        )
    usage = store.usage_for_market_date("2026-08-21")
    assert usage["provider_calls"] == 24
    assert usage["authorized_provider_call_ceiling"] == 24
    assert usage["corrected_panel_rearm_consumed"] is True
    assert usage["corrected_panel_rearm_authorized_additional_calls"] == 10
    assert usage["corrected_panel_rearm_replacement_run_id"] == replacement["run_id"]


def _seed_corrected_panel_first_critique_failure(tmp_path):
    store, completed_run, _ = _seed_completed_no_selection_for_corrected_panel_rearm(
        tmp_path
    )
    StrategyResearchAuditStore(tmp_path / "app.db").init()
    evidence = _corrected_panel_rearm_evidence()
    store.authorize_corrected_panel_rearm(
        completed_run["run_id"],
        rearm_evidence=evidence,
        approved_by="human:owner",
        notes="Bind the corrected frozen 40-stock panel.",
        confirmation=SHADOW_RESEARCH_CORRECTED_PANEL_REARM_CONFIRMATION,
        now="2026-08-23T01:00:00+00:00",
    )
    run, reused = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint="sha256:forty-stock-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-new",
        valuation_snapshot_id="valuation-new",
        ledger_cutoff_id=1,
        now="2026-08-23T01:01:00+00:00",
        corrected_panel_rearm_evidence=evidence,
    )
    assert reused is False
    store.update_run(
        run["run_id"],
        now="2026-08-23T01:01:01+00:00",
        baseline_result_id=1,
    )
    run = store.get_run(run["run_id"])
    context = _build_iteration_context(
        iteration_number=1,
        total_iterations=5,
        previous_iteration=None,
    )
    hypothesis_call_id = f"{run['run_id']}:hypothesis:iteration:01"
    session_id = "session-corrected-panel-iteration-1"
    draft_id = "draft-corrected-panel-iteration-1"
    backtest_run_id = "backtest-corrected-panel-iteration-1"
    critique_call_id = f"{run['run_id']}:critique:{draft_id}"
    formula_fingerprint = "sha256:" + "1" * 64
    draft = {
        "draft_id": draft_id,
        "formula_fingerprint": formula_fingerprint,
        "iteration_context_fingerprint": context["context_fingerprint"],
        "economic_hypothesis": "Testable corrected-panel hypothesis.",
        "formula_ast": {"operator": "rank", "operand": "momentum"},
        "parameter_values": {"lookback": 20},
        "parameter_ranges": {"lookback": [10, 40]},
        "risk_impact": "Bounded research-only risk.",
        "failure_conditions": ["OOS return is non-positive."],
        "limitations": ["Daily bars only."],
    }
    now = "2026-08-23T01:02:00+00:00"
    with sqlite3.connect(tmp_path / "app.db") as conn:
        conn.execute(
            """
            INSERT INTO ai_strategy_research_sessions
            (session_id, idempotency_key, request_fingerprint, request_json,
             selection_fingerprint, status, failure_code, prompt_version,
             created_at, updated_at)
            VALUES (?, ?, 'session-request-fingerprint', ?,
                    'selection-fingerprint', 'completed', NULL, 'v-test', ?, ?)
            """,
            (
                session_id,
                hypothesis_call_id,
                canonical_json({"iteration_context": context}),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_strategy_hypothesis_drafts
            (draft_id, session_id, ordinal, contract_json,
             artifact_fingerprint, formula_fingerprint, validation_status,
             validation_errors_json, created_at)
            VALUES (?, ?, 1, ?, ?, ?, 'valid', '[]', ?)
            """,
            (
                draft_id,
                session_id,
                canonical_json(draft),
                content_fingerprint(draft),
                formula_fingerprint,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_strategy_formula_backtests
            (backtest_run_id, idempotency_key, request_fingerprint, session_id,
             draft_id, formula_fingerprint, dataset_snapshot_id,
             cost_model_reference, status, canonical_backtest_result_id,
             evidence_fingerprint, failure_code, created_at, updated_at)
            VALUES (?, ?, 'backtest-request-fingerprint', ?, ?, ?,
                    'sha256:dataset', 'reviewed-fees', 'completed', 2,
                    'backtest-evidence-fingerprint', NULL, ?, ?)
            """,
            (
                backtest_run_id,
                f"{run['run_id']}:backtest:{draft_id}",
                session_id,
                draft_id,
                formula_fingerprint,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_strategy_backtest_critiques
            (critique_id, idempotency_key, request_fingerprint, session_id,
             draft_id, backtest_run_id, status, failure_code, prompt_version,
             created_at, updated_at)
            VALUES ('failed-critique-corrected-panel', ?,
                    'critique-request-fingerprint', ?, ?, ?, 'failed',
                    'critique_citation_outside_binding', 'v-test', ?, ?)
            """,
            (critique_call_id, session_id, draft_id, backtest_run_id, now, now),
        )
        conn.commit()
    comparison = {
        "schema_version": "karkinos.ai.shadow_research_comparison.v1",
        "failure_code": "strategy_critique_not_complete",
        "iteration_lineage": _iteration_lineage(
            context, current_formula_fingerprint=formula_fingerprint
        ),
        "promotion_gate": {
            "status": "blocked",
            "blockers": ["strategy_critique_not_complete"],
        },
        "automatic_strategy_replacement_enabled": False,
        "broker_submission_enabled": False,
    }
    store.save_candidate(
        run_id=run["run_id"],
        session_id=session_id,
        draft_id=draft_id,
        backtest_run_id=backtest_run_id,
        critique_id=None,
        baseline_result_id=1,
        candidate_result_id=2,
        status="failed_closed",
        recommendation="reject",
        comparison=comparison,
        now=now,
    )
    hypothesis_call, reused = store.claim_provider_call(
        call_id=hypothesis_call_id,
        run_id=run["run_id"],
        market_date="2026-08-21",
        call_kind="hypothesis_iteration",
        call_limit=10,
        now=now,
    )
    assert reused is False
    store.finish_provider_call(
        hypothesis_call["call_id"],
        status="completed",
        actual_tokens=100,
        failure_code=None,
        now=now,
    )
    critique_call, reused = store.claim_provider_call(
        call_id=critique_call_id,
        run_id=run["run_id"],
        market_date="2026-08-21",
        call_kind="critique",
        call_limit=10,
        now=now,
    )
    assert reused is False
    store.finish_provider_call(
        critique_call["call_id"],
        status="failed",
        actual_tokens=100,
        failure_code="critique_citation_outside_binding",
        now=now,
    )
    store.update_run(
        run["run_id"],
        now=now,
        status="failed",
        candidate_count=0,
        failure_code="sequential_iteration_not_complete",
    )
    return store, store.get_run(run["run_id"]), evidence


@pytest.mark.unit
@pytest.mark.trading_safety
def test_corrected_panel_first_critique_resume_adds_one_call_and_reuses_checkpoint(
    tmp_path,
) -> None:
    store, failed_run, evidence = _seed_corrected_panel_first_critique_failure(tmp_path)
    extension = store.authorize_corrected_panel_citation_resume_extension(
        failed_run["run_id"],
        rearm_evidence=evidence,
        approved_by="human:owner",
        notes="Reuse completed iteration-one hypothesis and local backtest.",
        confirmation=SHADOW_RESEARCH_CORRECTED_PANEL_CITATION_RESUME_CONFIRMATION,
        now="2026-08-23T02:00:00+00:00",
    )

    assert extension["provider_calls_at_authorization"] == 16
    assert extension["prior_provider_call_ceiling"] == 24
    assert extension["authorized_additional_calls"] == 1
    assert extension["provider_call_ceiling"] == 25
    assert extension["resume_iteration"] == 1
    assert extension["resume_stage"] == "critique"
    assert extension["consumed"] is False
    assert extension["broker_submission_enabled"] is False
    assert extension["capital_authority_changed"] is False

    resumed, reused = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint="sha256:forty-stock-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-new",
        valuation_snapshot_id="valuation-new",
        ledger_cutoff_id=1,
        now="2026-08-23T02:01:00+00:00",
        corrected_panel_rearm_evidence=evidence,
    )
    assert reused is False
    assert resumed["run_id"] == failed_run["run_id"]
    assert resumed["partial_resume_iteration"] == 1
    assert resumed["partial_resume_stage"] == "critique"
    checkpoint = store.load_first_critique_resume_checkpoint(
        resumed["run_id"],
        expected_fingerprint=resumed["partial_resume_evidence_fingerprint"],
    )
    assert checkpoint["hypotheses"]["session_id"] == (
        "session-corrected-panel-iteration-1"
    )
    assert checkpoint["draft"]["draft_id"] == "draft-corrected-panel-iteration-1"
    assert checkpoint["completed_backtest"] == {
        "backtest_run_id": "backtest-corrected-panel-iteration-1",
        "candidate_result_id": 2,
    }

    usage = store.usage_for_market_date("2026-08-21")
    assert usage["provider_calls"] == 16
    assert usage["authorized_provider_call_ceiling"] == 25
    assert usage["authorized_additional_calls"] == 12
    assert usage["corrected_panel_citation_resume_consumed"] is True
    assert usage["corrected_panel_citation_resume_authorized_additional_calls"] == 1
    assert usage["corrected_panel_citation_resume_resumed_run_id"] == resumed["run_id"]
    assert usage["corrected_panel_citation_resume_iteration"] == 1
    assert usage["corrected_panel_citation_resume_stage"] == "critique"

    for ordinal in range(9):
        store.claim_provider_call(
            call_id=f"remaining-call-{ordinal}",
            run_id=resumed["run_id"],
            market_date="2026-08-21",
            call_kind="critique" if ordinal % 2 == 0 else "hypothesis_iteration",
            call_limit=10,
            now="2026-08-23T02:02:00+00:00",
        )
    with pytest.raises(
        ShadowResearchRejected, match="daily_provider_call_limit_reached"
    ):
        store.claim_provider_call(
            call_id="call-over-25",
            run_id=resumed["run_id"],
            market_date="2026-08-21",
            call_kind="critique",
            call_limit=10,
            now="2026-08-23T02:03:00+00:00",
        )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_corrected_panel_resume_runs_only_failed_critique_then_four_rounds(
    tmp_path, monkeypatch
) -> None:
    store, failed_run, evidence = _seed_corrected_panel_first_critique_failure(tmp_path)
    store.authorize_corrected_panel_citation_resume_extension(
        failed_run["run_id"],
        rearm_evidence=evidence,
        approved_by="human:owner",
        notes="Resume only the failed first critique, then complete rounds two to five.",
        confirmation=SHADOW_RESEARCH_CORRECTED_PANEL_CITATION_RESUME_CONFIRMATION,
        now="2026-08-23T02:00:00+00:00",
    )
    db = AppDatabase(tmp_path / "app.db")
    baseline_payload = _result(total_return=0.05, sharpe=0.6, drawdown=0.12)
    candidate_payload = _result(total_return=0.12, sharpe=1.2, drawdown=0.08)
    result_ids = []
    for payload, strategy in (
        (baseline_payload, "dual_ma"),
        (candidate_payload, "ai_formula_research"),
    ):
        result_ids.append(
            await db.save_backtest_result(
                config_json=json.dumps({"strategy": strategy}),
                initial_cash=payload["initial_cash"],
                final_equity=payload["final_equity"],
                total_return=payload["total_return"],
                sharpe=payload["sharpe"],
                max_dd=payload["max_drawdown"],
                equity_curve_json=json.dumps(payload["equity_curve"]),
                annual_return=payload["annual_return"],
                sortino=payload["sortino"],
                win_rate=payload["win_rate"],
                duration_days=payload["duration_days"],
                metrics_json=json.dumps(payload["metrics_json"]),
                cost_summary_json=json.dumps(payload["cost_summary_json"]),
            )
        )
    assert result_ids == [1, 2]
    prepared = PreparedBaseline(
        seed_result_id=1,
        market_date="2026-08-21",
        snapshot={"snapshot_id": "sha256:dataset"},
        request=BacktestRequest(
            start_date="2026-01-01",
            end_date="2026-08-21",
            initial_cash=100_000,
            strategy="dual_ma",
            assets=[{"symbol": "600000", "asset_class": "stock"}],
            oos_mode="rolling",
        ),
        result=baseline_payload,
        cost_model_reference=(
            "karkinos.backtest.reviewed_account_fee_schedule.v1:"
            f"fee_review_{'a' * 32}:{'b' * 64}"
        ),
        fee_schedule_evidence={
            "fee_schedule_review_id": "fee_review_" + "a" * 32,
            "fee_schedule_review_fingerprint": "sha256:" + "b" * 64,
        },
    )
    fixture = _FixtureResearch(candidate_result_id=2)
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        now=lambda: datetime(2026, 8, 23, 8, 0, tzinfo=ZoneInfo("UTC")),
    )
    service.update_policy(_account_bound_policy_payload(enabled=True))
    monkeypatch.setattr(service, "_prepare_baseline", lambda policy: prepared)
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation._build_corrected_panel_rearm_evidence",
        lambda current: evidence,
    )
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        lambda db, persist: {
            "snapshot_id": "valuation-new",
            "ledger_cutoff_id": 1,
            "status": "complete",
            "trade_date": "2026-08-21",
        },
    )

    result = await service.run_once()

    assert result["run_status"] == "completed"
    assert result["run_id"] == failed_run["run_id"]
    assert fixture.hypothesis_calls == 4
    assert fixture.backtest_calls == 4
    assert fixture.critique_calls == 5
    assert [
        request.iteration_context["iteration_number"]
        for request in fixture.hypothesis_requests
    ] == [2, 3, 4, 5]
    assert result["usage"]["provider_calls"] == 25
    assert result["usage"]["authorized_provider_call_ceiling"] == 25
    resumed_candidates = [
        candidate
        for candidate in result["candidates"]
        if candidate["run_id"] == failed_run["run_id"]
    ]
    assert len(resumed_candidates) == 5
    assert all(
        candidate["status"] in {"awaiting_human_approval", "research_blocked"}
        for candidate in resumed_candidates
    )


def _service(tmp_path) -> AiShadowResearchAutomationService:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    return AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_shadow_status_separates_local_call_day_from_research_market_date(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    run, _ = store.claim_run(
        market_date="2026-09-03",
        input_fingerprint="cross-calendar-call-day",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
        research_context_id="normalized-cross-calendar-call-day",
        valuation_snapshot_id=None,
        ledger_cutoff_id=0,
        now="2026-09-03T15:00:00+00:00",
    )
    for call_id, created_at in (
        ("previous-local-day", "2026-09-03T15:50:00+00:00"),
        ("current-local-day", "2026-09-03T16:10:00+00:00"),
        ("current-local-day-provider-free", "2026-09-03T17:10:00+00:00"),
    ):
        store.claim_provider_call(
            call_id=call_id,
            run_id=str(run["run_id"]),
            market_date="2026-09-03",
            call_kind="hypothesis",
            call_limit=10,
            now=created_at,
        )
        store.finish_provider_call(
            call_id,
            status=("failed" if call_id.endswith("provider-free") else "completed"),
            actual_tokens=(0 if call_id.endswith("provider-free") else 12),
            failure_code=(
                "deepseek_peak_pricing_window"
                if call_id.endswith("provider-free")
                else None
            ),
            now=created_at,
        )
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        now=lambda: datetime(2026, 9, 4, 20, 0, tzinfo=SHANGHAI),
    )

    status = service.status()

    assert status["usage"]["market_date"] == "2026-09-03"
    assert status["usage"]["provider_calls"] == 2
    assert status["today_provider_activity"] == {
        "schema_version": "karkinos.ai.provider_local_day_activity.v1",
        "local_date": "2026-09-04",
        "timezone": "Asia/Shanghai",
        "provider_calls": 1,
        "recorded_call_attempts": 2,
        "provider_free_rejections": 1,
        "last_attempt_at": "2026-09-03T17:10:00+00:00",
        "last_attempt_updated_at": "2026-09-03T17:10:00+00:00",
        "last_attempt_status": "failed",
        "last_attempt_failure_code": "deepseek_peak_pricing_window",
        "last_attempt_kind": "hypothesis",
        "last_attempt_market_date": "2026-09-03",
        "last_provider_call_at": "2026-09-03T16:10:00+00:00",
        "last_provider_call_market_date": "2026-09-03",
        "read_only": True,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "authority_effect": "none",
    }


@pytest.mark.unit
@pytest.mark.trading_safety
def test_shadow_policy_defaults_disabled_and_requires_exact_standing_authorization(
    tmp_path,
) -> None:
    service = _service(tmp_path)

    status = service.status()

    assert status["policy"]["enabled"] is False
    assert status["policy"]["daily_token_budget"] is None
    assert status["policy"]["token_budget_mode"] == "unbounded_daily"
    assert status["automatic_strategy_replacement_enabled"] is False
    assert status["broker_submission_enabled"] is False
    with pytest.raises(PermissionError, match="exact owner authorization"):
        service.update_policy({**_policy_payload(enabled=True), "confirmation": "yes"})
    with pytest.raises(PermissionError, match="exact owner authorization"):
        service.update_policy(
            {
                **_policy_payload(enabled=True),
                "confirmation": SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
            }
        )
    with pytest.raises(PermissionError, match="exact legacy authorization"):
        service.update_policy(
            {
                **_policy_payload(enabled=True),
                "daily_token_budget": SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION,
                "token_budget_mode": "legacy_bounded_daily",
            }
        )

    bounded = service.update_policy(
        {
            **_account_bound_policy_payload(enabled=True),
            "daily_token_budget": SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * 10,
            "token_budget_mode": "legacy_bounded_daily",
            "confirmation": SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
        }
    )
    assert bounded["enabled"] is True
    assert (
        bounded["daily_token_budget"] == SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * 10
    )
    assert bounded["token_budget_mode"] == "legacy_bounded_daily"

    enabled = service.update_policy(_policy_payload(enabled=True))
    assert enabled["enabled"] is True
    assert enabled["authorization_recorded"] is True

    paused = service.update_policy(_policy_payload(enabled=False))
    assert paused["enabled"] is False
    assert paused["authorization_recorded"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_shadow_status_projects_candidate_without_full_backtest_evidence(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    run, reused = service._store.claim_run(
        market_date="2026-08-26",
        input_fingerprint="status-summary-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-status-summary",
        valuation_snapshot_id="valuation-status-summary",
        ledger_cutoff_id=1,
        now="2026-08-26T08:00:00+00:00",
    )
    assert reused is False
    evidence_marker = "internal-full-backtest-evidence-must-not-reach-status"
    metric_summary = {
        "result_id": 1,
        "total_return": 0.01,
        "sharpe": 0.8,
        "max_drawdown": -0.03,
        "total_cost": 12.5,
        "total_commission": 10.0,
        "total_slippage": 2.5,
        "total_trades": 4,
        "gross_turnover": 4000.0,
        "oos_fold_count": 3,
        "mean_oos_return": 0.004,
        "worst_oos_return": -0.001,
        "oos_validation_status": "pass",
        "evidence_gate_status": "pass",
        "dataset_snapshot_id": "sha256:" + "a" * 64,
    }
    candidate_summary = {**metric_summary, "result_id": 2, "total_return": 0.02}
    large_series = [evidence_marker] * 512
    full_comparison = {
        "schema_version": "karkinos.ai.shadow_research_comparison.v1",
        "research_capital_mode": "account_bound",
        "account_qualification_status": "blocked",
        "economic_hypothesis": "A bounded status projection fixture.",
        "baseline": {
            **metric_summary,
            "equity_curve": large_series,
            "drawdown_evidence": {"underwater_curve": large_series},
        },
        "candidate": {
            **candidate_summary,
            "oos_validation": {"folds": large_series},
        },
        "deepseek_critique": {
            "evidence_gaps": ["More regimes are needed."],
            "citation_evidence": large_series,
        },
        "promotion_gate": {
            "status": "blocked",
            "blockers": ["fixture_blocker"],
            "checks": large_series,
        },
    }
    candidate = service._store.save_candidate(
        run_id=run["run_id"],
        session_id="session-status-summary",
        draft_id="draft-status-summary",
        backtest_run_id="backtest-status-summary",
        critique_id="critique-status-summary",
        baseline_result_id=1,
        candidate_result_id=2,
        status="research_blocked",
        recommendation="keep_researching",
        comparison=full_comparison,
        now="2026-08-26T08:00:00+00:00",
    )

    summary = service.status()["candidates"][0]
    persisted = service._store.get_candidate(candidate["candidate_id"])
    serialized_summary = canonical_json(summary)

    assert set(summary) == set(persisted)
    assert summary["comparison"]["baseline"] == metric_summary
    assert summary["comparison"]["candidate"] == candidate_summary
    assert summary["comparison"]["promotion_gate"] == {
        "status": "blocked",
        "blockers": ["fixture_blocker"],
    }
    assert evidence_marker not in serialized_summary
    assert "equity_curve" not in summary["comparison"]["baseline"]
    assert "drawdown_evidence" not in summary["comparison"]["baseline"]
    assert "oos_validation" not in summary["comparison"]["candidate"]
    assert len(serialized_summary) < 10_000
    assert persisted["comparison"]["baseline"]["equity_curve"] == large_series
    assert persisted["comparison"]["candidate"]["oos_validation"]["folds"] == (
        large_series
    )
    assert persisted["comparison"]["promotion_gate"]["checks"] == large_series


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_enabled_partial_iteration_policy_fails_before_evidence_or_provider(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path)
    service.update_policy(
        {
            **_policy_payload(enabled=True),
            "max_provider_calls_per_market_date": 2,
            "max_candidates_per_run": 1,
        }
    )

    def unexpected_baseline(policy):
        raise AssertionError("baseline preparation must not run for a partial policy")

    monkeypatch.setattr(service, "_prepare_baseline", unexpected_baseline)

    result = await service.run_once()

    assert result["run_status"] == "blocked_by_policy"
    assert result["failure_code"] == "five_sequential_iterations_not_authorized"
    with sqlite3.connect(tmp_path / "app.db") as conn:
        audit = conn.execute(
            "SELECT status, payload_json FROM automation_runs WHERE run_id=?",
            (result["preflight_run_id"],),
        ).fetchone()
        provider_calls = conn.execute(
            "SELECT COUNT(*) FROM ai_shadow_research_provider_calls"
        ).fetchone()[0]
    assert audit is not None
    assert audit[0] == "blocked_by_policy"
    assert json.loads(audit[1])["provider_call_performed"] is False
    assert provider_calls == 0


@pytest.mark.unit
def test_provider_call_claim_is_atomic_capped_and_token_unbounded(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()

    for ordinal in range(3):
        call, reused = store.claim_provider_call(
            call_id=f"call-{ordinal}",
            run_id="run-1",
            market_date="2026-08-11",
            call_kind="critique" if ordinal else "hypothesis",
            call_limit=3,
            now="2026-08-11T08:00:00+00:00",
        )
        assert reused is False
        assert call["status"] == "reserved"
        if ordinal == 0:
            store.finish_provider_call(
                call["call_id"],
                status="completed",
                actual_tokens=SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * 20,
                failure_code=None,
                now="2026-08-11T08:01:00+00:00",
            )

    replay, reused = store.claim_provider_call(
        call_id="call-2",
        run_id="run-1",
        market_date="2026-08-11",
        call_kind="critique",
        call_limit=3,
        now="2026-08-11T08:00:00+00:00",
    )
    assert reused is True
    assert replay["call_id"] == "call-2"
    with pytest.raises(ShadowResearchRejected, match="call_limit"):
        store.claim_provider_call(
            call_id="call-3",
            run_id="run-1",
            market_date="2026-08-11",
            call_kind="critique",
            call_limit=3,
            now="2026-08-11T08:00:00+00:00",
        )

    usage = store.usage_for_market_date("2026-08-11")
    assert usage["provider_calls"] == 3
    assert usage["reserved_tokens"] == SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * 3
    assert usage["actual_tokens"] == SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * 20


@pytest.mark.unit
def test_provider_call_claim_enforces_daily_token_budget(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()

    reservation = SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION
    budget = reservation * 2
    for ordinal in range(2):
        call, reused = store.claim_provider_call(
            call_id=f"budget-call-{ordinal}",
            run_id="run-1",
            market_date="2026-08-11",
            call_kind="hypothesis",
            call_limit=10,
            daily_token_budget=budget,
            now="2026-08-11T08:00:00+00:00",
        )
        assert reused is False
        assert call["status"] == "reserved"

    with pytest.raises(ShadowResearchRejected, match="daily_token_budget_exceeded"):
        store.claim_provider_call(
            call_id="budget-call-3",
            run_id="run-1",
            market_date="2026-08-11",
            call_kind="critique",
            call_limit=10,
            daily_token_budget=budget,
            now="2026-08-11T08:00:00+00:00",
        )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    "failure_code",
    [
        "research_initial_cash_exceeds_current_account_equity",
        "account_evidence_binding_mismatch",
        "ai_runtime_role_identity_conflict",
        "reviewed_fee_schedule_current_reconciliation_blocked",
    ],
)
def test_provider_free_failed_run_can_be_rearmed_after_input_correction(
    tmp_path,
    failure_code,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    first, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="first-input-fingerprint",
        baseline_seed_result_id=8,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-first",
        valuation_snapshot_id="valuation-first",
        ledger_cutoff_id=11,
        now="2026-08-11T08:00:00+00:00",
    )
    assert reused is False
    provider_call, reused = store.claim_provider_call(
        call_id=f"{first['run_id']}:hypothesis:iteration:01",
        run_id=first["run_id"],
        market_date="2026-08-11",
        call_kind="hypothesis_iteration",
        call_limit=1,
        now="2026-08-11T08:01:00+00:00",
    )
    assert reused is False
    store.finish_provider_call(
        provider_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code=failure_code,
        now="2026-08-11T08:02:00+00:00",
    )
    store.update_run(
        first["run_id"],
        now="2026-08-11T08:02:00+00:00",
        status="failed",
        failure_code=failure_code,
    )

    replacement, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="corrected-input-fingerprint",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-corrected",
        valuation_snapshot_id="valuation-corrected",
        ledger_cutoff_id=12,
        now="2026-08-11T08:03:00+00:00",
    )

    assert reused is False
    assert replacement["run_id"] != first["run_id"]
    assert replacement["status"] == "running"
    assert replacement["baseline_seed_result_id"] == 25
    assert replacement["failure_code"] is None
    replacement_call, reused = store.claim_provider_call(
        call_id=f"{replacement['run_id']}:hypothesis:iteration:01",
        run_id=replacement["run_id"],
        market_date="2026-08-11",
        call_kind="hypothesis_iteration",
        call_limit=1,
        now="2026-08-11T08:04:00+00:00",
    )
    assert reused is False
    assert replacement_call["status"] == "reserved"
    usage = store.usage_for_market_date("2026-08-11")
    assert usage["provider_calls"] == 1
    assert usage["recorded_call_attempts"] == 2
    assert usage["provider_free_rejections"] == 1
    with sqlite3.connect(tmp_path / "app.db") as conn:
        attempt = conn.execute("""
            SELECT superseded_run_id, replacement_run_id, failure_code
            FROM ai_shadow_research_run_attempts
            """).fetchone()
    assert attempt == (
        first["run_id"],
        replacement["run_id"],
        failure_code,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_local_second_iteration_failure_resumes_from_completed_first_round(
    tmp_path,
) -> None:
    db_path = tmp_path / "app.db"
    db = AppDatabase(db_path)
    db.init_sync()
    AiAuditStore(db_path).init()
    StrategyResearchAuditStore(db_path).init()
    store = ShadowResearchStore(db_path)
    store.init()
    market_date = "2026-08-21"
    now = "2026-08-23T11:00:00+00:00"
    run, reused = store.claim_run(
        market_date=market_date,
        input_fingerprint="runtime-v9-input",
        baseline_seed_result_id=8,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=12,
        now=now,
    )
    assert reused is False
    store.update_run(run["run_id"], now=now, baseline_result_id=34)
    run = store.get_run(run["run_id"])

    first_context = _build_iteration_context(
        iteration_number=1,
        total_iterations=5,
        previous_iteration=None,
    )
    session_id = "completed-session-1"
    draft_id = "completed-draft-1"
    backtest_run_id = "completed-backtest-1"
    critique_id = "completed-critique-1"
    formula_fingerprint = f"sha256:{1:064x}"
    hypothesis_call_id = f"{run['run_id']}:hypothesis:iteration:01"
    critique_call_id = (
        f"{run['run_id']}:critique:{draft_id}:corrected-panel-citation-resume:fixture"
    )
    draft = {
        "draft_id": draft_id,
        "formula_ast": {"schema_version": "fixture"},
        "formula_fingerprint": formula_fingerprint,
        "iteration_context": first_context,
        "iteration_context_fingerprint": first_context["context_fingerprint"],
        "validation": {"status": "valid", "errors": []},
    }
    critique_artifact = {
        "supported_claims": ["Persisted result."],
        "evidence_gaps": ["Continue research."],
    }
    comparison = {
        "deepseek_critique": critique_artifact,
        "iteration_lineage": _iteration_lineage(
            first_context,
            current_formula_fingerprint=formula_fingerprint,
        ),
        "promotion_gate": {
            "status": "blocked",
            "blockers": ["research_evidence_incomplete"],
        },
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ai_strategy_research_sessions
            (session_id, idempotency_key, request_fingerprint, request_json,
             selection_fingerprint, status, prompt_version, created_at, updated_at)
            VALUES (?, ?, 'request-1', ?, 'selection-1', 'completed', 'fixture', ?, ?)
            """,
            (
                session_id,
                hypothesis_call_id,
                canonical_json({"iteration_context": first_context}),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_strategy_hypothesis_drafts
            VALUES (?, ?, 1, ?, ?, ?, 'valid', '[]', ?)
            """,
            (
                draft_id,
                session_id,
                canonical_json(draft),
                content_fingerprint(draft),
                formula_fingerprint,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_strategy_formula_backtests
            (backtest_run_id, idempotency_key, request_fingerprint, session_id,
             draft_id, formula_fingerprint, dataset_snapshot_id,
             cost_model_reference, status, canonical_backtest_result_id,
             evidence_fingerprint, created_at, updated_at)
            VALUES (?, ?, 'backtest-request', ?, ?, ?, 'dataset-fixture',
                    'reviewed-fees-fixture', 'completed', 77,
                    'backtest-evidence-1', ?, ?)
            """,
            (
                backtest_run_id,
                f"{run['run_id']}:backtest:{draft_id}",
                session_id,
                draft_id,
                formula_fingerprint,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_strategy_backtest_critiques
            (critique_id, idempotency_key, request_fingerprint, session_id,
             draft_id, backtest_run_id, status, normalized_artifact_json,
             artifact_fingerprint, prompt_version, created_at, updated_at)
            VALUES (?, ?, 'critique-request', ?, ?, ?, 'completed', ?, ?,
                    'fixture', ?, ?)
            """,
            (
                critique_id,
                critique_call_id,
                session_id,
                draft_id,
                backtest_run_id,
                canonical_json(critique_artifact),
                content_fingerprint(critique_artifact),
                now,
                now,
            ),
        )
    for call_id, call_kind in (
        (hypothesis_call_id, "hypothesis_iteration"),
        (critique_call_id, "critique"),
    ):
        call, reused = store.claim_provider_call(
            call_id=call_id,
            run_id=run["run_id"],
            market_date=market_date,
            call_kind=call_kind,
            call_limit=10,
            now=now,
        )
        assert reused is False
        store.finish_provider_call(
            call["call_id"],
            status="completed",
            actual_tokens=1_000,
            failure_code=None,
            now=now,
        )
    candidate = store.save_candidate(
        run_id=run["run_id"],
        session_id=session_id,
        draft_id=draft_id,
        backtest_run_id=backtest_run_id,
        critique_id=critique_id,
        baseline_result_id=34,
        candidate_result_id=77,
        status="research_blocked",
        recommendation="keep_researching",
        comparison=comparison,
        now=now,
    )

    second_context = _build_iteration_context(
        iteration_number=2,
        total_iterations=5,
        previous_iteration={
            "hypotheses": {"session_id": session_id},
            "draft": draft,
            "candidate": candidate,
        },
    )
    failed_call_id = f"{run['run_id']}:hypothesis:iteration:02"
    failed_session_id = "failed-session-2"
    failed_workflow_id = "failed-workflow-2"
    failed_agent_run_id = "failed-agent-run-2"
    failure_response = {
        "error": "strategy_research_citation_catalog_too_large",
        "turns": [
            {
                "artifacts": [],
                "message": "Read exact local evidence.",
                "partial": False,
                "tool_requests": [
                    {"tool_name": "research_evidence.read"},
                    {"tool_name": "account_state_projection.read"},
                    {"tool_name": "formula_operator_catalog.read"},
                    {"tool_name": "strategy_research_selection.read"},
                ],
            }
        ],
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ai_strategy_research_sessions
            (session_id, idempotency_key, request_fingerprint, request_json,
             selection_fingerprint, workflow_id, status, failure_code,
             prompt_version, created_at, updated_at)
            VALUES (?, ?, 'request-2', ?, 'selection-1', ?, 'failed',
                    'strategy_research_rejected', 'fixture', ?, ?)
            """,
            (
                failed_session_id,
                failed_call_id,
                canonical_json({"iteration_context": second_context}),
                failed_workflow_id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_workflows
            (workflow_id, idempotency_key, definition_id,
             definition_fingerprint, definition_json, context_snapshot_id,
             context_fingerprint, status, current_stage_index, partial_result,
             failure_code, created_at, updated_at)
            VALUES (?, ?, 'definition', 'definition-fingerprint', '{}',
                    'context', 'context-fingerprint', 'failed', 0, 0,
                    'strategy_research_rejected', ?, ?)
            """,
            (failed_workflow_id, failed_call_id, now, now),
        )
        conn.execute(
            """
            INSERT INTO ai_agent_runs
            (run_id, workflow_id, stage_id, role_id, model_id, provider_id,
             status, request_json, request_fingerprint, response_json,
             response_fingerprint, error_code, started_at, finished_at)
            VALUES (?, ?, 'hypothesis', 'role', 'model', 'deepseek', 'failed',
                    '{}', 'agent-request', ?, ?, 'strategy_research_rejected', ?, ?)
            """,
            (
                failed_agent_run_id,
                failed_workflow_id,
                canonical_json(failure_response),
                content_fingerprint(failure_response),
                now,
                now,
            ),
        )
    failed_call, reused = store.claim_provider_call(
        call_id=failed_call_id,
        run_id=run["run_id"],
        market_date=market_date,
        call_kind="hypothesis_iteration",
        call_limit=10,
        now=now,
    )
    assert reused is False
    store.finish_provider_call(
        failed_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="strategy_research_rejected",
        now=now,
    )
    store.update_run(
        run["run_id"],
        status="failed",
        failure_code="strategy_research_rejected",
        now=now,
    )

    resumed, reused = store.claim_run(
        market_date=market_date,
        input_fingerprint="runtime-v10-input",
        baseline_seed_result_id=8,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=12,
        now="2026-08-23T11:01:00+00:00",
    )

    assert reused is False
    assert resumed["run_id"] == run["run_id"]
    assert resumed["status"] == "running"
    assert resumed["candidate_count"] == 1
    assert resumed["partial_resume_iteration"] == 2
    checkpoint = store.load_provider_free_partial_resume_checkpoint(
        resumed["run_id"],
        resume_id=resumed["provider_free_partial_resume_id"],
        expected_fingerprint=resumed["partial_resume_evidence_fingerprint"],
    )
    assert [item["candidate_id"] for item in checkpoint["candidates"]] == [
        candidate["candidate_id"]
    ]
    assert checkpoint["previous_iteration"]["draft"]["draft_id"] == draft_id
    usage = store.usage_for_market_date(market_date)
    assert usage["provider_calls"] == 2
    assert usage["recorded_call_attempts"] == 3
    assert usage["provider_free_rejections"] == 1
    assert (
        usage["provider_free_partial_resume_failure_code"]
        == "strategy_research_citation_catalog_too_large"
    )
    for ordinal in range(1, 9):
        _, reused = store.claim_provider_call(
            call_id=f"{run['run_id']}:remaining:{ordinal}",
            run_id=run["run_id"],
            market_date=market_date,
            call_kind="remaining",
            call_limit=10,
            now=now,
        )
        assert reused is False
    with pytest.raises(ShadowResearchRejected, match="call_limit"):
        store.claim_provider_call(
            call_id=f"{run['run_id']}:remaining:9",
            run_id=run["run_id"],
            market_date=market_date,
            call_kind="remaining",
            call_limit=10,
            now=now,
        )
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_provider_free_partial_resumes"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_promotions"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_owner_authorized_provider_retry_is_append_only_consumed_once_and_adds_exactly_ten_calls(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    first, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="provider-failed-input-fingerprint",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=12,
        now="2026-08-11T08:00:00+00:00",
    )
    assert reused is False
    first_call, reused = store.claim_provider_call(
        call_id=f"{first['run_id']}:hypothesis:iteration:01",
        run_id=first["run_id"],
        market_date="2026-08-11",
        call_kind="hypothesis_iteration",
        call_limit=10,
        now="2026-08-11T08:01:00+00:00",
    )
    assert reused is False
    store.finish_provider_call(
        first_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="provider_citation_not_in_bound_input",
        now="2026-08-11T08:02:00+00:00",
    )
    store.update_run(
        first["run_id"],
        status="failed",
        failure_code="iteration_hypothesis_generation_not_complete",
        now="2026-08-11T08:02:00+00:00",
    )

    unchanged, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint=first["input_fingerprint"],
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=12,
        now="2026-08-11T08:03:00+00:00",
    )
    assert reused is True
    assert unchanged["run_id"] == first["run_id"]
    with pytest.raises(PermissionError, match="exact owner confirmation"):
        store.authorize_retry(
            first["run_id"],
            approved_by="human:owner",
            notes="Retry the rejected provider response once.",
            confirmation="yes",
            now="2026-08-11T08:04:00+00:00",
        )

    authorization = store.authorize_retry(
        first["run_id"],
        approved_by="human:owner",
        notes="Retry the rejected provider response once.",
        confirmation=SHADOW_RESEARCH_RETRY_CONFIRMATION,
        now="2026-08-11T08:04:00+00:00",
    )
    replayed_authorization = store.authorize_retry(
        first["run_id"],
        approved_by="human:owner",
        notes="Retry the rejected provider response once.",
        confirmation=SHADOW_RESEARCH_RETRY_CONFIRMATION,
        now="2026-08-11T08:05:00+00:00",
    )
    assert replayed_authorization == authorization
    assert authorization["provider_calls_at_authorization"] == 1
    assert authorization["authorized_additional_calls"] == 10
    assert authorization["provider_call_ceiling"] == 11
    assert authorization["consumed"] is False
    assert authorization["authority_effect"] == "research_only"
    assert authorization["automatic_strategy_replacement_enabled"] is False
    assert authorization["broker_submission_enabled"] is False
    assert authorization["capital_authority_changed"] is False

    replacement, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint=first["input_fingerprint"],
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=12,
        now="2026-08-11T08:06:00+00:00",
    )
    assert reused is False
    assert replacement["run_id"] != first["run_id"]
    assert replacement["input_fingerprint"] != first["input_fingerprint"]
    provider_free_call, reused = store.claim_provider_call(
        call_id=f"{replacement['run_id']}:hypothesis:iteration:01",
        run_id=replacement["run_id"],
        market_date="2026-08-11",
        call_kind="hypothesis_iteration",
        call_limit=10,
        now="2026-08-11T08:07:00+00:00",
    )
    assert reused is False
    store.finish_provider_call(
        provider_free_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="reviewed_fee_schedule_current_reconciliation_blocked",
        now="2026-08-11T08:08:00+00:00",
    )
    store.update_run(
        replacement["run_id"],
        status="failed",
        failure_code="reviewed_fee_schedule_current_reconciliation_blocked",
        now="2026-08-11T08:08:00+00:00",
    )
    resumed, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="corrected-runtime-contract-input-fingerprint",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=12,
        now="2026-08-11T08:09:00+00:00",
    )
    assert reused is False
    assert resumed["run_id"] != replacement["run_id"]
    replacement = resumed
    usage = store.usage_for_market_date("2026-08-11")
    assert usage["provider_calls"] == 1
    assert usage["provider_free_rejections"] == 1
    assert usage["retry_replacement_run_id"] == replacement["run_id"]
    for ordinal in range(1, 11):
        call, reused = store.claim_provider_call(
            call_id=f"{replacement['run_id']}:authorized:{ordinal:02d}",
            run_id=replacement["run_id"],
            market_date="2026-08-11",
            call_kind="authorized_retry",
            call_limit=10,
            now=f"2026-08-11T08:{ordinal + 6:02d}:00+00:00",
        )
        assert reused is False
        assert call["status"] == "reserved"
    with pytest.raises(ShadowResearchRejected, match="call_limit"):
        store.claim_provider_call(
            call_id=f"{replacement['run_id']}:authorized:11",
            run_id=replacement["run_id"],
            market_date="2026-08-11",
            call_kind="authorized_retry",
            call_limit=10,
            now="2026-08-11T08:17:00+00:00",
        )

    usage = store.usage_for_market_date("2026-08-11")
    assert usage["provider_calls"] == 11
    assert usage["authorized_additional_calls"] == 10
    assert usage["authorized_provider_call_ceiling"] == 11
    assert usage["retry_authorization_consumed"] is True
    assert usage["retry_replacement_run_id"] == replacement["run_id"]
    consumed = store.authorize_retry(
        first["run_id"],
        approved_by="human:owner",
        notes="Retry the rejected provider response once.",
        confirmation=SHADOW_RESEARCH_RETRY_CONFIRMATION,
        now="2026-08-11T08:18:00+00:00",
    )
    assert consumed["consumed"] is True
    assert consumed["replacement_run_id"] == replacement["run_id"]
    replayed_run, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint=first["input_fingerprint"],
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=12,
        now="2026-08-11T08:19:00+00:00",
    )
    assert reused is True
    assert replayed_run["run_id"] == replacement["run_id"]
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_retry_authorizations"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_retry_consumptions"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_candidates"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_promotions"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_citation_call_extension_is_one_shot_and_restores_exact_ten_call_capacity(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    first, _ = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint="first-provider-input",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:00:00+00:00",
    )
    first_call, _ = store.claim_provider_call(
        call_id=f"{first['run_id']}:hypothesis:iteration:01",
        run_id=first["run_id"],
        market_date="2026-08-21",
        call_kind="hypothesis_iteration",
        call_limit=10,
        now="2026-08-21T14:01:00+00:00",
    )
    store.finish_provider_call(
        first_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="external_research_invalid_response",
        now="2026-08-21T14:02:00+00:00",
    )
    store.update_run(
        first["run_id"],
        status="failed",
        failure_code="external_research_invalid_response",
        now="2026-08-21T14:02:00+00:00",
    )
    store.authorize_retry(
        first["run_id"],
        approved_by="human:owner",
        notes="Authorize the complete bounded retry.",
        confirmation=SHADOW_RESEARCH_RETRY_CONFIRMATION,
        now="2026-08-21T14:03:00+00:00",
    )
    replacement, reused = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint="retry-runtime-input",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:04:00+00:00",
    )
    assert reused is False
    rejected_call, _ = store.claim_provider_call(
        call_id=f"{replacement['run_id']}:hypothesis:iteration:01",
        run_id=replacement["run_id"],
        market_date="2026-08-21",
        call_kind="hypothesis_iteration",
        call_limit=10,
        now="2026-08-21T14:05:00+00:00",
    )
    store.finish_provider_call(
        rejected_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="provider_citation_not_in_bound_input",
        now="2026-08-21T14:06:00+00:00",
    )
    store.update_run(
        replacement["run_id"],
        status="failed",
        failure_code="provider_citation_not_in_bound_input",
        now="2026-08-21T14:06:00+00:00",
    )

    with pytest.raises(PermissionError, match="exact owner confirmation"):
        store.authorize_citation_call_extension(
            replacement["run_id"],
            approved_by="human:owner",
            notes="Restore exactly one complete five-round attempt.",
            confirmation="yes",
            now="2026-08-21T14:07:00+00:00",
        )
    real_provider_call_count = store._real_provider_call_count
    monkeypatch.setattr(store, "_real_provider_call_count", lambda conn, date: 3)
    with pytest.raises(
        ShadowResearchRejected,
        match="citation_call_extension_must_restore_exact_five_round_capacity",
    ):
        store.authorize_citation_call_extension(
            replacement["run_id"],
            approved_by="human:owner",
            notes="Restore exactly one complete five-round attempt.",
            confirmation=SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION,
            now="2026-08-21T14:07:00+00:00",
        )
    monkeypatch.setattr(store, "_real_provider_call_count", real_provider_call_count)
    extension = store.authorize_citation_call_extension(
        replacement["run_id"],
        approved_by="human:owner",
        notes="Restore exactly one complete five-round attempt.",
        confirmation=SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION,
        now="2026-08-21T14:07:00+00:00",
    )
    assert extension["provider_calls_at_authorization"] == 2
    assert extension["prior_provider_call_ceiling"] == 11
    assert extension["authorized_additional_calls"] == 1
    assert extension["provider_call_ceiling"] == 12
    assert extension["consumed"] is False
    assert extension["broker_submission_enabled"] is False
    assert extension["capital_authority_changed"] is False

    unchanged, reused = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint=replacement["input_fingerprint"],
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:08:00+00:00",
    )
    assert reused is True
    assert unchanged["run_id"] == replacement["run_id"]
    resumed, reused = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint="corrected-citation-runtime-input",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:09:00+00:00",
    )
    assert reused is False
    assert resumed["run_id"] != replacement["run_id"]
    provider_free_call, reused = store.claim_provider_call(
        call_id=f"{resumed['run_id']}:provider-free-role-conflict",
        run_id=resumed["run_id"],
        market_date="2026-08-21",
        call_kind="hypothesis_iteration",
        call_limit=10,
        now="2026-08-21T14:10:00+00:00",
    )
    assert reused is False
    store.finish_provider_call(
        provider_free_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="ai_runtime_role_identity_conflict",
        now="2026-08-21T14:11:00+00:00",
    )
    store.update_run(
        resumed["run_id"],
        status="failed",
        failure_code="ai_runtime_role_identity_conflict",
        now="2026-08-21T14:11:00+00:00",
    )
    with sqlite3.connect(tmp_path / "app.db") as conn:
        conn.execute(
            """
            UPDATE ai_shadow_research_citation_call_extension_consumptions
            SET replacement_run_id=?, replacement_input_fingerprint=?
            """,
            (replacement["run_id"], replacement["input_fingerprint"]),
        )
    corrected, reused = store.claim_run(
        market_date="2026-08-21",
        input_fingerprint="corrected-role-identity-runtime-input",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:12:00+00:00",
    )
    assert reused is False
    assert corrected["run_id"] != resumed["run_id"]
    resumed = corrected
    usage = store.usage_for_market_date("2026-08-21")
    assert usage["provider_calls"] == 2
    assert usage["provider_free_rejections"] == 1
    assert usage["authorized_additional_calls"] == 11
    assert usage["authorized_provider_call_ceiling"] == 12
    assert usage["retry_replacement_run_id"] == resumed["run_id"]
    assert usage["citation_call_extension_consumed"] is True
    assert usage["citation_authorized_additional_calls"] == 1
    assert usage["citation_extension_replacement_run_id"] == resumed["run_id"]

    for ordinal in range(1, 11):
        call, reused = store.claim_provider_call(
            call_id=f"{resumed['run_id']}:remaining:{ordinal:02d}",
            run_id=resumed["run_id"],
            market_date="2026-08-21",
            call_kind="citation_contract_retry",
            call_limit=10,
            now=f"2026-08-21T14:{ordinal + 9:02d}:00+00:00",
        )
        assert reused is False
        assert call["status"] == "reserved"
    with pytest.raises(ShadowResearchRejected, match="call_limit"):
        store.claim_provider_call(
            call_id=f"{resumed['run_id']}:remaining:11",
            run_id=resumed["run_id"],
            market_date="2026-08-21",
            call_kind="citation_contract_retry",
            call_limit=10,
            now="2026-08-21T14:20:00+00:00",
        )
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_promotions"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_output_truncation_extension_restores_exact_ten_calls_at_ceiling_thirteen(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    market_date = "2026-08-21"
    first, _ = store.claim_run(
        market_date=market_date,
        input_fingerprint="first-output-contract",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:00:00+00:00",
    )
    first_call, _ = store.claim_provider_call(
        call_id=f"{first['run_id']}:hypothesis:iteration:01",
        run_id=first["run_id"],
        market_date=market_date,
        call_kind="hypothesis_iteration",
        call_limit=10,
        now="2026-08-21T14:01:00+00:00",
    )
    store.finish_provider_call(
        first_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="external_research_invalid_response",
        now="2026-08-21T14:02:00+00:00",
    )
    store.update_run(
        first["run_id"],
        status="failed",
        failure_code="external_research_invalid_response",
        now="2026-08-21T14:02:00+00:00",
    )
    store.authorize_retry(
        first["run_id"],
        approved_by="human:owner",
        notes="Authorize the complete bounded retry.",
        confirmation=SHADOW_RESEARCH_RETRY_CONFIRMATION,
        now="2026-08-21T14:03:00+00:00",
    )
    citation_failed, reused = store.claim_run(
        market_date=market_date,
        input_fingerprint="citation-contract",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:04:00+00:00",
    )
    assert reused is False
    citation_call, _ = store.claim_provider_call(
        call_id=f"{citation_failed['run_id']}:hypothesis:iteration:01",
        run_id=citation_failed["run_id"],
        market_date=market_date,
        call_kind="hypothesis_iteration",
        call_limit=10,
        now="2026-08-21T14:05:00+00:00",
    )
    store.finish_provider_call(
        citation_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="provider_citation_not_in_bound_input",
        now="2026-08-21T14:06:00+00:00",
    )
    store.update_run(
        citation_failed["run_id"],
        status="failed",
        failure_code="provider_citation_not_in_bound_input",
        now="2026-08-21T14:06:00+00:00",
    )
    store.authorize_citation_call_extension(
        citation_failed["run_id"],
        approved_by="human:owner",
        notes="Restore exactly one complete five-round attempt.",
        confirmation=SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION,
        now="2026-08-21T14:07:00+00:00",
    )
    truncated, reused = store.claim_run(
        market_date=market_date,
        input_fingerprint="thinking-enabled-contract",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:08:00+00:00",
    )
    assert reused is False
    truncated_call, _ = store.claim_provider_call(
        call_id=f"{truncated['run_id']}:hypothesis:iteration:01",
        run_id=truncated["run_id"],
        market_date=market_date,
        call_kind="hypothesis_iteration",
        call_limit=10,
        now="2026-08-21T14:09:00+00:00",
    )
    store.finish_provider_call(
        truncated_call["call_id"],
        status="failed",
        actual_tokens=12_288,
        failure_code="provider_output_truncated",
        now="2026-08-21T14:10:00+00:00",
    )
    store.update_run(
        truncated["run_id"],
        status="failed",
        failure_code="provider_output_truncated",
        now="2026-08-21T14:10:00+00:00",
    )

    with pytest.raises(PermissionError, match="exact owner confirmation"):
        store.authorize_output_truncation_call_extension(
            truncated["run_id"],
            approved_by="human:owner",
            notes="Restore one call after the bounded JSON was truncated.",
            confirmation="yes",
            now="2026-08-21T14:11:00+00:00",
        )
    extension = store.authorize_output_truncation_call_extension(
        truncated["run_id"],
        approved_by="human:owner",
        notes="Restore one call after the bounded JSON was truncated.",
        confirmation=SHADOW_RESEARCH_OUTPUT_TRUNCATION_CALL_EXTENSION_CONFIRMATION,
        now="2026-08-21T14:11:00+00:00",
    )
    assert extension["provider_calls_at_authorization"] == 3
    assert extension["prior_provider_call_ceiling"] == 12
    assert extension["authorized_additional_calls"] == 1
    assert extension["provider_call_ceiling"] == 13
    assert extension["consumed"] is False
    assert extension["broker_submission_enabled"] is False
    assert extension["capital_authority_changed"] is False

    resumed, reused = store.claim_run(
        market_date=market_date,
        input_fingerprint="thinking-disabled-contract",
        baseline_seed_result_id=25,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-complete",
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=24,
        now="2026-08-21T14:12:00+00:00",
    )
    assert reused is False
    usage = store.usage_for_market_date(market_date)
    assert usage["provider_calls"] == 3
    assert usage["authorized_additional_calls"] == 12
    assert usage["authorized_provider_call_ceiling"] == 13
    assert usage["retry_replacement_run_id"] == resumed["run_id"]
    assert usage["citation_extension_replacement_run_id"] == resumed["run_id"]
    assert usage["output_truncation_call_extension_consumed"] is True
    assert usage["output_truncation_authorized_additional_calls"] == 1
    assert usage["output_truncation_extension_replacement_run_id"] == resumed["run_id"]

    for ordinal in range(1, 11):
        call, reused = store.claim_provider_call(
            call_id=f"{resumed['run_id']}:remaining:{ordinal:02d}",
            run_id=resumed["run_id"],
            market_date=market_date,
            call_kind="output_truncation_retry",
            call_limit=10,
            now=f"2026-08-21T14:{ordinal + 12:02d}:00+00:00",
        )
        assert reused is False
        assert call["status"] == "reserved"
    with pytest.raises(ShadowResearchRejected, match="call_limit"):
        store.claim_provider_call(
            call_id=f"{resumed['run_id']}:remaining:11",
            run_id=resumed["run_id"],
            market_date=market_date,
            call_kind="output_truncation_retry",
            call_limit=10,
            now="2026-08-21T14:23:00+00:00",
        )
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_output_truncation_call_extensions"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_output_truncation_call_extension_consumptions"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_promotions"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.unit
def test_runtime_role_conflict_has_provider_free_failure_code() -> None:
    assert (
        _failure_code(
            ValueError(
                "conflicting role id: external.strategy_hypothesis_researcher.v7"
            )
        )
        == "ai_runtime_role_identity_conflict"
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_enabled_legacy_bounded_policy_is_authorized_to_run(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path)
    legacy_payload = {
        **_policy_payload(enabled=True),
        "schema_version": "karkinos.ai.shadow_research_policy.v1",
        "daily_token_budget": SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * 10,
        "authorization": SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
    }
    legacy_payload.pop("token_budget_mode")
    legacy_payload.pop("research_capital_mode")
    legacy_payload.pop("require_complete_account_evidence")
    service._db.upsert_automation_policy_sync(
        policy_id="ai_shadow_research",
        payload=legacy_payload,
        updated_by="human:owner",
    )

    called = []

    def unexpected_baseline(policy):
        called.append(policy.daily_token_budget)
        raise RuntimeError("baseline fixture unavailable")

    monkeypatch.setattr(service, "_prepare_baseline", unexpected_baseline)

    result = await service.run_once()

    # The bounded policy is now authorized: preflight lets it proceed to baseline
    # preparation (which fails with a market-evidence block, not a policy block).
    assert called == [SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * 10]
    assert result["run_status"] == "blocked_by_market_evidence"
    assert result["policy"]["token_budget_mode"] == "legacy_bounded_daily"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_export_requires_deepseek_identity_and_deepseek_endpoint(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path)
    service._research_service_builder = lambda external: object()
    service._state.config = object()

    monkeypatch.setattr(
        "server.ai_runtime.provider_connectivity.load_provider_connectivity_settings",
        lambda config: SimpleNamespace(
            enabled=True,
            provider_id="openai",
            endpoint_origin="https://api.deepseek.com/v1",
        ),
    )
    with pytest.raises(
        ShadowResearchRejected, match="deepseek_provider_not_configured"
    ):
        service._require_deepseek_provider()

    monkeypatch.setattr(
        "server.ai_runtime.provider_connectivity.load_provider_connectivity_settings",
        lambda config: SimpleNamespace(
            enabled=True,
            provider_id="deepseek",
            endpoint_origin="https://proxy.example.com/v1",
        ),
    )
    with pytest.raises(
        ShadowResearchRejected, match="deepseek_provider_not_configured"
    ):
        service._require_deepseek_provider()

    monkeypatch.setattr(
        "server.ai_runtime.provider_connectivity.load_provider_connectivity_settings",
        lambda config: SimpleNamespace(
            enabled=True,
            provider_id="deepseek",
            endpoint_origin="https://api.deepseek.com/v1",
        ),
    )
    service._require_deepseek_provider()


@pytest.mark.unit
@pytest.mark.trading_safety
def test_candidate_approval_reads_full_evidence_after_status_projection(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    canonical_sources = seed_ai_shadow_canonical_sources(
        db,
        baseline_result_id=1,
        candidate_result_id=2,
        backtest_run_id="backtest-1",
        critique_id="critique-1",
    )
    approval_evidence = {
        "equity_curve": [
            {"timestamp": index, "equity": 100_000 + index} for index in range(64)
        ]
    }
    candidate = store.save_candidate(
        run_id="run-1",
        session_id="session-1",
        draft_id="draft-1",
        backtest_run_id="backtest-1",
        critique_id="critique-1",
        baseline_result_id=1,
        candidate_result_id=2,
        status="awaiting_human_approval",
        recommendation="paper_shadow_review",
        comparison={
            **canonical_sources,
            "approval_full_evidence": approval_evidence,
        },
        now="2026-08-11T08:00:00+00:00",
    )
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
    )

    status_candidate = service.status()["candidates"][0]
    persisted_get_candidate = store.get_candidate
    approval_reads: list[dict] = []

    def observed_get_candidate(candidate_id: str) -> dict:
        full_candidate = persisted_get_candidate(candidate_id)
        approval_reads.append(full_candidate["comparison"]["approval_full_evidence"])
        return full_candidate

    assert "approval_full_evidence" not in status_candidate["comparison"]
    assert (
        persisted_get_candidate(candidate["candidate_id"])["comparison"][
            "approval_full_evidence"
        ]
        == approval_evidence
    )
    monkeypatch.setattr(store, "get_candidate", observed_get_candidate)

    promotion = store.approve_candidate(
        candidate["candidate_id"],
        approved_by="human:owner",
        notes="Reviewed the complete persisted comparison evidence.",
        confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
        now="2026-08-11T08:05:00+00:00",
    )

    assert promotion["target_stage"] == "paper_shadow"
    assert approval_reads == [approval_evidence]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_human_candidate_approval_records_paper_shadow_only(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    canonical_sources = seed_ai_shadow_canonical_sources(
        db,
        baseline_result_id=1,
        candidate_result_id=2,
        backtest_run_id="backtest-1",
        critique_id="critique-1",
    )
    candidate = store.save_candidate(
        run_id="run-1",
        session_id="session-1",
        draft_id="draft-1",
        backtest_run_id="backtest-1",
        critique_id="critique-1",
        baseline_result_id=1,
        candidate_result_id=2,
        status="awaiting_human_approval",
        recommendation="paper_shadow_review",
        comparison={
            **canonical_sources,
            "iteration_lineage": {
                "iteration_number": 1,
                "total_iterations": 1,
                "formula_fingerprint": "sha256:formula-1",
                "parent_candidate_id": None,
                "parent_draft_id": None,
                "parent_formula_fingerprint": None,
                "iteration_context_fingerprint": "sha256:iteration-1",
                "sequential_feedback_bound": True,
            },
            "automatic_strategy_replacement_enabled": False,
        },
        now="2026-08-11T08:00:00+00:00",
    )

    with pytest.raises(PermissionError, match="exact human confirmation"):
        store.approve_candidate(
            candidate["candidate_id"],
            approved_by="human:owner",
            notes="Reviewed evidence.",
            confirmation="approve",
            now="2026-08-11T08:05:00+00:00",
        )

    promotion = store.approve_candidate(
        candidate["candidate_id"],
        approved_by="human:owner",
        notes="Reviewed OOS, costs, drawdown, and DeepSeek critique.",
        confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
        now="2026-08-11T08:05:00+00:00",
    )

    assert promotion["target_stage"] == "paper_shadow"
    assert promotion["production_strategy_replaced"] is False
    assert promotion["strategy_registry_mutated"] is False
    assert promotion["broker_order_created"] is False
    assert store.get_candidate(candidate["candidate_id"])["promotion_status"] == (
        "paper_shadow_approval_recorded"
    )

    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
    )
    with pytest.raises(
        DailyStrategyArtifactRejected, match="daily_selection_or_backup_missing"
    ):
        service.approve_candidate(
            candidate["candidate_id"],
            approved_by="human:owner",
            notes="Reviewed OOS, costs, drawdown, and DeepSeek critique.",
            confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
        )
    daily_artifacts = DailyStrategyArtifactStore(
        tmp_path / "app.db", tmp_path / "strategy-research-backups"
    )
    daily_artifacts.record_daily_artifacts(
        run={
            "run_id": "run-1",
            "market_date": "2026-08-11",
            "input_fingerprint": "sha256:approval-test",
        },
        candidates=[candidate],
        drafts=[
            {
                "draft_id": "draft-1",
                "formula_ast": {"schema_version": "fixture"},
                "formula_fingerprint": "sha256:" + "f" * 64,
                "economic_hypothesis": "Reviewed fixture hypothesis.",
                "risk_impact": "Loss remains possible under the reviewed limits.",
                "failure_conditions": ["OOS excess return turns non-positive."],
                "limitations": [
                    "Historical evidence does not establish future profit."
                ],
                "anti_lookahead_assumptions": [
                    "Signals use closed persisted bars only."
                ],
                "validation": {"status": "valid", "errors": []},
            }
        ],
        expected_candidate_count=1,
        run_status="completed",
        created_at="2026-08-11T08:04:00+00:00",
    )
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        daily_artifact_store=daily_artifacts,
    )
    canonical = service.approve_candidate(
        candidate["candidate_id"],
        approved_by="human:owner",
        notes="Reviewed OOS, costs, drawdown, and DeepSeek critique.",
        confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    )
    replay = service.approve_candidate(
        candidate["candidate_id"],
        approved_by="human:owner",
        notes="Reviewed OOS, costs, drawdown, and DeepSeek critique.",
        confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    )

    assert canonical["paper_shadow_stage_recorded"] is True
    assert canonical["strategy_promotion"]["stage"] == "paper_shadow"
    assert canonical["strategy_promotion"]["live_like_enabled"] is False
    readiness = canonical["strategy_promotion"]["payload"]["readiness"]
    daily_binding = readiness["daily_strategy_artifact_binding"]
    assert daily_binding == build_daily_strategy_promotion_binding(
        {
            "selection": canonical["daily_selection"],
            "backup": canonical["daily_backup"],
            "operating_constraints": daily_binding["operating_constraints"],
        }
    )
    assert "relative_path" not in daily_binding
    assert daily_binding["contains_private_account_identifiers"] is False
    assert daily_binding["contains_broker_export_rows"] is False
    assert daily_binding["does_not_change_capital_authority"] is True
    assert canonical["strategy_registry_mutated"] is False
    assert replay["promotion_id"] == canonical["promotion_id"]
    assert store.get_candidate(candidate["candidate_id"])["promotion_status"] == (
        "paper_shadow_approved"
    )
    events = db.list_strategy_promotion_events_sync(canonical["strategy_id"])
    assert [item["event_type"] for item in events].count(
        "promoted_to_paper_shadow"
    ) == 1


@pytest.mark.unit
@pytest.mark.trading_safety
def test_daily_binding_failure_precedes_candidate_approval_write(tmp_path) -> None:
    class TrackingStore:
        approval_called = False

        def get_candidate(self, candidate_id: str) -> dict:
            return {"candidate_id": candidate_id, "run_id": "run-invalid-binding"}

        def approve_candidate(self, *args, **kwargs) -> dict:
            self.approval_called = True
            raise AssertionError("candidate approval must not run")

    class InvalidDailyArtifacts:
        def require_verified_winner(self, **kwargs) -> dict:
            return {
                "selection": {"status": "winner_selected"},
                "backup": {"verification_status": "verified"},
            }

    store = TrackingStore()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        daily_artifact_store=InvalidDailyArtifacts(),
    )

    with pytest.raises(
        DailyStrategyArtifactRejected,
        match="daily_promotion_binding_artifact_missing",
    ):
        service.approve_candidate(
            "candidate-invalid-binding",
            approved_by="human:owner",
            notes="This must not be persisted before binding validation.",
            confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
        )

    assert store.approval_called is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_human_candidate_approval_rejects_incomplete_or_drifted_gate(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    run, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="incomplete-gate-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-incomplete-gate",
        valuation_snapshot_id="valuation-incomplete-gate",
        ledger_cutoff_id=1,
        now="2026-08-11T08:00:00+00:00",
    )
    assert reused is False
    candidate = store.save_candidate(
        run_id=run["run_id"],
        session_id="session-1",
        draft_id="draft-1",
        backtest_run_id="backtest-1",
        critique_id="critique-1",
        baseline_result_id=1,
        candidate_result_id=2,
        status="awaiting_human_approval",
        recommendation="paper_shadow_review",
        comparison={
            "research_capital_mode": "account_bound",
            "account_qualification_status": "passed",
            "promotion_gate": {
                "schema_version": "karkinos.strategy_advancement_gate.v2",
                "status": "pass",
                "blockers": [],
            },
        },
        now="2026-08-11T08:00:00+00:00",
    )

    with pytest.raises(
        ShadowResearchRejected,
        match="candidate_not_eligible_for_paper_shadow",
    ):
        store.approve_candidate(
            candidate["candidate_id"],
            approved_by="human:owner",
            notes="Incomplete gate must remain blocked.",
            confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
            now="2026-08-11T08:05:00+00:00",
        )


@pytest.mark.unit
def test_after_close_gate_supports_same_day_and_catch_up_runs() -> None:
    assert not _after_close(
        "2026-08-11", datetime(2026, 8, 11, 15, 29, tzinfo=SHANGHAI), "15:30"
    )
    assert _after_close(
        "2026-08-11", datetime(2026, 8, 11, 15, 30, tzinfo=SHANGHAI), "15:30"
    )
    assert _after_close(
        "2026-08-08", datetime(2026, 8, 11, 9, 0, tzinfo=SHANGHAI), "15:30"
    )


def _metrics(*, total_return: float, sharpe: float, drawdown: float) -> dict:
    return {
        "total_return": total_return,
        "sharpe": sharpe,
        "max_drawdown": drawdown,
        "evidence_bundle": {"total_cost": 10.0, "fill_count": 2},
        "dataset_snapshot": {"snapshot_id": "sha256:latest-market"},
        "oos_validation": {
            "validation_status": "benchmark_not_supplied",
            "fold_count": 2,
            "aggregate": {
                "mean_out_of_sample_return": total_return / 2,
                "worst_out_of_sample_return": total_return / 4,
            },
        },
        "research_evidence_bundle": {"gate_status": "pass"},
    }


def _result(
    *,
    total_return: float,
    sharpe: float,
    drawdown: float,
    initial_cash: float = 100_000.0,
) -> dict:
    return {
        "initial_cash": initial_cash,
        "final_equity": initial_cash * (1 + total_return),
        "total_return": total_return,
        "annual_return": total_return,
        "sharpe": sharpe,
        "sortino": sharpe,
        "max_drawdown": drawdown,
        "win_rate": 0.5,
        "duration_days": 100,
        "equity_curve": [
            {"timestamp": "2026-01-01T00:00:00", "equity": initial_cash},
            {
                "timestamp": "2026-08-11T00:00:00",
                "equity": initial_cash * (1 + total_return),
            },
        ],
        "metrics_json": _metrics(
            total_return=total_return, sharpe=sharpe, drawdown=drawdown
        ),
        "cost_summary_json": {
            "total_commission": 8.0,
            "total_slippage": 2.0,
            "total_trades": 2,
            "gross_turnover": 20_000.0,
        },
    }


def _prepared_baseline(*, account_bound: bool = False) -> PreparedBaseline:
    cost_model_reference = (
        (
            "karkinos.backtest.reviewed_account_fee_schedule.v1:"
            f"fee_review_{'a' * 32}:{'b' * 64}"
        )
        if account_bound
        else CANONICAL_COST_MODEL_REFERENCE
    )
    initial_cash = 100_000 if account_bound else 1_000_000
    result = _result(total_return=0.05, sharpe=0.6, drawdown=0.12)
    if not account_bound:
        result["initial_cash"] = initial_cash
        result["final_equity"] = initial_cash * 1.05
        result["equity_curve"] = [
            {**point, "equity": initial_cash * (1.05 if index else 1.0)}
            for index, point in enumerate(result["equity_curve"])
        ]
    return PreparedBaseline(
        seed_result_id=7,
        market_date="2026-08-11",
        snapshot={"snapshot_id": "sha256:latest-market"},
        request=BacktestRequest(
            start_date="2026-01-01",
            end_date="2026-08-11",
            initial_cash=initial_cash,
            strategy="dual_ma",
            assets=[{"symbol": "510300", "asset_class": "etf"}],
            oos_mode="rolling",
        ),
        result=result,
        cost_model_reference=cost_model_reference,
        fee_schedule_evidence=(
            {
                "fee_schedule_review_id": "fee_review_" + "a" * 32,
                "fee_schedule_review_fingerprint": "sha256:" + "b" * 64,
                "account_specific": True,
            }
            if account_bound
            else {
                "cost_model_reference": CANONICAL_COST_MODEL_REFERENCE,
                "fee_schedule_source": "canonical_default_estimate",
                "account_specific": False,
            }
        ),
    )


def _complete_valuation(db, persist):
    return {
        "snapshot_id": "valuation-latest",
        "ledger_cutoff_id": 11,
        "status": "complete",
        "trade_date": "2026-08-11",
    }


class _FixtureResearch:
    def __init__(self, candidate_result_id: int) -> None:
        self.candidate_result_id = candidate_result_id
        self.hypothesis_calls = 0
        self.hypothesis_requests = []
        self.backtest_calls = 0
        self.critique_calls = 0

    async def generate_hypotheses(self, request):
        self.hypothesis_calls += 1
        self.hypothesis_requests.append(request)
        ordinal = self.hypothesis_calls
        iteration_context = dict(request.iteration_context or {})
        return {
            "session_id": f"session-auto-{ordinal}",
            "status": "completed",
            "failure_code": None,
            "drafts": [
                {
                    "draft_id": f"draft-auto-{ordinal}",
                    "economic_hypothesis": "A slower trend filter reduces drawdown.",
                    "risk_impact": "Lower churn, but delayed exits remain possible.",
                    "failure_conditions": ["OOS drawdown exceeds baseline"],
                    "limitations": ["Historical evidence only"],
                    "formula_ast": {"schema_version": "fixture"},
                    "formula_fingerprint": f"sha256:{ordinal:064x}",
                    "iteration_context": iteration_context,
                    "iteration_context_fingerprint": iteration_context.get(
                        "context_fingerprint"
                    ),
                    "validation": {"status": "valid", "errors": []},
                    "provider_provenance": {"usage": {"total_tokens": 1000}},
                }
            ],
        }

    async def run_formula_backtest(self, request):
        self.backtest_calls += 1
        return {
            "status": "completed",
            "backtest_run_id": f"formula-{request.draft_id}",
            "canonical_backtest": {"result_id": self.candidate_result_id},
        }

    async def critique(self, request):
        self.critique_calls += 1
        return {
            "status": "completed",
            "failure_code": None,
            "critique_id": f"critique-{request.draft_id}",
            "artifact": {
                "supported_claims": ["Drawdown improved in the frozen run."],
                "evidence_gaps": ["More regimes are needed."],
                "provider_provenance": {"usage": {"total_tokens": 900}},
            },
        }


def _seed_four_round_timeout_resume_state(
    *,
    store: ShadowResearchStore,
    db_path,
    run: dict,
    baseline_result_id: int,
    candidate_result_id: int,
) -> tuple[list[dict], list[dict]]:
    StrategyResearchAuditStore(db_path).init()
    market_date = str(run["market_date"])
    now = "2026-08-11T08:00:00+00:00"
    store.update_run(
        run["run_id"],
        now=now,
        baseline_result_id=baseline_result_id,
    )
    run = store.get_run(run["run_id"])
    for ordinal in range(1, 4):
        call, reused = store.claim_provider_call(
            call_id=f"prior-real-provider-call-{ordinal}",
            run_id=f"prior-run-{ordinal}",
            market_date=market_date,
            call_kind="prior_attempt",
            call_limit=13,
            now=now,
        )
        assert reused is False
        store.finish_provider_call(
            call["call_id"],
            status="failed",
            actual_tokens=None,
            failure_code="external_research_invalid_response",
            now=now,
        )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ai_shadow_research_retry_authorizations
            VALUES ('retry-auth', 'prior-run-1', ?, 'prior-input-1',
                    'external_research_invalid_response', 1, 10, 11,
                    'human:owner', 'Bounded retry.', ?)
            """,
            (market_date, now),
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_retry_consumptions
            VALUES ('retry-auth', ?, ?, ?)
            """,
            (run["run_id"], run["input_fingerprint"], now),
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_citation_call_extensions
            VALUES ('citation-extension', 'prior-run-2', ?, 'prior-input-2',
                    'provider_citation_not_in_bound_input', 2, 11, 1, 12,
                    'human:owner', 'Bounded citation extension.', ?)
            """,
            (market_date, now),
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_citation_call_extension_consumptions
            VALUES ('citation-extension', ?, ?, ?)
            """,
            (run["run_id"], run["input_fingerprint"], now),
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_output_truncation_call_extensions
            VALUES ('output-extension', 'prior-run-3', ?, 'prior-input-3',
                    'provider_output_truncated', 3, 12, 1, 13,
                    'human:owner', 'Bounded output extension.', ?)
            """,
            (market_date, now),
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_output_truncation_call_extension_consumptions
            VALUES ('output-extension', ?, ?, ?)
            """,
            (run["run_id"], run["input_fingerprint"], now),
        )

    candidates: list[dict] = []
    drafts: list[dict] = []
    previous_iteration = None
    for iteration_number in range(1, 5):
        iteration_context = _build_iteration_context(
            iteration_number=iteration_number,
            total_iterations=5,
            previous_iteration=previous_iteration,
        )
        session_id = f"persisted-session-{iteration_number}"
        draft_id = f"persisted-draft-{iteration_number}"
        backtest_run_id = f"persisted-backtest-{iteration_number}"
        critique_id = f"persisted-critique-{iteration_number}"
        formula_fingerprint = f"sha256:{iteration_number:064x}"
        hypothesis_call_id = (
            f"{run['run_id']}:hypothesis:iteration:{iteration_number:02d}"
        )
        critique_call_id = f"{run['run_id']}:critique:{draft_id}"
        draft = {
            "draft_id": draft_id,
            "economic_hypothesis": f"Persisted hypothesis {iteration_number}.",
            "risk_impact": "Research only; no execution authority.",
            "failure_conditions": ["OOS evidence fails"],
            "limitations": ["Historical evidence only"],
            "formula_ast": {
                "schema_version": "fixture",
                "iteration": iteration_number,
            },
            "formula_fingerprint": formula_fingerprint,
            "parameter_values": {},
            "parameter_ranges": {},
            "iteration_context": iteration_context,
            "iteration_context_fingerprint": iteration_context["context_fingerprint"],
            "validation": {"status": "valid", "errors": []},
        }
        critique_artifact = {
            "supported_claims": ["Persisted result."],
            "evidence_gaps": ["Continue research."],
        }
        comparison = {
            "schema_version": "karkinos.ai.shadow_research_comparison.v1",
            "candidate": {
                "total_return": 0.1 + iteration_number / 100,
                "sharpe": 1.0,
                "max_drawdown": 0.1,
                "oos_fold_count": 3,
                "mean_oos_return": 0.02,
                "worst_oos_return": -0.01,
                "oos_validation_status": "pass",
            },
            "deltas": {
                "total_return": 0.01,
                "sharpe": 0.1,
                "max_drawdown": -0.01,
            },
            "deepseek_critique": critique_artifact,
            "iteration_lineage": _iteration_lineage(
                iteration_context,
                current_formula_fingerprint=formula_fingerprint,
            ),
            "recommendation": "keep_researching",
            "promotion_gate": {
                "status": "blocked",
                "blockers": ["research_evidence_incomplete"],
                "evidence_fingerprint": f"sha256:{iteration_number + 10:064x}",
            },
        }
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO ai_strategy_research_sessions
                (session_id, idempotency_key, request_fingerprint, request_json,
                 selection_fingerprint, status, prompt_version, created_at,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, 'completed', 'fixture', ?, ?)
                """,
                (
                    session_id,
                    hypothesis_call_id,
                    f"request-{iteration_number}",
                    canonical_json({"iteration_context": iteration_context}),
                    "selection-fixture",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_strategy_hypothesis_drafts
                VALUES (?, ?, 1, ?, ?, ?, 'valid', '[]', ?)
                """,
                (
                    draft_id,
                    session_id,
                    canonical_json(draft),
                    content_fingerprint(draft),
                    formula_fingerprint,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_strategy_formula_backtests
                (backtest_run_id, idempotency_key, request_fingerprint,
                 session_id, draft_id, formula_fingerprint,
                 dataset_snapshot_id, cost_model_reference, status,
                 canonical_backtest_result_id, evidence_fingerprint,
                 created_at, updated_at)
                VALUES (?, ?, 'backtest-request', ?, ?, ?, 'dataset-fixture',
                        'reviewed-fees-fixture', 'completed', ?, ?, ?, ?)
                """,
                (
                    backtest_run_id,
                    f"{run['run_id']}:backtest:{draft_id}",
                    session_id,
                    draft_id,
                    formula_fingerprint,
                    candidate_result_id,
                    f"backtest-evidence-{iteration_number}",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_strategy_backtest_critiques
                (critique_id, idempotency_key, request_fingerprint, session_id,
                 draft_id, backtest_run_id, status, normalized_artifact_json,
                 artifact_fingerprint, prompt_version, created_at, updated_at)
                VALUES (?, ?, 'critique-request', ?, ?, ?, 'completed', ?, ?,
                        'fixture', ?, ?)
                """,
                (
                    critique_id,
                    critique_call_id,
                    session_id,
                    draft_id,
                    backtest_run_id,
                    canonical_json(critique_artifact),
                    content_fingerprint(critique_artifact),
                    now,
                    now,
                ),
            )
        for call_id, call_kind in (
            (hypothesis_call_id, "hypothesis_iteration"),
            (critique_call_id, "critique"),
        ):
            call, reused = store.claim_provider_call(
                call_id=call_id,
                run_id=run["run_id"],
                market_date=market_date,
                call_kind=call_kind,
                call_limit=13,
                now=now,
            )
            assert reused is False
            store.finish_provider_call(
                call["call_id"],
                status="completed",
                actual_tokens=1_000,
                failure_code=None,
                now=now,
            )
        candidate = store.save_candidate(
            run_id=run["run_id"],
            session_id=session_id,
            draft_id=draft_id,
            backtest_run_id=backtest_run_id,
            critique_id=critique_id,
            baseline_result_id=baseline_result_id,
            candidate_result_id=candidate_result_id,
            status="research_blocked",
            recommendation="keep_researching",
            comparison=comparison,
            now=now,
        )
        candidates.append(candidate)
        drafts.append(draft)
        previous_iteration = {
            "hypotheses": {"session_id": session_id},
            "draft": draft,
            "candidate": candidate,
        }
    failed_call, reused = store.claim_provider_call(
        call_id=f"{run['run_id']}:hypothesis:iteration:05",
        run_id=run["run_id"],
        market_date=market_date,
        call_kind="hypothesis_iteration",
        call_limit=13,
        now=now,
    )
    assert reused is False
    store.finish_provider_call(
        failed_call["call_id"],
        status="failed",
        actual_tokens=None,
        failure_code="provider_timeout",
        now=now,
    )
    store.update_run(
        run["run_id"],
        now=now,
        status="failed",
        failure_code="provider_timeout",
    )
    return candidates, drafts


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_five_round_policy_runs_sequential_generation_backtest_and_critique(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    candidate_payload = _result(
        total_return=0.12,
        sharpe=1.2,
        drawdown=0.08,
        initial_cash=1_000_000.0,
    )
    candidate_result_id = await db.save_backtest_result(
        config_json=json.dumps({"strategy": "ai_formula_research"}),
        initial_cash=candidate_payload["initial_cash"],
        final_equity=candidate_payload["final_equity"],
        total_return=candidate_payload["total_return"],
        sharpe=candidate_payload["sharpe"],
        max_dd=candidate_payload["max_drawdown"],
        equity_curve_json=json.dumps(candidate_payload["equity_curve"]),
        annual_return=candidate_payload["annual_return"],
        sortino=candidate_payload["sortino"],
        win_rate=candidate_payload["win_rate"],
        duration_days=candidate_payload["duration_days"],
        metrics_json=json.dumps(candidate_payload["metrics_json"]),
        cost_summary_json=json.dumps(candidate_payload["cost_summary_json"]),
    )
    fixture = _FixtureResearch(candidate_result_id)
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        now=lambda: datetime(2026, 8, 11, 8, 0, tzinfo=ZoneInfo("UTC")),
    )
    service.update_policy(
        {
            **_policy_payload(enabled=True),
            "max_provider_calls_per_market_date": 10,
            "daily_token_budget": None,
            "token_budget_mode": SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
            "max_candidates_per_run": 5,
        }
    )
    monkeypatch.setattr(
        service, "_prepare_baseline", lambda policy: _prepared_baseline()
    )

    def unexpected_valuation(*args, **kwargs):
        raise AssertionError("normalized-notional discovery must not read valuation")

    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        unexpected_valuation,
    )

    result = await service.run_once()
    persisted_run = store.get_run(result["run_id"])

    assert result["run_status"] == "completed"
    assert persisted_run["research_capital_mode"] == "normalized_notional"
    assert str(persisted_run["research_context_id"]).startswith("nominal-research:")
    assert persisted_run["valuation_snapshot_id"] == ""
    assert persisted_run["ledger_cutoff_id"] == 0
    assert fixture.hypothesis_calls == 5
    assert fixture.backtest_calls == 5
    assert fixture.critique_calls == 5
    assert len(result["candidates"]) == 5
    assert result["usage"]["provider_calls"] == 10
    assert [
        request.iteration_context["iteration_number"]
        for request in fixture.hypothesis_requests
    ] == [1, 2, 3, 4, 5]
    assert fixture.hypothesis_requests[0].iteration_context["parent_iteration"] is None
    for ordinal, request in enumerate(fixture.hypothesis_requests[1:], start=2):
        parent = request.iteration_context["parent_iteration"]
        assert parent["iteration_number"] == ordinal - 1
        assert parent["draft_id"] == f"draft-auto-{ordinal - 1}"
        assert parent["formula_fingerprint"] == f"sha256:{ordinal - 1:064x}"
        assert parent["critique"]
    assert result["daily_selections"][0]["observed_candidate_count"] == 5
    assert result["daily_selections"][0]["status"] == "no_selection"
    assert result["daily_backups"][0]["verification_status"] == "verified"
    assert result["daily_new_candidate_winner_id"] is None
    assert result["daily_winner_candidate_id"] is None
    research_winner_candidate_id = result["daily_selections"][0][
        "research_recommendation"
    ]["research_winner_candidate_id"]
    assert research_winner_candidate_id
    assert result["daily_research_winner_candidate_id"] == (
        research_winner_candidate_id
    )
    assert result["research_outcome"] == {
        "status": "best_available_formula_for_further_research",
        "new_candidate_winner_id": None,
        "research_winner_candidate_id": research_winner_candidate_id,
        "account_qualification_status": "not_evaluated",
        "qualification_run_id": None,
        "winner_qualification_candidate_id": None,
        "incumbent_strategy_policy": (
            "leave_current_human_approved_strategy_unchanged"
        ),
        "incumbent_strategy_state_changed": False,
        "daily_trading_decision_status": "not_evaluated",
        "implies_daily_trading_no_action": False,
    }


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_fifth_round_timeout_resume_preserves_four_rounds_and_uses_two_calls(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "app.db"
    db = AppDatabase(db_path)
    db.init_sync()
    store = ShadowResearchStore(db_path)
    store.init()
    baseline_payload = _result(total_return=0.05, sharpe=0.6, drawdown=0.12)
    candidate_payload = _result(total_return=0.12, sharpe=1.2, drawdown=0.08)
    baseline_result_id = await db.save_backtest_result(
        config_json=json.dumps({"strategy": "dual_ma"}),
        initial_cash=baseline_payload["initial_cash"],
        final_equity=baseline_payload["final_equity"],
        total_return=baseline_payload["total_return"],
        sharpe=baseline_payload["sharpe"],
        max_dd=baseline_payload["max_drawdown"],
        equity_curve_json=json.dumps(baseline_payload["equity_curve"]),
        annual_return=baseline_payload["annual_return"],
        sortino=baseline_payload["sortino"],
        win_rate=baseline_payload["win_rate"],
        duration_days=baseline_payload["duration_days"],
        metrics_json=json.dumps(baseline_payload["metrics_json"]),
        cost_summary_json=json.dumps(baseline_payload["cost_summary_json"]),
    )
    candidate_result_id = await db.save_backtest_result(
        config_json=json.dumps({"strategy": "ai_formula_research"}),
        initial_cash=candidate_payload["initial_cash"],
        final_equity=candidate_payload["final_equity"],
        total_return=candidate_payload["total_return"],
        sharpe=candidate_payload["sharpe"],
        max_dd=candidate_payload["max_drawdown"],
        equity_curve_json=json.dumps(candidate_payload["equity_curve"]),
        annual_return=candidate_payload["annual_return"],
        sortino=candidate_payload["sortino"],
        win_rate=candidate_payload["win_rate"],
        duration_days=candidate_payload["duration_days"],
        metrics_json=json.dumps(candidate_payload["metrics_json"]),
        cost_summary_json=json.dumps(candidate_payload["cost_summary_json"]),
    )
    fixture = _FixtureResearch(candidate_result_id)
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        now=lambda: datetime(2026, 8, 11, 8, 0, tzinfo=ZoneInfo("UTC")),
    )
    service.update_policy(_account_bound_policy_payload(enabled=True))
    prepared = _prepared_baseline(account_bound=True)
    policy = service.get_policy()
    valuation = _complete_valuation(db, True)
    input_fingerprint = content_fingerprint(
        {
            "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
            "policy": policy.to_dict(),
            "baseline_fingerprint": prepared.fingerprint,
            "valuation_snapshot_id": valuation["snapshot_id"],
            "ledger_cutoff_id": valuation["ledger_cutoff_id"],
        }
    )
    run, reused = store.claim_run(
        market_date=prepared.market_date,
        input_fingerprint=input_fingerprint,
        baseline_seed_result_id=prepared.seed_result_id,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id=valuation["snapshot_id"],
        valuation_snapshot_id=valuation["snapshot_id"],
        ledger_cutoff_id=valuation["ledger_cutoff_id"],
        now="2026-08-11T08:00:00+00:00",
    )
    assert reused is False
    candidates, _ = _seed_four_round_timeout_resume_state(
        store=store,
        db_path=db_path,
        run=run,
        baseline_result_id=baseline_result_id,
        candidate_result_id=candidate_result_id,
    )
    persisted_selection = StrategyResearchSelection(
        saved_backtest_result_id=baseline_result_id,
        universe=tuple(asset["symbol"] for asset in prepared.request.assets or []),
        asset_classes=tuple(
            asset["asset_class"] for asset in prepared.request.assets or []
        ),
        dataset_snapshot_id=str(prepared.snapshot["snapshot_id"]),
        start_date=prepared.request.start_date,
        end_date=prepared.request.end_date,
        frequency=BarFrequency.DAILY.value,
        initial_cash=prepared.request.initial_cash,
        cost_model_reference=prepared.cost_model_reference,
        account_truth_freshness_as_of="2026-08-11T15:30:00+08:00",
        valuation_snapshot_id=valuation["snapshot_id"],
        ledger_cutoff_id=valuation["ledger_cutoff_id"],
    ).to_dict()
    wrapped_input_fingerprint = content_fingerprint(
        {
            "retry_wrapped_input_fingerprint": input_fingerprint,
            "authorization_lineage": "persisted-prior-retries",
        }
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO ai_shadow_research_baselines VALUES (?, ?, ?)",
            (prepared.fingerprint, baseline_result_id, "2026-08-11T08:00:00+00:00"),
        )
        conn.execute(
            "UPDATE ai_shadow_research_runs SET input_fingerprint=? WHERE run_id=?",
            (wrapped_input_fingerprint, run["run_id"]),
        )
        for iteration_number in range(1, 5):
            session_id = f"persisted-session-{iteration_number}"
            current = conn.execute(
                "SELECT request_json FROM ai_strategy_research_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            iteration_context = json.loads(current[0])["iteration_context"]
            conn.execute(
                """
                UPDATE ai_strategy_research_sessions SET request_json=?
                WHERE session_id=?
                """,
                (
                    canonical_json(
                        {
                            "requested_by": "automation:human:owner",
                            "account_alias": (
                                "standing-owner-authorized-shadow-research"
                            ),
                            "research_question": policy.research_question,
                            "selection": persisted_selection,
                            "iteration_context": iteration_context,
                            "confirmation_recorded": True,
                            "api_key_recorded": False,
                        }
                    ),
                    session_id,
                ),
            )
        first_four_calls_before = conn.execute(
            """
            SELECT call_id, status, actual_tokens, failure_code, created_at, updated_at
            FROM ai_shadow_research_provider_calls
            WHERE run_id=? AND status='completed'
            ORDER BY call_id
            """,
            (run["run_id"],),
        ).fetchall()

    extension = service.authorize_timeout_resume_call_extension(
        run["run_id"],
        approved_by="human:owner",
        notes="Resume only the persisted fifth round after its provider timeout.",
        confirmation=SHADOW_RESEARCH_TIMEOUT_RESUME_CALL_EXTENSION_CONFIRMATION,
    )
    assert extension["completed_iteration_count"] == 4
    assert extension["resume_iteration"] == 5
    assert extension["provider_calls_at_authorization"] == 12
    assert extension["prior_provider_call_ceiling"] == 13
    assert extension["authorized_additional_calls"] == 1
    assert extension["provider_call_ceiling"] == 14
    assert extension["consumed"] is False
    assert extension["broker_submission_enabled"] is False
    assert extension["capital_authority_changed"] is False

    selection_components = dict(persisted_selection)
    selection_components.pop("schema_version")
    selection_components.pop("saved_backtest_result_id")
    selection_components.pop("account_fact_binding")
    with pytest.raises(
        ShadowResearchRejected,
        match="timeout_resume_input_evidence_drift",
    ):
        store.claim_run(
            market_date=prepared.market_date,
            input_fingerprint=input_fingerprint,
            baseline_seed_result_id=prepared.seed_result_id,
            research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
            research_context_id=valuation["snapshot_id"],
            valuation_snapshot_id=valuation["snapshot_id"],
            ledger_cutoff_id=valuation["ledger_cutoff_id"],
            now="2026-08-11T08:01:30+00:00",
            timeout_resume_input_evidence={
                "baseline_fingerprint": prepared.fingerprint,
                "requested_by": "automation:human:owner",
                "account_alias": "standing-owner-authorized-shadow-research",
                "research_question": "A different research question.",
                "selection_components": selection_components,
            },
        )
    assert (
        store.usage_for_market_date(prepared.market_date)[
            "timeout_resume_call_extension_consumed"
        ]
        is False
    )

    monkeypatch.setattr(service, "_prepare_baseline", lambda policy: prepared)
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        _complete_valuation,
    )
    result = await service.run_once()
    replay = await service.run_once()

    assert result["run_status"] == "completed"
    assert replay["reused"] is True
    assert fixture.hypothesis_calls == 1
    assert fixture.backtest_calls == 1
    assert fixture.critique_calls == 1
    assert fixture.hypothesis_requests[0].iteration_context["iteration_number"] == 5
    assert (
        fixture.hypothesis_requests[0].iteration_context["parent_iteration"][
            "candidate_id"
        ]
        == candidates[-1]["candidate_id"]
    )
    assert result["usage"]["provider_calls"] == 14
    assert result["usage"]["authorized_additional_calls"] == 13
    assert result["usage"]["authorized_provider_call_ceiling"] == 14
    assert result["usage"]["timeout_resume_call_extension_consumed"] is True
    assert result["usage"]["timeout_resume_iteration"] == 5
    assert result["broker_submission_enabled"] is False
    assert result["automatic_strategy_replacement_enabled"] is False
    with sqlite3.connect(db_path) as conn:
        first_four_calls_after = conn.execute(
            """
            SELECT call_id, status, actual_tokens, failure_code, created_at, updated_at
            FROM ai_shadow_research_provider_calls
            WHERE run_id=? AND status='completed'
              AND call_id NOT LIKE '%timeout-resume%'
              AND call_id NOT LIKE '%draft-auto-1%'
            ORDER BY call_id
            """,
            (run["run_id"],),
        ).fetchall()
        saved_run = conn.execute(
            """
            SELECT status, failure_code, candidate_count
            FROM ai_shadow_research_runs WHERE run_id=?
            """,
            (run["run_id"],),
        ).fetchone()
        failed_fifth = conn.execute(
            """
            SELECT status, failure_code FROM ai_shadow_research_provider_calls
            WHERE call_id=?
            """,
            (f"{run['run_id']}:hypothesis:iteration:05",),
        ).fetchone()
        timeout_retry_calls = conn.execute(
            """
            SELECT call_kind, status FROM ai_shadow_research_provider_calls
            WHERE run_id=? AND call_id LIKE '%timeout-resume%'
            """,
            (run["run_id"],),
        ).fetchall()
        candidate_count = conn.execute(
            "SELECT COUNT(*) FROM ai_shadow_research_candidates WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()[0]
        promotion_count = conn.execute(
            "SELECT COUNT(*) FROM ai_shadow_research_promotions"
        ).fetchone()[0]
    assert first_four_calls_after == first_four_calls_before
    assert saved_run == ("completed", None, 5)
    assert failed_fifth == ("failed", "provider_timeout")
    assert timeout_retry_calls == [("hypothesis_iteration", "completed")]
    assert candidate_count == 5
    assert promotion_count == 0


@pytest.mark.unit
@pytest.mark.trading_safety
def test_fifth_round_timeout_resume_fails_closed_on_completed_evidence_drift(
    tmp_path,
) -> None:
    db_path = tmp_path / "app.db"
    db = AppDatabase(db_path)
    db.init_sync()
    store = ShadowResearchStore(db_path)
    store.init()
    run, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="persisted-four-round-input",
        baseline_seed_result_id=7,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-latest",
        valuation_snapshot_id="valuation-latest",
        ledger_cutoff_id=11,
        now="2026-08-11T08:00:00+00:00",
    )
    assert reused is False
    candidates, _ = _seed_four_round_timeout_resume_state(
        store=store,
        db_path=db_path,
        run=run,
        baseline_result_id=28,
        candidate_result_id=29,
    )
    store.authorize_timeout_resume_call_extension(
        run["run_id"],
        approved_by="human:owner",
        notes="Resume only unchanged persisted fifth-round evidence.",
        confirmation=SHADOW_RESEARCH_TIMEOUT_RESUME_CALL_EXTENSION_CONFIRMATION,
        now="2026-08-11T08:01:00+00:00",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE ai_shadow_research_candidates SET comparison_json='{}'
            WHERE candidate_id=?
            """,
            (candidates[-1]["candidate_id"],),
        )

    with pytest.raises(
        ShadowResearchRejected,
        match="timeout_resume_completed_iteration_evidence_invalid",
    ):
        store.claim_run(
            market_date=run["market_date"],
            input_fingerprint=run["input_fingerprint"],
            baseline_seed_result_id=run["baseline_seed_result_id"],
            research_capital_mode=run["research_capital_mode"],
            research_context_id=run["research_context_id"],
            valuation_snapshot_id=run["valuation_snapshot_id"],
            ledger_cutoff_id=run["ledger_cutoff_id"],
            now="2026-08-11T08:02:00+00:00",
        )
    saved = store.get_run(run["run_id"])
    usage = store.usage_for_market_date(run["market_date"])
    assert saved["status"] == "failed"
    assert saved["failure_code"] == "provider_timeout"
    assert usage["provider_calls"] == 12
    assert usage["authorized_provider_call_ceiling"] == 14
    assert usage["timeout_resume_call_extension_consumed"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_full_cycle_is_idempotent_and_stops_at_human_research_pool(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    candidate_payload = _result(
        total_return=0.12,
        sharpe=1.2,
        drawdown=0.08,
        initial_cash=1_000_000.0,
    )
    candidate_result_id = await db.save_backtest_result(
        config_json=json.dumps({"strategy": "ai_formula_research"}),
        initial_cash=candidate_payload["initial_cash"],
        final_equity=candidate_payload["final_equity"],
        total_return=candidate_payload["total_return"],
        sharpe=candidate_payload["sharpe"],
        max_dd=candidate_payload["max_drawdown"],
        equity_curve_json=json.dumps(candidate_payload["equity_curve"]),
        annual_return=candidate_payload["annual_return"],
        sortino=candidate_payload["sortino"],
        win_rate=candidate_payload["win_rate"],
        duration_days=candidate_payload["duration_days"],
        metrics_json=json.dumps(candidate_payload["metrics_json"]),
        cost_summary_json=json.dumps(candidate_payload["cost_summary_json"]),
    )
    fixture = _FixtureResearch(candidate_result_id)
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        now=lambda: datetime(2026, 8, 11, 8, 0, tzinfo=ZoneInfo("UTC")),
    )
    service.update_policy(_policy_payload(enabled=True))
    prepared = _prepared_baseline()
    monkeypatch.setattr(service, "_prepare_baseline", lambda policy: prepared)

    def unexpected_account_valuation(*args, **kwargs):
        raise AssertionError("normalized-notional discovery must not read valuation")

    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        unexpected_account_valuation,
    )

    first = await service.run_once()
    replay = await service.run_once()

    assert first["run_status"] == "completed"
    assert replay["reused"] is True
    assert fixture.hypothesis_calls == 5
    assert fixture.hypothesis_requests[0].selection.valuation_snapshot_id is None
    assert fixture.hypothesis_requests[0].selection.ledger_cutoff_id is None
    assert fixture.hypothesis_requests[0].selection.has_account_binding is False
    assert fixture.backtest_calls == 5
    assert fixture.critique_calls == 5
    candidate = first["candidates"][0]
    assert candidate["recommendation"] == "formula_research_candidate"
    assert candidate["status"] == "evaluated_research_only"
    assert candidate["promotion_status"] == "account_qualification_required"
    assert candidate["comparison"]["promotion_gate"]["status"] == "blocked"
    assert {
        "candidate_dataset_quality_not_clear",
        "baseline_rolling_oos_evidence_not_reproducible",
        "candidate_parameter_robustness_not_passing",
        "candidate_market_regime_robustness_not_passing",
        "candidate_capacity_or_liquidity_not_passing",
        "candidate_fee_or_tax_evidence_incomplete",
    }.issubset(candidate["comparison"]["promotion_gate"]["blockers"])
    assert candidate["automatic_strategy_replacement_enabled"] is False
    assert candidate["broker_submission_enabled"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_running_market_date_claim_prevents_concurrent_provider_reentry(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    fixture = _FixtureResearch(candidate_result_id=99)
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        now=lambda: datetime(2026, 8, 11, 8, 0, tzinfo=ZoneInfo("UTC")),
    )
    service.update_policy(_policy_payload(enabled=True))
    monkeypatch.setattr(
        service, "_prepare_baseline", lambda policy: _prepared_baseline()
    )
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        _complete_valuation,
    )
    claimed, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="another-scheduler-fingerprint",
        baseline_seed_result_id=7,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-latest",
        valuation_snapshot_id="valuation-latest",
        ledger_cutoff_id=11,
        now="2026-08-11T08:00:00+00:00",
    )
    assert reused is False

    result = await service.run_once()

    assert result["reused"] is True
    assert result["run_id"] == claimed["run_id"]
    assert result["run_status"] == "running"
    assert fixture.hypothesis_calls == 0
    assert fixture.backtest_calls == 0
    assert fixture.critique_calls == 0
    assert store.usage_for_market_date("2026-08-11")["provider_calls"] == 0


class _FailingHypothesisResearch(_FixtureResearch):
    async def generate_hypotheses(self, request):
        self.hypothesis_calls += 1
        raise RuntimeError("deepseek_timeout")


class _RejectedHypothesisResearch(_FixtureResearch):
    async def generate_hypotheses(self, request):
        self.hypothesis_calls += 1
        return {
            "status": "failed",
            "failure_code": "provider_citation_not_in_bound_input",
            "drafts": [],
        }


class _SendEdgeDeferredHypothesisResearch(_FixtureResearch):
    def __init__(self) -> None:
        super().__init__(candidate_result_id=99)
        self.provider_transport_calls = 0

    async def generate_hypotheses(self, request):
        self.hypothesis_calls += 1
        decision = DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(
            datetime(2026, 8, 12, 9, 0, tzinfo=SHANGHAI)
        )
        raise ProviderCallDeferred(decision)


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_send_edge_window_defer_is_provider_free_and_rearmable(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    fixture = _SendEdgeDeferredHypothesisResearch()
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        provider_call_window_policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
        now=lambda: datetime(2026, 8, 12, 6, 54, tzinfo=SHANGHAI),
    )
    service.update_policy(_policy_payload(enabled=True))
    monkeypatch.setattr(
        service, "_prepare_baseline", lambda policy: _prepared_baseline()
    )

    result = await service.run_once()

    assert result["run_status"] == "deferred_for_provider_off_peak"
    assert result["failure_code"] == "deepseek_peak_pricing_window"
    assert fixture.provider_transport_calls == 0
    call = store.get_provider_call(f"{result['run_id']}:hypothesis:iteration:01")
    assert (call["status"], call["actual_tokens"], call["failure_code"]) == (
        "deferred",
        0,
        "deepseek_peak_pricing_window",
    )
    usage = store.usage_for_market_date("2026-08-11")
    assert usage["provider_calls"] == 0
    assert usage["reserved_tokens"] == 0
    assert usage["recorded_call_attempts"] == 1
    assert usage["provider_free_rejections"] == 1

    deferred_run = store.get_run(result["run_id"])
    replacement, reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="next-eligible-window-input",
        baseline_seed_result_id=7,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
        research_context_id=str(deferred_run["research_context_id"]),
        valuation_snapshot_id=None,
        ledger_cutoff_id=0,
        now="2026-08-12T10:00:00+00:00",
    )
    assert reused is False
    assert replacement["status"] == "running"
    assert replacement["run_id"] != result["run_id"]
    replacement_call, reused = store.claim_provider_call(
        call_id=f"{replacement['run_id']}:hypothesis:iteration:01",
        run_id=replacement["run_id"],
        market_date="2026-08-11",
        call_kind="hypothesis_iteration",
        call_limit=1,
        now="2026-08-12T10:00:01+00:00",
    )
    assert reused is False
    assert replacement_call["status"] == "reserved"


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_provider_exception_is_audited_failed_and_replay_does_not_retry(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    fixture = _FailingHypothesisResearch(candidate_result_id=99)
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        now=lambda: datetime(2026, 8, 11, 8, 0, tzinfo=ZoneInfo("UTC")),
    )
    service.update_policy(_policy_payload(enabled=True))
    monkeypatch.setattr(
        service, "_prepare_baseline", lambda policy: _prepared_baseline()
    )
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        _complete_valuation,
    )

    first = await service.run_once()
    replay = await service.run_once()

    assert first["run_status"] == "failed"
    assert first["failure_code"] == "deepseek_timeout"
    assert replay["reused"] is True
    assert fixture.hypothesis_calls == 1
    call = store.get_provider_call(f"{first['run_id']}:hypothesis:iteration:01")
    assert call["status"] == "failed"
    assert call["failure_code"] == "deepseek_timeout"
    assert store.usage_for_market_date("2026-08-11")["provider_calls"] == 1


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_provider_rejection_keeps_exact_safe_failure_code(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    fixture = _RejectedHypothesisResearch(candidate_result_id=99)
    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        now=lambda: datetime(2026, 8, 11, 8, 0, tzinfo=ZoneInfo("UTC")),
    )
    service.update_policy(_policy_payload(enabled=True))
    monkeypatch.setattr(
        service, "_prepare_baseline", lambda policy: _prepared_baseline()
    )
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        _complete_valuation,
    )

    result = await service.run_once()

    assert result["run_status"] == "failed"
    assert result["failure_code"] == "provider_citation_not_in_bound_input"
    assert fixture.hypothesis_calls == 1
    call = store.get_provider_call(f"{result['run_id']}:hypothesis:iteration:01")
    assert call["status"] == "failed"
    assert call["failure_code"] == "provider_citation_not_in_bound_input"


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_missing_market_evidence_creates_provider_free_preflight_audit(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path)
    service.update_policy(_policy_payload(enabled=True))

    def reject_baseline(policy):
        raise ShadowResearchRejected("persisted_bars_missing:510300")

    monkeypatch.setattr(service, "_prepare_baseline", reject_baseline)

    result = await service.run_once()

    assert result["run_status"] == "blocked_by_market_evidence"
    assert result["failure_code"] == "persisted_bars_missing:510300"
    with sqlite3.connect(tmp_path / "app.db") as conn:
        audit = conn.execute(
            "SELECT status, payload_json FROM automation_runs WHERE run_id=?",
            (result["preflight_run_id"],),
        ).fetchone()
        provider_calls = conn.execute(
            "SELECT COUNT(*) FROM ai_shadow_research_provider_calls"
        ).fetchone()[0]
    assert audit is not None
    assert audit[0] == "blocked_by_market_evidence"
    assert json.loads(audit[1])["provider_call_performed"] is False
    assert provider_calls == 0


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_missing_reviewed_fee_schedule_is_account_evidence_no_action(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path)
    service.update_policy(_policy_payload(enabled=True))

    def reject_fee_schedule(policy):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_review_missing")

    monkeypatch.setattr(service, "_prepare_baseline", reject_fee_schedule)

    result = await service.run_once()

    assert result["run_status"] == "blocked_by_account_evidence"
    assert result["failure_code"] == "reviewed_fee_schedule_review_missing"
    assert result["policy"]["enabled"] is True
    with sqlite3.connect(tmp_path / "app.db") as conn:
        provider_calls = conn.execute(
            "SELECT COUNT(*) FROM ai_shadow_research_provider_calls"
        ).fetchone()[0]
    assert provider_calls == 0


@pytest.mark.unit
@pytest.mark.trading_safety
def test_automatic_baseline_uses_resolved_reviewed_fee_calculator(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market = DataStore(tmp_path / "market")
    symbol = Symbol("600000")
    closes = [10.0] * 40 + [20.0] * 40
    bars = pd.DataFrame(
        {
            "timestamp": pd.bdate_range("2026-01-02", periods=len(closes)),
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        }
    )
    universe_snapshot = market.save_market_universe_snapshot(
        trade_date=bars["timestamp"].iloc[-1].date().isoformat(),
        provider_name="deterministic_fixture",
        members=normalize_a_share_members(
            [f"{600000 + index:06d}" for index in range(1_000)]
        ),
    )
    panel_symbols = list(
        preliminary_research_panel_symbols(
            universe_snapshot,
            policy=MarketUniversePolicy(),
        )
    )
    for panel_symbol in panel_symbols:
        market.save_bars(
            Symbol(panel_symbol),
            BarFrequency.DAILY,
            bars,
            provider_name="deterministic_fixture",
            data_source="deterministic_fixture",
            adjustment_mode="none",
            instrument_type=InstrumentType.STOCK,
        )
    market_dates = [timestamp.date().isoformat() for timestamp in bars["timestamp"]]
    calendar_source_fingerprint = "c" * 64
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "deterministic_fixture",
            "status": "available",
            "trading_day_count": len(market_dates),
            "closed_day_count": 0,
            "source_fingerprint": calendar_source_fingerprint,
            "days": [
                {
                    "date": market_date,
                    "is_trading_day": True,
                    "day_type": "trading",
                    "reason_code": "scheduled_trading_day",
                }
                for market_date in market_dates
            ],
            "limitations": [],
        }
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=calendar_source_fingerprint,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="d" * 64,
        verified_by="unit-test",
    )
    for index, market_date in enumerate(market_dates):
        market.ingest_market_daily_batch(
            trade_date=market_date,
            provider_name="deterministic_fixture",
            bars=pd.DataFrame(
                {
                    "symbol": panel_symbols,
                    "timestamp": [bars["timestamp"].iloc[index]] * len(panel_symbols),
                    "open": [bars["open"].iloc[index]] * len(panel_symbols),
                    "high": [bars["high"].iloc[index]] * len(panel_symbols),
                    "low": [bars["low"].iloc[index]] * len(panel_symbols),
                    "close": [bars["close"].iloc[index]] * len(panel_symbols),
                    "volume": [bars["volume"].iloc[index]] * len(panel_symbols),
                }
            ),
        )
    db.upsert_automation_run_sync(
        {
            "run_id": (
                f"market_universe_sync:v2:deterministic_fixture:{market_dates[-1]}"
            ),
            "run_type": "market_universe_sync",
            "run_date": market_dates[-1],
            "status": "completed",
            "execution_mode": "market_data_ingestion",
            "source_ref": universe_snapshot["snapshot_id"],
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v2",
                "market_universe_snapshot_id": universe_snapshot["snapshot_id"],
                "full_market_history_frozen": True,
            },
        }
    )
    seed_result_id = asyncio.run(
        db.save_backtest_result(
            config_json=json.dumps(
                {
                    "start_date": "2026-01-02",
                    "end_date": bars["timestamp"].iloc[-1].date().isoformat(),
                    "initial_cash": 100_000,
                    "strategy": "dual_ma",
                    "short_period": 5,
                    "long_period": 20,
                    "assets": [{"symbol": str(symbol), "asset_class": "stock"}],
                }
            ),
            initial_cash=100_000,
            final_equity=100_000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
            metrics_json="{}",
            cost_summary_json="{}",
        )
    )
    review_id = "fee_review_" + "a" * 32
    review_fingerprint = "sha256:" + "b" * 64
    cost_model_reference = (
        "karkinos.backtest.reviewed_account_fee_schedule.v1:"
        f"{review_id}:{review_fingerprint.removeprefix('sha256:')}"
    )
    calculator = MultiAssetCommission(fee_rule_version=cost_model_reference)
    calculator.set_commission(
        CommissionType.STOCK_A,
        StockACommission(
            commission_rate=Decimal("0.01"),
            min_commission=Decimal("0"),
            fee_rule_id="reviewed-account-fee-rule",
        ),
    )
    resolution = SimpleNamespace(
        cost_model_reference=cost_model_reference,
        commission_calc=calculator,
        fee_evidence={
            "account_specific": True,
            "fee_schedule_source": (
                "reviewed_account_truth_or_reconciled_fee_schedule"
            ),
            "fee_schedule_fingerprint": "sha256:" + "f" * 64,
            "broker_statement_reconciled": True,
            "fee_schedule_review_id": review_id,
            "fee_schedule_review_fingerprint": review_fingerprint,
            "fee_schedule_preview_fingerprint": "sha256:" + "c" * 64,
            "account_truth_import_run_id": "import_fixture",
            "account_truth_source_fingerprint": "sha256:" + "d" * 64,
            "account_truth_scope_fingerprint": "sha256:" + "e" * 64,
            "effective_start_date": "2026-01-01",
            "effective_end_date": "2026-12-31",
            "fee_notional_envelope_enforced": True,
            "fee_notional_envelope_fingerprint": "sha256:" + "9" * 64,
            "fee_notional_covered_asset_classes": ["stock"],
        },
    )
    resolver_calls: list[dict] = []

    def resolve_fees(**kwargs):
        resolver_calls.append(kwargs)
        return resolution

    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=ShadowResearchStore(db._path),
        data_store=market,
        reviewed_fee_schedule_resolver=resolve_fees,
    )

    prepared = service._prepare_baseline(
        ShadowResearchPolicy(
            baseline_backtest_result_id=seed_result_id,
            research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
            require_complete_account_evidence=True,
        )
    )

    assert prepared.cost_model_reference == cost_model_reference
    assert resolver_calls[-1]["account_truth_as_of"] == datetime.combine(
        bars["timestamp"].iloc[-1].date(),
        datetime.strptime("15:30", "%H:%M").time(),
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    fee_evidence = prepared.result["metrics_json"]["fee_component_evidence"]
    assert fee_evidence["account_specific"] is True
    assert fee_evidence["fee_rule_version"] == cost_model_reference
    assert prepared.result["fills"]
    assert all(
        fill["fee_rule_version"] == cost_model_reference
        for fill in prepared.result["fills"]
    )

    resolver_call_count = len(resolver_calls)
    normalized = service._prepare_baseline(
        ShadowResearchPolicy(baseline_backtest_result_id=seed_result_id)
    )
    assert len(resolver_calls) == resolver_call_count
    assert normalized.cost_model_reference == (
        "karkinos.backtest.multi_asset_commission.default.v1"
    )
    normalized_fee_evidence = normalized.result["metrics_json"][
        "fee_component_evidence"
    ]
    assert normalized_fee_evidence["account_specific"] is False
    assert normalized_fee_evidence["authorizes_execution"] is False
    assert normalized.fee_schedule_evidence["authorizes_promotion"] is False

    etf_seed_result_id = asyncio.run(
        db.save_backtest_result(
            config_json=json.dumps(
                {
                    "start_date": "2026-01-02",
                    "end_date": bars["timestamp"].iloc[-1].date().isoformat(),
                    "initial_cash": 100_000,
                    "strategy": "dual_ma",
                    "short_period": 5,
                    "long_period": 20,
                    "assets": [{"symbol": str(symbol), "asset_class": "etf"}],
                }
            ),
            initial_cash=100_000,
            final_equity=100_000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
            metrics_json="{}",
            cost_summary_json="{}",
        )
    )
    with pytest.raises(
        ShadowResearchRejected,
        match="daily_candidate_strategy_asset_class_not_supported",
    ):
        service._prepare_baseline(
            ShadowResearchPolicy(baseline_backtest_result_id=etf_seed_result_id)
        )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_kill_switch_blocks_before_evidence_or_provider_and_is_audited(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path)
    service.update_policy(_policy_payload(enabled=True))
    service._state.trading_controls.set_kill_switch(True, "operator emergency stop")

    def unexpected_baseline(policy):
        raise AssertionError("baseline preparation must not run under Kill Switch")

    monkeypatch.setattr(service, "_prepare_baseline", unexpected_baseline)

    result = await service.run_once()

    assert result["run_status"] == "blocked_by_kill_switch"
    assert result["failure_code"] == "kill_switch_enabled"
    assert result["kill_switch"] == {
        "enabled": True,
        "reason": "operator emergency stop",
    }
    with sqlite3.connect(tmp_path / "app.db") as conn:
        audit = conn.execute(
            "SELECT status, payload_json FROM automation_runs WHERE run_id=?",
            (result["preflight_run_id"],),
        ).fetchone()
        provider_calls = conn.execute(
            "SELECT COUNT(*) FROM ai_shadow_research_provider_calls"
        ).fetchone()[0]
        shadow_runs = conn.execute(
            "SELECT COUNT(*) FROM ai_shadow_research_runs"
        ).fetchone()[0]
    assert audit is not None
    assert audit[0] == "blocked_by_kill_switch"
    assert json.loads(audit[1])["provider_call_performed"] is False
    assert provider_calls == 0
    assert shadow_runs == 0


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_kill_switch_change_after_local_backtest_blocks_deepseek_critique(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    state = _state(db)

    class KillSwitchAfterBacktestResearch(_FixtureResearch):
        async def run_formula_backtest(self, request):
            result = await super().run_formula_backtest(request)
            state.trading_controls.set_kill_switch(True, "operator mid-run stop")
            return result

    fixture = KillSwitchAfterBacktestResearch(candidate_result_id=99)
    service = AiShadowResearchAutomationService(
        state=state,
        store=store,
        data_store=DataStore(tmp_path / "market"),
        research_service_builder=lambda external: fixture,
        now=lambda: datetime(2026, 8, 11, 8, 0, tzinfo=ZoneInfo("UTC")),
    )
    service.update_policy(_policy_payload(enabled=True))
    monkeypatch.setattr(
        service, "_prepare_baseline", lambda policy: _prepared_baseline()
    )
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        _complete_valuation,
    )

    result = await service.run_once()

    assert result["run_status"] == "failed"
    assert result["failure_code"] == "sequential_iteration_not_complete"
    assert fixture.hypothesis_calls == 1
    assert fixture.backtest_calls == 1
    assert fixture.critique_calls == 0
    assert result["usage"]["provider_calls"] == 1
    candidate = result["candidates"][0]
    assert candidate["status"] == "failed_closed"
    assert candidate["recommendation"] == "reject"
    assert candidate["comparison"]["failure_code"] == "blocked_by_kill_switch"
    assert candidate["comparison"]["promotion_gate"] == {
        "status": "blocked",
        "blockers": ["blocked_by_kill_switch"],
    }
