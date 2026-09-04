"""Composition root for after-close AI shadow research automation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from analytics.dataset_snapshot import verify_backtest_dataset_snapshot_replay
from data.store import DataStore
from server.ai_runtime.capture import ContextCaptureAuditStore
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
)
from server.ai_runtime.store import AiAuditStore
from server.ai_runtime.strategy_research import (
    StrategyResearchAuditStore,
    StrategyResearchService,
)
from server.bootstrap import resolve_data_dir
from server.dependencies import AppState
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.persistence.ai_shadow_research_worker_jobs import (
    AiShadowResearchWorkerJobStore,
)
from server.persistence.database_identity import require_database_path
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)
from server.services.reviewed_fee_schedule import (
    build_reviewed_fee_schedule_review_status,
    resolve_reviewed_fee_schedule,
)

ServiceT = TypeVar("ServiceT")


def compose_ai_shadow_research_job_scheduler(
    state: AppState,
    *,
    service_type: Callable[..., ServiceT],
) -> ServiceT:
    """Wire provider-free scheduler admission to the durable worker queue."""

    return service_type(
        state=state,
        store=AiShadowResearchWorkerJobStore(
            require_database_path(
                state.require_database(),
                RuntimeError("database is not initialized"),
            )
        ),
    )


def compose_ai_shadow_research_worker(
    state: AppState,
    *,
    service_type: Callable[..., ServiceT],
) -> ServiceT:
    """Wire the non-HTTP worker to its durable lease store."""

    return service_type(
        state=state,
        store=AiShadowResearchWorkerJobStore(
            require_database_path(
                state.require_database(),
                RuntimeError("database is not initialized"),
            )
        ),
    )


def read_ai_shadow_research_worker_status(state: AppState) -> dict[str, Any]:
    """Compose one provider-free worker queue projection."""

    from server.services.ai_shadow_research_worker_status import (
        build_ai_shadow_research_worker_status,
    )

    return build_ai_shadow_research_worker_status(
        AiShadowResearchWorkerJobStore(
            require_database_path(
                state.require_database(),
                RuntimeError("database is not initialized"),
            )
        )
    )


def compose_ai_shadow_research_automation_service(
    state: AppState,
    *,
    research_service_builder: Callable[[bool], StrategyResearchService],
    service_type: Callable[..., ServiceT],
    execution_guard: Callable[[], None] | None = None,
) -> ServiceT:
    """Initialize persistence and wire all explicit runtime dependencies."""

    store = ShadowResearchStore(
        require_database_path(
            state.require_database(),
            RuntimeError("database is not initialized"),
        )
    )
    store.init()
    return service_type(
        state=state,
        store=store,
        data_store=DataStore(resolve_data_dir()),
        research_service_builder=research_service_builder,
        reviewed_fee_schedule_resolver=lambda **kwargs: resolve_reviewed_fee_schedule(
            state, **kwargs
        ),
        provider_call_window_policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
        execution_guard=execution_guard,
    )


def compose_ai_shadow_research_qualification_service(
    state: AppState,
    *,
    capture_service_factory: Callable[[], Any],
    account_identity_reader: Callable[[], Any],
    service_type: Callable[..., ServiceT],
) -> ServiceT:
    """Wire provider-free qualification to current persisted account evidence."""

    db = state.require_database()
    db_path = require_database_path(
        db,
        RuntimeError("database is not initialized"),
    )
    if not state.ai_shadow_research_qualification_persistence_ready:
        raise RuntimeError("qualification persistence is not initialized")
    data_store = state.ai_shadow_research_qualification_data_store
    if data_store is None:
        raise RuntimeError("qualification market data store is not initialized")
    store = ShadowResearchStore(db_path)
    daily_artifacts = DailyStrategyArtifactStore(
        db_path=db_path,
        backup_root=store.path.parent / "strategy-research-backups",
    )
    research_store = StrategyResearchAuditStore(db_path)
    data_root = resolve_data_dir()
    evidence_repository = CanonicalEvidenceRepository(db_path)
    return service_type(
        db=db,
        store=store,
        daily_artifact_store=daily_artifacts,
        research_store=research_store,
        data_store=data_store,
        capture_service=None,
        capture_service_factory=capture_service_factory,
        account_identity_reader=account_identity_reader,
        account_evidence_reader=evidence_repository.get,
        reviewed_fee_identity_reader=lambda selection: (
            build_reviewed_fee_schedule_review_status(
                state,
                as_of_date=selection.end_date,
            )
        ),
        dataset_snapshot_replay_reader=lambda snapshot: (
            verify_backtest_dataset_snapshot_replay(
                snapshot,
                store_root=data_root,
            )
        ),
        reviewed_fee_schedule_resolver=lambda **kwargs: resolve_reviewed_fee_schedule(
            state, **kwargs
        ),
    )


def initialize_ai_shadow_research_qualification_persistence(
    state: AppState,
) -> None:
    """Explicitly initialize qualification-owned stores during app startup."""

    db_path = require_database_path(
        state.require_database(),
        RuntimeError("database is not initialized"),
    )
    store = ShadowResearchStore(db_path)
    store.init()
    DailyStrategyArtifactStore(
        db_path=db_path,
        backup_root=store.path.parent / "strategy-research-backups",
    ).init()
    StrategyResearchAuditStore(db_path).init()
    CanonicalEvidenceRepository(db_path).init()
    AiAuditStore(db_path).init()
    ContextCaptureAuditStore(db_path).init()
    state.ai_shadow_research_qualification_data_store = DataStore(resolve_data_dir())
    state.ai_shadow_research_qualification_persistence_ready = True
