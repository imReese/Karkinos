"""Compatibility façade for human-gated AI strategy research.

Contracts, persistence, deterministic backtesting, model validation, and
application workflows have independent physical owners. This module preserves
the established import surface while the concrete boundaries stay testable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from data.store import DataStore
from server.ai_runtime.capture import (
    CAPTURE_CONFIRMATION,
    HumanResearchContextCaptureService,
)
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
)
from server.ai_runtime.provider_connectivity_contracts import (
    JsonHttpTransport,
    ProviderConnectivitySettings,
)
from server.ai_runtime.provider_connectivity_transport import (
    HttpxDeadlineJsonTransport,
)
from server.ai_runtime.store import AiAuditStore
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
    rolling_oos_parameters,
    validate_persisted_fee_schedule_binding,
    validated_fee_schedule_resolution,
)
from server.ai_runtime.strategy_research_backtest_workflow import (
    StrategyResearchBacktestWorkflowMixin,
)
from server.ai_runtime.strategy_research_citations import (
    build_critique_citation_catalog,
    build_hypothesis_citation_catalog,
    citation_path_exists,
    compact_hypothesis_citation_catalog,
    resolve_hypothesis_citations,
)
from server.ai_runtime.strategy_research_critique import StrategyResearchCritiqueMixin
from server.ai_runtime.strategy_research_generation import (
    StrategyResearchGenerationMixin,
)
from server.ai_runtime.strategy_research_model_contract import (
    bind_and_validate_drafts,
    critique_output_contract,
    hypothesis_output_contract,
    normalize_critique_payload,
    normalize_hypothesis_payload,
    strategy_research_system_prompt,
)
from server.ai_runtime.strategy_research_provider import StrategyResearchModelProvider
from server.ai_runtime.strategy_research_sealed import StrategyResearchSealedMixin
from server.ai_runtime.strategy_research_session import StrategyResearchSessionMixin
from server.ai_runtime.strategy_research_support import (
    critique_response,
    decode_model_json,
    report_artifact,
    safe_provider_usage,
    selection_from_session,
    strategy_research_failure_code,
    strategy_research_json_object,
    strategy_research_request_json,
    strategy_research_utc_now,
)
from server.ai_runtime.strategy_research_values import (
    ACCOUNT_STATE_TOOL,
    CATALOG_TOOL,
    CRITIQUE_CITATION_PATHS,
    CRITIQUE_ROLE,
    CRITIQUE_STAGE,
    HYPOTHESIS_ROLE,
    HYPOTHESIS_STAGE,
    RESEARCH_TOOL,
    SANITIZED_ACCOUNT_EVIDENCE_CONTRACT,
    SELECTION_TOOL,
    STRATEGY_RESEARCH_PROMPT_VERSION,
    TERMINAL_WORKFLOW_STATUSES,
    strategy_research_request_options,
)
from server.composition.strategy_research import (
    build_strategy_research_orchestrator,
    register_strategy_research_runtime,
    strategy_research_runtime_ids,
    strategy_research_workflow_definition,
)
from server.contracts.strategy_research import (
    BACKTEST_CONFIRMATION,
    CRITIQUE_EXPORT_CONFIRMATION,
    HYPOTHESIS_EXPORT_CONFIRMATION,
    REVIEW_CONFIRMATION,
    SEALED_TEST_CONFIRMATION,
    STRATEGY_BACKTEST_CRITIQUE_CONTRACT,
    STRATEGY_HYPOTHESIS_DRAFT_CONTRACT,
    STRATEGY_RESEARCH_API_CONTRACT,
    STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT,
    STRATEGY_RESEARCH_MAX_CANDIDATES,
    STRATEGY_RESEARCH_MAX_CITATION_CATALOG_BYTES,
    STRATEGY_RESEARCH_MAX_CITATION_PATHS,
    STRATEGY_RESEARCH_MAX_INPUT_BYTES,
    STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS,
    STRATEGY_RESEARCH_MAX_PROVIDER_CALLS,
    STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION,
    STRATEGY_RESEARCH_SELECTION_CONTRACT,
    CritiqueRequest,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
    SealedTestRequest,
    StrategyResearchRejected,
    StrategyResearchSelection,
    reject_private_iteration_keys,
    validate_iteration_context,
)
from server.persistence.strategy_research import StrategyResearchAuditStore


class StrategyResearchService(
    StrategyResearchGenerationMixin,
    StrategyResearchBacktestWorkflowMixin,
    StrategyResearchCritiqueMixin,
    StrategyResearchSealedMixin,
    StrategyResearchSessionMixin,
):
    """Coordinate explicit hypothesis, backtest, critique, and review gates."""

    def __init__(
        self,
        *,
        db: Any,
        db_path: Path,
        settings: ProviderConnectivitySettings | None,
        capture_service: HumanResearchContextCaptureService,
        evidence_repository: CanonicalEvidenceRepository,
        ai_store: AiAuditStore,
        research_store: StrategyResearchAuditStore,
        data_store: DataStore,
        transport: JsonHttpTransport | None = None,
        now: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        model_timeout_seconds: float = 180.0,
        reviewed_fee_schedule_resolver: Callable[..., Any] | None = None,
    ) -> None:
        self._db = db
        self._db_path = db_path
        self._settings = settings
        self._capture_service = capture_service
        self._evidence_repository = evidence_repository
        self._ai_store = ai_store
        self._research_store = research_store
        self._data_store = data_store
        self._transport = transport or HttpxDeadlineJsonTransport()
        self._now = now or strategy_research_utc_now
        self._monotonic = monotonic or time.monotonic
        self._model_timeout_seconds = model_timeout_seconds
        self._reviewed_fee_schedule_resolver = reviewed_fee_schedule_resolver


# Compatibility aliases for existing direct tests and callers. Concrete
# modules import public names and do not depend on this façade.
_RESEARCH_TOOL = RESEARCH_TOOL
_ACCOUNT_STATE_TOOL = ACCOUNT_STATE_TOOL
_CATALOG_TOOL = CATALOG_TOOL
_SELECTION_TOOL = SELECTION_TOOL
_HYPOTHESIS_ROLE = HYPOTHESIS_ROLE
_CRITIQUE_ROLE = CRITIQUE_ROLE
_HYPOTHESIS_STAGE = HYPOTHESIS_STAGE
_CRITIQUE_STAGE = CRITIQUE_STAGE
_PROMPT_VERSION = STRATEGY_RESEARCH_PROMPT_VERSION
_SANITIZED_ACCOUNT_EVIDENCE_CONTRACT = SANITIZED_ACCOUNT_EVIDENCE_CONTRACT
_CRITIQUE_CITATION_PATHS = CRITIQUE_CITATION_PATHS
_TERMINAL = TERMINAL_WORKFLOW_STATUSES
_strategy_research_request_options = strategy_research_request_options
_validated_fee_schedule_resolution = validated_fee_schedule_resolution
_validate_persisted_fee_schedule_binding = validate_persisted_fee_schedule_binding
_rolling_oos_parameters = rolling_oos_parameters
_orchestrator = build_strategy_research_orchestrator
_runtime_ids = strategy_research_runtime_ids
_register_runtime = register_strategy_research_runtime
_workflow = strategy_research_workflow_definition
_bind_and_validate_drafts = bind_and_validate_drafts
_normalize_hypothesis_payload = normalize_hypothesis_payload
_normalize_critique_payload = normalize_critique_payload
_validate_iteration_context = validate_iteration_context
_reject_private_iteration_keys = reject_private_iteration_keys
_hypothesis_output_contract = hypothesis_output_contract
_critique_output_contract = critique_output_contract
_system_prompt = strategy_research_system_prompt
_report_artifact = report_artifact
_selection_from_session = selection_from_session
_request_json = strategy_research_request_json
_json_object = strategy_research_json_object
_critique_response = critique_response
_safe_usage = safe_provider_usage
_decode_model_json = decode_model_json
_build_hypothesis_citation_catalog = build_hypothesis_citation_catalog
_compact_hypothesis_citation_catalog = compact_hypothesis_citation_catalog
_build_critique_citation_catalog = build_critique_citation_catalog
_resolve_hypothesis_citations = resolve_hypothesis_citations
_citation_path_exists = citation_path_exists
_failure_code = strategy_research_failure_code
_utc_now = strategy_research_utc_now
