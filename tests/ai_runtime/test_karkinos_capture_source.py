from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from analytics.backtest_fee_tax_evidence import build_backtest_fee_tax_evidence
from analytics.dataset_snapshot import (
    backtest_dataset_snapshot_content_id,
    build_backtest_dataset_snapshot,
    dataset_simulation_admission,
)
from analytics.oos_validation import build_rolling_out_of_sample_validation
from analytics.research_evidence import (
    AfterCostAnalyzer,
    AnalyzerResult,
    DataQualityAnalyzer,
    OosAnalyzer,
    build_research_evidence_bundle,
)
from backtest.metrics import (
    build_after_cost_evidence,
    calculate_backtest_metrics,
    summarize_fill_costs,
)
from backtest.result import BacktestResult
from core.events import FillEvent
from core.types import AssetClass, BarFrequency, InstrumentType, OrderSide, Symbol
from data.handler import DataHandler
from server.ai_runtime.capture import (
    CAPTURE_CONFIRMATION,
    CaptureEvidenceType,
    CaptureSelectionError,
    HumanContextCaptureRequest,
)
from server.ai_runtime.evidence import CanonicalEvidenceRecord, EvidenceIdentityMismatch
from server.ai_runtime.external_memory_analysis_output import redact_sensitive_content
from server.ai_runtime.formula_dsl import FormulaBinding
from server.ai_runtime.karkinos_source import (
    CaptureProjectionReaders,
    PersistedKarkinosCaptureSource,
    _research_evidence_projection,
)
from server.composition.ai_application_services import build_capture_projection_readers
from server.contracts.strategy_research import StrategyResearchSelection
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
)

NOW = "2026-07-13T12:30:00+00:00"
VALUATION_ID = "valuation-source-001"
LEDGER_CUTOFF_ID = 91
LEDGER_FINGERPRINT = "ledger-source-fingerprint-001"


def _refresh_native_report(row, *, analyzers=None):
    metrics = row["metrics_json"]
    snapshot = metrics["dataset_snapshot"]
    snapshot.pop("snapshot_id", None)
    snapshot["snapshot_id"] = backtest_dataset_snapshot_content_id(snapshot)
    metrics["source_selection"]["dataset_snapshot_id"] = snapshot["snapshot_id"]
    metrics["formula_binding"]["dataset_snapshot_id"] = snapshot["snapshot_id"]
    metrics["formula_fingerprint"] = FormulaBinding(
        **metrics["formula_binding"]
    ).fingerprint
    row["config_json"]["params"]["formula_fingerprint"] = metrics["formula_fingerprint"]
    metrics["research_evidence_bundle"] = build_research_evidence_bundle(
        metrics_json=metrics,
        cost_summary_json=row["cost_summary_json"],
        evidence_json=metrics["evidence_bundle"],
        strategy_metadata=metrics["strategy_metadata"],
        analyzers=analyzers,
    )


def _set_native_report_result(row, equity_values):
    timestamps = pd.bdate_range("2026-01-05", periods=6).to_pydatetime()
    fills = [
        FillEvent(
            timestamp=timestamps[index],
            fill_id=f"fixture-fill-{index}",
            order_id=f"fixture-order-{index}",
            symbol=Symbol("600001"),
            side=OrderSide.BUY,
            fill_price=Decimal("10"),
            fill_quantity=Decimal("50"),
            commission=Decimal("50"),
            slippage=Decimal("100"),
            fee_rule_id="fixture-default-estimate",
            fee_rule_version="karkinos.backtest.multi_asset_commission.default.v1",
            fee_breakdown={
                "commission": "50",
                "stamp_tax": "0",
                "transfer_fee": "0",
                "other_fees": "0",
                "total_fee": "50",
            },
        )
        for index in (2, 4)
    ]
    result = BacktestResult(
        equity_curve=list(
            zip(timestamps, (Decimal(value) for value in equity_values), strict=True)
        ),
        positions={},
        initial_cash=Decimal("1000000"),
        final_equity=Decimal(equity_values[-1]),
        fills=fills,
    )
    costs = summarize_fill_costs(fills)
    performance = calculate_backtest_metrics(
        result.equity_curve,
        initial_cash=result.initial_cash,
        final_equity=result.final_equity,
        cost_summary=costs,
    ).to_json_dict()
    row.update(performance)
    row["equity_curve_json"] = [
        {"timestamp": timestamp.isoformat(), "equity": float(value)}
        for timestamp, value in result.equity_curve
    ]
    row["cost_summary_json"] = costs.to_json_dict()
    row["metrics_json"].update(
        performance,
        evidence_bundle=build_after_cost_evidence(
            initial_cash=result.initial_cash,
            final_equity=result.final_equity,
            cost_summary=costs,
        ).to_json_dict(),
        drawdown_evidence=build_backtest_drawdown_evidence(
            equity_curve=result.equity_curve, initial_cash=result.initial_cash
        ),
        fee_component_evidence=build_backtest_fee_tax_evidence(
            fills=fills,
            cost_model_reference="karkinos.backtest.multi_asset_commission.default.v1",
        ),
        oos_validation=build_rolling_out_of_sample_validation(
            strategy_id="fixture_strategy",
            benchmark_role="current_persisted_baseline",
            result=result,
            min_train_points=2,
            test_window_points=2,
            step_points=1,
            benchmark_return=Decimal("0"),
        ).to_json_dict(),
    )


@pytest.fixture
def native_exploratory_report():
    # Native selection order and snapshot-builder order deliberately differ.
    symbols = ("600002", "600001")
    frame = pd.DataFrame(
        {
            "timestamp": pd.bdate_range("2026-01-05", periods=6),
            "open": [10, 11, 12, 13, 14, 15],
            "high": [10, 11, 12, 13, 14, 15],
            "low": [10, 11, 12, 13, 14, 15],
            "close": [10, 11, 12, 13, 14, 15],
            "volume": [100000] * 6,
        }
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date="2026-01-05",
        end_date="2026-01-12",
        configured_source="fixture",
        source_names=["fixture"],
        store=None,
        data_handlers={
            Symbol(symbol): DataHandler(
                frame.copy(),
                Symbol(symbol),
                BarFrequency.DAILY,
                AssetClass.STOCK,
                InstrumentType.STOCK,
            )
            for symbol in symbols
        },
        research_dataset_binding={
            "dataset_id": "sha256:" + "a" * 64,
            "cutoff": NOW,
            "price_basis": "unadjusted",
            "cross_source_verified": True,
            "point_in_time_verified": False,
            "limitations": [
                "Historical PIT is unverified.",
                "Unadjusted research bars.",
            ],
        },
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=183,
        universe=symbols,
        asset_classes=("stock", "stock"),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date="2026-01-05",
        end_date="2026-01-12",
        frequency="1d",
        initial_cash=1_000_000,
        deployment_scope=market_deployment_scope(
            MarketUniversePolicy(minimum_master_member_count=2, minimum_history_rows=2)
        ),
        portfolio_policy_id=market_deployment_scope(MarketUniversePolicy())[
            "portfolio_policy_id"
        ],
    )
    field = {"op": "field", "name": "close"}
    binding = FormulaBinding(
        formula_ast={
            "schema_version": "karkinos.ai.formula_ast.v1",
            "entry": {
                "op": "gt",
                "left": field,
                "right": {"op": "lag", "period": 1, "input": field},
            },
            "exit": {
                "op": "lt",
                "left": field,
                "right": {"op": "lag", "period": 1, "input": field},
            },
            "position_size": {"op": "equal_weight"},
        },
        universe=selection.universe,
        dataset_snapshot_id=selection.dataset_snapshot_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        frequency="1d",
        cost_model_reference=selection.cost_model_reference,
        anti_lookahead_assumptions=("Trade only after observed bars.",),
        parameter_values={},
        parameter_ranges={},
        initial_cash=selection.initial_cash,
    )
    row = {
        "id": 201,
        "created_at": NOW,
        "config_json": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
            "initial_cash": selection.initial_cash,
            "params": {
                "formula_fingerprint": binding.fingerprint,
                "portfolio_policy_id": selection.portfolio_policy_id,
                "deployment_scope": deepcopy(selection.deployment_scope),
            },
            "assets": [
                {"symbol": symbol, "asset_class": "stock"} for symbol in symbols
            ],
        },
        "metrics_json": {
            "dataset_snapshot": snapshot,
            "source_selection": selection.to_dict(),
            "formula_binding": binding.to_dict(),
            "formula_fingerprint": binding.fingerprint,
            "strategy_metadata": {"strategy_id": "fixture_strategy"},
        },
    }
    _set_native_report_result(row, [1000000, 1020000, 800000, 950000, 1050000, 1100000])
    _refresh_native_report(row)
    return row


async def _project_native_report(row):
    return await _research_evidence_projection(
        SimpleNamespace(get_backtest_result=lambda result_id: deepcopy(row)),
        tool_name="research_evidence.read",
        result_id=201,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_serialized_native_report_retains_analysis_admission(
    native_exploratory_report,
):
    row = native_exploratory_report
    for field in ("metrics_json", "config_json", "cost_summary_json"):
        row[field] = json.dumps(row[field])
    projection = await _project_native_report(row)
    assert projection.status == "complete"
    assert projection.payload["research_evidence_bundle"]["gate_status"] == "blocked"


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_complete_native_report_is_readable_with_formal_admission_blocked(
    native_exploratory_report, monkeypatch
):
    row = native_exploratory_report
    for name in (
        "load_immutable_dataset_inputs",
        "verify_backtest_dataset_snapshot_replay",
    ):
        monkeypatch.setattr(
            "analytics.dataset_snapshot." + name,
            lambda *a, **k: pytest.fail("Capture must not reread CAS"),
        )
    before = deepcopy(row)
    projection = await _project_native_report(row)
    assert projection.status == "complete"
    assert projection.payload["analysis_ready"] is True
    assert projection.payload["analysis_blocking_reasons"] == []
    assert row == before
    assert (
        row["metrics_json"]["source_selection"]["saved_backtest_result_id"] != row["id"]
    )
    assert [item["symbol"] for item in projection.payload["test_window"]["assets"]] == [
        "600002",
        "600001",
    ]
    assert [
        item["symbol"]
        for item in row["metrics_json"]["dataset_snapshot"]["symbol_universe"]
    ] == ["600001", "600002"]
    bundle = projection.payload["research_evidence_bundle"]
    assert bundle["gate_status"] == bundle["promotion_gate"]["status"] == "blocked"
    assert (
        next(
            item for item in bundle["analyzers"] if item["name"] == "research_admission"
        )["status"]
        == "blocked"
    )
    admission = projection.payload["dataset_simulation_admission"]
    assert admission["purpose"] == "research_selection_and_simulation"
    assert admission["historical_pit_verified"] is False
    assert admission["account_publication_admitted"] is False
    assert projection.payload["authority_effect"] == "research_only"
    record = CanonicalEvidenceRecord.capture(
        tool_name="research_evidence.read",
        valuation_snapshot_id="research-only:fixture",
        ledger_cutoff_id=0,
        ledger_fingerprint="research-only:fixture",
        status=projection.status,
        as_of=NOW,
        source_schema_version=projection.source_schema_version,
        payload=projection.payload,
        captured_at=NOW,
    )
    assert record.authoritative is True
    exported, _ = redact_sensitive_content(record.payload, path="payload")
    assert exported == projection.payload


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    [
        "performance_missing",
        "performance_nan",
        "performance_infinite",
        "performance_negative_notional",
        "after_cost_missing",
        "after_cost_partial",
        "metrics_json",
        "config_json",
        "cost_json",
        "bundle_hash",
        "snapshot_hash",
        "window",
        "asset_class",
        "asset_order",
        "typed_namespace",
        "snapshot_frequency",
        "snapshot_asset_class",
        "request_typed_namespace",
        "coordinated_typed_namespace",
        "row_id",
        "row_id_bool",
        "source_selection",
        "formula_hash",
        "formula_order",
        "no_native_scope",
        "request_formula_hash",
        "request_scope",
        "duplicate_snapshot_identity",
        "snapshot_row_count",
        "cost_nonfinite",
        "fractional_fill_count",
    ],
)
async def test_exploratory_label_does_not_admit_incomplete_or_drifted_report(
    native_exploratory_report, drift
):
    row = native_exploratory_report
    metrics = row["metrics_json"]
    if drift == "performance_missing":
        row.pop("final_equity")
    elif drift == "performance_nan":
        row["final_equity"] = float("nan")
    elif drift == "performance_infinite":
        row["max_drawdown"] = float("inf")
    elif drift == "performance_negative_notional":
        row["initial_cash"] = -1
    elif drift == "after_cost_missing":
        metrics.pop("evidence_bundle")
    elif drift == "after_cost_partial":
        metrics["evidence_bundle"].pop("net_pnl")
    elif drift == "metrics_json":
        row["metrics_json"] = "{invalid"
    elif drift == "config_json":
        row["config_json"] = "[]"
    elif drift == "cost_json":
        row["cost_summary_json"] = "null"
    elif drift == "bundle_hash":
        metrics["research_evidence_bundle"]["limitations"].append("unbound drift")
    elif drift == "snapshot_hash":
        metrics["dataset_snapshot"]["snapshot_id"] = "sha256:" + "b" * 64
    elif drift == "window":
        row["config_json"]["end_date"] = "2026-01-08"
    elif drift == "asset_class":
        row["config_json"]["assets"][0]["asset_class"] = "etf"
    elif drift == "asset_order":
        row["config_json"]["assets"].reverse()
    elif drift == "typed_namespace":
        metrics["dataset_snapshot"]["symbol_universe"][0]["instrument_type"] = "etf"
        _refresh_native_report(row)
    elif drift == "snapshot_frequency":
        metrics["dataset_snapshot"]["symbol_universe"][0]["frequency"] = "1h"
        _refresh_native_report(row)
    elif drift == "snapshot_asset_class":
        metrics["dataset_snapshot"]["symbol_universe"][0]["asset_class"] = "etf"
        _refresh_native_report(row)
    elif drift == "request_typed_namespace":
        row["config_json"]["assets"][0]["instrument_type"] = "etf"
    elif drift == "coordinated_typed_namespace":
        item = metrics["dataset_snapshot"]["symbol_universe"][0]
        item["instrument_type"] = "etf"
        next(
            asset
            for asset in row["config_json"]["assets"]
            if asset["symbol"] == item["symbol"]
        )["instrument_type"] = "etf"
        _refresh_native_report(row)
    elif drift == "row_id":
        row["id"] = 202
    elif drift == "row_id_bool":
        row["id"] = True
    elif drift == "source_selection":
        metrics["source_selection"]["universe"].reverse()
    elif drift == "formula_hash":
        metrics["formula_fingerprint"] = "sha256:" + "c" * 64
    elif drift == "formula_order":
        metrics["formula_binding"]["universe"].reverse()
        metrics["formula_fingerprint"] = FormulaBinding(
            **metrics["formula_binding"]
        ).fingerprint
    elif drift == "no_native_scope":
        metrics.pop("source_selection")
    elif drift == "request_formula_hash":
        row["config_json"]["params"]["formula_fingerprint"] = "sha256:" + "d" * 64
    elif drift == "request_scope":
        row["config_json"]["params"]["deployment_scope"]["universe_policy"][
            "allocation_slots"
        ] = 2
    elif drift == "duplicate_snapshot_identity":
        rows = metrics["dataset_snapshot"]["symbol_universe"]
        rows[1]["symbol"] = rows[0]["symbol"]
        _refresh_native_report(row)
    elif drift == "snapshot_row_count":
        metrics["dataset_snapshot"]["row_count"] += 1
        _refresh_native_report(row)
    elif drift == "cost_nonfinite":
        row["cost_summary_json"]["total_slippage"] = float("inf")
    elif drift == "fractional_fill_count":
        metrics["evidence_bundle"]["fill_count"] = 0.5
    if isinstance(row["metrics_json"], dict) and drift != "snapshot_hash":
        assert (
            dataset_simulation_admission(metrics["dataset_snapshot"])["status"]
            == "admitted"
        )
    projection = await _project_native_report(row)
    assert projection.status != "complete"
    assert projection.payload["analysis_ready"] is False
    assert "dataset_simulation_admission" not in projection.payload


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exploratory_report_preserves_losses_and_degraded_oos(
    native_exploratory_report,
):
    row = native_exploratory_report
    _set_native_report_result(row, [1000000, 980000, 960000, 940000, 920000, 900000])
    _refresh_native_report(row)
    projection = await _project_native_report(row)
    assert projection.status == "complete"
    assert projection.payload["performance_summary"]["total_return"] == -0.1
    assert (
        next(
            item
            for item in projection.payload["research_evidence_bundle"]["analyzers"]
            if item["name"] == "oos"
        )["status"]
        == "degraded"
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    [
        "final_equity",
        "total_return",
        "missing_rolling_oos",
        "rolling_oos_conflict",
        "drawdown_missing",
        "drawdown_equity_conflict",
        "fee_components_missing",
        "fee_summary_conflict",
        "gross_pnl_conflict",
        "turnover_conflict",
    ],
)
async def test_native_analysis_requires_reproducible_infrastructure_and_after_cost(
    native_exploratory_report, drift
):
    from analytics.normalized_research_gate import baseline_research_evidence_blockers
    from analytics.strategy_advancement_evidence import (
        after_cost_evidence_complete,
        payload_fingerprint,
    )
    from analytics.strategy_advancement_gate import strategy_advancement_backtest_view

    row = native_exploratory_report
    view = strategy_advancement_backtest_view(row)
    assert baseline_research_evidence_blockers(view) == []
    assert after_cost_evidence_complete(view) is True
    assert (await _project_native_report(row)).status == "complete"
    metrics = row["metrics_json"]
    if drift == "final_equity":
        row["final_equity"] = 9999999
    elif drift == "total_return":
        row["total_return"] = 0.99
    elif drift == "missing_rolling_oos":
        metrics.pop("oos_validation")
    elif drift == "rolling_oos_conflict":
        oos = metrics["oos_validation"]
        oos["folds"][0]["out_of_sample"]["net_return"] += 0.01
        oos["evidence_fingerprint"] = payload_fingerprint(
            {key: value for key, value in oos.items() if key != "evidence_fingerprint"}
        )
    elif drift == "drawdown_missing":
        metrics.pop("drawdown_evidence")
    elif drift == "drawdown_equity_conflict":
        row["equity_curve_json"][-1]["equity"] += 1
    elif drift == "fee_components_missing":
        metrics.pop("fee_component_evidence")
    elif drift == "fee_summary_conflict":
        row["cost_summary_json"]["total_commission"] += 1
    elif drift == "gross_pnl_conflict":
        metrics["evidence_bundle"]["gross_pnl_before_costs"] += 1
    elif drift == "turnover_conflict":
        metrics["evidence_bundle"]["gross_turnover"] += 1
    _refresh_native_report(row)
    assert metrics["research_evidence_bundle"]["gate_status"] == "blocked"
    assert (
        dataset_simulation_admission(metrics["dataset_snapshot"])["status"]
        == "admitted"
    )
    projection = await _project_native_report(row)
    assert projection.status == "blocked"
    assert projection.payload["analysis_ready"] is False
    assert "dataset_simulation_admission" not in projection.payload


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown_blocked", "malformed_oos"])
async def test_other_blockers_cannot_be_hidden_as_formal_admission(
    native_exploratory_report, failure
):
    row = native_exploratory_report
    if failure == "unknown_blocked":

        class UnknownAnalyzer:
            name = "unknown_check"

            def analyze(self, context):
                return AnalyzerResult(
                    name=self.name, status="blocked", summary="Unknown blocker."
                )

        _refresh_native_report(
            row,
            analyzers=[
                DataQualityAnalyzer(),
                AfterCostAnalyzer(),
                OosAnalyzer(),
                UnknownAnalyzer(),
            ],
        )
    else:
        row["metrics_json"]["chronological_validation"] = {
            "schema_version": "malformed"
        }
        _refresh_native_report(row)
    projection = await _project_native_report(row)
    assert projection.status == "blocked"
    assert projection.payload["analysis_ready"] is False


class FixtureModel:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        for key, value in payload.items():
            setattr(self, key, value)

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return dict(self._payload)


class FixtureDatabase:
    def get_runtime_control_sync(self, key: str):
        assert key == "account_strategy_assignment"
        return None

    def get_valuation_snapshot_sync(self, snapshot_id: str):
        if snapshot_id != VALUATION_ID:
            return None
        return {
            "snapshot_id": VALUATION_ID,
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
            "as_of": NOW,
        }

    async def get_backtest_result(self, result_id: int):
        if result_id != 17:
            return None
        return {
            "id": 17,
            "created_at": NOW,
            "metrics_json": json.dumps(
                {
                    "research_evidence_bundle": {
                        "schema_version": "karkinos.research_evidence.v1",
                        "bundle_id": "research-17",
                        "gate_status": "degraded",
                    }
                }
            ),
        }

    def get_paper_shadow_run_sync(self, run_id: str):
        if run_id != "shadow-17":
            return None
        return {
            "run_id": "shadow-17",
            "input_fingerprint": "shadow-input-17",
            "status": "review_required",
            "created_at": NOW,
            "updated_at": NOW,
            "payload_json": json.dumps(
                {
                    "schema_version": "karkinos.paper_shadow_run.v1",
                    "execution_mode": "paper_shadow",
                }
            ),
            "limitations_json": json.dumps(["manual review required"]),
        }


def _request() -> HumanContextCaptureRequest:
    return HumanContextCaptureRequest(
        idempotency_key="source-all-001",
        requested_by="human:reese",
        research_question="Review all exact persisted sources",
        account_alias="primary",
        evidence_types=tuple(CaptureEvidenceType),
        confirmation=CAPTURE_CONFIRMATION,
        backtest_result_id=17,
        paper_shadow_run_id="shadow-17",
        strategy_id="dual_ma",
    )


def _portfolio() -> FixtureModel:
    return FixtureModel(
        {
            "cash": 1000.0,
            "total_equity": 3000.0,
            "positions": [],
            "allocation": [],
            "closed_positions": [],
            "position_review_items": [],
            "valuation_snapshot_id": VALUATION_ID,
            "valuation_as_of": NOW,
            "valuation_status": "complete",
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
        }
    )


def _source(state) -> PersistedKarkinosCaptureSource:
    return PersistedKarkinosCaptureSource(
        state,
        build_capture_projection_readers(),
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_research_only_capture_never_reads_portfolio_or_account_identity() -> (
    None
):
    source = PersistedKarkinosCaptureSource(
        SimpleNamespace(db=FixtureDatabase()),
        None,
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-research-only-001",
        requested_by="human:reese",
        research_question="Run normalized-notional discovery.",
        account_alias="strategy-only",
        evidence_types=(CaptureEvidenceType.RESEARCH_EVIDENCE,),
        confirmation=CAPTURE_CONFIRMATION,
        backtest_result_id=17,
    )

    batch = await source.load(request)

    assert batch.valuation_snapshot_id.startswith("research-only:")
    assert batch.ledger_cutoff_id == 0
    assert batch.ledger_fingerprint.startswith("research-only:")
    assert [item.tool_name for item in batch.projections] == ["research_evidence.read"]
    payload = batch.projections[0].payload
    assert payload["absolute_notional_values_redacted"] is True
    assert "initial_cash" not in payload["performance_summary"]
    assert "final_equity" not in payload["performance_summary"]


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_production_source_reuses_canonical_builders_and_exact_persisted_rows(
    monkeypatch,
):
    # Load the route before patching its source module so the route keeps its
    # real imported function after this test's monkeypatch is restored.
    import server.routes.account_truth  # noqa: F401

    portfolio = _portfolio()
    calls: list[str] = []

    async def build_portfolio(state):
        calls.append("portfolio")
        return portfolio

    async def build_account_state(state, *, snapshot):
        assert snapshot is portfolio
        calls.append("account_state")
        return FixtureModel(
            {
                "summary": {"positions_count": 0},
                "snapshot": portfolio.model_dump(mode="json"),
                "risks": [],
                "next_step": "manual review",
            }
        )

    async def build_operations(state):
        calls.append("operations")
        return {
            "schema_version": "karkinos.operations_today.v1",
            "generated_at": NOW,
            "conclusion_status": "degraded",
            "health": {"degraded": 1, "blocked": 0},
            "attention_items": [
                {
                    "schema_version": "karkinos.operations_attention_item.v1",
                    "subsystem_id": "strategy_candidates",
                    "status": "degraded",
                    "target": "decision",
                    "evidence": {"status": "0/1", "observed_at": NOW},
                    "next_action": "review_strategy_evidence",
                    "resolution_condition": "candidate_strategy_evidence_must_pass",
                    "task_fingerprint": "sha256:attention-fixture",
                    "manual_acknowledgement_clears_status": False,
                    "read_only_projection": True,
                    "provider_contacted": False,
                    "database_writes_performed": False,
                    "authorizes_execution": False,
                }
            ],
            "default_execution_mode": "manual_confirmation",
        }

    def build_contribution(db, assignment):
        assert assignment.strategy_id == "dual_ma"
        calls.append("strategy_contribution")
        return FixtureModel(
            {
                "schema_version": "karkinos.account_strategy_contribution.v2",
                "strategy_id": "dual_ma",
                "contribution_status": "evidence_bound_from_posted_fills",
                "evidence_binding_status": "bound",
                "valuation_scope_status": "complete",
                "blockers": [],
                "valuation_snapshot_id": VALUATION_ID,
                "valuation_as_of": NOW,
                "ledger_cutoff_id": LEDGER_CUTOFF_ID,
                "ledger_fingerprint": LEDGER_FINGERPRINT,
                "contribution_fingerprint": "contribution-source-001",
                "persisted_facts_only": True,
                "provider_contacted": False,
                "database_writes_performed": False,
                "authorizes_execution": False,
            }
        )

    monkeypatch.setattr(
        "server.projections.portfolio_application.build_portfolio_snapshot",
        build_portfolio,
    )
    monkeypatch.setattr(
        "server.projections.portfolio_application.build_account_state_response",
        build_account_state,
    )
    monkeypatch.setattr(
        "server.projections.portfolio_application.current_valuation_snapshot",
        lambda state: {
            "snapshot_id": VALUATION_ID,
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
        },
    )
    monkeypatch.setattr(
        "server.services.decision.operations_projection.build_today_operations_payload",
        build_operations,
    )
    monkeypatch.setattr(
        "server.services.account.account_strategy_projections.build_contribution_report",
        build_contribution,
    )
    monkeypatch.setattr(
        "server.account_truth_gate.build_latest_account_truth_score_payload",
        lambda state: {
            "schema_version": "karkinos.account_truth.score.v1",
            "status": "ready",
            "gate_status": "pass",
            "data_freshness_status": "fresh",
            "created_at": NOW,
        },
    )
    state = SimpleNamespace(
        db=FixtureDatabase(),
        config=SimpleNamespace(strategy="dual_ma"),
    )

    batch = await _source(state).load(_request())

    assert batch.valuation_snapshot_id == VALUATION_ID
    assert batch.ledger_cutoff_id == LEDGER_CUTOFF_ID
    assert batch.ledger_fingerprint == LEDGER_FINGERPRINT
    assert calls == [
        "portfolio",
        "account_state",
        "operations",
        "strategy_contribution",
    ]
    assert [projection.tool_name for projection in batch.projections] == [
        "portfolio_projection.read",
        "account_state_projection.read",
        "operations_summary.read",
        "research_evidence.read",
        "account_truth.read",
        "paper_shadow_evidence.read",
        "strategy_contribution.read",
    ]
    assert [projection.status for projection in batch.projections] == [
        "complete",
        "complete",
        "degraded",
        "degraded",
        "complete",
        "complete",
        "complete",
    ]
    assert batch.projections[3].payload["backtest_result_id"] == 17
    operations_attention = batch.projections[2].payload["attention_items"][0]
    assert operations_attention["task_fingerprint"] == "sha256:attention-fixture"
    assert operations_attention["manual_acknowledgement_clears_status"] is False
    assert operations_attention["authorizes_execution"] is False
    assert batch.projections[5].payload["persisted_run"]["run_id"] == "shadow-17"
    contribution = batch.projections[6].payload
    assert contribution["strategy_id"] == "dual_ma"
    assert contribution["valuation_snapshot_id"] == VALUATION_ID
    assert (
        contribution["strategy_contribution_report"]["contribution_fingerprint"]
        == "contribution-source-001"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_source_blocks_valuation_or_ledger_drift(monkeypatch):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.projections.portfolio_application.build_portfolio_snapshot",
        build_portfolio,
    )
    monkeypatch.setattr(
        "server.projections.portfolio_application.current_valuation_snapshot",
        lambda state: {
            "snapshot_id": "valuation-drifted",
            "ledger_cutoff_id": LEDGER_CUTOFF_ID + 1,
            "ledger_fingerprint": "ledger-drifted",
        },
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-drift-001",
        requested_by="human:reese",
        research_question="Detect drift",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.PORTFOLIO,),
        confirmation=CAPTURE_CONFIRMATION,
    )

    with pytest.raises(EvidenceIdentityMismatch, match="drifted during"):
        await _source(SimpleNamespace(db=FixtureDatabase())).load(request)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_source_requires_replayable_persisted_valuation(monkeypatch):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.projections.portfolio_application.build_portfolio_snapshot",
        build_portfolio,
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-unpublished-001",
        requested_by="human:reese",
        research_question="Reject unpublished valuation",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.PORTFOLIO,),
        confirmation=CAPTURE_CONFIRMATION,
    )
    db = SimpleNamespace(get_valuation_snapshot_sync=lambda snapshot_id: None)

    with pytest.raises(EvidenceIdentityMismatch, match="not persisted"):
        await _source(SimpleNamespace(db=db)).load(request)


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_strategy_contribution_capture_rejects_assignment_drift(monkeypatch):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.projections.portfolio_application.build_portfolio_snapshot",
        build_portfolio,
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-strategy-drift-001",
        requested_by="human:reese",
        research_question="Reject a changed strategy selection",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.STRATEGY_CONTRIBUTION,),
        confirmation=CAPTURE_CONFIRMATION,
        strategy_id="not-the-current-strategy",
    )
    state = SimpleNamespace(
        db=FixtureDatabase(),
        config=SimpleNamespace(strategy="dual_ma"),
    )

    with pytest.raises(CaptureSelectionError, match="selected strategy changed"):
        await _source(state).load(request)


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_strategy_contribution_capture_rejects_financial_identity_drift(
    monkeypatch,
):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.projections.portfolio_application.build_portfolio_snapshot",
        build_portfolio,
    )
    monkeypatch.setattr(
        "server.services.account.account_strategy_projections.build_contribution_report",
        lambda db, assignment: FixtureModel(
            {
                "strategy_id": assignment.strategy_id,
                "contribution_status": "evidence_bound_from_posted_fills",
                "evidence_binding_status": "bound",
                "valuation_scope_status": "complete",
                "blockers": [],
                "valuation_snapshot_id": "different-valuation",
                "valuation_as_of": NOW,
                "ledger_cutoff_id": LEDGER_CUTOFF_ID,
                "ledger_fingerprint": LEDGER_FINGERPRINT,
                "contribution_fingerprint": "contribution-drifted",
            }
        ),
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-contribution-identity-drift-001",
        requested_by="human:reese",
        research_question="Reject contribution identity drift",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.STRATEGY_CONTRIBUTION,),
        confirmation=CAPTURE_CONFIRMATION,
        strategy_id="dual_ma",
    )
    state = SimpleNamespace(
        db=FixtureDatabase(),
        config=SimpleNamespace(strategy="dual_ma"),
    )

    with pytest.raises(EvidenceIdentityMismatch, match="valuation_snapshot_id"):
        await _source(state).load(request)


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_incomplete_strategy_contribution_remains_blocked_evidence(monkeypatch):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.projections.portfolio_application.build_portfolio_snapshot",
        build_portfolio,
    )
    monkeypatch.setattr(
        "server.projections.portfolio_application.current_valuation_snapshot",
        lambda state: {
            "snapshot_id": VALUATION_ID,
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
        },
    )
    monkeypatch.setattr(
        "server.services.account.account_strategy_projections.build_contribution_report",
        lambda db, assignment: FixtureModel(
            {
                "strategy_id": assignment.strategy_id,
                "contribution_status": "valuation_missing",
                "evidence_binding_status": "blocked",
                "valuation_scope_status": "blocked",
                "blockers": ["strategy_contribution_valuation_snapshot_missing"],
                "valuation_snapshot_id": None,
                "valuation_as_of": None,
                "ledger_cutoff_id": 0,
                "ledger_fingerprint": None,
                "contribution_fingerprint": None,
                "persisted_facts_only": True,
                "provider_contacted": False,
                "database_writes_performed": False,
                "authorizes_execution": False,
            }
        ),
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-contribution-blocked-001",
        requested_by="human:reese",
        research_question="Preserve incomplete outcome evidence as blocked",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.STRATEGY_CONTRIBUTION,),
        confirmation=CAPTURE_CONFIRMATION,
        strategy_id="dual_ma",
    )
    state = SimpleNamespace(
        db=FixtureDatabase(),
        config=SimpleNamespace(strategy="dual_ma"),
    )

    batch = await _source(state).load(request)

    assert batch.projections[0].status == "blocked"
    assert batch.projections[0].payload["valuation_snapshot_id"] == VALUATION_ID
    report = batch.projections[0].payload["strategy_contribution_report"]
    assert report["contribution_status"] == "valuation_missing"
    assert report["authorizes_execution"] is False
