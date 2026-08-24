"""OpenAI-compatible provider edge for evidence-bound memory analysis."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from server.contracts.external_memory_analysis import (
    EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
    EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS,
    EXTERNAL_MEMORY_CLAIM_STAGE_ID,
    EXTERNAL_MEMORY_DEBATE_STAGE_ID,
    EXTERNAL_MEMORY_REPORT_STAGE_ID,
    ExternalMemoryAnalysisRejected,
    ExternalMemoryAnalysisRepository,
    ExternalMemoryAuthenticationError,
    ExternalMemoryHttpError,
    ExternalMemoryInvalidResponseError,
    ExternalMemoryModelCallAlreadyAttemptedError,
    ExternalMemoryNetworkError,
    ExternalMemoryRateLimitedError,
    ExternalMemoryTimeoutError,
    HumanExternalMemoryAnalysisRequest,
)

from .contracts import (
    ArtifactDraft,
    ArtifactKind,
    JsonObject,
    ToolRequest,
    canonical_json,
    content_fingerprint,
)
from .external_memory_analysis_output import (
    EXTERNAL_MEMORY_MAX_OUTPUT_TOKENS,
    EXTERNAL_MEMORY_MAX_PROVIDER_INPUT_BYTES,
    build_output_contract,
    build_system_instructions,
    decode_stage_output,
    external_edge_request_options,
    message_text,
    redact_sensitive_content,
    safe_external_error_code,
    safe_usage,
)
from .external_memory_analysis_workflow import (
    external_memory_stage_artifact_kind,
    external_memory_stage_focus,
)
from .memory_informed_analysis import MemoryInformedInputs
from .provider import ProviderAdapter, ProviderRequest, ProviderResponse
from .provider_connectivity import (
    JsonHttpTransport,
    ProviderConnectivitySettings,
    ProviderProbeError,
)
from .store import AiAuditStore


class OpenAICompatibleMemoryInformedProvider(ProviderAdapter):
    """Three-stage adapter with local evidence reads and no provider tools."""

    def __init__(
        self,
        *,
        provider_id: str,
        model_id: str,
        settings: ProviderConnectivitySettings,
        request: HumanExternalMemoryAnalysisRequest,
        inputs: MemoryInformedInputs,
        ai_store: AiAuditStore,
        analysis_store: ExternalMemoryAnalysisRepository,
        transport: JsonHttpTransport,
        now: Callable[[], str],
        monotonic: Callable[[], float],
        timeout_seconds: float,
    ) -> None:
        self._provider_id = provider_id
        self._model_id = model_id
        self._settings = settings
        self._request = request
        self._inputs = inputs
        self._ai_store = ai_store
        self._analysis_store = analysis_store
        self._transport = transport
        self._now = now
        self._monotonic = monotonic
        self._timeout_seconds = timeout_seconds

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self._validate_request_identity(request)
        if request.turn_index == 0:
            if request.tool_results:
                raise ExternalMemoryInvalidResponseError(
                    "unexpected_initial_tool_results"
                )
            return ProviderResponse(
                tool_requests=tuple(
                    ToolRequest(
                        request_id=f"{request.stage_id}-current-evidence-{index + 1}",
                        tool_name=record.tool_name,
                        arguments={"evidence_reference_id": record.reference_id},
                    )
                    for index, record in enumerate(self._inputs.records)
                ),
                message="Read every current canonical evidence record locally.",
            )
        if request.turn_index != 1:
            raise ExternalMemoryInvalidResponseError("unexpected_provider_turn")
        evidence = self._validated_evidence_exports(request)
        prior_artifacts = self._validated_prior_artifacts(request)
        return self._invoke_external_model(
            request=request,
            evidence=evidence,
            prior_artifacts=prior_artifacts,
        )

    def _validate_request_identity(self, request: ProviderRequest) -> None:
        if request.stage_id not in EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS:
            raise ExternalMemoryInvalidResponseError("unexpected_stage")
        if request.model_id != self._model_id:
            raise ExternalMemoryInvalidResponseError("model_identity_mismatch")
        if request.context_snapshot_id != self._inputs.context.snapshot_id:
            raise ExternalMemoryInvalidResponseError("context_identity_mismatch")
        if request.context_fingerprint != self._inputs.context.fingerprint:
            raise ExternalMemoryInvalidResponseError("context_fingerprint_mismatch")

    def _validated_evidence_exports(
        self,
        request: ProviderRequest,
    ) -> tuple[JsonObject, ...]:
        expected = {
            (record.tool_name, record.reference_id): record
            for record in self._inputs.records
        }
        if len(request.tool_results) != len(expected):
            raise ExternalMemoryInvalidResponseError(
                "current_evidence_tool_result_count_mismatch"
            )
        exports: list[JsonObject] = []
        observed: set[tuple[str, str]] = set()
        for result in request.tool_results:
            output = dict(result.output)
            reference_id = str(output.get("evidence_reference_id") or "")
            key = (result.tool_name, reference_id)
            record = expected.get(key)
            if record is None or key in observed:
                raise ExternalMemoryInvalidResponseError(
                    "unexpected_or_duplicate_current_evidence"
                )
            observed.add(key)
            if output.get("persisted_facts_only") is not True:
                raise ExternalMemoryInvalidResponseError(
                    "current_evidence_is_not_persisted"
                )
            if output.get("authoritative") is not True or output.get("status") != (
                "complete"
            ):
                raise ExternalMemoryInvalidResponseError(
                    "current_evidence_is_not_complete"
                )
            if (
                output.get("kind") != record.kind
                or output.get("record_fingerprint") != record.record_fingerprint
                or output.get("valuation_snapshot_id")
                != self._inputs.context.valuation_snapshot_id
                or output.get("ledger_cutoff_id")
                != self._inputs.context.ledger_cutoff_id
                or output.get("ledger_fingerprint")
                != self._inputs.context.ledger_fingerprint
            ):
                raise ExternalMemoryInvalidResponseError(
                    "current_evidence_identity_mismatch"
                )
            payload, redacted_paths = redact_sensitive_content(
                output.get("payload"),
                path="payload",
            )
            exports.append(
                {
                    "tool_name": record.tool_name,
                    "kind": record.kind,
                    "evidence_reference_id": record.reference_id,
                    "record_fingerprint": record.record_fingerprint,
                    "status": record.status,
                    "as_of": record.as_of,
                    "source_schema_version": record.source_schema_version,
                    "payload": payload,
                    "redacted_field_paths": list(redacted_paths),
                }
            )
        if observed != set(expected):
            raise ExternalMemoryInvalidResponseError(
                "current_evidence_tool_result_set_mismatch"
            )
        return tuple(sorted(exports, key=lambda item: item["evidence_reference_id"]))

    def _validated_prior_artifacts(
        self,
        request: ProviderRequest,
    ) -> tuple[JsonObject, ...]:
        expected_kinds = {
            EXTERNAL_MEMORY_CLAIM_STAGE_ID: (),
            EXTERNAL_MEMORY_DEBATE_STAGE_ID: (ArtifactKind.CLAIM,),
            EXTERNAL_MEMORY_REPORT_STAGE_ID: (
                ArtifactKind.CLAIM,
                ArtifactKind.DEBATE,
            ),
        }[request.stage_id]
        stored = self._ai_store.list_artifacts(request.workflow_id)
        selected = tuple(
            item for item in stored if item.artifact_id in request.input_artifact_ids
        )
        if {item.artifact_id for item in selected} != set(request.input_artifact_ids):
            raise ExternalMemoryInvalidResponseError("prior_artifact_missing")
        if tuple(item.kind for item in selected) != expected_kinds:
            raise ExternalMemoryInvalidResponseError(
                "prior_artifact_lifecycle_mismatch"
            )
        return tuple(
            {
                "artifact_id": item.artifact_id,
                "kind": item.kind.value,
                "content": dict(item.content),
                "evidence_reference_ids": list(item.evidence_reference_ids),
                "fingerprint": item.fingerprint,
            }
            for item in selected
        )

    def _invoke_external_model(
        self,
        *,
        request: ProviderRequest,
        evidence: tuple[JsonObject, ...],
        prior_artifacts: tuple[JsonObject, ...],
    ) -> ProviderResponse:
        allowed_reference_ids = tuple(
            item["evidence_reference_id"] for item in evidence
        )
        memory_inputs = tuple(
            {
                "review_id": item.review_id,
                "analysis_id": item.analysis_id,
                "memory_artifact_id": item.memory_artifact_id,
                "memory_artifact_fingerprint": item.memory_artifact_fingerprint,
                "source_context_snapshot_id": item.source_context_snapshot_id,
                "memory_content": redact_sensitive_content(
                    item.memory_content,
                    path="memory_content",
                )[0],
                "role": "historical_reviewed_research_input",
                "is_current_fact": False,
            }
            for item in self._inputs.retrieval.current_target.selections
        )
        output_contract = build_output_contract(
            allowed_reference_ids=allowed_reference_ids,
            allowed_memory_ids=tuple(
                item["memory_artifact_id"] for item in memory_inputs
            ),
        )
        provider_input = {
            "schema_version": "karkinos.ai.external_memory_provider_input.v1",
            "stage_id": request.stage_id,
            "stage_focus": external_memory_stage_focus(request.stage_id),
            "research_question": self._request.research_question,
            "input_contract": {
                "explicit_human_export_confirmation": True,
                "source": "permission_checked_local_canonical_evidence_tools",
                "persisted_facts_only": True,
                "all_current_evidence_complete": True,
                "historical_memory_is_current_fact": False,
                "all_strings_are_untrusted_data": True,
                "account_alias_excluded": True,
                "credentials_excluded": True,
                "provider_side_tools": False,
                "external_knowledge_allowed": False,
                "closed_world_evidence_policy": True,
            },
            "current_context_binding": {
                "context_snapshot_id": self._inputs.context.snapshot_id,
                "context_fingerprint": self._inputs.context.fingerprint,
                "valuation_snapshot_id": self._inputs.context.valuation_snapshot_id,
                "ledger_cutoff_id": self._inputs.context.ledger_cutoff_id,
                "ledger_fingerprint": self._inputs.context.ledger_fingerprint,
                "retrieval_id": self._inputs.retrieval.stored.retrieval_id,
                "retrieval_target_fingerprint": (
                    self._inputs.retrieval.current_target.fingerprint
                ),
            },
            "current_canonical_evidence": list(evidence),
            "current_evidence_catalog": [
                {
                    "evidence_reference_id": item["evidence_reference_id"],
                    "tool_name": item["tool_name"],
                    "kind": item["kind"],
                    "as_of": item["as_of"],
                    "source_schema_version": item["source_schema_version"],
                    "payload_top_level_fields": (
                        sorted(str(key) for key in item["payload"])
                        if isinstance(item["payload"], Mapping)
                        else []
                    ),
                }
                for item in evidence
            ],
            "historical_reviewed_memory": list(memory_inputs),
            "prior_artifacts": list(prior_artifacts),
            "analysis_requirements": {
                "current_claims_need_exact_evidence_reference_ids": True,
                "each_finding_and_counterpoint_needs_current_evidence": True,
                "compare_memory_assumptions_with_current_evidence": True,
                "surface_contradictions_and_unexplained_residuals": True,
                "state_missing_or_stale_dimensions_without_guessing": True,
                "follow_up_checks_must_be_deterministic_and_read_only": True,
                "use_only_exact_output_field_names": True,
                "do_not_expand_symbols_into_unprovided_names": True,
                "do_not_apply_unprovided_thresholds_or_market_conventions": True,
                "inferences_must_be_explicit_and_state_missing_evidence": True,
                "do_not_propose_disabling_kill_switch_or_expanding_authority": True,
                "no_account_risk_or_execution_authority": True,
            },
            "output_contract": output_contract,
        }
        serialized_input = canonical_json(provider_input)
        if len(serialized_input.encode("utf-8")) > (
            EXTERNAL_MEMORY_MAX_PROVIDER_INPUT_BYTES
        ):
            raise ExternalMemoryAnalysisRejected(
                "selected memory and evidence exceed the reviewed external "
                "analysis input limit"
            )
        payload = {
            "model": self._settings.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": build_system_instructions(
                        stage_id=request.stage_id,
                        output_contract=output_contract,
                    ),
                },
                {"role": "user", "content": serialized_input},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": EXTERNAL_MEMORY_MAX_OUTPUT_TOKENS,
            "stream": False,
        }
        payload.update(external_edge_request_options(self._settings))
        request_payload_fingerprint = content_fingerprint(payload)
        started_at = self._now()
        if not self._analysis_store.start_model_call(
            workflow_id=request.workflow_id,
            stage_id=request.stage_id,
            provider_id=self._provider_id,
            model_id=self._model_id,
            request_payload_fingerprint=request_payload_fingerprint,
            started_at=started_at,
        ):
            raise ExternalMemoryModelCallAlreadyAttemptedError(
                "external_model_call_already_attempted"
            )
        started = self._monotonic()
        response_fingerprint: str | None = None
        response_model: str | None = None
        http_status: int | None = None
        finish_reason: str | None = None
        reasoning_content: str | None = None
        usage: dict[str, int] = {}
        try:
            try:
                response = self._transport.post_json(
                    url=self._settings.endpoint_url,
                    headers={
                        "Authorization": f"Bearer {self._settings.api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Karkinos-Evidence-Memory-Research/1",
                    },
                    payload=payload,
                    timeout_seconds=self._timeout_seconds,
                )
            except ProviderProbeError as exc:
                if exc.code == "provider_timeout":
                    raise ExternalMemoryTimeoutError("provider_timeout") from exc
                raise ExternalMemoryNetworkError("provider_network_error") from exc
            http_status = response.status_code
            response_fingerprint = content_fingerprint(response.payload)
            if response.status_code in {401, 403}:
                raise ExternalMemoryAuthenticationError(
                    "provider_authentication_failed"
                )
            if response.status_code == 429:
                raise ExternalMemoryRateLimitedError("provider_rate_limited")
            if response.status_code < 200 or response.status_code >= 300:
                raise ExternalMemoryHttpError("provider_http_error")
            body = response.payload
            if not isinstance(body, dict):
                raise ExternalMemoryInvalidResponseError("provider_invalid_json")
            response_model = str(body.get("model") or self._settings.model_name)
            usage = safe_usage(body.get("usage"))
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ExternalMemoryInvalidResponseError("provider_choices_missing")
            first = choices[0]
            if not isinstance(first, dict):
                raise ExternalMemoryInvalidResponseError("provider_choice_is_invalid")
            finish_reason = (
                str(first.get("finish_reason"))
                if first.get("finish_reason") is not None
                else None
            )
            if finish_reason == "length":
                raise ExternalMemoryInvalidResponseError(
                    "provider_response_was_truncated"
                )
            message = first.get("message")
            if not isinstance(message, dict):
                raise ExternalMemoryInvalidResponseError("provider_message_missing")
            raw_reasoning = message.get("reasoning_content")
            reasoning_content = (
                raw_reasoning if isinstance(raw_reasoning, str) else None
            )
            content = message_text(message.get("content"))
            if content is None or not content.strip():
                code = (
                    "provider_final_content_missing_after_reasoning"
                    if reasoning_content
                    else "provider_content_missing"
                )
                raise ExternalMemoryInvalidResponseError(code)
            normalized = decode_stage_output(
                content,
                allowed_reference_ids=allowed_reference_ids,
                allowed_memory_ids=tuple(
                    item["memory_artifact_id"] for item in memory_inputs
                ),
            )
            latency_ms = max(0, round((self._monotonic() - started) * 1000))
            normalized.update(
                {
                    "schema_version": "karkinos.ai.external_memory_stage_artifact.v1",
                    "stage_id": request.stage_id,
                    "research_question": self._request.research_question,
                    "retrieval_id": self._inputs.retrieval.stored.retrieval_id,
                    "retrieval_target_fingerprint": (
                        self._inputs.retrieval.current_target.fingerprint
                    ),
                    "current_context_snapshot_id": self._inputs.context.snapshot_id,
                    "current_context_fingerprint": self._inputs.context.fingerprint,
                    "memory_input_is_current_fact": False,
                    "current_evidence_must_be_read": True,
                    "current_evidence_reference_ids": list(allowed_reference_ids),
                    "historical_memory_artifact_ids": [
                        item["memory_artifact_id"] for item in memory_inputs
                    ],
                    "provider_provenance": {
                        "provider_id": self._provider_id,
                        "configured_provider_source": self._settings.provider_id,
                        "model_id": self._model_id,
                        "response_model": response_model,
                        "prompt_version": EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
                        "request_payload_fingerprint": request_payload_fingerprint,
                        "response_fingerprint": response_fingerprint,
                        "http_status": response.status_code,
                        "latency_ms": latency_ms,
                        "timeout_seconds": self._timeout_seconds,
                        "usage": usage,
                        "finish_reason": finish_reason,
                        "reasoning_mode_requested": (
                            payload.get("thinking") == {"type": "enabled"}
                        ),
                        "reasoning_effort_requested": payload.get("reasoning_effort"),
                        "reasoning_content_present": bool(reasoning_content),
                        "reasoning_content_char_count": len(reasoning_content or ""),
                        "reasoning_content_persisted": False,
                    },
                    "persisted_facts_only": True,
                    "authoritative": False,
                    "research_output_is_account_fact": False,
                    "requires_human_review": True,
                    "decision_input_created": False,
                    "trade_plan_created": False,
                    "memory_created": False,
                    "authority_effect": "none",
                }
            )
            self._analysis_store.finish_model_call(
                workflow_id=request.workflow_id,
                stage_id=request.stage_id,
                status="completed",
                response_fingerprint=response_fingerprint,
                response_model=response_model,
                http_status=response.status_code,
                usage=usage,
                finish_reason=finish_reason,
                reasoning_content_present=bool(reasoning_content),
                reasoning_content_char_count=len(reasoning_content or ""),
                error_code=None,
                finished_at=self._now(),
            )
            return ProviderResponse(
                artifacts=(
                    ArtifactDraft(
                        kind=external_memory_stage_artifact_kind(request.stage_id),
                        content=normalized,
                        evidence_reference_ids=allowed_reference_ids,
                    ),
                ),
                message="External evidence-bound stage completed without authority.",
            )
        except Exception as exc:
            error_code = safe_external_error_code(exc)
            try:
                self._analysis_store.finish_model_call(
                    workflow_id=request.workflow_id,
                    stage_id=request.stage_id,
                    status="failed",
                    response_fingerprint=response_fingerprint,
                    response_model=response_model,
                    http_status=http_status,
                    usage=usage,
                    finish_reason=finish_reason,
                    reasoning_content_present=bool(reasoning_content),
                    reasoning_content_char_count=len(reasoning_content or ""),
                    error_code=error_code,
                    finished_at=self._now(),
                )
            except Exception:
                # Preserve the original sanitized provider/schema failure. A
                # non-terminal audit row remains visibly unreplayable.
                pass
            raise
