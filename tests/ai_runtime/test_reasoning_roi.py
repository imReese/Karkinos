from __future__ import annotations

from server.ai_runtime.provider_connectivity_contracts import (
    ProviderConnectivitySettings,
)
from server.ai_runtime.reasoning_roi import (
    build_reasoning_roi_evidence,
    strategy_research_reasoning_policy,
)
from server.ai_runtime.strategy_research_values import (
    strategy_research_request_options,
)


def _settings() -> ProviderConnectivitySettings:
    return ProviderConnectivitySettings(
        provider_id="deepseek",
        model_name="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key="fixture-api-key",
        credential_source="test-only",
        enabled=True,
    )


def test_strategy_research_reasoning_policy_requests_maximum_reasoning():
    assert strategy_research_reasoning_policy() == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }


def test_strategy_research_request_options_use_maximum_reasoning_for_deepseek():
    assert strategy_research_request_options(_settings()) == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }


def test_strategy_research_request_options_use_maximum_reasoning_for_gemini():
    gemini_settings = ProviderConnectivitySettings(
        provider_id="google.gemini",
        model_name="gemini-3.8-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="fixture-api-key",
        credential_source="test-only",
        enabled=True,
    )
    assert strategy_research_request_options(gemini_settings) == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }


def test_reasoning_roi_evidence_passes_without_reasoning():
    evidence = build_reasoning_roi_evidence(
        reasoning_mode_requested=False,
        reasoning_content_present=False,
        reasoning_content_persisted=False,
    )
    assert evidence["status"] == "pass"
    assert evidence["reasoning_cost_incurred"] is False
    assert evidence["blocker"] is None
    assert len(evidence["evidence_fingerprint"]) == 64


def test_reasoning_roi_evidence_blocks_when_reasoning_present():
    evidence = build_reasoning_roi_evidence(
        reasoning_mode_requested=True,
        reasoning_content_present=True,
        reasoning_content_persisted=False,
    )
    assert evidence["status"] == "blocked"
    assert evidence["reasoning_cost_incurred"] is True
    assert evidence["blocker"] == "reasoning_content_billed_but_discarded"
