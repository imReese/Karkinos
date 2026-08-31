"""Composition root for after-close AI shadow research automation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from data.store import DataStore
from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
)
from server.ai_runtime.strategy_research import StrategyResearchService
from server.bootstrap import resolve_data_dir
from server.dependencies import AppState
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.persistence.database_identity import require_database_path
from server.services.reviewed_fee_schedule import resolve_reviewed_fee_schedule

ServiceT = TypeVar("ServiceT")


def compose_ai_shadow_research_automation_service(
    state: AppState,
    *,
    research_service_builder: Callable[[bool], StrategyResearchService],
    service_type: Callable[..., ServiceT],
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
    )
