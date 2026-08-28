"""Application-level factory for evidence-bound strategy research services."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from data.store import DataStore
from server.ai_runtime.capture import HumanResearchContextCaptureService
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.provider_call_window import (
    PROVIDER_CALL_COMPLETION_GUARD_SECONDS,
    provider_send_admission_for,
)
from server.ai_runtime.provider_connectivity import (
    ConnectivityConfigurationError,
    ProviderConnectivitySettings,
    load_provider_connectivity_settings,
)
from server.ai_runtime.store import AiAuditStore
from server.ai_runtime.strategy_research import (
    StrategyResearchAuditStore,
    StrategyResearchService,
)
from server.bootstrap import resolve_data_dir
from server.db import AppDatabase
from server.dependencies import AppState
from server.persistence.database_identity import require_database_path

DEFAULT_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS = 180.0
DEEPSEEK_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS = 600.0


def build_strategy_research_write_service(
    state: AppState,
    *,
    external: bool,
    capture_service: HumanResearchContextCaptureService,
) -> StrategyResearchService:
    """Build the mutation-capable AI audit boundary from explicit dependencies."""
    if state.db is None:
        raise ConnectivityConfigurationError("database is not initialized")
    db_path = database_path(state.db)
    evidence_repository = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    research_store = StrategyResearchAuditStore(db_path)
    evidence_repository.init()
    ai_store.init()
    research_store.init()
    settings = (
        load_provider_connectivity_settings(state.require_config())
        if external
        else None
    )
    from server.services.reviewed_fee_schedule import resolve_reviewed_fee_schedule

    model_timeout_seconds = strategy_research_model_timeout_seconds(settings)
    return StrategyResearchService(
        db=state.db,
        db_path=db_path,
        settings=settings,
        capture_service=capture_service,
        evidence_repository=evidence_repository,
        ai_store=ai_store,
        research_store=research_store,
        data_store=DataStore(resolve_data_dir()),
        model_timeout_seconds=model_timeout_seconds,
        provider_send_admission=(
            provider_send_admission_for(
                settings.provider_id,
                minimum_runway=timedelta(
                    seconds=(
                        model_timeout_seconds + PROVIDER_CALL_COMPLETION_GUARD_SECONDS
                    )
                ),
            )
            if settings is not None
            else None
        ),
        reviewed_fee_schedule_resolver=lambda **kwargs: resolve_reviewed_fee_schedule(
            state,
            **kwargs,
        ),
    )


def strategy_research_model_timeout_seconds(
    settings: ProviderConnectivitySettings | None,
) -> float:
    """Allow the configured DeepSeek research call up to ten minutes."""
    if settings is not None and settings.provider_id.strip().casefold() == "deepseek":
        return DEEPSEEK_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS
    return DEFAULT_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS


def database_path(db: AppDatabase | None) -> Path:
    return require_database_path(
        db,
        ConnectivityConfigurationError("database path is unavailable"),
    )
