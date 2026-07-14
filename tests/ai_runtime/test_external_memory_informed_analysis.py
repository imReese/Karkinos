from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.external_memory_informed_analysis import (
    EXTERNAL_MEMORY_ANALYSIS_CONFIRMATION,
    ExternalMemoryAnalysisStore,
    ExternalMemoryInvalidResponseError,
    HumanExternalMemoryAnalysisRequest,
    HumanExternalMemoryAnalysisService,
    _decode_stage_output,
)
from server.ai_runtime.provider_connectivity import (
    HttpJsonResponse,
    ProviderConnectivitySettings,
    ProviderProbeError,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from tests.ai_runtime.test_memory_informed_analysis import _prepared_retrieval
from tests.ai_runtime.test_memory_retrieval import _retrieval_service
from tests.ai_runtime.test_research_tasks import NOW


class EvidenceAwareTransport:
    def __init__(self, *, invalid_stage: str | None = None) -> None:
        self.invalid_stage = invalid_stage
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def post_json(self, **kwargs) -> HttpJsonResponse:
        with self._lock:
            self.calls.append(kwargs)
        provider_input = json.loads(kwargs["payload"]["messages"][1]["content"])
        stage_id = provider_input["stage_id"]
        if stage_id == self.invalid_stage:
            content = "RAW_PRIVATE_FAILURE: not valid JSON"
        else:
            contract = provider_input["output_contract"]
            reference_ids = contract["allowed_evidence_reference_ids"]
            memory_ids = contract["allowed_memory_artifact_ids"]
            content = json.dumps(
                {
                    "title": f"{stage_id} 的证据审阅",
                    "summary": "只基于当前持久化证据形成阶段性研究结论。",
                    "findings": [
                        {
                            "statement": "当前证据支持继续验证一项历史假设。",
                            "confidence": "中",
                            "evidence_reference_ids": reference_ids,
                            "memory_artifact_ids": memory_ids[:1],
                        }
                    ],
                    "counterpoints": [
                        {
                            "statement": "有限样本不能支持交易或资本授权结论。",
                            "confidence": "high",
                            "evidence_reference_ids": [reference_ids[0]],
                            "memory_artifact_ids": [],
                        }
                    ],
                    "limitations": ["缺少新的独立验证批次。"],
                    "follow_up_checks": ["在相同证据身份下执行确定性复核。"],
                    "conclusion": "只支持继续研究并由人工复核。",
                },
                ensure_ascii=False,
            )
        return HttpJsonResponse(
            status_code=200,
            payload={
                "id": "RAW_PROVIDER_ENVELOPE_ID",
                "model": "fixture-reasoning-model-20260714",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "RAW_PRIVATE_REASONING_MUST_NOT_PERSIST",
                            "content": content,
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 700,
                    "completion_tokens": 240,
                    "total_tokens": 940,
                },
            },
        )


class ProviderFailureTransport:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = []

    def post_json(self, **kwargs) -> HttpJsonResponse:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _settings() -> ProviderConnectivitySettings:
    return ProviderConnectivitySettings(
        provider_id="fixture-openai-compatible",
        model_name="fixture-reasoning-model",
        base_url="https://ai.example.test/v1",
        api_key="RAW_FIXTURE_API_KEY",
        credential_source="test-only",
        enabled=True,
    )


def _request(retrieval_id: str, **overrides) -> HumanExternalMemoryAnalysisRequest:
    values = {
        "retrieval_id": retrieval_id,
        "idempotency_key": "external-memory-analysis-001",
        "requested_by": "human:reese",
        "research_question": "历史研究判断与当前持久化证据是否仍然一致？",
        "confirmation": EXTERNAL_MEMORY_ANALYSIS_CONFIRMATION,
    }
    values.update(overrides)
    return HumanExternalMemoryAnalysisRequest(**values)


def _service(db_path, transport, *, settings_loader=_settings, initialize=True):
    store = ExternalMemoryAnalysisStore(db_path)
    if initialize:
        store.init()
    ticks = iter(float(index) for index in range(20))
    return HumanExternalMemoryAnalysisService(
        settings_loader=settings_loader,
        retrieval_service=_retrieval_service(db_path),
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        analysis_store=store,
        transport=transport,
        now=lambda: NOW,
        monotonic=lambda: next(ticks),
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_external_memory_analysis_rereads_every_evidence_stage_without_authority(
    tmp_path,
):
    db_path = tmp_path / "external-memory.db"
    protected_tables = (
        "oms_orders",
        "ledger_entries",
        "risk_decisions",
        "runtime_controls",
        "capital_authorizations",
        "decision_handoffs",
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for table in protected_tables:
            conn.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
            )
            conn.execute(f"INSERT INTO {table} (marker) VALUES ('protected')")

    retrieval, context, current_records = await _prepared_retrieval(db_path)
    transport = EvidenceAwareTransport()
    result = _service(db_path, transport).start(_request(retrieval.stored.retrieval_id))
    payload = result.to_dict()

    assert payload["workflow_status"] == "completed"
    assert payload["binding_validity"] == "valid"
    assert payload["context_snapshot_id"] == context.snapshot_id
    assert payload["valuation_snapshot_id"] == "valuation-current-002"
    assert payload["ledger_cutoff_id"] == 145
    assert payload["current_evidence_reads_complete"] is True
    assert payload["current_evidence_read_count"] == len(current_records) * 3
    assert [item["kind"] for item in payload["artifacts"]] == [
        "claim",
        "debate",
        "report",
    ]
    assert [item["stage_id"] for item in payload["model_calls"]] == [
        "external_current_evidence_claim",
        "external_memory_evidence_debate",
        "external_memory_evidence_report",
    ]
    assert all(item["status"] == "completed" for item in payload["model_calls"])
    assert all(
        item["reasoning_content_present"] is True
        and item["reasoning_content_persisted"] is False
        for item in payload["model_calls"]
    )
    assert payload["external_model_invocation_count"] == 3
    assert payload["account_alias_sent"] is False
    assert payload["credentials_sent_as_content"] is False
    assert payload["provider_side_tools_enabled"] is False
    assert payload["model_reasoning_mode_preserved"] is True
    assert payload["memory_input_is_current_fact"] is False
    assert payload["research_output_is_account_fact"] is False
    assert payload["decision_handoff_enabled"] is False
    assert payload["trade_plan_created"] is False
    assert payload["authority_effect"] == "none"
    assert result.replay().valid is True

    assert len(transport.calls) == 3
    for index, call in enumerate(transport.calls):
        assert call["timeout_seconds"] == 60.0
        external_payload = call["payload"]
        assert "tools" not in external_payload
        assert external_payload.get("thinking") != {"type": "disabled"}
        assert external_payload["response_format"] == {"type": "json_object"}
        assert external_payload["max_tokens"] == 8192
        provider_input = json.loads(external_payload["messages"][1]["content"])
        assert len(provider_input["current_canonical_evidence"]) == len(current_records)
        assert provider_input["input_contract"]["provider_side_tools"] is False
        assert (
            provider_input["input_contract"]["historical_memory_is_current_fact"]
            is False
        )
        assert len(provider_input["prior_artifacts"]) == index
        serialized = json.dumps(external_payload, ensure_ascii=False)
        assert "RAW_FIXTURE_API_KEY" not in serialized
        assert "primary" not in serialized

    with closing(sqlite3.connect(db_path)) as conn:
        dump = "\n".join(conn.iterdump())
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )
    assert "RAW_FIXTURE_API_KEY" not in dump
    assert "RAW_PROVIDER_ENVELOPE_ID" not in dump
    assert "RAW_PRIVATE_REASONING_MUST_NOT_PERSIST" not in dump


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exact_restart_is_lazy_and_never_bills_or_loads_credentials_twice(
    tmp_path,
):
    db_path = tmp_path / "external-memory-restart.db"
    retrieval, _, _ = await _prepared_retrieval(db_path)
    transport = EvidenceAwareTransport()
    request = _request(retrieval.stored.retrieval_id)
    first = _service(db_path, transport).start(request)

    def fail_if_loaded():
        raise AssertionError("credentials must not be loaded for exact replay")

    restarted = _service(
        db_path,
        transport,
        settings_loader=fail_if_loaded,
        initialize=False,
    ).start(request)

    assert restarted.record.analysis_id == first.record.analysis_id
    assert restarted.reused is True
    assert restarted.workflow.status.value == "completed"
    assert len(transport.calls) == 3
    with pytest.raises(IdempotencyConflict, match="different input"):
        _service(
            db_path,
            transport,
            settings_loader=fail_if_loaded,
            initialize=False,
        ).start(
            _request(
                retrieval.stored.retrieval_id,
                research_question="同一 key 不得换成另一问题。",
            )
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_duplicate_claims_one_analysis_and_three_model_calls(
    tmp_path,
):
    db_path = tmp_path / "external-memory-concurrent.db"
    retrieval, _, _ = await _prepared_retrieval(db_path)
    transport = EvidenceAwareTransport()
    service = _service(db_path, transport)
    request = _request(retrieval.stored.retrieval_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: service.start(request), range(2)))

    assert results[0].record.analysis_id == results[1].record.analysis_id
    assert len(transport.calls) == 3
    completed = service.get(results[0].record.analysis_id)
    assert completed.workflow.status.value == "completed"
    assert completed.replay().valid is True
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_memory_informed_analyses"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_memory_model_calls"
            ).fetchone()[0]
            == 3
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_model_output_fails_closed_and_is_not_retried_or_persisted(
    tmp_path,
):
    db_path = tmp_path / "external-memory-invalid.db"
    retrieval, _, current_records = await _prepared_retrieval(db_path)
    transport = EvidenceAwareTransport(invalid_stage="external_current_evidence_claim")
    request = _request(retrieval.stored.retrieval_id)
    failed = _service(db_path, transport).start(request)

    assert failed.workflow.status.value == "failed"
    assert failed.workflow.failure_code == "external_memory_invalid_response"
    assert failed.artifacts == ()
    assert len(failed.tool_calls) == len(current_records)
    assert len(failed.model_calls) == 1
    assert failed.model_calls[0].status == "failed"
    assert failed.model_calls[0].error_code == "provider_output_is_not_json_object"
    assert failed.current_evidence_reads_complete is False
    assert failed.replay().valid is False

    exact_retry = _service(db_path, transport, initialize=False).start(request)
    assert exact_retry.reused is True
    assert exact_retry.workflow.status.value == "failed"
    assert len(transport.calls) == 1
    with closing(sqlite3.connect(db_path)) as conn:
        dump = "\n".join(conn.iterdump())
    assert "RAW_PRIVATE_FAILURE" not in dump
    assert "RAW_PRIVATE_REASONING_MUST_NOT_PERSIST" not in dump


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        (ProviderProbeError("provider_timeout"), "provider_timeout"),
        (
            HttpJsonResponse(
                status_code=401,
                payload={"error": "RAW_PROVIDER_AUTH_BODY"},
            ),
            "provider_authentication_failed",
        ),
    ],
)
async def test_provider_failures_are_sanitized_terminal_audit_facts(
    tmp_path,
    outcome,
    expected_code,
):
    db_path = tmp_path / f"external-memory-{expected_code}.db"
    retrieval, _, _ = await _prepared_retrieval(db_path)
    transport = ProviderFailureTransport(outcome)
    failed = _service(db_path, transport).start(_request(retrieval.stored.retrieval_id))

    assert failed.workflow.status.value == "failed"
    assert len(failed.model_calls) == 1
    assert failed.model_calls[0].status == "failed"
    assert failed.model_calls[0].error_code == expected_code
    assert len(transport.calls) == 1
    with closing(sqlite3.connect(db_path)) as conn:
        dump = "\n".join(conn.iterdump())
    assert "RAW_PROVIDER_AUTH_BODY" not in dump
    assert "RAW_FIXTURE_API_KEY" not in dump


@pytest.mark.unit
@pytest.mark.asyncio
async def test_current_evidence_drift_invalidates_without_deleting_external_history(
    tmp_path,
):
    db_path = tmp_path / "external-memory-drift.db"
    retrieval, _, current_records = await _prepared_retrieval(db_path)
    transport = EvidenceAwareTransport()
    service = _service(db_path, transport)
    completed = service.start(_request(retrieval.stored.retrieval_id))
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? WHERE reference_id = ?",
            ('{"tampered":true}', current_records[0].reference_id),
        )

    invalidated = service.get(completed.record.analysis_id)

    assert invalidated.workflow.status.value == "completed"
    assert invalidated.binding_validity == "invalidated_by_drift"
    assert "retrieval_or_current_evidence_invalid" in invalidated.binding_errors
    assert len(invalidated.artifacts) == 3
    assert len(transport.calls) == 3
    assert invalidated.replay().valid is False


@pytest.mark.unit
def test_response_normalizer_accepts_common_json_aliases_but_rejects_unknown_evidence():
    decoded = _decode_stage_output(
        """```json
        {
          "标题": "证据审阅",
          "执行摘要": "当前证据只支持继续研究。",
          "claims": [{
            "claim": "一项受约束的判断。",
            "confidence": "中",
            "evidence_refs": ["evidence-1"],
            "memory_refs": ["memory-1"]
          }],
          "risks": [{
            "risk": "仍可能存在替代解释。",
            "confidence": "low",
            "sources": "依据 evidence-1。"
          }],
          "局限性": "证据窗口有限。",
          "下一步检查": "补充独立验证批次。",
          "总体结论": "不得据此签发交易权限。"
        }
        ```""",
        allowed_reference_ids=("evidence-1",),
        allowed_memory_ids=("memory-1",),
    )

    assert decoded["findings"][0]["confidence"] == "medium"
    assert decoded["counterpoints"][0]["evidence_reference_ids"] == ["evidence-1"]
    with pytest.raises(
        ExternalMemoryInvalidResponseError,
        match="contains_unknown_id",
    ):
        _decode_stage_output(
            json.dumps(
                {
                    "title": "t",
                    "summary": "s",
                    "findings": [
                        {
                            "statement": "f",
                            "confidence": "high",
                            "evidence_reference_ids": ["invented"],
                        }
                    ],
                    "counterpoints": [
                        {
                            "statement": "c",
                            "confidence": "low",
                            "evidence_reference_ids": ["evidence-1"],
                        }
                    ],
                    "limitations": ["l"],
                    "follow_up_checks": ["n"],
                    "conclusion": "c",
                }
            ),
            allowed_reference_ids=("evidence-1",),
            allowed_memory_ids=(),
        )


@pytest.mark.unit
def test_request_and_read_store_fail_closed_without_schema(tmp_path):
    with pytest.raises(PermissionError, match="explicit financial evidence export"):
        _request("retrieval-1", confirmation="wrong")
    with pytest.raises(ValueError, match="within"):
        HumanExternalMemoryAnalysisService(
            settings_loader=_settings,
            retrieval_service=object(),
            ai_store=object(),
            evidence_repository=object(),
            analysis_store=object(),
            transport=EvidenceAwareTransport(),
            model_timeout_seconds=61,
        )

    db_path = tmp_path / "external-memory-read.db"
    store = ExternalMemoryAnalysisStore(db_path)
    assert store.list() == ()
    assert store.list_model_calls("workflow-missing") == ()
    with pytest.raises(LookupError, match="not found"):
        store.get("analysis-missing")
    with closing(sqlite3.connect(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "ai_external_memory_informed_analyses" not in tables
