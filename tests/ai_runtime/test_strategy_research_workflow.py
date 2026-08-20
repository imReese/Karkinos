from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Event, Lock
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from core.types import AssetClass, BarFrequency, CommissionType, Symbol
from data.handler import DataHandler
from data.store import DataStore
from execution.commission import MultiAssetCommission, StockACommission
from server.ai_runtime.capture import (
    CAPTURE_TOOL_BY_TYPE,
    CapturedProjection,
    CaptureEvidenceType,
    CaptureSourceBatch,
    ContextCaptureAuditStore,
    HumanResearchContextCaptureService,
)
from server.ai_runtime.contracts import AgentRole, ArtifactKind, content_fingerprint
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.formula_dsl import (
    FORMULA_AST_CONTRACT,
)
from server.ai_runtime.provider_connectivity import (
    HttpJsonResponse,
    ProviderConnectivitySettings,
)
from server.ai_runtime.registry import AiRuntimeRegistry
from server.ai_runtime.store import AiAuditStore
from server.ai_runtime.strategy_research import (
    BACKTEST_CONFIRMATION,
    CRITIQUE_EXPORT_CONFIRMATION,
    HYPOTHESIS_EXPORT_CONFIRMATION,
    REVIEW_CONFIRMATION,
    CritiqueRequest,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
    StrategyResearchAuditStore,
    StrategyResearchSelection,
    StrategyResearchService,
)

NOW = "2026-07-15T01:00:00+00:00"
REVIEWED_COST_MODEL_REFERENCE = (
    "karkinos.backtest.reviewed_account_fee_schedule.v1:"
    f"fee_review_{'a' * 32}:{'b' * 64}"
)


def _reviewed_fee_resolution() -> SimpleNamespace:
    calculator = MultiAssetCommission(fee_rule_version=REVIEWED_COST_MODEL_REFERENCE)
    calculator.set_commission(
        CommissionType.STOCK_A,
        StockACommission(
            commission_rate=Decimal("0.001"),
            min_commission=Decimal("0"),
            fee_rule_id="reviewed-account-fee-rule",
        ),
    )
    return SimpleNamespace(
        cost_model_reference=REVIEWED_COST_MODEL_REFERENCE,
        commission_calc=calculator,
        fee_evidence={
            "account_specific": True,
            "fee_schedule_source": (
                "reviewed_account_truth_or_reconciled_fee_schedule"
            ),
            "fee_schedule_fingerprint": "sha256:" + "f" * 64,
            "broker_statement_reconciled": True,
            "fee_schedule_review_id": "fee_review_" + "a" * 32,
            "fee_schedule_review_fingerprint": "sha256:" + "b" * 64,
            "fee_schedule_preview_fingerprint": "sha256:" + "c" * 64,
            "account_truth_import_run_id": "import_fixture",
            "account_truth_source_fingerprint": "sha256:" + "d" * 64,
            "account_truth_scope_fingerprint": "sha256:" + "e" * 64,
            "effective_start_date": "2025-01-01",
            "effective_end_date": "2025-12-31",
            "fee_notional_envelope_enforced": True,
            "fee_notional_envelope_fingerprint": "sha256:" + "9" * 64,
            "fee_notional_covered_asset_classes": ["stock"],
        },
    )


class FixtureTransport:
    def __init__(self, responses: list[HttpJsonResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self._lock = Lock()

    def post_json(self, **kwargs) -> HttpJsonResponse:
        with self._lock:
            self.calls.append(kwargs)
            if not self._responses:
                raise AssertionError("unexpected extra external model call")
            response = self._responses.pop(0)
            input_payload = json.loads(kwargs["payload"]["messages"][1]["content"])
            if input_payload.get("mode") == "critique":
                content = json.loads(
                    response.payload["choices"][0]["message"]["content"]
                )
                if content.get("canonical_binding_echo") == {}:
                    content["canonical_binding_echo"] = input_payload["critique_input"][
                        "required_binding_echo"
                    ]
                response.payload["choices"][0]["message"]["content"] = json.dumps(
                    content
                )
            return response


class BlockingFixtureTransport(FixtureTransport):
    def __init__(self, responses: list[HttpJsonResponse]) -> None:
        super().__init__(responses)
        self.started = Event()
        self.release = Event()

    def post_json(self, **kwargs) -> HttpJsonResponse:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("fixture transport was not released")
        return super().post_json(**kwargs)


class FixtureCaptureSource:
    def __init__(
        self,
        research_payload: dict,
        account_payload: dict,
        *,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        ledger_fingerprint: str,
    ) -> None:
        self.research_payload = research_payload
        self.account_payload = account_payload
        self.valuation_snapshot_id = valuation_snapshot_id
        self.ledger_cutoff_id = ledger_cutoff_id
        self.ledger_fingerprint = ledger_fingerprint
        self.calls = 0
        self.requests = []

    async def load(self, request) -> CaptureSourceBatch:
        self.calls += 1
        self.requests.append(request)
        projections = []
        for evidence_type in request.evidence_types:
            if evidence_type == CaptureEvidenceType.RESEARCH_EVIDENCE:
                projections.append(
                    CapturedProjection(
                        tool_name=CAPTURE_TOOL_BY_TYPE[evidence_type],
                        status="complete",
                        as_of=NOW,
                        source_schema_version=(
                            "karkinos.ai.research_evidence_capture.v2"
                        ),
                        payload=self.research_payload,
                    )
                )
            elif evidence_type == CaptureEvidenceType.ACCOUNT_STATE:
                projections.append(
                    CapturedProjection(
                        tool_name=CAPTURE_TOOL_BY_TYPE[evidence_type],
                        status="complete",
                        as_of=NOW,
                        source_schema_version="karkinos.account_state.v1",
                        payload=self.account_payload,
                    )
                )
            else:
                raise AssertionError(f"unexpected fixture evidence: {evidence_type}")
        return CaptureSourceBatch(
            valuation_snapshot_id=self.valuation_snapshot_id,
            ledger_cutoff_id=self.ledger_cutoff_id,
            ledger_fingerprint=self.ledger_fingerprint,
            projections=tuple(projections),
        )


class FixtureDb:
    def __init__(self, initial_row: dict) -> None:
        self.rows = {17: initial_row}
        self.next_id = 18

    async def get_backtest_result(self, result_id: int):
        return self.rows.get(result_id)

    async def save_backtest_result(self, **kwargs) -> int:
        result_id = self.next_id
        self.next_id += 1
        self.rows[result_id] = {
            "id": result_id,
            "created_at": NOW,
            "config_json": kwargs["config_json"],
            "initial_cash": kwargs["initial_cash"],
            "final_equity": kwargs["final_equity"],
            "total_return": kwargs["total_return"],
            "sharpe": kwargs["sharpe"],
            "sortino": kwargs["sortino"],
            "max_drawdown": kwargs["max_dd"],
            "win_rate": kwargs["win_rate"],
            "duration_days": kwargs["duration_days"],
            "equity_curve_json": kwargs["equity_curve_json"],
            "metrics_json": kwargs["metrics_json"],
            "cost_summary_json": kwargs["cost_summary_json"],
        }
        return result_id


def _bars() -> pd.DataFrame:
    start = datetime(2025, 1, 2)
    closes = [10, 9, 8, 12, 13, 14, 7, 6]
    return pd.DataFrame(
        {
            "timestamp": [
                start + timedelta(days=index) for index in range(len(closes))
            ],
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [100_000] * len(closes),
        }
    )


def _formula() -> dict:
    average = {
        "op": "rolling_mean",
        "input": {"op": "field", "name": "close"},
        "window": 3,
    }
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "cross",
            "left": {"op": "field", "name": "close"},
            "right": average,
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": average,
        },
        "position_size": {"op": "equal_weight"},
    }


def _hypothesis_response(
    selection: StrategyResearchSelection,
    *,
    include_account_evidence: bool = True,
) -> HttpJsonResponse:
    draft = {
        "economic_hypothesis": "价格上穿短期均线后可能出现有限的趋势延续。",
        "selected_universe": list(selection.universe),
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
        },
        "frequency": selection.frequency,
        "formula_ast": _formula(),
        "parameter_values": {"window": 3},
        "parameter_ranges": {"window": [3, 5]},
        "entry_conditions": "收盘价从下向上穿越三日均线。",
        "exit_conditions": "收盘价低于三日均线。",
        "position_sizing_hypothesis": "使用受最大权重约束的等权目标。",
        "portfolio_constraints": {"long_only": True, "max_weight": 1.0},
        "cost_model_reference": selection.cost_model_reference,
        "required_evidence": ["绑定数据集上的成本后回测证据。"],
        "anti_lookahead_assumptions": ["信号只使用当前已完成日线及之前的历史。"],
        "proposed_deterministic_tests": ["重放同一快照应产生同一结果。"],
        "sample_split_plan": "先保留本次冻结区间，未来新增滚动样本外验证。",
        "failure_conditions": ["成本后收益为负。"],
        "limitations": ["单一短样本不能支持策略晋级。"],
        "risk_impact": "可能产生高换手和集中度风险，仅供研究。",
        "citations": [
            "saved_backtest_evidence.performance_summary",
            *(
                ["saved_account_evidence.summary.cash_ratio"]
                if include_account_evidence
                else []
            ),
        ],
    }
    return _model_response({"drafts": [draft]}, model="fixture-hypothesis")


def _critique_response() -> HttpJsonResponse:
    return _model_response(
        {
            "supported_claims": ["公式按绑定快照产生了可重放的研究结果。"],
            "contradicted_claims": ["成本后收益为负，未支持正向趋势收益假设。"],
            "evidence_gaps": ["缺少独立样本外与压力测试。"],
            "cost_turnover_sensitivity": "现有证据显示费用已计入，但仍需成本倍增测试。",
            "concentration_risk": "仅含一个标的，集中度风险高。",
            "sample_dependence": "结果依赖短时间窗。",
            "possible_overfitting": "单一三日窗口可能是样本偶然。",
            "recommended_ablations": ["移除交叉条件并比较固定持有基线。"],
            "recommended_walk_forward_stress_tests": ["新增滚动样本外窗口。"],
            "explicit_failure_conditions": ["样本外成本后收益持续为负。"],
            "uncertainty": "当前证据不足，结论置信度低。",
            "citations": ["critique_input.canonical_backtest.total_return"],
            "canonical_binding_echo": {},
        },
        model="fixture-critique",
    )


def _model_response(content: dict, *, model: str) -> HttpJsonResponse:
    return HttpJsonResponse(
        status_code=200,
        payload={
            "id": "raw-provider-envelope-must-not-persist",
            "model": model,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(content, ensure_ascii=False),
                        "reasoning_content": "private reasoning must not persist",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
            },
        },
    )


def _nested_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_nested_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_nested_keys(item) for item in value)) if value else set()
    return set()


def _iteration_context(*, iteration_number: int, total_iterations: int = 5) -> dict:
    parent = None
    if iteration_number > 1:
        parent_core = {
            "iteration_number": iteration_number - 1,
            "candidate_id": f"candidate-{iteration_number - 1}",
            "session_id": f"session-{iteration_number - 1}",
            "draft_id": f"draft-{iteration_number - 1}",
            "formula_fingerprint": "sha256:" + "1" * 64,
            "backtest_run_id": f"backtest-{iteration_number - 1}",
            "critique_id": f"critique-{iteration_number - 1}",
            "strategy": {
                "economic_hypothesis": "The prior trend filter was too reactive.",
                "parameter_values": {"window": 2},
            },
            "evaluation": {
                "promotion_gate_status": "blocked",
                "blockers": ["worst_oos_excess_return"],
            },
            "critique": {
                "supported_claims": ["The frozen run is reproducible."],
                "evidence_gaps": ["Worst-window excess remained negative."],
            },
        }
        parent = {
            **parent_core,
            "parent_artifact_fingerprint": (
                "sha256:" + content_fingerprint(parent_core)
            ),
        }
    core = {
        "schema_version": "karkinos.ai.strategy_iteration_context.v1",
        "iteration_number": iteration_number,
        "total_iterations": total_iterations,
        "parent_iteration": parent,
        "required_behavior": {
            "draft_count": 1,
            "must_change_formula_from_parent": iteration_number > 1,
            "must_use_parent_backtest_and_critique": iteration_number > 1,
            "authority_effect": "none",
        },
    }
    return {**core, "context_fingerprint": "sha256:" + content_fingerprint(core)}


def _service(tmp_path, *, bind_account: bool = True):
    market = DataStore(tmp_path / "market")
    symbol = Symbol("600000")
    bars = _bars()
    market.save_bars(
        symbol,
        BarFrequency.DAILY,
        bars,
        provider_name="deterministic_fixture",
        data_source="deterministic_fixture",
        adjustment_mode="none",
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date="2025-01-02",
        end_date="2025-01-09",
        configured_source="deterministic_fixture",
        data_handlers={
            symbol: DataHandler(bars, symbol, BarFrequency.DAILY, AssetClass.STOCK)
        },
        store=market,
        source_names=["akshare", "deterministic_fixture"],
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=17,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date="2025-01-02",
        end_date="2025-01-09",
        frequency="1d",
        initial_cash=100_000,
        cost_model_reference=REVIEWED_COST_MODEL_REFERENCE,
        valuation_snapshot_id=("private-valuation-id" if bind_account else None),
        ledger_cutoff_id=(88 if bind_account else None),
    )
    original_evidence = {
        "schema_version": "karkinos.research_evidence.v1",
        "gate_status": "pass",
        "limitations": ["deterministic synthetic fixture"],
    }
    db = FixtureDb(
        {
            "id": 17,
            "created_at": NOW,
            "config_json": json.dumps(
                {
                    "start_date": selection.start_date,
                    "end_date": selection.end_date,
                    "initial_cash": selection.initial_cash,
                    "strategy": "fixture_baseline",
                    "assets": [{"symbol": "600000", "asset_class": "stock"}],
                }
            ),
            "initial_cash": 100_000,
            "final_equity": 99_500,
            "total_return": -0.005,
            "sharpe": -0.1,
            "sortino": -0.1,
            "max_drawdown": 0.03,
            "win_rate": 0.4,
            "duration_days": 8,
            "metrics_json": json.dumps(
                {
                    "dataset_snapshot": snapshot,
                    "evidence_bundle": {"total_cost": 10, "fill_count": 2},
                    "research_evidence_bundle": original_evidence,
                }
            ),
            "cost_summary_json": json.dumps(
                {
                    "total_commission": 10,
                    "total_slippage": 0,
                    "total_trades": 2,
                    "gross_turnover": 20_000,
                }
            ),
        }
    )
    captured_payload = {
        "schema_version": "karkinos.ai.research_evidence_capture.v2",
        "backtest_result_id": 17,
        "performance_summary": {
            "initial_cash": 100_000,
            "final_equity": 99_500,
            "total_return": -0.005,
            "max_drawdown": 0.03,
            "duration_days": 8,
        },
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
            "assets": [{"symbol": "600000", "asset_class": "stock"}],
        },
        "after_cost_evidence": {"total_cost": 10, "fill_count": 2},
        "cost_summary": {"total_commission": 10, "total_trades": 2},
        "research_evidence_bundle": original_evidence,
        "analysis_ready": True,
        "analysis_blocking_reasons": [],
        "persisted_backtest_facts_only": True,
    }
    account_payload = {
        "summary": {
            "total_equity": 100_000,
            "available_cash": 25_000,
            "positions_count": 1,
            "cash_ratio": 0.25,
            "current_drawdown": 0.04,
            "quote_status": "live",
            "using_persistent_cache": True,
            "valuation_trade_date": "2025-01-09",
            "valuation_status": "complete",
            "valuation_snapshot_id": "private-valuation-id",
            "ledger_cutoff_id": 88,
            "ledger_fingerprint": "private-ledger-fingerprint",
        },
        "snapshot": {
            "cash": 25_000,
            "total_equity": 100_000,
            "positions": [
                {
                    "symbol": "600000",
                    "quantity": 5_000,
                    "avg_cost": 12.5,
                    "market_value": 75_000,
                }
            ],
            "allocation": [
                {
                    "symbol": "CASH",
                    "name": "现金",
                    "asset_class": "cash",
                    "weight": 0.25,
                    "value": 25_000,
                },
                {
                    "symbol": "600000",
                    "name": "浦发银行",
                    "asset_class": "stock",
                    "weight": 0.75,
                    "value": 75_000,
                },
            ],
            "allocation_grouped": [
                {
                    "asset_class": "cash",
                    "name": "现金",
                    "weight": 0.25,
                    "value": 25_000,
                    "items": [],
                },
                {
                    "asset_class": "stock",
                    "name": "股票",
                    "weight": 0.75,
                    "value": 75_000,
                    "items": [],
                },
            ],
            "valuation_trade_date": "2025-01-09",
            "valuation_status": "complete",
            "valuation_snapshot_id": "private-valuation-id",
            "ledger_cutoff_id": 88,
            "ledger_fingerprint": "private-ledger-fingerprint",
        },
        "risks": [
            {
                "kind": "risk",
                "level": "high",
                "title": "仓位集中度偏高",
                "detail": "浦发银行占总资产 75.0%",
            }
        ],
        "next_step": "确认待执行建议",
    }
    db_path = tmp_path / "app.db"
    evidence = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    capture_store = ContextCaptureAuditStore(db_path)
    research_store = StrategyResearchAuditStore(db_path)
    evidence.init()
    ai_store.init()
    capture_store.init()
    research_store.init()
    source = FixtureCaptureSource(
        captured_payload,
        account_payload,
        valuation_snapshot_id=(
            "private-valuation-id"
            if bind_account
            else "not-applicable-strategy-research"
        ),
        ledger_cutoff_id=(88 if bind_account else 0),
        ledger_fingerprint=(
            "private-ledger-fingerprint"
            if bind_account
            else "not-applicable-strategy-research"
        ),
    )
    capture = HumanResearchContextCaptureService(
        source=source,
        evidence_repository=evidence,
        context_store=ai_store,
        capture_store=capture_store,
        now=lambda: NOW,
    )
    transport = FixtureTransport(
        [
            _hypothesis_response(
                selection,
                include_account_evidence=bind_account,
            ),
            _critique_response(),
        ]
    )
    service = StrategyResearchService(
        db=db,
        db_path=db_path,
        settings=ProviderConnectivitySettings(
            provider_id="deepseek",
            model_name="fixture-model",
            base_url="https://ai.example.test/v1",
            api_key="fixture-api-key-must-not-persist",
            credential_source="test-only",
            enabled=True,
        ),
        capture_service=capture,
        evidence_repository=evidence,
        ai_store=ai_store,
        research_store=research_store,
        data_store=market,
        transport=transport,
        now=lambda: NOW,
        monotonic=lambda: 10.0,
        reviewed_fee_schedule_resolver=lambda **_: _reviewed_fee_resolution(),
    )
    return service, selection, transport, db_path


@pytest.mark.unit
def test_external_selection_redacts_account_snapshot_and_ledger_identifiers() -> None:
    selection = StrategyResearchSelection(
        saved_backtest_result_id=17,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id="sha256:dataset",
        start_date="2025-01-02",
        end_date="2025-01-09",
        frequency="1d",
        initial_cash=100_000,
        valuation_snapshot_id="private-valuation-id",
        ledger_cutoff_id=88,
    )

    external = selection.to_external_dict()

    assert "valuation_snapshot_id" not in external
    assert "ledger_cutoff_id" not in external
    assert external["account_fact_binding"] == "present_but_identifiers_redacted"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("valuation_snapshot_id", "ledger_cutoff_id"),
    (("valuation-only", None), (None, 88)),
)
def test_selection_rejects_partial_account_fact_binding(
    valuation_snapshot_id,
    ledger_cutoff_id,
) -> None:
    with pytest.raises(Exception, match="account_fact_binding_incomplete"):
        StrategyResearchSelection(
            saved_backtest_result_id=17,
            universe=("600000",),
            asset_classes=("stock",),
            dataset_snapshot_id="sha256:dataset",
            start_date="2025-01-02",
            end_date="2025-01-09",
            frequency="1d",
            initial_cash=100_000,
            valuation_snapshot_id=valuation_snapshot_id,
            ledger_cutoff_id=ledger_cutoff_id,
        )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_iteration_exports_exact_parent_feedback_and_one_draft_contract(
    tmp_path,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    iteration_context = _iteration_context(iteration_number=2)
    response = transport._responses[0].payload
    content = json.loads(response["choices"][0]["message"]["content"])
    content["drafts"][0]["citations"].append(
        "iteration_context.parent_iteration.evaluation.blockers"
    )
    response["choices"][0]["message"]["content"] = json.dumps(content)

    result = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-iteration-2",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Revise the prior formula from its frozen evidence.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
            iteration_context=iteration_context,
        )
    )

    assert result["status"] == "completed"
    assert len(result["drafts"]) == 1
    assert result["iteration_context"] == iteration_context
    assert result["drafts"][0]["iteration_context"] == iteration_context
    assert result["drafts"][0]["iteration_context_fingerprint"] == (
        iteration_context["context_fingerprint"]
    )
    external = json.loads(transport.calls[0]["payload"]["messages"][1]["content"])
    assert external["iteration_context"] == iteration_context
    assert external["output_contract"]["draft_count"] == "exactly 1"
    assert not {
        "account_id",
        "valuation_snapshot_id",
        "ledger_cutoff_id",
        "broker_export",
        "credentials",
        "api_key",
    }.intersection(_nested_keys(external["iteration_context"]))


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_iteration_rejects_multiple_provider_drafts_fail_closed(tmp_path) -> None:
    service, selection, transport, _ = _service(tmp_path)
    response = transport._responses[0].payload
    content = json.loads(response["choices"][0]["message"]["content"])
    content["drafts"].append(dict(content["drafts"][0]))
    response["choices"][0]["message"]["content"] = json.dumps(content)

    result = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-iteration-multiple-drafts",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Each sequential round must return one revision.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
            iteration_context=_iteration_context(iteration_number=1),
        )
    )

    assert result["status"] == "failed"
    assert result["drafts"] == []
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_fake_provider_completes_hypothesis_backtest_critique_without_authority(
    tmp_path,
) -> None:
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE oms_orders (id TEXT PRIMARY KEY);
            CREATE TABLE ledger_entries (id TEXT PRIMARY KEY);
            CREATE TABLE risk_decisions (id TEXT PRIMARY KEY);
            CREATE TABLE kill_switch_state (id TEXT PRIMARY KEY);
            CREATE TABLE capital_authorizations (id TEXT PRIMARY KEY);
            CREATE TABLE broker_submissions (id TEXT PRIMARY KEY);
            INSERT INTO oms_orders VALUES ('oms-before');
            INSERT INTO ledger_entries VALUES ('ledger-before');
            INSERT INTO risk_decisions VALUES ('risk-before');
            INSERT INTO kill_switch_state VALUES ('kill-before');
            INSERT INTO capital_authorizations VALUES ('capital-before');
            INSERT INTO broker_submissions VALUES ('broker-before');
            """)
    service, selection, transport, actual_db_path = _service(tmp_path)
    assert actual_db_path == db_path
    registry = AiRuntimeRegistry(service._ai_store)
    for role_id, instructions_version in (
        (
            "external.strategy_hypothesis_researcher.v1",
            "karkinos.ai.strategy_research_prompt.v2",
        ),
        (
            "external.strategy_hypothesis_researcher.v2",
            "karkinos.ai.strategy_research_prompt.v3",
        ),
        (
            "external.strategy_hypothesis_researcher.v3",
            "karkinos.ai.strategy_research_prompt.v4",
        ),
        (
            "external.strategy_hypothesis_researcher.v4",
            "karkinos.ai.strategy_research_prompt.v5",
        ),
        (
            "external.strategy_hypothesis_researcher.v5",
            "karkinos.ai.strategy_research_prompt.v6",
        ),
        (
            "external.strategy_hypothesis_researcher.v6",
            "karkinos.ai.strategy_research_prompt.v7",
        ),
    ):
        registry.register_role(
            AgentRole(
                role_id=role_id,
                display_name="Strategy hypothesis researcher",
                purpose=(
                    "Propose or critique non-executable research hypotheses using "
                    "only bound evidence and the local Formula DSL; never create "
                    "authority."
                ),
                allowed_tools=(
                    "research_evidence.read",
                    "formula_operator_catalog.read",
                    "strategy_research_selection.read",
                ),
                allowed_artifact_kinds=(ArtifactKind.REPORT,),
                instructions_version=instructions_version,
            )
        )

    hypotheses = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-001",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="该趋势延续假设是否值得进入确定性成本后回测？",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    assert hypotheses["status"] == "completed"
    assert len(hypotheses["drafts"]) == 1
    draft = hypotheses["drafts"][0]
    assert draft["validation"]["status"] == "valid"
    assert draft["executable"] is False
    assert draft["authority_effect"] == "none"
    assert draft["provider_provenance"]["usage"]["total_tokens"] == 300
    assert draft["provider_provenance"]["reasoning_content_present"] is True
    assert draft["provider_provenance"]["reasoning_content_persisted"] is False
    role_ids = {item.role_id for item in service._ai_store.list_roles()}
    assert "external.strategy_hypothesis_researcher.v1" in role_ids
    assert "external.strategy_hypothesis_researcher.v2" in role_ids
    assert "external.strategy_hypothesis_researcher.v3" in role_ids
    assert "external.strategy_hypothesis_researcher.v4" in role_ids
    assert "external.strategy_hypothesis_researcher.v5" in role_ids
    assert "external.strategy_hypothesis_researcher.v6" in role_ids
    assert "external.strategy_hypothesis_researcher.v7" in role_ids
    current_role = next(
        item
        for item in service._ai_store.list_roles()
        if item.role_id == "external.strategy_hypothesis_researcher.v7"
    )
    assert "account_state_projection.read" in current_role.allowed_tools
    assert (
        current_role.instructions_version == "karkinos.ai.strategy_research_prompt.v9"
    )

    backtest = await service.run_formula_backtest(
        FormulaBacktestRequest(
            idempotency_key="backtest-001",
            requested_by="human:reese",
            session_id=hypotheses["session_id"],
            draft_id=draft["draft_id"],
            confirmation=BACKTEST_CONFIRMATION,
        )
    )
    assert backtest["status"] == "completed"
    assert backtest["canonical_backtest"]["result_id"] == 18
    assert backtest["canonical_backtest"]["total_return"] < 0
    assert backtest["canonical_backtest"]["cost_summary"]["total_trades"] > 0
    assert (
        backtest["canonical_backtest"]["dataset_snapshot"]["snapshot_id"]
        == selection.dataset_snapshot_id
    )
    saved_candidate = await service._db.get_backtest_result(
        backtest["canonical_backtest"]["result_id"]
    )
    account_capital = json.loads(saved_candidate["metrics_json"])[
        "account_capital_constraint"
    ]
    assert account_capital["status"] == "pass"
    assert account_capital["initial_cash_within_current_account_equity"] is True
    assert account_capital["current_account_total_equity_redacted"] is True
    assert "available_cash" not in account_capital
    assert "positions" not in account_capital

    critique = await service.critique(
        CritiqueRequest(
            idempotency_key="critique-001",
            requested_by="human:reese",
            session_id=hypotheses["session_id"],
            draft_id=draft["draft_id"],
            backtest_run_id=backtest["backtest_run_id"],
            confirmation=CRITIQUE_EXPORT_CONFIRMATION,
        )
    )
    assert critique["status"] == "completed"
    assert critique["artifact"]["trade_plan_created"] is False
    assert critique["artifact"]["authority_effect"] == "none"
    assert critique["artifact"]["canonical_binding_echo"]["total_return"] == (
        backtest["canonical_backtest"]["total_return"]
    )
    assert len(transport.calls) == 2
    assert all(call["payload"].get("tools") is None for call in transport.calls)
    assert all(
        call["payload"]["thinking"] == {"type": "enabled"} for call in transport.calls
    )
    hypothesis_payload = transport.calls[0]["payload"]
    hypothesis_system_prompt = hypothesis_payload["messages"][0]["content"]
    hypothesis_input = json.loads(hypothesis_payload["messages"][1]["content"])
    assert hypothesis_payload["max_tokens"] == 12_288
    assert "schema_version must" in hypothesis_system_prompt
    assert "must never be omitted" in hypothesis_system_prompt
    assert "ATR is a special operator" in hypothesis_system_prompt
    assert "Prefer one compact draft" in hypothesis_system_prompt
    assert "sanitized persisted risk/allocation projection" in hypothesis_system_prompt
    account_evidence = hypothesis_input["saved_account_evidence"]
    assert account_evidence["schema_version"] == (
        "karkinos.ai.sanitized_account_risk_evidence.v1"
    )
    assert account_evidence["summary"] == {
        "positions_count": 1,
        "cash_ratio": 0.25,
        "current_drawdown": 0.04,
        "quote_status": "live",
        "valuation_trade_date": "2025-01-09",
        "valuation_status": "complete",
        "using_persistent_cache": True,
    }
    assert account_evidence["allocation"] == [
        {"symbol": "CASH", "asset_class": "cash", "weight": 0.25},
        {"symbol": "600000", "asset_class": "stock", "weight": 0.75},
    ]
    assert account_evidence["allocation_grouped"] == [
        {"asset_class": "cash", "weight": 0.25},
        {"asset_class": "stock", "weight": 0.75},
    ]
    assert account_evidence["absolute_account_values_redacted"] is True
    assert account_evidence["valuation_and_ledger_identifiers_redacted"] is True
    sensitive_account_keys = {
        "total_equity",
        "available_cash",
        "cash",
        "value",
        "quantity",
        "avg_cost",
        "market_value",
        "valuation_snapshot_id",
        "ledger_cutoff_id",
        "ledger_fingerprint",
        "evidence_reference_id",
        "record_fingerprint",
    }
    assert sensitive_account_keys.isdisjoint(_nested_keys(account_evidence))
    serialized_account = json.dumps(account_evidence, ensure_ascii=False)
    assert "private-valuation-id" not in serialized_account
    assert "private-ledger-fingerprint" not in serialized_account
    assert "saved_account_evidence.summary.cash_ratio" in draft["citations"]
    assert draft["provider_provenance"]["account_evidence_exported"] is True
    assert draft["provider_provenance"]["absolute_account_values_redacted"] is True
    source = service._capture_service._source
    assert source.requests[0].evidence_types == (
        CaptureEvidenceType.RESEARCH_EVIDENCE,
        CaptureEvidenceType.ACCOUNT_STATE,
    )
    assert hypothesis_input["output_contract"]["formula_ast_exact_top_level_keys"] == [
        "schema_version",
        "entry",
        "exit",
        "position_size",
    ]
    assert (
        hypothesis_input["output_contract"]["formula_ast_schema_version_literal"]
        == FORMULA_AST_CONTRACT
    )
    assert (
        hypothesis_input["output_contract"][
            "formula_ast_missing_schema_version_is_invalid"
        ]
        is True
    )
    node_key_contract = hypothesis_input["output_contract"][
        "formula_ast_node_exact_keys"
    ]
    assert node_key_contract["atr"] == ["op", "window"]
    assert node_key_contract["window_operator_except_atr"] == [
        "op",
        "input",
        "window",
    ]
    critique_payload = transport.calls[1]["payload"]
    critique_system_prompt = critique_payload["messages"][0]["content"]
    critique_input = json.loads(critique_payload["messages"][1]["content"])
    assert "prior baseline, not the formula result" in critique_system_prompt
    assert critique_input["critique_input"]["canonical_backtest"]["result_id"] == 18
    assert (
        critique_input["critique_input"]["canonical_backtest"]["oos_validation"]
        == backtest["canonical_backtest"]["oos_validation"]
    )
    assert critique_input["critique_input"]["required_binding_echo"][
        "oos_validation_fingerprint"
    ]
    assert (
        critique_input["critique_input"]["required_binding_echo"]
        == critique["artifact"]["canonical_binding_echo"]
    )
    assert (
        "critique_input.canonical_backtest.total_return"
        in critique_input["output_contract"]["allowed_citation_paths"]
    )
    assert (
        "critique_input.canonical_backtest.oos_validation.aggregate."
        "worst_out_of_sample_return"
        in critique_input["output_contract"]["allowed_citation_paths"]
    )
    assert all(
        citation.startswith("critique_input.")
        for citation in critique["artifact"]["citations"]
    )
    critique_row = service._research_store.get_critique(critique["critique_id"])
    review = service._research_store.save_review(
        idempotency_key="review-001",
        session_id=hypotheses["session_id"],
        critique_id=critique["critique_id"],
        critique_artifact_fingerprint=critique_row["artifact_fingerprint"],
        reviewer="human:reese",
        disposition="needs_revision",
        notes="Keep the negative result and add out-of-sample evidence.",
        confirmation=REVIEW_CONFIRMATION,
        created_at=NOW,
    )
    assert review["critique_id"] == critique["critique_id"]
    assert service._research_store.verify_events(hypotheses["session_id"])[0]
    assert service._research_store.verify_events(critique["critique_id"])[0]
    critique_replay = await service.critique(
        CritiqueRequest(
            idempotency_key="critique-001",
            requested_by="human:reese",
            session_id=hypotheses["session_id"],
            draft_id=draft["draft_id"],
            backtest_run_id=backtest["backtest_run_id"],
            confirmation=CRITIQUE_EXPORT_CONFIRMATION,
        )
    )
    assert critique_replay["reused"] is True
    assert len(transport.calls) == 2

    replay = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-001",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="该趋势延续假设是否值得进入确定性成本后回测？",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    assert replay["reused"] is True
    assert len(transport.calls) == 2

    with sqlite3.connect(db_path) as conn:
        for table, expected in (
            ("oms_orders", "oms-before"),
            ("ledger_entries", "ledger-before"),
            ("risk_decisions", "risk-before"),
            ("kill_switch_state", "kill-before"),
            ("capital_authorizations", "capital-before"),
            ("broker_submissions", "broker-before"),
        ):
            assert conn.execute(f"SELECT id FROM {table}").fetchall() == [(expected,)]
        persisted = "\n".join(
            str(value)
            for table in (
                "ai_agent_runs",
                "ai_artifacts",
                "ai_strategy_research_sessions",
                "ai_strategy_backtest_critiques",
            )
            for row in conn.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )
    assert "fixture-api-key-must-not-persist" not in persisted
    assert "private reasoning must not persist" not in persisted
    assert "raw-provider-envelope-must-not-persist" not in persisted


@pytest.mark.unit
@pytest.mark.asyncio
async def test_strategy_research_without_account_binding_fails_before_export(
    tmp_path,
) -> None:
    service, selection, transport, _ = _service(tmp_path, bind_account=False)

    with pytest.raises(Exception, match="research_account_binding_required"):
        await service.generate_hypotheses(
            HypothesisGenerationRequest(
                idempotency_key="strategy-only-hypothesis",
                requested_by="human:reese",
                account_alias="strategy-only",
                research_question="Unbound research must fail closed.",
                selection=selection,
                confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
            )
        )

    assert transport.calls == []
    assert service._capture_service._source.requests == []


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_strategy_research_capital_above_current_equity_fails_before_export(
    tmp_path,
) -> None:
    service, selection, transport, db_path = _service(tmp_path)
    source = service._capture_service._source
    source.account_payload["summary"]["total_equity"] = 99_999
    source.account_payload["snapshot"]["total_equity"] = 99_999

    with pytest.raises(
        Exception, match="research_initial_cash_exceeds_current_account_equity"
    ):
        await service.generate_hypotheses(
            HypothesisGenerationRequest(
                idempotency_key="oversized-account-capital",
                requested_by="human:reese",
                account_alias="bound-account",
                research_question="Oversized research capital must fail closed.",
                selection=selection,
                confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
            )
        )

    assert transport.calls == []
    with sqlite3.connect(db_path) as conn:
        stored = conn.execute(
            "SELECT status, failure_code FROM ai_strategy_research_sessions"
        ).fetchone()
    assert stored == (
        "blocked",
        "research_initial_cash_exceeds_current_account_equity",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_bound_account_evidence_fails_before_provider_export(
    tmp_path,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    source = service._capture_service._source
    source.account_payload["snapshot"].pop("allocation")

    result = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="malformed-account-evidence",
            requested_by="human:reese",
            account_alias="bound-account",
            research_question="Malformed account evidence must fail closed.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )

    assert result["status"] == "failed"
    assert result["drafts"] == []
    assert transport.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bound_account_evidence_drift_invalidates_research_session(
    tmp_path,
) -> None:
    service, selection, _, db_path = _service(tmp_path)
    hypotheses = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="account-evidence-drift",
            requested_by="human:reese",
            account_alias="bound-account",
            research_question="Account evidence drift must invalidate the session.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    with sqlite3.connect(db_path) as conn:
        account_reference_id = conn.execute(
            "SELECT reference_id FROM ai_canonical_evidence "
            "WHERE tool_name='account_state_projection.read'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json='{}' "
            "WHERE reference_id=?",
            (account_reference_id,),
        )

    replay = service.get_session(hypotheses["session_id"])

    assert replay["binding_validity"] == "invalidated_by_drift"
    assert replay["binding_errors"] == ["account_evidence_drift"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provider_changed_dataset_is_saved_as_blocked_not_executable(
    tmp_path,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    response = transport._responses[0].payload
    content = json.loads(response["choices"][0]["message"]["content"])
    content["drafts"][0]["dataset_snapshot_id"] = "sha256:provider-changed"
    response["choices"][0]["message"]["content"] = json.dumps(content)

    result = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-drift",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="测试冻结数据集约束。",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )

    draft = result["drafts"][0]
    assert draft["validation"]["status"] == "blocked"
    assert "provider_changed_dataset_snapshot" in draft["validation"]["errors"]
    assert draft["executable"] is False


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["malformed", "truncated", "schema"])
@pytest.mark.asyncio
async def test_malformed_or_truncated_provider_output_is_terminal_and_not_retried(
    tmp_path,
    failure: str,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    response = transport._responses[0].payload
    if failure == "malformed":
        response["choices"][0]["message"]["content"] = "{not-json"
    elif failure == "truncated":
        response["choices"][0]["finish_reason"] = "length"
    else:
        response["choices"][0]["message"]["content"] = json.dumps({"unexpected": []})
    request = HypothesisGenerationRequest(
        idempotency_key=f"hypothesis-{failure}",
        requested_by="human:reese",
        account_alias="synthetic-research-only",
        research_question="Malformed output must fail closed.",
        selection=selection,
        confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
    )

    result = await service.generate_hypotheses(request)
    replay = await service.generate_hypotheses(request)

    assert result["status"] == "failed"
    assert result["drafts"] == []
    assert replay["status"] == "failed"
    assert replay["reused"] is True
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_provider_output_logs_only_safe_rejection_code(
    tmp_path,
    caplog,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    response = transport._responses[0].payload
    response["choices"][0]["message"]["content"] = "private malformed content"

    with caplog.at_level("WARNING", logger="server.ai_runtime.strategy_research"):
        result = await service.generate_hypotheses(
            HypothesisGenerationRequest(
                idempotency_key="hypothesis-safe-rejection-log",
                requested_by="human:reese",
                account_alias="synthetic-research-only",
                research_question="Invalid output must expose only its safe code.",
                selection=selection,
                confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
            )
        )

    assert result["status"] == "failed"
    assert "provider_content_not_json" in caplog.text
    assert "private malformed content" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_duplicate_obtains_one_external_cost_claim(tmp_path) -> None:
    service, selection, original_transport, _ = _service(tmp_path)
    transport = BlockingFixtureTransport(list(original_transport._responses))
    service._transport = transport
    request = HypothesisGenerationRequest(
        idempotency_key="hypothesis-concurrent",
        requested_by="human:reese",
        account_alias="synthetic-research-only",
        research_question="Concurrent duplicate must call the model once.",
        selection=selection,
        confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
    )

    first = asyncio.create_task(service.generate_hypotheses(request))
    assert await asyncio.to_thread(transport.started.wait, 5)
    duplicate = await service.generate_hypotheses(request)
    transport.release.set()
    completed = await first

    assert duplicate["status"] == "running"
    assert completed["status"] == "completed"
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persisted_dataset_drift_blocks_formula_backtest_before_engine_run(
    tmp_path,
) -> None:
    service, selection, _, _ = _service(tmp_path)
    hypotheses = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-dataset-drift",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Dataset drift must invalidate the draft.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    drifted = _bars()
    drifted.loc[0, "close"] = 999
    service._data_store.save_bars(
        Symbol("600000"),
        BarFrequency.DAILY,
        drifted,
        provider_name="deterministic_fixture",
        data_source="deterministic_fixture",
        adjustment_mode="none",
    )

    with pytest.raises(Exception, match="dataset_snapshot_drift"):
        await service.run_formula_backtest(
            FormulaBacktestRequest(
                idempotency_key="backtest-dataset-drift",
                requested_by="human:reese",
                session_id=hypotheses["session_id"],
                draft_id=hypotheses["drafts"][0]["draft_id"],
                confirmation=BACKTEST_CONFIRMATION,
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "citation",
    (
        "saved_account_evidence.risks.0.level",
        "saved_account_evidence.risks[0].level",
    ),
)
@pytest.mark.asyncio
async def test_hypothesis_citation_accepts_bounded_array_index(
    tmp_path,
    citation: str,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    response = transport._responses[0].payload
    content = json.loads(response["choices"][0]["message"]["content"])
    content["drafts"][0]["citations"] = [citation]
    response["choices"][0]["message"]["content"] = json.dumps(content)

    result = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key=f"hypothesis-array-citation-{citation}",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Bound array citations must remain auditable.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )

    assert result["status"] == "completed"
    assert result["drafts"][0]["citations"] == [citation]
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "citation",
    (
        "saved_backtest_evidence.nonexistent",
        "saved_account_evidence.risks[1].level",
        "saved_account_evidence.risks[-1].level",
        "saved_account_evidence.risks[*].level",
    ),
)
@pytest.mark.asyncio
async def test_unknown_hypothesis_citation_fails_closed(
    tmp_path,
    citation: str,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    response = transport._responses[0].payload
    content = json.loads(response["choices"][0]["message"]["content"])
    content["drafts"][0]["citations"] = [citation]
    response["choices"][0]["message"]["content"] = json.dumps(content)

    result = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-unbound-citation",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Unknown citations must fail closed.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )

    assert result["status"] == "failed"
    assert result["drafts"] == []
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_replay_marks_audit_and_evidence_drift_without_deleting_history(
    tmp_path,
) -> None:
    service, selection, _, db_path = _service(tmp_path)
    hypotheses = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-read-drift",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Read replay must surface drift.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    with sqlite3.connect(db_path) as conn:
        original_event_hash = conn.execute(
            "SELECT event_hash FROM ai_workflow_events "
            "WHERE workflow_id = ? AND sequence_number = 1",
            (hypotheses["workflow"]["workflow_id"],),
        ).fetchone()[0]
        conn.execute(
            "UPDATE ai_workflow_events SET event_hash = ? "
            "WHERE workflow_id = ? AND sequence_number = 1",
            ("0" * 64, hypotheses["workflow"]["workflow_id"]),
        )

    replay = service.get_session(hypotheses["session_id"])

    assert replay["binding_validity"] == "invalidated_by_drift"
    assert replay["binding_errors"] == ["research_audit_drift"]
    assert replay["drafts"][0]["draft_id"] == hypotheses["drafts"][0]["draft_id"]

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE ai_workflow_events SET event_hash = ? "
            "WHERE workflow_id = ? AND sequence_number = 1",
            (
                original_event_hash,
                hypotheses["workflow"]["workflow_id"],
            ),
        )
        original_strategy_event_hash = conn.execute(
            "SELECT event_hash FROM ai_strategy_research_events "
            "WHERE entity_id = ? ORDER BY rowid LIMIT 1",
            (hypotheses["session_id"],),
        ).fetchone()[0]
        conn.execute(
            "UPDATE ai_strategy_research_events SET event_hash = ? "
            "WHERE event_hash = ?",
            ("f" * 64, original_strategy_event_hash),
        )
    strategy_replay = service.get_session(hypotheses["session_id"])
    assert strategy_replay["binding_validity"] == "invalidated_by_drift"
    assert strategy_replay["binding_errors"] == ["strategy_research_audit_drift"]

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE ai_strategy_research_events SET event_hash = ? "
            "WHERE event_hash = ?",
            (original_strategy_event_hash, "f" * 64),
        )
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = '{}' "
            "WHERE reference_id = ?",
            (hypotheses["evidence_reference_id"],),
        )
    evidence_replay = service.get_session(hypotheses["session_id"])
    assert evidence_replay["binding_validity"] == "invalidated_by_drift"
    assert evidence_replay["binding_errors"] == ["research_evidence_drift"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_canonical_backtest_artifact_drift_blocks_critique(tmp_path) -> None:
    service, selection, _, _ = _service(tmp_path)
    hypotheses = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-artifact-drift",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Artifact drift must block critique.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    draft = hypotheses["drafts"][0]
    backtest = await service.run_formula_backtest(
        FormulaBacktestRequest(
            idempotency_key="backtest-artifact-drift",
            requested_by="human:reese",
            session_id=hypotheses["session_id"],
            draft_id=draft["draft_id"],
            confirmation=BACKTEST_CONFIRMATION,
        )
    )
    row = service._db.rows[backtest["canonical_backtest"]["result_id"]]
    metrics = json.loads(row["metrics_json"])
    metrics["research_evidence_bundle"]["total_return"] = 999
    row["metrics_json"] = json.dumps(metrics)

    with pytest.raises(Exception, match="canonical_backtest_artifact_drift"):
        await service.critique(
            CritiqueRequest(
                idempotency_key="critique-artifact-drift",
                requested_by="human:reese",
                session_id=hypotheses["session_id"],
                draft_id=draft["draft_id"],
                backtest_run_id=backtest["backtest_run_id"],
                confirmation=CRITIQUE_EXPORT_CONFIRMATION,
            )
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_critique_with_unbound_citation_fails_closed_and_is_not_retried(
    tmp_path,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    hypotheses = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-critique-citation",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Critique citations must remain bound.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    draft = hypotheses["drafts"][0]
    backtest = await service.run_formula_backtest(
        FormulaBacktestRequest(
            idempotency_key="backtest-critique-citation",
            requested_by="human:reese",
            session_id=hypotheses["session_id"],
            draft_id=draft["draft_id"],
            confirmation=BACKTEST_CONFIRMATION,
        )
    )
    response = transport._responses[0].payload
    content = json.loads(response["choices"][0]["message"]["content"])
    content["citations"] = ["critique_input.nonexistent"]
    response["choices"][0]["message"]["content"] = json.dumps(content)
    request = CritiqueRequest(
        idempotency_key="critique-unbound-citation",
        requested_by="human:reese",
        session_id=hypotheses["session_id"],
        draft_id=draft["draft_id"],
        backtest_run_id=backtest["backtest_run_id"],
        confirmation=CRITIQUE_EXPORT_CONFIRMATION,
    )

    result = await service.critique(request)
    replay = await service.critique(request)

    assert result["status"] == "failed"
    assert result["artifact"] is None
    assert replay["reused"] is True
    assert len(transport.calls) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_critique_with_changed_canonical_binding_echo_fails_closed(
    tmp_path,
) -> None:
    service, selection, transport, _ = _service(tmp_path)
    hypotheses = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="hypothesis-critique-binding",
            requested_by="human:reese",
            account_alias="synthetic-research-only",
            research_question="Critique binding echoes must remain exact.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    draft = hypotheses["drafts"][0]
    backtest = await service.run_formula_backtest(
        FormulaBacktestRequest(
            idempotency_key="backtest-critique-binding",
            requested_by="human:reese",
            session_id=hypotheses["session_id"],
            draft_id=draft["draft_id"],
            confirmation=BACKTEST_CONFIRMATION,
        )
    )
    response = transport._responses[0].payload
    content = json.loads(response["choices"][0]["message"]["content"])
    content["canonical_binding_echo"] = {"total_return": 999}
    response["choices"][0]["message"]["content"] = json.dumps(content)

    result = await service.critique(
        CritiqueRequest(
            idempotency_key="critique-changed-binding",
            requested_by="human:reese",
            session_id=hypotheses["session_id"],
            draft_id=draft["draft_id"],
            backtest_run_id=backtest["backtest_run_id"],
            confirmation=CRITIQUE_EXPORT_CONFIRMATION,
        )
    )

    assert result["status"] == "failed"
    assert result["artifact"] is None
    assert len(transport.calls) == 2
