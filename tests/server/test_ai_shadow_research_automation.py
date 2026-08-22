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
from core.types import BarFrequency, CommissionType, Symbol
from data.store import DataStore
from execution.commission import MultiAssetCommission, StockACommission
from server.db import AppDatabase
from server.models import BacktestRequest
from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_PAUSE_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION,
    SHADOW_RESEARCH_RETRY_CONFIRMATION,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
    AiShadowResearchAutomationService,
    PreparedBaseline,
    ShadowResearchPolicy,
    ShadowResearchRejected,
    ShadowResearchStore,
    _after_close,
    _failure_code,
)
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
    build_daily_strategy_promotion_binding,
)
from server.services.reviewed_fee_schedule import ReviewedFeeScheduleRejected
from server.services.trading_controls import TradingControlState
from tests.ai_shadow_strategy_fixtures import seed_ai_shadow_canonical_sources

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _state(db: AppDatabase) -> SimpleNamespace:
    return SimpleNamespace(
        db=db,
        trading_controls=TradingControlState(db=db),
        notifier=None,
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
        "require_complete_account_evidence": True,
        "research_question": "Generate one falsifiable formula improvement.",
        "updated_by": "human:owner",
        "confirmation": (
            SHADOW_RESEARCH_POLICY_CONFIRMATION
            if enabled
            else SHADOW_RESEARCH_PAUSE_CONFIRMATION
        ),
    }


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
    with pytest.raises(
        ShadowResearchRejected,
        match="enabled_shadow_research_requires_unbounded_daily_token_policy",
    ):
        service.update_policy(
            {
                **_policy_payload(enabled=True),
                "daily_token_budget": SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION,
                "token_budget_mode": "legacy_bounded_daily",
            }
        )

    enabled = service.update_policy(_policy_payload(enabled=True))
    assert enabled["enabled"] is True
    assert enabled["authorization_recorded"] is True

    paused = service.update_policy(_policy_payload(enabled=False))
    assert paused["enabled"] is False
    assert paused["authorization_recorded"] is False


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
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    "failure_code",
    [
        "research_initial_cash_exceeds_current_account_equity",
        "account_evidence_binding_mismatch",
        "ai_runtime_role_identity_conflict",
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
        valuation_snapshot_id="valuation-complete",
        ledger_cutoff_id=12,
        now="2026-08-11T08:06:00+00:00",
    )
    assert reused is False
    assert replacement["run_id"] != first["run_id"]
    assert replacement["input_fingerprint"] != first["input_fingerprint"]
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
async def test_enabled_legacy_bounded_policy_is_audited_but_cannot_run(
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
    service._db.upsert_automation_policy_sync(
        policy_id="ai_shadow_research",
        payload=legacy_payload,
        updated_by="human:owner",
    )

    def unexpected_baseline(policy):
        raise AssertionError("legacy bounded policy must not prepare evidence")

    monkeypatch.setattr(service, "_prepare_baseline", unexpected_baseline)

    result = await service.run_once()

    assert result["run_status"] == "blocked_by_policy"
    assert result["failure_code"] == "unbounded_daily_token_policy_not_authorized"
    assert result["policy"]["token_budget_mode"] == "legacy_bounded_daily"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_export_requires_deepseek_identity_and_deepseek_endpoint(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path)
    service._state.config = object()

    monkeypatch.setattr(
        "server.ai_runtime.provider_connectivity.load_provider_connectivity_settings",
        lambda config: SimpleNamespace(
            provider_id="openai", endpoint_origin="https://api.deepseek.com/v1"
        ),
    )
    with pytest.raises(
        ShadowResearchRejected, match="deepseek_provider_not_configured"
    ):
        service._require_deepseek_provider()

    monkeypatch.setattr(
        "server.ai_runtime.provider_connectivity.load_provider_connectivity_settings",
        lambda config: SimpleNamespace(
            provider_id="deepseek", endpoint_origin="https://proxy.example.com/v1"
        ),
    )
    with pytest.raises(
        ShadowResearchRejected, match="deepseek_provider_not_configured"
    ):
        service._require_deepseek_provider()

    monkeypatch.setattr(
        "server.ai_runtime.provider_connectivity.load_provider_connectivity_settings",
        lambda config: SimpleNamespace(
            provider_id="deepseek", endpoint_origin="https://api.deepseek.com/v1"
        ),
    )
    service._require_deepseek_provider()


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
    service = AiShadowResearchAutomationService(
        state=SimpleNamespace(db=SimpleNamespace(_path=tmp_path / "app.db")),
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
    candidate = store.save_candidate(
        run_id="run-incomplete-gate",
        session_id="session-1",
        draft_id="draft-1",
        backtest_run_id="backtest-1",
        critique_id="critique-1",
        baseline_result_id=1,
        candidate_result_id=2,
        status="awaiting_human_approval",
        recommendation="paper_shadow_review",
        comparison={
            "promotion_gate": {
                "schema_version": "karkinos.strategy_advancement_gate.v2",
                "status": "pass",
                "blockers": [],
            }
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


def _result(*, total_return: float, sharpe: float, drawdown: float) -> dict:
    return {
        "initial_cash": 100_000.0,
        "final_equity": 100_000.0 * (1 + total_return),
        "total_return": total_return,
        "annual_return": total_return,
        "sharpe": sharpe,
        "sortino": sharpe,
        "max_drawdown": drawdown,
        "win_rate": 0.5,
        "duration_days": 100,
        "equity_curve": [
            {"timestamp": "2026-01-01T00:00:00", "equity": 100_000.0},
            {
                "timestamp": "2026-08-11T00:00:00",
                "equity": 100_000.0 * (1 + total_return),
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


def _prepared_baseline() -> PreparedBaseline:
    cost_model_reference = (
        "karkinos.backtest.reviewed_account_fee_schedule.v1:"
        f"fee_review_{'a' * 32}:{'b' * 64}"
    )
    return PreparedBaseline(
        seed_result_id=7,
        market_date="2026-08-11",
        snapshot={"snapshot_id": "sha256:latest-market"},
        request=BacktestRequest(
            start_date="2026-01-01",
            end_date="2026-08-11",
            initial_cash=100_000,
            strategy="dual_ma",
            assets=[{"symbol": "510300", "asset_class": "etf"}],
            oos_mode="rolling",
        ),
        result=_result(total_return=0.05, sharpe=0.6, drawdown=0.12),
        cost_model_reference=cost_model_reference,
        fee_schedule_evidence={
            "fee_schedule_review_id": "fee_review_" + "a" * 32,
            "fee_schedule_review_fingerprint": "sha256:" + "b" * 64,
        },
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
    candidate_payload = _result(total_return=0.12, sharpe=1.2, drawdown=0.08)
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
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        _complete_valuation,
    )

    result = await service.run_once()

    assert result["run_status"] == "completed"
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
    assert result["research_outcome"] == {
        "status": "no_new_candidate_current_strategy_unchanged",
        "new_candidate_winner_id": None,
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
async def test_full_cycle_is_idempotent_and_stops_at_human_research_pool(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    candidate_payload = _result(total_return=0.12, sharpe=1.2, drawdown=0.08)
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
    monkeypatch.setattr(
        "server.services.ai_shadow_research_automation.build_current_valuation_snapshot",
        _complete_valuation,
    )

    first = await service.run_once()
    replay = await service.run_once()

    assert first["run_status"] == "completed"
    assert replay["reused"] is True
    assert fixture.hypothesis_calls == 5
    assert fixture.hypothesis_requests[0].selection.valuation_snapshot_id == (
        "valuation-latest"
    )
    assert fixture.hypothesis_requests[0].selection.ledger_cutoff_id == 11
    assert fixture.hypothesis_requests[0].selection.has_account_binding is True
    assert fixture.backtest_calls == 5
    assert fixture.critique_calls == 5
    candidate = first["candidates"][0]
    assert candidate["recommendation"] == "keep_researching"
    assert candidate["status"] == "research_blocked"
    assert candidate["promotion_status"] == "blocked_by_evidence"
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
    closes = [10.0] * 20 + [20.0] * 20
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
    market.save_bars(
        symbol,
        BarFrequency.DAILY,
        bars,
        provider_name="deterministic_fixture",
        data_source="deterministic_fixture",
        adjustment_mode="none",
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
        ShadowResearchPolicy(baseline_backtest_result_id=seed_result_id)
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
