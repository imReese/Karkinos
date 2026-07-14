"""Human-started, evidence-bound external research reports.

This boundary sends one immutable saved-backtest evidence payload to one
explicitly configured OpenAI-compatible model.  It cannot read account
holdings, request provider-side tools, create trade plans, or change any
financial or execution authority.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capture import (
    CAPTURE_CONFIRMATION,
    CaptureEvidenceType,
    HumanContextCaptureRequest,
    HumanResearchContextCaptureService,
)
from .contracts import (
    AgentRole,
    ArtifactDraft,
    ArtifactKind,
    JsonObject,
    ModelRegistration,
    ProviderRegistration,
    ResearchWorkflow,
    StageDefinition,
    StoredArtifact,
    ToolRequest,
    WorkflowDefinition,
    WorkflowStatus,
    canonical_json,
    content_fingerprint,
)
from .evidence import CanonicalEvidenceRepository, CanonicalEvidenceToolExecutors
from .orchestrator import DeterministicWorkflowOrchestrator
from .permissions import default_tool_permission_registry
from .provider import ProviderAdapter, ProviderRequest, ProviderResponse
from .provider_connectivity import (
    JsonHttpTransport,
    ProviderConnectivitySettings,
    ProviderProbeError,
    UrllibJsonTransport,
)
from .registry import AiRuntimeRegistry
from .store import AiAuditStore, AuditReplayResult, IdempotencyConflict

EXTERNAL_BACKTEST_REPORT_CONFIRMATION = (
    "send_selected_saved_backtest_evidence_to_configured_external_model_"
    "without_trade_authority"
)
EXTERNAL_BACKTEST_REPORT_CONTRACT = "karkinos.ai.external_backtest_report.v1"
EXTERNAL_BACKTEST_REPORT_PROMPT = "karkinos.ai.backtest_report_prompt.v2"
EXTERNAL_BACKTEST_REPORT_DEFINITION = "karkinos.external_backtest_report.v2"
EXTERNAL_BACKTEST_REPORT_ROLE = "external.backtest_evidence_analyst.v2"

_REPORT_STAGE_ID = "external_backtest_report"
_RESEARCH_TOOL = "research_evidence.read"
_TERMINAL = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.PARTIAL,
    WorkflowStatus.FAILED,
    WorkflowStatus.BLOCKED,
}


class ExternalBacktestReportRejected(ValueError):
    """Raised before network I/O when evidence or intent is not admissible."""


class ExternalResearchAuthenticationError(RuntimeError):
    pass


class ExternalResearchRateLimitedError(RuntimeError):
    pass


class ExternalResearchHttpError(RuntimeError):
    pass


class ExternalResearchTimeoutError(RuntimeError):
    pass


class ExternalResearchNetworkError(RuntimeError):
    pass


class ExternalResearchInvalidResponseError(RuntimeError):
    pass


@dataclass(frozen=True)
class HumanExternalBacktestReportRequest:
    idempotency_key: str
    requested_by: str
    research_question: str
    account_alias: str
    backtest_result_id: int
    confirmation: str
    schema_version: str = "karkinos.ai.human_external_backtest_report_request.v2"

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "requested_by",
            "research_question",
            "account_alias",
            "schema_version",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.backtest_result_id <= 0:
            raise ValueError("backtest_result_id must be positive")
        if self.confirmation != EXTERNAL_BACKTEST_REPORT_CONFIRMATION:
            raise PermissionError(
                "external backtest analysis requires exact human confirmation"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "requested_by": self.requested_by,
            "research_question": self.research_question,
            "account_alias": self.account_alias,
            "backtest_result_id": self.backtest_result_id,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalBacktestReportRecord:
    analysis_id: str
    idempotency_key: str
    request_fingerprint: str
    requested_by: str
    backtest_result_id: int
    capture_id: str
    workflow_id: str
    context_snapshot_id: str
    context_fingerprint: str
    evidence_reference_id: str
    provider_id: str
    model_id: str
    prompt_version: str
    created_at: str


@dataclass(frozen=True)
class ExternalBacktestReportResult:
    record: ExternalBacktestReportRecord
    workflow: ResearchWorkflow
    report: StoredArtifact | None
    tool_calls: tuple[JsonObject, ...]
    audit_replay: AuditReplayResult
    binding_validity: str
    binding_errors: tuple[str, ...]
    external_model_stage_run_count: int
    reused: bool

    def to_dict(self) -> JsonObject:
        report_payload = None
        if self.report is not None:
            report_payload = {
                "artifact_id": self.report.artifact_id,
                "kind": self.report.kind.value,
                "content": dict(self.report.content),
                "evidence_reference_ids": list(self.report.evidence_reference_ids),
                "fingerprint": self.report.fingerprint,
                "created_at": self.report.created_at,
            }
        return {
            "schema_version": EXTERNAL_BACKTEST_REPORT_CONTRACT,
            "analysis_id": self.record.analysis_id,
            "workflow_id": self.record.workflow_id,
            "workflow_status": self.workflow.status.value,
            "workflow_failure_code": self.workflow.failure_code,
            "backtest_result_id": self.record.backtest_result_id,
            "capture_id": self.record.capture_id,
            "context_snapshot_id": self.record.context_snapshot_id,
            "context_fingerprint": self.record.context_fingerprint,
            "evidence_reference_id": self.record.evidence_reference_id,
            "binding_validity": self.binding_validity,
            "binding_errors": list(self.binding_errors),
            "report": report_payload,
            "tool_calls": [dict(item) for item in self.tool_calls],
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "provider_id": self.record.provider_id,
            "model_id": self.record.model_id,
            "prompt_version": self.record.prompt_version,
            "requested_by": self.record.requested_by,
            "created_at": self.record.created_at,
            "reused": self.reused,
            "external_model_used": self.external_model_stage_run_count > 0,
            "external_model_stage_run_count": self.external_model_stage_run_count,
            "external_context_scope": "saved_backtest_research_evidence_only",
            "account_holdings_sent": False,
            "market_or_broker_provider_fetch_used": False,
            "provider_side_tools_enabled": False,
            "research_output_is_account_fact": False,
            "decision_input_created": False,
            "trade_plan_created": False,
            "memory_created": False,
            "authority_effect": "none",
            "oms_write_count": 0,
            "ledger_write_count": 0,
            "risk_decision_write_count": 0,
            "capital_authority_write_count": 0,
            "broker_action_count": 0,
        }


_EXTERNAL_REPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_backtest_report_requests (
    analysis_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    backtest_result_id INTEGER NOT NULL CHECK(backtest_result_id > 0),
    capture_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL UNIQUE,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    evidence_reference_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    run_claimed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_backtest_reports_result
ON ai_external_backtest_report_requests(backtest_result_id, created_at DESC);
"""


class ExternalBacktestReportAuditStore:
    """Human request to evidence-bound workflow mapping; secrets are excluded."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(_EXTERNAL_REPORT_SCHEMA)

    def create_or_get(
        self,
        request: HumanExternalBacktestReportRequest,
        *,
        capture_id: str,
        workflow_id: str,
        context_snapshot_id: str,
        context_fingerprint: str,
        evidence_reference_id: str,
        provider_id: str,
        model_id: str,
        created_at: str,
    ) -> tuple[ExternalBacktestReportRecord, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "workflow_id": workflow_id,
            "evidence_reference_id": evidence_reference_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "prompt_version": EXTERNAL_BACKTEST_REPORT_PROMPT,
        }
        analysis_id = f"ai-external-report-{content_fingerprint(identity)[:24]}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_external_backtest_report_requests "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["request_fingerprint"]) != request.fingerprint
                    or str(existing["workflow_id"]) != workflow_id
                    or str(existing["evidence_reference_id"]) != evidence_reference_id
                ):
                    raise IdempotencyConflict(
                        "external report idempotency key was reused with different input"
                    )
                return _record_from_row(existing), True
            conn.execute(
                """
                INSERT INTO ai_external_backtest_report_requests (
                    analysis_id, idempotency_key, request_json,
                    request_fingerprint, requested_by, backtest_result_id,
                    capture_id, workflow_id, context_snapshot_id,
                    context_fingerprint, evidence_reference_id, provider_id,
                    model_id, prompt_version, run_claimed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    analysis_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    request.requested_by,
                    request.backtest_result_id,
                    capture_id,
                    workflow_id,
                    context_snapshot_id,
                    context_fingerprint,
                    evidence_reference_id,
                    provider_id,
                    model_id,
                    EXTERNAL_BACKTEST_REPORT_PROMPT,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_external_backtest_report_requests "
                "WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("external report audit mapping persistence failed")
        return _record_from_row(row), False

    def claim_run(self, analysis_id: str, *, claimed_at: str) -> bool:
        """Atomically let one exact request cross the billable model boundary."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ai_external_backtest_report_requests
                SET run_claimed_at = ?
                WHERE analysis_id = ? AND run_claimed_at IS NULL
                """,
                (claimed_at, analysis_id),
            )
        return cursor.rowcount == 1


class OpenAICompatibleBacktestReportProvider(ProviderAdapter):
    """One purpose-built provider turn over one authorized evidence record."""

    def __init__(
        self,
        *,
        provider_id: str,
        settings: ProviderConnectivitySettings,
        evidence_reference_id: str,
        research_question: str,
        context_binding: JsonObject,
        transport: JsonHttpTransport,
        monotonic: Callable[[], float],
        timeout_seconds: float,
    ) -> None:
        self._provider_id = provider_id
        self._settings = settings
        self._evidence_reference_id = evidence_reference_id
        self._research_question = research_question
        self._context_binding = dict(context_binding)
        self._transport = transport
        self._monotonic = monotonic
        self._timeout_seconds = timeout_seconds

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if request.turn_index == 0:
            if request.tool_results:
                raise ExternalResearchInvalidResponseError(
                    "unexpected_initial_tool_results"
                )
            return ProviderResponse(
                tool_requests=(
                    ToolRequest(
                        request_id="read-bound-backtest-evidence",
                        tool_name=_RESEARCH_TOOL,
                        arguments={
                            "evidence_reference_id": self._evidence_reference_id
                        },
                    ),
                ),
                message="Read the exact persisted research evidence before analysis.",
            )
        if request.turn_index != 1 or len(request.tool_results) != 1:
            raise ExternalResearchInvalidResponseError("unexpected_provider_turn")
        tool_result = request.tool_results[0]
        if tool_result.tool_name != _RESEARCH_TOOL:
            raise ExternalResearchInvalidResponseError("unexpected_evidence_tool")
        evidence = dict(tool_result.output)
        if evidence.get("evidence_reference_id") != self._evidence_reference_id:
            raise ExternalResearchInvalidResponseError("evidence_reference_mismatch")
        if evidence.get("persisted_facts_only") is not True:
            raise ExternalResearchInvalidResponseError("evidence_not_persisted")
        if evidence.get("authoritative") is not True:
            raise ExternalResearchInvalidResponseError("evidence_not_authoritative")
        if evidence.get("kind") != "research_evidence_bundle":
            raise ExternalResearchInvalidResponseError("evidence_kind_mismatch")
        evidence_payload = evidence.get("payload")
        if not isinstance(evidence_payload, dict):
            raise ExternalResearchInvalidResponseError("evidence_payload_missing")
        if evidence_payload.get("analysis_ready") is not True:
            raise ExternalResearchInvalidResponseError("evidence_not_analysis_ready")
        return self._invoke_external_model(dict(evidence_payload))

    def _invoke_external_model(self, evidence_payload: JsonObject) -> ProviderResponse:
        provider_input = {
            "research_question": self._research_question,
            "evidence_reference_id": self._evidence_reference_id,
            "saved_backtest_evidence": evidence_payload,
            "required_output_schema": {
                "title": "string",
                "executive_summary": "string",
                "claims": [
                    {
                        "claim": "string",
                        "confidence": "low|medium|high",
                        "evidence": "string",
                    }
                ],
                "counterarguments": [{"risk": "string", "evidence": "string"}],
                "limitations": ["string"],
                "conclusion": "string",
                "follow_up_checks": ["string"],
            },
        }
        serialized_input = canonical_json(provider_input)
        if len(serialized_input.encode("utf-8")) > 131_072:
            raise ExternalBacktestReportRejected(
                "saved backtest evidence exceeds the reviewed model input limit"
            )
        payload = {
            "model": self._settings.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a cautious quantitative-research reviewer. Analyze "
                        "only the supplied persisted saved-backtest evidence. Return "
                        "one JSON object matching the requested schema, in Chinese. "
                        "Do not invent market facts, prices, holdings, or missing "
                        "tests. Do not give buy/sell instructions, position sizing, "
                        "capital authorization, execution steps, or investment advice. "
                        "Treat the result as a non-authoritative research artifact."
                    ),
                },
                {"role": "user", "content": serialized_input},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 1800,
            "temperature": 0,
            "stream": False,
        }
        started = self._monotonic()
        try:
            response = self._transport.post_json(
                url=self._settings.endpoint_url,
                headers={
                    "Authorization": f"Bearer {self._settings.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Karkinos-Evidence-Research/1",
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
        if not isinstance(choices, list) or not choices:
            raise ExternalResearchInvalidResponseError("provider_choices_missing")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ExternalResearchInvalidResponseError("provider_content_missing")
        report = _decode_external_report(content, self._evidence_reference_id)
        report.update(
            {
                "schema_version": EXTERNAL_BACKTEST_REPORT_CONTRACT,
                "research_question": self._research_question,
                "evidence_binding": dict(self._context_binding),
                "provider_provenance": {
                    "provider_id": self._provider_id,
                    "configured_provider_source": self._settings.provider_id,
                    "model_id": self._settings.model_id,
                    "response_model": str(
                        body.get("model") or self._settings.model_name
                    ),
                    "prompt_version": EXTERNAL_BACKTEST_REPORT_PROMPT,
                    "request_payload_fingerprint": content_fingerprint(payload),
                    "response_fingerprint": content_fingerprint(body),
                    "http_status": response.status_code,
                    "latency_ms": latency_ms,
                    "timeout_seconds": self._timeout_seconds,
                    "usage": _safe_usage(body.get("usage")),
                },
                "persisted_facts_only": True,
                "authoritative": False,
                "research_output_is_account_fact": False,
                "decision_input_created": False,
                "trade_plan_created": False,
                "memory_created": False,
                "requires_human_review": True,
                "authority_effect": "none",
            }
        )
        return ProviderResponse(
            artifacts=(
                ArtifactDraft(
                    kind=ArtifactKind.REPORT,
                    content=report,
                    evidence_reference_ids=(self._evidence_reference_id,),
                ),
            ),
            message="External evidence-bound report completed without authority.",
        )


class HumanExternalBacktestReportService:
    """Capture, authorize, run, and audit one explicit external report."""

    def __init__(
        self,
        *,
        settings: ProviderConnectivitySettings,
        capture_service: HumanResearchContextCaptureService,
        evidence_repository: CanonicalEvidenceRepository,
        ai_store: AiAuditStore,
        report_store: ExternalBacktestReportAuditStore,
        transport: JsonHttpTransport | None = None,
        now: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        model_timeout_seconds: float = 45.0,
    ) -> None:
        self._settings = settings
        self._capture_service = capture_service
        self._evidence_repository = evidence_repository
        self._ai_store = ai_store
        self._report_store = report_store
        self._transport = transport or UrllibJsonTransport()
        self._now = now or _utc_now
        self._monotonic = monotonic or time.monotonic
        if model_timeout_seconds <= 0 or model_timeout_seconds > 60:
            raise ValueError("model_timeout_seconds must be within (0, 60]")
        self._model_timeout_seconds = model_timeout_seconds

    async def run(
        self,
        request: HumanExternalBacktestReportRequest,
    ) -> ExternalBacktestReportResult:
        capture = await self._capture_service.capture(
            HumanContextCaptureRequest(
                idempotency_key=f"external-report:{request.idempotency_key}",
                requested_by=request.requested_by,
                research_question=request.research_question,
                account_alias=request.account_alias,
                evidence_types=(CaptureEvidenceType.RESEARCH_EVIDENCE,),
                confirmation=CAPTURE_CONFIRMATION,
                backtest_result_id=request.backtest_result_id,
            )
        )
        if len(capture.records) != 1:
            raise ExternalBacktestReportRejected(
                "external report requires exactly one research evidence record"
            )
        evidence = capture.records[0]
        if evidence.tool_name != _RESEARCH_TOOL:
            raise ExternalBacktestReportRejected(
                "external report received an unexpected evidence type"
            )
        if not evidence.authoritative:
            raise ExternalBacktestReportRejected(
                f"external report requires complete evidence; status={evidence.status}"
            )
        if evidence.payload.get("analysis_ready") is not True:
            blockers = evidence.payload.get("analysis_blocking_reasons")
            raise ExternalBacktestReportRejected(
                "saved backtest is not ready for external analysis: "
                + canonical_json(blockers if isinstance(blockers, list) else [])
            )

        runtime_provider_id, runtime_model_id = self._runtime_ids()
        registry = AiRuntimeRegistry(self._ai_store)
        self._register_runtime(
            registry,
            provider_id=runtime_provider_id,
            model_id=runtime_model_id,
        )
        context_binding = {
            "context_snapshot_id": capture.context.snapshot_id,
            "context_fingerprint": capture.context.fingerprint,
            "valuation_snapshot_id": capture.context.valuation_snapshot_id,
            "ledger_cutoff_id": capture.context.ledger_cutoff_id,
            "ledger_fingerprint": capture.context.ledger_fingerprint,
            "evidence_reference_id": evidence.reference_id,
            "evidence_record_fingerprint": evidence.record_fingerprint,
        }
        provider = OpenAICompatibleBacktestReportProvider(
            provider_id=runtime_provider_id,
            settings=self._settings,
            evidence_reference_id=evidence.reference_id,
            research_question=request.research_question,
            context_binding=context_binding,
            transport=self._transport,
            monotonic=self._monotonic,
            timeout_seconds=self._model_timeout_seconds,
        )
        orchestrator = DeterministicWorkflowOrchestrator(
            store=self._ai_store,
            registry=registry,
            permissions=default_tool_permission_registry(),
            providers={runtime_provider_id: provider},
            tool_executors=CanonicalEvidenceToolExecutors(
                self._evidence_repository
            ).as_mapping(),
            now=self._now,
            max_provider_turns=2,
        )
        workflow = orchestrator.create_workflow(
            definition=_workflow_definition(runtime_model_id),
            context=capture.context,
            idempotency_key=f"external-report:{request.idempotency_key}",
        )
        record, reused = self._report_store.create_or_get(
            request,
            capture_id=capture.run.capture_id,
            workflow_id=workflow.workflow_id,
            context_snapshot_id=capture.context.snapshot_id,
            context_fingerprint=capture.context.fingerprint,
            evidence_reference_id=evidence.reference_id,
            provider_id=runtime_provider_id,
            model_id=runtime_model_id,
            created_at=self._now(),
        )
        claimed = self._report_store.claim_run(
            record.analysis_id,
            claimed_at=self._now(),
        )
        if claimed and workflow.status not in _TERMINAL:
            workflow = await asyncio.to_thread(
                orchestrator.run,
                workflow.workflow_id,
                current_context=capture.context,
            )
        elif not claimed:
            workflow = self._ai_store.get_workflow(workflow.workflow_id)
        return self._result(record, workflow=workflow, reused=reused)

    def _runtime_ids(self) -> tuple[str, str]:
        provider_id = f"karkinos.external_research.{self._settings.provider_id}.v1"
        model_id = f"{provider_id}:{self._settings.model_name}"
        return provider_id, model_id

    def _register_runtime(
        self,
        registry: AiRuntimeRegistry,
        *,
        provider_id: str,
        model_id: str,
    ) -> None:
        registry.register_provider(
            ProviderRegistration(
                provider_id=provider_id,
                display_name=(
                    f"{self._settings.provider_id} evidence-bound research edge"
                ),
                adapter_kind=self._settings.adapter_kind,
                enabled=True,
                capabilities=(
                    "saved_backtest_evidence_report",
                    "provider_side_tools_disabled",
                ),
            )
        )
        registry.register_model(
            ModelRegistration(
                model_id=model_id,
                provider_id=provider_id,
                model_name=self._settings.model_name,
                enabled=True,
                purposes=("human_started_backtest_evidence_review",),
            )
        )
        registry.register_role(
            AgentRole(
                role_id=EXTERNAL_BACKTEST_REPORT_ROLE,
                display_name="External backtest evidence analyst",
                purpose=(
                    "Analyze one exact saved-backtest evidence record without "
                    "investment, account, risk, capital, or execution authority."
                ),
                allowed_tools=(_RESEARCH_TOOL,),
                allowed_artifact_kinds=(ArtifactKind.REPORT,),
                instructions_version=EXTERNAL_BACKTEST_REPORT_PROMPT,
            )
        )

    def _result(
        self,
        record: ExternalBacktestReportRecord,
        *,
        workflow: ResearchWorkflow,
        reused: bool,
    ) -> ExternalBacktestReportResult:
        artifacts = self._ai_store.list_artifacts(workflow.workflow_id)
        report = next(
            (item for item in artifacts if item.kind == ArtifactKind.REPORT),
            None,
        )
        binding_validity, binding_errors = self._binding_validity(record)
        tool_calls = tuple(
            {
                "call_id": item.call_id,
                "run_id": item.run_id,
                "stage_id": item.stage_id,
                "role_id": item.role_id,
                "tool_name": item.tool_name,
                "status": item.status.value,
                "evidence_reference_id": item.arguments.get("evidence_reference_id"),
                "denial_reason": item.denial_reason,
            }
            for item in self._ai_store.list_tool_calls(workflow.workflow_id)
        )
        return ExternalBacktestReportResult(
            record=record,
            workflow=workflow,
            report=report,
            tool_calls=tool_calls,
            audit_replay=self._ai_store.verify_replay(workflow.workflow_id),
            binding_validity=binding_validity,
            binding_errors=binding_errors,
            external_model_stage_run_count=len(
                self._ai_store.list_agent_runs(workflow.workflow_id)
            ),
            reused=reused,
        )

    def _binding_validity(
        self,
        record: ExternalBacktestReportRecord,
    ) -> tuple[str, tuple[str, ...]]:
        errors: list[str] = []
        try:
            context = self._ai_store.get_context(record.context_snapshot_id)
        except LookupError:
            return "invalid", ("context_snapshot_missing",)
        if context.fingerprint != record.context_fingerprint:
            errors.append("context_fingerprint_mismatch")
        evidence = self._evidence_repository.get(record.evidence_reference_id)
        if evidence is None:
            errors.append("evidence_record_missing")
        else:
            reference = next(
                (
                    item
                    for item in context.evidence_references
                    if item.reference_id == record.evidence_reference_id
                ),
                None,
            )
            if reference is None or reference != evidence.to_reference():
                errors.append("evidence_context_binding_mismatch")
        return ("valid", ()) if not errors else ("invalid", tuple(errors))


def _workflow_definition(model_id: str) -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id=EXTERNAL_BACKTEST_REPORT_DEFINITION,
        name="Human-started external review of one saved backtest evidence record",
        stages=(
            StageDefinition(
                stage_id=_REPORT_STAGE_ID,
                role_id=EXTERNAL_BACKTEST_REPORT_ROLE,
                model_id=model_id,
                output_kind=ArtifactKind.REPORT,
            ),
        ),
    )


def _decode_external_report(
    content: str,
    evidence_reference_id: str,
) -> JsonObject:
    candidate = content.strip()
    if len(candidate) > 131_072:
        raise ExternalResearchInvalidResponseError("provider_report_is_too_large")
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            lines = lines[1:-1]
            if lines and lines[0].strip().lower() == "json":
                lines = lines[1:]
            candidate = "\n".join(lines).strip()
    payload = _first_json_object(candidate)
    if not isinstance(payload, dict):
        raise ExternalResearchInvalidResponseError("provider_report_is_not_an_object")
    claims = _report_items(
        payload,
        primary_key="claim",
        keys=("claims", "supported_findings", "findings", "evidence_review"),
        minimum=1,
        maximum=8,
    )
    counterarguments = _report_items(
        payload,
        primary_key="risk",
        keys=(
            "counterarguments",
            "risks",
            "counterarguments_and_risks",
            "unsupported_findings",
        ),
        minimum=1,
        maximum=8,
    )
    normalized_claims = []
    for item in claims:
        confidence_value = item.get("confidence")
        confidence = (
            confidence_value.strip().lower()
            if isinstance(confidence_value, str)
            else "unspecified"
        )
        if confidence not in {"low", "medium", "high"}:
            confidence = "unspecified"
        claim = _text(item, "claim", maximum=2_000)
        normalized_claims.append(
            {
                "claim": claim,
                "confidence": confidence,
                "evidence": _optional_text(item, "evidence", maximum=2_000) or claim,
                "evidence_reference_ids": [evidence_reference_id],
            }
        )
    normalized_counterarguments = []
    for item in counterarguments:
        risk = _text(item, "risk", maximum=2_000)
        normalized_counterarguments.append(
            {
                "risk": risk,
                "evidence": _optional_text(item, "evidence", maximum=2_000) or risk,
                "evidence_reference_ids": [evidence_reference_id],
            }
        )
    return {
        "title": _text(payload, "title", maximum=500),
        "executive_summary": _text(
            payload,
            "executive_summary",
            maximum=4_000,
        ),
        "claims": normalized_claims,
        "counterarguments": normalized_counterarguments,
        "limitations": _text_list(payload, "limitations", minimum=1, maximum=12),
        "conclusion": _text(payload, "conclusion", maximum=4_000),
        "follow_up_checks": _text_list(
            payload,
            "follow_up_checks",
            minimum=1,
            maximum=12,
        ),
    }


def _first_json_object(candidate: str) -> object:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, character in enumerate(candidate):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ExternalResearchInvalidResponseError("provider_report_is_not_json")


def _text(payload: dict[str, Any], key: str, *, maximum: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExternalResearchInvalidResponseError(f"provider_report_{key}_is_missing")
    result = value.strip()
    if len(result) > maximum:
        raise ExternalResearchInvalidResponseError(f"provider_report_{key}_is_too_long")
    return result


def _report_items(
    payload: dict[str, Any],
    *,
    primary_key: str,
    keys: tuple[str, ...],
    minimum: int,
    maximum: int,
) -> list[dict[str, Any]]:
    selected_key = next((key for key in keys if payload.get(key) is not None), keys[0])
    value = payload.get(selected_key)
    items: list[dict[str, Any]] = []
    if isinstance(value, str):
        items.append({primary_key: value})
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                items.append({primary_key: item})
            elif isinstance(item, dict):
                items.append(dict(item))
            else:
                items = []
                break
    elif isinstance(value, dict):
        if isinstance(value.get(primary_key), str):
            items.append(dict(value))
        else:
            for label, item in value.items():
                if isinstance(item, str):
                    items.append({primary_key: f"{label}: {item}"})
                elif isinstance(item, list):
                    for entry in item:
                        if isinstance(entry, str):
                            items.append({primary_key: f"{label}: {entry}"})
    if len(items) < minimum or len(items) > maximum:
        raise ExternalResearchInvalidResponseError(
            f"provider_report_{selected_key}_is_invalid"
        )
    return items


def _optional_text(
    payload: dict[str, Any],
    key: str,
    *,
    maximum: int,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ExternalResearchInvalidResponseError(f"provider_report_{key}_is_invalid")
    return value.strip()


def _text_list(
    payload: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> list[str]:
    value = payload.get(key)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or len(value) < minimum or len(value) > maximum:
        raise ExternalResearchInvalidResponseError(f"provider_report_{key}_is_invalid")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 2_000:
            raise ExternalResearchInvalidResponseError(
                f"provider_report_{key}_is_invalid"
            )
        result.append(item.strip())
    return result


def _safe_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        raw = value.get(key)
        if isinstance(raw, int) and raw >= 0:
            result[key] = raw
    return result


def _record_from_row(row: sqlite3.Row) -> ExternalBacktestReportRecord:
    return ExternalBacktestReportRecord(
        analysis_id=str(row["analysis_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        requested_by=str(row["requested_by"]),
        backtest_result_id=int(row["backtest_result_id"]),
        capture_id=str(row["capture_id"]),
        workflow_id=str(row["workflow_id"]),
        context_snapshot_id=str(row["context_snapshot_id"]),
        context_fingerprint=str(row["context_fingerprint"]),
        evidence_reference_id=str(row["evidence_reference_id"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        prompt_version=str(row["prompt_version"]),
        created_at=str(row["created_at"]),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
