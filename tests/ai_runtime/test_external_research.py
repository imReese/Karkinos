from __future__ import annotations

import asyncio
import json
import sqlite3
import threading

import pytest

from server.ai_runtime.capture import (
    CAPTURE_TOOL_BY_TYPE,
    CapturedProjection,
    CaptureEvidenceType,
    CaptureSourceBatch,
    ContextCaptureAuditStore,
    HumanResearchContextCaptureService,
)
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.external_research import (
    EXTERNAL_BACKTEST_REPORT_CONFIRMATION,
    ExternalBacktestReportAuditStore,
    ExternalBacktestReportRejected,
    HumanExternalBacktestReportRequest,
    HumanExternalBacktestReportService,
    _decode_external_report,
)
from server.ai_runtime.karkinos_source import _research_evidence_projection
from server.ai_runtime.provider_connectivity import (
    HttpJsonResponse,
    ProviderConnectivitySettings,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict

NOW = "2026-07-14T05:00:00+00:00"
VALUATION_ID = "valuation-external-report-001"
LEDGER_CUTOFF_ID = 117
LEDGER_FINGERPRINT = "ledger-external-report-fingerprint-001"
EVIDENCE_REFERENCE_SEED = "saved-backtest-17"


class FixtureTransport:
    def __init__(self, response: HttpJsonResponse) -> None:
        self.response = response
        self.calls = []
        self._lock = threading.Lock()

    def post_json(self, **kwargs) -> HttpJsonResponse:
        with self._lock:
            self.calls.append(kwargs)
        return self.response


class BlockingFixtureTransport(FixtureTransport):
    def __init__(self, response: HttpJsonResponse) -> None:
        super().__init__(response)
        self.started = threading.Event()
        self.release = threading.Event()

    def post_json(self, **kwargs) -> HttpJsonResponse:
        with self._lock:
            self.calls.append(kwargs)
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("fixture transport was not released")
        return self.response


class FixtureCaptureSource:
    def __init__(self, batch: CaptureSourceBatch) -> None:
        self.batch = batch
        self.calls = 0

    async def load(self, request) -> CaptureSourceBatch:
        self.calls += 1
        assert request.evidence_types == (CaptureEvidenceType.RESEARCH_EVIDENCE,)
        return self.batch


def _payload(*, analysis_ready: bool = True) -> dict:
    blockers = [] if analysis_ready else ["after_cost_evidence_missing"]
    return {
        "schema_version": "karkinos.ai.research_evidence_capture.v2",
        "backtest_result_id": 17,
        "backtest_created_at": NOW,
        "performance_summary": {
            "initial_cash": 100_000.0,
            "final_equity": 100_888.28507,
            "total_return": 0.0088828507,
            "sharpe": 0.000012939959750936647,
            "sortino": 0.00001764646208314975,
            "max_drawdown": 0.1571207859506828,
            "win_rate": 0.2028169014084507,
            "duration_days": 540,
        },
        "test_window": {
            "start_date": "2024-01-01",
            "end_date": "2025-06-24",
            "assets": ["fixture-symbol"],
            "benchmark_return": None,
        },
        "after_cost_evidence": {
            "net_pnl": 888.28507,
            "total_cost": 1020.71493,
            "gross_pnl_before_costs": 1909.0,
            "net_return": 0.0088828507,
            "gross_return_before_costs": 0.01909,
        },
        "cost_summary": {
            "total_commission": 1020.71493,
            "total_slippage": 0.0,
            "total_trades": 20,
            "gross_turnover": 1821853.0,
        },
        "research_evidence_bundle": {
            "schema_version": "karkinos.research_evidence.v1",
            "bundle_id": EVIDENCE_REFERENCE_SEED,
            "gate_status": "pass",
            "promotion_gate": {
                "manual_confirmation_required": True,
                "does_not_enable_execution": True,
            },
            "limitations": ["OOS evidence is not present."],
        },
        "bundle_status": "available",
        "blocking_reasons": [],
        "analysis_ready": analysis_ready,
        "analysis_blocking_reasons": blockers,
        "persisted_backtest_facts_only": True,
    }


def _batch(*, status: str = "complete", analysis_ready: bool = True):
    return CaptureSourceBatch(
        valuation_snapshot_id=VALUATION_ID,
        ledger_cutoff_id=LEDGER_CUTOFF_ID,
        ledger_fingerprint=LEDGER_FINGERPRINT,
        projections=(
            CapturedProjection(
                tool_name=CAPTURE_TOOL_BY_TYPE[CaptureEvidenceType.RESEARCH_EVIDENCE],
                status=status,
                as_of=NOW,
                source_schema_version=("karkinos.ai.research_evidence_capture.v2"),
                payload=_payload(analysis_ready=analysis_ready),
            ),
        ),
    )


def _successful_response() -> HttpJsonResponse:
    content = {
        "title": "双均线回测证据审阅",
        "executive_summary": (
            "该回测在样本内仅取得小幅正收益，而最大回撤明显高于净收益；"
            "成本侵蚀显著，且缺少样本外验证。"
        ),
        "claims": [
            {
                "claim": "净收益为正，但收益相对最大回撤偏弱。",
                "confidence": "high",
                "evidence": "净收益约0.89%，最大回撤约15.71%。",
            },
            {
                "claim": "交易成本对毛收益形成明显侵蚀。",
                "confidence": "high",
                "evidence": "毛收益约1.91%，成本约占初始资金1.02%。",
            },
        ],
        "counterarguments": [
            {
                "risk": "单一资产与单一时间窗可能放大偶然性。",
                "evidence": "证据仅覆盖一个标的，且没有OOS结果。",
            }
        ],
        "limitations": [
            "缺少样本外验证。",
            "T+1、涨跌停、停牌与冲击成本仍有建模缺口。",
        ],
        "conclusion": "当前证据只支持继续研究，不支持策略晋级或交易执行。",
        "follow_up_checks": [
            "增加滚动样本外验证。",
            "补齐中国市场交易约束并开展参数敏感性测试。",
        ],
    }
    return HttpJsonResponse(
        status_code=200,
        payload={
            "id": "provider-envelope-private-id",
            "model": "fixture-model-20260714",
            "choices": [
                {"message": {"role": "assistant", "content": json.dumps(content)}}
            ],
            "usage": {
                "prompt_tokens": 800,
                "completion_tokens": 320,
                "total_tokens": 1120,
            },
        },
    )


def _request(
    *,
    idempotency_key: str = "external-report-001",
    research_question: str = "这条回测证据说明了什么，又不能说明什么？",
) -> HumanExternalBacktestReportRequest:
    return HumanExternalBacktestReportRequest(
        idempotency_key=idempotency_key,
        requested_by="human:reese",
        research_question=research_question,
        account_alias="private-primary-account",
        backtest_result_id=17,
        confirmation=EXTERNAL_BACKTEST_REPORT_CONFIRMATION,
    )


def _service(
    db_path,
    transport: FixtureTransport,
    *,
    status: str = "complete",
    analysis_ready: bool = True,
):
    evidence = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    capture_store = ContextCaptureAuditStore(db_path)
    report_store = ExternalBacktestReportAuditStore(db_path)
    evidence.init()
    ai_store.init()
    capture_store.init()
    report_store.init()
    source = FixtureCaptureSource(_batch(status=status, analysis_ready=analysis_ready))
    capture_service = HumanResearchContextCaptureService(
        source=source,
        evidence_repository=evidence,
        context_store=ai_store,
        capture_store=capture_store,
        now=lambda: NOW,
    )
    ticks = iter((10.0, 10.123, 20.0, 20.123))
    service = HumanExternalBacktestReportService(
        settings=ProviderConnectivitySettings(
            provider_id="fixture-provider",
            model_name="fixture-model",
            base_url="https://ai.example.test/v1",
            api_key="fixture-secret",
            credential_source="test-only",
            enabled=True,
        ),
        capture_service=capture_service,
        evidence_repository=evidence,
        ai_store=ai_store,
        report_store=report_store,
        transport=transport,
        now=lambda: NOW,
        monotonic=lambda: next(ticks),
    )
    return service, source


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_external_report_uses_only_bound_backtest_evidence_and_no_authority(
    tmp_path,
):
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE oms_orders (id TEXT PRIMARY KEY);
            CREATE TABLE ledger_entries (id TEXT PRIMARY KEY);
            CREATE TABLE risk_decisions (id TEXT PRIMARY KEY);
            CREATE TABLE capital_authorizations (id TEXT PRIMARY KEY);
            INSERT INTO oms_orders VALUES ('oms-before');
            INSERT INTO ledger_entries VALUES ('ledger-before');
            INSERT INTO risk_decisions VALUES ('risk-before');
            INSERT INTO capital_authorizations VALUES ('capital-before');
            """)
    transport = FixtureTransport(_successful_response())
    service, source = _service(db_path, transport)

    result = await service.run(_request())

    payload = result.to_dict()
    assert payload["workflow_status"] == "completed"
    assert payload["binding_validity"] == "valid"
    assert payload["audit_replay"]["valid"] is True
    assert payload["external_context_scope"] == (
        "saved_backtest_research_evidence_only"
    )
    assert payload["account_holdings_sent"] is False
    assert payload["provider_side_tools_enabled"] is False
    assert payload["research_output_is_account_fact"] is False
    assert payload["decision_input_created"] is False
    assert payload["trade_plan_created"] is False
    assert payload["memory_created"] is False
    assert payload["authority_effect"] == "none"
    assert payload["report"]["content"]["title"] == "双均线回测证据审阅"
    assert payload["report"]["content"]["authoritative"] is False
    assert payload["report"]["content"]["requires_human_review"] is True
    assert payload["report"]["content"]["provider_provenance"]["usage"] == {
        "prompt_tokens": 800,
        "completion_tokens": 320,
        "total_tokens": 1120,
    }
    assert len(payload["tool_calls"]) == 1
    assert payload["tool_calls"][0]["tool_name"] == "research_evidence.read"
    assert source.calls == 1
    assert len(transport.calls) == 1
    assert transport.calls[0]["timeout_seconds"] == 45.0
    external_payload = transport.calls[0]["payload"]
    serialized = json.dumps(external_payload, ensure_ascii=False)
    assert EVIDENCE_REFERENCE_SEED in serialized
    assert "private-primary-account" not in serialized
    assert VALUATION_ID not in serialized
    assert LEDGER_FINGERPRINT not in serialized
    assert "tools" not in external_payload
    with sqlite3.connect(db_path) as conn:
        dump = "\n".join(conn.iterdump())
        protected = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "oms_orders",
                "ledger_entries",
                "risk_decisions",
                "capital_authorizations",
            )
        }
    assert protected == {
        "oms_orders": 1,
        "ledger_entries": 1,
        "risk_decisions": 1,
        "capital_authorizations": 1,
    }
    assert "fixture-secret" not in dump
    assert "provider-envelope-private-id" not in dump


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exact_restart_reuses_report_without_second_provider_call(tmp_path):
    db_path = tmp_path / "app.db"
    transport = FixtureTransport(_successful_response())
    first_service, _ = _service(db_path, transport)
    first = await first_service.run(_request())
    restarted_service, restarted_source = _service(db_path, transport)

    second = await restarted_service.run(_request())

    assert second.record.analysis_id == first.record.analysis_id
    assert second.reused is True
    assert restarted_source.calls == 0
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_duplicate_is_inflight_and_never_double_charged(tmp_path):
    transport = BlockingFixtureTransport(_successful_response())
    service, _ = _service(tmp_path / "app.db", transport)

    first_task = asyncio.create_task(service.run(_request()))
    started = await asyncio.to_thread(transport.started.wait, 2)
    assert started is True
    duplicate = await service.run(_request())
    transport.release.set()
    first = await first_task

    assert duplicate.workflow.status.value in {"pending", "running"}
    assert first.workflow.status.value == "completed"
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_changed_input_reusing_idempotency_key_is_rejected_before_network(
    tmp_path,
):
    transport = FixtureTransport(_successful_response())
    service, _ = _service(tmp_path / "app.db", transport)
    await service.run(_request())

    with pytest.raises(IdempotencyConflict, match="different input"):
        await service.run(_request(research_question="换一个问题"))

    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incomplete_evidence_blocks_before_external_model(tmp_path):
    transport = FixtureTransport(_successful_response())
    service, _ = _service(
        tmp_path / "app.db",
        transport,
        status="degraded",
        analysis_ready=False,
    )

    with pytest.raises(ExternalBacktestReportRejected, match="complete evidence"):
        await service.run(_request())

    assert transport.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_provider_report_fails_closed_without_raw_body_persistence(
    tmp_path,
):
    db_path = tmp_path / "app.db"
    leaked = "not-json private-provider-body"
    transport = FixtureTransport(
        HttpJsonResponse(
            status_code=200,
            payload={
                "choices": [{"message": {"content": leaked}}],
                "model": "fixture-model",
            },
        )
    )
    service, _ = _service(db_path, transport)

    first = await service.run(_request())
    second = await service.run(_request())

    assert first.workflow.status.value == "failed"
    assert first.workflow.failure_code == "external_research_invalid_response"
    assert first.report is None
    assert second.workflow.status.value == "failed"
    assert len(transport.calls) == 1
    with sqlite3.connect(db_path) as conn:
        dump = "\n".join(conn.iterdump())
    assert leaked not in dump


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capture_v2_projects_persisted_performance_without_recalculation():
    class FixtureDb:
        async def get_backtest_result(self, result_id):
            assert result_id == 17
            return {
                "id": 17,
                "created_at": NOW,
                "initial_cash": 100_000.0,
                "final_equity": 100_888.28507,
                "total_return": 0.0088828507,
                "sharpe": 0.1,
                "sortino": 0.2,
                "max_drawdown": 0.1571207859506828,
                "win_rate": 0.2028169014084507,
                "duration_days": 540,
                "config_json": json.dumps(
                    {
                        "start_date": "2024-01-01",
                        "end_date": "2025-06-24",
                        "assets": ["fixture-symbol"],
                    }
                ),
                "cost_summary_json": json.dumps(
                    {"total_commission": 1020.71493, "total_trades": 20}
                ),
                "metrics_json": json.dumps(
                    {
                        "evidence_bundle": {
                            "net_pnl": 888.28507,
                            "total_cost": 1020.71493,
                        },
                        "research_evidence_bundle": {
                            "gate_status": "pass",
                            "bundle_id": "fixture-bundle",
                        },
                    }
                ),
            }

    projection = await _research_evidence_projection(
        FixtureDb(),
        tool_name="research_evidence.read",
        result_id=17,
    )

    assert projection.status == "complete"
    assert projection.source_schema_version == (
        "karkinos.ai.research_evidence_capture.v2"
    )
    assert projection.payload["performance_summary"]["total_return"] == (0.0088828507)
    assert projection.payload["performance_summary"]["max_drawdown"] == (
        0.1571207859506828
    )
    assert projection.payload["after_cost_evidence"]["total_cost"] == 1020.71493
    assert projection.payload["analysis_ready"] is True
    assert projection.payload["persisted_backtest_facts_only"] is True


@pytest.mark.unit
def test_report_decoder_accepts_explanatory_wrapper_but_still_validates_schema():
    response = _successful_response().payload
    raw = response["choices"][0]["message"]["content"]

    decoded = _decode_external_report(
        f"以下是结构化结果：\n{raw}\n以上内容仅供研究复核。",
        "ai-evidence-fixture",
    )

    assert decoded["title"] == "双均线回测证据审阅"
    assert decoded["claims"][0]["evidence_reference_ids"] == ["ai-evidence-fixture"]


@pytest.mark.unit
def test_report_decoder_normalizes_bounded_object_and_string_sections():
    content = {
        "title": "证据审阅",
        "executive_summary": "只支持继续研究。",
        "claims": {"supported": ["成本已经进入回测结果。", "数据质量门禁通过。"]},
        "risks": "缺少样本外证据。",
        "limitations": "中国市场交易约束仍不完整。",
        "conclusion": "不得据此晋级或执行。",
        "follow_up_checks": "补充滚动样本外检验。",
    }

    decoded = _decode_external_report(
        json.dumps(content, ensure_ascii=False),
        "ai-evidence-normalized",
    )

    assert len(decoded["claims"]) == 2
    assert decoded["claims"][0]["confidence"] == "unspecified"
    assert decoded["counterarguments"][0]["risk"] == "缺少样本外证据。"
    assert decoded["limitations"] == ["中国市场交易约束仍不完整。"]
    assert decoded["follow_up_checks"] == ["补充滚动样本外检验。"]
