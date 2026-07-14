from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.external_memory_informed_analysis import (
    EXTERNAL_MEMORY_ANALYSIS_CONFIRMATION,
    HumanExternalMemoryAnalysisRequest,
    HumanExternalMemoryAnalysisService,
)
from server.ai_runtime.external_promoted_memory_analysis import (
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION,
    ExternalPromotedMemoryAnalysisStore,
    HumanExternalPromotedMemoryAnalysisService,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from tests.ai_runtime.test_external_memory_informed_analysis import (
    EvidenceAwareTransport,
    _deepseek_settings,
)
from tests.ai_runtime.test_external_reviewed_memory import _revocation_request
from tests.ai_runtime.test_external_reviewed_memory_retrieval import (
    _new_current_context,
    _promoted_memory,
)
from tests.ai_runtime.test_external_reviewed_memory_retrieval import (
    _request as _retrieval_request,
)
from tests.ai_runtime.test_external_reviewed_memory_retrieval import (
    _service as _retrieval_service,
)
from tests.ai_runtime.test_research_tasks import NOW


async def _prepared_promoted_retrieval(db_path):
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    context, current_records = _new_current_context(db_path, source_records)
    retrievals = _retrieval_service(db_path, promotions)
    retrieval = retrievals.start(
        _retrieval_request(promotion.promotion.promotion_id, context.snapshot_id)
    )
    return retrieval, promotions, promotion, current_records, retrievals


def _request(retrieval_id: str, **overrides):
    values = {
        "retrieval_id": retrieval_id,
        "idempotency_key": "external-promoted-memory-analysis-001",
        "requested_by": "human:reese",
        "research_question": "历史审查结论与当前持久化证据是否仍然一致？",
        "confirmation": EXTERNAL_MEMORY_ANALYSIS_CONFIRMATION,
        "schema_version": EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION,
    }
    values.update(overrides)
    return HumanExternalMemoryAnalysisRequest(**values)


def _service(
    db_path,
    retrieval_service,
    transport,
    *,
    settings_loader=_deepseek_settings,
    initialize=True,
):
    store = ExternalPromotedMemoryAnalysisStore(db_path)
    if initialize:
        store.init()
    ticks = iter(float(index) for index in range(40))
    inner = HumanExternalMemoryAnalysisService(
        settings_loader=settings_loader,
        retrieval_service=retrieval_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        analysis_store=store,
        transport=transport,
        now=lambda: NOW,
        monotonic=lambda: next(ticks),
    )
    return HumanExternalPromotedMemoryAnalysisService(
        analysis_service=inner,
        retrieval_service=retrieval_service,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_promoted_memory_analysis_uses_current_tools_and_preserves_thinking(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-memory-analysis.db"
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

    retrieval, _, promotion, current_records, retrievals = (
        await _prepared_promoted_retrieval(db_path)
    )
    with closing(sqlite3.connect(db_path)) as conn:
        legacy_count_before = conn.execute(
            "SELECT COUNT(*) FROM ai_external_memory_informed_analyses"
        ).fetchone()[0]
    transport = EvidenceAwareTransport()
    result = _service(db_path, retrievals, transport).start(
        _request(retrieval.stored.retrieval_id)
    )
    payload = result.to_dict()

    assert payload["schema_version"] == (
        "karkinos.ai.external_promoted_memory_analysis.v1"
    )
    assert payload["request_schema_version"] == (
        "karkinos.ai.external_promoted_memory_request.v1"
    )
    assert payload["workflow_status"] == "completed"
    assert payload["binding_validity"] == "valid"
    assert payload["promoted_memory_retrieval_eligible"] is True
    assert payload["promotion_ids"] == [promotion.promotion.promotion_id]
    assert payload["selected_memory_sources"] == [
        {
            "promotion_id": promotion.promotion.promotion_id,
            "review_id": promotion.promotion.review_id,
            "source_analysis_id": promotion.promotion.analysis_id,
            "memory_artifact_id": promotion.promotion.memory_artifact_id,
            "memory_artifact_fingerprint": (
                promotion.promotion.memory_artifact_fingerprint
            ),
        }
    ]
    assert payload["current_evidence_read_count"] == len(current_records) * 3
    assert payload["current_evidence_reads_complete"] is True
    assert [item["kind"] for item in payload["artifacts"]] == [
        "claim",
        "debate",
        "report",
    ]
    assert payload["external_model_invocation_count"] == 3
    assert payload["legacy_retrieval_v1_modified"] is False
    assert payload["provider_side_tools_enabled"] is False
    assert payload["model_reasoning_mode_preserved"] is True
    assert payload["reasoning_content_persisted"] is False
    assert payload["decision_handoff_enabled"] is False
    assert payload["trade_plan_created"] is False
    assert payload["authority_effect"] == "none"
    assert result.replay()["valid"] is True

    assert len(transport.calls) == 3
    for index, call in enumerate(transport.calls):
        request_payload = call["payload"]
        assert request_payload["thinking"] == {"type": "enabled"}
        assert request_payload["reasoning_effort"] == "high"
        assert "temperature" not in request_payload
        assert "tools" not in request_payload
        assert request_payload["max_tokens"] == 16_384
        provider_input = json.loads(request_payload["messages"][1]["content"])
        assert len(provider_input["current_canonical_evidence"]) == len(current_records)
        assert len(provider_input["prior_artifacts"]) == index
        assert (
            provider_input["historical_reviewed_memory"][0]["memory_artifact_id"]
            == promotion.promotion.memory_artifact_id
        )
        assert provider_input["input_contract"]["provider_side_tools"] is False
        assert provider_input["input_contract"]["external_knowledge_allowed"] is False

    with closing(sqlite3.connect(db_path)) as conn:
        dump = "\n".join(conn.iterdump())
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_promoted_memory_analyses"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_promoted_memory_model_calls"
            ).fetchone()[0]
            == 3
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_memory_informed_analyses"
            ).fetchone()[0]
            == legacy_count_before
        )
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )
    assert "RAW_FIXTURE_API_KEY" not in dump
    assert "RAW_PROVIDER_ENVELOPE_ID" not in dump
    assert "RAW_PRIVATE_REASONING_MUST_NOT_PERSIST" not in dump


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promoted_memory_analysis_is_restart_concurrency_and_key_idempotent(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-memory-idempotency.db"
    retrieval, _, _, _, retrievals = await _prepared_promoted_retrieval(db_path)
    transport = EvidenceAwareTransport()
    service = _service(db_path, retrievals, transport)
    request = _request(retrieval.stored.retrieval_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: service.start(request), range(2)))

    assert results[0].analysis.record.analysis_id == (
        results[1].analysis.record.analysis_id
    )
    assert len(transport.calls) == 3

    def fail_if_loaded():
        raise AssertionError("credentials must remain lazy during exact replay")

    restarted = _service(
        db_path,
        retrievals,
        transport,
        settings_loader=fail_if_loaded,
        initialize=False,
    ).start(request)
    assert restarted.analysis.reused is True
    assert restarted.replay()["valid"] is True
    assert len(transport.calls) == 3

    with pytest.raises(IdempotencyConflict, match="different input"):
        _service(
            db_path,
            retrievals,
            transport,
            settings_loader=fail_if_loaded,
            initialize=False,
        ).start(_request(retrieval.stored.retrieval_id, research_question="另一问题"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_output_and_revoked_source_fail_closed_without_history_loss(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-memory-fail-closed.db"
    retrieval, promotions, promotion, current_records, retrievals = (
        await _prepared_promoted_retrieval(db_path)
    )
    transport = EvidenceAwareTransport(invalid_stage="external_current_evidence_claim")
    service = _service(db_path, retrievals, transport)
    request = _request(retrieval.stored.retrieval_id)
    failed = service.start(request)

    assert failed.analysis.workflow.status.value == "failed"
    assert failed.analysis.workflow.failure_code == "external_memory_invalid_response"
    assert failed.analysis.artifacts == ()
    assert len(failed.analysis.tool_calls) == len(current_records)
    assert failed.analysis.model_calls[0].error_code == (
        "provider_output_is_not_json_object"
    )
    assert failed.replay()["valid"] is False
    assert service.start(request).analysis.reused is True
    assert len(transport.calls) == 1

    promotions.revoke(
        promotion.promotion.promotion_id,
        _revocation_request(),
    )
    invalidated = service.get(failed.analysis.record.analysis_id)
    assert invalidated.source_retrieval is not None
    assert invalidated.source_retrieval.retrieval_eligible is False
    assert invalidated.to_dict()["promoted_memory_retrieval_eligible"] is False
    assert invalidated.analysis.artifacts == ()
    assert invalidated.replay()["valid"] is False
    with closing(sqlite3.connect(db_path)) as conn:
        dump = "\n".join(conn.iterdump())
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_promoted_memory_analyses"
            ).fetchone()[0]
            == 1
        )
    assert "RAW_PRIVATE_FAILURE" not in dump
    assert "RAW_PRIVATE_REASONING_MUST_NOT_PERSIST" not in dump


@pytest.mark.unit
def test_promoted_memory_analysis_read_store_does_not_initialize_schema(tmp_path):
    db_path = tmp_path / "external-promoted-memory-read.db"
    store = ExternalPromotedMemoryAnalysisStore(db_path)

    assert store.get_by_idempotency_key("missing") is None
    assert store.list() == ()
    with pytest.raises(LookupError, match="not found"):
        store.get("missing")
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            == []
        )
