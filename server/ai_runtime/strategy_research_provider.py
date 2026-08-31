"""External model edge for evidence-bound, zero-authority strategy research."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from server.ai_runtime.contracts import (
    ArtifactDraft,
    ArtifactKind,
    JsonObject,
    ToolRequest,
    canonical_json,
    content_fingerprint,
)
from server.ai_runtime.external_research_errors import (
    ExternalResearchAuthenticationError,
    ExternalResearchHttpError,
    ExternalResearchInvalidResponseError,
    ExternalResearchNetworkError,
    ExternalResearchRateLimitedError,
    ExternalResearchTimeoutError,
)
from server.ai_runtime.openai_compatibility import message_text
from server.ai_runtime.provider import (
    ProviderAdapter,
    ProviderRequest,
    ProviderResponse,
)
from server.ai_runtime.provider_call_window import ProviderSendAdmission
from server.ai_runtime.provider_connectivity_contracts import (
    JsonHttpTransport,
    ProviderConnectivitySettings,
    ProviderProbeError,
)
from server.ai_runtime.strategy_research_account_evidence import (
    sanitize_account_evidence,
)
from server.ai_runtime.strategy_research_citations import (
    build_critique_citation_catalog,
    citation_path_exists,
    compact_hypothesis_citation_catalog,
    resolve_hypothesis_citations,
)
from server.ai_runtime.strategy_research_model_contract import (
    critique_output_contract,
    hypothesis_output_contract,
    normalize_critique_payload,
    normalize_hypothesis_payload,
    strategy_research_system_prompt,
)
from server.ai_runtime.strategy_research_privacy import (
    research_pack_privacy_violations,
)
from server.ai_runtime.strategy_research_support import (
    decode_model_json,
    safe_provider_usage,
)
from server.ai_runtime.strategy_research_values import (
    ACCOUNT_STATE_TOOL,
    CATALOG_TOOL,
    RESEARCH_TOOL,
    SELECTION_TOOL,
    STRATEGY_RESEARCH_PROMPT_VERSION,
    strategy_research_request_options,
)
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_MAX_INPUT_BYTES,
    STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS,
    StrategyResearchRejected,
)

logger = logging.getLogger(__name__)


class StrategyResearchModelProvider(ProviderAdapter):
    """One external model call after permission-checked local tool reads."""

    def __init__(
        self,
        *,
        provider_id: str,
        settings: ProviderConnectivitySettings,
        mode: Literal["hypothesis", "critique"],
        evidence_reference_id: str,
        selection: JsonObject,
        research_question: str,
        critique_input: JsonObject | None,
        iteration_context: JsonObject | None,
        transport: JsonHttpTransport,
        monotonic: Callable[[], float],
        timeout_seconds: float,
        account_evidence_reference_id: str | None = None,
        send_admission: ProviderSendAdmission | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._settings = settings
        self._mode = mode
        self._evidence_reference_id = evidence_reference_id
        self._account_evidence_reference_id = account_evidence_reference_id
        self._selection = dict(selection)
        self._research_question = research_question
        self._critique_input = dict(critique_input or {})
        self._iteration_context = dict(iteration_context or {})
        self._transport = transport
        self._monotonic = monotonic
        self._timeout_seconds = timeout_seconds
        self._send_admission = send_admission

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if request.turn_index == 0:
            tool_requests = [
                ToolRequest(
                    "read-bound-research-evidence",
                    RESEARCH_TOOL,
                    {"evidence_reference_id": self._evidence_reference_id},
                )
            ]
            if self._account_evidence_reference_id is not None:
                tool_requests.append(
                    ToolRequest(
                        "read-bound-account-state",
                        ACCOUNT_STATE_TOOL,
                        {
                            "evidence_reference_id": (
                                self._account_evidence_reference_id
                            )
                        },
                    )
                )
            tool_requests.extend(
                (
                    ToolRequest("read-formula-catalog", CATALOG_TOOL, {}),
                    ToolRequest("read-frozen-selection", SELECTION_TOOL, {}),
                )
            )
            return ProviderResponse(
                tool_requests=tuple(tool_requests),
                message="Read the exact local evidence and reviewed formula boundary.",
            )
        expected_result_count = (
            4 if self._account_evidence_reference_id is not None else 3
        )
        if (
            request.turn_index != 1
            or len(request.tool_results) != expected_result_count
        ):
            raise ExternalResearchInvalidResponseError("unexpected_provider_turn")
        results = {item.tool_name: dict(item.output) for item in request.tool_results}
        evidence = results.get(RESEARCH_TOOL)
        account_evidence = results.get(ACCOUNT_STATE_TOOL)
        catalog = results.get(CATALOG_TOOL)
        selection = results.get(SELECTION_TOOL)
        if (
            not evidence
            or evidence.get("evidence_reference_id") != self._evidence_reference_id
        ):
            raise ExternalResearchInvalidResponseError("evidence_reference_mismatch")
        if (
            evidence.get("persisted_facts_only") is not True
            or evidence.get("authoritative") is not True
            or evidence.get("status") != "complete"
        ):
            raise ExternalResearchInvalidResponseError("evidence_not_authoritative")
        sanitized_account_evidence = None
        if self._account_evidence_reference_id is not None:
            if (
                not account_evidence
                or account_evidence.get("evidence_reference_id")
                != self._account_evidence_reference_id
            ):
                raise ExternalResearchInvalidResponseError(
                    "account_evidence_reference_mismatch"
                )
            if (
                account_evidence.get("persisted_facts_only") is not True
                or account_evidence.get("authoritative") is not True
                or account_evidence.get("status") != "complete"
            ):
                raise ExternalResearchInvalidResponseError(
                    "account_evidence_not_authoritative"
                )
            sanitized_account_evidence = sanitize_account_evidence(account_evidence)
        if not catalog or not selection:
            raise ExternalResearchInvalidResponseError("local_tool_result_missing")
        try:
            return self._invoke_external(
                evidence=dict(evidence),
                account_evidence=sanitized_account_evidence,
                catalog=dict(catalog),
                selection=dict(selection),
            )
        except ExternalResearchInvalidResponseError as exc:
            logger.warning("Strategy research provider response rejected: %s", exc)
            raise

    def _invoke_external(
        self,
        *,
        evidence: JsonObject,
        account_evidence: JsonObject | None,
        catalog: JsonObject,
        selection: JsonObject,
    ) -> ProviderResponse:
        citation_sources = {
            "saved_backtest_evidence": evidence.get("payload"),
            "approved_formula_catalog": catalog,
            "operator_frozen_selection": selection,
            "iteration_context": self._iteration_context,
        }
        if account_evidence is not None:
            citation_sources["saved_account_evidence"] = account_evidence
        hypothesis_citation_catalog = None
        critique_citation_catalog = None
        if self._mode == "hypothesis":
            hypothesis_citation_catalog = compact_hypothesis_citation_catalog(
                citation_sources=citation_sources,
            )
        else:
            citation_sources["critique_input"] = self._critique_input
            critique_citation_catalog = build_critique_citation_catalog(
                self._critique_input
            )
        input_payload = {
            "mode": self._mode,
            "research_question": self._research_question,
            "evidence_reference_id": self._evidence_reference_id,
            "saved_backtest_evidence": evidence.get("payload"),
            "approved_formula_catalog": catalog,
            "operator_frozen_selection": selection,
            "critique_input": (
                self._critique_input if self._mode == "critique" else None
            ),
            "iteration_context": (
                self._iteration_context if self._mode == "hypothesis" else None
            ),
            "boundaries": {
                "provider_side_tools": False,
                "arbitrary_code": False,
                "external_knowledge": False,
                "financial_metrics_must_come_from_input": True,
                "trade_plan_allowed": False,
                "authority_effect": "none",
            },
            "output_contract": (
                hypothesis_output_contract(
                    iterative=bool(self._iteration_context),
                    citation_catalog=hypothesis_citation_catalog or {},
                )
                if self._mode == "hypothesis"
                else critique_output_contract(
                    citation_catalog=critique_citation_catalog or {}
                )
            ),
        }
        if account_evidence is not None:
            input_payload["saved_account_evidence"] = account_evidence
        privacy_violations = research_pack_privacy_violations(input_payload)
        if privacy_violations:
            raise ExternalResearchInvalidResponseError(
                f"research_pack_privacy_violation:{privacy_violations[0]}"
            )
        serialized = canonical_json(input_payload)
        if len(serialized.encode("utf-8")) > STRATEGY_RESEARCH_MAX_INPUT_BYTES:
            raise StrategyResearchRejected("strategy_research_input_too_large")
        payload: JsonObject = {
            "model": self._settings.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": strategy_research_system_prompt(self._mode),
                },
                {"role": "user", "content": serialized},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS,
            "stream": False,
        }
        payload.update(strategy_research_request_options(self._settings))
        started = self._monotonic()
        try:
            if self._send_admission is not None:
                self._send_admission.require_allowed()
            response = self._transport.post_json(
                url=self._settings.endpoint_url,
                headers={
                    "Authorization": f"Bearer {self._settings.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Karkinos-Strategy-Research/1",
                },
                payload=payload,
                timeout_seconds=self._timeout_seconds,
            )
        except ProviderProbeError as exc:
            if exc.code == "provider_timeout":
                raise ExternalResearchTimeoutError("provider_timeout") from exc
            raise ExternalResearchNetworkError("provider_network_error") from exc
        latency_ms = max(0, round((self._monotonic() - started) * 1000))
        if response.status_code in {401, 403}:
            raise ExternalResearchAuthenticationError("provider_authentication_failed")
        if response.status_code == 429:
            raise ExternalResearchRateLimitedError("provider_rate_limited")
        if response.status_code < 200 or response.status_code >= 300:
            raise ExternalResearchHttpError("provider_http_error")
        body = response.payload
        if not isinstance(body, dict):
            raise ExternalResearchInvalidResponseError("provider_invalid_json")
        choices = body.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise ExternalResearchInvalidResponseError("provider_choices_missing")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise ExternalResearchInvalidResponseError("provider_output_truncated")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ExternalResearchInvalidResponseError("provider_message_missing")
        reasoning = message.get("reasoning_content")
        reasoning_chars = len(reasoning) if isinstance(reasoning, str) else 0
        content = message_text(message.get("content"))
        if not content:
            raise ExternalResearchInvalidResponseError("provider_content_missing")
        decoded = decode_model_json(content)
        if self._mode == "hypothesis":
            normalized = normalize_hypothesis_payload(
                decoded,
                expected_draft_count=(1 if self._iteration_context else None),
            )
            normalized = resolve_hypothesis_citations(
                normalized,
                citation_catalog=hypothesis_citation_catalog or {},
                citation_sources=citation_sources,
            )
        else:
            normalized = normalize_critique_payload(
                decoded,
                self._evidence_reference_id,
                self._critique_input,
                citation_catalog=critique_citation_catalog or {},
            )
        citation_groups = (
            [draft.get("citations") for draft in normalized["drafts"]]
            if self._mode == "hypothesis"
            else [normalized.get("citations")]
        )
        if any(
            not citation_path_exists(citation, citation_sources)
            for citations in citation_groups
            if isinstance(citations, list)
            for citation in citations
            if isinstance(citation, str)
        ):
            raise ExternalResearchInvalidResponseError(
                "provider_citation_not_in_bound_input"
            )
        normalized["provider_provenance"] = {
            "provider_id": self._provider_id,
            "configured_provider_source": self._settings.provider_id,
            "model_id": self._settings.model_id,
            "response_model": str(body.get("model") or self._settings.model_name),
            "prompt_version": STRATEGY_RESEARCH_PROMPT_VERSION,
            "request_payload_fingerprint": content_fingerprint(payload),
            "response_content_fingerprint": content_fingerprint(normalized),
            "latency_ms": latency_ms,
            "usage": safe_provider_usage(body.get("usage")),
            "finish_reason": choice.get("finish_reason"),
            "reasoning_mode_requested": payload.get("thinking") == {"type": "enabled"},
            "reasoning_effort_requested": payload.get("reasoning_effort"),
            "reasoning_content_present": reasoning_chars > 0,
            "reasoning_content_char_count": reasoning_chars,
            "reasoning_content_persisted": False,
            "raw_response_persisted": False,
            "account_evidence_exported": account_evidence is not None,
            "absolute_account_values_redacted": account_evidence is not None,
        }
        normalized.update(
            {
                "non_authoritative": True,
                "non_executable": True,
                "requires_human_review": True,
                "decision_input_created": False,
                "trade_plan_created": False,
                "authority_effect": "none",
            }
        )
        return ProviderResponse(
            artifacts=(
                ArtifactDraft(
                    kind=ArtifactKind.REPORT,
                    content=normalized,
                    evidence_reference_ids=tuple(
                        reference_id
                        for reference_id in (
                            self._evidence_reference_id,
                            self._account_evidence_reference_id,
                        )
                        if reference_id is not None
                    ),
                ),
            ),
            message="Strategy research artifact completed without authority.",
        )
