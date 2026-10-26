"""Normalized-notional privacy boundary tests for external strategy research."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from analytics.dataset_snapshot import backtest_dataset_snapshot_content_id
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.external_research_errors import (
    ExternalResearchInvalidResponseError,
)
from server.ai_runtime.formula_dsl import formula_operator_catalog
from server.ai_runtime.karkinos_source import _research_evidence_projection
from server.ai_runtime.provider_connectivity_contracts import (
    ProviderConnectivitySettings,
)
from server.ai_runtime.strategy_research_model_contract import (
    bind_and_validate_drafts,
    normalize_hypothesis_payload,
)
from server.ai_runtime.strategy_research_privacy import (
    NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
    build_normalized_lot_feasibility_evidence,
    build_normalized_research_pack,
    build_normalized_robustness_evidence,
    build_normalized_signal_execution_evidence,
    research_pack_privacy_violations,
)
from server.ai_runtime.strategy_research_provider import StrategyResearchModelProvider
from server.contracts.strategy_research import (
    CANONICAL_COST_MODEL_REFERENCE,
    STRATEGY_RESEARCH_MAX_INPUT_BYTES,
    StrategyResearchRejected,
    StrategyResearchSelection,
)
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_normalized_pack_exports_ratios_bps_and_counts_without_absolutes() -> None:
    pack = build_normalized_research_pack(
        performance={
            "initial_cash": 100_000,
            "final_equity": 110_000,
            "total_return": 0.1,
            "sharpe": 1.2,
            "max_drawdown": 0.08,
        },
        after_cost_evidence={
            "net_pnl": 10_000,
            "gross_pnl_before_costs": 10_100,
            "total_cost": 100,
            "fill_count": 4,
            "gross_turnover": 200_000,
        },
        cost_summary={
            "total_commission": 80,
            "total_slippage": 20,
            "total_trades": 4,
            "gross_turnover": 200_000,
        },
        research_evidence_bundle={
            "schema_version": "karkinos.research_evidence.v1",
            "gate_status": "pass",
            "strategy": {
                "strategy_id": "baseline",
                "params": {"window": 20, "initial_cash": 100_000},
                "private_extension": {"quantity": 100},
            },
            "trade_statistics": {
                "fill_count": 4,
                "trade_count": 4,
                "gross_turnover": 200_000,
                "total_commission": 80,
                "total_slippage": 20,
            },
            "promotion_gate": {
                "status": "pass",
                "manual_confirmation_required": True,
                "does_not_enable_execution": True,
                "next_review": "human review",
                "raw_account_gate": {"total_equity": 100_000},
            },
        },
        oos_validation={
            "validation_mode": "rolling",
            "validation_status": "pass",
            "folds": [{"fold_index": 1}, {"fold_index": 2}],
            "aggregate": {
                "mean_out_of_sample_return": 0.0,
                "worst_out_of_sample_return": -0.02,
            },
        },
    )

    assert pack["notional_policy_id"] == NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID
    assert pack["after_cost_summary"] == {
        "net_return_after_costs": 0.1,
        "gross_return_before_costs": 0.101,
        "total_cost_bps": 10.0,
        "fill_count": 4,
        "gross_turnover_ratio": 2.0,
        "limitations": [],
    }
    assert pack["cost_summary"]["total_commission_bps"] == 8.0
    assert pack["cost_summary"]["total_slippage_bps"] == 2.0
    assert pack["oos_validation"]["mean_out_of_sample_return"] == 0.0
    assert pack["oos_validation"]["fold_count"] == 2
    assert pack["research_evidence_bundle"]["strategy"] == {
        "strategy_id": "baseline",
        "name": None,
        "display_name": None,
        "params": {"window": 20},
    }
    assert pack["research_evidence_bundle"]["promotion_gate"] == {
        "status": "pass",
        "manual_confirmation_required": True,
        "does_not_enable_execution": True,
        "next_review": "human review",
    }
    assert research_pack_privacy_violations(pack) == []


@pytest.mark.unit
@pytest.mark.trading_safety
def test_privacy_guard_reports_nested_absolute_account_and_notional_keys() -> None:
    violations = research_pack_privacy_violations(
        {
            "saved_backtest": {"initial_cash": 100_000},
            "account": {"positions": [{"quantity": 100}]},
            "cost": {"total_commission": 5},
            "lot": {"lot_size": 100},
        }
    )

    assert violations == [
        "saved_backtest.initial_cash",
        "account.positions",
        "account.positions[0].quantity",
        "cost.total_commission",
        "lot.lot_size",
    ]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_robustness_feedback_preserves_losses_and_excludes_raw_financial_rows() -> None:
    feedback = build_normalized_robustness_evidence(
        {
            "parameter_robustness": {
                "rank_by": "after_cost_total_return",
                "selected_params": {"window": 20},
                "best_params": {"window": 40},
                "tested_count": 3,
                "tested_results": [
                    {
                        "params": {"window": window, "initial_cash": 100_000},
                        "score": score,
                        "private_extension": {"quantity": 100},
                    }
                    for window, score in [(10, -0.1), (20, -0.05), (40, 0.07)]
                ],
                "local_stability": {"stability_ratio": -0.9, "cash": 50_000},
                "overfitting_warnings": [
                    {"code": "local_peak_risk", "message": "Unstable", "cash": 50_000}
                ],
            },
            "market_regime_robustness": {
                "regime_definition": "equal_weight_frozen_close_return_sign.v1",
                "status": "blocked",
                "regimes": [
                    {
                        "name": "falling",
                        "observation_count": 12,
                        "candidate_net_return": "-0.12",
                        "market_return": "-0.2",
                        "status": "blocked",
                        "final_equity": 88_000,
                    }
                ],
                "aligned_observations": [{"cash": 50_000}],
            },
            "account_capital_constraint": {"total_equity": 100_000},
        }
    )
    parameter = feedback["parameter_robustness"]
    assert parameter["selected_params"] == {"window": 20}
    assert parameter["best_params"] == {"window": 40}
    assert parameter["tested_results"] == [
        {"params": {"window": window}, "score": score}
        for window, score in [(10, -0.1), (20, -0.05), (40, 0.07)]
    ]
    assert parameter["local_stability"]["stability_ratio"] == -0.9
    regime = feedback["market_regime_robustness"]
    assert regime["regimes"] == [
        {
            "name": "falling",
            "observation_count": 12,
            "candidate_net_return": -0.12,
            "market_return": -0.2,
            "status": "blocked",
        }
    ]
    assert "aligned_observations" not in regime
    assert "private_extension" not in str(feedback)
    assert research_pack_privacy_violations(feedback) == []


@pytest.mark.unit
@pytest.mark.trading_safety
def test_cost_feedback_preserves_failed_and_incomplete_scenarios_without_account_values():
    feedback = build_normalized_robustness_evidence(
        {
            "cost_sensitivity": [
                {
                    "slippage_bps": "10",
                    "max_volume_participation": "0.01",
                    "calibration": "explicit_research_assumption",
                    "total_return": -0.03,
                    "max_drawdown": 0.09,
                    "fill_count": 11,
                    "initial_cash": 123456,
                },
                {
                    "cost_assumptions": {
                        "slippage_bps": "25",
                        "max_volume_participation": "0.02",
                        "stock": {"min_commission": "5"},
                        "cash": 765432,
                    },
                    "status": "failed",
                    "failure_code": "simulation_incomplete",
                    "total_return": "NaN",
                    "private_extension": {"quantity": 100},
                },
            ]
        }
    )
    first, failed = feedback["cost_sensitivity"]
    assert first["total_return"] == -0.03
    assert first["slippage_bps"] == 10
    assert first["fill_count"] == 11
    assert first["status"] is None
    assert failed["slippage_bps"] == 25
    assert failed["max_volume_participation"] == 0.02
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "simulation_incomplete"
    assert failed["total_return"] is None
    assert failed["fill_count"] is None
    assert "private_extension" not in str(feedback)
    assert "min_commission" not in str(feedback)
    assert research_pack_privacy_violations(feedback) == []
    assert build_normalized_robustness_evidence({})["cost_sensitivity"] == []


@pytest.mark.unit
@pytest.mark.trading_safety
def test_critique_diagnostics_use_allowlists_and_remove_lot_size() -> None:
    signal = build_normalized_signal_execution_evidence(
        {
            "schema_version": "karkinos.ai.formula_signal_execution.v1",
            "entry_signal_count": 3,
            "exit_signal_count": 1,
            "entry_target_count": 2,
            "fill_count": 2,
            "allocation_slots": 1,
            "canonical_target_weight": 1.0,
            "contains_holding_quantity": False,
            "quantity": 100,
            "unreviewed_nested": {"cash": 50_000},
        }
    )
    lot = build_normalized_lot_feasibility_evidence(
        {
            "schema_version": "karkinos.ai.research_lot_feasibility.v1",
            "symbol_count": 3,
            "feasible_symbol_count": 2,
            "one_lot_too_expensive_count": 1,
            "lot_size": 100,
            "allocation_slots": 1,
            "target_weight": 1.0,
            "contains_holding_quantity": False,
            "unreviewed_nested": {"positions": []},
        }
    )

    assert "quantity" not in signal
    assert "unreviewed_nested" not in signal
    assert "lot_size" not in lot
    assert "unreviewed_nested" not in lot
    assert (
        research_pack_privacy_violations(
            {"signal_execution_evidence": signal, "lot_feasibility_evidence": lot}
        )
        == []
    )


@pytest.fixture
def full_scope_research():
    symbols = tuple(f"{600000 + index:06d}" for index in range(5372))
    scope = market_deployment_scope(MarketUniversePolicy())
    snapshot = {
        "schema_version": "karkinos.dataset_snapshot.v1",
        "date_range": {"start": "2020-01-02", "end": "2026-10-16"},
        "immutable_dataset_id": "sha256:" + "a" * 64,
        "market_data_binding": {"dataset_id": "sha256:" + "a" * 64},
        "point_in_time_verified": False,
        "research_use": "exploratory_backtest",
        "content_identity": {
            "algorithm": "sha256",
            "complete": True,
            "row_contract": "timestamp_ohlcva.v2",
        },
        "data_quality": {"status": "ok", "issues": []},
        "symbol_universe": [
            {
                "symbol": symbol,
                "asset_class": "stock",
                "row_count": 1643,
                "content_digest": content_fingerprint(symbol),
                "start_timestamp": "2020-01-02T15:00:00+08:00",
                "end_timestamp": "2026-10-16T15:00:00+08:00",
            }
            for symbol in symbols
        ],
    }
    snapshot["snapshot_id"] = backtest_dataset_snapshot_content_id(snapshot)
    selection = StrategyResearchSelection(
        saved_backtest_result_id=201,
        universe=symbols,
        asset_classes=("stock",) * len(symbols),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date="2020-01-02",
        end_date="2026-10-16",
        frequency="1d",
        initial_cash=1_000_000,
        cost_model_reference=CANONICAL_COST_MODEL_REFERENCE,
        deployment_scope=scope,
        portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID,
    )
    candidate = {
        "economic_hypothesis": "Sanitized frozen breakout research.",
        "selected_universe": list(symbols),
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
        },
        "frequency": "1d",
        "formula_ast": {
            "schema_version": "karkinos.ai.formula_ast.v1",
            "entry": {
                "op": "gt",
                "left": {"op": "field", "name": "close"},
                "right": {
                    "op": "lag",
                    "period": 1,
                    "input": {
                        "op": "rolling_max",
                        "window": 40,
                        "input": {"op": "field", "name": "close"},
                    },
                },
            },
            "exit": {
                "op": "lt",
                "left": {"op": "field", "name": "close"},
                "right": {
                    "op": "lag",
                    "period": 1,
                    "input": {
                        "op": "rolling_min",
                        "window": 20,
                        "input": {"op": "field", "name": "close"},
                    },
                },
            },
            "position_size": {"op": "equal_weight"},
        },
        "parameter_values": {"breakout_window": 40, "exit_window": 20},
        "parameter_ranges": {
            "breakout_window": [30, 40, 50],
            "exit_window": [10, 20, 25],
        },
        "entry_conditions": "Completed close above prior 40-close maximum.",
        "exit_conditions": "Completed close below prior 20-close minimum.",
        "position_sizing_hypothesis": "Frozen shared-capital policy.",
        "portfolio_constraints": deepcopy(scope),
        "cost_model_reference": selection.cost_model_reference,
        "required_evidence": ["Exact historical evidence."],
        "anti_lookahead_assumptions": ["Completed bars; strictly later fills."],
        "proposed_deterministic_tests": ["Replay exact frozen inputs."],
        "sample_split_plan": "Historical rolling OOS, separate future test.",
        "failure_conditions": ["After-cost loss."],
        "limitations": ["Historical PIT unverified."],
        "risk_impact": "Research can lose value.",
        "citations": ["saved_backtest_evidence.performance_summary"],
    }
    binding = dict(
        session_id="session-fixture",
        workflow_id="workflow-fixture",
        context_snapshot_id="context-fixture",
        context_fingerprint="b" * 64,
        evidence_reference_id="evidence-fixture",
        selection=selection,
        research_question="Review frozen research only.",
        iteration_context=None,
        provider_id="fixture",
        model_id="fixture-model",
    )
    draft = bind_and_validate_drafts({"drafts": [candidate]}, **binding)[0]
    assert draft["validation"]["status"] == "valid"
    bundle = {
        "schema_version": "karkinos.research_evidence.v1",
        "bundle_id": "fixture-bundle",
        "gate_status": "blocked",
        "dataset_snapshot_id": snapshot["snapshot_id"],
        "analyzers": [
            {
                "name": "research_admission",
                "status": "blocked",
                "summary": "Formal promotion is not admitted.",
                "details": {"snapshot": snapshot},
                "warnings": [],
                "limitations": ["Historical PIT remains unverified."],
            }
        ],
        "promotion_gate": {
            "status": "blocked",
            "manual_confirmation_required": True,
            "does_not_enable_execution": True,
        },
        "evidence_references": {
            "dataset_snapshot_id": snapshot["snapshot_id"],
            "snapshot_per_symbol": snapshot["symbol_universe"],
        },
        "trade_statistics": {
            "fill_count": 4,
            "gross_turnover": 800_000,
            "total_commission": 300,
            "total_slippage": 400,
        },
        "limitations": ["Exploratory historical evidence only."],
    }
    metrics = {
        "dataset_snapshot": snapshot,
        "research_evidence_bundle": bundle,
        "formula_binding": {
            "formula_ast": candidate["formula_ast"],
            "universe": list(symbols),
            "parameter_values": candidate["parameter_values"],
            "parameter_ranges": candidate["parameter_ranges"],
        },
        "evidence_bundle": {
            "net_pnl": 100_000,
            "gross_pnl_before_costs": 100_700,
            "total_cost": 700,
            "fill_count": 4,
            "gross_turnover": 800_000,
        },
        "oos_validation": {
            "validation_mode": "rolling",
            "validation_status": "pass",
            "equity_point_count": 1643,
            "folds": [{"fold_index": 1}, {"fold_index": 2}],
            "aggregate": {
                "mean_out_of_sample_return": -0.01,
                "worst_out_of_sample_return": -0.02,
            },
        },
        "parameter_robustness": {
            "tested_count": 9,
            "selected_params": candidate["parameter_values"],
            "best_params": candidate["parameter_values"],
            "tested_results": [
                {
                    "params": {"breakout_window": entry, "exit_window": exit},
                    "score": -0.02,
                }
                for entry in (30, 40, 50)
                for exit in (10, 20, 25)
            ],
            "local_stability": {"neighbor_count": 4, "stability_ratio": 0.8},
            "overfitting_warnings": [],
        },
        "market_regime_robustness": {
            "status": "blocked",
            "regime_count": 2,
            "failed_regime_count": 1,
            "regimes": [
                {"name": "rising", "observation_count": 1000, "status": "pass"},
                {"name": "falling", "observation_count": 643, "status": "blocked"},
            ],
            "aligned_observations": [
                {
                    "timestamp": str(index),
                    "market_return": -0.01,
                    "candidate_net_return": -0.02,
                }
                for index in range(1643)
            ],
        },
    }
    row = {
        "id": 201,
        "created_at": "2026-10-23T05:00:00+00:00",
        "initial_cash": 1_000_000,
        "final_equity": 1_100_000,
        "total_return": 0.1,
        "annual_return": 0.015,
        "sharpe": 0.5,
        "max_drawdown": 0.2,
        "duration_days": 2479,
        "config_json": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
            "assets": [
                {"symbol": symbol, "asset_class": "stock"} for symbol in symbols
            ],
        },
        "metrics_json": metrics,
        "cost_summary_json": {
            "total_commission": 300,
            "total_slippage": 400,
            "total_trades": 4,
            "gross_turnover": 800_000,
        },
    }
    return SimpleNamespace(
        selection=selection, candidate=candidate, binding=binding, draft=draft, row=row
    )


async def _full_scope_capture_and_critique(fixture):
    projection = await _research_evidence_projection(
        SimpleNamespace(get_backtest_result=lambda result_id: deepcopy(fixture.row)),
        tool_name="research_evidence.read",
        result_id=201,
    )
    metrics = fixture.row["metrics_json"]
    pack = build_normalized_research_pack(
        performance=fixture.row,
        after_cost_evidence=metrics["evidence_bundle"],
        cost_summary=fixture.row["cost_summary_json"],
        research_evidence_bundle=metrics["research_evidence_bundle"],
        oos_validation=metrics["oos_validation"],
    )
    critique = {
        "hypothesis_draft": fixture.draft,
        "canonical_backtest_result_id": 201,
        "canonical_backtest": {
            "result_id": 201,
            **pack["performance_summary"],
            "performance_summary": pack["performance_summary"],
            "after_cost_evidence": pack["after_cost_summary"],
            "cost_summary": pack["cost_summary"],
            "oos_validation": pack["oos_validation"],
            "research_evidence_bundle": pack["research_evidence_bundle"],
            **build_normalized_robustness_evidence(metrics),
        },
        "canonical_research_evidence": pack["research_evidence_bundle"],
        "required_binding_echo": {
            "canonical_backtest_result_id": 201,
            "formula_fingerprint": fixture.draft["formula_fingerprint"],
            "dataset_snapshot_id": fixture.selection.dataset_snapshot_id,
            "cost_model_reference": fixture.selection.cost_model_reference,
            **pack["performance_summary"],
            **pack["cost_summary"],
            "oos_validation_fingerprint": content_fingerprint(
                metrics["oos_validation"]
            ),
            "research_evidence_fingerprint": content_fingerprint(
                metrics["research_evidence_bundle"]
            ),
        },
    }
    return projection, critique


def _boundary_provider(fixture, critique, mode):
    return StrategyResearchModelProvider(
        provider_id="fixture",
        settings=ProviderConnectivitySettings(
            provider_id="fixture",
            model_name="fixture-model",
            base_url="https://example.invalid",
            api_key="synthetic-test-key",
            enabled=True,
        ),
        mode=mode,
        evidence_reference_id="evidence-fixture",
        selection=fixture.selection.to_external_dict(),
        research_question="Review frozen research only.",
        critique_input=critique,
        iteration_context=None,
        transport=SimpleNamespace(post_json=lambda **_: pytest.fail("No HTTP allowed")),
        monotonic=lambda: 0,
        timeout_seconds=1,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hypothesis", "critique"])
async def test_real_full_scope_capture_fits_model_boundary_without_losing_bindings(
    full_scope_research, monkeypatch, mode
):
    fixture = full_scope_research
    original = canonical_json(
        {
            "row": fixture.row,
            "draft": fixture.draft,
            "selection": fixture.selection.to_dict(),
        }
    )
    fingerprint = fixture.selection.fingerprint
    projection, critique = await _full_scope_capture_and_critique(fixture)
    assert projection.status == "blocked"
    assert projection.payload["analysis_ready"] is False
    capture_before = canonical_json(projection.payload)
    captured = []
    provider = _boundary_provider(fixture, critique, mode)

    def inspect_before_send(payload):
        captured.append(payload)
        raise RuntimeError("outbound_inspected_without_send")

    monkeypatch.setattr(provider, "_post_json", inspect_before_send)
    # Exercise only outbound assembly: the unchanged workflow must still reject
    # the blocked capture before reaching this boundary in a real model run.
    with pytest.raises(RuntimeError, match="outbound_inspected_without_send"):
        provider._invoke_external(
            evidence={"payload": projection.payload},
            account_evidence=None,
            catalog=formula_operator_catalog(),
            selection=fixture.selection.to_external_dict(),
        )
    content = captured[0]["messages"][1]["content"]
    outbound = json.loads(content)
    assert len(content.encode()) <= STRATEGY_RESEARCH_MAX_INPUT_BYTES
    assert research_pack_privacy_violations(outbound) == []
    identity = fixture.selection.to_external_dict()["universe"]
    assert identity == {
        "symbol_count": 5372,
        "universe_fingerprint": content_fingerprint(list(fixture.selection.universe)),
        "deployment_scope_fingerprint": fixture.selection.deployment_scope[
            "deployment_scope_fingerprint"
        ],
    }
    assert outbound["operator_frozen_selection"]["universe"] == identity
    assert outbound["saved_backtest_evidence"]["test_window"]["assets"] == {
        **identity,
        "asset_class_counts": {"stock": 5372},
    }
    assert (
        outbound["saved_backtest_evidence"]["research_evidence_bundle"]["gate_status"]
        == "blocked"
    )
    assert (
        outbound["saved_backtest_evidence"]["oos_validation"][
            "worst_out_of_sample_return"
        ]
        == -0.02
    )
    if mode == "critique":
        assert (
            outbound["critique_input"]["hypothesis_draft"]["selected_universe"]
            == identity
        )
        assert (
            outbound["critique_input"]["required_binding_echo"]
            == critique["required_binding_echo"]
        )
        assert (
            outbound["critique_input"]["canonical_backtest"]["parameter_robustness"][
                "tested_count"
            ]
            == 9
        )
        assert (
            outbound["critique_input"]["canonical_backtest"][
                "market_regime_robustness"
            ]["status"]
            == "blocked"
        )
    else:
        system = captured[0]["messages"][0]["content"]
        assert "10+ trades" not in system
        assert "operator-frozen risk and turnover constraints" in system
        assert "allocation slots are a maximum" in system
        assert "Zero fills or zero turnover fail" in system
        assert (
            "object, exact"
            in outbound["output_contract"]["field_types"]["selected_universe"]
        )
        assert (
            "portfolio_constraints"
            in outbound["output_contract"]["immutable_echo_fields"]
        )
        assert (
            "exact operator_frozen_selection.deployment_scope"
            in outbound["output_contract"]["field_types"]["portfolio_constraints"]
        )
    assert canonical_json(projection.payload) == capture_before
    assert (
        canonical_json(
            {
                "row": fixture.row,
                "draft": fixture.draft,
                "selection": fixture.selection.to_dict(),
            }
        )
        == original
    )
    assert fixture.selection.fingerprint == fingerprint
    assert (
        len(fixture.row["metrics_json"]["dataset_snapshot"]["symbol_universe"]) == 5372
    )
    print(
        json.dumps(
            {
                "mode": mode,
                "model_input_utf8_bytes": len(content.encode()),
                "complete_symbol_count": 5372,
            }
        )
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_compact_echo_restores_exact_internal_draft_and_formula_identity(
    full_scope_research,
):
    fixture = full_scope_research
    external = fixture.selection.to_external_dict()
    compact = {
        **deepcopy(fixture.candidate),
        "selected_universe": external["universe"],
        "portfolio_constraints": external["deployment_scope"],
    }
    before = canonical_json(compact)
    normalized = normalize_hypothesis_payload({"drafts": [compact]})
    restored = bind_and_validate_drafts(normalized, **fixture.binding)[0]
    assert restored == fixture.draft
    assert restored["selected_universe"] == list(fixture.selection.universe)
    assert canonical_json(compact) == before


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    "drift",
    [
        "count",
        "ordered_hash",
        "scope_hash",
        "extra_legacy_symbols",
        "wrong_legacy_list_with_correct_hash",
        "full_policy",
        "legacy_list_with_wrong_full_policy",
        "flattened_policy",
    ],
)
def test_compact_or_legacy_universe_cannot_hide_a_different_membership(
    full_scope_research, drift
):
    fixture = full_scope_research
    echo = deepcopy(fixture.selection.to_external_dict()["universe"])
    if drift == "count":
        echo["symbol_count"] -= 1
    elif drift == "ordered_hash":
        echo["universe_fingerprint"] = content_fingerprint(
            list(reversed(fixture.selection.universe))
        )
    elif drift == "scope_hash":
        echo["deployment_scope_fingerprint"] = "sha256:" + "f" * 64
    elif drift == "extra_legacy_symbols":
        echo["symbols"] = list(fixture.selection.universe[:-1])
    candidate = {**deepcopy(fixture.candidate), "selected_universe": echo}
    if drift == "wrong_legacy_list_with_correct_hash":
        candidate["selected_universe"] = list(fixture.selection.universe[:-1])
        candidate["universe_fingerprint"] = echo["universe_fingerprint"]
        with pytest.raises(
            ExternalResearchInvalidResponseError,
            match="hypothesis_draft_schema_invalid",
        ):
            normalize_hypothesis_payload({"drafts": [candidate]})
        return
    if drift in {"full_policy", "legacy_list_with_wrong_full_policy"}:
        if drift == "legacy_list_with_wrong_full_policy":
            candidate["selected_universe"] = list(fixture.selection.universe)
        candidate["portfolio_constraints"] = deepcopy(
            fixture.selection.to_external_dict()["deployment_scope"]
        )
        candidate["portfolio_constraints"]["universe_policy"]["allocation_slots"] = 5
    elif drift == "flattened_policy":
        candidate["portfolio_constraints"] = {
            "scope_kind": "full_declared_market",
            "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
            "allocation_slots": 4,
        }
    before = canonical_json(candidate)
    normalized = normalize_hypothesis_payload({"drafts": [candidate]})
    assert canonical_json(normalized["drafts"][0]) == before
    blocked = bind_and_validate_drafts(normalized, **fixture.binding)[0]
    assert blocked["validation"]["status"] == "blocked"
    expected_error = (
        "provider_changed_deployment_scope"
        if drift
        in {"full_policy", "legacy_list_with_wrong_full_policy", "flattened_policy"}
        else "provider_changed_universe"
    )
    assert expected_error in blocked["validation"]["errors"]
    assert canonical_json(normalized["drafts"][0]) == before


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["lot_size", "cash", "positions"])
async def test_full_scope_compaction_does_not_allow_private_account_facts(
    full_scope_research, monkeypatch, field
):
    fixture = full_scope_research
    projection, critique = await _full_scope_capture_and_critique(fixture)
    projection.payload["private_account"] = {field: 100}
    provider = _boundary_provider(fixture, critique, "critique")
    monkeypatch.setattr(
        provider, "_post_json", lambda _: pytest.fail("Privacy violation reached send")
    )
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="research_pack_privacy_violation"
    ):
        provider._invoke_external(
            evidence={"payload": projection.payload},
            account_evidence=None,
            catalog=formula_operator_catalog(),
            selection=fixture.selection.to_external_dict(),
        )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift", ["assets_missing", "assets_reordered", "draft_missing", "draft_reordered"]
)
async def test_full_scope_outbound_checks_legacy_lists_before_compaction(
    full_scope_research, monkeypatch, drift
):
    fixture = full_scope_research
    projection, critique = await _full_scope_capture_and_critique(fixture)
    critique = deepcopy(critique)
    if drift.startswith("assets"):
        rows = projection.payload["test_window"]["assets"]
        projection.payload["test_window"]["assets"] = (
            rows[:-1] if drift.endswith("missing") else list(reversed(rows))
        )
    else:
        draft = critique["hypothesis_draft"]
        rows = draft["selected_universe"]
        draft["selected_universe"] = (
            rows[:-1] if drift.endswith("missing") else list(reversed(rows))
        )
        # A valid declared hash must not hide the inconsistent complete list.
        assert draft["universe_fingerprint"] == content_fingerprint(
            list(fixture.selection.universe)
        )
    provider = _boundary_provider(fixture, critique, "critique")
    monkeypatch.setattr(
        provider,
        "_post_json",
        lambda _: pytest.fail("Mismatched membership reached send"),
    )
    with pytest.raises(
        ExternalResearchInvalidResponseError,
        match="full_scope_universe_binding_mismatch",
    ):
        provider._invoke_external(
            evidence={"payload": projection.payload},
            account_evidence=None,
            catalog=formula_operator_catalog(),
            selection=fixture.selection.to_external_dict(),
        )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy_form",
    ["canonical", "public", "legacy_lot_size_drift", "public_policy_drift"],
)
async def test_full_scope_critique_validates_policy_before_redaction(
    full_scope_research, monkeypatch, policy_form
):
    fixture = full_scope_research
    projection, critique = await _full_scope_capture_and_critique(fixture)
    critique = deepcopy(critique)
    constraints = critique["hypothesis_draft"]["portfolio_constraints"]
    if policy_form in {"public", "public_policy_drift"}:
        constraints = deepcopy(fixture.selection.to_external_dict()["deployment_scope"])
        critique["hypothesis_draft"]["portfolio_constraints"] = constraints
    if policy_form == "legacy_lot_size_drift":
        constraints["universe_policy"]["lot_size"] += 100
    elif policy_form == "public_policy_drift":
        constraints["universe_policy"]["allocation_slots"] += 1
    assert (
        constraints["deployment_scope_fingerprint"]
        == (fixture.selection.deployment_scope["deployment_scope_fingerprint"])
    )
    before = canonical_json(critique)
    provider = _boundary_provider(fixture, critique, "critique")

    def inspect_without_send(_):
        raise RuntimeError("outbound_inspected_without_send")

    monkeypatch.setattr(provider, "_post_json", inspect_without_send)
    rejected = policy_form in {"legacy_lot_size_drift", "public_policy_drift"}
    with pytest.raises(
        ExternalResearchInvalidResponseError if rejected else RuntimeError,
        match="full_scope_policy_binding_mismatch"
        if rejected
        else "outbound_inspected_without_send",
    ):
        provider._invoke_external(
            evidence={"payload": projection.payload},
            account_evidence=None,
            catalog=formula_operator_catalog(),
            selection=fixture.selection.to_external_dict(),
        )
    assert canonical_json(critique) == before


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_full_scope_preserves_oversized_financial_warning_and_fails_closed(
    full_scope_research, monkeypatch
):
    fixture = full_scope_research
    fixture.row["metrics_json"]["research_evidence_bundle"]["limitations"] = [
        "x" * STRATEGY_RESEARCH_MAX_INPUT_BYTES
    ]
    projection, critique = await _full_scope_capture_and_critique(fixture)
    provider = _boundary_provider(fixture, critique, "critique")
    monkeypatch.setattr(
        provider, "_post_json", lambda _: pytest.fail("Oversized evidence reached send")
    )
    with pytest.raises(
        StrategyResearchRejected, match="strategy_research_input_too_large"
    ):
        provider._invoke_external(
            evidence={"payload": projection.payload},
            account_evidence=None,
            catalog=formula_operator_catalog(),
            selection=fixture.selection.to_external_dict(),
        )
    assert projection.payload["research_evidence_bundle"]["limitations"] == [
        "x" * STRATEGY_RESEARCH_MAX_INPUT_BYTES
    ]
