"""Composition root for AI application services used by HTTP and lifecycle code."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from server.ai_runtime.analysis_reviews import (
    AnalysisReviewRejected,
    AnalysisReviewStore,
    HumanAnalysisReviewService,
)
from server.ai_runtime.capture import (
    ContextCaptureAuditStore,
    HumanResearchContextCaptureService,
)
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.external_analysis_reviews import (
    ExternalAnalysisReviewRejected,
    ExternalAnalysisReviewStore,
    HumanExternalAnalysisReviewService,
)
from server.ai_runtime.external_memory_informed_analysis import (
    ExternalMemoryAnalysisStore,
    HumanExternalMemoryAnalysisService,
)
from server.ai_runtime.external_promoted_analysis_memory import (
    ExternalPromotedAnalysisMemoryPromotionService,
    ExternalPromotedAnalysisMemoryRejected,
    ExternalPromotedAnalysisMemoryStore,
)
from server.ai_runtime.external_promoted_analysis_memory_retrieval import (
    ExternalPromotedAnalysisMemoryRetrievalRejected,
    ExternalPromotedAnalysisMemoryRetrievalStore,
    HumanExternalPromotedAnalysisMemoryRetrievalService,
)
from server.ai_runtime.external_promoted_memory_analysis import (
    ExternalPromotedMemoryAnalysisStore,
    HumanExternalPromotedMemoryAnalysisService,
)
from server.ai_runtime.external_promoted_memory_analysis_reviews import (
    ExternalPromotedMemoryAnalysisReviewRejected,
    ExternalPromotedMemoryAnalysisReviewStore,
    HumanExternalPromotedMemoryAnalysisReviewService,
)
from server.ai_runtime.external_research import (
    ExternalBacktestReportAuditStore,
    HumanExternalBacktestReportService,
)
from server.ai_runtime.external_reviewed_memory import (
    ExternalReviewedMemoryPromotionRejected,
    ExternalReviewedMemoryPromotionService,
    ExternalReviewedMemoryStore,
)
from server.ai_runtime.external_reviewed_memory_retrieval import (
    ExternalReviewedMemoryRetrievalRejected,
    ExternalReviewedMemoryRetrievalStore,
    HumanExternalReviewedMemoryRetrievalService,
)
from server.ai_runtime.karkinos_source import CaptureProjectionReaders
from server.ai_runtime.memory_informed_analysis import (
    HumanMemoryInformedFixtureAnalysisService,
    MemoryInformedAnalysisRejected,
    MemoryInformedAnalysisStore,
)
from server.ai_runtime.memory_retrieval import (
    HumanReviewedMemoryRetrievalService,
    ReviewedMemoryRetrievalRejected,
    ReviewedMemoryRetrievalStore,
)
from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
    PROVIDER_CALL_COMPLETION_GUARD_SECONDS,
    provider_send_admission_for,
)
from server.ai_runtime.provider_connectivity import (
    ConnectivityConfigurationError,
    ProviderConnectivityAuditStore,
    ProviderConnectivityService,
    load_provider_connectivity_settings,
)
from server.ai_runtime.store import AiAuditStore
from server.ai_runtime.strategy_research import (
    StrategyResearchAuditStore,
    StrategyResearchService,
)
from server.ai_runtime.task_analysis import (
    HumanResearchTaskFixtureAnalysisService,
    ResearchTaskAnalysisRejected,
    ResearchTaskAnalysisStore,
)
from server.ai_runtime.tasks import (
    HumanResearchTaskService,
    ResearchTaskRejected,
    ResearchTaskStore,
)
from server.dependencies import AppState
from server.persistence.database_identity import require_database_path
from server.projections import portfolio_application
from server.services import account_strategy_projections, operations_projection
from server.services.ai_context_capture_factory import (
    build_human_context_capture_service as _build_context_capture_service,
)
from server.services.strategy_research_factory import (
    build_strategy_research_write_service as _build_strategy_research_write_service,
)

if TYPE_CHECKING:
    from server.services.ai_shadow_research_automation import (
        AiShadowResearchAutomationService,
    )


def build_capture_projection_readers() -> CaptureProjectionReaders:
    """Bind the canonical persisted projections consumed by AI capture."""
    return CaptureProjectionReaders(
        portfolio_snapshot=portfolio_application.build_portfolio_snapshot,
        account_state=portfolio_application.build_account_state_response,
        operations_today=operations_projection.build_today_operations_payload,
        current_valuation_snapshot=portfolio_application.current_valuation_snapshot,
        strategy_contribution_report=(
            account_strategy_projections.build_contribution_report
        ),
    )


def build_human_context_capture_service(
    state: AppState,
) -> HumanResearchContextCaptureService:
    """Build audit-only capture services on the application's SQLite database."""
    return _build_context_capture_service(
        state,
        projection_readers=build_capture_projection_readers(),
    )


def build_provider_connectivity_service(state: AppState) -> ProviderConnectivityService:
    """Build the explicit network probe on AI-only audit tables."""
    db_path = _database_path(
        state.db,
        ConnectivityConfigurationError("database path is unavailable"),
    )
    settings = load_provider_connectivity_settings(state.require_config())
    ai_store = AiAuditStore(db_path)
    audit_store = ProviderConnectivityAuditStore(db_path)
    ai_store.init()
    audit_store.init()
    return ProviderConnectivityService(
        settings=settings,
        audit_store=audit_store,
        ai_store=ai_store,
        provider_send_admission=provider_send_admission_for(
            settings.provider_id,
            endpoint_origin=settings.endpoint_origin,
            minimum_runway=timedelta(
                seconds=(
                    settings.timeout_seconds + PROVIDER_CALL_COMPLETION_GUARD_SECONDS
                )
            ),
        ),
    )


def build_human_research_task_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanResearchTaskService:
    """Build the model-free research task audit service on application SQLite."""
    db_path = _database_path(
        state.db,
        ResearchTaskRejected("database path is unavailable"),
    )
    evidence_repository = CanonicalEvidenceRepository(db_path)
    context_store = AiAuditStore(db_path)
    capture_store = ContextCaptureAuditStore(db_path)
    task_store = ResearchTaskStore(db_path)
    if initialize:
        evidence_repository.init()
        context_store.init()
        capture_store.init()
        task_store.init()
    return HumanResearchTaskService(
        evidence_repository=evidence_repository,
        context_store=context_store,
        capture_store=capture_store,
        task_store=task_store,
        now=_utc_now,
    )


def build_human_fixture_analysis_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanResearchTaskFixtureAnalysisService:
    """Build the explicit, network-free fixture workflow boundary."""
    db_path = _database_path(
        state.db,
        ResearchTaskAnalysisRejected("database path is unavailable"),
    )
    evidence_repository = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    capture_store = ContextCaptureAuditStore(db_path)
    task_store = ResearchTaskStore(db_path)
    analysis_store = ResearchTaskAnalysisStore(db_path)
    if initialize:
        evidence_repository.init()
        ai_store.init()
        capture_store.init()
        task_store.init()
        analysis_store.init()
    task_service = HumanResearchTaskService(
        evidence_repository=evidence_repository,
        context_store=ai_store,
        capture_store=capture_store,
        task_store=task_store,
        now=_utc_now,
    )
    return HumanResearchTaskFixtureAnalysisService(
        ai_store=ai_store,
        evidence_repository=evidence_repository,
        task_store=task_store,
        task_service=task_service,
        analysis_store=analysis_store,
        now=_utc_now,
    )


def build_human_analysis_review_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanAnalysisReviewService:
    """Build the non-authoritative, human-only analysis review boundary."""
    db_path = _database_path(
        state.db,
        AnalysisReviewRejected("database path is unavailable"),
    )
    analysis_service = build_human_fixture_analysis_service(
        state,
        initialize=initialize,
    )
    review_store = AnalysisReviewStore(db_path)
    if initialize:
        review_store.init()
    return HumanAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=review_store,
        now=_utc_now,
    )


def build_human_reviewed_memory_retrieval_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanReviewedMemoryRetrievalService:
    """Build explicit reviewed-memory retrieval without a provider or AI tool."""
    db_path = _database_path(
        state.db,
        ReviewedMemoryRetrievalRejected("database path is unavailable"),
    )
    analysis_service = build_human_fixture_analysis_service(
        state,
        initialize=initialize,
    )
    review_store = AnalysisReviewStore(db_path)
    retrieval_store = ReviewedMemoryRetrievalStore(db_path)
    if initialize:
        review_store.init()
        retrieval_store.init()
    review_service = HumanAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=review_store,
        now=_utc_now,
    )
    return HumanReviewedMemoryRetrievalService(
        review_service=review_service,
        analysis_service=analysis_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        retrieval_store=retrieval_store,
        now=_utc_now,
    )


def build_human_memory_informed_analysis_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanMemoryInformedFixtureAnalysisService:
    """Build the fixture-only consumer of an already-reviewed retrieval."""
    db_path = _database_path(
        state.db,
        MemoryInformedAnalysisRejected("database path is unavailable"),
    )
    retrieval_service = build_human_reviewed_memory_retrieval_service(
        state,
        initialize=initialize,
    )
    store = MemoryInformedAnalysisStore(db_path)
    if initialize:
        store.init()
    return HumanMemoryInformedFixtureAnalysisService(
        retrieval_service=retrieval_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        analysis_store=store,
        now=_utc_now,
    )


def build_human_external_memory_analysis_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanExternalMemoryAnalysisService:
    """Build an explicit external edge with lazy credential loading."""
    db_path = _database_path(
        state.db,
        ConnectivityConfigurationError("database path is unavailable"),
    )
    retrieval_service = build_human_reviewed_memory_retrieval_service(
        state,
        initialize=initialize,
    )
    store = ExternalMemoryAnalysisStore(db_path)
    if initialize:
        store.init()
    return HumanExternalMemoryAnalysisService(
        settings_loader=lambda: load_provider_connectivity_settings(
            state.require_config()
        ),
        retrieval_service=retrieval_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        analysis_store=store,
        now=_utc_now,
        provider_send_admission_factory=lambda provider_id, endpoint_origin: provider_send_admission_for(
            provider_id,
            endpoint_origin=endpoint_origin,
            minimum_runway=timedelta(
                seconds=(180 + PROVIDER_CALL_COMPLETION_GUARD_SECONDS)
            ),
        ),
    )


def build_human_external_analysis_review_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanExternalAnalysisReviewService:
    """Build the local review edge without loading provider credentials."""
    db_path = _database_path(
        state.db,
        ExternalAnalysisReviewRejected("database path is unavailable"),
    )
    analysis_service = build_human_external_memory_analysis_service(
        state,
        initialize=initialize,
    )
    review_store = ExternalAnalysisReviewStore(db_path)
    if initialize:
        review_store.init()
    return HumanExternalAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=review_store,
        now=_utc_now,
    )


def build_external_reviewed_memory_promotion_service(
    state: AppState,
    *,
    initialize: bool,
) -> ExternalReviewedMemoryPromotionService:
    """Build the local-only promotion edge without model credentials."""
    db_path = _database_path(
        state.db,
        ExternalReviewedMemoryPromotionRejected("database path is unavailable"),
    )
    review_service = build_human_external_analysis_review_service(
        state,
        initialize=initialize,
    )
    promotion_store = ExternalReviewedMemoryStore(db_path)
    if initialize:
        promotion_store.init()
    return ExternalReviewedMemoryPromotionService(
        review_service=review_service,
        ai_store=AiAuditStore(db_path),
        promotion_store=promotion_store,
        now=_utc_now,
    )


def build_human_external_reviewed_memory_retrieval_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanExternalReviewedMemoryRetrievalService:
    """Build versioned local retrieval without loading credentials."""
    db_path = _database_path(
        state.db,
        ExternalReviewedMemoryRetrievalRejected("database path is unavailable"),
    )
    promotion_service = build_external_reviewed_memory_promotion_service(
        state,
        initialize=initialize,
    )
    legacy_retrieval_service = build_human_reviewed_memory_retrieval_service(
        state,
        initialize=False,
    )
    retrieval_store = ExternalReviewedMemoryRetrievalStore(db_path)
    if initialize:
        retrieval_store.init()
    return HumanExternalReviewedMemoryRetrievalService(
        promotion_service=promotion_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        current_context_validator=legacy_retrieval_service._validate_current_context,
        retrieval_store=retrieval_store,
        now=_utc_now,
    )


def build_human_external_promoted_memory_analysis_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanExternalPromotedMemoryAnalysisService:
    """Build a lazy external edge over versioned promoted memory."""
    db_path = _database_path(
        state.db,
        ConnectivityConfigurationError("database path is unavailable"),
    )
    retrieval_service = build_human_external_reviewed_memory_retrieval_service(
        state,
        initialize=initialize,
    )
    store = ExternalPromotedMemoryAnalysisStore(db_path)
    if initialize:
        store.init()
    analysis_service = HumanExternalMemoryAnalysisService(
        settings_loader=lambda: load_provider_connectivity_settings(
            state.require_config()
        ),
        retrieval_service=retrieval_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        analysis_store=store,
        now=_utc_now,
        provider_send_admission_factory=lambda provider_id, endpoint_origin: provider_send_admission_for(
            provider_id,
            endpoint_origin=endpoint_origin,
            minimum_runway=timedelta(
                seconds=(180 + PROVIDER_CALL_COMPLETION_GUARD_SECONDS)
            ),
        ),
    )
    return HumanExternalPromotedMemoryAnalysisService(
        analysis_service=analysis_service,
        retrieval_service=retrieval_service,
    )


def build_human_external_promoted_memory_analysis_review_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanExternalPromotedMemoryAnalysisReviewService:
    """Build a local review edge without loading provider credentials."""
    db_path = _database_path(
        state.db,
        ExternalPromotedMemoryAnalysisReviewRejected("database path is unavailable"),
    )
    analysis_service = build_human_external_promoted_memory_analysis_service(
        state,
        initialize=initialize,
    )
    review_store = ExternalPromotedMemoryAnalysisReviewStore(db_path)
    if initialize:
        review_store.init()
    return HumanExternalPromotedMemoryAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=review_store,
        now=_utc_now,
    )


def build_external_promoted_analysis_memory_promotion_service(
    state: AppState,
    *,
    initialize: bool,
) -> ExternalPromotedAnalysisMemoryPromotionService:
    """Build the local-only promoted-analysis memory boundary."""
    db_path = _database_path(
        state.db,
        ExternalPromotedAnalysisMemoryRejected("database path is unavailable"),
    )
    review_service = build_human_external_promoted_memory_analysis_review_service(
        state,
        initialize=initialize,
    )
    promotion_store = ExternalPromotedAnalysisMemoryStore(db_path)
    if initialize:
        promotion_store.init()
    return ExternalPromotedAnalysisMemoryPromotionService(
        review_service=review_service,
        ai_store=AiAuditStore(db_path),
        promotion_store=promotion_store,
        now=_utc_now,
    )


def build_human_external_promoted_analysis_memory_retrieval_service(
    state: AppState,
    *,
    initialize: bool,
) -> HumanExternalPromotedAnalysisMemoryRetrievalService:
    """Build the local-only promoted-analysis memory retrieval boundary."""
    db_path = _database_path(
        state.db,
        ExternalPromotedAnalysisMemoryRetrievalRejected("database path is unavailable"),
    )
    promotion_service = build_external_promoted_analysis_memory_promotion_service(
        state,
        initialize=initialize,
    )
    legacy_retrieval_service = build_human_reviewed_memory_retrieval_service(
        state,
        initialize=False,
    )
    retrieval_store = ExternalPromotedAnalysisMemoryRetrievalStore(db_path)
    if initialize:
        retrieval_store.init()
    return HumanExternalPromotedAnalysisMemoryRetrievalService(
        promotion_service=promotion_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        current_context_validator=legacy_retrieval_service._validate_current_context,
        retrieval_store=retrieval_store,
        now=_utc_now,
    )


def build_external_backtest_report_service(
    state: AppState,
) -> HumanExternalBacktestReportService:
    """Build the explicit external boundary on AI-only audit storage."""
    db_path = _database_path(
        state.db,
        ConnectivityConfigurationError("database path is unavailable"),
    )
    evidence_repository = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    report_store = ExternalBacktestReportAuditStore(db_path)
    evidence_repository.init()
    ai_store.init()
    report_store.init()
    settings = load_provider_connectivity_settings(state.require_config())
    return HumanExternalBacktestReportService(
        settings=settings,
        capture_service=build_human_context_capture_service(state),
        evidence_repository=evidence_repository,
        ai_store=ai_store,
        report_store=report_store,
        provider_send_admission=provider_send_admission_for(
            settings.provider_id,
            endpoint_origin=settings.endpoint_origin,
            minimum_runway=timedelta(
                seconds=(180 + PROVIDER_CALL_COMPLETION_GUARD_SECONDS)
            ),
        ),
    )


def build_strategy_research_write_service(
    state: AppState,
    *,
    external: bool,
) -> StrategyResearchService:
    return _build_strategy_research_write_service(
        state,
        external=external,
        capture_service=build_human_context_capture_service(state),
    )


def build_strategy_research_read_service(state: AppState) -> StrategyResearchService:
    """Build without init, data storage, config, provider, or secrets."""
    db_path = _database_path(
        state.db,
        ConnectivityConfigurationError("database path is unavailable"),
    )
    return StrategyResearchService(
        db=state.db,
        db_path=db_path,
        settings=None,
        capture_service=None,  # type: ignore[arg-type]
        evidence_repository=CanonicalEvidenceRepository(db_path),
        ai_store=AiAuditStore(db_path),
        research_store=StrategyResearchAuditStore(db_path),
        data_store=None,  # type: ignore[arg-type]
    )


def build_shadow_research_write_service(
    state: AppState,
) -> AiShadowResearchAutomationService:
    if state.db is None:
        raise ConnectivityConfigurationError("database is not initialized")
    from server.services.ai_shadow_research_automation import (
        build_ai_shadow_research_automation_service,
    )

    return build_ai_shadow_research_automation_service(
        state,
        research_service_builder=lambda external: build_strategy_research_write_service(
            state,
            external=external,
        ),
    )


def build_shadow_research_read_service(
    state: AppState,
) -> AiShadowResearchAutomationService:
    """Build a read projection without initializing tables or market storage."""
    from server.services.ai_shadow_research_automation import (
        AiShadowResearchAutomationService,
        ShadowResearchStore,
    )

    return AiShadowResearchAutomationService(
        state=state,
        store=ShadowResearchStore(
            _database_path(
                state.db,
                ConnectivityConfigurationError("database path is unavailable"),
            )
        ),
        data_store=None,  # type: ignore[arg-type]
        provider_call_window_policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
    )


def _database_path(db: object | None, missing_error: Exception) -> Path:
    return require_database_path(db, missing_error)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
