from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.evidence_scope_review import EvidenceScopeReviewRepository
from analytics.strategy_advancement_gate import (
    STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES,
    StrategyAdvancementGate,
)
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.strategy_research import StrategyResearchAuditStore
from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    ShadowResearchStore,
    _backtest_source_fingerprint,
)
from server.services.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
    ReviewedFeeScheduleReviewRepository,
    reviewed_cost_model_reference,
)
from server.services.strategy_promotion_pipeline import (
    STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    StrategyPromotionPipeline,
)

_SYNTHETIC_ACCOUNT_TRUTH = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
fixture-buy,trade_buy,2026-08-10T09:30:00+08:00,2026-08-11,510300.SH,synthetic ETF,etf,CNY,100,4.00,400.00,5.00,0.00,-405.00,99595.00,100,4.05,synthetic only
fixture-sell,trade_sell,2026-08-11T09:30:00+08:00,2026-08-12,510300.SH,synthetic ETF,etf,CNY,100,4.00,400.00,5.00,0.00,395.00,99990.00,0,0,synthetic only
"""


def seed_ai_shadow_canonical_sources(
    db: Any,
    *,
    baseline_result_id: int,
    candidate_result_id: int,
    backtest_run_id: str,
    critique_id: str,
) -> dict[str, Any]:
    """Seed exact persisted research sources for promotion-binding tests."""

    research_evidence = {
        "schema_version": "karkinos.research_evidence.v1",
        "gate_status": "pass",
    }
    review = _seed_reviewed_fee_schedule(db)
    notional_envelope = review.preview["component_reconciliation"][
        "reconciled_notional_envelope"
    ]
    fee_binding = {
        "fee_schedule_review_id": review.review_id,
        "fee_schedule_review_fingerprint": review.review_fingerprint,
        "fee_schedule_preview_fingerprint": review.preview_fingerprint,
        "account_truth_import_run_id": review.account_truth_import_run_id,
        "account_truth_source_fingerprint": review.account_truth_source_fingerprint,
        "account_truth_scope_fingerprint": review.account_truth_scope_fingerprint,
        "effective_start_date": review.effective_start_date,
        "effective_end_date": review.effective_end_date,
        "fee_notional_envelope_enforced": True,
        "fee_notional_envelope_fingerprint": notional_envelope["evidence_fingerprint"],
        "fee_notional_covered_asset_classes": notional_envelope["asset_classes"],
    }
    metrics = {
        "research_evidence_bundle": research_evidence,
        "fee_component_evidence": {
            "cost_model_reference": reviewed_cost_model_reference(review),
            "account_specific": True,
            "broker_statement_reconciled": True,
            "fee_schedule_fingerprint": review.schedule_fingerprint,
            "fee_schedule_binding": fee_binding,
        },
    }
    costs = {"total_trades": 1, "gross_turnover": 1000}
    rows = [
        _backtest_row(baseline_result_id, 0.01, metrics, costs),
        _backtest_row(candidate_result_id, 0.02, metrics, costs),
    ]
    critique = {
        "schema_version": "karkinos.ai.strategy_backtest_critique.v1",
        "supported_claims": ["deterministic fixture"],
    }
    audit_store = StrategyResearchAuditStore(db._path)
    audit_store.init()
    with sqlite3.connect(db._path) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO backtest_results
                (id, created_at, config_json, initial_cash, final_equity,
                 total_return, sharpe, sortino, max_drawdown, win_rate,
                 duration_days, equity_curve_json, metrics_json, cost_summary_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    "2026-08-12T07:00:00+00:00",
                    "{}",
                    row["initial_cash"],
                    row["final_equity"],
                    row["total_return"],
                    row["sharpe"],
                    0,
                    row["max_drawdown"],
                    0,
                    1,
                    "[]",
                    row["metrics_json"],
                    row["cost_summary_json"],
                ),
            )
        conn.execute(
            """
            INSERT INTO ai_strategy_formula_backtests
            (backtest_run_id, idempotency_key, request_fingerprint, session_id,
             draft_id, formula_fingerprint, dataset_snapshot_id,
             cost_model_reference, status, canonical_backtest_result_id,
             evidence_fingerprint, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?)
            """,
            (
                backtest_run_id,
                f"idempotency:{backtest_run_id}",
                "request-fixture",
                "session-fixture",
                "draft-fixture",
                "sha256:formula-fixture",
                "sha256:dataset-fixture",
                "cost-fixture",
                candidate_result_id,
                content_fingerprint(research_evidence),
                "2026-08-12T07:00:00+00:00",
                "2026-08-12T07:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_strategy_backtest_critiques
            (critique_id, idempotency_key, request_fingerprint, session_id,
             draft_id, backtest_run_id, status, normalized_artifact_json,
             artifact_fingerprint, prompt_version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?)
            """,
            (
                critique_id,
                f"idempotency:{critique_id}",
                "request-fixture",
                "session-fixture",
                "draft-fixture",
                backtest_run_id,
                json.dumps(critique, ensure_ascii=False, sort_keys=True),
                content_fingerprint(critique),
                "fixture-prompt-v1",
                "2026-08-12T07:00:00+00:00",
                "2026-08-12T07:00:00+00:00",
            ),
        )
    return {
        "baseline_source_fingerprint": _backtest_source_fingerprint(rows[0]),
        "candidate_source_fingerprint": _backtest_source_fingerprint(rows[1]),
        "deepseek_critique": critique,
    }


def seed_approved_ai_shadow_strategy(
    db: Any,
    *,
    fixture_id: str,
    baseline_result_id: int,
    candidate_result_id: int,
) -> dict[str, Any]:
    """Seed one fully reviewed paper/shadow-only strategy for safety tests."""

    backtest_run_id = f"backtest-{fixture_id}"
    critique_id = f"critique-{fixture_id}"
    promotion_gate = StrategyAdvancementGate(
        status="pass",
        blockers=(),
        checks=tuple(
            {
                "name": name,
                "status": "pass",
                "blocker": None,
                "evidence": {},
            }
            for name in STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES
        ),
    ).to_json_dict()
    comparison = {
        "promotion_gate": promotion_gate,
        **seed_ai_shadow_canonical_sources(
            db,
            baseline_result_id=baseline_result_id,
            candidate_result_id=candidate_result_id,
            backtest_run_id=backtest_run_id,
            critique_id=critique_id,
        ),
    }
    store = ShadowResearchStore(db._path)
    store.init()
    candidate = store.save_candidate(
        run_id=f"run-{fixture_id}",
        session_id=f"session-{fixture_id}",
        draft_id=f"draft-{fixture_id}",
        backtest_run_id=backtest_run_id,
        critique_id=critique_id,
        baseline_result_id=baseline_result_id,
        candidate_result_id=candidate_result_id,
        status="awaiting_human_approval",
        recommendation="paper_shadow_review",
        comparison=comparison,
        now="2026-08-12T07:00:00+00:00",
    )
    approval = store.approve_candidate(
        candidate["candidate_id"],
        approved_by="human:fixture-owner",
        notes="Reviewed exact deterministic strategy advancement evidence.",
        confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
        now="2026-08-12T07:05:00+00:00",
    )
    strategy_id = f"ai_formula_shadow:{candidate['candidate_id']}"
    readiness = {
        "schema_version": "karkinos.ai.shadow_research_promotion_readiness.v1",
        "strategy_id": strategy_id,
        "promotion_status": "promotable_for_paper_review",
        "is_promotable": True,
        "missing_requirements": [],
        "backtest_result_id": candidate_result_id,
        "candidate_id": candidate["candidate_id"],
        "critique_id": critique_id,
        "comparison_fingerprint": content_fingerprint(comparison),
        "human_approval_id": approval["promotion_id"],
        "strategy_advancement_gate": promotion_gate,
        "live_like_enabled": False,
        "broker_submission_enabled": False,
    }
    pipeline = StrategyPromotionPipeline(db=db)
    pipeline.evaluate_readiness(readiness, actor="human:fixture-owner")
    state = pipeline.request_promotion(
        strategy_id,
        target_stage="paper_shadow",
        readiness=readiness,
        actor="human:fixture-owner",
        confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
        review_note="Reviewed exact deterministic strategy advancement evidence.",
    )
    return {
        "strategy_id": strategy_id,
        "candidate": candidate,
        "approval": approval,
        "readiness": readiness,
        "state": state,
    }


def _seed_reviewed_fee_schedule(db: Any):
    broker_preview = parse_broker_statement_csv(_SYNTHETIC_ACCOUNT_TRUTH)
    imported = BrokerEvidenceRepository(db._path).save_preview(
        broker_preview,
        source_name="synthetic-fixture.csv",
    )
    EvidenceScopeReviewRepository(db._path).record_review(
        import_run_id=imported.import_run_id,
        import_file_fingerprint=imported.file_fingerprint,
        observed_scope_fingerprint="sha256:" + "9" * 64,
        provider="synthetic_broker",
        account_alias="fixture_account",
        account_reference_hash="sha256:" + "3" * 64,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-12-31",
        asset_classes=["etf"],
        full_account_scope_attested=True,
        reviewer="fixture_owner",
    )
    schedule = {
        "schedule_id": "fixture_schedule",
        "account_profile_id": "fixture_account",
        "broker_name": "fixture_broker",
        "stock_a_commission_rate": "0.0001",
        "stock_a_min_commission": "5",
        "fund_etf_commission_rate": "0.0001",
        "fund_etf_min_commission": "5",
        "stamp_tax_rate": "0.0005",
        "transfer_fee_rate": "0.00001",
        "fund_etf_transfer_fee_rate": "0.00001",
        "exchange_transfer_fee_rates": {},
        "other_fee_rate": "0",
        "money_precision": None,
        "money_rounding_mode": "none",
        "limitations": [],
    }
    notional_envelope_core = {
        "schema_version": ("karkinos.account_truth.reviewed_fee_notional_envelope.v1"),
        "enforcement_mode": "maximum_matched_historical_gross_by_asset_class",
        "asset_classes": ["etf"],
        "limits": {
            "etf": {
                "maximum_gross_amount": "400.00",
                "matched_trade_count": 2,
            }
        },
        "authorizes_execution": False,
        "does_not_change_capital_authority": True,
    }
    notional_envelope = {
        **notional_envelope_core,
        "evidence_fingerprint": _fingerprint(notional_envelope_core),
    }
    core = {
        "schema_version": REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
        "status": "ready",
        "schedule": schedule,
        "schedule_fingerprint": _fingerprint(schedule),
        "effective_start_date": "2026-01-01",
        "effective_end_date": "2026-12-31",
        "account_truth_import_run_id": imported.import_run_id,
        "account_truth_source_fingerprint": "sha256:" + "1" * 64,
        "account_truth_scope_fingerprint": "sha256:" + "2" * 64,
        "account_reference_hash": "sha256:" + "3" * 64,
        "account_truth_readiness_status": "ready",
        "account_truth_promotion_status": "clear",
        "component_reconciliation": {
            "status": "pass",
            "reconciled_notional_envelope": notional_envelope,
        },
        "issues": [],
        "persisted_broker_events_only": True,
        "stores_broker_event_details": False,
        "provider_contacted": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    preview = {**core, "preview_fingerprint": _fingerprint(core)}
    return ReviewedFeeScheduleReviewRepository(db._path).record_review(
        preview=preview,
        expected_preview_fingerprint=preview["preview_fingerprint"],
        reviewer="fixture_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _backtest_row(
    result_id: int,
    total_return: float,
    metrics: dict[str, Any],
    costs: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": result_id,
        "initial_cash": 100_000.0,
        "final_equity": 100_000.0 * (1 + total_return),
        "total_return": total_return,
        "sharpe": 1.0 + total_return,
        "max_drawdown": 0.05,
        "metrics_json": json.dumps(metrics, ensure_ascii=False, sort_keys=True),
        "cost_summary_json": json.dumps(costs, ensure_ascii=False, sort_keys=True),
    }
