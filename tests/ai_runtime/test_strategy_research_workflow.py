from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from threading import Event, Lock

import pandas as pd
import pytest

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.store import DataStore
from server.ai_runtime.capture import (
    CAPTURE_TOOL_BY_TYPE,
    CapturedProjection,
    CaptureEvidenceType,
    CaptureSourceBatch,
    ContextCaptureAuditStore,
    HumanResearchContextCaptureService,
)
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
)
from server.ai_runtime.provider_connectivity import (
    HttpJsonResponse,
    ProviderConnectivitySettings,
)
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
            return self._responses.pop(0)


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
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def load(self, request) -> CaptureSourceBatch:
        self.calls += 1
        return CaptureSourceBatch(
            valuation_snapshot_id="not-applicable-strategy-research",
            ledger_cutoff_id=0,
            ledger_fingerprint="not-applicable-strategy-research",
            projections=(
                CapturedProjection(
                    tool_name=CAPTURE_TOOL_BY_TYPE[
                        CaptureEvidenceType.RESEARCH_EVIDENCE
                    ],
                    status="complete",
                    as_of=NOW,
                    source_schema_version="karkinos.ai.research_evidence_capture.v2",
                    payload=self.payload,
                ),
            ),
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


def _hypothesis_response(selection: StrategyResearchSelection) -> HttpJsonResponse:
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
        "citations": ["saved_backtest_evidence.performance_summary"],
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
            "citations": ["critique_input.canonical_research_evidence"],
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


def _service(tmp_path):
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
        configured_source=None,
        data_handlers={
            symbol: DataHandler(bars, symbol, BarFrequency.DAILY, AssetClass.STOCK)
        },
        store=market,
        source_names=[],
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
    db_path = tmp_path / "app.db"
    evidence = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    capture_store = ContextCaptureAuditStore(db_path)
    research_store = StrategyResearchAuditStore(db_path)
    evidence.init()
    ai_store.init()
    capture_store.init()
    research_store.init()
    source = FixtureCaptureSource(captured_payload)
    capture = HumanResearchContextCaptureService(
        source=source,
        evidence_repository=evidence,
        context_store=ai_store,
        capture_store=capture_store,
        now=lambda: NOW,
    )
    transport = FixtureTransport(
        [_hypothesis_response(selection), _critique_response()]
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
    assert len(transport.calls) == 2
    assert all(call["payload"].get("tools") is None for call in transport.calls)
    assert all(
        call["payload"]["thinking"] == {"type": "enabled"} for call in transport.calls
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
@pytest.mark.asyncio
async def test_unknown_hypothesis_citation_fails_closed(tmp_path) -> None:
    service, selection, transport, _ = _service(tmp_path)
    response = transport._responses[0].payload
    content = json.loads(response["choices"][0]["message"]["content"])
    content["drafts"][0]["citations"] = ["saved_backtest_evidence.nonexistent"]
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
