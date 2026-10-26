"""The formal research workflow keeps its evidence contract across transports."""

from __future__ import annotations

import json

import pytest

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.strategy_research_codex import CodexResearchSettings
from server.contracts.strategy_research import (
    HYPOTHESIS_EXPORT_CONFIRMATION,
    HypothesisGenerationRequest,
)
from tests.ai_runtime.test_strategy_research_workflow import (
    _hypothesis_response,
    _service,
)


@pytest.mark.asyncio
async def test_codex_formal_generation_binds_history_and_never_calls_http(
    tmp_path, monkeypatch
):
    service, selection, http, _ = _service(tmp_path, bind_account=False)
    service._settings = CodexResearchSettings(model_name="gpt-6.1-sol")
    calls = []
    history = {"related_trials": 262, "previous_result": "rejected"}

    def complete(**kwargs):
        calls.append(kwargs)
        pack = json.loads(kwargs["input_json"])
        assert pack["research_history"] == {
            "non_authoritative": True,
            "operator_supplied": True,
            "source": "operator_supplied_research_history",
            "content_fingerprint": "sha256:" + content_fingerprint(history),
            "content": history,
        }
        body = json.loads(
            _hypothesis_response(selection).payload["choices"][0]["message"]["content"]
        )
        body["drafts"][0]["citations"] = pack["output_contract"][
            "required_citation_ids"
        ]
        return json.dumps(body), {
            "transport_kind": "codex_app_server_rpc",
            "response_model": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "finish_reason": "completed",
        }

    monkeypatch.setattr(
        "server.ai_runtime.strategy_research_provider.complete_codex_research", complete
    )
    request = HypothesisGenerationRequest(
        idempotency_key="formal-codex-history",
        requested_by="human:reese",
        account_alias="strategy-only",
        research_question="Review the complete previous research history.",
        selection=selection,
        confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        research_history=history,
    )
    result = await service.generate_hypotheses(request)
    assert result["status"] == "completed"
    draft = result["drafts"][0]
    assert "research_history.content_fingerprint" in draft["citations"]
    provenance = draft["provider_provenance"]
    assert provenance["transport_kind"] == "codex_app_server_rpc"
    assert provenance["response_model"] is None
    assert provenance["usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert draft["executable"] is False
    again = await service.generate_hypotheses(request)
    assert again["reused"] is True
    assert len(calls) == 1
    assert http.calls == []
    saved = service._research_store.get_session(result["session_id"])
    assert json.loads(saved["request_json"])["research_history"] == history


@pytest.mark.asyncio
async def test_codex_malformed_response_is_terminal_without_http_or_retry(
    tmp_path, monkeypatch
):
    service, selection, http, _ = _service(tmp_path, bind_account=False)
    service._settings = CodexResearchSettings(model_name="gpt-6.1-sol")
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return '{"drafts": []}', {"transport_kind": "codex_app_server_rpc"}

    monkeypatch.setattr(
        "server.ai_runtime.strategy_research_provider.complete_codex_research", complete
    )
    request = HypothesisGenerationRequest(
        idempotency_key="formal-codex-invalid",
        requested_by="human:reese",
        account_alias="strategy-only",
        research_question="Generate one bounded research hypothesis.",
        selection=selection,
        confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
    )
    result = await service.generate_hypotheses(request)
    assert result["status"] == "failed"
    assert result["drafts"] == []
    await service.generate_hypotheses(request)
    assert len(calls) == 1
    assert http.calls == []
