from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.evidence_scope_review import EvidenceScopeReviewRepository
from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from analytics.backtest_market_regime_evidence import (
    build_backtest_market_regime_evidence,
)
from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from analytics.oos_validation import build_rolling_out_of_sample_validation
from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
)
from analytics.strategy_advancement_gate import (
    build_strategy_advancement_gate,
    strategy_advancement_backtest_view,
)
from analytics.sweep_robustness import build_sweep_robustness_evidence
from backtest.result import BacktestResult
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.strategy_research import StrategyResearchAuditStore
from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    ShadowResearchStore,
    _backtest_source_fingerprint,
)
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
    build_daily_strategy_promotion_binding,
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

_SYNTHETIC_ACCOUNT_TRUTH = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,broker_order_id,client_order_id
fixture-buy,trade_buy,2026-08-10T09:30:00+08:00,2026-08-11,510300.SH,synthetic ETF,etf,CNY,100,4.00,400.00,5.00,0.00,-405.00,99595.00,100,4.05,synthetic only,synthetic-broker-order-1,prior-manual-order-1
fixture-sell,trade_sell,2026-08-11T09:30:00+08:00,2026-08-12,510300.SH,synthetic ETF,etf,CNY,100,4.00,400.00,5.00,0.00,395.00,99990.00,0,0,synthetic only,,
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

    ShadowResearchStore(db._path).init()
    fixture_suffix = backtest_run_id.removeprefix("backtest-")
    run_id = f"run-{fixture_suffix}"
    session_id = f"session-{fixture_suffix}"
    draft_id = f"draft-{fixture_suffix}"
    research_evidence = {
        "schema_version": "karkinos.research_evidence.v1",
        "gate_status": "pass",
    }
    review = _seed_reviewed_fee_schedule(db)
    dataset_snapshot = _seed_frozen_dataset(db)
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
    baseline_metrics = _strategy_advancement_metrics(
        candidate=False,
        research_evidence=research_evidence,
        review=review,
        fee_binding=fee_binding,
        dataset_snapshot=dataset_snapshot,
    )
    candidate_metrics = _strategy_advancement_metrics(
        candidate=True,
        research_evidence=research_evidence,
        review=review,
        fee_binding=fee_binding,
        dataset_snapshot=dataset_snapshot,
    )
    rows = [
        _backtest_row(
            baseline_result_id,
            0.01,
            baseline_metrics,
            {
                "total_commission": 9.2,
                "total_slippage": 2.0,
                "total_trades": 1,
                "gross_turnover": 1200,
            },
        ),
        _backtest_row(
            candidate_result_id,
            0.02,
            candidate_metrics,
            {
                "total_commission": 9.2,
                "total_slippage": 2.0,
                "total_trades": 1,
                "gross_turnover": 1000,
            },
        ),
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
                    row["equity_curve_json"],
                    row["metrics_json"],
                    row["cost_summary_json"],
                ),
            )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_runs
            (run_id, market_date, input_fingerprint, status,
             baseline_seed_result_id, baseline_result_id,
             valuation_snapshot_id, ledger_cutoff_id, session_id,
             failure_code, candidate_count, created_at, updated_at)
            VALUES (?, '2026-08-12', ?, 'completed', ?, ?, ?, ?, ?, NULL, 1, ?, ?)
            """,
            (
                run_id,
                content_fingerprint({"run_id": run_id}),
                baseline_result_id,
                baseline_result_id,
                "valuation-fixture",
                42,
                session_id,
                "2026-08-12T07:00:00+00:00",
                "2026-08-12T07:00:00+00:00",
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
                session_id,
                draft_id,
                "sha256:formula-fixture",
                dataset_snapshot["snapshot_id"],
                reviewed_cost_model_reference(review),
                candidate_result_id,
                content_fingerprint(candidate_metrics["research_evidence_bundle"]),
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
                session_id,
                draft_id,
                backtest_run_id,
                json.dumps(critique, ensure_ascii=False, sort_keys=True),
                content_fingerprint(critique),
                "fixture-prompt-v1",
                "2026-08-12T07:00:00+00:00",
                "2026-08-12T07:00:00+00:00",
            ),
        )
    promotion_gate = build_strategy_advancement_gate(
        baseline=strategy_advancement_backtest_view(rows[0]),
        candidate=strategy_advancement_backtest_view(rows[1]),
        critique_evidence={
            "status": "completed",
            "critique_id": critique_id,
            "artifact_fingerprint": content_fingerprint(critique),
        },
    ).to_json_dict()
    assert promotion_gate["status"] == "pass"
    return {
        "baseline_source_fingerprint": _backtest_source_fingerprint(rows[0]),
        "candidate_source_fingerprint": _backtest_source_fingerprint(rows[1]),
        "deepseek_critique": critique,
        "promotion_gate": promotion_gate,
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
    comparison = seed_ai_shadow_canonical_sources(
        db,
        baseline_result_id=baseline_result_id,
        candidate_result_id=candidate_result_id,
        backtest_run_id=backtest_run_id,
        critique_id=critique_id,
    )
    comparison = {
        **comparison,
        "iteration_lineage": {
            "iteration_number": 1,
            "total_iterations": 1,
            "formula_fingerprint": "sha256:formula-fixture",
            "parent_candidate_id": None,
            "parent_draft_id": None,
            "parent_formula_fingerprint": None,
            "iteration_context_fingerprint": (
                "sha256:" + content_fingerprint({"fixture_id": fixture_id})
            ),
            "sequential_feedback_bound": True,
        },
    }
    promotion_gate = comparison["promotion_gate"]
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
    database_path = Path(db._path)
    daily_store = DailyStrategyArtifactStore(
        database_path,
        database_path.parent / "strategy-research-backups",
    )
    daily_store.record_daily_artifacts(
        run={
            "run_id": f"run-{fixture_id}",
            "market_date": "2026-08-12",
            "input_fingerprint": content_fingerprint({"run_id": f"run-{fixture_id}"}),
        },
        candidates=[candidate],
        drafts=[
            {
                "draft_id": f"draft-{fixture_id}",
                "economic_hypothesis": "Reviewed deterministic fixture hypothesis.",
                "risk_impact": "The bounded strategy can still lose capital.",
                "failure_conditions": [
                    "After-cost out-of-sample excess return turns non-positive."
                ],
                "limitations": [
                    "Historical deterministic evidence does not prove future profit."
                ],
                "anti_lookahead_assumptions": [
                    "Signals use only closed persisted market bars."
                ],
                "formula_ast": {"schema_version": "fixture"},
                "formula_fingerprint": "sha256:formula-fixture",
                "validation": {"status": "valid", "errors": []},
            }
        ],
        expected_candidate_count=1,
        run_status="completed",
        created_at="2026-08-12T07:04:00+00:00",
    )
    daily_artifacts = daily_store.require_verified_winner(
        candidate_id=candidate["candidate_id"],
        run_id=candidate["run_id"],
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
        "daily_strategy_artifact_binding": (
            build_daily_strategy_promotion_binding(daily_artifacts)
        ),
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
        "daily_artifacts": daily_artifacts,
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


def _evidence(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "evidence_fingerprint": _fingerprint(payload).removeprefix("sha256:"),
    }


def _market_regime_evidence() -> dict[str, Any]:
    timestamps = list(
        pd.to_datetime(
            ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
        )
    )
    return build_backtest_market_regime_evidence(
        result=SimpleNamespace(
            equity_curve=[
                (timestamp, equity)
                for timestamp, equity in zip(
                    timestamps, [100.0, 101.0, 102.0, 103.0, 104.0], strict=True
                )
            ]
        ),
        data_handlers={
            "510300.SH": SimpleNamespace(
                _df=pd.DataFrame(
                    {
                        "timestamp": timestamps,
                        "close": [100.0, 110.0, 100.0, 105.0, 100.0],
                    }
                )
            )
        },
    )


def _rolling_oos_evidence(*, candidate: bool) -> dict[str, Any]:
    timestamps = list(
        pd.to_datetime(
            [
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
                "2026-01-04",
                "2026-01-05",
                "2026-01-06",
            ]
        )
    )
    values = (
        [100_000, 102_000, 104_000, 106_000, 108_000, 110_000]
        if candidate
        else [100_000, 101_000, 102_000, 103_000, 104_000, 105_000]
    )
    return build_rolling_out_of_sample_validation(
        strategy_id="candidate" if candidate else "baseline",
        benchmark_role="reviewed_persisted_baseline",
        result=BacktestResult(
            equity_curve=[
                (timestamp, Decimal(value))
                for timestamp, value in zip(timestamps, values, strict=True)
            ],
            positions={},
            initial_cash=Decimal(values[0]),
            final_equity=Decimal(values[-1]),
        ),
        min_train_points=2,
        test_window_points=2,
        step_points=1,
    ).to_json_dict()


def _drawdown_equity_curve(total_return: float) -> list[dict[str, Any]]:
    timestamps = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
    values = [100_000.0, 95_000.0, 100_000.0 * (1 + total_return)]
    return [
        {"timestamp": timestamp.isoformat(), "equity": equity}
        for timestamp, equity in zip(timestamps, values, strict=True)
    ]


def _strategy_advancement_metrics(
    *,
    candidate: bool,
    research_evidence: dict[str, Any],
    review: Any,
    fee_binding: dict[str, Any],
    dataset_snapshot: dict[str, Any],
) -> dict[str, Any]:
    cost_model_reference = reviewed_cost_model_reference(review)
    account_capital = build_research_account_capital_evidence(
        initial_cash=100_000,
        account_evidence={
            "status": "complete",
            "persisted_facts_only": True,
            "record_fingerprint": "8" * 64,
            "valuation_snapshot_id": "valuation-fixture",
            "ledger_cutoff_id": 42,
            "payload": {
                "summary": {
                    "valuation_snapshot_id": "valuation-fixture",
                    "ledger_cutoff_id": 42,
                    "valuation_status": "complete",
                    "total_equity": 100_000,
                },
                "snapshot": {
                    "valuation_snapshot_id": "valuation-fixture",
                    "ledger_cutoff_id": 42,
                    "valuation_status": "complete",
                    "total_equity": 100_000,
                },
            },
        },
        fee_schedule_evidence={
            "account_specific": True,
            "broker_statement_reconciled": True,
            **fee_binding,
        },
        expected_valuation_snapshot_id="valuation-fixture",
        expected_ledger_cutoff_id=42,
    )
    oos_validation = _rolling_oos_evidence(candidate=candidate)
    total_return = 0.02 if candidate else 0.01
    gross_turnover = 1000 if candidate else 1200
    capacity_utilization = format(Decimal(gross_turnover) / Decimal("100000"), "f")
    total_cost = 11.2
    net_pnl = total_return * 100_000
    return {
        "research_evidence_bundle": research_evidence,
        "evidence_bundle": {
            "total_cost": total_cost,
            "net_pnl": net_pnl,
            "gross_pnl_before_costs": net_pnl + total_cost,
            "net_return": total_return,
            "gross_return_before_costs": (net_pnl + total_cost) / 100_000,
            "cost_to_initial_cash": total_cost / 100_000,
            "fill_count": 1,
            "gross_turnover": gross_turnover,
        },
        "dataset_snapshot": dataset_snapshot,
        "drawdown_evidence": build_backtest_drawdown_evidence(
            equity_curve=_drawdown_equity_curve(total_return),
        ),
        "oos_validation": oos_validation,
        "formula_binding": {"parameter_values": {"window": 5}},
        "formula_fingerprint": "sha256:formula-fixture",
        "parameter_robustness": build_sweep_robustness_evidence(
            results=[
                {"params": {"window": window}, "score": score}
                for window, score in (
                    (3, 0.85),
                    (4, 0.9),
                    (5, 1.0),
                    (6, 0.9),
                    (7, 0.85),
                )
            ],
            rank_by="after_cost_total_return",
            rank_direction="desc",
            selected_params={"window": 5},
        ),
        "market_regime_robustness": _market_regime_evidence(),
        "account_capital_constraint": account_capital,
        "capacity_review": _evidence(
            {
                "schema_version": "karkinos.backtest_capacity.v1",
                "status": "pass",
                "capacity_model_ref": (
                    "karkinos.backtest.capacity.daily_bar_participation.v1"
                ),
                "capacity_utilization_pct": capacity_utilization,
                "liquidity_utilization_pct": "0.5",
                "max_daily_volume_participation": "0.1",
                "gross_turnover": str(gross_turnover),
                "fill_count": 1,
                "observation_count": 1,
                "observations": [
                    {
                        "fill_index": 0,
                        "symbol": "510300.SH",
                        "timestamp": "2026-01-05T00:00:00",
                        "fill_notional": str(gross_turnover),
                        "bar_notional": "800000",
                        "raw_volume_participation": "0.05",
                        "capacity_utilization_pct": capacity_utilization,
                        "liquidity_utilization_pct": "0.5",
                    }
                ],
                "issues": [],
                "assumptions": ["deterministic fixture assumption"],
                "limitations": ["deterministic fixture limitation"],
                "persisted_market_data_only": True,
                "human_review_required": True,
                "authorizes_execution": False,
                "does_not_change_capital_authority": True,
            }
        ),
        "fee_component_evidence": _evidence(
            {
                "schema_version": "karkinos.backtest_fee_tax_evidence.v1",
                "status": "complete",
                "includes_taxes": True,
                "cost_model_reference": cost_model_reference,
                "fee_rule_id": cost_model_reference,
                "fee_rule_version": cost_model_reference,
                "fill_rule_ids": [cost_model_reference],
                "fill_rule_versions": [cost_model_reference],
                "fill_count": 1,
                "account_specific": True,
                "fee_schedule_source": (
                    "reviewed_account_truth_or_reconciled_fee_schedule"
                ),
                "fee_schedule_fingerprint": review.schedule_fingerprint,
                "broker_statement_reconciled": True,
                "fee_schedule_binding": fee_binding,
                "components": {
                    "commission": 8.0,
                    "stamp_tax": 1.0,
                    "transfer_fee": 0.2,
                    "other_fees": 0.0,
                    "slippage": 2.0,
                },
                "component_reconciliation_status": "pass",
                "issues": [],
                "model_limitations": [],
                "persisted_fill_evidence_only": True,
                "does_not_recalculate_backtest_pnl": True,
                "human_review_required": True,
                "authorizes_execution": False,
                "does_not_change_capital_authority": True,
                "limitations": [],
            }
        ),
    }


def _seed_frozen_dataset(db: Any) -> dict[str, Any]:
    symbol = Symbol("510300.SH")
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
            "open": [4.0, 4.1, 4.2],
            "high": [4.1, 4.2, 4.3],
            "low": [3.9, 4.0, 4.1],
            "close": [4.05, 4.15, 4.25],
            "volume": [1000, 1100, 1200],
        }
    )
    store = DataStore(db._path.parent)
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        frame,
        provider_name="fixture_market",
        data_source="fixture_market",
        adjustment_mode="qfq",
    )
    return build_backtest_dataset_snapshot(
        start_date="2026-01-01",
        end_date="2026-01-31",
        configured_source="fixture_market",
        data_handlers={
            symbol: DataHandler(
                frame,
                symbol,
                BarFrequency.DAILY,
                AssetClass.FUND,
            )
        },
        store=store,
        source_names=["fixture_market"],
    )


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
        "equity_curve_json": json.dumps(
            _drawdown_equity_curve(total_return), ensure_ascii=False, sort_keys=True
        ),
        "metrics_json": json.dumps(metrics, ensure_ascii=False, sort_keys=True),
        "cost_summary_json": json.dumps(costs, ensure_ascii=False, sort_keys=True),
    }
